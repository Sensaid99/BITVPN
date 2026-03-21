# -*- coding: utf-8 -*-
"""
Карточка «Моя подписка» для Telegram: текст + inline-кнопки (как у конкурентов).
Используется после оплаты, по deep link my_subscription и по кнопке «Мои устройства».
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

from bot.config.settings import Config
from bot.utils import happ_client
from bot.utils.helpers import format_date

logger = logging.getLogger(__name__)


def _link_raw(sub) -> str:
    return (getattr(sub, "vpn_config", None) or "").strip()


def _days_left_int(sub) -> int:
    dr = getattr(sub, "days_remaining", None)
    if dr is not None:
        try:
            return max(0, int(dr))
        except (TypeError, ValueError):
            pass
    return 0


def is_url_like_subscription(s: str) -> bool:
    t = (s or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://") or t.startswith("happ://")


def get_device_counts_display(sub) -> tuple[int | None, int]:
    """(used, limit) для подписи «Мои устройства (3/5)»."""
    limit = happ_client.devices_from_plan_type(getattr(sub, "plan_type", "") or "")
    link = _link_raw(sub)
    if not link or not (getattr(Config, "HAPP_PROVIDER_CODE", None) and getattr(Config, "HAPP_AUTH_KEY", None)):
        return None, limit
    code = happ_client.parse_install_code_from_happ_link(link)
    if not code:
        return None, limit
    list_url = (getattr(Config, "HAPP_LIST_INSTALL_URL", None) or os.getenv("HAPP_LIST_INSTALL_URL") or "").strip()
    api_url = (list_url or getattr(Config, "HAPP_API_URL", None) or os.getenv("HAPP_API_URL") or "").strip().rstrip("/")
    if not api_url:
        return None, limit
    used, lim = happ_client.get_install_stats(api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, code)
    if lim is not None:
        limit = int(lim)
    if used is not None:
        return int(used), limit
    return None, limit


def build_connect_url(subscription_link: str) -> str | None:
    """HTTPS URL редиректа на happ://add/... для кнопки «Подключиться»."""
    if not subscription_link or not is_url_like_subscription(subscription_link):
        return None
    base = (getattr(Config, "MINIAPP_API_URL", None) or os.getenv("MINIAPP_API_URL") or "").strip().rstrip("/")
    if not base:
        return None
    deep = subscription_link.strip()
    if not deep.lower().startswith("happ://"):
        deep = "happ://add/" + deep
    return base + "/api/miniapp/redirect-to-app?url=" + quote(deep, safe="")


def build_my_subscription_card(sub, *, fetch_device_counts: bool = True) -> tuple[str, dict]:
    """
    Возвращает (html_text, reply_markup как dict для Telegram Bot API / PTB).

    fetch_device_counts: если False — не вызывать Happ list-install (быстрый ответ).
    Счётчик покажет «—/N»; актуальные цифры — по кнопке «Мои устройства» (обновление).
    """
    from locales.ru import get_message

    brand = (getattr(Config, "SUBSCRIPTION_DISPLAY_NAME", None) or "BIT VPN").strip() or "BIT VPN"
    link = _link_raw(sub)
    days = _days_left_int(sub)
    end_date = format_date(sub.end_date) if getattr(sub, "end_date", None) else "—"

    if not link:
        text = get_message("my_subscription_card_no_link", brand=brand, end_date=end_date, days_left=days)
        rows = [[{"text": "◀️ Вернуться назад", "callback_data": "main_menu"}]]
        return text, {"inline_keyboard": rows}

    if not is_url_like_subscription(link):
        text = get_message(
            "my_subscription_card_wireguard",
            brand=brand,
            end_date=end_date,
            days_left=days,
        )
        rows = [[{"text": "◀️ Вернуться назад", "callback_data": "main_menu"}]]
        return text, {"inline_keyboard": rows}

    link_short = link if len(link) <= 64 else (link[:48] + "…")
    text = get_message(
        "my_subscription_card",
        brand=brand,
        end_date=end_date,
        days_left=days,
        link=link,
        link_short=link_short,
    )

    if fetch_device_counts:
        used, limit = get_device_counts_display(sub)
    else:
        used = None
        limit = happ_client.devices_from_plan_type(getattr(sub, "plan_type", "") or "")
    u_disp = used if used is not None else "—"
    dev_label = f"📱 Мои устройства ({u_disp}/{limit})"

    rows = []
    connect = build_connect_url(link)
    if connect:
        rows.append([{"text": "🔌 Подключиться", "url": connect}])
    else:
        rows.append([{"text": "🔌 Подключиться", "callback_data": "my_sub_connect"}])
    rows.append([{"text": dev_label, "callback_data": "my_sub_refresh"}])
    rows.append([{"text": "◀️ Вернуться назад", "callback_data": "main_menu"}])

    return text, {"inline_keyboard": rows}


def inline_keyboard_dict_to_ptb(reply_markup: dict):
    """Конвертация dict → telegram.InlineKeyboardMarkup (python-telegram-bot v20+)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for row in reply_markup.get("inline_keyboard", []):
        btn_row = []
        for b in row:
            if b.get("url"):
                btn_row.append(InlineKeyboardButton(b["text"], url=b["url"]))
            else:
                btn_row.append(InlineKeyboardButton(b["text"], callback_data=b.get("callback_data") or "main_menu"))
        rows.append(btn_row)
    return InlineKeyboardMarkup(rows)
