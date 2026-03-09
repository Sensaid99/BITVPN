"""Main bot application - VPN Telegram Bot"""

import os
import sys
import logging
import asyncio

# Add parent directory to path for proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import BotCommand, MenuButtonWebApp, WebAppInfo
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
    show_plans,
    select_duration,
    select_devices,
    select_payment_method,
    process_payment,
    verify_payment,
    show_profile,
    show_my_config,
    show_referral_info,
    request_payout_start,
    request_payout_done,
    cancel_payout,
    show_help,
    show_support,
    main_menu,
    cancel_conversation,
    SELECTING_PLAN,
    SELECTING_DEVICES,
    SELECTING_PAYMENT_METHOD,
    WAITING_PAYMENT,
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

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def create_application() -> Application:
    """Create and configure the bot application"""
    # Validate configuration
    Config.validate()
    
    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Purchase conversation handler
    purchase_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_plans, pattern='^buy_vpn$')],
        states={
            SELECTING_PLAN: [
                CallbackQueryHandler(select_duration, pattern='^plan_'),
                CallbackQueryHandler(main_menu, pattern='^main_menu$')
            ],
            SELECTING_DEVICES: [
                CallbackQueryHandler(select_devices, pattern='^devices_'),
                CallbackQueryHandler(show_plans, pattern='^buy_vpn$')
            ],
            SELECTING_PAYMENT_METHOD: [
                CallbackQueryHandler(process_payment, pattern='^pay_'),
                CallbackQueryHandler(show_plans, pattern='^buy_vpn$')
            ],
            WAITING_PAYMENT: [
                CallbackQueryHandler(verify_payment, pattern='^verify_payment_'),
                CallbackQueryHandler(main_menu, pattern='^main_menu$')
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            CallbackQueryHandler(main_menu, pattern='^main_menu$')
        ]
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
    application.add_handler(CallbackQueryHandler(show_referral_info, pattern='^referral$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_help, pattern='^help$'), group=-1)
    application.add_handler(CallbackQueryHandler(show_support, pattern='^support$'), group=-1)
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'), group=-1)
    
    # Покупка (цепочка: тариф → устройства → оплата; или из мини-апп — сразу оплата)
    application.add_handler(purchase_conversation)
    application.add_handler(CallbackQueryHandler(process_payment, pattern='^pay_'))  # deep link из мини-апп
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
    """Логируем ошибки и отправляем пользователю сообщение. В лог пишем причину для отладки."""
    import traceback
    tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    # Контекст: что делал пользователь (чтобы искать причину "через раз")
    ctx_info = ""
    if update is not None:
        if hasattr(update, "callback_query") and update.callback_query is not None:
            ctx_info = f" callback_data={getattr(update.callback_query, 'data', '')}"
        elif hasattr(update, "message") and update.message is not None:
            ctx_info = f" message_text={getattr(update.message, 'text', '') or '(не текст)'}"
    logger.error("Exception while handling an update%s: %s\n%s", ctx_info, context.error, tb)
    
    support = getattr(Config, "SUPPORT_USERNAME", None) or "HelpBit_bot"
    support = support.lstrip("@")
    # Временные сетевые/таймаут ошибки — дружелюбнее формулировка
    err_name = type(context.error).__name__
    if "Timeout" in err_name or "Network" in err_name or "Connection" in err_name:
        user_text = (
            "⚠️ Временная ошибка связи.\n\n"
            "Попробуйте через минуту. Если повторится — напишите в поддержку: @{support}"
        ).format(support=support)
    else:
        user_text = (
            "❌ Произошла техническая ошибка. Мы уже работаем над её устранением.\n\n"
            "Попробуйте позже или обратитесь в поддержку: @{support}"
        ).format(support=support)
    
    try:
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=user_text
            )
    except Exception as e:
        logger.error("Failed to send error message to user: %s", e)


async def post_init(application: Application) -> None:
    """Post initialization tasks"""
    logger.info("🚀 VPN Bot initialization started")
    
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