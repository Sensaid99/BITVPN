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
from fastapi.responses import Response

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


# Ленивая загрузка БД/конфига — не импортируем bot при старте, чтобы GET / и /health не падали на Vercel
_db_cache = None


def _get_db():
    """Один раз загрузить bot/БД; при ошибке вернуть None и логировать."""
    global _db_cache
    if _db_cache is not None:
        return _db_cache
    try:
        from bot.config.settings import Config as _C, SUBSCRIPTION_PLANS as _P
        from bot.models.database import DatabaseManager, User as _U, Payment as _Pay
        from bot.utils.helpers import format_date as _fd, get_server_flag as _gsf, get_plan_duration_key as _gpdk
        _url = getattr(_C, "DATABASE_URL", None) or os.getenv("DATABASE_URL")
        if not _url:
            _db_cache = {"db_manager": None, "Config": _C, "SUBSCRIPTION_PLANS": _P, "User": _U, "Payment": _Pay,
                         "format_date": _fd, "get_server_flag": _gsf, "get_plan_duration_key": _gpdk}
            return _db_cache
        dm = DatabaseManager(_url)
        dm.create_tables()
        _db_cache = {"db_manager": dm, "Config": _C, "SUBSCRIPTION_PLANS": _P, "User": _U, "Payment": _Pay,
                     "format_date": _fd, "get_server_flag": _gsf, "get_plan_duration_key": _gpdk}
        logger.info("DB/Config loaded for API")
        return _db_cache
    except Exception as e:
        import traceback
        logger.warning("DB/Config init failed (set BOT_TOKEN + DATABASE_URL in Vercel): %s\n%s", e, traceback.format_exc())
        _db_cache = {}
        return _db_cache


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


def plan_type_to_name(plan_type: str, ctx=None) -> str:
    """Human-readable plan name (6_months_3 -> 6 месяцев)."""
    ctx = ctx or _get_db()
    get_pdk = ctx.get("get_plan_duration_key") if isinstance(ctx, dict) else None
    plans = ctx.get("SUBSCRIPTION_PLANS", {}) if isinstance(ctx, dict) else {}
    if get_pdk:
        key = get_pdk(plan_type)
        return (plans or {}).get(key, {}).get("name", plan_type.replace("_", " "))
    return plan_type.replace("_", " ")


def plans_for_miniapp(ctx=None):
    """Тарифы для мини-апп — те же, что в боте (имя, цена, описание, emoji, popular, duration_days)."""
    ctx = ctx or _get_db()
    plans = ctx.get("SUBSCRIPTION_PLANS", {}) if isinstance(ctx, dict) else {}
    return [
        {
            "key": k,
            "name": v["name"],
            "price": v["price"],
            "months": v.get("months", 1),
            "duration_days": v.get("duration_days", v.get("months", 1) * 30),
            "description": v.get("description", ""),
            "emoji": v.get("emoji", "📦"),
            "popular": bool(v.get("popular")),
        }
        for k, v in (plans or {}).items()
    ]


def pricing_for_miniapp():
    """Ценообразование (база по устройствам, скидка) — как в боте, для единой формулы в мини-апп."""
    try:
        from bot.config.settings import DEVICE_BASE_PRICE
        return {
            "device_base_price": DEVICE_BASE_PRICE,
            "discount_per_3_months": 5,
            "device_options": list(DEVICE_BASE_PRICE.keys()) if isinstance(DEVICE_BASE_PRICE, dict) else [1, 3, 5, 10],
        }
    except Exception:
        return {
            "device_base_price": {1: 100, 3: 150, 5: 250, 10: 450},
            "discount_per_3_months": 5,
            "device_options": [1, 3, 5, 10],
        }


def config_for_miniapp():
    """Общие настройки для мини-апп (поддержка, рефералы) — из того же .env, что и бот."""
    try:
        from bot.config.settings import Config
        return {
            "support_username": (getattr(Config, "SUPPORT_USERNAME", None) or os.getenv("SUPPORT_USERNAME") or "").strip() or None,
            "referral_bonus_percent": int(getattr(Config, "REFERRAL_BONUS_PERCENT", None) or os.getenv("REFERRAL_BONUS_PERCENT", "10") or "10"),
            "referral_min_payout": int(getattr(Config, "REFERRAL_MIN_PAYOUT", None) or os.getenv("REFERRAL_MIN_PAYOUT", "100") or "100"),
        }
    except Exception:
        return {
            "support_username": (os.getenv("SUPPORT_USERNAME") or "").strip() or None,
            "referral_bonus_percent": 10,
            "referral_min_payout": 100,
        }


# Мини-приложение: на Vercel главная отдаётся из public/index.html (rewrite в vercel.json).
# Если запрос всё же попал в функцию — отдаём HTML без FileResponse (чтобы не падать).
def _read_webapp_html():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp", "index.html")
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        logger.warning("serve_webapp read: %s", e)
    return None


_MINIMAL_HTML = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bit VPN</title></head><body><p>Bit VPN</p><p>Загрузка… Проверьте настройки Vercel (BOT_TOKEN, DATABASE_URL) и наличие public/index.html.</p></body></html>"""


@app.get("/")
@app.get("/index.html")
def serve_webapp():
    """Отдаём HTML с Content-Type: text/html, чтобы Telegram открывал как Web App. Без FileResponse — не падаем на Vercel."""
    html = _read_webapp_html()
    if html:
        return Response(content=html, media_type="text/html")
    return Response(content=_MINIMAL_HTML, media_type="text/html")


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
    try:
        ctx = _get_db()
        db_manager = ctx.get("db_manager") if isinstance(ctx, dict) else None
        User = ctx.get("User") if isinstance(ctx, dict) else None
        Payment = ctx.get("Payment") if isinstance(ctx, dict) else None
        format_date = ctx.get("format_date") if isinstance(ctx, dict) else None
        get_server_flag = ctx.get("get_server_flag") if isinstance(ctx, dict) else None
        if not db_manager or not User:
            raise HTTPException(status_code=503, detail="Database not configured. Set BOT_TOKEN and DATABASE_URL in Vercel.")
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
                "total_referrals": getattr(u, "total_referrals", 0) or 0,
                "referral_balance": float(getattr(u, "referral_balance", 0) or 0),
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
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                return {
                    "ok": True,
                    "user": init_user_row(),
                    "subscription": None,
                    "subscription_status": None,
                    "referral_invited_count": 0,
                    "referral_balance": 0,
                    "referral_bonus_days": 0,
                }

            _ = list(user.subscriptions)
            sub = user.active_subscription
            subscriptions_list = [
                {
                    "plan_type": s.plan_type,
                    "plan_name": plan_type_to_name(s.plan_type, ctx),
                    "end_date": s.end_date.isoformat() if s.end_date else None,
                    "end_date_formatted": format_date(s.end_date) if format_date and s.end_date else None,
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
                    "plan_name": plan_type_to_name(pay.plan_type or "", ctx),
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
                    "referral_invited_count": getattr(user, "total_referrals", 0) or 0,
                    "referral_balance": float(getattr(user, "referral_balance", 0) or 0),
                    "referral_bonus_days": 0,
                }

            status = get_subscription_status(sub.plan_type)
            return {
                "ok": True,
                "user": user_row(user),
                "referral_invited_count": getattr(user, "total_referrals", 0) or 0,
                "referral_balance": float(getattr(user, "referral_balance", 0) or 0),
                "referral_bonus_days": 0,
                "subscription": {
                    "plan_type": sub.plan_type,
                    "plan_name": plan_type_to_name(sub.plan_type, ctx),
                    "end_date": sub.end_date.isoformat() if sub.end_date else None,
                    "end_date_formatted": format_date(sub.end_date) if format_date and sub.end_date else (sub.end_date.isoformat() if sub.end_date else None),
                    "days_remaining": sub.days_remaining,
                    "server_location": sub.server_location or "",
                    "server_flag": get_server_flag(sub.server_location or "") if get_server_flag and sub.server_location else "🌍",
                },
                "subscription_status": status,
                "subscriptions": subscriptions_list,
                "payments": payments_list,
            }
        finally:
            session.close()
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.exception("miniapp_me failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal error. Check Vercel logs.")


@app.get("/api/miniapp/plans")
async def miniapp_plans():
    """Тарифы, цены и настройки для мини-апп — единый источник с ботом (тарифы, цены, поддержка, рефералы)."""
    try:
        ctx = _get_db()
        if not ctx.get("SUBSCRIPTION_PLANS"):
            raise HTTPException(status_code=503, detail="Config not loaded. Set BOT_TOKEN and DATABASE_URL in Vercel.")
        return {
            "ok": True,
            "plans": plans_for_miniapp(ctx),
            "pricing": pricing_for_miniapp(),
            "config": config_for_miniapp(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("miniapp_plans failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal error. Check Vercel logs.")
