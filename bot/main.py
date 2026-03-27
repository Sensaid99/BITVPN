"""Main bot application - VPN Telegram Bot"""

import os
import sys
import logging
import asyncio

# Add parent directory to path for proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import BotCommand, MenuButtonWebApp, WebAppInfo
from telegram.error import TimedOut
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    ConversationHandler,
    filters
)

from bot.config.settings import Config
from bot.handlers.main import (
    start_command,
    show_profile,
    show_my_config,
    setup_device_handler,
    my_subscription_refresh_handler,
    hap_devices_handler,
    hap_device_remove_handler,
    my_sub_connect_handler,
    show_referral_info,
    request_payout_start,
    request_payout_done,
    cancel_payout,
    show_help,
    show_support,
    main_menu,
    WAITING_PAYOUT_REQUISITES,
)
from bot.handlers.admin import (
    admin_panel,
    admin_callback_handler,
    handle_broadcast_message,
    admin_back_to_panel,
    admin_broadcast_confirm
)
from bot.utils.helpers import setup_logging
from bot.utils.telegram_notify import notify_admins

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def create_application() -> Application:
    """Create and configure the bot application"""
    # Validate configuration
    Config.validate()
    
    # Таймауты HTTP к api.telegram.org: на части VPS дефолт ~5 с даёт TimedOut при getMe() на старте
    _tg_t = float(os.getenv("TG_HTTP_TIMEOUT", "30"))
    # Прокси (если с VPS до api.telegram.org нет маршрута / блок — см. TG_PROXY или HTTPS_PROXY в .env)
    _proxy = (os.getenv("TG_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY") or "").strip() or None
    _request = HTTPXRequest(
        connect_timeout=_tg_t,
        read_timeout=_tg_t,
        write_timeout=_tg_t,
        pool_timeout=_tg_t,
        proxy=_proxy,
    )
    if _proxy:
        logger.info("Telegram API: используется прокси (TG_PROXY / HTTPS_PROXY / ALL_PROXY)")
    # concurrent_updates: несколько апдейтов обрабатываются параллельно (иначе один медленный запрос блокирует всех)
    # Один и тот же request для Bot API и long polling (таймауты/прокси применяются к getUpdates)
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .request(_request)
        .get_updates_request(_request)
        .concurrent_updates(True)
        .build()
    )
    
    payout_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(request_payout_start, pattern='^request_payout$')],
        states={
            WAITING_PAYOUT_REQUISITES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, request_payout_done),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_payout),
            CallbackQueryHandler(main_menu, pattern='^main_menu$'),
        ],
    )
    
    # Команды (group=0)
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('admin', admin_panel))
    
    # Кнопки меню — group=-1 чтобы обрабатывались ДО ConversationHandler (иначе callback не доходят)
    application.add_handler(CallbackQueryHandler(show_profile, pattern='^profile$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_my_config, pattern='^my_config$'), group=-1)
    application.add_handler(CallbackQueryHandler(setup_device_handler, pattern='^setup_(android|ios|windows)$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_referral_info, pattern='^referral$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_help, pattern='^help$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_support, pattern='^support$'), group=-1)
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'), group=-1)
    application.add_handler(CallbackQueryHandler(hap_device_remove_handler, pattern=r'^hap_d\d+$'), group=-1)
    application.add_handler(CallbackQueryHandler(hap_devices_handler, pattern='^hap_devices$'), group=-1)
    application.add_handler(CallbackQueryHandler(my_subscription_refresh_handler, pattern='^my_sub_refresh$'), group=-1)
    application.add_handler(CallbackQueryHandler(my_sub_connect_handler, pattern='^my_sub_connect$'), group=-1)
    
    # Покупка и оплата — только в мини-приложении
    application.add_handler(payout_conversation)
    
    # Admin handlers
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(admin_back_to_panel, pattern='^admin_back$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_confirm, pattern='^admin_broadcast_confirm$'))
    
    # Рассылка — только для админов
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(user_id=Config.ADMIN_IDS),
        handle_broadcast_message
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    return application


async def error_handler(update: object, context) -> None:
    """Логируем ошибку; клиентам не пишем технические тексты — только админам."""
    import traceback
    err = context.error
    err_type = type(err).__name__
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    ctx_info = ""
    uid = ""
    if update is not None:
        if hasattr(update, "effective_user") and update.effective_user:
            uid = str(update.effective_user.id)
        if hasattr(update, "callback_query") and update.callback_query is not None:
            ctx_info = f"callback_data={getattr(update.callback_query, 'data', '')}"
        elif hasattr(update, "message") and update.message is not None:
            ctx_info = f"message_text={getattr(update.message, 'text', '') or '(не текст)'}"

    logger.error("[%s] Exception while handling an update user=%s %s: %s\n%s", err_type, uid, ctx_info, err, tb)

    body = f"user_id={uid}\n{ctx_info}\n\n{err_type}: {err}\n\n{tb}"
    try:
        await notify_admins(context.bot, "Ошибка обработки апдейта", body)
    except Exception as e:
        logger.error("notify_admins failed: %s", e)


async def post_init(application: Application) -> None:
    """Post initialization tasks"""
    from datetime import time as dt_time

    logger.info("🚀 VPN Bot initialization started")

    # Если на токене висит webhook, long polling не получает апдейты — пользователю кажется, что бот «мёртвый» на /start
    try:
        wh = await application.bot.get_webhook_info()
        if getattr(wh, "url", None):
            logger.warning(
                "Активен Telegram webhook (%s) — удаляем для режима polling. Иначе бот не получает сообщения.",
                wh.url,
            )
        await application.bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.warning("get_webhook_info / delete_webhook: %s", e)

    # Initialize database
    from bot.models.database import DatabaseManager
    db_manager = DatabaseManager(Config.DATABASE_URL)
    db_manager.create_tables()
    logger.info("✅ Database initialized successfully")
    
    # Get bot info
    bot_info = await application.bot.get_me()
    logger.info(f"✅ Bot started: @{bot_info.username} ({bot_info.first_name})")
    logger.info(f"📱 Mini App URL: {Config.WEBAPP_URL or '(не задан)'}")
    from bot.utils.payments import payment_manager
    pm = payment_manager.get_available_methods()
    logger.info(f"💳 Способы оплаты: {pm if pm else '(нет — проверьте YOOKASSA_* или YOOMONEY_TOKEN в .env)'}")
    
    # Меню бота: одна команда — Запустить бота с ракетой
    await application.bot.set_my_commands([BotCommand("start", "🚀 Запустить бота")])
    
    # Единственная кнопка для мини-приложения — «Открыть VPN» внизу; при каждом старте синхронизируем URL с ботом
    MINI_APP_URL = "https://bitvpn.vercel.app"
    webapp_url = (Config.WEBAPP_URL or "").strip().rstrip("/")
    if not webapp_url or "bitvpn.vercel.app" not in webapp_url:
        webapp_url = MINI_APP_URL
    try:
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть VPN", web_app=WebAppInfo(url=webapp_url))
        )
        logger.info(f"✅ Кнопка «Открыть VPN» → {webapp_url}")
    except Exception as e:
        logger.warning(f"Не удалось установить кнопку меню бота: {e}")
    
    # Send startup message to admins
    startup_message = (
        "🤖 <b>VPN Bot запущен успешно!</b>\n\n"
        f"🆔 Бот: @{bot_info.username}\n"
        f"📅 Время запуска: {logging.Formatter().formatTime(logging.LogRecord('', 0, '', 0, '', (), None))}\n"
        f"⚙️ Режим отладки: {'✅' if Config.DEBUG else '❌'}\n"
        f"🗄️ База данных: {'✅ Подключена' if db_manager else '❌ Ошибка'}\n\n"
        "🎯 Бот готов к работе с пользователями!"
    )
    
    for admin_id in Config.ADMIN_IDS:
        try:
            await application.bot.send_message(
                chat_id=admin_id,
                text=startup_message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.warning(f"Failed to send startup message to admin {admin_id}: {e}")

    # Выдать безлимитную подписку на 10 устройств обоим админам (если ещё нет активной)
    try:
        from bot.handlers.main import ensure_admin_unlimited_subscription
        for admin_id in Config.ADMIN_IDS:
            try:
                ensure_admin_unlimited_subscription(admin_id)
            except Exception as e:
                logger.warning("ensure_admin_unlimited for %s: %s", admin_id, e)
        logger.info("✅ Admin unlimited subscriptions (10 devices) ensured for %s", Config.ADMIN_IDS)
    except Exception as e:
        logger.warning("Admin subscription ensure on startup: %s", e)

    # Ежедневная рассылка: истечение подписки (за 3 дня, за 1 день, после истечения)
    try:
        from bot.jobs.expiry_notifications import send_expiry_notifications
        application.job_queue.run_daily(send_expiry_notifications, time=dt_time(10, 0, 0))
        logger.info("✅ Job: expiry notifications (daily at 10:00 UTC)")
    except Exception as e:
        logger.warning("Could not schedule expiry notifications job: %s", e)

    logger.info("🎉 VPN Bot initialization completed successfully")


async def post_shutdown(application: Application) -> None:
    """Post shutdown tasks"""
    logger.info("🛑 VPN Bot shutdown initiated")
    
    # Get bot info
    try:
        bot_info = await application.bot.get_me()
        
        # Send shutdown message to admins
        shutdown_message = (
            "🛑 <b>VPN Bot остановлен</b>\n\n"
            f"🆔 Бот: @{bot_info.username}\n"
            f"📅 Время остановки: {logging.Formatter().formatTime(logging.LogRecord('', 0, '', 0, '', (), None))}\n\n"
            "ℹ️ Бот временно недоступен для пользователей."
        )
        
        for admin_id in Config.ADMIN_IDS:
            try:
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=shutdown_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to send shutdown message to admin {admin_id}: {e}")
                
    except TimedOut:
        # Нет связи с Telegram (как при падении на getMe) — не ждём повторно и не спамим WARNING
        logger.info("Shutdown: пропуск уведомления админам — нет ответа от Telegram API (TimedOut)")
    except Exception as e:
        # При остановке бота httpx/telegram часто дают RuntimeError — не считаем это критичной ошибкой
        if "HTTPXRequest" in str(e) or "not initialized" in str(e):
            logger.debug("Shutdown: telegram/httpx already closed (%s)", e)
        else:
            logger.warning("Error during shutdown: %s", e)
    
    logger.info("✅ VPN Bot shutdown completed")


def main():
    """Main function to run the bot"""
    logger.info("🚀 Starting VPN Telegram Bot...")
    
    try:
        # Create application
        application = create_application()
        
        # Set post init and shutdown handlers
        application.post_init = post_init
        application.post_shutdown = post_shutdown
        
        # Run the bot
        logger.info("⚡ Bot is starting polling...")
        application.run_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            close_loop=False
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise


if __name__ == '__main__':
    main()