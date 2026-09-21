# -*- coding: utf-8 -*-
"""
مدل‌های دیتابیس + اتصال به PostgreSQL / SQLite (نسخه Sync)
"""
import os
import uuid
import secrets
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, Boolean, BigInteger,
    DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, sessionmaker
from passlib.hash import bcrypt

# ---------- اتصال به دیتابیس ----------
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    # حالت آنلاین (روی لیارا) - استفاده از PostgreSQL
    connect_args = {}
else:
    # حالت محلی (روی کامپیوتر شما) - استفاده از SQLite
    DATABASE_URL = "sqlite:///./teb_local.db"
    connect_args = {"check_same_thread": False}

# ⭐ این خط بسیار مهم است: استفاده از create_engine (نه async)
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# ⭐ خط بسیار مهم: تعریف Base
Base = declarative_base()


# ============================================================
# مدل‌ها
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
# توابع کمکی
# ============================================================
def init_db():
    """ساخت جداول + ساخت Super Admin اولیه"""
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


def get_user_by_phone(phone):
    db = SessionLocal()
    try:
        return db.query(User).filter_by(phone=phone).first()
    finally:
        db.close()


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