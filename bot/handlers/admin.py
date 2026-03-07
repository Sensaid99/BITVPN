"""Admin handlers for VPN Telegram Bot"""

import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import func, desc

from bot.models.database import DatabaseManager, User, Subscription, Payment, VPNKey, BotStats, ReferralPayout
from bot.config.settings import Config
from bot.utils.helpers import (
    is_admin, 
    log_admin_action, 
    format_datetime, 
    format_date,
    format_time_ago,
    StatsCalculator,
    escape_html,
    get_user_display_name,
)
from locales.ru import get_message

logger = logging.getLogger(__name__)

db_manager = DatabaseManager(Config.DATABASE_URL)

# Admin conversation states
WAITING_BROADCAST_MESSAGE = 1


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin panel"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(get_message('admin_not_authorized'))
        return
    
    session = db_manager.get_session()
    try:
        # Get comprehensive statistics
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        # Daily revenue
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100  # Convert from kopecks
        
        # Monthly revenue
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100  # Convert from kopecks
        
        # Available VPN keys
        available_keys = session.query(VPNKey).filter(VPNKey.is_used == False).count()
        
        # New users today
        new_users = session.query(User).filter(
            User.created_at >= today
        ).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            available_keys=available_keys,
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("🔑 VPN ключи", callback_data='admin_keys'),
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments')
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
                InlineKeyboardButton("📋 Логи", callback_data='admin_logs')
            ],
            [
                InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_refresh')
            ],
            [InlineKeyboardButton("💳 Выплаты рефералов", callback_data='admin_payouts')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "accessed_admin_panel")
        
    finally:
        session.close()


async def admin_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin statistics (legacy function for compatibility)"""
    # Redirect to new detailed stats function
    await admin_detailed_stats(update, context)


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin callback queries"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text(get_message('admin_not_authorized'))
        return
    
    action = query.data.replace('admin_', '')
    
    if action == 'refresh':
        await admin_panel_refresh(update, context)
    elif action == 'users':
        await admin_users_list(update, context)
    elif action == 'stats':
        await admin_detailed_stats(update, context)
    elif action == 'keys':
        await admin_keys_management(update, context)
    elif action == 'payments':
        await admin_payments_list(update, context)
    elif action == 'broadcast':
        await admin_broadcast_start(update, context)
    elif action == 'logs':
        await admin_logs_view(update, context)
    elif action == 'payouts':
        await admin_payouts_list(update, context)
    elif action.startswith('payout_complete_'):
        try:
            pid = int(action.replace('payout_complete_', ''))
            await admin_payout_complete(update, context, pid)
        except ValueError:
            pass
    elif action.startswith('payout_reject_'):
        try:
            pid = int(action.replace('payout_reject_', ''))
            await admin_payout_reject(update, context, pid)
        except ValueError:
            pass
    elif action == 'settings':
        await admin_settings(update, context)


async def admin_panel_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh admin panel"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get fresh statistics
        total_users = session.query(User).count()
        active_subscriptions = session.query(Subscription).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).count()
        
        today = datetime.utcnow().date()
        daily_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= today
        ).scalar() or 0
        daily_revenue = daily_revenue / 100
        
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= start_of_month
        ).scalar() or 0
        monthly_revenue = monthly_revenue / 100
        
        available_keys = session.query(VPNKey).filter(VPNKey.is_used == False).count()
        new_users = session.query(User).filter(User.created_at >= today).count()
        
        admin_text = get_message('admin_panel',
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            daily_revenue=int(daily_revenue),
            monthly_revenue=int(monthly_revenue),
            available_keys=available_keys,
            new_users=new_users,
            last_update=format_datetime(datetime.utcnow())
        )
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')
            ],
            [
                InlineKeyboardButton("🔑 VPN ключи", callback_data='admin_keys'),
                InlineKeyboardButton("💰 Платежи", callback_data='admin_payments')
            ],
            [
                InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
                InlineKeyboardButton("📋 Логи", callback_data='admin_logs')
            ],
            [
                InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings'),
                InlineKeyboardButton("🔄 Обновлено ✅", callback_data='admin_refresh')
            ],
            [InlineKeyboardButton("💳 Выплаты рефералов", callback_data='admin_payouts')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=admin_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "refreshed_admin_panel")
        
    finally:
        session.close()


async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show users list for admin"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent users with pagination
        page = context.user_data.get('admin_users_page', 0)
        limit = 10
        offset = page * limit
        
        users = session.query(User).order_by(desc(User.created_at)).offset(offset).limit(limit).all()
        total_users = session.query(User).count()
        
        users_text = f"👥 Пользователи (стр. {page + 1}):\n\n"
        
        for user in users:
            status_emoji = "✅" if user.has_active_subscription else "❌"
            last_activity = format_time_ago(user.last_activity)
            
            users_text += f"{status_emoji} <b>{user.full_name}</b>\n"
            users_text += f"   🆔 ID: <code>{user.telegram_id}</code>\n"
            users_text += f"   👤 @{user.username or 'None'}\n"
            users_text += f"   📅 Регистрация: {format_date(user.created_at)}\n"
            users_text += f"   🕐 Активность: {last_activity}\n"
            users_text += f"   💰 Потрачено: {user.total_spent} ₽\n"
            users_text += f"   🎁 Рефералов: {user.total_referrals}\n\n"
        
        users_text += f"📊 Всего пользователей: {total_users}"
        
        # Navigation buttons
        keyboard = []
        nav_row = []
        
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f'admin_users_page_{page-1}'))
        
        if (page + 1) * limit < total_users:
            nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=f'admin_users_page_{page+1}'))
        
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.extend([
            [
                InlineKeyboardButton("🔍 Поиск пользователя", callback_data='admin_user_search'),
                InlineKeyboardButton("📊 Статистика", callback_data='admin_user_stats')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=users_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed statistics"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Calculate comprehensive stats
        stats = StatsCalculator.calculate_daily_stats()
        
        # User statistics
        total_users = session.query(User).count()
        active_users_week = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=7)
        ).count()
        active_users_month = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        # Subscription statistics
        subs_by_plan = session.query(
            Subscription.plan_type,
            func.count(Subscription.id)
        ).filter(
            Subscription.is_active == True,
            Subscription.end_date > datetime.utcnow()
        ).group_by(Subscription.plan_type).all()
        
        # Payment statistics
        total_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed'
        ).scalar() or 0
        total_revenue = total_revenue / 100
        
        # Weekly revenue
        week_ago = datetime.utcnow() - timedelta(days=7)
        weekly_revenue = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.completed_at >= week_ago
        ).scalar() or 0
        weekly_revenue = weekly_revenue / 100
        
        stats_text = f"📊 <b>Подробная статистика</b>\n\n"
        
        stats_text += f"👥 <b>Пользователи:</b>\n"
        stats_text += f"   • Всего: {total_users}\n"
        stats_text += f"   • Новых сегодня: {stats['new_users']}\n"
        stats_text += f"   • Активных за неделю: {active_users_week}\n"
        stats_text += f"   • Активных за месяц: {active_users_month}\n\n"
        
        stats_text += f"📱 <b>Подписки:</b>\n"
        stats_text += f"   • Активных: {stats['active_subscriptions']}\n"
        for plan_type, count in subs_by_plan:
            plan_name = plan_type.replace('_', ' ').title()
            stats_text += f"   • {plan_name}: {count}\n"
        stats_text += "\n"
        
        stats_text += f"💰 <b>Доходы:</b>\n"
        stats_text += f"   • Сегодня: {stats['daily_revenue']:.0f} ₽\n"
        stats_text += f"   • За неделю: {weekly_revenue:.0f} ₽\n"
        stats_text += f"   • Всего: {total_revenue:.0f} ₽\n"
        stats_text += f"   • Платежей сегодня: {stats['successful_payments']}\n\n"
        
        stats_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"
        
        keyboard = [
            [
                InlineKeyboardButton("📈 График доходов", callback_data='admin_revenue_chart'),
                InlineKeyboardButton("👥 Активность пользователей", callback_data='admin_activity_chart')
            ],
            [
                InlineKeyboardButton("📊 Экспорт данных", callback_data='admin_export_data'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_stats')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=stats_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "viewed_detailed_stats")
        
    finally:
        session.close()


async def admin_keys_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage VPN keys"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        total_keys = session.query(VPNKey).count()
        available_keys = session.query(VPNKey).filter(VPNKey.is_used == False).count()
        used_keys = total_keys - available_keys
        
        keys_text = f"🔑 <b>Управление VPN ключами</b>\n\n"
        keys_text += f"📊 <b>Статистика:</b>\n"
        keys_text += f"   • Всего ключей: {total_keys}\n"
        keys_text += f"   • Доступных: {available_keys}\n"
        keys_text += f"   • Использованных: {used_keys}\n\n"
        
        if available_keys < 10:
            keys_text += "⚠️ <b>Внимание!</b> Мало доступных ключей!\n\n"
        
        keys_text += f"🔄 <b>Обновлено:</b> {format_datetime(datetime.utcnow())}"
        
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить ключи", callback_data='admin_keys_add'),
                InlineKeyboardButton("📋 Список ключей", callback_data='admin_keys_list')
            ],
            [
                InlineKeyboardButton("🗑️ Очистить использованные", callback_data='admin_keys_cleanup'),
                InlineKeyboardButton("📊 Статистика по серверам", callback_data='admin_keys_stats')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=keys_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_payments_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent payments"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        # Get recent payments
        payments = session.query(Payment).order_by(desc(Payment.created_at)).limit(20).all()
        
        payments_text = f"💰 <b>Последние платежи</b>\n\n"
        
        for payment in payments:
            user = session.query(User).filter_by(id=payment.user_id).first()
            status_emoji = {
                'completed': '✅',
                'pending': '⏳',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(payment.status, '❓')
            
            payments_text += f"{status_emoji} <b>{payment.amount_rubles:.0f} ₽</b>\n"
            payments_text += f"   👤 {user.full_name if user else 'Unknown'}\n"
            payments_text += f"   📦 {payment.plan_type.replace('_', ' ').title()}\n"
            payments_text += f"   💳 {payment.payment_method.upper()}\n"
            payments_text += f"   📅 {format_datetime(payment.created_at)}\n\n"
        
        keyboard = [
            [
                InlineKeyboardButton("💰 Статистика доходов", callback_data='admin_revenue_stats'),
                InlineKeyboardButton("🔍 Поиск платежа", callback_data='admin_payment_search')
            ],
            [
                InlineKeyboardButton("📊 По методам оплаты", callback_data='admin_payment_methods'),
                InlineKeyboardButton("🔄 Обновить", callback_data='admin_payments')
            ],
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=payments_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start broadcast message creation"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        active_users = session.query(User).filter(
            User.last_activity >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        broadcast_text = get_message('broadcast_start',
            total_users=total_users,
            active_users=active_users
        )
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=broadcast_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        # Set state for waiting broadcast message
        context.user_data['waiting_broadcast'] = True
        
    finally:
        session.close()


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle broadcast message from admin"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id) or not context.user_data.get('waiting_broadcast'):
        return
    
    broadcast_message = update.message.text
    context.user_data['waiting_broadcast'] = False
    context.user_data['broadcast_message'] = broadcast_message
    
    session = db_manager.get_session()
    try:
        total_users = session.query(User).count()
        
        confirm_text = get_message('broadcast_confirm',
            recipients=total_users,
            message=broadcast_message
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить всем", callback_data='admin_broadcast_confirm'),
                InlineKeyboardButton("❌ Отмена", callback_data='admin_back')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text=confirm_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
    finally:
        session.close()


async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and execute broadcast"""
    query = update.callback_query
    await query.answer("📢 Начинаем рассылку...")
    
    user_id = update.effective_user.id
    broadcast_message = context.user_data.get('broadcast_message')
    
    if not broadcast_message:
        await query.edit_message_text("❌ Сообщение для рассылки не найдено")
        return
    
    session = db_manager.get_session()
    try:
        users = session.query(User).all()
        total_users = len(users)
        sent_count = 0
        failed_count = 0
        
        # Update message to show progress
        await query.edit_message_text(
            f"📢 Рассылка запущена...\n\n"
            f"👥 Всего получателей: {total_users}\n"
            f"✅ Отправлено: 0\n"
            f"❌ Ошибок: 0"
        )
        
        # Send messages with progress updates
        safe_message = escape_html(broadcast_message)
        for i, user in enumerate(users):
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=safe_message,
                    parse_mode='HTML'
                )
                sent_count += 1
                
                # Update progress every 50 messages
                if (i + 1) % 50 == 0:
                    await query.edit_message_text(
                        f"📢 Рассылка в процессе...\n\n"
                        f"👥 Всего получателей: {total_users}\n"
                        f"✅ Отправлено: {sent_count}\n"
                        f"❌ Ошибок: {failed_count}\n"
                        f"📊 Прогресс: {((i + 1) / total_users * 100):.1f}%"
                    )
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failed_count += 1
                logger.warning(f"Failed to send broadcast to user {user.telegram_id}: {e}")
        
        # Final result
        success_text = get_message('broadcast_success', sent=sent_count, total=total_users)
        if failed_count > 0:
            success_text += f"\n❌ Не удалось отправить: {failed_count}"
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=success_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        log_admin_action(user_id, "broadcast_sent", details=f"Sent to {sent_count}/{total_users} users")
        
    finally:
        session.close()


async def admin_payouts_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список заявок на вывод реферальных средств."""
    query = update.callback_query
    await query.answer()
    session = db_manager.get_session()
    try:
        pending = session.query(ReferralPayout).filter(ReferralPayout.status == 'pending').order_by(ReferralPayout.created_at.desc()).all()
        lines = []
        keyboard = []
        for p in pending:
            u = session.query(User).filter_by(id=p.user_id).first()
            name = get_user_display_name(u) if u else f"ID:{p.user_id}"
            lines.append(
                f"💳 #{p.id} — {p.amount:.2f} ₽\n"
                f"   👤 {name} (tg: {u.telegram_id if u else '—'})\n"
                f"   📝 {escape_html((p.payment_details or '')[:80])}\n"
            )
            keyboard.append([
                InlineKeyboardButton(f"✅ Выплачено #{p.id}", callback_data=f"admin_payout_complete_{p.id}"),
                InlineKeyboardButton(f"❌ Отклонить #{p.id}", callback_data=f"admin_payout_reject_{p.id}"),
            ])
        text = "💳 <b>Заявки на вывод реферальных средств</b>\n\n"
        if not lines:
            text += "Нет ожидающих заявок."
        else:
            text += "\n".join(lines)
        keyboard.append([InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')])
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    finally:
        session.close()


async def admin_payout_complete(update: Update, context: ContextTypes.DEFAULT_TYPE, payout_id: int) -> None:
    """Отметить выплату выполненной и списать баланс пользователя."""
    query = update.callback_query
    session = db_manager.get_session()
    try:
        payout = session.query(ReferralPayout).filter_by(id=payout_id, status='pending').first()
        if not payout:
            await query.answer("Заявка не найдена или уже обработана.", show_alert=True)
            return
        user = session.query(User).filter_by(id=payout.user_id).first()
        if not user:
            await query.answer("Пользователь не найден.", show_alert=True)
            return
        payout.status = 'completed'
        payout.completed_at = datetime.utcnow()
        user.referral_balance -= payout.amount
        if user.referral_balance < 0:
            user.referral_balance = 0
        session.commit()
        await query.answer("Выплата отмечена выполненной.")
        try:
            await context.bot.send_message(
                user.telegram_id,
                f"✅ Ваша заявка на вывод {payout.amount:.2f} ₽ выполнена. Средства переведены на указанные реквизиты.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.warning("Notify user %s about payout: %s", user.telegram_id, e)
        await admin_payouts_list(update, context)
    finally:
        session.close()


async def admin_payout_reject(update: Update, context: ContextTypes.DEFAULT_TYPE, payout_id: int) -> None:
    """Отклонить заявку на вывод (баланс не списывался)."""
    query = update.callback_query
    session = db_manager.get_session()
    try:
        payout = session.query(ReferralPayout).filter_by(id=payout_id, status='pending').first()
        if not payout:
            await query.answer("Заявка не найдена или уже обработана.", show_alert=True)
            return
        user = session.query(User).filter_by(id=payout.user_id).first()
        payout.status = 'failed'
        session.commit()
        await query.answer("Заявка отклонена.")
        if user:
            try:
                await context.bot.send_message(
                    user.telegram_id,
                    f"❌ Заявка на вывод {payout.amount:.2f} ₽ отклонена. Обратитесь в поддержку при необходимости.",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning("Notify user %s about payout reject: %s", user.telegram_id, e)
        await admin_payouts_list(update, context)
    finally:
        session.close()


async def admin_logs_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View admin logs"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Read recent log entries from file
    try:
        log_file = f"logs/vpn_bot_{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent_logs = lines[-20:]  # Last 20 lines
        
        logs_text = f"📋 <b>Последние логи</b>\n\n"
        logs_text += "<pre>"
        for line in recent_logs:
            if len(line) > 100:
                line = line[:97] + "..."
            logs_text += line
        logs_text += "</pre>"
        
    except FileNotFoundError:
        logs_text = "📋 <b>Логи</b>\n\n❌ Файл логов не найден"
    except Exception as e:
        logs_text = f"📋 <b>Логи</b>\n\n❌ Ошибка чтения логов: {str(e)}"
    
    keyboard = [
        [
            InlineKeyboardButton("📁 Скачать полный лог", callback_data='admin_download_logs'),
            InlineKeyboardButton("🔄 Обновить", callback_data='admin_logs')
        ],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=logs_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin settings"""
    query = update.callback_query
    
    settings_text = f"⚙️ <b>Настройки бота</b>\n\n"
    settings_text += f"🤖 <b>Основные:</b>\n"
    settings_text += f"   • Режим отладки: {'✅' if Config.DEBUG else '❌'}\n"
    settings_text += f"   • Уровень логов: {Config.LOG_LEVEL}\n"
    settings_text += f"   • Язык по умолчанию: {Config.DEFAULT_LANGUAGE}\n\n"
    
    settings_text += f"💰 <b>Тарифы (1 устройство):</b>\n"
    settings_text += f"   • 1 месяц: {Config.PLAN_1_MONTH_PRICE} ₽\n"
    settings_text += f"   • 3 месяца: {Config.PLAN_3_MONTH_PRICE} ₽\n"
    settings_text += f"   • 6 месяцев: {Config.PLAN_6_MONTH_PRICE} ₽\n"
    settings_text += f"   • 9 месяцев: {Config.PLAN_9_MONTH_PRICE} ₽\n"
    settings_text += f"   • 12 месяцев: {Config.PLAN_12_MONTH_PRICE} ₽\n\n"
    
    settings_text += f"🎁 <b>Реферальная программа:</b>\n"
    settings_text += f"   • Процент бонуса: {Config.REFERRAL_BONUS_PERCENT}%\n"
    settings_text += f"   • Минимум для вывода: {Config.REFERRAL_MIN_PAYOUT} ₽\n"
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Изменить тарифы", callback_data='admin_edit_prices'),
            InlineKeyboardButton("🎁 Настроить рефералы", callback_data='admin_edit_referrals')
        ],
        [
            InlineKeyboardButton("🔧 Системные настройки", callback_data='admin_system_settings'),
            InlineKeyboardButton("💾 Резервное копирование", callback_data='admin_backup')
        ],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data='admin_back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=settings_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def admin_back_to_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to admin panel"""
    query = update.callback_query
    await query.answer()
    
    # Clear any admin states
    context.user_data.pop('waiting_broadcast', None)
    context.user_data.pop('broadcast_message', None)
    
    # Show fresh admin panel
    await admin_panel_refresh(update, context)