"""Ежедневная рассылка уведомлений об истечении подписки: за 3 дня, за 1 день и после истечения."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models.database import DatabaseManager, Subscription, User
from bot.config.settings import Config
from bot.utils.helpers import build_renew_start_param, format_date
from locales.ru import get_message

logger = logging.getLogger(__name__)


def _get_renew_url(plan_type: str, bot_username: str) -> str:
    """Ссылка на бота с start-параметром для оплаты той же подписки."""
    start_param = build_renew_start_param(plan_type)
    username = (bot_username or "").strip().lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start={start_param}"


async def send_expiry_notifications(context) -> None:
    """
    Вызывается по расписанию (раз в день). Находит подписки:
    - истекшие (end_date в прошлом) и ещё не уведомлённые → «подписка истекла» + кнопка оплаты;
    - истекают ровно через 3 дня → «истекает через 3 дня» + кнопка;
    - истекают ровно через 1 день → «истекает завтра» + кнопка.
    Кнопка ведёт на оплату той же подписки (тот же план и кол-во устройств).
    """
    bot = context.bot
    bot_username = (getattr(bot, "username", None) or "").strip() or (Config.BOT_USERNAME or "").strip().lstrip("@")
    if not bot_username:
        logger.warning("Expiry notifications: BOT_USERNAME not set, payment links will be empty")

    db = DatabaseManager(Config.DATABASE_URL)
    now = datetime.utcnow()
    today = now.date()

    session = db.get_session()
    try:
        # Подписки, у которых ещё не отправляли уведомление об истечении
        # и дата окончания уже в прошлом
        expired = (
            session.query(Subscription, User)
            .join(User, Subscription.user_id == User.id)
            .filter(
                Subscription.is_active == True,
                Subscription.end_date < now,
                Subscription.notified_expired == False,
            )
            .all()
        )
        for sub, user in expired:
            try:
                text = get_message(
                    "notification_expired",
                    name=user.first_name or "друг",
                    end_date=format_date(sub.end_date),
                )
                url = _get_renew_url(sub.plan_type, bot_username)
                keyboard = [[InlineKeyboardButton(get_message("btn_pay_subscription"), url=url)]] if url else []
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode="HTML",
                )
                sub.notified_expired = True
                logger.info("Sent expired notification to user %s (sub id %s)", user.telegram_id, sub.id)
            except Exception as e:
                logger.exception("Failed to send expired notification to %s: %s", user.telegram_id, e)

        # Истекают ровно через 3 дня
        in_3_days = (
            session.query(Subscription, User)
            .join(User, Subscription.user_id == User.id)
            .filter(
                Subscription.is_active == True,
                Subscription.end_date >= now,
                Subscription.notified_3d == False,
            )
            .all()
        )
        for sub, user in in_3_days:
            days_left = (sub.end_date.replace(tzinfo=None) - now).days
            if days_left != 3:
                continue
            try:
                text = get_message(
                    "notification_expires_3d",
                    name=user.first_name or "друг",
                    end_date=format_date(sub.end_date),
                )
                url = _get_renew_url(sub.plan_type, bot_username)
                keyboard = [[InlineKeyboardButton(get_message("btn_pay_subscription"), url=url)]] if url else []
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode="HTML",
                )
                sub.notified_3d = True
                logger.info("Sent 3-day expiry notification to user %s (sub id %s)", user.telegram_id, sub.id)
            except Exception as e:
                logger.exception("Failed to send 3d notification to %s: %s", user.telegram_id, e)

        # Истекают ровно через 1 день
        in_1_day = (
            session.query(Subscription, User)
            .join(User, Subscription.user_id == User.id)
            .filter(
                Subscription.is_active == True,
                Subscription.end_date >= now,
                Subscription.notified_1d == False,
            )
            .all()
        )
        for sub, user in in_1_day:
            days_left = (sub.end_date.replace(tzinfo=None) - now).days
            if days_left != 1:
                continue
            try:
                text = get_message(
                    "notification_expires_1d",
                    name=user.first_name or "друг",
                    end_date=format_date(sub.end_date),
                )
                url = _get_renew_url(sub.plan_type, bot_username)
                keyboard = [[InlineKeyboardButton(get_message("btn_pay_subscription"), url=url)]] if url else []
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode="HTML",
                )
                sub.notified_1d = True
                logger.info("Sent 1-day expiry notification to user %s (sub id %s)", user.telegram_id, sub.id)
            except Exception as e:
                logger.exception("Failed to send 1d notification to %s: %s", user.telegram_id, e)

        session.commit()
    except Exception as e:
        logger.exception("Expiry notifications job failed: %s", e)
        session.rollback()
    finally:
        session.close()
