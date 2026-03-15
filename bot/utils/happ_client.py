# -*- coding: utf-8 -*-
"""Клиент API Happ-Proxy: создание лимитированных ссылок для приложения Happ."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)

# Заголовок из документации Happ — без него сервер может отдавать 404
HAPP_HEADERS = {"Accept": "application/json"}


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
            timeout=10,
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
            # Happ может вернуть install_code или installCode
            item_code = (item.get("install_code") or item.get("installCode") or "").strip()
            if item_code.lower() == install_code_clean.lower():
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
        logger.debug("Happ list-install: install_code %s not found in list (%s items)", (install_code or "")[:6] + "***", len(items or []))
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
            timeout=10,
        )
        data = r.json() if r.ok else {}
        out["rc"] = data.get("rc")
        out["msg"] = data.get("msg")
        items = data.get("data") or data.get("obj") or data.get("list") or []
        if isinstance(items, dict):
            items = items.get("list") or []
        if not isinstance(items, list):
            items = []
        out["list_total"] = len(items)
        out["sample_codes"] = [(item.get("install_code") or item.get("installCode") or "")[:6] for item in items[:10]]
        install_code_clean = (install_code or "").strip()
        for item in items:
            item_code = (item.get("install_code") or item.get("installCode") or "").strip()
            if item_code.lower() == install_code_clean.lower():
                out["found"] = True
                out["install_count"] = item.get("install_count") if item.get("install_count") is not None else item.get("installCount")
                out["install_limit"] = item.get("install_limit") if item.get("install_limit") is not None else item.get("installLimit")
                break
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def parse_install_code_from_happ_link(happ_link: str | None) -> str | None:
    """
    Извлекает install_code из ссылки:
    - ...?installid=ABC123 или ...&installid=ABC123
    - или .../sub/XXXXXXXXXXXX (редирект-ссылка, 12 символов)
    """
    if not happ_link:
        return None
    try:
        if "installid=" in happ_link:
            parsed = urllib.parse.urlparse(happ_link)
            qs = urllib.parse.parse_qs(parsed.query)
            codes = qs.get("installid") or qs.get("install_id") or []
            return (codes[0] or "").strip() or None
        if "/sub/" in happ_link:
            parsed = urllib.parse.urlparse(happ_link)
            path = (parsed.path or "").strip("/")
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part == "sub" and i + 1 < len(parts):
                    code = (parts[i + 1] or "").strip().split("/")[0]
                    if len(code) == 12 and code.isalnum():
                        return code
            return None
    except Exception:
        pass
    return None


def _devices_from_plan_type(plan_type: str) -> int:
    """Из plan_type вида 1_month_1, 6_months_3 извлекает число устройств. По умолчанию 1."""
    if not plan_type:
        return 1
    parts = plan_type.split("_")
    if parts and parts[-1].isdigit():
        return max(1, min(100, int(parts[-1])))
    return 1


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
        if r.status_code == 404:
            logger.warning(
                "Happ API 404: URL=%s (no /api/add-install here?). "
                "Check HAPP_API_URL in .env; ask Happ support for the correct API base URL.",
                url,
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
