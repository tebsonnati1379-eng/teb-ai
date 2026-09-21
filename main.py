# -*- coding: utf-8 -*-
"""
کد اصلی FastAPI — ربات طب سنتی و اسلامی
"""
import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import (
    init_db, SessionLocal, User, Visit, Admin,
    register_user, get_user_by_phone, generate_referral_code
)
from diagnosis import detect_mizaj, calculate_bmi, detect_disease
from knowledge import get_treatment

app = FastAPI(title="Teb-AI — ربات طب سنتی و اسلامی")

VISIT_PRICE = 500_000
REFERRALS_NEEDED = 5


# ============================================================
# مدل‌های ورودی
# ============================================================
class RegisterInput(BaseModel):
    name: str
    phone: str
    referral_code: str = ""


class AnswerInput(BaseModel):
    question_id: str
    answer: str


# ============================================================
# WebSocket Manager (اعلان Real-time)
# ============================================================
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(user_id, []).append(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        if user_id in self.active:
            self.active[user_id].remove(ws)

    async def send(self, user_id: str, message: dict):
        for ws in self.active.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


# ============================================================
# Startup
# ============================================================
@app.on_event("startup")
def on_startup():
    init_db()


# ============================================================
# Endpoints
# ============================================================
@app.get("/")
def root():
    return {"status": "ok", "message": "ربات طب سنتی و اسلامی آماده به کار است 🌿"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/register")
async def register(data: RegisterInput):
    if len(data.phone) != 11 or not data.phone.isdigit():
        raise HTTPException(400, "شماره موبایل نامعتبر است")

    result = register_user(data.name, data.phone, data.referral_code)
    user = result["user"]

    # شروع یا ادامه ویزیت
    db = SessionLocal()
    try:
        in_progress = db.query(Visit).filter_by(
            user_id=user.id, status="in_progress"
        ).first()

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
        {"id": "digestion", "text": "هضم food شما چگونه است؟", "type": "choice", "options": ["سریع", "کند", "معمولی", "نفخ و سنگینی"]},
        {"id": "thirst", "text": "میزان تشنگی شما؟", "type": "choice", "options": ["زیاد", "کم", "معمولی"]},
        {"id": "mood", "text": "حال روحی معمول شما؟", "type": "choice", "options": ["عصبانی و پرانرژی", "آرام و کم‌حرف", "مضطرب", "شاد و اجتماعی"]},
        {"id": "stool", "text": "وضعیت دفع شما؟", "type": "choice", "options": ["یبوست", "اسهال", "معمولی", "متغیر"]},
        {"id": "hair", "text": "وضعیت موهای شما؟", "type": "choice", "options": ["ریزش زیاد", "خشک و شکننده", "چرب", "معمولی"]},
        {"id": "energy", "text": "سطح انرژی روزانه شما؟", "type": "choice", "options": ["بالا", "پایین", "متوسط", "متغیر"]},
        {"id": "appetite", "text": "اشتهای شما چگونه است؟", "type": "choice", "options": ["زیاد", "کم", "معمولی", "متغیر"]},
        {"id": "complaint", "text": "مشکل اصلی شما چیست؟ با جزئیات توضیح دهید.", "type": "text"},
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

        # تشخیص
        mizaj_data = detect_mizaj(answers)
        bmi, bmi_cat = calculate_bmi(answers.get("weight"), answers.get("height"))
        disease, _ = detect_disease(answers.get("complaint", ""))

        # ساخت پاسخ
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

        # به‌روزرسانی کاربر
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
        cv = user.completed_visits
        if cv >= 20: user.loyalty_tier = "platinum"
        elif cv >= 10: user.loyalty_tier = "gold"
        elif cv >= 5: user.loyalty_tier = "silver"
        else: user.loyalty_tier = "bronze"

        # ⭐ پاداش معرفی
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
                    # اعلان به معرف
                    await manager.send(str(referrer.id), {
                        "title": "🎁 تبریک!",
                        "message": f"{referrer.name} عزیز، یک نوبت رایگان دریافت کردید!"
                    })
                else:
                    referrer.confirmed_referrals = new_count
                    referral_reward = {"referrer_name": referrer.name, "progress": new_count}

        db.commit()

        # اعلان به کاربر
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