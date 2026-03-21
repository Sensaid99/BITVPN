"""Main handlers for VPN Telegram Bot"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest
from sqlalchemy.orm import sessionmaker, joinedload

from bot.models.database import DatabaseManager, User, Subscription, Payment, ReferralPayout
from bot.config.settings import Config, SUBSCRIPTION_PLANS, PAYMENT_METHODS, calc_subscription_price
from bot.utils.helpers import (
    generate_referral_code, 
    format_datetime, 
    format_date, 
    calculate_end_date,
    generate_vpn_config,
    create_qr_code,
    get_user_display_name,
    update_user_activity,
    get_plan_emoji,
    get_plan_duration_key,
    get_server_flag,
    create_referral_link,
    create_config_file,
    get_random_server_location,
    generate_config_filename,
    calculate_referral_bonus,
    format_currency,
    escape_html,
)
from bot.utils.payments import payment_manager, PaymentError
from bot.utils import happ_client
from bot.utils.subscription_card import build_my_subscription_card, inline_keyboard_dict_to_ptb, link_for_user_display
from locales.ru import get_message, format_price_per_month, format_savings

logger = logging.getLogger(__name__)

# План для безлимитной подписки админа: 10 устройств, отображение в профиле и в мини-аппе
ADMIN_UNLIMITED_PLAN_TYPE = "12_months_10"
ADMIN_SERVER_LOCATION = "Admin"


def ensure_admin_unlimited_subscription(telegram_id: int) -> None:
    """Создать безлимитную подписку администратору, если у него ещё нет активной."""
    if telegram_id not in Config.ADMIN_IDS:
        return
    session = db_manager.get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user or not user.is_admin:
            return
        _ = list(user.subscriptions)
        if user.active_subscription and user.active_subscription.end_date and user.active_subscription.end_date > datetime.utcnow():
            return
        # Деактивировать старые просроченные
        for sub in user.subscriptions:
            if sub.is_active:
                sub.is_active = False
        end_date = datetime.utcnow() + timedelta(days=365 * 100)
        use_happ = bool(Config.HAPP_PROVIDER_CODE and Config.HAPP_AUTH_KEY and Config.HAPP_SUBSCRIPTION_URL)
        vpn_config_content = None
        if use_happ:
            install_code, _link = happ_client.create_happ_install_link(
                Config.HAPP_API_URL,
                Config.HAPP_PROVIDER_CODE,
                Config.HAPP_AUTH_KEY,
                10,
                Config.HAPP_SUBSCRIPTION_URL,
                note=f"adm{telegram_id}",
            )
            if _link:
                redirect_base = getattr(Config, 'HAPP_SUBSCRIPTION_REDIRECT_BASE', None) or ''
                vpn_config_content = (redirect_base.strip().rstrip('/') + '/sub/' + install_code) if (redirect_base and isinstance(redirect_base, str) and redirect_base.strip() and install_code) else _link
        if not vpn_config_content:
            vpn_config_content = generate_vpn_config(telegram_id, ADMIN_SERVER_LOCATION)
        subscription = Subscription(
            user_id=user.id,
            plan_type=ADMIN_UNLIMITED_PLAN_TYPE,
            end_date=end_date,
            is_active=True,
            vpn_config=vpn_config_content,
            config_name="VPN Админ (безлимит)",
            server_location=ADMIN_SERVER_LOCATION,
        )
        session.add(subscription)
        session.commit()
        logger.info("Created unlimited subscription for admin %s", telegram_id)
    except Exception as e:
        logger.warning("ensure_admin_unlimited_subscription: %s", e)
        session.rollback()
    finally:
        session.close()

# Conversation states
SELECTING_PLAN, SELECTING_DEVICES, SELECTING_PAYMENT_METHOD, WAITING_PAYMENT = range(4)
WAITING_PAYOUT_REQUISITES = 10

# Initialize database
db_manager = DatabaseManager(Config.DATABASE_URL)
db_manager.create_tables()


# Единый URL мини-приложения: везде (меню, inline, reply) открывается этот адрес
MINI_APP_URL = "https://bitvpn.vercel.app"


def get_webapp_url():
    """URL мини-апп для кнопок. Если в .env нет bitvpn.vercel.app — возвращаем фиксированный URL, чтобы кнопки всегда работали."""
    base = (Config.WEBAPP_URL or "").strip().rstrip("/")
    if base and "bitvpn.vercel.app" in base:
        return base
    return MINI_APP_URL


def _happ_devices_html_line(sub) -> str:
    """
    Строка (HTML) про устройства Happ — только из тарифа, без HTTP к Happ API.
    Раньше здесь был синхронный get_install_stats (до 5+ с), из‑за чего бот «висел» на /start и не отвечал другим.
    Актуальный счётчик — в мини-аппе и по кнопке «Мои устройства» в карточке подписки.
    """
    if not sub or getattr(sub, "server_location", None) == ADMIN_SERVER_LOCATION:
        return ""
    if not Config.HAPP_PROVIDER_CODE or not Config.HAPP_AUTH_KEY:
        return ""
    vpn_cfg = getattr(sub, "vpn_config", None) or ""
    if not vpn_cfg:
        return ""
    install_code = happ_client.parse_install_code_from_happ_link(vpn_cfg)
    limit_from_plan = happ_client.devices_from_plan_type(sub.plan_type)
    if install_code:
        return f"\n📱 По тарифу: до <b>{limit_from_plan}</b> устр. · Счётчик: мини-апп → Устройства"
    if limit_from_plan > 1:
        return f"\n📱 Лимит устройств: <b>{limit_from_plan}</b>"
    return ""


def get_persistent_keyboard(telegram_id=None):
    """Постоянная клавиатура внизу: кнопка «Открыть VPN» с отображением ID пользователя."""
    url = get_webapp_url()
    if url:
        if telegram_id is not None:
            label = f"📱 Открыть VPN · ID {telegram_id}"
        else:
            label = "📱 Открыть VPN"
        btn = KeyboardButton(label, web_app=WebAppInfo(url=url))
        return ReplyKeyboardMarkup([[btn]], resize_keyboard=True)
    return ReplyKeyboardRemove()


def get_or_create_user(telegram_user) -> User:
    """Get or create user in database. Подписки подгружаются одним запросом (снижает риск SSL closed от Neon)."""
    session = db_manager.get_session()
    try:
        user = (
            session.query(User)
            .options(joinedload(User.subscriptions))
            .filter_by(telegram_id=telegram_user.id)
            .first()
        )
        if not user:
            user = User(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                language_code=telegram_user.language_code or 'ru',
                referral_code=generate_referral_code(),
                is_admin=telegram_user.id in Config.ADMIN_IDS
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(f"New user created: {user.telegram_id}")
        
        # Update user activity
        user.last_activity = datetime.utcnow()
        session.commit()
        session.refresh(user)
        # subscriptions уже загружены через joinedload
        return user
    finally:
        session.close()


def _is_db_retryable_error(exc: Exception) -> bool:
    """Проверка: ошибка БД/сети, при которой имеет смысл повторить запрос (Neon SSL closed, таймаут и т.п.)."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "OperationalError" in name or "Timeout" in name or "Connection" in name:
        return True
    if "timeout" in msg or "connection" in msg or "could not connect" in msg:
        return True
    if "ssl" in msg and "closed" in msg:
        return True
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = None
    for attempt in range(2):
        try:
            user = get_or_create_user(update.effective_user)
            break
        except Exception as e:
            if attempt == 0 and _is_db_retryable_error(e):
                logger.warning("start_command: DB/connection error on first attempt, retrying: %s", e)
                await asyncio.sleep(1.5)
                continue
            raise
    if user is None:
        raise RuntimeError("get_or_create_user failed")
    if user.is_admin:
        ensure_admin_unlimited_subscription(user.telegram_id)
        user = get_or_create_user(update.effective_user)
    
    # Deep link: «Моя подписка» — карточка со ссылкой и кнопками (как после оплаты)
    if context.args and context.args[0].lower() == 'my_subscription':
        if user.is_admin and not user.has_active_subscription:
            ensure_admin_unlimited_subscription(user.telegram_id)
            user = get_or_create_user(update.effective_user)
        if not user.has_active_subscription:
            await update.message.reply_text("❌ Нет активной подписки.", parse_mode='HTML')
            return
        sub = user.active_subscription
        # Без запроса Happ list-install — иначе ответ на /start задерживается на секунды (синхронный HTTP).
        card_text, card_kb = build_my_subscription_card(sub, fetch_device_counts=False)
        await update.message.reply_text(
            card_text,
            reply_markup=inline_keyboard_dict_to_ptb(card_kb),
            parse_mode='HTML',
            disable_web_page_preview=True,
        )
        return

    # Deep link из Mini App «Настроить здесь» — одно сообщение «Настроить VPN» с кнопками (без /start и без файлов)
    if context.args and context.args[0].lower() == 'config':
        if user.is_admin and not user.has_active_subscription:
            ensure_admin_unlimited_subscription(user.telegram_id)
            user = get_or_create_user(update.effective_user)
        if not user.has_active_subscription:
            await update.message.reply_text(get_message('error_no_subscription'), parse_mode='HTML')
            return
        await send_setup_device_choice(context.bot, update.effective_chat.id)
        return

    # Ссылка из уведомления об истечении: pay_1month_1, pay_3month_1 и т.д. — открыть приложение для оплаты
    if context.args and context.args[0].lower().startswith('pay_'):
        webapp_url = get_webapp_url()
        keyboard = [[InlineKeyboardButton(get_message('btn_pay_subscription'), web_app=WebAppInfo(url=webapp_url))]]
        await update.message.reply_text(
            get_message('renew_via_app'),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return

    # Handle referral code
    if context.args and user.referrer_id is None:
        referral_code = context.args[0]
        session = db_manager.get_session()
        try:
            referrer = session.query(User).filter_by(referral_code=referral_code).first()
            if referrer and referrer.telegram_id != user.telegram_id:
                user.referrer_id = referrer.id
                referrer.total_referrals += 1
                session.commit()
                logger.info(f"User {user.telegram_id} referred by {referrer.telegram_id}")
                try:
                    await context.bot.send_message(
                        chat_id=referrer.telegram_id,
                        text=get_message('success_referral_registered')
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify referrer: {e}")
        except Exception:
            raise
        finally:
            session.close()
    
    # Краткое приветствие и две кнопки: Открыть приложение, Поддержка. Всё остальное — в мини-апп.
    is_returning = user.created_at < datetime.utcnow() - timedelta(hours=1)
    webapp_url = get_webapp_url()
    support_username = (Config.SUPPORT_USERNAME or "").strip()
    keyboard = [
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("🌐 Канал BIT VPN", url="https://t.me/BitVpnProxy")],
    ]
    if support_username:
        support_url = f"https://t.me/{support_username.lstrip('@')}"
        keyboard.append([InlineKeyboardButton("💬 Поддержка", url=support_url)])
    else:
        keyboard.append([InlineKeyboardButton(get_message('btn_support'), callback_data='support')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_returning:
        message_text = get_message('welcome_back_short', name=user.first_name or 'друг')
    else:
        message_text = get_message('welcome_short')
    
    if user.has_active_subscription and user.active_subscription:
        message_text += _happ_devices_html_line(user.active_subscription)
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show subscription plans"""
    query = update.callback_query
    await query.answer()
    
    message_text = get_message('plans_header')
    
    # Add each plan info with enhanced formatting
    base_month_price = SUBSCRIPTION_PLANS['1_month']['price']
    
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        months = plan['duration_days'] // 30
        price_per_month = format_price_per_month(plan['price'], months)
        savings = format_savings(plan['price'], base_month_price, months)
        popular_badge = get_message('popular_badge') if plan.get('popular') else ""
        
        message_text += get_message('plan_template',
            emoji=plan['emoji'],
            name=plan['name'],
            popular_badge=popular_badge,
            price=plan['price'],
            price_per_month=price_per_month,
            duration=plan['duration_days'],
            description=plan['description'],
            savings=savings
        )
    
    message_text += get_message('choose_plan')
    
    # Кнопки тарифов (как в мини-апп: срок)
    keyboard = [
        [InlineKeyboardButton(
            get_message('btn_plan_1_month', price=SUBSCRIPTION_PLANS['1_month']['price']),
            callback_data='plan_1_month'
        )],
        [InlineKeyboardButton(
            get_message('btn_plan_3_months', price=SUBSCRIPTION_PLANS['3_months']['price']),
            callback_data='plan_3_months'
        )],
        [InlineKeyboardButton(
            get_message('btn_plan_6_months', price=SUBSCRIPTION_PLANS['6_months']['price']),
            callback_data='plan_6_months'
        )],
        [InlineKeyboardButton(
            get_message('btn_plan_9_months', price=SUBSCRIPTION_PLANS['9_months']['price']),
            callback_data='plan_9_months'
        )],
        [InlineKeyboardButton(
            get_message('btn_plan_12_months', price=SUBSCRIPTION_PLANS['12_months']['price']),
            callback_data='plan_12_months'
        )],
        [InlineKeyboardButton(get_message('btn_back'), callback_data='main_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=message_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return SELECTING_PLAN


async def select_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """После выбора срока — выбор количества устройств (1, 3, 5, 10), как в мини-апп."""
    query = update.callback_query
    await query.answer()
    
    plan_type = query.data.replace('plan_', '')
    plan = SUBSCRIPTION_PLANS.get(plan_type)
    if not plan:
        await query.edit_message_text("❌ Неверный план")
        return ConversationHandler.END
    
    context.user_data['duration_key'] = plan_type
    context.user_data['months'] = plan.get('months', 1)
    
    # Цены для каждого варианта устройств (та же формула, что в мини-апп)
    devices_prices = []
    for dev in (1, 3, 5, 10):
        price = calc_subscription_price(dev, plan['months'])
        label = f"{dev} устройств(а) — {price} ₽"
        devices_prices.append([InlineKeyboardButton(label, callback_data=f'devices_{dev}')])
    devices_prices.append([InlineKeyboardButton(get_message('btn_back'), callback_data='buy_vpn')])
    
    await query.edit_message_text(
        text=f"📱 <b>{plan['name']}</b>\n\nВыберите количество устройств (как в мини-апп):",
        reply_markup=InlineKeyboardMarkup(devices_prices),
        parse_mode='HTML'
    )
    return SELECTING_DEVICES


async def select_devices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбрано число устройств — переходим к выбору способа оплаты."""
    query = update.callback_query
    await query.answer()
    
    devices = int(query.data.replace('devices_', ''))
    duration_key = context.user_data.get('duration_key', '1_month')
    months = context.user_data.get('months', 1)
    
    if devices not in (1, 3, 5, 10):
        await query.edit_message_text("❌ Неверное количество устройств")
        return ConversationHandler.END
    
    context.user_data['selected_plan'] = f'{duration_key}_{devices}'
    plan = SUBSCRIPTION_PLANS.get(duration_key)
    if not plan:
        await query.edit_message_text("❌ Ошибка плана")
        return ConversationHandler.END
    
    amount_rub = calc_subscription_price(devices, months)
    month_label = '1 год' if months == 12 else f'{months} мес.'
    
    available_methods = payment_manager.get_available_methods()
    if not available_methods:
        await query.edit_message_text(
            "⚠️ Сейчас приём оплаты не настроен. Обратитесь в поддержку.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    keyboard = []
    for method in available_methods:
        method_info = PAYMENT_METHODS[method]
        keyboard.append([InlineKeyboardButton(
            f"{method_info['emoji']} {method_info['name']}",
            callback_data=f'pay_{method}'
        )])
    keyboard.append([InlineKeyboardButton(get_message('btn_back'), callback_data='buy_vpn')])
    
    await query.edit_message_text(
        text=get_message('payment_methods',
            plan_name=plan['name'],
            amount=amount_rub,
            duration=plan['duration_days']
        ) + f"\n\n📱 Устройств: <b>{devices}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return SELECTING_PAYMENT_METHOD


async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle plan selection and show payment methods"""
    query = update.callback_query
    await query.answer()
    
    plan_type = query.data.replace('plan_', '')
    context.user_data['selected_plan'] = plan_type
    
    plan = SUBSCRIPTION_PLANS.get(plan_type)
    if not plan:
        await query.edit_message_text("❌ Неверный план")
        return ConversationHandler.END
    
    # Get available payment methods
    available_methods = payment_manager.get_available_methods()
    
    if not available_methods:
        await query.edit_message_text(
            "⚠️ Сейчас приём оплаты не настроен. "
            "Обратитесь в поддержку или попробуйте позже.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    keyboard = []
    for method in available_methods:
        method_info = PAYMENT_METHODS[method]
        keyboard.append([InlineKeyboardButton(
            f"{method_info['emoji']} {method_info['name']}",
            callback_data=f'pay_{method}'
        )])
    
    keyboard.append([InlineKeyboardButton(get_message('btn_back'), callback_data='buy_vpn')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=get_message('payment_methods',
            plan_name=plan['name'],
            amount=plan['price'],
            duration=plan['duration_days']
        ),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    return SELECTING_PAYMENT_METHOD


async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process payment"""
    query = update.callback_query
    await query.answer("💳 Создаем счет для оплаты...")
    
    payment_method = query.data.replace('pay_', '')
    plan_type = context.user_data.get('selected_plan')
    custom_amount = context.user_data.pop('from_miniapp_amount', None)
    
    if not plan_type:
        await query.edit_message_text("❌ Ошибка: план не выбран")
        return ConversationHandler.END
    
    duration_key = get_plan_duration_key(plan_type)
    plan = SUBSCRIPTION_PLANS.get(duration_key)
    if not plan:
        await query.edit_message_text("❌ Неверный план")
        return ConversationHandler.END
    
    devices = happ_client.devices_from_plan_type(plan_type)
    amount_rub = custom_amount if custom_amount is not None else calc_subscription_price(devices, plan['months'])
    user = get_or_create_user(update.effective_user)
    
    # Create payment record
    session = db_manager.get_session()
    try:
        payment = Payment(
            user_id=user.id,
            amount=amount_rub * 100,  # Convert to kopecks
            plan_type=plan_type,
            payment_method=payment_method,
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)
        
        # Create payment with provider
        try:
            payment_data = payment_manager.create_payment(
                method=payment_method,
                amount=payment.amount,
                order_id=f"vpn_{payment.id}",
                description=f"VPN подписка {plan['name']}"
            )
            
            # Update payment with external data
            payment.payment_id = payment_data['payment_id']
            payment.payment_url = payment_data['payment_url']
            session.commit()
            
        except PaymentError as e:
            logger.error(f"Payment creation error: {e}")
            await query.edit_message_text(f"❌ {str(e)}")
            return ConversationHandler.END
        
        # Store payment info for verification
        context.user_data['payment_id'] = payment.id
        
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить платеж", callback_data=f'verify_payment_{payment.id}')],
            [InlineKeyboardButton("💳 Новый счет", callback_data=f'plan_{plan_type}')],
            [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=get_message('payment_created',
                plan_name=plan['name'],
                amount=amount_rub,
                payment_url=payment_data['payment_url']
            ),
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
        return WAITING_PAYMENT
        
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        await query.edit_message_text(get_message('error_general'))
        return ConversationHandler.END
    finally:
        session.close()


async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Verify and complete payment"""
    query = update.callback_query
    await query.answer("🔄 Проверяем статус платежа...")
    
    try:
        payment_id = int(query.data.replace('verify_payment_', ''))
    except ValueError:
        await query.edit_message_text("❌ Неверный запрос.")
        return ConversationHandler.END
    
    current_user = get_or_create_user(update.effective_user)
    session = db_manager.get_session()
    try:
        payment = session.query(Payment).filter_by(id=payment_id).first()
        if not payment:
            await query.edit_message_text("❌ Платеж не найден")
            return ConversationHandler.END
        if payment.user_id != current_user.id:
            await query.edit_message_text("❌ Нет доступа к этому платежу.")
            return ConversationHandler.END
        
        # Уже обработан (например вебхуком ЮKassa) — не создаём подписку повторно
        if payment.status == 'completed':
            await query.edit_message_text(
                "✅ Оплата уже проведена.\n\nСсылка на VPN была отправлена вам в чат ранее — проверьте сообщения выше.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
        
        # Check if payment expired
        if payment.is_expired:
            await query.edit_message_text(get_message('error_payment_timeout'))
            return ConversationHandler.END
        
        # Verify payment with provider
        payment_status = payment_manager.check_payment(payment.payment_method, payment.payment_id)
        
        if payment_status == 'completed':
            # Payment successful - create subscription
            payment.status = 'completed'
            payment.completed_at = datetime.utcnow()
            
            # Get user and update stats
            user = session.query(User).filter_by(id=payment.user_id).first()
            user.total_spent += payment.amount_rubles
            
            # Deactivate old subscriptions
            old_subs = session.query(Subscription).filter_by(
                user_id=payment.user_id,
                is_active=True
            ).all()
            for sub in old_subs:
                sub.is_active = False
            
            # Create VPN subscription (Happ или WireGuard)
            server_location = get_random_server_location()
            use_happ = bool(Config.HAPP_PROVIDER_CODE and Config.HAPP_AUTH_KEY and Config.HAPP_SUBSCRIPTION_URL)
            happ_link = None
            if use_happ:
                devices = happ_client.devices_from_plan_type(payment.plan_type)
                install_code, _happ_link = happ_client.create_happ_install_link(
                    Config.HAPP_API_URL,
                    Config.HAPP_PROVIDER_CODE,
                    Config.HAPP_AUTH_KEY,
                    devices,
                    Config.HAPP_SUBSCRIPTION_URL,
                    note=f"tg{user.telegram_id}",
                )
                if _happ_link:
                    redirect_base = getattr(Config, 'HAPP_SUBSCRIPTION_REDIRECT_BASE', None) or ''
                    happ_link = (redirect_base.strip().rstrip('/') + '/sub/' + install_code) if (redirect_base and isinstance(redirect_base, str) and redirect_base.strip() and install_code) else _happ_link
                if not happ_link:
                    use_happ = False
            vpn_config_content = (
                happ_link
                if use_happ
                else generate_vpn_config(user.telegram_id, server_location)
            )
            subscription = Subscription(
                user_id=payment.user_id,
                plan_type=payment.plan_type,
                end_date=calculate_end_date(payment.plan_type),
                vpn_config=vpn_config_content,
                config_name=f"VPN_{SUBSCRIPTION_PLANS.get(get_plan_duration_key(payment.plan_type), {}).get('name', payment.plan_type)}",
                server_location=server_location
            )
            session.add(subscription)
            
            # Process referral bonus
            if user.referrer_id:
                referrer = session.query(User).filter_by(id=user.referrer_id).first()
                if referrer:
                    bonus = calculate_referral_bonus(payment.amount)
                    referrer.referral_balance += bonus / 100  # Convert to rubles
                    session.commit()
                    
                    # Notify referrer
                    try:
                        await context.bot.send_message(
                            chat_id=referrer.telegram_id,
                            text=get_message('referral_bonus',
                                amount=bonus / 100,
                                friend_name=user.full_name
                            )
                        )
                    except Exception as e:
                        logger.warning(f"Failed to notify referrer about bonus: {e}")
            
            session.commit()
            
            # Карточка «Моя подписка» — без ожидания Happ list-install (быстрее после оплаты)
            card_text, card_kb = build_my_subscription_card(subscription, fetch_device_counts=False)
            await query.edit_message_text(
                card_text,
                reply_markup=inline_keyboard_dict_to_ptb(card_kb),
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
            
            if use_happ and happ_link:
                # Файл .txt: при HAPP_ENCRYPT_SUBSCRIPTION_LINKS — happ://crypt* (как в карточке)
                config_filename = f"happ_subscription_{user.telegram_id}.txt"
                config_file = create_config_file(link_for_user_display(happ_link), config_filename)
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=config_file,
                    filename=config_filename,
                    caption="Ссылку можно вставить в приложение Happ из этого файла.",
                    parse_mode='HTML'
                )
            else:
                # Выдача WireGuard конфига (файл + QR)
                config_filename = generate_config_filename(user.telegram_id, payment.plan_type)
                config_file = create_config_file(subscription.vpn_config, config_filename)
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=config_file,
                    filename=config_filename,
                    caption=get_message('vpn_config_info'),
                    parse_mode='HTML'
                )
                qr_buffer = create_qr_code(subscription.vpn_config)
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=qr_buffer,
                    caption=get_message('config_qr'),
                    parse_mode='HTML'
                )
            
            # Одно сообщение «Настроить VPN» с кнопками выбора устройства
            await send_setup_device_choice(context.bot, update.effective_chat.id)
            
        elif payment_status == 'failed':
            payment.status = 'failed'
            session.commit()
            await query.edit_message_text(get_message('payment_failed'), parse_mode='HTML')
            
        else:  # pending or unknown
            time_left = int((payment.expires_at - datetime.utcnow()).total_seconds() / 60)
            if time_left > 0:
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f'verify_payment_{payment.id}')],
                    [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=get_message('payment_pending',
                        amount=payment.amount_rubles,
                        payment_url=payment.payment_url,
                        time_left=time_left
                    ),
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text(get_message('error_payment_timeout'))
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        await query.edit_message_text(get_message('error_general'))
        return ConversationHandler.END
    finally:
        session.close()


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user profile"""
    query = update.callback_query
    await query.answer()
    
    user = get_or_create_user(update.effective_user)
    if user.is_admin and not user.has_active_subscription:
        ensure_admin_unlimited_subscription(user.telegram_id)
        user = get_or_create_user(update.effective_user)
    
    # Get subscription info
    if user.has_active_subscription:
        sub = user.active_subscription
        if sub.server_location == ADMIN_SERVER_LOCATION:
            subscription_info = f"♾️ <b>Безлимит</b> (администратор)\n🌍 Сервер: {get_server_flag(sub.server_location)} {sub.server_location}"
        else:
            plan = SUBSCRIPTION_PLANS.get(get_plan_duration_key(sub.plan_type), SUBSCRIPTION_PLANS.get('1_month'))
            subscription_info = get_message('subscription_active',
                plan_name=plan['name'],
                end_date=format_date(sub.end_date),
                time_remaining=sub.time_remaining_text,
                server_location=f"{get_server_flag(sub.server_location)} {sub.server_location}"
            )
            subscription_info += _happ_devices_html_line(sub)
    else:
        subscription_info = get_message('subscription_inactive')
    
    webapp_url = get_webapp_url()
    keyboard = [
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=get_message('profile_info',
            user_id=user.telegram_id,
            full_name=user.full_name,
            created_at=format_date(user.created_at),
            total_spent=user.total_spent,
            subscription_info=subscription_info,
            referral_code=user.referral_code
        ),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def my_subscription_refresh_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обновить карточку «Моя подписка» (кнопка «Мои устройства»)."""
    query = update.callback_query
    await query.answer()
    user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription:
        await query.edit_message_text("❌ Нет активной подписки.", parse_mode='HTML')
        return
    text, kb = build_my_subscription_card(user.active_subscription)
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=inline_keyboard_dict_to_ptb(kb),
            parse_mode='HTML',
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        raise


async def _edit_message_hap_devices(query, user) -> None:
    """Список устройств Happ (list-hwid) + кнопки отключить."""
    if not user.has_active_subscription:
        await query.edit_message_text("❌ Нет активной подписки.", parse_mode='HTML')
        return
    sub = user.active_subscription
    link = (getattr(sub, "vpn_config", None) or "").strip()
    if not link:
        await query.edit_message_text(
            "❌ Ссылка подписки не найдена. Откройте «Мой конфиг» в боте.",
            parse_mode='HTML',
        )
        return
    install_code = happ_client.parse_install_code_from_happ_link(link)
    if not install_code:
        await query.edit_message_text(
            "❌ Не удалось определить код подписки.",
            parse_mode='HTML',
        )
        return
    list_url = (getattr(Config, "HAPP_LIST_INSTALL_URL", None) or "").strip()
    api_url = (list_url or getattr(Config, "HAPP_API_URL", None) or "https://happ-proxy.com").strip().rstrip("/")
    if not Config.HAPP_PROVIDER_CODE or not Config.HAPP_AUTH_KEY:
        await query.edit_message_text("❌ Happ API не настроен на сервере.", parse_mode='HTML')
        return
    items = happ_client.list_hwids(api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, install_code)
    back_row = [InlineKeyboardButton("◀️ Назад к подписке", callback_data="my_sub_refresh")]
    if not items:
        text = (
            "📱 <b>Список ваших устройств</b>\n\n"
            "Подключённых устройств пока нет.\n\n"
            "Добавьте подписку в Happ — устройства появятся здесь."
        )
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([back_row]),
            parse_mode='HTML',
        )
        return
    lines = ["📱 <b>Список ваших устройств</b>\n"]
    rows = []
    for i, item in enumerate(items[:20]):
        name = item.get("device_name") or "Устройство"
        dt = item.get("date") or "—"
        hw = item.get("hwid") or ""
        hw_short = (hw[:8] + "…" + hw[-6:]) if len(hw) > 18 else hw
        lines.append(
            f"{i + 1}. <b>{escape_html(name)}</b>\n"
            f"   📅 {escape_html(dt)}\n"
            f"   <code>{escape_html(hw_short)}</code>"
        )
        rows.append([InlineKeyboardButton(f"🚫 Отключить ({i + 1})", callback_data=f"hap_d{i}")])
    note = (
        "\n\n<blockquote>Если отключили устройство, при следующем запуске Happ оно может снова учитываться. "
        "Удалите подписку в приложении на том устройстве.</blockquote>"
    )
    text = "\n\n".join(lines) + note
    if len(text) > 4000:
        text = text[:3950] + "…"
    rows.append(back_row)
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='HTML',
    )


async def hap_devices_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Экран списка устройств (как в конкурентах)."""
    query = update.callback_query
    await query.answer()
    user = get_or_create_user(update.effective_user)
    try:
        await _edit_message_hap_devices(query, user)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        raise


async def hap_device_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отключить устройство по индексу (Happ delete-hwid)."""
    query = update.callback_query
    m = re.match(r"^hap_d(\d+)$", query.data or "")
    if not m:
        return
    idx = int(m.group(1))
    await query.answer()
    user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Нет активной подписки.",
            parse_mode='HTML',
        )
        return
    sub = user.active_subscription
    link = (getattr(sub, "vpn_config", None) or "").strip()
    install_code = happ_client.parse_install_code_from_happ_link(link)
    if not install_code:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Нет кода подписки в ссылке.",
            parse_mode='HTML',
        )
        return
    list_url = (getattr(Config, "HAPP_LIST_INSTALL_URL", None) or "").strip()
    api_url = (list_url or getattr(Config, "HAPP_API_URL", None) or "https://happ-proxy.com").strip().rstrip("/")
    items = happ_client.list_hwids(api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, install_code)
    if idx < 0 or idx >= len(items):
        await _edit_message_hap_devices(query, user)
        return
    hwid = items[idx].get("hwid") or ""
    if not hwid:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка HWID.", parse_mode='HTML')
        return
    ok, msg = happ_client.delete_hwid(api_url, Config.HAPP_PROVIDER_CODE, Config.HAPP_AUTH_KEY, install_code, hwid)
    if not ok:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Не удалось отключить: {escape_html(msg[:500])}",
            parse_mode='HTML',
        )
        return
    try:
        await _edit_message_hap_devices(query, user)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def my_sub_connect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если нет MINIAPP_API_URL — подсказка и ссылка в чат."""
    query = update.callback_query
    user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription:
        await query.answer("Нет активной подписки", show_alert=True)
        return
    link = (getattr(user.active_subscription, "vpn_config", None) or "").strip()
    if not link:
        await query.answer("Ссылка не найдена", show_alert=True)
        return
    await query.answer()
    show = link_for_user_display(link)
    safe = escape_html(show[:4000])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Скопируйте и вставьте в Happ → Подписки → + :\n\n<code>" + safe + "</code>",
        parse_mode='HTML',
    )


def _get_setup_device_keyboard():
    """Клавиатура «Настроить VPN»: выбор устройства (Happ)."""
    webapp_url = get_webapp_url()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Android", callback_data='setup_android')],
        [InlineKeyboardButton("🍎 iOS", callback_data='setup_ios')],
        [InlineKeyboardButton("🖥️ Windows", callback_data='setup_windows')],
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
    ])


async def send_setup_device_choice(bot, chat_id: int) -> None:
    """Отправить одно сообщение «Настроить VPN» с кнопками выбора устройства (без /start и без файлов)."""
    text = get_message('setup_choose_device')
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_get_setup_device_keyboard(),
        parse_mode='HTML'
    )


async def setup_device_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответ на нажатие кнопки устройства: отправить ссылку подписки (если есть или удалось сгенерировать), затем инструкцию Happ."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription:
        await context.bot.send_message(chat_id=chat_id, text=get_message('error_no_subscription'), parse_mode='HTML')
        return
    sub = user.active_subscription
    happ_link = None
    vpn_cfg = getattr(sub, 'vpn_config', None) or ''
    if vpn_cfg and isinstance(vpn_cfg, str) and ('installid=' in vpn_cfg or '/sub/' in vpn_cfg or vpn_cfg.strip().startswith('http') or vpn_cfg.strip().lower().startswith('happ://')):
        happ_link = vpn_cfg.strip()
        # В чат отдаём ссылку в формате редиректа (не прямую с installid=)
        if happ_link and 'installid=' in happ_link and '/sub/' not in happ_link:
            _code = happ_client.parse_install_code_from_happ_link(happ_link)
            redirect_base = getattr(Config, 'HAPP_SUBSCRIPTION_REDIRECT_BASE', None) or getattr(Config, 'MINIAPP_API_URL', None) or ''
            if _code and redirect_base and isinstance(redirect_base, str) and redirect_base.strip():
                happ_link = redirect_base.strip().rstrip('/') + '/sub/' + _code
    if not happ_link and Config.HAPP_PROVIDER_CODE and Config.HAPP_AUTH_KEY and Config.HAPP_SUBSCRIPTION_URL:
        try:
            install_code, _happ_link = happ_client.create_happ_install_link(
                getattr(Config, 'HAPP_API_URL', 'https://happ-proxy.com'),
                Config.HAPP_PROVIDER_CODE,
                Config.HAPP_AUTH_KEY,
                happ_client.devices_from_plan_type(sub.plan_type or ''),
                Config.HAPP_SUBSCRIPTION_URL,
                note=f'tg{user.telegram_id}',
            )
            if _happ_link:
                redirect_base = getattr(Config, 'HAPP_SUBSCRIPTION_REDIRECT_BASE', None) or ''
                if (redirect_base and isinstance(redirect_base, str) and redirect_base.strip() and install_code):
                    happ_link = redirect_base.strip().rstrip('/') + '/sub/' + install_code
                else:
                    happ_link = _happ_link
                session = db_manager.get_session()
                try:
                    sub_row = session.query(Subscription).filter_by(id=sub.id).first()
                    if sub_row:
                        sub_row.vpn_config = happ_link
                        session.commit()
                finally:
                    session.close()
        except Exception as e:
            logger.warning("setup_device_handler: generate Happ link: %s", e)
    if happ_link:
        await context.bot.send_message(
            chat_id=chat_id,
            text=get_message('happ_link_send_in_chat') + f"\n\n<code>{happ_link}</code>",
            parse_mode='HTML',
        )
    device = query.data
    key = 'setup_android' if device == 'setup_android' else 'setup_ios' if device == 'setup_ios' else 'setup_windows'
    text = get_message(key)
    if not happ_link:
        text = get_message('happ_link_not_available_hint') + "\n\n" + text
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')


async def show_my_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать «Настроить VPN» — одно сообщение с кнопками выбора устройства (Happ). Без файла и QR в чате."""
    query = getattr(update, 'callback_query', None)
    chat_id = update.effective_chat.id
    if query:
        await query.answer()
    
    user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription and user.is_admin:
        ensure_admin_unlimited_subscription(user.telegram_id)
        user = get_or_create_user(update.effective_user)
    if not user.has_active_subscription:
        msg = get_message('error_no_subscription')
        if query:
            await query.edit_message_text(msg)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        return
    
    text = get_message('setup_choose_device')
    if query:
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=_get_setup_device_keyboard(),
                parse_mode='HTML'
            )
        except BadRequest:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=_get_setup_device_keyboard(), parse_mode='HTML')
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=_get_setup_device_keyboard(), parse_mode='HTML')


async def show_referral_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show referral program info"""
    query = update.callback_query
    await query.answer()
    
    user = get_or_create_user(update.effective_user)
    
    # Get bot username for referral link
    bot_info = await context.bot.get_me()
    referral_link = create_referral_link(user.referral_code, bot_info.username)
    
    keyboard = [
        [InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}")],
        [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
    ]
    
    # Add payout button if has enough balance
    if user.referral_balance >= Config.REFERRAL_MIN_PAYOUT:
        keyboard.insert(1, [InlineKeyboardButton("💳 Вывести средства", callback_data='request_payout')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=get_message('referral_info',
            referral_count=user.total_referrals,
            earned_amount=user.referral_balance,
            available_balance=user.referral_balance,
            referral_link=referral_link,
            min_payout=Config.REFERRAL_MIN_PAYOUT
        ),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def request_payout_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало заявки на вывод реферальных средств."""
    query = update.callback_query
    await query.answer()
    user = get_or_create_user(update.effective_user)
    if user.referral_balance < Config.REFERRAL_MIN_PAYOUT:
        await query.edit_message_text(
            f"❌ Минимальная сумма вывода: {Config.REFERRAL_MIN_PAYOUT} ₽.\n\n"
            f"Ваш баланс: {user.referral_balance:.2f} ₽.",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    text = get_message('referral_payout_request', amount=f"{user.referral_balance:.2f}")
    keyboard = [[InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]]
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    context.user_data['payout_amount'] = user.referral_balance
    return WAITING_PAYOUT_REQUISITES


async def request_payout_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь прислал реквизиты — создаём заявку и уведомляем админов."""
    requisites = (update.message.text or "").strip()
    if not requisites or len(requisites) < 4:
        await update.message.reply_text("❌ Введите реквизиты (карта, кошелёк или телефон).")
        return WAITING_PAYOUT_REQUISITES
    amount = context.user_data.pop('payout_amount', 0)
    user = get_or_create_user(update.effective_user)
    if amount <= 0 or user.referral_balance < Config.REFERRAL_MIN_PAYOUT:
        await update.message.reply_text("❌ Недостаточно средств для вывода.")
        return ConversationHandler.END
    session = db_manager.get_session()
    try:
        payout = ReferralPayout(
            user_id=user.id,
            amount=min(amount, user.referral_balance),
            status='pending',
            payment_details=requisites[:500],
        )
        session.add(payout)
        session.commit()
        await update.message.reply_text(
            f"✅ Заявка на вывод {payout.amount:.2f} ₽ принята.\n\n"
            "Администратор свяжется с вами для подтверждения выплаты.",
            parse_mode='HTML'
        )
        notify = (
            f"💳 <b>Новая заявка на вывод реферальных средств</b>\n\n"
            f"👤 {get_user_display_name(user)} (ID: {user.telegram_id})\n"
            f"💰 Сумма: {payout.amount:.2f} ₽\n"
            f"📝 Реквизиты: {escape_html(requisites[:300])}\n\n"
            f"Заявка #{payout.id}. Обработать в админке: /admin → Платежи/выплаты."
        )
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, notify, parse_mode='HTML')
            except Exception as e:
                logger.warning("Notify admin %s about payout: %s", admin_id, e)
        return ConversationHandler.END
    finally:
        session.close()


async def cancel_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена заявки на вывод."""
    context.user_data.pop('payout_amount', None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help information"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton(get_message('btn_support'), callback_data='support')],
        [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=get_message('help'),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show support information"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💬 Написать в поддержку", url=f"https://t.me/{Config.SUPPORT_USERNAME}")],
        [InlineKeyboardButton(get_message('btn_main_menu'), callback_data='main_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=get_message('support_info', support_username=Config.SUPPORT_USERNAME),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return to main menu — кратко, две кнопки: приложение и поддержка."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user = get_or_create_user(update.effective_user)
    
    webapp_url = get_webapp_url()
    support_username = (Config.SUPPORT_USERNAME or "").strip()
    keyboard = [
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("🌐 Канал BIT VPN", url="https://t.me/BitVpnProxy")],
    ]
    if support_username:
        support_url = f"https://t.me/{support_username.lstrip('@')}"
        keyboard.append([InlineKeyboardButton("💬 Поддержка", url=support_url)])
    else:
        keyboard.append([InlineKeyboardButton(get_message('btn_support'), callback_data='support')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = get_message('welcome_back_short', name=user.first_name or 'друг')
    if user.has_active_subscription and user.active_subscription:
        message_text += _happ_devices_html_line(user.active_subscription)
    
    if query:
        try:
            await query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except BadRequest as e:
            # Сообщение уже такое же — Telegram не меняет. Кнопка уже answer() — просто не показываем ошибку.
            err = str(e).lower()
            if "message is not modified" not in err and "same" not in err:
                raise
            logger.debug("main_menu: edit_message_text skipped (message not modified)")
    else:
        await update.message.reply_text(
            text=message_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current conversation"""
    await update.message.reply_text("❌ Операция отменена")
    return ConversationHandler.END