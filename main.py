# -*- coding: utf-8 -*-
"""
ربات طب سنتی و اسلامی — دکتر حکیم
نسخه نهایی: ۸۸ سوال + هوش مصنوعی + باشگاه مشتریان + پنل مدیریت
"""

import os
import json
import uuid
import secrets
import io
import jdatetime
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Boolean,
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    JSON,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from passlib.hash import bcrypt
from openai import OpenAI
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ============================================================
# اتصال به Metis AI
# ============================================================
METIS_API_KEY = os.getenv("METIS_API_KEY", "")
AI_MODEL = "gpt-4o-mini"

if METIS_API_KEY and len(METIS_API_KEY) > 20:
    ai_client = OpenAI(
        base_url="https://api.metisai.ir/openai/v1",
        api_key=METIS_API_KEY,
    )
    AI_ENABLED = True
    print("✅ Metis AI متصل شد")
else:
    ai_client = None
    AI_ENABLED = False
    print("⚠️ METIS_API_KEY تنظیم نشده - از پاسخ‌های پیش‌فرض استفاده می‌شود")


# ============================================================
# بارگذاری پایگاه دانش (فقط برای fallback)
# ============================================================
KB_PATH = "knowledge.json"
try:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        _knowledge_data = json.load(f)
        DISEASE_KNOWLEDGE = _knowledge_data.get("diseases", {})
    DISEASE_KEYWORDS = {
        name: data.get("keywords", [name]) for name, data in DISEASE_KNOWLEDGE.items()
    }
    print(f"✅ {len(DISEASE_KNOWLEDGE)} بیماری (برای fallback) بارگذاری شد")
except FileNotFoundError:
    print("⚠️ فایل knowledge.json پیدا نشد - فقط از AI استفاده می‌شود")
    DISEASE_KNOWLEDGE = {}
    DISEASE_KEYWORDS = {}
except json.JSONDecodeError as e:
    print(f"❌ خطا در knowledge.json: {e}")
    DISEASE_KNOWLEDGE = {}
    DISEASE_KEYWORDS = {}


# ============================================================
# تنظیمات دیتابیس (SQLite)
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teb_local.db")

# تنظیمات مخصوص هر دیتابیس (SQLite برای لوکال، PostgreSQL برای لیارا)
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
VISIT_PRICE = 100_000
REFERRALS_NEEDED = 5
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@1403")
admin_sessions = {}


# ============================================================
# باشگاه مشتریان - ۶ سطح
# ============================================================
LOYALTY_TIERS = {
    "newcomer": {
        "min_visits": 0,
        "discount": 0,
        "name": "تازه‌وارد",
        "icon": "🌱",
        "color": "#86efac",
        "description": "اولین قدم را برداشتی!",
    },
    "herbalist": {
        "min_visits": 2,
        "discount": 10,
        "name": "گیاه‌شناس",
        "icon": "🌿",
        "color": "#4ade80",
        "description": "قدم در راه حکمت گذاشتی",
    },
    "young_sage": {
        "min_visits": 5,
        "discount": 15,
        "name": "حکیم جوان",
        "icon": "🌸",
        "color": "#22c55e",
        "description": "دانش تو در حال شکوفایی است",
    },
    "skilled_sage": {
        "min_visits": 10,
        "discount": 25,
        "name": "حکیم ماهر",
        "icon": "🍃",
        "color": "#16a34a",
        "description": "به استادی نزدیک می‌شوی",
    },
    "grand_sage": {
        "min_visits": 20,
        "discount": 40,
        "name": "حکیم بزرگ",
        "icon": "🌟",
        "color": "#15803d",
        "description": "تو یک حکیم واقعی هستی!",
    },
    "master_sage": {
        "min_visits": 50,
        "discount": 50,
        "name": "استاد حکیم",
        "icon": "💎",
        "color": "#059669",
        "description": "افسانه‌ای در عالم حکمت!",
    },
}

REFERRAL_REWARDS = [
    {"count": 1, "type": "credit_10", "value": 10, "label": "کد تخفیف ۱۰٪"},
    {"count": 3, "type": "free_visit", "value": 1, "label": "۱ ویزیت رایگان"},
    {
        "count": 5,
        "type": "tier_boost",
        "value": "young_sage",
        "label": "ارتقا به 🌸 حکیم جوان",
        "extra_free": 1,
    },
    {
        "count": 10,
        "type": "tier_boost",
        "value": "skilled_sage",
        "label": "ارتقا به 🍃 حکیم ماهر",
        "extra_free": 3,
    },
    {
        "count": 20,
        "type": "tier_boost",
        "value": "master_sage",
        "label": "ارتقا به 💎 استاد حکیم",
        "extra_free": 5,
    },
]


def calculate_tier(completed_visits):
    tier = "newcomer"
    for t, info in LOYALTY_TIERS.items():
        if completed_visits >= info["min_visits"]:
            tier = t
    return tier


def get_tier_info(tier):
    return LOYALTY_TIERS.get(tier, LOYALTY_TIERS["newcomer"])


def next_tier_info(completed_visits):
    for t, info in LOYALTY_TIERS.items():
        if completed_visits < info["min_visits"]:
            return {
                "tier": t,
                "name": info["name"],
                "icon": info["icon"],
                "visits_needed": info["min_visits"] - completed_visits,
                "discount": info["discount"],
                "description": info["description"],
            }
    return None


def apply_discount(base_amount, tier):
    discount_pct = get_tier_info(tier)["discount"]
    discount = base_amount * discount_pct // 100
    return {
        "original": base_amount,
        "discount_percent": discount_pct,
        "discount_amount": discount,
        "final": base_amount - discount,
    }


def get_next_referral_milestone(confirmed_count):
    for r in REFERRAL_REWARDS:
        if confirmed_count < r["count"]:
            return {
                "count": r["count"],
                "remaining": r["count"] - confirmed_count,
                "label": r["label"],
            }
    return None


def apply_referral_boost(user, confirmed_referrals):
    boost_applied = None
    for r in REFERRAL_REWARDS:
        if r["type"] == "tier_boost" and confirmed_referrals >= r["count"]:
            target_tier = r["value"]
            current_tier = user.loyalty_tier or "newcomer"
            current_rank = (
                list(LOYALTY_TIERS.keys()).index(current_tier)
                if current_tier in LOYALTY_TIERS
                else 0
            )
            target_rank = (
                list(LOYALTY_TIERS.keys()).index(target_tier)
                if target_tier in LOYALTY_TIERS
                else 0
            )
            if target_rank > current_rank:
                user.loyalty_tier = target_tier
                user.free_credits = (user.free_credits or 0) + r.get("extra_free", 0)
                boost_applied = {
                    "tier": target_tier,
                    "tier_name": get_tier_info(target_tier)["name"],
                    "tier_icon": get_tier_info(target_tier)["icon"],
                    "extra_free": r.get("extra_free", 0),
                }
    return boost_applied


# ============================================================
# تبدیل تاریخ میلادی به شمسی
# ============================================================
def to_shamsi(dt):
    if not dt:
        return "—"
    try:
        jd = jdatetime.datetime.fromgregorian(datetime=dt)
        month_names = [
            "فروردین",
            "اردیبهشت",
            "خرداد",
            "تیر",
            "مرداد",
            "شهریور",
            "مهر",
            "آبان",
            "آذر",
            "دی",
            "بهمن",
            "اسفند",
        ]
        return f"{jd.day} {month_names[jd.month - 1]} {jd.year} — {jd.hour:02d}:{jd.minute:02d}"
    except Exception:
        return "—"


# ============================================================
# مدل‌های دیتابیس
# ============================================================
class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    phone = Column(String(11), unique=True, nullable=False, index=True)
    referral_code = Column(String(20), unique=True, nullable=False, index=True)
    referred_by = Column(String(20))
    referral_confirmed = Column(Boolean, default=False)
    confirmed_referrals = Column(Integer, default=0)
    free_credits = Column(Integer, default=0)
    loyalty_tier = Column(String(20), default="newcomer")
    completed_visits = Column(Integer, default=0)
    total_paid = Column(Integer, default=0)
    total_free = Column(Integer, default=0)
    total_spent = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Visit(Base):
    __tablename__ = "visits"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"))
    visit_number = Column(Integer, nullable=False)
    must_pay = Column(Boolean, default=True)
    used_free_credit = Column(Boolean, default=False)
    payment_status = Column(String(20), default="pending")
    payment_amount = Column(BigInteger, default=0)
    final_amount = Column(BigInteger, default=0)
    payment_ref = Column(String(100))
    status = Column(String(20), default="in_progress")
    session_data = Column(JSON)
    progress_step = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class Admin(Base):
    __tablename__ = "admins"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"))
    visit_id = Column(String(36))
    feedback_type = Column(String(50))
    feedback_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# توابع کمکی دیتابیس
# ============================================================
def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        exists = db.query(Admin).filter_by(username="superadmin").first()
        if not exists:
            admin = Admin(
                username="superadmin",
                password_hash=bcrypt.hash("change_me_12345"),
                full_name="مدیر ارشد",
                role="super_admin",
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


def generate_referral_code(name):
    base = "".join([c for c in name.upper() if c.isalpha()])[:4] or "USER"
    for _ in range(20):
        code = f"{base}{secrets.randbelow(9000) + 1000}"
        db = SessionLocal()
        try:
            if not db.query(User).filter_by(referral_code=code).first():
                return code
        finally:
            db.close()
    return f"U{uuid.uuid4().hex[:6].upper()}"


def register_user(name, phone, referral_code_used=None):
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(phone=phone).first()
        if existing:
            return {"user": existing, "is_returning": True, "referral_applied": False}

        my_code = generate_referral_code(name)
        referred_by = None
        if referral_code_used:
            code = referral_code_used.strip().upper()
            referrer = db.query(User).filter_by(referral_code=code).first()
            if referrer and referrer.phone != phone:
                referred_by = code

        user = User(
            name=name, phone=phone, referral_code=my_code, referred_by=referred_by
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {
            "user": user,
            "is_returning": False,
            "referral_applied": referred_by is not None,
        }
    finally:
        db.close()


# ============================================================
# موتور تشخیص مزاج و BMI
# ============================================================
def detect_mizaj(answers: dict) -> dict:
    score = {"گرم": 0, "سرد": 0, "تر": 0, "خشک": 0}

    temp = answers.get("body_temp", "")
    if "گرم" in temp:
        score["گرم"] += 3
    elif "سرد" in temp:
        score["سرد"] += 3

    hands = answers.get("hands_temp", "")
    if "گرم" in hands and "خشک" in hands:
        score["گرم"] += 2
        score["خشک"] += 2
    elif "گرم" in hands and "مرطوب" in hands:
        score["گرم"] += 2
        score["تر"] += 2
    elif "سرد" in hands and "خشک" in hands:
        score["سرد"] += 2
        score["خشک"] += 2
    elif "سرد" in hands and "مرطوب" in hands:
        score["سرد"] += 2
        score["تر"] += 2

    thirst = answers.get("thirst", "")
    if "خیلی زیاد" in thirst or thirst == "زیاد":
        score["گرم"] += 2
        score["خشک"] += 1
    elif "خیلی کم" in thirst or thirst == "کم":
        score["سرد"] += 2
        score["تر"] += 1

    mood = answers.get("mood", "")
    if "عصبی" in mood:
        score["گرم"] += 2
        score["خشک"] += 2
    elif "آرام" in mood:
        score["سرد"] += 2
        score["تر"] += 1
    elif "مضطرب" in mood:
        score["خشک"] += 2
        score["گرم"] += 1
    elif "غمگین" in mood:
        score["سرد"] += 2
        score["خشک"] += 2

    skin = answers.get("skin_quality", "")
    if "خشک" in skin:
        score["خشک"] += 3
    elif "چرب" in skin:
        score["تر"] += 3
    elif "مخلوط" in skin:
        score["خشک"] += 1
        score["تر"] += 1

    hair = answers.get("hair", "")
    if "خشک" in hair:
        score["خشک"] += 2
    elif "چرب" in hair:
        score["تر"] += 2
    elif "ریزش" in hair:
        score["خشک"] += 1
        score["سرد"] += 1

    sleep_type = answers.get("sleep_type", "")
    if "کم" in sleep_type:
        score["خشک"] += 2
        score["گرم"] += 1
    elif "زیاد" in sleep_type:
        score["تر"] += 2
        score["سرد"] += 1
    elif "بی‌خوابی" in sleep_type:
        score["خشک"] += 3

    stool_shape = answers.get("stool_shape", "")
    if "سفت" in stool_shape:
        score["خشک"] += 3
    elif "شل" in stool_shape:
        score["تر"] += 2
        score["سرد"] += 1

    energy = answers.get("energy", "")
    if "بالا" in energy:
        score["گرم"] += 2
    elif "پایین" in energy:
        score["سرد"] += 2

    appetite = answers.get("appetite", "")
    if "زیاد" in appetite:
        score["گرم"] += 2
    elif "کم" in appetite:
        score["سرد"] += 2

    digestion = answers.get("digestion", "")
    if "سریع" in digestion:
        score["گرم"] += 1
        score["خشک"] += 1
    elif "کند" in digestion:
        score["سرد"] += 2
        score["تر"] += 1
    elif "متغیر" in digestion:
        score["تر"] += 2
        score["سرد"] += 1

    voice = answers.get("voice", "")
    if "بلند" in voice:
        score["گرم"] += 2
    elif "آرام" in voice:
        score["سرد"] += 2

    hot_cold = "گرم" if score["گرم"] > score["سرد"] else "سرد"
    wet_dry = "خشک" if score["خشک"] > score["تر"] else "تر"

    mizaj_map = {
        ("گرم", "خشک"): "صفراوی",
        ("گرم", "تر"): "دموی",
        ("سرد", "تر"): "بلغمی",
        ("سرد", "خشک"): "سوداوی",
    }
    mizaj = mizaj_map.get((hot_cold, wet_dry), "معتدل")
    return {"mizaj": mizaj, "hot_cold": hot_cold, "wet_dry": wet_dry, "score": score}


def calculate_bmi(weight, height_cm):
    try:
        h = float(height_cm) / 100
        bmi = float(weight) / (h * h)
        if bmi < 18.5:
            cat = "کمبود وزن"
        elif bmi < 25:
            cat = "وزن نرمال"
        elif bmi < 30:
            cat = "اضافه وزن"
        else:
            cat = "چاقی"
        return round(bmi, 1), cat
    except Exception:
        return None, "نامشخص"


def detect_disease(complaint_text: str):
    if not complaint_text:
        return None, []
    matches = []
    for disease, keywords in DISEASE_KEYWORDS.items():
        for kw in keywords:
            if kw in complaint_text:
                matches.append(disease)
                break
    return (matches[0] if matches else None), matches


def get_treatment(disease, mizaj):
    if disease not in DISEASE_KNOWLEDGE:
        return None
    kb = DISEASE_KNOWLEDGE[disease]
    return {
        "definition": kb.get("definition", ""),
        "general": kb.get("general", []),
        "herbs": kb.get("herbs", []),
        "mizaj_advice": kb.get("by_mizaj", {}).get(mizaj, "توصیه خاصی ثبت نشده."),
        "spiritual": kb.get("spiritual", []),
    }


# ============================================================
# مدیریت نشست ادمین
# ============================================================
def create_admin_session():
    token = secrets.token_urlsafe(32)
    admin_sessions[token] = datetime.utcnow() + timedelta(hours=24)
    return token


def check_admin_session(token):
    if not token:
        return False
    expiry = admin_sessions.get(token)
    if not expiry:
        return False
    if expiry < datetime.utcnow():
        admin_sessions.pop(token, None)
        return False
    return True


# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(title="Teb AI - ربات طب سنتی و اسلامی")
from fastapi.responses import FileResponse


@app.get("/terms")
def terms_page():
    return FileResponse("terms.html")


@app.get("/contact")
def contact_page():
    return FileResponse("contact.html")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterInput(BaseModel):
    review_code: str = None
    name: str
    phone: str
    referral_code: str = ""


class AnswerInput(BaseModel):
    question_id: str
    answer: str


class AdminLoginInput(BaseModel):
    password: str


class FeedbackInput(BaseModel):
    user_id: str
    visit_id: str
    feedback_type: str
    feedback_text: str


class ConnectionManager:
    def __init__(self):
        self.active = {}

    async def connect(self, user_id, ws):
        await ws.accept()
        self.active.setdefault(user_id, []).append(ws)

    def disconnect(self, user_id, ws):
        if user_id in self.active:
            self.active[user_id].remove(ws)

    async def send(self, user_id, message):
        for ws in self.active.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.on_event("startup")
def on_startup():
    init_db()


# ============================================================
# صفحه اصلی و چت
# ============================================================
@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    try:
        with open("chat.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>صفحه یافت نشد</h1>", status_code=404)


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    try:
        with open("admin.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>admin.html یافت نشد</h1>", status_code=404)


@app.get("/")
def root():
    return RedirectResponse(url="/chat")


@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================================================
# ثبت‌نام
# ============================================================
@app.post("/register")
async def register(data: RegisterInput):
    if len(data.phone) != 11 or not data.phone.isdigit():
        raise HTTPException(400, "شماره موبایل نامعتبر است")

    result = register_user(data.name, data.phone, data.referral_code)
    user = result["user"]

    db = SessionLocal()
    try:
        in_progress = (
            db.query(Visit).filter_by(user_id=user.id, status="in_progress").first()
        )
        if in_progress:
            visit = in_progress
            resumed = True
        else:
            visit_number = (user.completed_visits or 0) + 1
            review_match = data.review_code == "ZARINPAL-REVIEW-1403"
            has_free_credit = (user.free_credits or 0) > 0

            if review_match:
                must_pay = False
                used_credit = False
                payment_status = "free"
                amount = 0
            elif has_free_credit:
                must_pay = False
                used_credit = True
                payment_status = "free"
                amount = 0
            else:
                must_pay = True
                user_tier = calculate_tier(user.completed_visits or 0)
                discount_info = apply_discount(VISIT_PRICE, user_tier)
                amount = discount_info["final"]
                payment_status = "pending"
                used_credit = False

            visit = Visit(
                user_id=user.id,
                visit_number=visit_number,
                must_pay=must_pay,
                used_free_credit=used_credit,
                payment_status=payment_status,
                payment_amount=amount,
                final_amount=amount,
            )
            db.add(visit)
            db.commit()
            db.refresh(visit)
            resumed = False

        return {
            "user_id": str(user.id),
            "name": user.name,
            "referral_code": user.referral_code,
            "visit_id": str(visit.id),
            "visit_number": visit.visit_number,
            "must_pay": visit.must_pay,
            "payment_status": visit.payment_status,
            "payment_amount": visit.payment_amount,
            "is_returning": result["is_returning"],
            "referral_applied": result["referral_applied"],
            "resumed": resumed,
        }
    finally:
        db.close()


# ============================================================
# سوالات جامع: ۸۸ سوال
# ============================================================
@app.get("/visits/{visit_id}/questions")
def get_questions(visit_id: str):
    questions = [
        # بخش ۱: اطلاعات پایه (۸ سوال)
        {"id": "name", "text": "نام و نام خانوادگی شما؟", "type": "text"},
        {"id": "age", "text": "سن شما چند سال است؟", "type": "number"},
        {
            "id": "gender",
            "text": "جنسیت شما؟",
            "type": "choice",
            "options": ["مرد", "زن"],
        },
        {
            "id": "marital_status",
            "text": "وضعیت تاهل شما؟",
            "type": "choice",
            "options": ["مجرد", "متاهل", "مطلقه", "همسر فوت شده"],
        },
        {
            "id": "children_count",
            "text": "چند فرزند دارید؟ (اگر ندارید، عدد ۰ وارد کنید)",
            "type": "number",
        },
        {
            "id": "children_detail",
            "text": "اگر فرزند دارید، تعداد پسر و دختر را بنویسید. (مثال: ۲ پسر، ۱ دختر)",
            "type": "text",
        },
        {"id": "weight", "text": "وزن شما (کیلوگرم)؟", "type": "number"},
        {"id": "height", "text": "قد شما (سانتی‌متر)؟", "type": "number"},
        # بخش ۲: ظاهر و رنگ‌شناسی (۸ سوال)
        {
            "id": "skin_color",
            "text": "رنگ پوست شما چگونه است؟",
            "type": "choice",
            "options": ["سفید روشن (بور)", "گندمی روشن", "گندمی تیره", "سبزه", "تیره"],
        },
        {
            "id": "skin_quality",
            "text": "کیفیت پوست شما چگونه است؟",
            "type": "choice",
            "options": ["خشک و زبر", "چرب و براق", "نرم و معمولی", "مخلوط"],
        },
        {
            "id": "eye_color",
            "text": "رنگ چشم شما چیست؟",
            "type": "choice",
            "options": ["قهوه‌ای تیره", "قهوه‌ای روشن", "عسلی", "سبز", "آبی/خاکستری"],
        },
        {
            "id": "tongue_color",
            "text": "رنگ زبان شما معمولاً چگونه است؟",
            "type": "choice",
            "options": [
                "صورتی طبیعی",
                "سفید (باردار)",
                "زرد",
                "قرمز تیره",
                "بنفش/تیره",
            ],
        },
        {
            "id": "tongue_moisture",
            "text": "زبان شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["خشک", "مرطوب و خیس", "معمولی", "متغیر"],
        },
        {
            "id": "body_hair",
            "text": "پرپشتی موی بدن شما (به جز سر) چگونه است؟",
            "type": "choice",
            "options": ["پرپشت و زیاد", "متوسط", "کم", "تقریباً بدون مو"],
        },
        {
            "id": "head_hair_density",
            "text": "پرپشتی موی سر شما چگونه است؟",
            "type": "choice",
            "options": ["پرپشت و زیاد", "متوسط", "کم‌پشت", "طاس (کم‌مو)"],
        },
        {
            "id": "nail_quality",
            "text": "وضعیت ناخن‌های شما؟",
            "type": "choice",
            "options": [
                "سالم و محکم",
                "شکننده و لایه‌لایه",
                "لکه سفید دارند",
                "زرد و ضخیم",
                "قاشقی شکل",
            ],
        },
        # بخش ۳: مزاج‌شناسی (۱۴ سوال)
        {
            "id": "body_temp",
            "text": "دمای کلی بدن شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["گرم - زیاد عرق می‌کنم", "سرد - کم عرق می‌کنم", "معتدل"],
        },
        {
            "id": "hands_temp",
            "text": "کف دست‌های شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["گرم و خشک", "گرم و مرطوب", "سرد و خشک", "سرد و مرطوب"],
        },
        {
            "id": "feet_temp",
            "text": "کف پاهای شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["گرم و خشک", "گرم و مرطوب", "سرد و خشک", "سرد و مرطوب"],
        },
        {
            "id": "thirst",
            "text": "میزان تشنگی شما در طول روز؟",
            "type": "choice",
            "options": ["خیلی زیاد", "زیاد", "معمولی", "کم", "خیلی کم"],
        },
        {
            "id": "mood",
            "text": "حال روحی معمول شما؟",
            "type": "choice",
            "options": [
                "عصبی و پرانرژی",
                "آرام و کم‌حرف",
                "مضطرب و نگران",
                "غمگین و بی‌حوصله",
            ],
        },
        {
            "id": "hair",
            "text": "وضعیت موهای سر شما چگونه است؟",
            "type": "choice",
            "options": [
                "خشک، شکننده، بدحالت",
                "چرب و سنگین",
                "ریزش زیاد دارم",
                "معمولی و سالم",
            ],
        },
        {
            "id": "sleep_type",
            "text": "خواب شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["کم و سبک", "زیاد و سنگین", "معمولی", "بی‌خوابی مزمن"],
        },
        {
            "id": "energy",
            "text": "سطح انرژی روزانه شما؟",
            "type": "choice",
            "options": ["بالا و پرانرژی", "پایین و خسته", "متوسط", "متغیر"],
        },
        {
            "id": "appetite",
            "text": "اشتهای شما چگونه است؟",
            "type": "choice",
            "options": ["زیاد و پرخور", "کم و بی‌اشتها", "معمولی", "متغیر"],
        },
        {
            "id": "voice",
            "text": "صدای شما چگونه است؟",
            "type": "choice",
            "options": ["بلند و قوی", "آرام و ضعیف", "معمولی", "خشن و گرفته"],
        },
        {
            "id": "body_build",
            "text": "ساختار بدنی شما؟",
            "type": "choice",
            "options": ["لاغر و استخوانی", "عضلانی و درشت", "چاق و پرگوشت", "متوسط"],
        },
        {
            "id": "pulse",
            "text": "ضربان قلب شما معمولاً چگونه است؟ (تند = بالای ۹۰، کند = زیر ۶۰)",
            "type": "choice",
            "options": [
                "تند و قوی",
                "کند و ضعیف",
                "معمولی (۶۰ تا ۹۰)",
                "نامنظم",
                "نمی‌دانم",
            ],
        },
        {
            "id": "walk_speed",
            "text": "سرعت راه رفتن شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["تند و شتاب‌زده", "کند و آرام", "معمولی", "متغیر"],
        },
        {
            "id": "talking_speed",
            "text": "سرعت صحبت کردن شما؟",
            "type": "choice",
            "options": ["تند و پرشور", "کند و آرام", "معمولی", "متغیر"],
        },
        # بخش ۴: دستگاه گوارش (۸ سوال)
        {
            "id": "digestion",
            "text": "سرعت هضم غذای شما؟",
            "type": "choice",
            "options": ["سریع", "کند", "معمولی", "متغیر"],
        },
        {
            "id": "stool_freq",
            "text": "چند وقت یکبار اجابت مزاج دارید؟",
            "type": "choice",
            "options": [
                "چند بار در روز",
                "روزی ۱ بار",
                "یک روز در میان",
                "کمتر از ۳ بار در هفته",
                "متغیر",
            ],
        },
        {
            "id": "stool_shape",
            "text": "شکل مدفوع شما معمولاً چگونه است؟",
            "type": "choice",
            "options": [
                "سفت و خشک",
                "شل و آبکی",
                "معمولی (قالبی)",
                "باریک و روبان‌مانند",
                "متغیر",
            ],
        },
        {
            "id": "stool_color",
            "text": "رنگ مدفوع شما معمولاً چگونه است؟",
            "type": "choice",
            "options": [
                "قهوه‌ای طبیعی",
                "زرد روشن",
                "تیره/سیاه",
                "رنگ روشن یا سفید",
                "متغیر",
            ],
        },
        {
            "id": "bloating",
            "text": "میزان نفخ و سنگینی معده شما؟",
            "type": "choice",
            "options": ["زیاد - همیشه سنگین", "متوسط", "کم", "تقریباً هیچ"],
        },
        {
            "id": "acid_reflux",
            "text": "آیا ترش کردن، سوزش معده یا رفلاکس دارید؟",
            "type": "choice",
            "options": ["بله، زیاد", "بله، گاهی", "خیر", "فقط بعد از غذاهای خاص"],
        },
        {
            "id": "nausea",
            "text": "آیا تهوع، استفراغ یا سرگیجه دارید؟",
            "type": "choice",
            "options": ["بله، زیاد", "بله، گاهی", "خیر", "فقط صبح‌ها"],
        },
        {
            "id": "mouth_taste",
            "text": "مزه دهان شما معمولاً چگونه است؟",
            "type": "choice",
            "options": ["تلخ", "ترش", "شیرین", "بی‌مزه", "معمولی", "متغیر"],
        },
        # بخش ۵: دفع و تعریق (۵ سوال)
        {
            "id": "urine_color",
            "text": "رنگ ادرار شما معمولاً چگونه است؟",
            "type": "choice",
            "options": [
                "زرد پررنگ",
                "زرد روشن",
                "بی‌رنگ و شفاف",
                "تیره و کدر",
                "خونی",
                "متغیر",
            ],
        },
        {
            "id": "urine_freq",
            "text": "چند بار در روز ادرار می‌کنید؟",
            "type": "choice",
            "options": [
                "بیشتر از ۸ بار",
                "۵ تا ۸ بار",
                "۳ تا ۵ بار",
                "کمتر از ۳ بار",
                "متغیر",
            ],
        },
        {
            "id": "urine_night",
            "text": "آیا شب‌ها برای ادرار بیدار می‌شوید؟",
            "type": "choice",
            "options": ["بیشتر از ۲ بار", "۱ تا ۲ بار", "خیر", "گاهی"],
        },
        {
            "id": "sweating",
            "text": "میزان تعریق شما؟",
            "type": "choice",
            "options": [
                "زیاد - حتی در زمستان",
                "کم - به‌ندرت",
                "معمولی",
                "فقط شب‌ها",
                "متغیر",
            ],
        },
        {
            "id": "body_odor",
            "text": "بوی بدن و دهان شما؟",
            "type": "choice",
            "options": ["بوی تند و نامطبوع", "معمولی", "فقط صبح‌ها", "مشکلی ندارم"],
        },
        # بخش ۶: خواب و ذهن (۵ سوال)
        {
            "id": "sleep_hours",
            "text": "چند ساعت در شب می‌خوابید؟",
            "type": "choice",
            "options": [
                "کمتر از ۵ ساعت",
                "۵ تا ۷ ساعت",
                "۷ تا ۹ ساعت",
                "بیشتر از ۹ ساعت",
                "متغیر",
            ],
        },
        {
            "id": "sleep_quality",
            "text": "کیفیت خواب شما؟",
            "type": "choice",
            "options": [
                "عمیق و راحت",
                "سبک - زود بیدار می‌شوم",
                "کابوس می‌بینم",
                "دیر به خواب می‌روم",
                "متغیر",
            ],
        },
        {
            "id": "memory",
            "text": "وضعیت حافظه و تمرکز شما؟",
            "type": "choice",
            "options": ["خوب و قوی", "ضعیف شده", "متوسط", "متغیر"],
        },
        {
            "id": "stress",
            "text": "سطح استرس و فشار عصبی شما؟",
            "type": "choice",
            "options": ["خیلی زیاد", "متوسط", "کم", "تقریباً هیچ", "متغیر"],
        },
        {
            "id": "anxiety_mood",
            "text": "آیا دچار اضطراب، افسردگی یا وسواس هستید؟",
            "type": "choice",
            "options": [
                "بله، اضطراب شدید",
                "بله، افسردگی",
                "بله، وسواس",
                "خیر، آرام هستم",
            ],
        },
        # بخش ۷: علائم جسمی (۷ سوال)
        {
            "id": "headache",
            "text": "سردرد یا سرگیجه دارید؟",
            "type": "choice",
            "options": ["سردرد مکرر", "سرگیجه", "هم سردرد و هم سرگیجه", "گاهی", "خیر"],
        },
        {
            "id": "pain_location",
            "text": "آیا در بدن خود درد خاصی دارید؟",
            "type": "choice",
            "options": [
                "درد مفاصل و زانو",
                "درد کمر و گردن",
                "درد معده و شکم",
                "درد سینه",
                "گاهی چند جا",
                "خیر",
            ],
        },
        {
            "id": "breathing",
            "text": "وضعیت تنفس شما؟",
            "type": "choice",
            "options": [
                "راحت و عمیق",
                "تنگی نفس",
                "خس‌خس سینه",
                "نفس‌نفس زدن",
                "گاهی کند می‌شود",
            ],
        },
        {
            "id": "vision",
            "text": "وضعیت بینایی و چشم شما؟",
            "type": "choice",
            "options": ["خوب", "ضعیف شده", "خشکی چشم", "اشک‌ریزش زیاد", "تاری دید"],
        },
        {
            "id": "hearing",
            "text": "وضعیت شنوایی شما؟",
            "type": "choice",
            "options": ["خوب", "وزوز گوش", "کم‌شنوایی", "درد گوش"],
        },
        {
            "id": "skin_problems",
            "text": "آیا مشکل پوستی خاصی دارید؟",
            "type": "choice",
            "options": [
                "آکنه و جوش",
                "اگزما و خشکی",
                "لک و پیسی",
                "خارش (گاهی)",
                "خارش (مداوم)",
                "خیر",
            ],
        },
        {
            "id": "sexual_health",
            "text": "وضعیت سلامت جنسی شما چگونه است؟ (محرمانه می‌ماند)",
            "type": "choice",
            "options": [
                "خوب و طبیعی",
                "کاهش میل جنسی",
                "افزایش میل جنسی",
                "اختلال در عملکرد",
                "سردی جنسی",
                "تمایلی به پاسخ ندارم",
            ],
        },
        # بخش ۸: حالات معنوی (۴ سوال)
        {
            "id": "spiritual_state",
            "text": "حال معنوی خود را چگونه توصیف می‌کنید؟",
            "type": "choice",
            "options": [
                "قوی و متصل به خدا",
                "متوسط",
                "ضعیف - احساس دوری از خدا",
                "پریشان و مضطرب روحی",
            ],
        },
        {
            "id": "prayer_feeling",
            "text": "هنگام نماز و عبادت چه حالی دارید؟",
            "type": "choice",
            "options": [
                "حضور قلب دارم و لذت می‌برم",
                "معمولی",
                "حواسم پرت می‌شود",
                "کسل و بی‌حال هستم",
                "نماز نمی‌خوانم",
            ],
        },
        {
            "id": "quran_connection",
            "text": "ارتباط شما با قرآن کریم چگونه است؟",
            "type": "choice",
            "options": [
                "هر روز تلاوت می‌کنم",
                "هفته‌ای چند بار",
                "گاهی",
                "کم - فقط در مناسبت‌ها",
                "تقریباً هیچ",
            ],
        },
        {
            "id": "heart_peace",
            "text": "آیا در قلب خود آرامش و سکینه دارید؟",
            "type": "choice",
            "options": [
                "بله، کاملاً آرامم",
                "نسبتاً آرام",
                "دلشوره و نگرانی دارم",
                "قلبم مضطرب و پریشان است",
            ],
        },
        # بخش ۹: فرائض دینی (۴ سوال)
        {
            "id": "prayer_regular",
            "text": "نمازهای واجب خود را چگونه می‌خوانید؟",
            "type": "choice",
            "options": [
                "همیشه اول وقت",
                "همیشه ولی با تأخیر",
                "بعضی اوقات قضا می‌شود",
                "غالباً قضا می‌شود",
                "نمی‌خوانم",
            ],
        },
        {
            "id": "fasting",
            "text": "وضعیت روزه‌داری شما؟",
            "type": "choice",
            "options": [
                "همه روزه‌های واجب و مستحبی",
                "همه واجب‌ها",
                "بعضی قضا می‌شود",
                "روزه نمی‌گیرم",
            ],
        },
        {
            "id": "khums_zakat",
            "text": "وضعیت پرداخت خمس و زکات شما؟",
            "type": "choice",
            "options": ["مرتب پرداخت می‌کنم", "گاهی", "کم", "اصلاً پرداخت نمی‌کنم"],
        },
        {
            "id": "night_prayer",
            "text": "آیا نماز شب یا تهجد دارید؟ (نماز شب = ۱۱ رکعت قبل از اذان صبح)",
            "type": "choice",
            "options": ["بله، مرتب", "گاهی", "خیلی کم", "هرگز"],
        },
        # بخش ۱۰: رابطه با خدا (۵ سوال)
        {
            "id": "trust_in_god",
            "text": "میزان توکل و اعتماد شما به خدا؟",
            "type": "choice",
            "options": [
                "کامل - در همه امور",
                "زیاد",
                "متوسط",
                "کم",
                "خیلی کم - نگران آینده‌ام",
            ],
        },
        {
            "id": "gratitude",
            "text": "چقدر شکرگزار نعمت‌های خدا هستید؟",
            "type": "choice",
            "options": [
                "همیشه در حال شکر",
                "غالباً",
                "گاهی",
                "کم",
                "غالباً ناسپاسی می‌کنم",
            ],
        },
        {
            "id": "repentance",
            "text": "آیا از گناهان گذشته خود توبه کرده‌اید؟",
            "type": "choice",
            "options": [
                "بله، توبه‌ی واقعی کرده‌ام",
                "توبه کرده‌ام ولی گاهی برمی‌گردم",
                "قصد توبه دارم",
                "هنوز تصمیم نگرفته‌ام",
            ],
        },
        {
            "id": "god_communication",
            "text": "چقدر با خدا راز و نیاز می‌کنید؟",
            "type": "choice",
            "options": [
                "هر روز دعا و مناجات دارم",
                "هفته‌ای چند بار",
                "گاهی",
                "کم",
                "هرگز",
            ],
        },
        {
            "id": "satisfaction",
            "text": "آیا به تقدیر و قضای الهی راضی هستید؟",
            "type": "choice",
            "options": [
                "کاملاً راضی و تسلیم",
                "نسبتاً راضی",
                "گاهی معترضم",
                "غالباً ناراضی‌ام",
            ],
        },
        # بخش ۱۱: اخلاق و روابط (۵ سوال)
        {
            "id": "family_relations",
            "text": "رابطه شما با خانواده (والدین، همسر، فرزندان) چگونه است؟",
            "type": "choice",
            "options": [
                "عالی و صمیمی",
                "خوب",
                "متوسط - گاهی اختلاف",
                "پرخاشگری و تنش زیاد",
                "قطع رابطه",
            ],
        },
        {
            "id": "neighbors_friends",
            "text": "رابطه شما با همسایه‌ها، دوستان و اقوام؟",
            "type": "choice",
            "options": [
                "عالی",
                "خوب",
                "متوسط",
                "کم - فقط در حد سلام",
                "کدورت و اختلاف دارم",
            ],
        },
        {
            "id": "moral_habits",
            "text": "آیا دچار اخلاق ناپسند هستید؟ (حسد، کینه، دروغ، غیبت و...)",
            "type": "choice",
            "options": [
                "خیر، تلاش می‌کنم پاک باشم",
                "گاهی",
                "زیاد - درگیر این صفات هستم",
                "نمی‌دانم",
            ],
        },
        {
            "id": "forgiveness",
            "text": "آیا کسی را نبخشیده‌اید یا از کسی کینه دارید؟",
            "type": "choice",
            "options": [
                "همه را بخشیده‌ام",
                "تقریباً همه را بخشیده‌ام",
                "چند نفر را نبخشیده‌ام",
                "کینه‌ی زیادی در قلبم دارم",
            ],
        },
        {
            "id": "kindness",
            "text": "میزان انفاق، احسان و کمک به دیگران؟",
            "type": "choice",
            "options": [
                "زیاد - همیشه در حال کمک",
                "متوسط",
                "گاهی",
                "کم",
                "تقریباً هیچ",
            ],
        },
        # بخش ۱۲: سبک زندگی (۸ سوال)
        {
            "id": "exercise",
            "text": "چقدر ورزش می‌کنید؟",
            "type": "choice",
            "options": ["هر روز", "هفته‌ای ۲-۳ بار", "هفته‌ای ۱ بار", "هیچ"],
        },
        {
            "id": "water_intake",
            "text": "روزانه چقدر آب می‌نوشید؟",
            "type": "choice",
            "options": [
                "کمتر از ۱ لیتر",
                "۱ تا ۲ لیتر",
                "۲ تا ۳ لیتر",
                "بیشتر از ۳ لیتر",
                "متغیر",
            ],
        },
        {
            "id": "tea_coffee",
            "text": "مصرف چای شما در روز چقدر است؟",
            "type": "choice",
            "options": [
                "بیشتر از ۵ فنجان",
                "۲ تا ۵ فنجان",
                "۱ فنجان",
                "مصرف نمی‌کنم",
                "متغیر",
            ],
        },
        {
            "id": "coffee_only",
            "text": "مصرف قهوه شما در روز چقدر است؟",
            "type": "choice",
            "options": [
                "بیشتر از ۳ فنجان",
                "۱ تا ۳ فنجان",
                "کمتر از ۱ فنجان",
                "مصرف نمی‌کنم",
            ],
        },
        {
            "id": "fast_food",
            "text": "مصرف فست‌فود؟",
            "type": "choice",
            "options": ["هر روز", "هفته‌ای چند بار", "هفته‌ای یک بار", "تقریباً هرگز"],
        },
        {
            "id": "dairy",
            "text": "مصرف لبنیات شما؟",
            "type": "choice",
            "options": ["زیاد و روزانه", "متوسط", "کم", "اصلاً مصرف نمی‌کنم"],
        },
        {
            "id": "smoking_cigarette",
            "text": "مصرف سیگار شما؟",
            "type": "choice",
            "options": ["بله، روزانه", "بله، گاهی", "ترک کرده‌ام", "هرگز"],
        },
        {
            "id": "smoking_hookah",
            "text": "مصرف قلیان شما؟",
            "type": "choice",
            "options": [
                "بله، روزانه",
                "هفته‌ای چند بار",
                "ماهی چند بار",
                "سالانه چند بار",
                "هرگز",
            ],
        },
        # بخش ۱۳: سابقه پزشکی (۳ سوال)
        {
            "id": "medications",
            "text": "آیا داروی خاصی مصرف می‌کنید؟ نام ببرید.",
            "type": "text",
        },
        {
            "id": "chronic_disease",
            "text": "آیا بیماری زمینه‌ای دارید؟ (دیابت، فشار خون، تیروئید، قلبی و...)",
            "type": "text",
        },
        {
            "id": "family_history",
            "text": "آیا در خانواده سابقه بیماری خاصی وجود دارد؟",
            "type": "text",
        },
        # بخش ۱۴: شکایت اصلی (۴ سوال)
        {
            "id": "complaint_duration",
            "text": "چند وقت است که از مشکل رنج می‌برید؟",
            "type": "choice",
            "options": [
                "کمتر از ۱ هفته",
                "۱ تا ۴ هفته",
                "۱ تا ۶ ماه",
                "بیشتر از ۶ ماه",
            ],
        },
        {
            "id": "complaint_severity",
            "text": "شدت مشکل چقدر است؟",
            "type": "choice",
            "options": ["خفیف", "متوسط", "شدید", "بسیار شدید"],
        },
        {
            "id": "complaint_pattern",
            "text": "مشکل شما چه الگویی دارد؟",
            "type": "choice",
            "options": [
                "همیشه ثابت",
                "صبح‌ها بدتر",
                "شب‌ها بدتر",
                "بعد از غذا بدتر",
                "با استرس بدتر",
                "متغیر",
            ],
        },
        {
            "id": "complaint",
            "text": "لطفاً همه‌ی مشکلات خود را با جزئیات کامل بنویسید. (جسمی، روحی، معنوی)",
            "type": "text",
        },
    ]
    return {"questions": questions, "total": len(questions)}


@app.post("/visits/{visit_id}/answer")
def submit_answer(visit_id: str, data: AnswerInput):
    db = SessionLocal()
    try:
        visit = db.query(Visit).filter_by(id=visit_id).first()
        if not visit:
            raise HTTPException(404, "ویزیت یافت نشد")

        session_data = dict(visit.session_data or {})
        answers = dict(session_data.get("answers", {}))
        answers[data.question_id] = data.answer
        session_data["answers"] = answers
        visit.session_data = session_data
        flag_modified(visit, "session_data")

        visit.progress_step = len(answers)
        db.commit()
        return {"status": "ok", "answered": len(answers)}
    finally:
        db.close()


# ============================================================
# تکمیل ویزیت و تولید گزارش
# ============================================================
@app.post("/visits/{visit_id}/complete")
async def complete_visit(visit_id: str):
    db = SessionLocal()
    try:
        visit = db.query(Visit).filter_by(id=visit_id).first()
        if not visit:
            raise HTTPException(404, "ویزیت یافت نشد")

        user = db.query(User).filter_by(id=visit.user_id).first()
        answers = (visit.session_data or {}).get("answers", {})
        mizaj_data = detect_mizaj(answers)
                # ✅ استخراج جداگانه‌ی همه شکایات (قبل از پرامپت)
        complaint_text = answers.get('complaint', 'موردی ذکر نشده')
        pain_location = answers.get('pain_location', 'موردی ذکر نشده')
        sexual_health = answers.get('sexual_health', 'موردی ذکر نشده')
        skin_problems = answers.get('skin_problems', 'موردی ذکر نشده')
        sleep_quality = answers.get('sleep_quality', 'موردی ذکر نشده')
        digestion = answers.get('digestion', 'موردی ذکر نشده')
        stool_shape = answers.get('stool_shape', 'موردی ذکر نشده')
        headache = answers.get('headache', 'موردی ذکر نشده')
        bloating = answers.get('bloating', 'موردی ذکر نشده')
        today_shamsi = jdatetime.date.today().strftime("%Y/%m/%d")
                # ✅ تاریخ شمسی امروز
        today_shamsi = jdatetime.date.today().strftime("%Y/%m/%d")

        # محاسبه BMI
        weight = answers.get("weight")
        height = answers.get("height")
        if weight and height:
            bmi, bmi_cat = calculate_bmi(weight, height)
        else:
            bmi, bmi_cat = None, "نامشخص"

        # شکایت اصلی
        complaint_text = answers.get("complaint", "موردی ذکر نشده")

        # ساخت پرامپت برای AI
        prompt = f"""
اطلاعات کامل کاربر:
- نام: {answers.get('name', user.name)}
- تاریخ مراجعه: {today_shamsi}
- سن: {answers.get('age', 'نامشخص')}
- جنسیت: {answers.get('gender', 'نامشخص')}
- وزن: {weight} کیلوگرم
- قد: {height} سانتی‌متر
- BMI: {bmi} ({bmi_cat})
- مزاج تشخیص داده شده: {mizaj_data['mizaj']}
- درجه گرمی/سردی: {mizaj_data['hot_cold']}
- درجه تری/خشکی: {mizaj_data['wet_dry']}
- امتیاز تفصیلی مزاج: {mizaj_data['score']}

پاسخ‌های کامل کاربر به ۸۸ سوال:
{json.dumps(answers, ensure_ascii=False, indent=2)}
        # ✅ استخراج جداگانه‌ی همه شکایات
        complaint_text = answers.get('complaint', 'موردی ذکر نشده')
        pain_location = answers.get('pain_location', '')
        sexual_health = answers.get('sexual_health', '')
        skin_problems = answers.get('skin_problems', '')
        sleep_quality = answers.get('sleep_quality', '')
        digestion = answers.get('digestion', '')
        stool_shape = answers.get('stool_shape', '')
        headache = answers.get('headache', '')
        bloating = answers.get('bloating', '')

⚠️⚠️⚠️ **شکایات اصلی کاربر (حتماً همه رو جداگانه تحلیل کن):**
1. شکایت اصلی: {complaint_text}
2. محل درد: {pain_location}
3. سلامت جنسی: {sexual_health}
4. مشکلات پوستی: {skin_problems}
5. کیفیت خواب: {sleep_quality}
6. وضعیت گوارش: {digestion}
7. شکل مدفوع: {stool_shape}
8. سردرد: {headache}
9. نفخ: {bloating}

🚨 **تأکید ویژه:** برای **هر یک از این ۹ مورد**، حتی اگه کوچک باشه، یه بخش جداگانه با جدول درمانی بنویس. مثلاً اگه کاربر «افتادگی پا» یا «کاهش میل جنسی» داره، حتماً براش بخش جداگانه با ریشه‌یابی، درمان مادی و معنوی بساز. **هیچ‌کدوم رو نادیده نگیر!**

لطفاً بر اساس این اطلاعات، یک گزارش کامل، دقیق، حرفه‌ای و امیدوارکننده برای کاربر بنویس.
"""

        report_text = ""
        try:
            if AI_ENABLED:
                response = ai_client.chat.completions.create(
                    model=AI_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": """تو «دکتر حکیم» هستی؛ جدیدترین، فوق‌تخصص‌ترین و مهربان‌ترین پزشک متخصص طب سنتی و اسلامی در جهان هستی. لحن تو باید کاملاً دوستانه، امیدوارکننده و دلسوزانه باشه.


📅 **تاریخ امروز: امروز**

🎯 **مأموریت تو:**
تحلیل دقیق، جامع و شخصی‌سازی‌شده‌ای از وضعیت جسمی و روحی کاربر ارائه بده.

📋 **ساختار گزارش (دقیقاً به همین ترتیب):**

**📌 نسخه ۱.۰ | تحلیل تخصصی دکتر حکیم | تاریخ: [تاریخ امروز به شمسی]**

**۱. 🌿 تحلیل جامع وضعیت**
- خلاصه‌ای صمیمانه با ذکر نام کاربر
- نقاط قوت و ضعف (مادی و معنوی) به صورت **جدول**

**۲. 🌡️ تشخیص مزاج دقیق**

| مزاج | امتیاز |
|------|--------|
| گرم | X |
| سرد | X |
| تر | X |
| خشک | X |

- نوع مزاج غالب، درجه گرمی/سردی و تری/خشکی

**۳. 💊 درمان‌های مادی (فوق تخصصی)**

برای هر مشکل جسمی، یک بخش جداگانه بنویس:

**۳.۱ مشکل اول: [نام مشکل]**
- **ریشه‌یابی:** ...
- **علائم:** ...

| نوع درمان | مقدار دقیق | زمان مصرف |
|------------|-----------|-----------|
| تغذیه | ۱ قاشق غذاخوری عسل | صبح ناشتا |
| گیاه دارویی | ۱ قاشق چای‌خوری ... | ۲ بار در روز |
| ورزش | ۲۰ دقیقه پیاده‌روی | صبح |
| درمان مکمل | حجامت | ماهی ۱ بار |

- **پرهیزها:** ...
- **زمان بهبودی:** ...

**۴. 📿 درمان‌های معنوی**

| نوع عبادت | تعداد/مقدار | زمان |
|-----------|------------|------|
| توبه و استغفار | ۱۰۰ بار | روزانه |
| تلاوت قرآن | سوره یاسین | صبح |
| ذکر | «یا شافی» ۱۰۰ بار | بعد از نماز |
| صدقه | مبلغ مشخص | هفتگی |
| صله رحم | تماس/دیدار | هفتگی |

**۵. 📅 برنامه هفتگی**

| روز | فعالیت مادی | فعالیت معنوی |
|-----|-------------|--------------|
| شنبه | صبحانه: ۱ قاشق عسل | ۱۰ دقیقه قرآن |
| یکشنبه | ... | ... |
| ... | ... | ... |

**۶. 💎 توصیه‌های نهایی طلایی**

۱. ...
۲. ...
۳. ...

**۷. 🌸 پیام پایانی**

جمله‌ای از ته دل + دعای خیر

---

**⚠️ نکات مهم:**
✅ حتماً از **جدول Markdown** برای همه بخش‌ها استفاده کن (خطوط `| ... | ... |` و `|---|---|`)
✅ دوز داروها و غذاها حتماً با **قاشق غذاخوری/چای‌خوری/گرم** مشخص کن
✅ بعد از هر بخش بزرگ، این امضا رو بذار:
`---`
`🖋️ **امضای دکتر حکیم** — دستیار هوشمند طب سنتی و اسلامی`
`📞 پشتیبانی: bale.ir/TebAI_Help_bot`
`---`
✅ در بخش پیام پایانی، تأکید کن:
«📅 **یادآوری مهم:** هنگام مراجعه‌ی بعدی، لطفاً بگو **ماه قبل مراجعه کرده‌ام** تا سوابق درمانی‌ات بررسی و برنامه‌ی جدید بر اساس پیشرفتت تنظیم شود.»
✅ لحن کاملاً صمیمی، دلسوزانه و امیدوارکننده
✅ از ایموجی‌های مناسب استفاده کن
✅ با عشق و دلسوزی بنویس! 💚

🚨 **قانون طلایی حیاتی:**
اگه کاربر ۱۰ مشکل گفته، باید **۱۰ بخش جداگانه** با جدول، ریشه‌یابی و درمان بنویسی.
اگه ۱۵ مشکل گفته، **۱۵ بخش جداگانه**.
**هیچ شکایتی رو نادیده نگیر!** حتی اگه کاربر گفته «پام افتاده»، باید براش بخش درمان کامل با جدول بنویسی.
مواردی مثل: افتادگی پا، کاهش میل جنسی، سردی پاها، ریزش مو، یبوست، سردرد، نفخ، اضطراب، افسردگی و... همه باید بخش جداگانه داشته باشن.

📋 **ساختار کامل هر مشکل (حتماً این ۱۲ بخش رو برای هر مشکل بنویس):**

### 🔴 مشکل شماره X: [نام دقیق مشکل]

**🔍 ریشه‌یابی دقیق:**
- علت اصلی از دیدگاه طب سنتی
- علت از دیدگاه طب مدرن
- نقش مزاج در ایجاد این مشکل

**⚠️ علائم تخصصی:**
- علائم جسمی
- علائم روحی
- علائم معنوی

**جدول جامع درمان‌های مادی (حتماً حداقل ۸ ردیف بنویس):**

| 🍃 نوع درمان | 📏 مقدار دقیق | ⏰ زمان مصرف |
|:------------|:-------------|:-------------|
| 🍲 **تغذیه** | ۱ قاشق غذاخوری عسل | صبح ناشتا |
| 🌿 **گیاه دارویی ۱** | ۱ قاشق چای‌خوری ... | ۲ بار در روز |
| 🌱 **گیاه دارویی ۲** | ۱ قاشق چای‌خوری ... | قبل از خواب |
| 🫖 **دمنوش ویژه** | ۱ لیوان | ۳ بار در روز |
| 💧 **روغن‌مالی** | ۵ قطره | موضعی، ۲ بار در روز |
| 🏃 **ورزش اختصاصی** | ۲۰ دقیقه | صبح‌ها |
| 🧘 **یوگا/تنفس** | ۱۰ دقیقه | عصرها |
| 💆 **حجامت/بادکش** | ۱ جلسه | ماهی ۱ بار |
| 🛁 **حمام درمانی** | ۲۰ دقیقه | هفته‌ای ۲ بار |
| ☀️ **آفتاب‌درمانی** | ۱۵ دقیقه | صبح‌ها |

**🚫 پرهیزهای غذایی و رفتاری:**
- پرهیز اول
- پرهیز دوم
- پرهیز سوم

**⏱️ زمان تقریبی بهبودی:** ...

**🌙 تدابیر شبانه:**
- قبل از خواب چه کار کنه

**☀️ تدابیر صبحگاهی:**
- بعد از بیدار شدن چه کار کنه

**💊 مکمل‌های پیشنهادی:** 
- ویتامین‌ها یا مکمل‌های مفید 

🚨 **قوانین حیاتی برای درمان‌ها:**

۱. برای **هر مشکل کاربر**، حداقل **۸ تا ۱۲ نوع درمان متفاوت** بنویس.
۲. حتماً از این دسته‌ها استفاده کن:
   - 🍲 تغذیه (غذا و نوشیدنی)
   - 🌿 گیاهان دارویی (حداقل ۳ گیاه مختلف)
   - 🫖 دمنوش‌های ترکیبی
   - 💊 پودرها و ترکیبات
   - 💧 روغن‌مالی و ماساژ
   - 🏃 ورزش و پیاده‌روی
   - 🧘 یوگا، مدیتیشن، تنفس عمیق
   - 💆 حجامت، فصد، بادکش، طب‌سوزنی
   - 🛁 حمام درمانی و آب‌درمانی
   - ☀️ نور خورشید و هوای تازه
   - 🛌 خواب و استراحت
   - 🎵 موسیقی‌درمانی

۳. **دوز دقیق** رو حتماً بنویس: با قاشق غذاخوری، قاشق چای‌خوری، گرم، قطره، یا لیوان.
۴. **زمان مصرف** رو مشخص کن: صبح ناشتا، بعد از غذا، قبل از خواب، شب‌ها.
۵. **مدت درمان** رو بنویس: چند هفته یا چند ماه.

❌ **هرگز فقط ۳-۴ درمان ننویس!** هر مشکل باید حداقل ۸ درمان مختلف داشته باشه.
📚 **منابع معتبر:**
از دستورات طب سنتی ایرانی (ابن‌سینا، رازی، جرجانی) و طب اسلامی (احادیث اهل بیت) و همچنین جدیدترین مقالات علمی روز استفاده کن. """
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.75,
                    max_tokens=16000,
                )
                report_text = response.choices[0].message.content
                print(f"✅ گزارش AI تولید شد ({len(report_text)} کاراکتر)")
            else:
                raise Exception("API Key تنظیم نشده")
        except Exception as e:
            print(f"❌ خطا در AI: {e}")
            fallback = []
            fallback.append(
                f"سلام {answers.get('name', user.name)} عزیز،نسخه شما آماده است:\n"
            )
            fallback.append(
                f"🔥 مزاج غالب: {mizaj_data['mizaj']} ({mizaj_data['hot_cold']} و {mizaj_data['wet_dry']})"
            )
            if bmi:
                fallback.append(f"⚖️ BMI: {bmi} ({bmi_cat})")
            fallback.append(f"\n📝 شکایت شما: {complaint_text}")
            fallback.append("\n⚠️ متأسفانه در لحظه تولید تحلیل اختصاصی خطایی رخ داد.")
            fallback.append(
                "\n📅 حتماً برای ادامه معالجه و بررسی روند بهبودی هر ماه مراجعه کنید."
            )
            report_text = "\n".join(fallback)

        # به‌روزرسانی دیتابیس
        visit.status = "completed"
        visit.completed_at = datetime.utcnow()
        if visit.payment_status == "paid":
            user.completed_visits += 1
            user.total_paid += 1
            user.total_spent += visit.final_amount
        else:
            user.completed_visits += 1
            user.total_free += 1
            if visit.used_free_credit:
                user.free_credits = max(0, (user.free_credits or 0) - 1)

        # به‌روزرسانی سطح باشگاه
        old_tier = user.loyalty_tier or "newcomer"
        new_tier = calculate_tier(user.completed_visits)
        user.loyalty_tier = new_tier
        tier_upgraded = old_tier != new_tier
        new_tier_info = get_tier_info(new_tier)

        # پاداش پلاتینیوم
        if new_tier == "master_sage" and user.completed_visits % 10 == 0:
            user.free_credits = (user.free_credits or 0) + 1

        # پاداش معرفی
        referral_reward = None
        if user.referred_by and not user.referral_confirmed:
            user.referral_confirmed = True
            referrer = db.query(User).filter_by(referral_code=user.referred_by).first()
            if referrer:
                new_count = (referrer.confirmed_referrals or 0) + 1
                referrer.confirmed_referrals = new_count

                milestone_reached = None
                for r in REFERRAL_REWARDS:
                    if r["count"] == new_count:
                        milestone_reached = r
                        break

                rewards_applied = []
                if milestone_reached:
                    if milestone_reached["type"] in ["credit_10", "free_visit"]:
                        referrer.free_credits = (referrer.free_credits or 0) + 1
                        rewards_applied.append(milestone_reached["label"])

                tier_boost = apply_referral_boost(referrer, new_count)
                if tier_boost:
                    rewards_applied.append(
                        f"🏆 ارتقا به {tier_boost['tier_icon']} {tier_boost['tier_name']}"
                    )

                if rewards_applied:
                    reward_msg = " | ".join(rewards_applied)
                    await manager.send(
                        str(referrer.id),
                        {
                            "title": "🎉 پاداش معرفی!",
                            "message": f"{referrer.name} عزیز، {reward_msg}",
                        },
                    )
                    referral_reward = {
                        "referrer_name": referrer.name,
                        "reward": "milestone",
                        "message": reward_msg,
                        "count": new_count,
                    }
                else:
                    next_milestone = get_next_referral_milestone(new_count)
                    referral_reward = {
                        "referrer_name": referrer.name,
                        "reward": "progress",
                        "count": new_count,
                        "next": next_milestone,
                    }

        db.commit()

        await manager.send(
            str(user.id),
            {
                "title": "✅نسخه شما آماده شد",
                "message": f"نسخه ویزیت #{visit.visit_number} شما آماده است.",
            },
        )

        return {
            "report": report_text,
            "mizaj": mizaj_data,
            "bmi": bmi,
            "visit_number": visit.visit_number,
            "referral_reward": referral_reward,
            "loyalty_tier": user.loyalty_tier,
            "loyalty_info": {
                "tier": new_tier,
                "name": new_tier_info["name"],
                "icon": new_tier_info["icon"],
                "discount": new_tier_info["discount"],
                "color": new_tier_info["color"],
                "upgraded": tier_upgraded,
                "next_tier": next_tier_info(user.completed_visits),
                "free_credits": user.free_credits or 0,
            },
        }
    finally:
        db.close()


# ============================================================
# نظرات
# ============================================================
@app.post("/feedback")
def submit_feedback(data: FeedbackInput):
    db = SessionLocal()
    try:
        feedback = Feedback(
            user_id=data.user_id,
            visit_id=data.visit_id,
            feedback_type=data.feedback_type,
            feedback_text=data.feedback_text,
        )
        db.add(feedback)
        db.commit()
        return {"status": "ok", "message": "نظر شما ثبت شد"}
    finally:
        db.close()


# ============================================================
# باشگاه مشتریان
# ============================================================
@app.get("/users/{user_id}/loyalty")
def user_loyalty(user_id: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(404, "کاربر یافت نشد")

        tier = calculate_tier(user.completed_visits or 0)
        tier_info = get_tier_info(tier)

        return {
            "tier": tier,
            "name": tier_info["name"],
            "icon": tier_info["icon"],
            "discount": tier_info["discount"],
            "color": tier_info["color"],
            "completed_visits": user.completed_visits or 0,
            "free_credits": user.free_credits or 0,
            "next_tier": next_tier_info(user.completed_visits or 0),
            "all_tiers": [
                {
                    "key": k,
                    "name": v["name"],
                    "icon": v["icon"],
                    "min_visits": v["min_visits"],
                    "discount": v["discount"],
                    "is_current": (k == tier),
                }
                for k, v in LOYALTY_TIERS.items()
            ],
        }
    finally:
        db.close()


@app.get("/users/{user_id}/rewards")
def user_rewards(user_id: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(404, "کاربر یافت نشد")

        confirmed = user.confirmed_referrals or 0
        all_rewards = []
        for r in REFERRAL_REWARDS:
            all_rewards.append(
                {
                    "count": r["count"],
                    "label": r["label"],
                    "achieved": confirmed >= r["count"],
                    "remaining": max(0, r["count"] - confirmed),
                }
            )

        return {
            "confirmed_referrals": confirmed,
            "referral_code": user.referral_code,
            "free_credits": user.free_credits or 0,
            "next_milestone": get_next_referral_milestone(confirmed),
            "all_rewards": all_rewards,
        }
    finally:
        db.close()


# ============================================================
# پنل مدیریت
# ============================================================
@app.post("/admin/login")
def admin_login(data: AdminLoginInput):
    if data.password != ADMIN_PASSWORD:
        raise HTTPException(401, "رمز عبور اشتباه است")
    token = create_admin_session()
    return {"token": token, "message": "ورود موفق"}


@app.get("/admin/stats")
def admin_stats(token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        total_users = db.query(User).count()
        total_visits = db.query(Visit).count()
        completed_visits = db.query(Visit).filter(Visit.status == "completed").count()
        total_feedbacks = db.query(Feedback).count()

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        new_users_today = db.query(User).filter(User.created_at >= today).count()
        visits_today = db.query(Visit).filter(Visit.created_at >= today).count()

        return {
            "total_users": total_users,
            "total_visits": total_visits,
            "completed_visits": completed_visits,
            "total_feedbacks": total_feedbacks,
            "new_users_today": new_users_today,
            "visits_today": visits_today,
        }
    finally:
        db.close()


@app.get("/admin/users")
def admin_users(token: str, search: str = "", limit: int = 200):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        query = db.query(User)
        if search:
            query = query.filter(
                (User.name.contains(search)) | (User.phone.contains(search))
            )
        users = query.order_by(User.created_at.desc()).limit(limit).all()
        return [
            {
                "id": str(u.id),
                "name": u.name,
                "phone": u.phone,
                "referral_code": u.referral_code,
                "referred_by": u.referred_by,
                "completed_visits": u.completed_visits or 0,
                "total_paid": u.total_paid or 0,
                "total_free": u.total_free or 0,
                "loyalty_tier": u.loyalty_tier or "newcomer",
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    finally:
        db.close()


@app.get("/admin/visits")
def admin_visits(token: str, limit: int = 200):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        visits = (
            db.query(Visit, User)
            .join(User, Visit.user_id == User.id)
            .order_by(Visit.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(v.id),
                "user_name": u.name,
                "user_phone": u.phone,
                "visit_number": v.visit_number,
                "status": v.status,
                "payment_status": v.payment_status,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "completed_at": v.completed_at.isoformat() if v.completed_at else None,
            }
            for v, u in visits
        ]
    finally:
        db.close()


@app.get("/admin/feedbacks")
def admin_feedbacks(token: str, limit: int = 200):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        feedbacks = (
            db.query(Feedback, User)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(f.id),
                "user_name": u.name,
                "user_phone": u.phone,
                "feedback_type": f.feedback_type,
                "feedback_text": f.feedback_text,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f, u in feedbacks
        ]
    finally:
        db.close()


@app.get("/admin/user/{user_id}")
def admin_user_detail(user_id: str, token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(404, "کاربر یافت نشد")
        visits = (
            db.query(Visit)
            .filter_by(user_id=user_id)
            .order_by(Visit.visit_number)
            .all()
        )
        return {
            "id": str(user.id),
            "name": user.name,
            "phone": user.phone,
            "referral_code": user.referral_code,
            "completed_visits": user.completed_visits or 0,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "visits": [
                {
                    "id": str(v.id),
                    "visit_number": v.visit_number,
                    "status": v.status,
                    "payment_status": v.payment_status,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "completed_at": (
                        v.completed_at.isoformat() if v.completed_at else None
                    ),
                    "session_data": v.session_data,
                }
                for v in visits
            ],
        }
    finally:
        db.close()


@app.get("/admin/loyalty/distribution")
def admin_loyalty_distribution(token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        distribution = {}
        for tier_key in LOYALTY_TIERS.keys():
            count = db.query(User).filter(User.loyalty_tier == tier_key).count()
            distribution[tier_key] = count

        top_users = (
            db.query(User)
            .filter(User.completed_visits > 0)
            .order_by(User.completed_visits.desc())
            .limit(20)
            .all()
        )

        return {
            "distribution": [
                {
                    "tier": k,
                    "name": LOYALTY_TIERS[k]["name"],
                    "icon": LOYALTY_TIERS[k]["icon"],
                    "color": LOYALTY_TIERS[k]["color"],
                    "discount": LOYALTY_TIERS[k]["discount"],
                    "min_visits": LOYALTY_TIERS[k]["min_visits"],
                    "count": distribution.get(k, 0),
                }
                for k in LOYALTY_TIERS.keys()
            ],
            "top_users": [
                {
                    "name": u.name,
                    "phone": u.phone,
                    "completed_visits": u.completed_visits or 0,
                    "tier": u.loyalty_tier or "newcomer",
                    "tier_name": get_tier_info(u.loyalty_tier)["name"],
                    "tier_icon": get_tier_info(u.loyalty_tier)["icon"],
                }
                for u in top_users
            ],
        }
    finally:
        db.close()


# ============================================================
# خروجی اکسل
# ============================================================
def _style_excel_sheet(ws, headers, rows):
    header_fill = PatternFill(
        start_color="1a6b52", end_color="1a6b52", fill_type="solid"
    )
    header_font = Font(bold=True, color="FFFFFF", size=12, name="Tahoma")
    header_align = Alignment(horizontal="center", vertical="center", readingOrder=2)
    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )

    ws.append(headers)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border

    data_align = Alignment(horizontal="right", vertical="center", readingOrder=2)
    data_font = Font(size=11, name="Tahoma")

    for row in rows:
        ws.append(row)
        for cell in ws[ws.max_row]:
            cell.alignment = data_align
            cell.font = data_font
            cell.border = thin_border

    for col_idx, header in enumerate(headers, 1):
        max_len = len(str(header))
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(
            max_len + 4, 40
        )


@app.get("/admin/export/users")
def export_users_excel(token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()

        wb = Workbook()
        ws = wb.active
        ws.title = "کاربران"
        ws.sheet_view.rightToLeft = True

        headers = [
            "ردیف",
            "نام و نام خانوادگی",
            "موبایل",
            "کد معرفی",
            "معرفی‌شده توسط",
            "ویزیت موفق",
            "کل ویزیت پرداخت‌شده",
            "ویزیت رایگان",
            "سطح باشگاه",
            "تاریخ ثبت‌نام",
        ]

        rows = []
        for i, u in enumerate(users, 1):
            tier_info = get_tier_info(u.loyalty_tier)
            rows.append(
                [
                    i,
                    u.name or "—",
                    u.phone or "—",
                    u.referral_code or "—",
                    u.referred_by or "—",
                    u.completed_visits or 0,
                    u.total_paid or 0,
                    u.total_free or 0,
                    f"{tier_info['icon']} {tier_info['name']}",
                    to_shamsi(u.created_at),
                ]
            )

        _style_excel_sheet(ws, headers, rows)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"users_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


@app.get("/admin/export/visits")
def export_visits_excel(token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        visits = (
            db.query(Visit, User)
            .join(User, Visit.user_id == User.id)
            .order_by(Visit.created_at.desc())
            .all()
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "ویزیت‌ها"
        ws.sheet_view.rightToLeft = True

        headers = [
            "ردیف",
            "کاربر",
            "موبایل",
            "شماره ویزیت",
            "وضعیت ویزیت",
            "وضعیت پرداخت",
            "مبلغ پرداخت",
            "تاریخ شروع",
            "تاریخ پایان",
        ]

        status_map = {"completed": "✅ تکمیل شده", "in_progress": "🔄 در جریان"}
        pay_map = {
            "paid": "💰 پرداخت‌شده",
            "free": "🎁 رایگان",
            "pending": "⏳ در انتظار",
        }

        rows = []
        for i, (v, u) in enumerate(visits, 1):
            rows.append(
                [
                    i,
                    u.name or "—",
                    u.phone or "—",
                    v.visit_number or "—",
                    status_map.get(v.status, v.status or "—"),
                    pay_map.get(v.payment_status, v.payment_status or "—"),
                    f"{v.final_amount or 0:,}",
                    to_shamsi(v.created_at),
                    to_shamsi(v.completed_at),
                ]
            )

        _style_excel_sheet(ws, headers, rows)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"visits_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


@app.get("/admin/export/feedbacks")
def export_feedbacks_excel(token: str):
    if not check_admin_session(token):
        raise HTTPException(401, "لطفاً دوباره وارد شوید")
    db = SessionLocal()
    try:
        feedbacks = (
            db.query(Feedback, User)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .all()
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "نظرات"
        ws.sheet_view.rightToLeft = True

        headers = ["ردیف", "کاربر", "موبایل", "نوع پیام", "متن پیام", "تاریخ"]

        rows = []
        for i, (f, u) in enumerate(feedbacks, 1):
            rows.append(
                [
                    i,
                    u.name or "—",
                    u.phone or "—",
                    f.feedback_type or "—",
                    f.feedback_text or "—",
                    to_shamsi(f.created_at),
                ]
            )

        _style_excel_sheet(ws, headers, rows)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"feedbacks_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


# ============================================================
# تاریخچه و معرفی‌ها
# ============================================================
@app.get("/users/{user_id}/history")
def user_history(user_id: str):
    db = SessionLocal()
    try:
        visits = (
            db.query(Visit)
            .filter_by(user_id=user_id)
            .order_by(Visit.visit_number)
            .all()
        )
        return [
            {
                "visit_number": v.visit_number,
                "status": v.status,
                "payment_status": v.payment_status,
                "amount": v.final_amount,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "completed_at": v.completed_at.isoformat() if v.completed_at else None,
            }
            for v in visits
        ]
    finally:
        db.close()


@app.get("/users/{user_id}/referrals")
def user_referrals(user_id: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(404, "کاربر یافت نشد")
        referred = db.query(User).filter_by(referred_by=user.referral_code).all()
        return {
            "referral_code": user.referral_code,
            "confirmed_referrals": user.confirmed_referrals,
            "free_credits": user.free_credits,
            "referred_list": [
                {
                    "name": u.name,
                    "confirmed": u.referral_confirmed,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in referred
            ],
        }
    finally:
        db.close()


# ============================================================
# WebSocket
# ============================================================
@app.websocket("/ws/notifications/{user_id}")
async def notifications_ws(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)