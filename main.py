# -*- coding: utf-8 -*-
"""
ربات طب سنتی و اسلامی — کد کامل یکپارچه
"""
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import uuid
import secrets
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import (
    create_engine, Column, String, Integer, Boolean, BigInteger,
    DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker
from passlib.hash import bcrypt

# ============================================================
# ۱. تنظیمات دیتابیس
# ============================================================
 ⚠️ موقتاً فقط SQLite
DATABASE_URL = "sqlite:///./teb_local.db"
connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

VISIT_PRICE = 500_000
REFERRALS_NEEDED = 5


# ============================================================
# ۲. مدل‌های دیتابیس
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
    loyalty_tier = Column(String(20), default="bronze")
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


# ============================================================
# ۳. توابع کمکی دیتابیس
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
                role="super_admin"
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

        user = User(name=name, phone=phone, referral_code=my_code, referred_by=referred_by)
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"user": user, "is_returning": False, "referral_applied": referred_by is not None}
    finally:
        db.close()


# ============================================================
# ۴. موتور تشخیص مزاج و بیماری
# ============================================================
def detect_mizaj(answers: dict) -> dict:
    score = {"گرم": 0, "سرد": 0, "تر": 0, "خشک": 0}

    temp = answers.get("body_temp")
    if temp == "گرم": score["گرم"] += 3
    elif temp == "سرد": score["سرد"] += 3

    thirst = answers.get("thirst")
    if thirst == "زیاد": score["گرم"] += 2; score["خشک"] += 1
    elif thirst == "کم": score["سرد"] += 2; score["تر"] += 1

    mood = answers.get("mood")
    if mood == "عصبی و پرانرژی": score["گرم"] += 2; score["خشک"] += 2
    elif mood == "آرام و کم‌حرف": score["سرد"] += 2; score["تر"] += 1
    elif mood == "مضطرب": score["خشک"] += 2; score["گرم"] += 1

    skin = answers.get("skin")
    if skin == "خشک": score["خشک"] += 3
    elif skin == "چرب": score["تر"] += 3
    elif skin == "مخلوط": score["خشک"] += 1; score["تر"] += 1

    sleep = answers.get("sleep")
    if sleep == "کم و سبک": score["خشک"] += 2; score["گرم"] += 1
    elif sleep == "زیاد و سنگین": score["تر"] += 2; score["سرد"] += 1
    elif sleep == "بی‌خوابی": score["خشک"] += 3

    stool = answers.get("stool")
    if stool == "یبوست": score["خشک"] += 3
    elif stool == "اسهال": score["تر"] += 2; score["سرد"] += 1

    hair = answers.get("hair")
    if hair == "خشک و شکننده": score["خشک"] += 2
    elif hair == "چرب": score["تر"] += 2
    elif hair == "ریزش زیاد": score["خشک"] += 1; score["سرد"] += 1

    energy = answers.get("energy")
    if energy == "بالا": score["گرم"] += 2
    elif energy == "پایین": score["سرد"] += 2

    appetite = answers.get("appetite")
    if appetite == "زیاد": score["گرم"] += 2
    elif appetite == "کم": score["سرد"] += 2

    digestion = answers.get("digestion")
    if digestion == "سریع": score["گرم"] += 1; score["خشک"] += 1
    elif digestion == "کند": score["سرد"] += 2; score["تر"] += 1
    elif digestion == "نفخ و سنگینی": score["تر"] += 2; score["سرد"] += 1

    hot_cold = "گرم" if score["گرم"] > score["سرد"] else "سرد"
    wet_dry = "خشک" if score["خشک"] > score["تر"] else "تر"

    mizaj_map = {
        ("گرم", "خشک"): "صفراوی",
        ("گرم", "تر"): "دموی",
        ("سرد", "تر"): "بلغمی",
        ("سرد", "خشک"): "سوداوی"
    }
    mizaj = mizaj_map.get((hot_cold, wet_dry), "معتدل")
    return {"mizaj": mizaj, "hot_cold": hot_cold, "wet_dry": wet_dry, "score": score}


def calculate_bmi(weight, height_cm):
    try:
        h = float(height_cm) / 100
        bmi = float(weight) / (h * h)
        if bmi < 18.5: cat = "کمبود وزن"
        elif bmi < 25: cat = "وزن نرمال"
        elif bmi < 30: cat = "اضافه وزن"
        else: cat = "چاقی"
        return round(bmi, 1), cat
    except Exception:
        return None, "نامشخص"


DISEASE_KEYWORDS = {
    "کبد چرب": ["کبد چرب", "چربی کبد", "کبد"],
    "دیابت": ["دیابت", "قند خون", "قند بالا"],
    "فشار خون": ["فشار خون", "پرفشاری"],
    "چربی خون": ["چربی خون", "کلسترول", "تری گلیسیرید"],
    "یبوست": ["یبوست", "دفع سخت"],
    "سردرد": ["سردرد", "میگرن", "سر درد"],
    "اضطراب": ["اضطراب", "استرس", "نگرانی", "دلشوره"],
    "افسردگی": ["افسردگی", "غم"],
    "بی‌خوابی": ["بی‌خوابی", "خواب"],
    "کم‌خونی": ["کم‌خونی", "آنمی"],
    "معده": ["معده", "نفخ", "سوزش معده", "رفلاکس"],
    "مفاصل": ["مفاصل", "درد زانو", "آرتروز"],
    "ریزش مو": ["ریزش مو", "کم‌پشتی مو"]
}


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


# ============================================================
# ۵. پایگاه دانش طب سنتی
# ============================================================
DISEASE_KNOWLEDGE = {
    "کبد چرب": {
        "definition": "تجمع چربی در سلول‌های کبد که در طب سنتی معمولاً ناشی از سردی و تری مزاج است.",
        "general": ["کاهش وزن تدریجی", "پرهیز از غذاهای سرد و تر", "پرهیز از فست‌فود", "مصرف ۸ لیوان آب گرم", "پیاده‌روی روزانه ۳۰ دقیقه"],
        "herbs": [
            {"name": "خار مریم", "usage": "دم‌کرده روزی ۲ بار"},
            {"name": "زردچوبه", "usage": "نصف قاشق با فلفل سیاه"},
            {"name": "سیر", "usage": "۱-۲ حبه ناشتا"},
        ],
        "by_mizaj": {
            "صفراوی": "پرهیز از سرخ‌کردنی. مصرف کاسنی، شاتره.",
            "دموی": "حجامت توصیه می‌شود. کاهش گوشت قرمز.",
            "بلغمی": "مصرف زنجبیل، دارچین. پرهیز از ماست و ترشی.",
            "سوداوی": "مصرف روغن زیتون، کنجد. ورزش سبک."
        },
        "spiritual": ["پیامبر (ص): «معده خانه هر بیماری است»"]
    },
    "دیابت": {
        "definition": "افزایش قند خون که با سردی مزاج مرتبط است.",
        "general": ["پرهیز از قند ساده", "مصرف نان سبوس‌دار", "تقسیم وعده‌ها", "پیاده‌روی ۴۵ دقیقه"],
        "herbs": [
            {"name": "شنبلیله", "usage": "دم‌کرده قبل از غذا"},
            {"name": "دارچین", "usage": "نصف قاشق روزانه"},
            {"name": "چای سبز", "usage": "۲-۳ لیوان در روز"},
        ],
        "by_mizaj": {
            "صفراوی": "مصرف کدو حلوایی، خرفه، کاسنی.",
            "دموی": "حجامت. کاهش گوشت قرمز.",
            "بلغمی": "مصرف دارچین، زنجبیل، فلفل.",
            "سوداوی": "مصرف روغن زیتون، کنجد، خرما."
        },
        "spiritual": ["پیامبر (ص): «سیاه‌دانه درمان هر دردی است»"]
    },
    "فشار خون": {
        "definition": "افزایش فشار خون که معمولاً ناشی از غلبه گرمی و خشکی است.",
        "general": ["کاهش نمک", "پرهیز از ترشیجات", "مدیریت استرس", "خواب کافی"],
        "herbs": [
            {"name": "سیر", "usage": "۱-۲ حبه ناشتا"},
            {"name": "چای ترش", "usage": "۱-۲ لیوان روزانه"},
            {"name": "زرشک", "usage": "آب‌زرشک طبیعی"},
        ],
        "by_mizaj": {
            "صفراوی": "پرهیز از تندی. مصرف کاسنی، شاتره.",
            "دموی": "حجامت عام. کاهش گوشت قرمز.",
            "بلغمی": "مصرف زنجبیل، دارچین.",
            "سوداوی": "مصرف روغن زیتون، ورزش ملایم."
        },
        "spiritual": ["قرآن: «و لا تقتلوا انفسکم»"]
    },
    "یبوست": {
        "definition": "سختی دفع که ناشی از خشکی مزاج است.",
        "general": ["مصرف فیبر", "آب گرم ناشتا", "پیاده‌روی", "پرهیز از نان سفید"],
        "herbs": [
            {"name": "سنامکی", "usage": "۱ قاشق چای‌خوری قبل از خواب"},
            {"name": "گل ختمی", "usage": "دم‌کرده"},
            {"name": "انجیر", "usage": "۳-۵ عدد خیسانده صبح"},
        ],
        "by_mizaj": {
            "صفراوی": "مصرف خرفه، کاهو، آب‌لیمو.",
            "دموی": "مصرف آلو، انجیر.",
            "بلغمی": "مصرف گرمی‌جات و دارچین.",
            "سوداوی": "مصرف روغن زیتون، انجیر، خرما."
        },
        "spiritual": ["پیامبر (ص): «بر شما باد به خوردن انجیر»"]
    },
    "اضطراب": {
        "definition": "حالت نگرانی که ناشی از سودا یا خشکی مغز است.",
        "general": ["تنفس عمیق", "پیاده‌روی در طبیعت", "کاهش کافئین", "خواب منظم"],
        "herbs": [
            {"name": "اسطوخودوس", "usage": "دم‌کرده روزی ۱-۲ لیوان"},
            {"name": "بابونه", "usage": "دم‌کرده قبل از خواب"},
            {"name": "گل گاوزبان", "usage": "دم‌کرده با عسل"},
        ],
        "by_mizaj": {
            "صفراوی": "پرهیز از تندی. مصرف کاسنی.",
            "دموی": "حجامت، کاهش گوشت قرمز.",
            "بلغمی": "مصرف دارچین، زنجبیل.",
            "سوداوی": "مصرف زعفران، گاوزبان، ورزش ملایم."
        },
        "spiritual": ["قرآن: «الا بذکر الله تطمئن القلوب»"]
    }
}


def get_treatment(disease, mizaj):
    if disease not in DISEASE_KNOWLEDGE:
        return None
    kb = DISEASE_KNOWLEDGE[disease]
    return {
        "definition": kb["definition"],
        "general": kb["general"],
        "herbs": kb["herbs"],
        "mizaj_advice": kb["by_mizaj"].get(mizaj, "توصیه خاصی ثبت نشده."),
        "spiritual": kb.get("spiritual", [])
    }


# ============================================================
# ۶. FastAPI App
# ============================================================
app = FastAPI(title="Teb AI - ربات طب سنتی و اسلامی")
# اضافه کردن CORS برای اجازه دسترسی از مرورگرها و پنل React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterInput(BaseModel):
    name: str
    phone: str
    referral_code: str = ""


class AnswerInput(BaseModel):
    question_id: str
    answer: str


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

@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    """صفحه چت کاربران"""
    try:
        with open("chat.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>صفحه یافت نشد</h1>", status_code=404)


@app.get("/")
def root():
    return RedirectResponse(url="/chat")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/register")
async def register(data: RegisterInput):
    if len(data.phone) != 11 or not data.phone.isdigit():
        raise HTTPException(400, "شماره موبایل نامعتبر است")

    result = register_user(data.name, data.phone, data.referral_code)
    user = result["user"]

    db = SessionLocal()
    try:
        in_progress = db.query(Visit).filter_by(user_id=user.id, status="in_progress").first()
        if in_progress:
            visit = in_progress
            resumed = True
        else:
            visit_number = (user.completed_visits or 0) + 1
            if (user.free_credits or 0) > 0:
                must_pay = False
                used_credit = True
                payment_status = "free"
                amount = 0
            else:
                must_pay = (visit_number % 2 == 1)
                used_credit = False
                payment_status = "pending" if must_pay else "free"
                amount = VISIT_PRICE if must_pay else 0

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


@app.get("/visits/{visit_id}/questions")
def get_questions(visit_id: str):
    questions = [
        {"id": "name", "text": "نام شما چیست؟", "type": "text"},
        {"id": "age", "text": "سن شما چند سال است؟", "type": "number"},
        {"id": "gender", "text": "جنسیت شما؟", "type": "choice", "options": ["مرد", "زن"]},
        {"id": "weight", "text": "وزن شما (کیلوگرم)؟", "type": "number"},
        {"id": "height", "text": "قد شما (سانتی‌متر)؟", "type": "number"},
        {"id": "body_temp", "text": "معمولاً بدن شما چگونه است؟", "type": "choice", "options": ["گرم", "سرد", "معتدل"]},
        {"id": "skin", "text": "پوست شما چگونه است؟", "type": "choice", "options": ["خشک", "چرب", "معمولی", "مخلوط"]},
        {"id": "sleep", "text": "خواب شما چگونه است؟", "type": "choice", "options": ["کم و سبک", "زیاد و سنگین", "معمولی", "بی‌خوابی"]},
        {"id": "digestion", "text": "هضم غذا چگونه است؟", "type": "choice", "options": ["سریع", "کند", "معمولی", "نفخ و سنگینی"]},
        {"id": "thirst", "text": "میزان تشنگی شما؟", "type": "choice", "options": ["زیاد", "کم", "معمولی"]},
        {"id": "mood", "text": "حال روحی معمول شما؟", "type": "choice", "options": ["عصبی و پرانرژی", "آرام و کم‌حرف", "مضطرب", "شاد و اجتماعی"]},
        {"id": "stool", "text": "وضعیت دفع شما؟", "type": "choice", "options": ["یبوست", "اسهال", "معمولی", "متغیر"]},
        {"id": "hair", "text": "وضعیت موهای شما؟", "type": "choice", "options": ["ریزش زیاد", "خشک و شکننده", "چرب", "معمولی"]},
        {"id": "energy", "text": "سطح انرژی روزانه شما؟", "type": "choice", "options": ["بالا", "پایین", "متوسط", "متغیر"]},
        {"id": "appetite", "text": "اشتهای شما چگونه است؟", "type": "choice", "options": ["زیاد", "کم", "معمولی", "متغیر"]},
        {"id": "complaint", "text": "مشکل اصلی شما چیست؟", "type": "text"},
    ]
    return {"questions": questions, "total": len(questions)}


@app.post("/visits/{visit_id}/answer")
def submit_answer(visit_id: str, data: AnswerInput):
    db = SessionLocal()
    try:
        visit = db.query(Visit).filter_by(id=visit_id).first()
        if not visit:
            raise HTTPException(404, "ویزیت یافت نشد")

        session_data = visit.session_data or {}
        answers = session_data.get("answers", {})
        answers[data.question_id] = data.answer
        session_data["answers"] = answers
        visit.session_data = session_data
        visit.progress_step = len(answers)
        db.commit()
        return {"status": "ok", "answered": len(answers)}
    finally:
        db.close()


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
        bmi, bmi_cat = calculate_bmi(answers.get("weight"), answers.get("height"))
        disease, _ = detect_disease(answers.get("complaint", ""))

        report = []
        report.append(f"سلام {answers.get('name', user.name)} عزیز، تحلیل شما آماده است:\n")
        report.append(f"🔥 مزاج غالب: {mizaj_data['mizaj']} ({mizaj_data['hot_cold']} و {mizaj_data['wet_dry']})")
        if bmi:
            report.append(f"⚖️ BMI: {bmi} ({bmi_cat})")

        if disease:
            t = get_treatment(disease, mizaj_data["mizaj"])
            if t:
                report.append(f"\n🩺 تشخیص احتمالی: {disease}\n{t['definition']}\n")
                report.append("✅ توصیه‌های عمومی:")
                for g in t["general"]:
                    report.append(f"• {g}")
                report.append("\n🌱 گیاهان دارویی:")
                for h in t["herbs"]:
                    report.append(f"• {h['name']}: {h['usage']}")
                report.append(f"\n🎯 توصیه اختصاصی مزاج {mizaj_data['mizaj']}: {t['mizaj_advice']}")
                if t["spiritual"]:
                    report.append("\n📖 از قرآن و حدیث:")
                    for s in t["spiritual"]:
                        report.append(f"• {s}")

        report.append("\n⚠️ هشدار: این تحلیل جایگزین تشخیص پزشک نیست.")

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

        cv = user.completed_visits
        if cv >= 20: user.loyalty_tier = "platinum"
        elif cv >= 10: user.loyalty_tier = "gold"
        elif cv >= 5: user.loyalty_tier = "silver"
        else: user.loyalty_tier = "bronze"

        referral_reward = None
        if user.referred_by and not user.referral_confirmed and visit.payment_status == "paid":
            user.referral_confirmed = True
            referrer = db.query(User).filter_by(referral_code=user.referred_by).first()
            if referrer:
                new_count = (referrer.confirmed_referrals or 0) + 1
                if new_count >= REFERRALS_NEEDED:
                    referrer.confirmed_referrals = new_count - REFERRALS_NEEDED
                    referrer.free_credits = (referrer.free_credits or 0) + 1
                    referral_reward = {"referrer_name": referrer.name, "reward": "free"}
                    await manager.send(str(referrer.id), {
                        "title": "🎁 تبریک!",
                        "message": f"{referrer.name} عزیز، یک نوبت رایگان دریافت کردید!"
                    })
                else:
                    referrer.confirmed_referrals = new_count
                    referral_reward = {"referrer_name": referrer.name, "progress": new_count}

        db.commit()

        await manager.send(str(user.id), {
            "title": "✅ تحلیل آماده شد",
            "message": f"تحلیل ویزیت #{visit.visit_number} شما آماده است."
        })

        return {
            "report": "\n".join(report),
            "mizaj": mizaj_data,
            "bmi": bmi,
            "disease": disease,
            "visit_number": visit.visit_number,
            "referral_reward": referral_reward,
            "loyalty_tier": user.loyalty_tier,
        }
    finally:
        db.close()


@app.get("/users/{user_id}/history")
def user_history(user_id: str):
    db = SessionLocal()
    try:
        visits = db.query(Visit).filter_by(user_id=user_id).order_by(Visit.visit_number).all()
        return [{
            "visit_number": v.visit_number,
            "status": v.status,
            "payment_status": v.payment_status,
            "amount": v.final_amount,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "completed_at": v.completed_at.isoformat() if v.completed_at else None,
        } for v in visits]
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
            "referred_list": [{
                "name": u.name,
                "confirmed": u.referral_confirmed,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            } for u in referred]
        }
    finally:
        db.close()


@app.websocket("/ws/notifications/{user_id}")
async def notifications_ws(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
