# -*- coding: utf-8 -*-
"""Обработчики для пользователей: старт, тикеты, FAQ."""

import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from support_bot.config import SERVICE_NAME, MASTER_ADMIN_IDS
from support_bot.database import (
    is_admin,
    create_ticket,
    get_user_tickets,
    get_user_open_ticket_id,
    get_user_open_ticket_ids,
    add_user_reply,
    save_rating,
    update_rating_feedback,
    get_all_admin_ids,
    get_assigned_admin_id,
    get_ticket,
    get_replies,
    init_db,
)

logger = logging.getLogger(__name__)

# Состояния для создания тикета
CHOOSE_TOPIC, ENTER_MESSAGE = range(2)

TOPICS = {
    "tech": "🔧 Техническая проблема",
    "payment": "💰 Оплата / возврат",
    "other": "📝 Другое",
}

WELCOME_USER = (
    "👋 Здравствуйте!\n\n"
    "Здесь вы можете создать обращение в поддержку {service}, "
    "посмотреть свои тикеты или прочитать FAQ.\n\n"
    "Выберите действие:"
).format(service=SERVICE_NAME)

FAQ_TEXT = (
    "❓ <b>Часто задаваемые вопросы</b>\n\n"
    "• <b>Не подключается VPN</b> — проверьте логин/пароль и выбранный сервер. Переустановите конфиг при необходимости.\n\n"
    "• <b>Медленная скорость</b> — попробуйте другой сервер или протокол (WireGuard обычно быстрее).\n\n"
    "• <b>Оплата не прошла</b> — подождите 5–10 минут. Если доступ не пришёл — создайте обращение с темой «Оплата».\n\n"
    "• <b>Нужна настройка на устройстве</b> — опишите устройство и ОС в новом обращении.\n\n"
    "Если не нашли ответ — нажмите «Создать обращение» и опишите проблему."
)


MAIN_MENU_BUTTON_TEXT = "Главное меню"


def user_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Создать обращение", callback_data="new_ticket")],
        [InlineKeyboardButton("📋 Мои обращения", callback_data="my_tickets")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
    ])


def get_user_reply_keyboard():
    """Клавиатура внизу для клиента (как «Открыть приложение» в VPN-боте)."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(MAIN_MENU_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start: пользователь видит меню, админ — админ-панель."""
    init_db()
    user = update.effective_user
    if is_admin(user.id, MASTER_ADMIN_IDS):
        from support_bot.handlers.admin import show_admin_panel
        return await show_admin_panel(update, context, set_reply_keyboard=True)
    await update.message.reply_text(
        WELCOME_USER,
        reply_markup=user_menu_keyboard(),
        parse_mode="HTML"
    )
    await update.message.reply_text(
        "Кнопка внизу — главное меню (создать обращение, мои обращения, FAQ).",
        reply_markup=get_user_reply_keyboard(),
    )


async def show_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать пользовательское меню (по callback «Назад» и т.д.)."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            WELCOME_USER,
            reply_markup=user_menu_keyboard(),
            parse_mode="HTML"
        )
    return ConversationHandler.END


async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать FAQ."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("◀️ В меню", callback_data="back_to_main")]]
    await query.edit_message_text(
        FAQ_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список тикетов пользователя."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    tickets = get_user_tickets(user_id)
    if not tickets:
        text = "📋 У вас пока нет обращений.\n\nНажмите «Создать обращение», чтобы написать в поддержку."
    else:
        lines = []
        for t in tickets:
            tid, topic, msg, status, created = t
            st = "🟢 Открыт" if status == "open" else "🔴 Закрыт"
            lines.append(f"• #{tid} — {TOPICS.get(topic, topic)} — {st}\n  {created}")
        text = "📋 <b>Ваши обращения</b>\n\n" + "\n\n".join(lines)
    keyboard = [[InlineKeyboardButton("◀️ В меню", callback_data="back_to_main")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# --- Создание тикета (ConversationHandler) ---

async def new_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания тикета: выбор темы."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(TOPICS["tech"], callback_data="topic_tech")],
        [InlineKeyboardButton(TOPICS["payment"], callback_data="topic_payment")],
        [InlineKeyboardButton(TOPICS["other"], callback_data="topic_other")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="back_to_main")],
    ]
    await query.edit_message_text(
        "📝 <b>Создание обращения</b>\n\nВыберите тему:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CHOOSE_TOPIC


async def new_ticket_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь выбрал тему — просим текст."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "back_to_main":
        await show_user_menu(update, context)
        return ConversationHandler.END
    if not data.startswith("topic_"):
        return CHOOSE_TOPIC
    topic = data.replace("topic_", "")
    context.user_data["ticket_topic"] = topic
    await query.edit_message_text(
        "✏️ Опишите вашу проблему или вопрос одним сообщением:"
    )
    return ENTER_MESSAGE


async def new_ticket_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь прислал текст — создаём тикет и уведомляем админов."""
    topic = context.user_data.pop("ticket_topic", "other")
    message = (update.message and update.message.text) or ""
    if not message.strip():
        await update.message.reply_text("Пожалуйста, введите текст обращения.")
        return ENTER_MESSAGE
    user = update.effective_user
    ticket_id = create_ticket(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        topic=topic,
        message=message.strip()
    )
    if not ticket_id:
        await update.message.reply_text("❌ Не удалось создать обращение. Попробуйте позже.")
        return ConversationHandler.END

    topic_label = TOPICS.get(topic, topic)
    await update.message.reply_text(
        f"✅ Обращение #{ticket_id} создано.\n\n"
        f"Тема: {topic_label}\n\n"
        f"⏱ Ожидайте ответа в течение 24 часов.\n\n"
        f"💬 Вы можете продолжать диалог: просто пишите сообщения в этот чат — они автоматически добавятся в обращение. "
        f"Ответ поддержки придёт сюда же.",
        reply_markup=user_menu_keyboard(),
        parse_mode="HTML"
    )

    # Уведомление всем админам
    admin_ids = get_all_admin_ids(MASTER_ADMIN_IDS)
    notify_text = (
        f"🆕 <b>Новое обращение #{ticket_id}</b>\n\n"
        f"👤 {user.full_name or 'Без имени'} (@{user.username or '—'}) ID: <code>{user.id}</code>\n"
        f"📌 Тема: {topic_label}\n\n"
        f"💬 {message.strip()}"
    )
    for aid in admin_ids:
        try:
            await context.bot.send_message(aid, notify_text, parse_mode="HTML")
        except Exception as e:
            logger.warning("Notify admin %s: %s", aid, e)

    # Чтобы не дублировать уведомление «Клиент дописал» (то же сообщение попадёт в user_free_message)
    context.user_data["last_created_ticket_id"] = ticket_id
    context.user_data["last_created_ticket_at"] = time.time()

    return ConversationHandler.END


async def cancel_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена создания тикета."""
    context.user_data.pop("ticket_topic", None)
    await update.message.reply_text("Отменено.", reply_markup=user_menu_keyboard(), parse_mode="HTML")
    return ConversationHandler.END


async def user_free_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сообщение вне сценария: админ — ответ в активный тикет; пользователь — в тикет или отзыв."""
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return
    # Кнопка «Главное меню» у клиента — показать список (создать обращение, мои обращения, FAQ)
    if text == MAIN_MENU_BUTTON_TEXT and not is_admin(user.id, MASTER_ADMIN_IDS):
        await update.message.reply_text(
            WELCOME_USER,
            reply_markup=user_menu_keyboard(),
            parse_mode="HTML",
        )
        return
    if is_admin(user.id, MASTER_ADMIN_IDS):
        from support_bot.handlers.admin import show_admin_panel, admin_handle_continue_reply, ADMIN_PANEL_BUTTON_TEXT
        if text.strip() == ADMIN_PANEL_BUTTON_TEXT or text.strip() == "Панель администратора":
            await show_admin_panel(update, context)
            return
        if await admin_handle_continue_reply(update, context):
            return
    # Далее только для обычных пользователей
    # Ожидаем текстовый отзыв после оценки?
    tid = context.user_data.pop("pending_feedback", None)
    if tid is not None:
        update_rating_feedback(tid, text)
        context.user_data.pop("last_rating", None)
        await update.message.reply_text("💬 Спасибо за отзыв!")
        return
    # Добавляем в обращение только если у пользователя ровно одно открытое (после закрытия тикета не подставляем другое)
    open_ids = get_user_open_ticket_ids(user.id)
    if not open_ids:
        # Админу не показываем сообщение для клиентов — у него нет «обращений» как у пользователя
        if not is_admin(user.id, MASTER_ADMIN_IDS):
            await update.message.reply_text(
                "📋 У вас нет открытых обращений. Обращение по этому вопросу закрыто.\n\n"
                "Создайте новое обращение через меню (кнопка «📝 Создать обращение»), если вопрос остался.",
                reply_markup=user_menu_keyboard(),
            )
        return
    if len(open_ids) > 1:
        # Отправляем предупреждение только один раз, чтобы не дублировать сообщение
        last = context.user_data.get("last_multi_ticket_warning") or 0
        if time.time() - last > 60:
            context.user_data["last_multi_ticket_warning"] = time.time()
            await update.message.reply_text(
                "📋 У вас несколько открытых обращений. Зайдите в «Мои обращения» или создайте новое через меню.",
                reply_markup=user_menu_keyboard(),
            )
        return
    ticket_id = open_ids[0]
    if not add_user_reply(ticket_id, text):
        await update.message.reply_text("❌ Не удалось добавить сообщение. Попробуйте позже.")
        return
    await update.message.reply_text(f"✅ Сообщение добавлено в обращение #{ticket_id}. Ожидайте ответа.")
    # Не дублировать уведомление «Клиент дописал» сразу после «Новое обращение» (то же сообщение обработали дважды)
    last_created = context.user_data.get("last_created_ticket_id"), context.user_data.get("last_created_ticket_at") or 0
    if last_created[0] == ticket_id and (time.time() - last_created[1]) < 20:
        context.user_data.pop("last_created_ticket_id", None)
        context.user_data.pop("last_created_ticket_at", None)
    else:
        assigned = get_assigned_admin_id(ticket_id)
        admin_ids = [assigned] if assigned else get_all_admin_ids(MASTER_ADMIN_IDS)
        t = get_ticket(ticket_id)
        topic_label = TOPICS.get(t[4], t[4]) if t else ""
        initial_msg = t[5] if t else ""
        notify = (
            f"💬 <b>Клиент дописал в обращение #{ticket_id}</b>\n\n"
            f"📌 <b>Суть проблемы</b> ({topic_label}):\n{initial_msg}\n\n"
            f"👤 {user.full_name or user.username or '—'} (@{user.username or '—'}):\n{text}"
        )
        for aid in admin_ids:
            try:
                await context.bot.send_message(aid, notify, parse_mode="HTML")
            except Exception as e:
                logger.warning("Notify admin %s: %s", aid, e)


async def handle_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал оценку (1–5 или Пропустить). Оценку может поставить только клиент, не админ."""
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("rate_"):
        await query.answer()
        return
    user = update.effective_user
    if is_admin(user.id, MASTER_ADMIN_IDS):
        await query.answer("Оценку может поставить только клиент.", show_alert=True)
        return
    await query.answer()
    parts = data.split("_")
    if len(parts) < 3:
        return
    try:
        ticket_id = int(parts[-1])
    except ValueError:
        return
    if parts[1] == "skip":
        rating = 0
    else:
        try:
            rating = int(parts[1])
        except ValueError:
            return
        if rating not in (1, 2, 3, 4, 5):
            rating = 0
    save_rating(ticket_id, user.id, rating)
    context.user_data["pending_feedback"] = ticket_id
    context.user_data["last_rating"] = rating
    done_btn = InlineKeyboardButton("Готово", callback_data=f"feedback_done_{ticket_id}")
    await query.edit_message_text(
        "💬 Спасибо! Можете оставить текстовый отзыв — напишите его следующим сообщением или нажмите «Готово».",
        reply_markup=InlineKeyboardMarkup([[done_btn]]),
    )


async def handle_feedback_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Готово» (пропуск текстового отзыва)."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("feedback_done_"):
        return
    try:
        ticket_id = int(data.replace("feedback_done_", ""))
    except ValueError:
        return
    context.user_data.pop("pending_feedback", None)
    context.user_data.pop("last_rating", None)
    await query.edit_message_text(
        "✅ Спасибо за оценку! При новом вопросе создайте обращение через меню.",
        reply_markup=user_menu_keyboard(),
    )
