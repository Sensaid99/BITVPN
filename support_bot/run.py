# -*- coding: utf-8 -*-
"""
Запуск бота поддержки @HelpBit_bot.
Запуск из папки support_bot: python run.py
Или из корня проекта: python -m support_bot.run
"""

import sys
import logging
from pathlib import Path

_root = Path(__file__).resolve().parent
# Загрузка .env: сначала корень проекта (VPN BOT), затем support_bot (HELPBIT_*)
try:
    from dotenv import load_dotenv
    load_dotenv(_root.parent / ".env")
    load_dotenv(_root / ".env")
except ImportError:
    pass

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from support_bot.config import BOT_TOKEN, MASTER_ADMIN_IDS
from support_bot.database import init_db
from support_bot.handlers.user import (
    start,
    show_user_menu,
    faq,
    my_tickets,
    new_ticket_start,
    new_ticket_topic,
    new_ticket_message,
    cancel_ticket,
    user_free_message,
    handle_rating_callback,
    handle_feedback_done,
    CHOOSE_TOPIC,
    ENTER_MESSAGE,
)
from support_bot.handlers.admin import (
    show_admin_panel,
    admin_tickets,
    admin_ticket_detail,
    admin_archive_list,
    admin_archive_view,
    admin_reviews,
    admin_reviews_ratings,
    admin_reviews_feedback,
    admin_review_ticket_view,
    reply_ticket_ask,
    reply_ticket_done,
    reply_ticket_cancel,
    close_ticket_confirm,
    admin_stats,
    admin_manage,
    admin_back,
    add_admin_start,
    add_admin_done,
    add_admin_cancel,
    ENTER_REPLY,
    ENTER_NEW_ADMIN_ID,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Маршрутизация callback_query: пользовательское меню, админка, тикеты."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # Пользовательское меню
    if data == "back_to_main":
        await show_user_menu(update, context)
        return
    if data == "faq":
        await faq(update, context)
        return
    if data == "my_tickets":
        await my_tickets(update, context)
        return

    # Админка
    if data == "admin_back":
        await admin_back(update, context)
        return
    if data == "admin_tickets":
        await admin_tickets(update, context)
        return
    if data == "admin_archive":
        await admin_archive_list(update, context)
        return
    if data.startswith("view_archive_"):
        try:
            tid = int(data.replace("view_archive_", ""))
            await admin_archive_view(update, context, tid)
        except ValueError:
            pass
        return
    if data == "admin_stats":
        await admin_stats(update, context)
        return
    if data == "admin_manage":
        await admin_manage(update, context)
        return
    if data == "admin_reviews":
        await admin_reviews(update, context)
        return
    if data == "admin_reviews_ratings":
        await admin_reviews_ratings(update, context)
        return
    if data == "admin_reviews_feedback":
        await admin_reviews_feedback(update, context)
        return
    if data.startswith("view_review_ticket_"):
        try:
            tid = int(data.replace("view_review_ticket_", ""))
            await admin_review_ticket_view(update, context, tid)
        except ValueError:
            pass
        return
    if data.startswith("close_ticket_"):
        await close_ticket_confirm(update, context)
        return
    if data.startswith("rate_"):
        await handle_rating_callback(update, context)
        return
    if data.startswith("feedback_done_"):
        await handle_feedback_done(update, context)
        return
    # reply_ticket_* и add_admin_start обрабатываются в ConversationHandler

    # Просмотр тикета по id (опционально: view_ticket_123)
    if data.startswith("view_ticket_"):
        try:
            tid = int(data.replace("view_ticket_", ""))
            await admin_ticket_detail(update, context, tid)
        except ValueError:
            pass
        return


def build_application() -> Application:
    """Сборка Application со всеми обработчиками."""
    if not BOT_TOKEN:
        raise ValueError("Укажите HELPBIT_BOT_TOKEN в .env или переменных окружения")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # /start
    app.add_handler(CommandHandler("start", start))

    # Сообщения пользователя: добавить в открытый тикет или сохранить отзыв (group=1, после ConversationHandler)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, user_free_message),
        group=1,
    )

    # Создание тикета (ConversationHandler)
    conv_ticket = ConversationHandler(
        entry_points=[CallbackQueryHandler(new_ticket_start, pattern="^new_ticket$")],
        states={
            CHOOSE_TOPIC: [CallbackQueryHandler(new_ticket_topic, pattern="^(topic_|back_to_main)")],
            ENTER_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_ticket_message),
                CommandHandler("cancel", cancel_ticket),
            ],
        },
        fallbacks=[CallbackQueryHandler(show_user_menu, pattern="^back_to_main$")],
    )
    app.add_handler(conv_ticket)

    # Ответ админа на тикет (ConversationHandler)
    conv_reply = ConversationHandler(
        entry_points=[CallbackQueryHandler(reply_ticket_ask, pattern="^reply_ticket_")],
        states={
            ENTER_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, reply_ticket_done)],
        },
        fallbacks=[CommandHandler("cancel", reply_ticket_cancel)],
    )
    app.add_handler(conv_reply)

    # Добавление админа (только мастер)
    conv_add_admin = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin_start, pattern="^add_admin_start$")],
        states={
            ENTER_NEW_ADMIN_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_done),
                MessageHandler(filters.FORWARDED, add_admin_done),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_admin_cancel)],
    )
    app.add_handler(conv_add_admin)

    # Все остальные callback (меню, админка, закрытие тикета и т.д.)
    app.add_handler(CallbackQueryHandler(callback_router))

    return app


def main():
    app = build_application()
    logger.info("Бот поддержки @HelpBit_bot запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
