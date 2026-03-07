"""Main handlers for VPN Telegram Bot"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest
from sqlalchemy.orm import sessionmaker

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
from locales.ru import get_message, format_price_per_month, format_savings

logger = logging.getLogger(__name__)

# План для безлимитной подписки админа (отображение в профиле)
ADMIN_UNLIMITED_PLAN_TYPE = "12_months_1"
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
            _, vpn_config_content = happ_client.create_happ_install_link(
                Config.HAPP_API_URL,
                Config.HAPP_PROVIDER_CODE,
                Config.HAPP_AUTH_KEY,
                10,
                Config.HAPP_SUBSCRIPTION_URL,
                note=f"adm{telegram_id}",
            )
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
    """Get or create user in database"""
    session = db_manager.get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_user.id).first()
        
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
        # Подгрузить связи до закрытия сессии, иначе user.has_active_subscription упадёт после session.close()
        _ = list(user.subscriptions)
        
        return user
    finally:
        session.close()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = get_or_create_user(update.effective_user)
    if user.is_admin:
        ensure_admin_unlimited_subscription(user.telegram_id)
        user = get_or_create_user(update.effective_user)
    
    # Deep link из Mini App «Настроить на этом устройстве» — сразу показать конфиг
    if context.args and context.args[0].lower() == 'config':
        await show_my_config(update, context)
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
    
    # Переход из Mini App: оплата с выбором устройств и срока (pay_6month_3)
    if context.args and len(context.args[0]) > 4 and context.args[0].startswith('pay_'):
        m = re.match(r'pay_(\d+)month_(\d+)', context.args[0])
        if m:
            months, devices = int(m.group(1)), int(m.group(2))
            if months in (1, 3, 6, 9, 12) and devices in (1, 3, 5, 10):
                amount = calc_subscription_price(devices, months)
                plan_key = {1: '1_month', 3: '3_months', 6: '6_months', 9: '9_months', 12: '12_months'}[months]
                context.user_data['selected_plan'] = f'{plan_key}_{devices}'
                context.user_data['from_miniapp_amount'] = amount
                available = payment_manager.get_available_methods()
                if available:
                    keyboard = []
                    for method in available:
                        method_info = PAYMENT_METHODS[method]
                        keyboard.append([InlineKeyboardButton(
                            f"{method_info['emoji']} {method_info['name']}",
                            callback_data=f'pay_{method}'
                        )])
                    keyboard.append([InlineKeyboardButton(get_message('btn_back'), callback_data='buy_vpn')])
                    month_label = '1 год' if months == 12 else f'{months} мес.'
                    text = (
                        f"💳 Оплата <b>{amount} ₽</b>\n"
                        f"📦 {month_label}, {devices} устройств(а)\n\n"
                        "Выберите способ оплаты:"
                    )
                    await update.message.reply_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='HTML'
                    )
                    return
    # Check if returning user
    is_returning = user.created_at < datetime.utcnow() - timedelta(hours=1)
    
    # Кнопки: Купить VPN, Мой профиль, Помощь|Поддержка, Рефералы. Открыть приложение — только кнопкой внизу (меню бота).
    keyboard = [
        [InlineKeyboardButton(get_message('btn_buy_vpn'), callback_data='buy_vpn')],
        [InlineKeyboardButton(get_message('btn_my_profile'), callback_data='profile')],
        [
            InlineKeyboardButton(get_message('btn_help'), callback_data='help'),
            InlineKeyboardButton(get_message('btn_support'), callback_data='support')
        ],
        [InlineKeyboardButton(get_message('btn_referral'), callback_data='referral')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_returning:
        message_text = get_message('welcome_back', name=user.first_name or 'друг')
    else:
        message_text = get_message('welcome')
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    
    # Убираем лишнюю клавиатуру; открывать приложение — кнопкой «Открыть VPN» внизу.
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="👇 Откройте приложение кнопкой ниже",
        reply_markup=ReplyKeyboardRemove()
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
            expires_at=datetime.utcnow() + timedelta(minutes=15)
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
                _, happ_link = happ_client.create_happ_install_link(
                    Config.HAPP_API_URL,
                    Config.HAPP_PROVIDER_CODE,
                    Config.HAPP_AUTH_KEY,
                    devices,
                    Config.HAPP_SUBSCRIPTION_URL,
                    note=f"tg{user.telegram_id}",
                )
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
            
            # Send success message
            plan = SUBSCRIPTION_PLANS.get(get_plan_duration_key(payment.plan_type), SUBSCRIPTION_PLANS.get('1_month'))
            success_message = get_message('payment_success',
                plan_name=plan['name'],
                end_date=format_date(subscription.end_date),
                server_location=f"{get_server_flag(server_location)} {server_location}"
            )
            
            await query.edit_message_text(success_message, parse_mode='HTML')
            
            if use_happ and happ_link:
                # Выдача ссылки Happ — отправляем ссылку и файл .txt
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=get_message('happ_link_caption') + f"\n\n<code>{happ_link}</code>",
                    parse_mode='HTML'
                )
                config_filename = f"happ_subscription_{user.telegram_id}.txt"
                config_file = create_config_file(happ_link, config_filename)
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
            
            # Send main menu
            await main_menu(update, context)
            
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
    else:
        subscription_info = get_message('subscription_inactive')
    
    keyboard = [
        [InlineKeyboardButton("🔄 Продлить подписку", callback_data='buy_vpn')],
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


async def show_my_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's VPN configuration (вызов и по callback из меню, и по /start config из Mini App)."""
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
    
    subscription = user.active_subscription
    is_happ_link = subscription.vpn_config and subscription.vpn_config.strip().startswith("http")
    
    if is_happ_link:
        config_info_text = get_message('happ_link_caption') + f"\n\n<code>{subscription.vpn_config}</code>"
        config_filename = f"happ_subscription_{user.telegram_id}.txt"
    else:
        config_info_text = get_message('vpn_config_info')
        config_filename = generate_config_filename(user.telegram_id, subscription.plan_type)
    
    if query:
        await query.edit_message_text(text=config_info_text, parse_mode='HTML')
    else:
        await context.bot.send_message(chat_id=chat_id, text=config_info_text, parse_mode='HTML')
    
    # Send config file (ссылка Happ — .txt, иначе WireGuard .conf)
    config_file = create_config_file(subscription.vpn_config, config_filename)
    
    await context.bot.send_document(
        chat_id=chat_id,
        document=config_file,
        filename=config_filename,
        caption=f"📱 Конфигурация VPN\n🌍 Сервер: {get_server_flag(subscription.server_location)} {subscription.server_location}",
        parse_mode='HTML'
    )
    
    # Send QR code
    qr_buffer = create_qr_code(subscription.vpn_config)
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=qr_buffer,
        caption=get_message('config_qr'),
        parse_mode='HTML'
    )


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
    """Return to main menu"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user = get_or_create_user(update.effective_user)
    
    # Кнопки без «Открыть приложение» — приложение открывается кнопкой «Открыть VPN» внизу
    keyboard = [
        [InlineKeyboardButton(get_message('btn_buy_vpn'), callback_data='buy_vpn')],
        [InlineKeyboardButton(get_message('btn_my_profile'), callback_data='profile')],
        [
            InlineKeyboardButton(get_message('btn_help'), callback_data='help'),
            InlineKeyboardButton(get_message('btn_support'), callback_data='support')
        ],
        [InlineKeyboardButton(get_message('btn_referral'), callback_data='referral')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = get_message('welcome_back', name=user.first_name or 'друг')
    
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