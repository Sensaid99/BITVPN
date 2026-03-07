# -*- coding: utf-8 -*-
"""
API для Mini App Bit VPN: проверка initData и выдача данных пользователя и подписки.
Запуск (из корня проекта): uvicorn api_miniapp:app --host 0.0.0.0 --port 8765
Или: python -m uvicorn api_miniapp:app --host 0.0.0.0 --port 8765
"""

import os
import sys
import json
import hmac
import hashlib
import logging
from urllib.parse import unquote
from datetime import datetime

import requests

# Корень проекта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bit VPN Mini App API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.warning("BOT_TOKEN not set — initData validation will fail")


def validate_init_data(init_data: str) -> dict | None:
    """Validate Telegram Web App initData, return parsed dict or None."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = {}
        hash_val = ""
        for chunk in init_data.split("&"):
            if "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            value = unquote(value)
            if key == "hash":
                hash_val = value
                continue
            parsed[key] = value
        if not hash_val:
            return None
        data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        secret = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if expected != hash_val:
            return None
        return parsed
    except Exception as e:
        logger.debug("validate_init_data: %s", e)
        return None


def get_telegram_user_from_init(parsed: dict) -> tuple[int | None, dict | None]:
    """Extract telegram user id and dict from validated init_data (user is JSON string). Returns (telegram_id, user_dict)."""
    user_str = parsed.get("user")
    if not user_str:
        return None, None
    try:
        user = json.loads(user_str)
        return int(user.get("id")), user
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, None


def fetch_telegram_photo_url(telegram_id: int) -> str | None:
    """Get user profile photo URL from Telegram Bot API. Returns URL or None."""
    if not BOT_TOKEN or not telegram_id:
        return None
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
            params={"user_id": telegram_id, "limit": 1},
            timeout=3,
        )
        data = r.json() if r.ok else {}
        if not data.get("ok"):
            return None
        photos = data.get("result", {}).get("photos", [])
        if not photos or not photos[0]:
            return None
        # last size is the largest
        file_id = photos[0][-1].get("file_id")
        if not file_id:
            return None
        r2 = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=3,
        )
        data2 = r2.json() if r2.ok else {}
        if not data2.get("ok"):
            return None
        path = data2.get("result", {}).get("file_path")
        if not path:
            return None
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    except Exception as e:
        logger.debug("fetch_telegram_photo_url: %s", e)
        return None


# Импорт БД после добавления пути
from bot.config.settings import Config, SUBSCRIPTION_PLANS
from bot.models.database import DatabaseManager, User, Payment
from bot.utils.helpers import format_date, get_server_flag, get_plan_duration_key

db_manager = DatabaseManager(Config.DATABASE_URL)


@app.on_event("startup")
def on_startup():
    """Создать таблицы в БД при старте (важно для Render с новой PostgreSQL)."""
    try:
        db_manager.create_tables()
        logger.info("Database tables ensured")
    except Exception as e:
        logger.warning("create_tables: %s", e)


# Базовый = только 1 месяц на 1 устройство. Премиум = остальные тарифы (3+ устройств или 3+ мес).
def get_subscription_status(plan_type: str) -> str | None:
    """Return 'basic', 'premium' or None from plan_type (e.g. 1_month_1, 6_months_3)."""
    if not plan_type:
        return None
    parts = plan_type.split("_")
    # devices: суффикс _N в конце
    devices = 1
    if parts and parts[-1].isdigit():
        devices = int(parts[-1])
        parts = parts[:-1]
    duration_key = "_".join(parts) if parts else plan_type
    months_map = {"1_month": 1, "3_months": 3, "6_months": 6, "9_months": 9, "12_months": 12}
    months = months_map.get(duration_key, 1)
    if months == 1 and devices == 1:
        return "basic"
    if months >= 1 and (devices >= 3 or months >= 3):
        return "premium"
    return "premium"  # 1 month, 5 or 10 devices etc.


def plan_type_to_name(plan_type: str) -> str:
    """Human-readable plan name (6_months_3 -> 6 месяцев)."""
    key = get_plan_duration_key(plan_type)
    return SUBSCRIPTION_PLANS.get(key, {}).get("name", plan_type.replace("_", " "))


def plans_for_miniapp():
    """Return subscription plans for Mini App (prices in rubles, keys)."""
    return [
        {"key": k, "name": v["name"], "price": v["price"], "months": v.get("months", 1)}
        for k, v in SUBSCRIPTION_PLANS.items()
    ]


@app.get("/")
def root():
    """API на Render; мини-приложение — на Vercel (WEBAPP_URL в .env)."""
    return {"service": "Bit VPN Mini App API", "status": "ok"}


@app.get("/health")
def health():
    """Проверка работы сервиса (для Render и мониторинга)."""
    return {"service": "Bit VPN Mini App API", "status": "ok"}


@app.post("/api/miniapp/me")
async def miniapp_me(request: Request):
    """
    Accept Telegram initData (JSON body: {"initData": "..."} or header X-Telegram-Init-Data),
    validate and return user + subscription for Mini App.
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    init_data = (body.get("initData") or request.headers.get("X-Telegram-Init-Data") or "").strip()
    if not init_data:
        raise HTTPException(status_code=400, detail="initData required")

    parsed = validate_init_data(init_data)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid initData")

    telegram_id, init_user = get_telegram_user_from_init(parsed)
    if not telegram_id:
        raise HTTPException(status_code=400, detail="user not in initData")

    def user_row(u):
        out = {
            "telegram_id": u.telegram_id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "username": u.username,
            "referral_code": getattr(u, "referral_code", None) or "",
        }
        photo = fetch_telegram_photo_url(u.telegram_id)
        if photo:
            out["photo_url"] = photo
        return out

    def init_user_row():
        row = {
            "telegram_id": telegram_id,
            "first_name": (init_user or {}).get("first_name"),
            "last_name": (init_user or {}).get("last_name"),
            "username": (init_user or {}).get("username"),
        }
        if init_user and "photo_url" in init_user:
            row["photo_url"] = init_user.get("photo_url")
        else:
            photo = fetch_telegram_photo_url(telegram_id)
            if photo:
                row["photo_url"] = photo
        return row

    session = db_manager.get_session()
    try:
        from bot.models.database import User
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return {
                "ok": True,
                "user": init_user_row(),
                "subscription": None,
                "subscription_status": None,
            }

        _ = list(user.subscriptions)  # load relationship
        sub = user.active_subscription
        subscriptions_list = [
            {
                "plan_type": s.plan_type,
                "plan_name": plan_type_to_name(s.plan_type),
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "end_date_formatted": format_date(s.end_date) if s.end_date else None,
                "days_remaining": getattr(s, "days_remaining", None),
                "is_active": s.is_active and (s.end_date and s.end_date > datetime.utcnow()),
                "server_location": s.server_location or "",
            }
            for s in user.subscriptions
        ]
        payments_rows = session.query(Payment).filter_by(user_id=user.id).order_by(Payment.completed_at.desc()).limit(20).all()
        payments_list = [
            {
                "id": pay.id,
                "amount_rubles": pay.amount_rubles,
                "plan_type": pay.plan_type or "",
                "status": pay.status or "",
                "completed_at": pay.completed_at.isoformat() if pay.completed_at else None,
            }
            for pay in payments_rows
        ]
        if not sub:
            return {
                "ok": True,
                "user": user_row(user),
                "subscription": None,
                "subscription_status": None,
                "subscriptions": subscriptions_list,
                "payments": payments_list,
            }

        status = get_subscription_status(sub.plan_type)
        return {
            "ok": True,
            "user": user_row(user),
            "subscription": {
                "plan_type": sub.plan_type,
                "plan_name": plan_type_to_name(sub.plan_type),
                "end_date": sub.end_date.isoformat() if sub.end_date else None,
                "end_date_formatted": format_date(sub.end_date) if sub.end_date else None,
                "days_remaining": sub.days_remaining,
                "server_location": sub.server_location or "",
                "server_flag": get_server_flag(sub.server_location or "") if sub.server_location else "🌍",
            },
            "subscription_status": status,
            "subscriptions": subscriptions_list,
            "payments": payments_list,
        }
    finally:
        session.close()


@app.get("/api/miniapp/plans")
async def miniapp_plans():
    """Return subscription plans (prices) for Mini App — single source of truth."""
    return {"ok": True, "plans": plans_for_miniapp()}
