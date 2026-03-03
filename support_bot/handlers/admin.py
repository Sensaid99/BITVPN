# -*- coding: utf-8 -*-
"""Обработчики для админов: тикеты, ответы, закрытие, добавление админов, статистика."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from support_bot.config import SERVICE_NAME, MASTER_ADMIN_IDS
from support_bot.database import (
    is_admin,
    get_open_tickets,
    get_closed_tickets,
    get_ticket,
    get_replies,
    get_ticket_thread,
    get_rating,
    get_rating_counts,
    get_ratings_by_month,
    get_negative_ratings_list,
    close_ticket,
    add_reply,
    add_admin as db_add_admin,
    get_admins_list,
    get_stats,
    get_all_admin_ids,
)

logger = logging.getLogger(__name__)

ENTER_REPLY, ENTER_NEW_ADMIN_ID = range(2)

TOPICS = {"tech": "🔧 Техническая", "payment": "💰 Оплата", "other": "📝 Другое"}

# Постоянная кнопка внизу для админов (как «Открыть приложение» в VPN-боте)
ADMIN_PANEL_BUTTON_TEXT = "🔧 Панель администратора"


def get_admin_reply_keyboard():
    """Клавиатура внизу под вводом для быстрого доступа в панель."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(ADMIN_PANEL_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


def _admin_only(func):
    """Проверка прав админа."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or not is_admin(user_id, MASTER_ADMIN_IDS):
            if update.callback_query:
                await update.callback_query.answer("Доступ только для администраторов.", show_alert=True)
            else:
                await update.message.reply_text("Доступ только для администраторов.")
            return None
        return await func(update, context, *args, **kwargs)
    return wrapper


@_admin_only
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, set_reply_keyboard: bool = False):
    """Панель администратора. set_reply_keyboard=True — показать кнопку «Панель администратора» внизу."""
    context.user_data.pop("admin_active_ticket_id", None)
    query = update.callback_query
    msg = update.message
    text = (
        f"🔧 <b>Панель администратора</b>\n\n"
        f"Сервис: {SERVICE_NAME}\n"
        f"Ваш ID: <code>{update.effective_user.id}</code>\n\n"
        f"Выберите действие:"
    )
    keyboard = [
        [InlineKeyboardButton("📋 Открытые обращения", callback_data="admin_tickets")],
        [InlineKeyboardButton("📁 Архив обращений", callback_data="admin_archive")],
        [InlineKeyboardButton("⭐ Отзывы", callback_data="admin_reviews")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Управление админами", callback_data="admin_manage")],
        [InlineKeyboardButton("◀️ В пользовательское меню", callback_data="back_to_main")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await msg.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        if set_reply_keyboard:
            await msg.reply_text(
                "Кнопка внизу — быстрый вход в панель.",
                reply_markup=get_admin_reply_keyboard(),
            )


@_admin_only
async def admin_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список открытых тикетов."""
    query = update.callback_query
    await query.answer()
    tickets = get_open_tickets()
    if not tickets:
        await query.edit_message_text(
            "📋 Нет открытых обращений.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin_back")
            ]]),
            parse_mode="HTML"
        )
        return
    text = "📋 <b>Открытые обращения</b>\n\n"
    keyboard = []
    for t in tickets:
        tid, uid, username, full_name, topic, message, created = t
        topic_label = TOPICS.get(topic, topic)
        text += f"#{tid} — {topic_label} — {full_name or username or uid}\n"
        keyboard.append([
            InlineKeyboardButton(f"💬 Ответ #{tid}", callback_data=f"reply_ticket_{tid}"),
            InlineKeyboardButton(f"✅ Закрыть #{tid}", callback_data=f"close_ticket_{tid}"),
        ])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


@_admin_only
async def admin_ticket_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    """Детали тикета и кнопки Ответ / Закрыть."""
    query = update.callback_query
    await query.answer()
    t = get_ticket(ticket_id)
    if not t:
        await query.edit_message_text("Тикет не найден.")
        return
    (tid, uid, username, full_name, topic, message, status, created, closed_at, closed_by, _) = t
    topic_label = TOPICS.get(topic, topic)
    lines = [
        f"<b>Обращение #{tid}</b> — {topic_label}",
        f"👤 {full_name or username or '—'} (@{username or '—'}) ID: <code>{uid}</code>",
        f"📅 {created}",
        "",
        message,
    ]
    thread = get_ticket_thread(tid)
    if len(thread) > 1:
        lines.append("\n<b>Переписка:</b>")
        for is_user, label, msg, at in thread[1:]:
            prefix = "👤" if is_user == "user" else "👨‍💼"
            lines.append(f"  {prefix} <b>{label}</b> ({at}):\n    {msg}")
    keyboard = [
        [InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket_{tid}")],
        [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_ticket_{tid}")],
        [InlineKeyboardButton("◀️ К списку", callback_data="admin_tickets")],
    ]
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


def _format_ticket_thread(ticket_id: int, for_reply: bool = False) -> str:
    """Формирует текст тикета: вся переписка по порядку (клиент и сотрудники)."""
    t = get_ticket(ticket_id)
    if not t:
        return ""
    (tid, uid, username, full_name, topic, _, status, created, closed_at, closed_by, _) = t
    topic_label = TOPICS.get(topic, topic)
    lines = [
        f"<b>Обращение #{tid}</b> — {topic_label}",
        f"👤 Клиент: {full_name or username or '—'} (@{username or '—'}) ID: <code>{uid}</code>",
        f"📅 {created}",
        "",
        "<b>Переписка:</b>",
    ]
    for is_user, label, msg, at in get_ticket_thread(tid):
        prefix = "👤" if is_user == "user" else "👨‍💼"
        lines.append(f"  {prefix} <b>{label}</b> ({at}):\n    {msg}")
    if for_reply:
        lines.append("")
        lines.append("✏️ Введите ваш ответ ниже (или /cancel для отмены):")
    return "\n".join(lines)


@_admin_only
async def reply_ticket_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажали «Ответить» — показываем переписку и просим текст ответа."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("reply_ticket_"):
        return ConversationHandler.END
    ticket_id = int(data.replace("reply_ticket_", ""))
    context.user_data["reply_ticket_id"] = ticket_id
    context.user_data["admin_active_ticket_id"] = ticket_id
    text = _format_ticket_thread(ticket_id, for_reply=True)
    if len(text) > 4000:
        text = text[:3990] + "\n\n… (обрезано)\n\n✏️ Введите ваш ответ ниже (или /cancel):"
    await query.edit_message_text(text, parse_mode="HTML")
    return ENTER_REPLY


async def admin_handle_continue_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Админ пишет сообщение в чат — если у него «активный» тикет, отправляем ответ клиенту.
    Возвращает True, если сообщение обработано (ответ ушёл в тикет).
    """
    ticket_id = context.user_data.get("admin_active_ticket_id")
    if not ticket_id:
        return False
    text = (update.message and update.message.text) or ""
    if not text.strip():
        return False
    t = get_ticket(ticket_id)
    if not t or t[6] != "open":
        context.user_data.pop("admin_active_ticket_id", None)
        await update.message.reply_text("Тикет закрыт или не найден. Откройте панель и выберите другое обращение.")
        return True
    user_id = t[1]
    admin = update.effective_user
    add_reply(ticket_id, admin.id, admin.full_name, text.strip())
    context.user_data.pop("admin_active_ticket_id", None)
    await update.message.reply_text(
        f"✅ Отправлено в тикет #{ticket_id}. Чтобы ответить снова — откройте панель и выберите «Ответить» по обращению #{ticket_id}."
    )
    try:
        await context.bot.send_message(
            user_id,
            f"💬 <b>Ответ по обращению #{ticket_id}</b>\n\n{text.strip()}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("Send reply to user %s: %s", user_id, e)
    return True


async def reply_ticket_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ прислал текст ответа (из сценария «Ответить») — сохраняем и отправляем пользователю."""
    context.user_data.pop("reply_ticket_id", None)
    ticket_id = context.user_data.get("admin_active_ticket_id")
    if not ticket_id:
        return ConversationHandler.END
    text = (update.message and update.message.text) or ""
    if not text.strip():
        await update.message.reply_text("Введите непустой ответ.")
        return ENTER_REPLY
    t = get_ticket(ticket_id)
    if not t or t[6] != "open":
        await update.message.reply_text("Тикет не найден или уже закрыт.")
        return ConversationHandler.END
    user_id = t[1]
    admin = update.effective_user
    add_reply(ticket_id, admin.id, admin.full_name, text.strip())
    context.user_data.pop("admin_active_ticket_id", None)
    await update.message.reply_text(
        f"✅ Ответ на тикет #{ticket_id} отправлен. Чтобы ответить снова — откройте панель → Открытые обращения → Ответить по обращению #{ticket_id}."
    )
    try:
        await context.bot.send_message(
            user_id,
            f"💬 <b>Ответ по обращению #{ticket_id}</b>\n\n{text.strip()}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("Send reply to user %s: %s", user_id, e)
    return ConversationHandler.END


@_admin_only
async def close_ticket_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрыть тикет и уведомить пользователя."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("close_ticket_"):
        return
    ticket_id = int(data.replace("close_ticket_", ""))
    t = get_ticket(ticket_id)
    if not t:
        await query.answer("Тикет не найден.", show_alert=True)
        return
    if t[6] == "closed":
        await query.answer("Тикет уже закрыт.", show_alert=True)
        return
    close_ticket(ticket_id, update.effective_user.id)
    if context.user_data.get("admin_active_ticket_id") == ticket_id:
        context.user_data.pop("admin_active_ticket_id", None)
    user_id = t[1]
    try:
        await context.bot.send_message(
            user_id,
            f"✅ Обращение #{ticket_id} закрыто. Если вопрос остался — создайте новое обращение.",
            parse_mode="HTML"
        )
        # Запрос оценки и отзыва
        rate_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1", callback_data=f"rate_1_{ticket_id}"),
                InlineKeyboardButton("2", callback_data=f"rate_2_{ticket_id}"),
                InlineKeyboardButton("3", callback_data=f"rate_3_{ticket_id}"),
                InlineKeyboardButton("4", callback_data=f"rate_4_{ticket_id}"),
                InlineKeyboardButton("5", callback_data=f"rate_5_{ticket_id}"),
            ],
            [InlineKeyboardButton("Пропустить", callback_data=f"rate_skip_{ticket_id}")],
        ])
        await context.bot.send_message(
            user_id,
            "⭐ Оцените, пожалуйста, работу поддержки (1—5):",
            reply_markup=rate_kb,
        )
    except Exception as e:
        logger.warning("Notify user %s ticket closed: %s", user_id, e)
    await query.edit_message_text(
        f"✅ Тикет #{ticket_id} закрыт. Пользователю отправлен запрос оценки.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ К списку", callback_data="admin_tickets")
        ]])
    )


@_admin_only
async def admin_archive_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список закрытых тикетов (архив) — для контроля переписки сотрудников."""
    query = update.callback_query
    await query.answer()
    tickets = get_closed_tickets(limit=50)
    if not tickets:
        await query.edit_message_text(
            "📁 В архиве пока нет закрытых обращений.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin_back")
            ]]),
            parse_mode="HTML"
        )
        return
    text = (
        "📁 <b>Архив обращений</b> (последние 50)\n\n"
        "Выберите тикет — откроется полная переписка: что писал клиент и кто что ответил (с датой и ID сотрудника)."
    )
    keyboard = []
    for t in tickets:
        tid, uid, username, full_name, topic, created, closed_at = t
        topic_label = TOPICS.get(topic, topic)
        label = f"#{tid} — {topic_label} — {full_name or username or str(uid)}"
        if len(label) > 35:
            label = f"#{tid} — {topic_label}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"view_archive_{tid}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


@_admin_only
async def admin_archive_view(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    """Просмотр закрытого тикета: что писал клиент, кто что ответил (контроль сотрудников)."""
    query = update.callback_query
    await query.answer()
    t = get_ticket(ticket_id)
    if not t:
        await query.answer("Тикет не найден.", show_alert=True)
        return
    (tid, uid, username, full_name, topic, _, status, created, closed_at, closed_by, _) = t
    topic_label = TOPICS.get(topic, topic)
    lines = [
        f"<b>Обращение #{tid}</b> — {topic_label} [ЗАКРЫТ]",
        f"👤 Клиент: {full_name or username or '—'} (@{username or '—'}) ID: <code>{uid}</code>",
        f"📅 Создан: {created} · Закрыт: {closed_at or '—'}",
        "",
        "<b>Переписка:</b>",
    ]
    for is_user, label, msg, at in get_ticket_thread(tid):
        prefix = "👤" if is_user == "user" else "👨‍💼"
        lines.append(f"  {prefix} <b>{label}</b> ({at}):\n    {msg}")
    rating = get_rating(tid)
    if rating:
        r_stars, r_feedback = rating
        lines.append("")
        lines.append(f"⭐ Оценка: {r_stars}/5")
        if r_feedback:
            lines.append(f"💬 Отзыв: {r_feedback}")
    keyboard = [
        [InlineKeyboardButton("◀️ В архив", callback_data="admin_archive")],
        [InlineKeyboardButton("◀️ В панель", callback_data="admin_back")],
    ]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n\n… (текст обрезан)"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


@_admin_only
async def admin_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Раздел «Отзывы»: сводка по оценкам 1–5 и два подраздела."""
    query = update.callback_query
    await query.answer()
    counts = get_rating_counts()
    total = sum(counts.values())
    lines = [
        "⭐ <b>Отзывы</b>",
        "",
        "Количество оценок по баллам:",
        f"  5 звёзд: {counts[5]}",
        f"  4 звезды: {counts[4]}",
        f"  3 звезды: {counts[3]}",
        f"  2 звезды: {counts[2]}",
        f"  1 звезда: {counts[1]}",
        f"  Всего: {total}",
        "",
        "Выберите подраздел:",
    ]
    keyboard = [
        [InlineKeyboardButton("📊 Оценки клиентов", callback_data="admin_reviews_ratings")],
        [InlineKeyboardButton("💬 Отзывы клиентов", callback_data="admin_reviews_feedback")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")],
    ]
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


@_admin_only
async def admin_reviews_ratings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оценки клиентов — таблица по месяцам (сколько оценок 1–5 за месяц)."""
    query = update.callback_query
    await query.answer()
    by_month = get_ratings_by_month(12)
    if not by_month:
        text = (
            "📊 <b>Оценки клиентов</b>\n\n"
            "За выбранный период оценок пока нет."
        )
    else:
        lines = ["📊 <b>Оценки клиентов</b> (по месяцам)\n"]
        lines.append("<pre>Месяц     | 1   | 2   | 3   | 4   | 5   | Всего")
        lines.append("----------+-----+-----+-----+-----+-----+------")
        for ym, c1, c2, c3, c4, c5 in by_month:
            total = c1 + c2 + c3 + c4 + c5
            lines.append(f"{ym}   | {c1:3} | {c2:3} | {c3:3} | {c4:3} | {c5:3} | {total:4}")
        lines.append("</pre>")
        text = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("◀️ К отзывам", callback_data="admin_reviews")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


@_admin_only
async def admin_reviews_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список обращений с негативными оценками (1–3); по нажатию — переписка с ID клиента и админа."""
    query = update.callback_query
    await query.answer()
    items = get_negative_ratings_list(50)
    if not items:
        text = (
            "💬 <b>Отзывы клиентов</b> (негативные оценки 1–3)\n\n"
            "Пока нет обращений с низкими оценками."
        )
        keyboard = [[InlineKeyboardButton("◀️ К отзывам", callback_data="admin_reviews")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return
    text = "💬 <b>Отзывы клиентов</b> (негативные оценки 1–3)\n\nНажмите на обращение — откроется переписка (клиент и администратор с ID/username).\n\n"
    keyboard = []
    for tid, uid, username, full_name, rating, feedback, created_at in items:
        label = f"#{tid} — {rating}⭐ — {full_name or username or uid}"
        if feedback:
            short = (feedback[:25] + "…") if len(feedback) > 25 else feedback
            label += f" — {short}"
        if len(label) > 40:
            label = f"#{tid} — {rating}⭐ — {full_name or username or uid}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"view_review_ticket_{tid}")])
    keyboard.append([InlineKeyboardButton("◀️ К отзывам", callback_data="admin_reviews")])
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


@_admin_only
async def admin_review_ticket_view(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: int):
    """Просмотр переписки по тикету из раздела «Отзывы клиентов»: клиент и админ с ID/username."""
    query = update.callback_query
    await query.answer()
    t = get_ticket(ticket_id)
    if not t:
        await query.answer("Тикет не найден.", show_alert=True)
        return
    (tid, uid, username, full_name, topic, _, status, created, closed_at, closed_by, _) = t
    topic_label = TOPICS.get(topic, topic)
    lines = [
        f"<b>Обращение #{tid}</b> — {topic_label}",
        f"👤 Клиент: {full_name or '—'} (@{username or '—'}) ID: <code>{uid}</code>",
        f"📅 Создан: {created}",
        "",
        "<b>Переписка:</b>",
    ]
    for is_user, label, msg, at in get_ticket_thread(tid):
        prefix = "👤" if is_user == "user" else "👨‍💼"
        lines.append(f"  {prefix} <b>{label}</b> ({at}):\n    {msg}")
    rating = get_rating(tid)
    if rating:
        r_stars, r_feedback = rating
        lines.append("")
        lines.append(f"⭐ Оценка: {r_stars}/5")
        if r_feedback:
            lines.append(f"💬 Отзыв: {r_feedback}")
    keyboard = [
        [InlineKeyboardButton("◀️ К списку отзывов", callback_data="admin_reviews_feedback")],
        [InlineKeyboardButton("◀️ К отзывам", callback_data="admin_reviews")],
    ]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n\n… (текст обрезан)"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


@_admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика."""
    query = update.callback_query
    await query.answer()
    s = get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Всего обращений: {s['total_tickets']}\n"
        f"Открыто: {s['open_tickets']}\n"
        f"Закрыто: {s['closed_tickets']}\n"
        f"Администраторов: {s['total_admins']}"
    )
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


@_admin_only
async def admin_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление админами: список + добавить (только мастер)."""
    query = update.callback_query
    await query.answer()
    admins = get_admins_list()
    master_ids = MASTER_ADMIN_IDS
    is_master = update.effective_user.id in master_ids
    lines = ["👥 <b>Администраторы</b>\n"]
    for uid, uname, fname in admins:
        lines.append(f"• {fname or uname or '—'} (@{uname or '—'}) <code>{uid}</code>")
    if master_ids:
        lines.append("\n<b>Главные админы</b> (из .env):")
        for mid in master_ids:
            lines.append(f"• <code>{mid}</code>")
    text = "\n".join(lines)
    keyboard = []
    if is_master:
        keyboard.append([InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin_start")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления админа (только мастер)."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in MASTER_ADMIN_IDS:
        await query.answer("Только главный админ может добавлять.", show_alert=True)
        return ConversationHandler.END
    await query.edit_message_text(
        "✏️ Перешлите любое сообщение от пользователя, которого хотите сделать админом, "
        "или отправьте его Telegram ID (число). Отмена: /cancel"
    )
    return ENTER_NEW_ADMIN_ID


async def add_admin_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пересланного сообщения или числа — добавление админа."""
    if update.effective_user.id not in MASTER_ADMIN_IDS:
        return ConversationHandler.END
    user_id = None
    username = None
    full_name = None
    msg = update.message
    if msg.forward_from:
        u = msg.forward_from
        user_id = u.id
        username = getattr(u, "username", None)
        fn = getattr(u, "first_name", None) or ""
        ln = getattr(u, "last_name", None) or ""
        full_name = (fn + " " + ln).strip() or fn
    elif msg.text and msg.text.strip().isdigit():
        user_id = int(msg.text.strip())
    if not user_id:
        await msg.reply_text(
            "Отправьте пересланное сообщение от пользователя или его Telegram ID (число)."
        )
        return ENTER_NEW_ADMIN_ID
    added = db_add_admin(user_id, username, full_name, update.effective_user.id)
    if added:
        await update.message.reply_text(f"✅ Пользователь {user_id} добавлен в администраторы.")
    else:
        await update.message.reply_text("❌ Не удалось добавить.")
    return ConversationHandler.END


async def add_admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добавление админа отменено.")
    return ConversationHandler.END


async def reply_ticket_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена ответа на тикет."""
    context.user_data.pop("reply_ticket_id", None)
    await update.message.reply_text("Ответ отменён.")
    return ConversationHandler.END


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка «Назад» в админке — вернуться в панель."""
    query = update.callback_query
    await query.answer()
    await show_admin_panel(update, context)
