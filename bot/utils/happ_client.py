# -*- coding: utf-8 -*-
"""Клиент API Happ-Proxy: создание лимитированных ссылок для приложения Happ."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)


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
            timeout=10,
        )
        data = r.json() if r.ok else {}
        if data.get("rc") != 1:
            return None, None
        # Список записей: в документации Happ — поле "data"
        items = data.get("data") or data.get("obj") or data.get("list") or []
        if isinstance(items, dict):
            items = items.get("list") or []
        for item in (items or []):
            if item.get("install_code") == install_code:
                count = item.get("install_count")
                limit = item.get("install_limit")
                if count is not None and limit is not None:
                    return int(count), int(limit)
                if count is not None:
                    return int(count), int(limit) if limit is not None else count
                break
        return None, None
    except Exception as e:
        logger.warning("Happ API list-install error: %s", e)
        return None, None


def parse_install_code_from_happ_link(happ_link: str | None) -> str | None:
    """Из ссылки вида ...?installid=ABC123 или ...&installid=ABC123 извлекает install_code."""
    if not happ_link or "installid=" not in happ_link:
        return None
    try:
        parsed = urllib.parse.urlparse(happ_link)
        qs = urllib.parse.parse_qs(parsed.query)
        codes = qs.get("installid") or qs.get("install_id") or []
        return (codes[0] or "").strip() or None
    except Exception:
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
    """
    if install_limit < 1 or install_limit > 100:
        install_limit = 1
    params = {
        "provider_code": provider_code,
        "auth_key": auth_key,
        "install_limit": install_limit,
    }
    if note:
        params["note"] = note[:255]
    try:
        r = requests.get(
            f"{api_url}/api/add-install",
            params=params,
            timeout=10,
        )
        data = r.json() if r.ok else {}
        if data.get("rc") == 1 and data.get("install_code"):
            code = data["install_code"]
            base = subscription_base_url.rstrip("/")
            sep = "&" if "?" in base else "?"
            full_url = f"{base}{sep}installid={code}"
            return code, full_url
        logger.warning("Happ API add-install failed: %s", data.get("msg", r.text))
        return None, None
    except Exception as e:
        logger.warning("Happ API request error: %s", e)
        return None, None


def devices_from_plan_type(plan_type: str) -> int:
    """Публичная обёртка для использования в handlers."""
    return _devices_from_plan_type(plan_type)
