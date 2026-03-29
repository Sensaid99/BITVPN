# -*- coding: utf-8 -*-
"""Клиент API Happ-Proxy: создание лимитированных ссылок для приложения Happ."""

import logging
import os
import re
import urllib.parse

import requests

logger = logging.getLogger(__name__)

# Заголовок из документации Happ — без него сервер может отдавать 404
HAPP_HEADERS = {"Accept": "application/json"}


def resolve_happ_base_list_install() -> str:
    """
    Базовый URL для GET /api/list-install, /api/list-hwid, /api/delete-hwid (счётчик и устройства).
    Порядок: HAPP_LIST_INSTALL_URL → HAPP_ADD_DOMAIN_URL → HAPP_API_URL → https://happ-proxy.com
    (на api.happ-proxy.com list-install часто отдаёт 404).
    """
    try:
        from bot.config.settings import Config

        for u in (
            getattr(Config, "HAPP_LIST_INSTALL_URL", None),
            getattr(Config, "HAPP_ADD_DOMAIN_URL", None),
            getattr(Config, "HAPP_API_URL", None),
        ):
            s = (u or "").strip().rstrip("/")
            if s:
                return s
    except Exception:
        pass
    for key in ("HAPP_LIST_INSTALL_URL", "HAPP_ADD_DOMAIN_URL", "HAPP_API_URL"):
        s = (os.getenv(key) or "").strip().rstrip("/")
        if s:
            return s
    return "https://happ-proxy.com"


def resolve_happ_base_add_domain() -> str:
    """
    Базовый URL для GET /api/add-domain (привязка домена редиректа к провайдеру).
    Порядок: HAPP_ADD_DOMAIN_URL → HAPP_LIST_INSTALL_URL → https://happ-proxy.com
    """
    try:
        from bot.config.settings import Config

        for u in (
            getattr(Config, "HAPP_ADD_DOMAIN_URL", None),
            getattr(Config, "HAPP_LIST_INSTALL_URL", None),
        ):
            s = (u or "").strip().rstrip("/")
            if s:
                return s
    except Exception:
        pass
    for key in ("HAPP_ADD_DOMAIN_URL", "HAPP_LIST_INSTALL_URL"):
        s = (os.getenv(key) or "").strip().rstrip("/")
        if s:
            return s
    return "https://happ-proxy.com"


def get_install_stats(
    api_url: str,
    provider_code: str,
    auth_key: str,
    install_code: str,
) -> tuple[int | None, int | None]:
    """
    Получить по install_code количество подключённых устройств и лимит.
    Возвращает (install_count, install_limit) или (None, None) при ошибке.
    """
    if not install_code or len(install_code) != 12:
        return None, None
    try:
        r = requests.get(
            f"{api_url}/api/list-install",
            params={
                "provider_code": provider_code,
                "auth_key": auth_key,
            },
            headers=HAPP_HEADERS,
            timeout=5,
        )
        data = r.json() if r.ok else {}
        if data.get("rc") != 1:
            return None, None
        # Список записей: в документации Happ — поле "data"
        items = data.get("data") or data.get("obj") or data.get("list") or []
        if isinstance(items, dict):
            items = items.get("list") or []
        if not isinstance(items, list):
            items = []
        install_code_clean = (install_code or "").strip()
        for item in (items or []):
            # Happ может вернуть install_code, installCode или install_id
            item_code = (item.get("install_code") or item.get("installCode") or item.get("install_id") or "").strip()
            if item_code and item_code.lower() == install_code_clean.lower():
                count = item.get("install_count") if item.get("install_count") is not None else item.get("installCount")
                limit = item.get("install_limit") if item.get("install_limit") is not None else item.get("installLimit")
                if count is not None and limit is not None:
                    logger.debug("Happ list-install: install_code %s -> count=%s limit=%s", install_code_clean[:6] + "***", count, limit)
                    return int(count), int(limit)
                if count is not None:
                    logger.debug("Happ list-install: install_code %s -> count=%s limit=%s", install_code_clean[:6] + "***", count, limit)
                    return int(count), int(limit) if limit is not None else count
                # Нашли запись, но count не пришёл — считаем 0
                if limit is not None:
                    logger.debug("Happ list-install: install_code %s -> count=0 limit=%s (count missing in response)", install_code_clean[:6] + "***", limit)
                    return 0, int(limit)
                return 0, 0
        logger.info(
            "Happ list-install: install_code %s not found in list (total %s items). Add in Happ the link from the app (Copy link), not the direct server URL.",
            (install_code or "")[:6] + "***",
            len(items or []),
        )
        return None, None
    except Exception as e:
        logger.warning("Happ API list-install error: %s", e)
        return None, None


def get_install_stats_debug(
    api_url: str,
    provider_code: str,
    auth_key: str,
    install_code: str,
) -> dict:
    """
    То же что get_install_stats, но возвращает dict с отладочной информацией:
    found, install_count, install_limit, list_total, rc, msg, sample_codes (первые 6 символов кодов из ответа).
    """
    out = {"found": False, "install_count": None, "install_limit": None, "list_total": 0, "rc": None, "msg": None, "sample_codes": [], "error": None}
    if not install_code or len(install_code) != 12:
        out["error"] = "install_code must be 12 chars"
        return out
    try:
        r = requests.get(
            f"{api_url}/api/list-install",
            params={"provider_code": provider_code, "auth_key": auth_key},
            headers=HAPP_HEADERS,
            timeout=5,
        )
        data = r.json() if r.ok else {}
        out["rc"] = data.get("rc")
        out["msg"] = data.get("msg")
        out["raw_keys"] = list(data.keys())[:20]  # какие ключи вернул Happ
        items = data.get("data") or data.get("obj") or data.get("list") or []
        if isinstance(items, dict):
            items = items.get("list") or []
        if not isinstance(items, list):
            items = []
        out["list_total"] = len(items)
        out["sample_codes"] = [(item.get("install_code") or item.get("installCode") or item.get("install_id") or "")[:6] for item in items[:10]]
        if items:
            first = items[0]
            out["first_item_keys"] = list(first.keys())[:15] if isinstance(first, dict) else []
        install_code_clean = (install_code or "").strip()
        for item in items:
            item_code = (item.get("install_code") or item.get("installCode") or item.get("install_id") or "").strip()
            if item_code and item_code.lower() == install_code_clean.lower():
                out["found"] = True
                out["install_count"] = item.get("install_count") if item.get("install_count") is not None else item.get("installCount")
                out["install_limit"] = item.get("install_limit") if item.get("install_limit") is not None else item.get("installLimit")
                break
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def list_hwids(
    api_url: str,
    provider_code: str,
    auth_key: str,
    install_code: str,
) -> list[dict]:
    """
    GET /api/list-hwid — список устройств по лимитированной ссылке.
    Каждый элемент: hwid, date, device_name (как в API Happ).
    """
    if not install_code or len(install_code) != 12:
        return []
    try:
        r = requests.get(
            f"{api_url.rstrip('/')}/api/list-hwid",
            params={
                "provider_code": provider_code,
                "auth_key": auth_key,
                "install_code": install_code.strip(),
            },
            headers=HAPP_HEADERS,
            timeout=10,
        )
        data = r.json() if r.ok else {}
        if data.get("rc") != 1:
            return []
        items = data.get("data") or []
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "hwid": (item.get("hwid") or item.get("HWID") or "").strip(),
                    "date": (item.get("date") or item.get("created_at") or "").strip(),
                    "device_name": (item.get("device_name") or item.get("deviceName") or "").strip() or "Устройство",
                }
            )
        return [x for x in out if x.get("hwid")]
    except Exception as e:
        logger.warning("Happ list-hwid error: %s", e)
        return []


def delete_hwid(
    api_url: str,
    provider_code: str,
    auth_key: str,
    install_code: str,
    hwid: str,
) -> tuple[bool, str]:
    """GET /api/delete-hwid — отвязать устройство (HWID) от ссылки."""
    if not install_code or not hwid:
        return False, "missing params"
    try:
        r = requests.get(
            f"{api_url.rstrip('/')}/api/delete-hwid",
            params={
                "provider_code": provider_code,
                "auth_key": auth_key,
                "install_code": install_code.strip(),
                "hwid": hwid.strip(),
            },
            headers=HAPP_HEADERS,
            timeout=10,
        )
        data = r.json() if r.ok else {}
        if data.get("rc") == 1:
            return True, "ok"
        return False, str(data.get("msg") or r.text[:120])
    except Exception as e:
        logger.warning("Happ delete-hwid error: %s", e)
        return False, str(e)


def parse_install_code_from_happ_link(happ_link: str | None) -> str | None:
    """
    Извлекает install_code из ссылки.
    Сначала путь .../sub/XXXXXXXXXXXX (без дублирования в query), затем ?installid=.
    """
    if not happ_link:
        return None
    try:
        if "/sub/" in happ_link:
            parsed = urllib.parse.urlparse(happ_link)
            path = (parsed.path or "").strip("/")
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part == "sub" and i + 1 < len(parts):
                    code = (parts[i + 1] or "").strip().split("/")[0]
                    if len(code) == 12 and code.isalnum():
                        return code
        if "installid=" in happ_link:
            parsed = urllib.parse.urlparse(happ_link)
            qs = urllib.parse.parse_qs(parsed.query)
            codes = qs.get("installid") or qs.get("install_id") or []
            return (codes[0] or "").strip() or None
    except Exception:
        pass
    return None


def public_subscription_url(url: str | None) -> str | None:
    """
    Публичная ссылка для пользователя: только https://хост/sub/CODE без ?installid=.
    Код уже в пути; дублирование в query позволяет «обрезать» query и пытаться обойти лимит.
    """
    if not url or not isinstance(url, str):
        return url
    s = url.strip()
    if "/sub/" not in s:
        return s
    m = re.search(r"/sub/([A-Za-z0-9]{12})", s)
    if not m:
        return s
    try:
        parsed = urllib.parse.urlparse(s)
        return f"{parsed.scheme}://{parsed.netloc}/sub/{m.group(1)}"
    except Exception:
        return s.split("?")[0] if "?" in s else s


def _devices_from_plan_type(plan_type: str) -> int:
    """Из plan_type вида 1_month_1, 6_months_3 извлекает число устройств. По умолчанию 1."""
    if not plan_type:
        return 1
    parts = plan_type.split("_")
    if parts and parts[-1].isdigit():
        return max(1, min(100, int(parts[-1])))
    return 1


def _origin_for_happ_add_install(base: str) -> str:
    """
    Базовый origin для GET /api/add-install.
    Apex happ-proxy.com (и www) часто отдаёт 404 на /api/add-install — нужен api-поддомен.
    """
    s = (base or "").strip()
    if not s:
        return "https://api.happ-proxy.com"
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    p = urllib.parse.urlparse(s)
    host = ((p.hostname or "").lower()).rstrip(".")
    if host in ("happ-proxy.com", "www.happ-proxy.com"):
        logger.warning(
            "Happ add-install: host %s → https://api.happ-proxy.com (apex не для /api/add-install)",
            host or "?",
        )
        return "https://api.happ-proxy.com"
    if not p.scheme or not p.netloc:
        return "https://api.happ-proxy.com"
    return f"{p.scheme}://{p.netloc}".rstrip("/")


def resolve_happ_base_add_install() -> str:
    """
    Базовый URL только для GET /api/add-install.
    Не путать с HAPP_ADD_DOMAIN_URL: на https://happ-proxy.com без api часто 404 на add-install.
    """
    try:
        from bot.config.settings import Config

        u = (getattr(Config, "HAPP_API_URL", None) or "").strip().rstrip("/")
    except Exception:
        u = ""
    if not u:
        u = (os.getenv("HAPP_API_URL") or "").strip().rstrip("/")
    if not u:
        return "https://api.happ-proxy.com"
    return _origin_for_happ_add_install(u)


def _normalize_api_url_for_add_install(api_url: str | None) -> str:
    """Если передали корень happ-proxy.com вместо api — подменяем."""
    u = (api_url or "").strip().rstrip("/")
    if not u:
        return resolve_happ_base_add_install()
    return _origin_for_happ_add_install(u)


def create_happ_install_link(
    api_url: str,
    provider_code: str,
    auth_key: str,
    install_limit: int,
    subscription_base_url: str,
    note: str = "",
) -> tuple[str | None, str | None]:
    """
    Создаёт лимитированную ссылку через API Happ.
    Возвращает (install_code, full_url) или (None, None) при ошибке.
    Если subscription_base_url — ссылка happ:// (прямая ссылка из кабинета Happ),
    возвращает (None, subscription_base_url) без вызова API (выдаём ссылку как есть).
    """
    api_url = _normalize_api_url_for_add_install(api_url)
    base = (subscription_base_url or "").strip()
    if base.lower().startswith("happ://"):
        return None, base
    if install_limit < 1 or install_limit > 100:
        install_limit = 1
    params = {
        "provider_code": provider_code,
        "auth_key": auth_key,
        "install_limit": install_limit,
    }
    if note:
        params["note"] = note[:255]
    url = f"{api_url.rstrip('/')}/api/add-install"
    try:
        r = requests.get(url, params=params, headers=HAPP_HEADERS, timeout=10)
        # Apex happ-proxy.com часто отдаёт 404 на add-install (старый код / неверный .env).
        if r.status_code == 404:
            ph = ((urllib.parse.urlparse(url).hostname or "").lower()).rstrip(".")
            if ph in ("happ-proxy.com", "www.happ-proxy.com"):
                retry_url = "https://api.happ-proxy.com/api/add-install"
                logger.warning(
                    "Happ add-install 404 on %s — retrying %s",
                    url,
                    retry_url,
                )
                r = requests.get(retry_url, params=params, headers=HAPP_HEADERS, timeout=10)
        if r.status_code == 404:
            logger.warning(
                "Happ API 404: URL=%s (no /api/add-install here?). "
                "Check HAPP_API_URL in .env; ask Happ support for the correct API base URL.",
                getattr(r, "url", None) or url,
            )
            return None, None
        try:
            data = r.json()
        except Exception:
            data = {}
        if data.get("rc") == 1 and data.get("install_code"):
            code = data["install_code"]
            base = subscription_base_url.rstrip("/")
            sep = "&" if "?" in base else "?"
            full_url = f"{base}{sep}installid={code}"
            return code, full_url
        logger.warning(
            "Happ API add-install failed: status=%s rc=%s msg=%s body=%s",
            r.status_code, data.get("rc"), data.get("msg"), (r.text[:300] if not data else data),
        )
        return None, None
    except Exception as e:
        logger.warning("Happ API request error: %s", e)
        return None, None


def devices_from_plan_type(plan_type: str) -> int:
    """Публичная обёртка для использования в handlers."""
    return _devices_from_plan_type(plan_type)


def encrypt_subscription_url_to_crypto(https_url: str) -> str | None:
    """
    Преобразует HTTPS-ссылку подписки в зашифрованную happ://crypt4|crypt5/...
    через официальный API Happ (см. https://www.happ.su/main/dev-docs/crypto-link).
    Пользователь не видит исходный URL сервера в интерфейсе Happ после добавления.
    """
    u = (https_url or "").strip()
    if not u.startswith("http"):
        return None
    try:
        r = requests.post(
            "https://crypto.happ.su/api-v2.php",
            json={"url": u},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=5,
        )
        if not r.ok:
            logger.warning("Happ crypto API HTTP %s: %s", r.status_code, (r.text or "")[:200])
            return None
        text = (r.text or "").strip()
        if text.startswith("happ://"):
            return text
        try:
            data = r.json()
        except Exception:
            return None
        if isinstance(data, dict):
            for key in ("data", "url", "result", "encrypted", "link", "crypto"):
                v = data.get(key)
                if isinstance(v, str) and v.strip().startswith("happ://"):
                    return v.strip()
            # иногда ответ: {"rc":1,"msg":"...","data":"happ://..."}
            if data.get("rc") == 1 and isinstance(data.get("data"), str):
                v = data["data"].strip()
                if v.startswith("happ://"):
                    return v
        if isinstance(data, str) and data.startswith("happ://"):
            return data
    except Exception as e:
        logger.warning("Happ crypto encrypt error: %s", e)
    return None
