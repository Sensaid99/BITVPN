# -*- coding: utf-8 -*-
"""
API для Mini App Bit VPN: проверка initData и выдача данных пользователя и подписки.
Запуск (из корня проекта): uvicorn api_miniapp:app --host 0.0.0.0 --port 8765
Или: python -m uvicorn api_miniapp:app --host 0.0.0.0 --port 8765
"""

import os
import sys
import json
import base64
import hmac
import hashlib
import logging
from urllib.parse import unquote, quote, urlparse, urlunparse
from datetime import datetime, timedelta

import requests

# Корень проекта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse, HTMLResponse, RedirectResponse

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


@app.middleware("http")
async def log_every_request(request: Request, call_next):
    """Пишем в лог каждый запрос — чтобы в консоли было видно, что API вызывают."""
    logger.info(">>> %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


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
    """Общие настройки для мини-апп (поддержка, рефералы, bot_username, server_count) — из того же .env, что и бот."""
    try:
        from bot.config.settings import Config
        sc = os.getenv("SERVER_COUNT", "")
        try:
            server_count = int(sc) if sc else 50
        except ValueError:
            server_count = 50
        bypass_raw = os.getenv("MINIAPP_BYPASS_USER_IDS", "").strip()
        bypass_ids = []
        if bypass_raw:
            for part in bypass_raw.replace(",", " ").split():
                part = part.strip()
                if part.isdigit():
                    bypass_ids.append(int(part))
        return {
            "support_username": (getattr(Config, "SUPPORT_USERNAME", None) or os.getenv("SUPPORT_USERNAME") or "").strip() or None,
            "referral_bonus_percent": int(getattr(Config, "REFERRAL_BONUS_PERCENT", None) or os.getenv("REFERRAL_BONUS_PERCENT", "10") or "10"),
            "referral_min_payout": int(getattr(Config, "REFERRAL_MIN_PAYOUT", None) or os.getenv("REFERRAL_MIN_PAYOUT", "100") or "100"),
            "bot_username": (getattr(Config, "BOT_USERNAME", None) or os.getenv("BOT_USERNAME") or "").strip() or None,
            "server_count": server_count,
            "miniapp_bypass_user_ids": bypass_ids,
        }
    except Exception:
        bypass_raw = os.getenv("MINIAPP_BYPASS_USER_IDS", "").strip()
        bypass_ids = [int(x) for x in bypass_raw.replace(",", " ").split() if x.strip().isdigit()] if bypass_raw else []
        return {
            "support_username": (os.getenv("SUPPORT_USERNAME") or "").strip() or None,
            "referral_bonus_percent": 10,
            "referral_min_payout": 100,
            "bot_username": (os.getenv("BOT_USERNAME") or "").strip() or None,
            "server_count": 50,
            "miniapp_bypass_user_ids": bypass_ids,
        }


# Мини-приложение: на Vercel главная отдаётся из public/index.html (rewrite в vercel.json).
# Если запрос всё же попал в функцию — отдаём HTML без FileResponse (чтобы не падать).
def _read_webapp_html():
    base = os.path.dirname(os.path.abspath(__file__))
    for rel in ("webapp", "public"):
        path = os.path.join(base, rel, "index.html")
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logger.warning("serve_webapp read %s: %s", path, e)
    return None


_MINIMAL_HTML = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bit VPN</title></head><body><p>Bit VPN</p><p><a href="https://t.me/Bitvpnproxy_bot">Открыть в Telegram</a></p></body></html>"""


@app.get("/")
@app.get("/index.html")
def serve_webapp():
    """Отдаём HTML с Content-Type: text/html. При любой ошибке — 200 и минимальная страница (без 500)."""
    try:
        html = _read_webapp_html()
        if html:
            return Response(content=html, media_type="text/html")
    except Exception as e:
        logger.warning("serve_webapp: %s", e)
    return Response(content=_MINIMAL_HTML, media_type="text/html")


@app.get("/health")
def health():
    """Проверка работы сервиса (для Render и мониторинга)."""
    return {"service": "Bit VPN Mini App API", "status": "ok"}


@app.get("/api/health")
def health_under_api_prefix():
    """
    Тот же health, но под префиксом /api/ — чтобы проверка работала за типовым nginx,
    который проксирует только /api/ и /sub/, а корень отдаёт статику (иначе GET /health → 404).
    """
    return health()


REDIRECT_TO_APP_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Открытие приложения</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#fff;margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;box-sizing:border-box;}
.text{margin-bottom:20px;text-align:center;max-width:320px;}
.btn{display:inline-block;padding:14px 28px;background:#3b82f6;color:#fff;text-decoration:none;border-radius:12px;font-weight:600;margin-top:12px;}
.fallback{display:none;}</style></head>
<body>
<p class="text" id="msg">Перенаправление в приложение…</p>
<div class="text fallback" id="fallback">
  <p>Автоматическое открытие не сработало. Нажмите кнопку ниже для открытия приложения.</p>
  <a id="openBtn" class="btn" href="#">Открыть вручную</a>
</div>
<script>
(function(){
  var p = new URLSearchParams(location.search).get("url");
  if (!p) { document.getElementById("msg").textContent = "Нет ссылки для открытия."; return; }
  var r = new URLSearchParams(location.search).get("return_url");
  var returnUrl = r || '';
  try { returnUrl = decodeURIComponent(r); } catch (e) {}
  // URLSearchParams уже возвращает декодированное значение.
  var target = p;
  try { target = decodeURIComponent(p); } catch (e) {}

  function go(){
    try { window.location.replace(target); } catch (e0) {}
    try { window.location.href = target; } catch (e1) {}
    try { window.location.assign(target); } catch (e2) {}
    // Клик по скрытой ссылке иногда проходит лучше для custom scheme.
    try {
      var a = document.createElement('a');
      a.href = target;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e3) {}
    try {
      var btn = document.getElementById('openBtn');
      if (btn) { btn.href = target; btn.click(); }
    } catch (e4) {}
  }

  // Пытаемся открыть сразу (в идеале всё ещё в контексте клика пользователя).
  go();

  var wentHidden = false;
  try {
    document.addEventListener('visibilitychange', function() {
      if (document.hidden) wentHidden = true;
    });
  } catch (e) {}

  setTimeout(function(){
    if (returnUrl) {
      // Быстрый возврат на страницу мини-аппа, чтобы не показывать "синий экран"
      // и не ломать пользователю сценарий.
      if (!wentHidden) {
        try { window.location.replace(returnUrl); } catch (e2) {}
      }
      return;
    }
    document.getElementById("msg").style.display = "none";
    document.getElementById("fallback").style.display = "block";
    document.getElementById("openBtn").href = target;
  }, 900);
})();
</script></body></html>"""


@app.get("/api/miniapp/redirect-to-app", response_class=HTMLResponse)
def redirect_to_app(url: str = ""):
    """
    Страница перенаправления: открывает ссылку подписки (как ASB).
    Браузер переходит по ссылке — на мобильном может предложить «Открыть в Happ».
    Если не сработало — показывается кнопка «Открыть вручную».
    """
    return HTMLResponse(content=REDIRECT_TO_APP_HTML)


def _rewrite_subscription_remark(raw: bytes, display_name: str, description: str | None, provider_id: str | None = None) -> bytes:
    """
    Подменяет имя (ps/remark) в контенте подписки, чтобы в Happ отображалось SUBSCRIPTION_DISPLAY_NAME
    и описание (как у LastdepVPN), без домена. Подключение остаётся к серверу из ссылок (95.181.175.67).
    Если передан provider_id (HAPP_PROVIDER_CODE), в начало тела подписки добавляется комментарий
    #providerid {id} — по документации Happ это нужно для учёта устройств и проверки на check.happ-proxy.com.
    """
    if not raw or not display_name:
        return raw
    remark = display_name.strip()
    if description:
        # Убираем лишние переносы и склеиваем в одну строку — в Happ так описание выглядит аккуратнее
        desc = " ".join(s.strip() for s in description.strip().replace("\r", "\n").split("\n") if s.strip())
        if desc:
            remark = remark + "\n" + desc
    try:
        decoded = base64.standard_b64decode(raw).decode("utf-8", errors="replace")
    except Exception:
        # Если upstream не base64-контент — не портим ответ.
        return raw
    # Защита: если в decoded нет признаков формата подписки,
    # значит upstream отдал не то, что мы ожидаем; возвращаем как есть.
    if not any(x in decoded for x in ["vmess://", "vless://", "trojan://", "ss://"]):
        return raw
    lines = [s.strip() for s in decoded.replace("\r", "\n").split("\n") if s.strip()]
    out = []
    for line in lines:
        try:
            if line.startswith("vmess://"):
                payload_b64 = line[8:].strip()
                payload = base64.standard_b64decode(payload_b64).decode("utf-8", errors="replace")
                obj = json.loads(payload)
                obj["ps"] = remark
                out.append("vmess://" + base64.standard_b64encode(json.dumps(obj, ensure_ascii=False).encode()).decode())
                continue
            if "vless://" in line or "trojan://" in line or line.startswith("ss://"):
                parsed = urlparse(line)
                # Фрагмент после # — только текст названия (без "ps="), иначе Happ показывает "ps=BIT VPN" буквально
                new_frag = quote(remark, safe="")
                new = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, new_frag))
                out.append(new)
                continue
        except Exception:
            pass
        out.append(line)
    if not out:
        return raw
    text = "\n".join(out)
    if provider_id and provider_id.strip():
        text = "#providerid " + provider_id.strip() + "\n" + text
    return base64.standard_b64encode(text.encode("utf-8"))


@app.get("/sub/{install_code:path}")
def sub_redirect(install_code: str, request: Request):
    """
    Отдаёт контент подписки по ссылке без installid в адресе: https://ваш-домен/sub/КОД.
    Сначала пробуем вернуть контент подписки напрямую (чтобы работало в Happ и других клиентах,
    которые не переходят по редиректу). При прокси подменяем имя и описание (SUBSCRIPTION_DISPLAY_NAME/DESCRIPTION).
    Если не удалось — редирект 302.
    """
    import re
    code = (install_code or "").strip().split("/")[0]
    if not code or not re.match(r"^[A-Za-z0-9]{12}$", code):
        raise HTTPException(status_code=404, detail="Invalid or missing install code")
    try:
        from bot.config.settings import Config
        base = (getattr(Config, "HAPP_SUBSCRIPTION_URL", None) or os.environ.get("HAPP_SUBSCRIPTION_URL") or "").strip().rstrip("/")
        if not base:
            raise HTTPException(status_code=503, detail="Subscription URL not configured")
        if base.lower().startswith("happ://"):
            raise HTTPException(status_code=404, detail="Direct Happ link in use; /sub/ redirect not available")
        target = f"{base}?installid={code}" if "?" not in base else f"{base}&installid={code}"
        display_name = (getattr(Config, "SUBSCRIPTION_DISPLAY_NAME", None) or os.environ.get("SUBSCRIPTION_DISPLAY_NAME") or "BIT VPN").strip()
        description = (getattr(Config, "SUBSCRIPTION_DESCRIPTION", None) or os.environ.get("SUBSCRIPTION_DESCRIPTION") or "").strip() or None
        if description and "\\n" in description:
            description = description.replace("\\n", "\n")
        # Проксируем контент подписки, чтобы клиенты (Happ и др.) получали конфиг без перехода по редиректу
        provider_code = (getattr(Config, "HAPP_PROVIDER_CODE", None) or os.environ.get("HAPP_PROVIDER_CODE") or "").strip()
        try:
            r = requests.get(target, timeout=15, headers={"User-Agent": request.headers.get("User-Agent", "BitVPN-MiniApp/1.0")})
            if r.status_code == 200 and r.content:
                content = _rewrite_subscription_remark(r.content, display_name, description, provider_id=provider_code or None)
                # Happ на iOS иногда капризничает с обработкой content-type/заголовков, поэтому
                # явно задаём text/plain + Content-Disposition.
                out_headers = {}
                if provider_code:
                    out_headers["providerid"] = provider_code
                out_headers["Content-Disposition"] = f'attachment; filename="{code}.txt"'
                out_headers["Cache-Control"] = "no-store"

                content_str = content
                if isinstance(content, (bytes, bytearray)):
                    content_str = content.decode("utf-8", errors="ignore")

                return Response(
                    content=content_str,
                    status_code=200,
                    media_type="text/plain; charset=utf-8",
                    headers=out_headers,
                )
        except Exception as e:
            logger.debug("sub proxy fetch failed, fallback to redirect: %s", e)
        return RedirectResponse(url=target, status_code=302)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("sub_redirect: %s", e)
        raise HTTPException(status_code=503, detail="Redirect unavailable")


@app.get("/api/miniapp/check-happ-env")
def check_happ_env():
    """
    Проверка: видит ли API переменные Happ (для отладки).
    Возвращает, какие переменные заданы, без значений.
    Вызовите в браузере: https://ваш-домен-api/api/miniapp/check-happ-env
    """
    try:
        from bot.config.settings import Config
        env = {
            "HAPP_API_URL": bool(getattr(Config, "HAPP_API_URL", None)),
            "HAPP_PROVIDER_CODE": bool(getattr(Config, "HAPP_PROVIDER_CODE", None)),
            "HAPP_AUTH_KEY": bool(getattr(Config, "HAPP_AUTH_KEY", None)),
            "HAPP_SUBSCRIPTION_URL": bool(getattr(Config, "HAPP_SUBSCRIPTION_URL", None)),
        }
        all_ok = all(env.values())
        return {
            "ok": all_ok,
            "message": "Все HAPP_* заданы. Ссылка должна генерироваться." if all_ok else "Не хватает переменных — добавьте в .env на СЕРВЕРЕ и перезапустите API.",
            "env_set": env,
        }
    except Exception as e:
        logger.warning("check_happ_env: %s", e)
        return {"ok": False, "message": str(e), "env_set": {}}


@app.get("/api/miniapp/debug-link-format")
async def debug_link_format(request: Request):
    """
    Отладка: какой redirect_base использует API для ссылок /sub/CODE.
    Откройте в браузере: https://ваш-домен-api/api/miniapp/debug-link-format
    Если redirect_base пустой или http://127.0.0.1 — на сервере задайте HAPP_SUBSCRIPTION_REDIRECT_BASE в .env
    или настройте nginx: proxy_set_header X-Forwarded-Host $host; proxy_set_header X-Forwarded-Proto $scheme;
    """
    try:
        base = _redirect_base_from_request(request)
        host = request.headers.get("Host") or ""
        x_host = request.headers.get("X-Forwarded-Host") or ""
        x_proto = request.headers.get("X-Forwarded-Proto") or ""
        return {
            "ok": True,
            "rewrite_version": "redirect_v2",
            "redirect_base": base or "(пусто — ссылка не переведётся в формат /sub/CODE)",
            "redirect_base_ok": bool(base and "127.0.0.1" not in base and "localhost" not in base),
            "headers_seen": {"Host": host, "X-Forwarded-Host": x_host, "X-Forwarded-Proto": x_proto},
            "hint": "Если redirect_base пустой или внутренний — задайте на сервере в .env: HAPP_SUBSCRIPTION_REDIRECT_BASE=https://ваш-домен и перезапустите miniapp-api. Мини-апп дергает API по адресу из ?api= (ваш сервер), не Vercel.",
        }
    except Exception as e:
        logger.warning("debug_link_format: %s", e)
        return {"ok": False, "error": str(e)}


def _country_code_to_flag(code: str) -> str:
    """RU -> 🇷🇺 (regional indicator symbols U+1F1E6..U+1F1FF)."""
    if not code or len(code) != 2:
        return ""
    code = code.upper()
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code if "A" <= c <= "Z")


# Кэш для снижения нагрузки при большом числе пользователей (см. НАГРУЗКА_МИНИАПП.md)
_my_ip_cache: dict = {}
_my_ip_cache_ttl = 600  # 10 минут — один IP не дёргаем гео-API чаще
_servers_status_cache: dict = {}
_servers_status_cache_ttl = 60  # 1 минута — пинг списка серверов раз в минуту для всех


def _geo_lookup(client_ip: str):
    """Возвращает (country_code, country_name) по IP. Сначала ipwho.is, затем ip-api.com, ipapi.co."""
    # 1) ipwho.is — стабильный, реже 403/429
    try:
        r = requests.get(f"https://ipwho.is/{client_ip}", timeout=5)
        if r.ok:
            data = r.json()
            if data.get("success") is not False:
                cc = (data.get("country_code") or "").strip()
                cn = (data.get("country") or "").strip()
                if cc and len(cc) == 2:
                    logger.info("my-ip geo ok ip=%s provider=ipwho.is country=%s code=%s", client_ip, cn, cc)
                    return (cc, cn or None)
        else:
            logger.info("my-ip geo ipwho.is ip=%s status=%s", client_ip, r.status_code)
    except Exception as e:
        logger.info("my-ip geo ipwho.is ip=%s error=%s", client_ip, e)
    # 2) ip-api.com (часто 403 с хостингов)
    try:
        r = requests.get(
            f"https://ip-api.com/json/{client_ip}?fields=country,countryCode",
            timeout=5,
        )
        if r.ok:
            data = r.json()
            cc = (data.get("countryCode") or "").strip()
            cn = (data.get("country") or "").strip()
            if cc and len(cc) == 2:
                logger.info("my-ip geo ok ip=%s provider=ip-api.com country=%s code=%s", client_ip, cn, cc)
                return (cc, cn or None)
        else:
            logger.info("my-ip geo ip-api.com ip=%s status=%s body=%s", client_ip, r.status_code, r.text[:200])
    except Exception as e:
        logger.info("my-ip geo ip-api.com ip=%s error=%s", client_ip, e)
    # 3) ipapi.co (лимит 429)
    try:
        r = requests.get(f"https://ipapi.co/{client_ip}/json/", timeout=5)
        if r.ok:
            data = r.json()
            if not data.get("error"):
                cc = (data.get("country_code") or "").strip()
                cn = (data.get("country_name") or "").strip()
                if cc and len(cc) == 2:
                    logger.info("my-ip geo ok ip=%s provider=ipapi.co country=%s code=%s", client_ip, cn, cc)
                    return (cc, cn or None)
        else:
            logger.info("my-ip geo ipapi.co ip=%s status=%s body=%s", client_ip, r.status_code, r.text[:200])
    except Exception as e:
        logger.info("my-ip geo ipapi.co ip=%s error=%s", client_ip, e)
    logger.info("my-ip geo fail ip=%s (all providers returned no country)", client_ip)
    return (None, None)


@app.get("/api/miniapp/my-ip")
async def miniapp_my_ip(request: Request):
    """
    Возвращает IP клиента и страну (по геолокации IP). Кэш по IP 10 мин.
    Гео: ip-api.com, при неудаче — ipapi.co.
    """
    try:
        # Реальный IP клиента: Vercel/Cloudflare/прокси передают в заголовках
        raw = (
            request.headers.get("x-forwarded-for")
            or request.headers.get("x-real-ip")
            or request.headers.get("cf-connecting-ip")
            or request.headers.get("true-client-ip")
        )
        client_ip = raw.split(",")[0].strip() if raw else (request.client.host if request.client else "")
        logger.info("my-ip request x-forwarded-for=%s cf-connecting-ip=%s client_ip=%s", request.headers.get("x-forwarded-for"), request.headers.get("cf-connecting-ip"), client_ip)
        # Локальный запуск (127.0.0.1): гео по тестовому IP, чтобы флаг отображался при проверке на своём компе
        geo_ip = client_ip
        if not client_ip or client_ip == "127.0.0.1":
            geo_ip = "8.8.8.8"  # для гео при локальной проверке; в ответе ip оставляем как есть
            if not client_ip:
                client_ip = "127.0.0.1"
            logger.info("my-ip local test: using geo_ip=%s for country lookup", geo_ip)
        now = datetime.utcnow()
        if geo_ip in _my_ip_cache:
            entry = _my_ip_cache[geo_ip]
            if (now - entry["ts"]).total_seconds() < _my_ip_cache_ttl:
                logger.info("my-ip cache hit ip=%s country=%s code=%s", geo_ip, entry.get("cn"), entry.get("cc"))
                return {"ok": True, "ip": client_ip, "country_code": entry.get("cc"), "country_name": entry.get("cn"), "flag": entry.get("flag")}
        cc, cn = _geo_lookup(geo_ip)
        flag = _country_code_to_flag(cc) if cc else ""
        if cc:
            _my_ip_cache[geo_ip] = {"cc": cc, "cn": cn, "flag": flag, "ts": now}
        return {"ok": True, "ip": client_ip, "country_code": cc, "country_name": cn, "flag": flag}
    except Exception as e:
        logger.info("my-ip error: %s", e)
        return {"ok": False, "ip": None, "country_code": None, "country_name": None, "flag": None}


@app.get("/api/miniapp/geo")
async def miniapp_geo(ip: str = ""):
    """
    Страна по переданному IP (для случая, когда my-ip вернул ip без страны).
    Вызов: GET /api/miniapp/geo?ip=188.233.190.15
    """
    ip = (ip or "").strip()
    if not ip or len(ip) > 45:
        return {"ok": False, "country_code": None, "country_name": None}
    now = datetime.utcnow()
    if ip in _my_ip_cache:
        entry = _my_ip_cache[ip]
        if (now - entry["ts"]).total_seconds() < _my_ip_cache_ttl:
            return {"ok": True, "country_code": entry.get("cc"), "country_name": entry.get("cn")}
    cc, cn = _geo_lookup(ip)
    if cc:
        _my_ip_cache[ip] = {"cc": cc, "cn": cn, "flag": _country_code_to_flag(cc), "ts": now}
    return {"ok": True, "country_code": cc, "country_name": cn}


@app.get("/api/miniapp/ping")
async def miniapp_ping():
    """
    Минимальный ответ для замера задержки (RTT) на клиенте. Не делает внешних запросов.
    """
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/miniapp/speed-test-file")
async def miniapp_speed_test_file():
    """
    Отдаёт 1 МБ данных для замера скорости на клиенте. Клиент замеряет время загрузки и считает Мбит/с.
    """
    size = 1024 * 1024  # 1 MB
    def chunk():
        chunk_size = 64 * 1024
        remaining = size
        while remaining > 0:
            n = min(chunk_size, remaining)
            yield b"\x00" * n
            remaining -= n
    return StreamingResponse(
        chunk(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size), "Cache-Control": "no-store"},
    )


@app.post("/api/miniapp/speed-test-upload")
async def miniapp_speed_test_upload(request: Request):
    """
    Принимает тело запроса для замера исходящей скорости. Клиент отправляет blob и по времени считает Мбит/с.
    """
    body = await request.body()
    return {"ok": True, "received": len(body)}


@app.get("/api/miniapp/servers-status")
async def miniapp_servers_status():
    """
    Проверяет список серверов из SERVER_LIST. Результат кэшируется на 60 сек — при 1000 пользователей
    не пингуем 50 серверов × 1000 раз, а один раз в минуту для всех.
    """
    try:
        now = datetime.utcnow()
        if _servers_status_cache.get("ts") and (now - _servers_status_cache["ts"]).total_seconds() < _servers_status_cache_ttl:
            return {"ok": True, "online": _servers_status_cache["online"], "total": _servers_status_cache["total"], "source": _servers_status_cache.get("source", "cache")}
        raw = (os.getenv("SERVER_LIST") or "").strip()
        if not raw:
            total = int(os.getenv("SERVER_COUNT", "50") or "50")
            try:
                total = max(0, int(total))
            except ValueError:
                total = 50
            _servers_status_cache.update({"online": total, "total": total, "source": "config", "ts": now})
            return {"ok": True, "online": total, "total": total, "source": "config"}
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if not urls:
            _servers_status_cache.update({"online": 0, "total": 0, "source": "list", "ts": now})
            return {"ok": True, "online": 0, "total": 0, "source": "list"}
        online = 0
        for url in urls:
            try:
                r = requests.head(url, timeout=2)
                if r.status_code < 400:
                    online += 1
            except Exception:
                try:
                    r = requests.get(url, timeout=2)
                    if r.status_code < 400:
                        online += 1
                except Exception:
                    pass
        _servers_status_cache.update({"online": online, "total": len(urls), "source": "ping", "ts": now})
        return {"ok": True, "online": online, "total": len(urls), "source": "ping"}
    except Exception as e:
        logger.warning("servers-status: %s", e)
        return {"ok": False, "online": 0, "total": 0, "source": "error"}


def _redirect_base_from_request(request: Request) -> str:
    """Базовый URL для редиректа /sub/CODE: из переменных окружения или из запроса (Host / X-Forwarded-*)."""
    try:
        from bot.config.settings import Config
        base = (
            getattr(Config, "HAPP_SUBSCRIPTION_REDIRECT_BASE", None)
            or os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE", "").strip()
        )
        if base:
            return base.rstrip("/")
    except Exception:
        pass
    base = os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE", "").strip()
    if base:
        return base.rstrip("/")
    try:
        host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or ""
        proto = request.headers.get("X-Forwarded-Proto") or "https"
        if host:
            return (proto or "https").strip().lower() + "://" + host.split(",")[0].strip()
        return str(request.base_url).rstrip("/")
    except Exception:
        return str(request.base_url).rstrip("/") if request else ""


@app.post("/api/miniapp/debug-subscription")
async def debug_subscription(request: Request):
    """
    Отладка «Нет подписки»: принять initData и вернуть короткий статус (есть ли пользователь,
    есть ли активная подписка). Вызовите POST с телом {"initData": "..."} — например из консоли
    мини-аппа: copy(Telegram.WebApp.initData) и вставить в тело запроса к /api/miniapp/debug-subscription.
    """
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        init_data = (body.get("initData") or request.headers.get("X-Telegram-Init-Data") or "").strip()
        if not init_data:
            return {"ok": False, "reason": "initData_required", "message": "Передайте initData в теле POST (или откройте приложение из Telegram — тогда initData подставится автоматически)."}
        parsed = validate_init_data(init_data)
        if not parsed:
            return {"ok": False, "reason": "invalid_initData", "message": "initData не прошёл проверку. Проверьте, что на сервере API в .env указан тот же BOT_TOKEN, что у бота, из которого открыто приложение."}
        telegram_id, _ = get_telegram_user_from_init(parsed)
        if not telegram_id:
            return {"ok": False, "reason": "no_user_in_initData", "message": "В initData нет пользователя."}
        ctx = _get_db()
        db_manager = ctx.get("db_manager") if isinstance(ctx, dict) else None
        User = ctx.get("User") if isinstance(ctx, dict) else None
        if not db_manager or not User:
            return {"ok": False, "reason": "db_not_configured", "message": "API: база данных не настроена (DATABASE_URL, BOT_TOKEN на сервере)."}
        session = db_manager.get_session()
        try:
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                return {
                    "ok": True,
                    "reason": "user_not_in_db",
                    "telegram_id": telegram_id,
                    "message": "Пользователь с этим Telegram ID не найден в базе. Напишите боту в Telegram /start — тогда создастся запись. Подписка появится после оплаты или выдачи админом.",
                }
            sub = user.active_subscription
            if not sub:
                subs = list(user.subscriptions)
                return {
                    "ok": True,
                    "reason": "no_active_subscription",
                    "telegram_id": telegram_id,
                    "subscriptions_count": len(subs),
                    "message": "В базе нет активной подписки (все истекли или is_active=false). Проверьте в Neon таблицу subscriptions: user_id=%s, is_active=true, end_date > сейчас." % user.id,
                }
            return {
                "ok": True,
                "reason": "has_active_subscription",
                "telegram_id": telegram_id,
                "end_date": sub.end_date.isoformat() if sub.end_date else None,
                "message": "Активная подписка есть. Если в приложении всё равно «Нет подписки» — обновите страницу или нажмите «Повторить».",
            }
        finally:
            session.close()
    except Exception as e:
        logger.warning("debug_subscription: %s", e)
        return {"ok": False, "reason": "error", "message": str(e)}


@app.get("/api/miniapp/debug-install-stats")
def debug_install_stats(install_code: str = ""):
    """
    Отладка счётчика «Подключено»: проверка, видит ли API ваш install в ответе Happ.
    Откройте в браузере: https://ваш-API/api/miniapp/debug-install-stats?install_code=XXXXXXXXXXXX
    (код из ссылки подписки — 12 символов после /sub/ в ссылке из бота).
    """
    code = (install_code or "").strip()
    if len(code) != 12 or not code.isalnum():
        return {
            "ok": False,
            "message": "Укажите install_code в query: ?install_code=XXXXXXXXXXXX (12 символов из ссылки после /sub/).",
            "example": "/api/miniapp/debug-install-stats?install_code=Abc123Def456",
        }
    try:
        from bot.config.settings import Config
        from bot.utils import happ_client
        list_url = getattr(Config, "HAPP_LIST_INSTALL_URL", None) or os.environ.get("HAPP_LIST_INSTALL_URL", "")
        api_url = (list_url or getattr(Config, "HAPP_API_URL", None) or os.environ.get("HAPP_API_URL", "") or "").strip().rstrip("/")
        pc = getattr(Config, "HAPP_PROVIDER_CODE", None) or os.environ.get("HAPP_PROVIDER_CODE", "")
        ak = getattr(Config, "HAPP_AUTH_KEY", None) or os.environ.get("HAPP_AUTH_KEY", "")
        if not api_url or not pc or not ak:
            return {"ok": False, "message": "На сервере не заданы HAPP_API_URL (или HAPP_LIST_INSTALL_URL), HAPP_PROVIDER_CODE или HAPP_AUTH_KEY.", "install_code_sent": code[:6] + "***"}
        info = happ_client.get_install_stats_debug(api_url, pc, ak, code)
        hint = ""
        if info.get("error"):
            hint = "Ошибка запроса к Happ: " + str(info["error"])
        elif info.get("rc") != 1:
            hint = "Happ вернул rc=%s, msg=%s. Проверьте HAPP_PROVIDER_CODE и HAPP_AUTH_KEY." % (info.get("rc"), info.get("msg"))
        elif not info.get("found"):
            hint = "Ваш код не найден в списке Happ (всего записей: %s). Убедитесь, что добавили в Happ именно ссылку из бота (Подписки → +). Коды в ответе (первые 6 символов): %s." % (info.get("list_total"), info.get("sample_codes"))
        else:
            hint = "Найдено. Счётчик должен отображаться в мини-аппе после обновления."
        return {
            "ok": True,
            "install_code_sent": code[:6] + "***",
            "list_install_url_used": api_url[:50] + "..." if len(api_url) > 50 else api_url,
            "found": info.get("found"),
            "install_count": info.get("install_count"),
            "install_limit": info.get("install_limit"),
            "list_total": info.get("list_total"),
            "rc": info.get("rc"),
            "raw_keys": info.get("raw_keys"),
            "first_item_keys": info.get("first_item_keys"),
            "hint": hint,
        }
    except Exception as e:
        logger.warning("debug_install_stats: %s", e)
        return {"ok": False, "message": str(e), "install_code_sent": code[:6] + "***"}


@app.get("/api/miniapp/debug-sub-content")
def debug_sub_content(install_code: str = ""):
    """
    Отладка: проксирует ли наш API подписку по /sub/{CODE} и добавляет ли ProviderID
    в контент (строка вида #providerid <HAPP_PROVIDER_CODE>).

    Вызов:
      https://ВАШ_ДОМЕН_API/api/miniapp/debug-sub-content?install_code=XXXXXXXXXXXX
    """
    code = (install_code or "").strip()
    if len(code) != 12 or not code.isalnum():
        return {
            "ok": False,
            "message": "Укажите install_code в query: ?install_code=XXXXXXXXXXXX (12 символов после /sub/).",
            "install_code_sent": code[:6] + "***",
        }
    try:
        from bot.config.settings import Config
        provider_code = (getattr(Config, "HAPP_PROVIDER_CODE", None) or os.environ.get("HAPP_PROVIDER_CODE", "") or "").strip()
        base_url = (getattr(Config, "HAPP_SUBSCRIPTION_URL", None) or os.environ.get("HAPP_SUBSCRIPTION_URL", "") or "").strip().rstrip("/")
        display_name = (getattr(Config, "SUBSCRIPTION_DISPLAY_NAME", None) or os.environ.get("SUBSCRIPTION_DISPLAY_NAME", "") or "BIT VPN").strip()
        description = (getattr(Config, "SUBSCRIPTION_DESCRIPTION", None) or os.environ.get("SUBSCRIPTION_DESCRIPTION", "") or "").strip() or None

        if not base_url:
            return {"ok": False, "message": "HAPP_SUBSCRIPTION_URL missing on API server."}
        if not provider_code:
            return {"ok": False, "message": "HAPP_PROVIDER_CODE missing on API server."}

        target = f"{base_url}?installid={code}" if "?" not in base_url else f"{base_url}&installid={code}"
        r = requests.get(target, timeout=15, headers={"User-Agent": "BitVPN-MiniApp/1.0"})
        status = r.status_code
        proxied_ok = (status == 200 and bool(r.content))
        providerid_injected = False
        snippet = ""

        if proxied_ok:
            rewritten_b64 = _rewrite_subscription_remark(r.content, display_name, description, provider_id=provider_code)
            try:
                decoded = base64.standard_b64decode(rewritten_b64).decode("utf-8", errors="replace")
                providerid_injected = ("#providerid " + provider_code) in decoded
                snippet = "\n".join(decoded.split("\n")[:6])
            except Exception:
                providerid_injected = False
        return {
            "ok": True,
            "install_code_sent": code[:6] + "***",
            "sub_target": target.split("?")[0],
            "upstream_status": status,
            "proxied_ok": proxied_ok,
            "provider_code_sent": provider_code[:6] + "***" if provider_code else None,
            "providerid_injected": providerid_injected,
            "decoded_snippet": snippet,
        }
    except Exception as e:
        logger.warning("debug_sub_content: %s", e)
        return {"ok": False, "message": str(e), "install_code_sent": code[:6] + "***"}


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
            now = datetime.utcnow()
            session.query(Payment).filter(
                Payment.user_id == user.id,
                Payment.status == "pending",
                Payment.expires_at != None,
                Payment.expires_at < now,
            ).update({"status": "expired"}, synchronize_session="fetch")
            session.commit()

            payments_rows = session.query(Payment).filter_by(user_id=user.id).order_by(Payment.completed_at.desc()).limit(20).all()
            payments_list = [
                {
                    "id": pay.id,
                    "amount_rubles": pay.amount_rubles,
                    "plan_type": pay.plan_type or "",
                    "plan_name": plan_type_to_name(pay.plan_type or "", ctx),
                    "status": pay.status or "",
                    "status_reason": "Истёк срок оплаты (30 мин)" if (pay.status or "") == "expired" else ("Ошибка оплаты" if (pay.status or "") == "failed" else None),
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
            # Ссылка для Happ — отдаём только если это URL (Happ), не отдаём WireGuard-конфиг
            vpn_cfg = getattr(sub, "vpn_config", None) or ""
            subscription_link = None
            if vpn_cfg and isinstance(vpn_cfg, str) and ("installid=" in vpn_cfg or "/sub/" in vpn_cfg or vpn_cfg.strip().startswith("http") or vpn_cfg.strip().lower().startswith("happ://")):
                subscription_link = vpn_cfg.strip()
            # Если в БД сохранён только базовый HTTP URL (без installid и без /sub/CODE) — считаем, что ссылки нет; happ:// не трогаем
            if subscription_link and "installid=" not in subscription_link and "/sub/" not in subscription_link and not subscription_link.strip().lower().startswith("happ://"):
                subscription_link = None
            # Если в БД старая ссылка с installid= — перезаписать в формат /sub/CODE (редирект) и сохранить в БД
            if subscription_link and "installid=" in subscription_link and "/sub/" not in subscription_link:
                try:
                    from bot.utils import happ_client
                    _code = happ_client.parse_install_code_from_happ_link(subscription_link)
                    redirect_base = _redirect_base_from_request(request)
                    if _code and redirect_base:
                        new_link = redirect_base.rstrip("/") + "/sub/" + _code + "?installid=" + _code
                        subscription_link = new_link
                        sub.vpn_config = new_link
                        session.commit()
                        logger.info("miniapp_me: Rewrote subscription link to redirect format for user %s -> %s/sub/***", user.telegram_id, redirect_base[:40])
                except Exception as e:
                    logger.warning("miniapp_me: rewrite to redirect link failed: %s", e)

            # Нормализация /sub/<code> ссылки под текущий домен API (важно для iOS):
            # на iOS/мобилке сертификаты для IP часто считаются недействительными,
            # из-за чего Happ добавляет подписку, но не может загрузить содержимое.
            # Поэтому всегда приводим /sub/... к redirect_base (hostname с валидным SSL).
            try:
                if subscription_link and "/sub/" in subscription_link and not subscription_link.strip().lower().startswith("happ://"):
                    from bot.utils import happ_client
                    _code = happ_client.parse_install_code_from_happ_link(subscription_link)
                    # Брать основу для редиректа лучше из конфигурации (домен с валидным SSL),
                    # а не из Host запроса (Host может быть IP).
                    try:
                        from bot.config.settings import Config
                        cfg_base = (getattr(Config, "HAPP_SUBSCRIPTION_REDIRECT_BASE", None) or os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE", "") or "").strip().rstrip("/")
                    except Exception:
                        cfg_base = (os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE", "") or "").strip().rstrip("/")
                    redirect_base = cfg_base or _redirect_base_from_request(request)
                    if _code and redirect_base:
                        normalized = redirect_base.rstrip("/") + "/sub/" + _code + "?installid=" + _code
                        if normalized != subscription_link:
                            subscription_link = normalized
                            sub.vpn_config = normalized
                            session.commit()
                            logger.info("miniapp_me: Normalized /sub link host for user %s -> %s/sub/***", user.telegram_id, redirect_base[:40])
            except Exception as e:
                logger.warning("miniapp_me: normalize /sub link failed for user %s: %s", user.telegram_id, e)
            # Если в БД уже хранится /sub/<code>, но без ?installid=<code> — доклеиваем installid (для учёта devices).
            if subscription_link and "/sub/" in subscription_link and "installid=" not in subscription_link:
                try:
                    from bot.utils import happ_client
                    _code = happ_client.parse_install_code_from_happ_link(subscription_link)
                    if _code:
                        sep = "&" if "?" in subscription_link else "?"
                        subscription_link = subscription_link + sep + "installid=" + _code
                        sub.vpn_config = subscription_link
                        session.commit()
                        logger.info("miniapp_me: Added missing installid to redirect link for user %s", user.telegram_id)
                except Exception as e:
                    logger.warning("miniapp_me: failed to append installid to /sub link for user %s: %s", user.telegram_id, e)
            # Гарантированно отдать в ответе ссылку в формате редиректа (если ещё осталась старая — подменяем только в ответе)
            if subscription_link and "installid=" in subscription_link and "/sub/" not in subscription_link:
                try:
                    from bot.utils import happ_client
                    _code = happ_client.parse_install_code_from_happ_link(subscription_link)
                    redirect_base = _redirect_base_from_request(request)
                    if _code and redirect_base:
                        subscription_link = redirect_base.rstrip("/") + "/sub/" + _code + "?installid=" + _code
                        logger.info("miniapp_me: Response link forced to redirect format for user %s", user.telegram_id)
                except Exception:
                    pass
            # Если подписка активна, но ссылки нет — пробуем сгенерировать Happ-ссылку (и сохранить в подписку)
            if not subscription_link and sub.end_date and sub.end_date > datetime.utcnow():
                try:
                    from bot.config.settings import Config
                    from bot.utils import happ_client
                    use_happ = bool(
                        getattr(Config, "HAPP_PROVIDER_CODE", None)
                        and getattr(Config, "HAPP_AUTH_KEY", None)
                        and getattr(Config, "HAPP_SUBSCRIPTION_URL", None)
                    )
                    if not use_happ:
                        logger.info("miniapp_me: Happ fallback skipped — HAPP_PROVIDER_CODE, HAPP_AUTH_KEY or HAPP_SUBSCRIPTION_URL missing in env (check .env on API server)")
                    elif use_happ:
                        devices = happ_client.devices_from_plan_type(sub.plan_type or "")
                        logger.info("miniapp_me: Trying Happ fallback for user %s plan_type=%s devices=%s", user.telegram_id, sub.plan_type, devices)
                        install_code, happ_link = happ_client.create_happ_install_link(
                            getattr(Config, "HAPP_API_URL", "https://happ-proxy.com"),
                            Config.HAPP_PROVIDER_CODE,
                            Config.HAPP_AUTH_KEY,
                            devices,
                            Config.HAPP_SUBSCRIPTION_URL,
                            note=f"tg{user.telegram_id}",
                        )
                        if happ_link:
                            redirect_base = _redirect_base_from_request(request)
                            subscription_link = (redirect_base.rstrip("/") + "/sub/" + install_code + "?installid=" + install_code) if (redirect_base and install_code) else happ_link
                            sub.vpn_config = happ_link
                            session.commit()
                            logger.info("miniapp_me: Happ link generated and saved for user %s", user.telegram_id)
                        else:
                            logger.warning("miniapp_me: Happ API returned no link for user %s (see happ_client logs above; check HAPP_НАСТРОЙКА.md)", user.telegram_id)
                            # Пока API Happ недоступен — отдаём базовый URL подписки (тот же, что открывается в браузере)
                            base_url = (getattr(Config, "HAPP_SUBSCRIPTION_URL", None) or "").strip()
                            if base_url:
                                subscription_link = base_url.rstrip("/")
                                logger.info("miniapp_me: Using base HAPP_SUBSCRIPTION_URL as fallback for user %s", user.telegram_id)
                except Exception as e:
                    logger.warning("miniapp_me: generate Happ link fallback: %s", e)
                    if not subscription_link:
                        import os
                        base_url = (os.environ.get("HAPP_SUBSCRIPTION_URL") or "").strip()
                        if base_url:
                            subscription_link = base_url.rstrip("/")
                            logger.info("miniapp_me: Using base HAPP_SUBSCRIPTION_URL as fallback after error for user %s", user.telegram_id)
            devices_used, devices_limit = None, None
            if subscription_link:
                try:
                    from bot.utils import happ_client
                    install_code = happ_client.parse_install_code_from_happ_link(subscription_link)
                    if install_code:
                        from bot.config.settings import Config
                        # при необходимости list-install можно направить на другой URL через HAPP_LIST_INSTALL_URL
                        list_url = getattr(Config, "HAPP_LIST_INSTALL_URL", None) or os.environ.get("HAPP_LIST_INSTALL_URL", "")
                        api_url = (list_url or getattr(Config, "HAPP_API_URL", None) or os.environ.get("HAPP_API_URL", "") or "").strip().rstrip("/")
                        if api_url and getattr(Config, "HAPP_PROVIDER_CODE", None) and getattr(Config, "HAPP_AUTH_KEY", None):
                            used, limit = happ_client.get_install_stats(
                                api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, install_code
                            )
                            if used is not None and limit is not None:
                                devices_used, devices_limit = used, limit
                                logger.info("miniapp_me: get_install_stats api=%s install_code=%s*** -> used=%s limit=%s", api_url[:30], install_code[:6], used, limit)
                            elif used is not None:
                                devices_used = used
                                devices_limit = limit if limit is not None else happ_client.devices_from_plan_type(sub.plan_type or "")
                                logger.info("miniapp_me: get_install_stats api=%s install_code=%s*** -> used=%s limit=%s", api_url[:30], install_code[:6], used, devices_limit)
                            else:
                                debug_info = happ_client.get_install_stats_debug(
                                    api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, install_code
                                )
                                logger.info(
                                    "miniapp_me: get_install_stats not_found/error install_code=%s*** rc=%s list_total=%s sample_codes=%s raw_keys=%s first_item_keys=%s",
                                    install_code[:6],
                                    debug_info.get("rc"),
                                    debug_info.get("list_total"),
                                    debug_info.get("sample_codes"),
                                    debug_info.get("raw_keys"),
                                    debug_info.get("first_item_keys"),
                                )
                        else:
                            logger.info("miniapp_me: get_install_stats skipped (api_url=%s or missing provider/auth)", "set" if api_url else "empty")
                except Exception as e:
                    logger.warning("miniapp_me: get_install_stats: %s", e)
            # Если Happ не вернул счётчик, но ссылка с installid есть — показываем лимит из тарифа и 0 подключено
            devices_hint = None
            if subscription_link and devices_used is None and devices_limit is None:
                try:
                    from bot.utils import happ_client
                    if happ_client.parse_install_code_from_happ_link(subscription_link):
                        devices_limit = happ_client.devices_from_plan_type(sub.plan_type or "") or 1
                        devices_used = 0
                        devices_hint = "Нажмите «+ Добавить устройство» — откроется Happ Proxy Client и подписка добавится автоматически. После добавления вернитесь сюда и нажмите ↻."
                except Exception:
                    pass
            # Опционально: отдать в мини-апп зашифрованную happ://crypt* ссылку (скрывает исходный HTTPS от глаз пользователя).
            subscription_link_out = subscription_link
            try:
                if subscription_link and str(subscription_link).strip().lower().startswith("http"):
                    if (os.getenv("HAPP_ENCRYPT_SUBSCRIPTION_LINKS") or "").strip().lower() in ("1", "true", "yes"):
                        from bot.utils import happ_client as _happ_crypto
                        crypto_link = _happ_crypto.encrypt_subscription_url_to_crypto(subscription_link)
                        if crypto_link:
                            subscription_link_out = crypto_link
                            logger.info("miniapp_me: encrypted subscription link for user %s", user.telegram_id)
            except Exception as e:
                logger.warning("miniapp_me: HAPP_ENCRYPT_SUBSCRIPTION_LINKS: %s", e)

            sub_payload = {
                "plan_type": sub.plan_type,
                "plan_name": plan_type_to_name(sub.plan_type, ctx),
                "end_date": sub.end_date.isoformat() if sub.end_date else None,
                "end_date_formatted": format_date(sub.end_date) if format_date and sub.end_date else (sub.end_date.isoformat() if sub.end_date else None),
                "days_remaining": sub.days_remaining,
                "server_location": sub.server_location or "",
                "server_flag": get_server_flag(sub.server_location or "") if get_server_flag and sub.server_location else "🌍",
                "subscription_link": subscription_link_out,
                "subscription_link_has_install_limit": bool(
                    subscription_link
                    and (
                        "installid=" in subscription_link
                        or ("/sub/" in subscription_link and happ_client.parse_install_code_from_happ_link(subscription_link))
                    )
                ),
                "devices_used": devices_used,
                "devices_limit": devices_limit,
                "devices_hint": devices_hint,
            }
            return {
                "ok": True,
                "user": user_row(user),
                "referral_invited_count": getattr(user, "total_referrals", 0) or 0,
                "referral_balance": float(getattr(user, "referral_balance", 0) or 0),
                "referral_bonus_days": 0,
                "subscription": sub_payload,
                "subscription_status": status,
                "subscriptions": subscriptions_list,
                "payments": payments_list,
                "devices_used": devices_used,
                "devices_limit": devices_limit,
            }
        finally:
            session.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("miniapp_me failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal error. Check API server logs (journalctl -u miniapp-api).")


def payment_methods_for_miniapp():
    """Список доступных способов оплаты для мини-апп (id, name, emoji)."""
    try:
        from bot.config.settings import PAYMENT_METHODS
        from bot.utils.payments import payment_manager
        available = payment_manager.get_available_methods()
        return [
            {"id": m, "name": PAYMENT_METHODS[m]["name"], "emoji": PAYMENT_METHODS[m].get("emoji", "💳")}
            for m in available
            if m in (PAYMENT_METHODS or {})
        ]
    except Exception as e:
        logger.warning("payment_methods_for_miniapp: %s", e)
        return []


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
            "payment_methods": payment_methods_for_miniapp(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("miniapp_plans failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal error. Check Vercel logs.")


@app.post("/api/miniapp/create-payment")
async def miniapp_create_payment(request: Request):
    """
    Создать платёж из мини-апп: initData, months, devices, payment_method.
    Возвращает payment_url для открытия в браузере (openLink).
    """
    logger.info("create-payment: request started")
    print("[MINIAPP] create-payment called", flush=True)  # всегда в stdout для Vercel Logs
    try:
        from bot.config.settings import SUBSCRIPTION_PLANS, PAYMENT_METHODS, calc_subscription_price
        from bot.utils.payments import payment_manager, PaymentError
        from bot.utils.helpers import get_plan_duration_key
        from bot.utils import happ_client

        ctx = _get_db()
        db_manager = ctx.get("db_manager") if isinstance(ctx, dict) else None
        User = ctx.get("User") if isinstance(ctx, dict) else None
        Payment = ctx.get("Payment") if isinstance(ctx, dict) else None
        if not db_manager or not User or not Payment:
            raise HTTPException(
                status_code=503,
                detail="База не настроена. Укажите DATABASE_URL и BOT_TOKEN в Vercel (Environment Variables) или используйте API на своём сервере (?api=...)."
            )

        body = await request.json()
        init_data = (body.get("initData") or "").strip()
        if not init_data:
            raise HTTPException(status_code=400, detail="initData required")

        parsed = validate_init_data(init_data)
        if not parsed:
            raise HTTPException(status_code=401, detail="Invalid initData")

        telegram_id, _ = get_telegram_user_from_init(parsed)
        if not telegram_id:
            raise HTTPException(status_code=400, detail="user not in initData")

        months = int(body.get("months", 1))
        devices = int(body.get("devices", 1))
        payment_method = (body.get("payment_method") or "").strip()
        if months not in (1, 3, 6, 9, 12) or devices not in (1, 3, 5, 10):
            raise HTTPException(status_code=400, detail="Invalid months or devices")
        if not payment_method or payment_method not in payment_manager.get_available_methods():
            raise HTTPException(status_code=400, detail="Invalid or unavailable payment method")

        plan_key = {1: "1_month", 3: "3_months", 6: "6_months", 9: "9_months", 12: "12_months"}.get(months, "1_month")
        plan_type = f"{plan_key}_{devices}"
        duration_key = get_plan_duration_key(plan_type)
        plan = SUBSCRIPTION_PLANS.get(duration_key)
        if not plan:
            raise HTTPException(status_code=400, detail="Unknown plan")

        amount_rub = calc_subscription_price(devices, months)
        amount_kop = amount_rub * 100

        session = db_manager.get_session()
        try:
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found. Start the bot first.")

            payment = Payment(
                user_id=user.id,
                amount=amount_kop,
                plan_type=plan_type,
                payment_method=payment_method,
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )
            session.add(payment)
            session.commit()
            session.refresh(payment)

            payment_data = payment_manager.create_payment(
                method=payment_method,
                amount=payment.amount,
                order_id=f"vpn_{payment.id}",
                description=f"VPN подписка {plan['name']}",
            )
            payment.payment_id = payment_data["payment_id"]
            payment.payment_url = payment_data["payment_url"]
            session.commit()

            return {
                "ok": True,
                "payment_url": payment_data["payment_url"],
                "payment_id": payment.id,
            }
        except HTTPException:
            raise
        except PaymentError as e:
            logger.error("create-payment PaymentError (YooKassa/backend): %s", e)
            print("[MINIAPP] create-payment ERROR:", str(e), flush=True)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("miniapp_create_payment: %s", e)
            raise HTTPException(status_code=500, detail="Не удалось создать платёж. Проверьте настройки API (DATABASE_URL, ЮKassa) или запустите API на своём сервере.")
        finally:
            session.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("miniapp_create_payment failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Ошибка при создании платежа. Укажите DATABASE_URL и BOT_TOKEN в настройках или запустите API на своём сервере (ЛОГИ_API_НА_СЕРВЕРЕ.txt)."
        )


def _complete_payment_and_send_link(payment_db_id: int) -> bool:
    """
    Завершить платёж (подписка + выдача ссылки/конфига) и отправить сообщения в Telegram.
    Вызывается из вебхука ЮKassa. Возвращает True если обработано успешно.
    """
    try:
        from bot.config.settings import Config, SUBSCRIPTION_PLANS
        from bot.utils.helpers import (
            get_plan_duration_key,
            calculate_end_date,
            get_random_server_location,
            get_server_flag,
            create_config_file,
            generate_config_filename,
            create_qr_code,
            generate_vpn_config,
            calculate_referral_bonus,
            format_date,
        )
        from bot.utils import happ_client
        from locales.ru import get_message
        from bot.models.database import Subscription
    except Exception as e:
        logger.exception("webhook imports: %s", e)
        return False

    ctx = _get_db()
    db_manager = ctx.get("db_manager") if isinstance(ctx, dict) else None
    User = ctx.get("User") if isinstance(ctx, dict) else None
    Payment = ctx.get("Payment") if isinstance(ctx, dict) else None
    if not db_manager or not User or not Payment or not BOT_TOKEN:
        return False

    session = db_manager.get_session()
    try:
        payment = session.query(Payment).filter_by(id=payment_db_id).first()
        if not payment or payment.status == "completed":
            return True
        if getattr(payment, "expires_at", None) and payment.expires_at < datetime.utcnow():
            payment.status = "expired"
            session.commit()
            return False
        user = session.query(User).filter_by(id=payment.user_id).first()
        if not user:
            return False
        telegram_id = user.telegram_id

        payment.status = "completed"
        payment.completed_at = datetime.utcnow()
        user.total_spent += payment.amount_rubles

        for sub in session.query(Subscription).filter_by(user_id=payment.user_id, is_active=True).all():
            sub.is_active = False

        use_happ = bool(
            getattr(Config, "HAPP_PROVIDER_CODE", None)
            and getattr(Config, "HAPP_AUTH_KEY", None)
            and getattr(Config, "HAPP_SUBSCRIPTION_URL", None)
        )
        happ_link = None
        if use_happ:
            devices = happ_client.devices_from_plan_type(payment.plan_type)
            install_code, _happ_link = happ_client.create_happ_install_link(
                getattr(Config, "HAPP_API_URL", "https://happ-proxy.com"),
                Config.HAPP_PROVIDER_CODE,
                Config.HAPP_AUTH_KEY,
                devices,
                Config.HAPP_SUBSCRIPTION_URL,
                note=f"tg{telegram_id}",
            )
            if _happ_link:
                redirect_base = getattr(Config, "HAPP_SUBSCRIPTION_REDIRECT_BASE", None) or os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE", "").strip()
                happ_link = (redirect_base.rstrip("/") + "/sub/" + install_code + "?installid=" + install_code) if (redirect_base and install_code) else _happ_link
            if not happ_link:
                use_happ = False
        server_location = get_random_server_location()
        vpn_config_content = (
            happ_link if use_happ else generate_vpn_config(telegram_id, server_location)
        )
        subscription = Subscription(
            user_id=payment.user_id,
            plan_type=payment.plan_type,
            end_date=calculate_end_date(payment.plan_type),
            vpn_config=vpn_config_content,
            config_name=f"VPN_{SUBSCRIPTION_PLANS.get(get_plan_duration_key(payment.plan_type), {}).get('name', payment.plan_type)}",
            server_location=server_location,
        )
        session.add(subscription)

        if getattr(user, "referrer_id", None):
            from bot.models.database import User as U
            referrer = session.query(U).filter_by(id=user.referrer_id).first()
            if referrer:
                bonus = calculate_referral_bonus(payment.amount)
                referrer.referral_balance += bonus / 100
                session.commit()
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        json={
                            "chat_id": referrer.telegram_id,
                            "text": get_message("referral_bonus", amount=bonus / 100, friend_name=user.full_name),
                            "parse_mode": "HTML",
                        },
                        timeout=10,
                    )
                except Exception as e:
                    logger.warning("referral notify: %s", e)

        session.commit()

        from bot.utils.subscription_card import build_my_subscription_card, link_for_user_display

        card_text, card_kb = build_my_subscription_card(subscription, fetch_device_counts=False)
        base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

        requests.post(
            base_url + "/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": card_text,
                "reply_markup": card_kb,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )

        if use_happ and happ_link:
            config_filename = f"happ_subscription_{telegram_id}.txt"
            file_buffer = create_config_file(link_for_user_display(happ_link), config_filename)
            file_buffer.seek(0)
            requests.post(
                base_url + "/sendDocument",
                data={"chat_id": telegram_id, "caption": "Ссылку можно вставить в приложение Happ из этого файла.", "parse_mode": "HTML"},
                files={"document": (config_filename, file_buffer.read(), "text/plain")},
                timeout=15,
            )
        else:
            config_filename = generate_config_filename(telegram_id, payment.plan_type)
            file_buffer = create_config_file(subscription.vpn_config, config_filename)
            file_buffer.seek(0)
            requests.post(
                base_url + "/sendDocument",
                data={"chat_id": telegram_id, "caption": get_message("vpn_config_info"), "parse_mode": "HTML"},
                files={"document": (config_filename, file_buffer.read(), "text/plain")},
                timeout=15,
            )
            qr_bytes = create_qr_code(subscription.vpn_config)
            if qr_bytes:
                qr_bytes.seek(0)
                requests.post(
                    base_url + "/sendPhoto",
                    data={"chat_id": telegram_id, "caption": get_message("config_qr"), "parse_mode": "HTML"},
                    files={"photo": ("qr.png", qr_bytes.read(), "image/png")},
                    timeout=15,
                )

        setup_text = get_message("setup_choose_device")
        webapp_url = (getattr(Config, "WEBAPP_URL", None) or os.getenv("WEBAPP_URL") or "https://bitvpn.vercel.app").strip().rstrip("/")
        keyboard = {
            "inline_keyboard": [
                [{"text": "🤖 Android", "callback_data": "setup_android"}],
                [{"text": "🍎 iOS", "callback_data": "setup_ios"}],
                [{"text": "🖥️ Windows", "callback_data": "setup_windows"}],
                [{"text": "📱 Открыть приложение", "url": webapp_url}],
            ]
        }
        requests.post(
            base_url + "/sendMessage",
            json={"chat_id": telegram_id, "text": setup_text, "reply_markup": keyboard, "parse_mode": "HTML"},
            timeout=10,
        )
        return True
    except Exception as e:
        logger.exception("_complete_payment_and_send_link: %s", e)
        session.rollback()
        return False
    finally:
        session.close()


@app.post("/api/webhook/yookassa")
async def webhook_yookassa(request: Request):
    """
    Вебхук ЮKassa: при payment.succeeded находим платёж по object.id (payment_id),
    завершаем подписку и отправляем пользователю ссылку Happ (или конфиг) в Telegram.
    Ответ 200 OK обязателен в течение нескольких секунд.
    """
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)
    event = (body.get("event") or "").strip()
    obj = body.get("object") or {}
    yookassa_payment_id = (obj.get("id") or "").strip()
    if event != "payment.succeeded" or not yookassa_payment_id:
        return Response(status_code=200)

    ctx = _get_db()
    db_manager = ctx.get("db_manager") if isinstance(ctx, dict) else None
    Payment = ctx.get("Payment") if isinstance(ctx, dict) else None
    if not db_manager or not Payment:
        return Response(status_code=200)

    session = db_manager.get_session()
    try:
        payment = session.query(Payment).filter_by(payment_id=yookassa_payment_id).first()
        if not payment:
            return Response(status_code=200)
        payment_db_id = payment.id
    finally:
        session.close()

    _complete_payment_and_send_link(payment_db_id)
    return Response(status_code=200)
