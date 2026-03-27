"""Уведомления администраторам в Telegram (без спама клиентам)."""

import html
import logging

from bot.config.settings import Config

logger = logging.getLogger(__name__)


async def notify_admins(bot, title: str, body: str) -> None:
    """Отправить короткое уведомление всем ADMIN_IDS. Клиентам не используется."""
    if not Config.ADMIN_IDS:
        return
    safe_title = html.escape(title)
    safe_body = html.escape(body[:3500])
    text = f"<b>{safe_title}</b>\n\n<pre>{safe_body}</pre>"
    if len(text) > 4096:
        text = text[:4093] + "…"
    for aid in Config.ADMIN_IDS:
        try:
            await bot.send_message(chat_id=aid, text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning("notify_admins → %s: %s", aid, e)
