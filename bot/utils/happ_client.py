# -*- coding: utf-8 -*-
"""Клиент API Happ-Proxy: создание лимитированных ссылок для приложения Happ."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)


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
