# -*- coding: utf-8 -*-
"""База данных: тикеты, ответы, список админов."""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from support_bot.config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_connection():
    """Подключение к SQLite (каждый раз новое для потокобезопасности)."""
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


def init_db():
    """Создание таблиц."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                added_by INTEGER,
                added_at TEXT,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                topic TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                closed_at TEXT,
                closed_by INTEGER,
                assigned_to INTEGER
            );
            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                from_admin_id INTEGER NOT NULL,
                from_admin_name TEXT,
                message TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS user_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS ticket_ratings (
                ticket_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                feedback TEXT,
                created_at TEXT
            );
        """)
        conn.commit()
        _ensure_assigned_to_column(conn)
        conn.commit()
        logger.info("DB initialized: %s", DATABASE_PATH)
    finally:
        conn.close()


def _ensure_assigned_to_column(conn):
    """Добавить колонку assigned_to, если её ещё нет (миграция старых БД)."""
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()]
        if "assigned_to" not in cols:
            conn.execute("ALTER TABLE tickets ADD COLUMN assigned_to INTEGER")
    except Exception as e:
        logger.debug("assigned_to column: %s", e)


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# --- Админы ---

def is_admin(user_id: int, master_ids: list) -> bool:
    """Проверка: пользователь — мастер-админ или добавленный админ."""
    if user_id in master_ids:
        return True
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def add_admin(user_id: int, username: str, full_name: str, added_by: int) -> bool:
    """Добавить админа (вызвать от имени мастера)."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO admins (user_id, username, full_name, added_by, added_at, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (user_id, username or "", full_name or "", added_by, _now())
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("add_admin: %s", e)
        return False
    finally:
        conn.close()


def deactivate_admin(user_id: int) -> bool:
    """Деактивировать админа."""
    conn = get_connection()
    try:
        conn.execute("UPDATE admins SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def get_all_admin_ids(master_ids: list) -> list:
    """Список всех ID, которым слать уведомления (мастера + активные админы)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT user_id FROM admins WHERE is_active = 1"
        ).fetchall()
        ids = {r[0] for r in rows}
        ids.update(master_ids)
        return list(ids)
    finally:
        conn.close()


def get_admins_list() -> list:
    """Список (user_id, username, full_name) активных админов."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT user_id, username, full_name FROM admins WHERE is_active = 1 ORDER BY added_at"
        ).fetchall()
    finally:
        conn.close()


# --- Тикеты ---

def create_ticket(user_id: int, username: str, full_name: str, topic: str, message: str) -> int | None:
    """Создать тикет. Возвращает ticket_id или None."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tickets (user_id, username, full_name, topic, message, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (user_id, username or "", full_name or "", topic, message, _now())
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        logger.exception("create_ticket: %s", e)
        return None
    finally:
        conn.close()


def get_open_tickets() -> list:
    """Все открытые тикеты: (id, user_id, username, full_name, topic, message, created_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, user_id, username, full_name, topic, message, created_at
               FROM tickets WHERE status = 'open' ORDER BY created_at DESC"""
        ).fetchall()
    finally:
        conn.close()


def get_closed_tickets(limit: int = 50) -> list:
    """Закрытые тикеты для архива: (id, user_id, username, full_name, topic, created_at, closed_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, user_id, username, full_name, topic, created_at, closed_at
               FROM tickets WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    finally:
        conn.close()


def get_ticket(ticket_id: int) -> tuple | None:
    """Один тикет по id: (id, user_id, username, full_name, topic, message, status, created_at, closed_at, closed_by, assigned_to)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, user_id, username, full_name, topic, message, status, created_at, closed_at, closed_by, assigned_to FROM tickets WHERE id = ?",
            (ticket_id,)
        ).fetchone()
    finally:
        conn.close()


def get_assigned_admin_id(ticket_id: int) -> int | None:
    """ID админа, назначенного на тикет (тот, кто первым ответил). None — не назначен."""
    conn = get_connection()
    try:
        r = conn.execute("SELECT assigned_to FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return r[0] if r and r[0] is not None else None
    finally:
        conn.close()


def get_user_tickets(user_id: int) -> list:
    """Тикеты пользователя: (id, topic, message, status, created_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, topic, message, status, created_at FROM tickets WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()


def close_ticket(ticket_id: int, closed_by: int) -> bool:
    """Закрыть тикет."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ? WHERE id = ?",
            (_now(), closed_by, ticket_id)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def add_reply(ticket_id: int, from_admin_id: int, from_admin_name: str, message: str) -> bool:
    """Добавить ответ админа к тикету. При первом ответе назначает тикет на этого админа (assigned_to)."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO replies (ticket_id, from_admin_id, from_admin_name, message, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (ticket_id, from_admin_id, from_admin_name or "", message, _now())
        )
        r = conn.execute("SELECT assigned_to FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if r and r[0] is None:
            conn.execute("UPDATE tickets SET assigned_to = ? WHERE id = ?", (from_admin_id, ticket_id))
        conn.commit()
        return True
    except Exception as e:
        logger.exception("add_reply: %s", e)
        return False
    finally:
        conn.close()


def get_replies(ticket_id: int) -> list:
    """Ответы по тикету: (from_admin_id, from_admin_name, message, created_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT from_admin_id, from_admin_name, message, created_at FROM replies WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,)
        ).fetchall()
    finally:
        conn.close()


def get_user_open_ticket_id(user_id: int) -> int | None:
    """ID последнего открытого тикета пользователя (для добавления сообщений в диалог)."""
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT id FROM tickets WHERE user_id = ? AND status = 'open' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def get_user_open_ticket_ids(user_id: int) -> list:
    """Список ID всех открытых тикетов пользователя."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM tickets WHERE user_id = ? AND status = 'open' ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def add_user_reply(ticket_id: int, message: str) -> bool:
    """Добавить сообщение пользователя в диалог по тикету."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO user_replies (ticket_id, message, created_at) VALUES (?, ?, ?)",
            (ticket_id, message, _now())
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("add_user_reply: %s", e)
        return False
    finally:
        conn.close()


def get_user_replies(ticket_id: int) -> list:
    """Сообщения пользователя в тикете: (message, created_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT message, created_at FROM user_replies WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,)
        ).fetchall()
    finally:
        conn.close()


def get_ticket_thread(ticket_id: int) -> list:
    """Вся переписка по тикету в хронологическом порядке.
    Элемент: (is_user: bool, label: str, message: str, created_at: str).
    """
    t = get_ticket(ticket_id)
    if not t:
        return []
    (tid, uid, username, full_name, topic, initial_msg, status, created, closed_at, closed_by, _) = t
    thread = [("user", "Клиент (начальное обращение)", initial_msg, created)]
    user_replies = get_user_replies(ticket_id)
    admin_replies = get_replies(ticket_id)
    for msg, at in user_replies:
        thread.append(("user", "Клиент", msg, at))
    for r in admin_replies:
        r_id, r_name, r_msg, r_at = r
        thread.append(("admin", f"{r_name} (ID {r_id})", r_msg, r_at))
    thread.sort(key=lambda x: x[3])
    return thread


def save_rating(ticket_id: int, user_id: int, rating: int, feedback: str | None = None) -> bool:
    """Сохранить оценку и опционально отзыв по тикету."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO ticket_ratings (ticket_id, user_id, rating, feedback, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (ticket_id, user_id, rating, feedback or "", _now())
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("save_rating: %s", e)
        return False
    finally:
        conn.close()


def update_rating_feedback(ticket_id: int, feedback: str) -> bool:
    """Добавить/обновить текстовый отзыв к уже сохранённой оценке."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE ticket_ratings SET feedback = ? WHERE ticket_id = ?",
            (feedback, ticket_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.exception("update_rating_feedback: %s", e)
        return False
    finally:
        conn.close()


def get_rating(ticket_id: int) -> tuple | None:
    """Оценка по тикету: (rating, feedback) или None."""
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT rating, feedback FROM ticket_ratings WHERE ticket_id = ?",
            (ticket_id,)
        ).fetchone()
        return r
    finally:
        conn.close()


def get_rating_counts() -> dict:
    """Количество оценок по баллам: {1: n1, 2: n2, 3: n3, 4: n4, 5: n5}."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT rating, COUNT(*) FROM ticket_ratings GROUP BY rating"
        ).fetchall()
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r, c in rows:
            if r in counts:
                counts[r] = c
        return counts
    finally:
        conn.close()


def get_ratings_by_month(months: int = 12) -> list:
    """Оценки по месяцам. Возвращает список кортежей (year_month, cnt_1, cnt_2, cnt_3, cnt_4, cnt_5).
    year_month в формате 'YYYY-MM'. Сортировка от нового к старому."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT strftime('%Y-%m', created_at) AS ym, rating, COUNT(*)
               FROM ticket_ratings
               WHERE created_at IS NOT NULL AND created_at != ''
               GROUP BY ym, rating
               ORDER BY ym DESC"""
        ).fetchall()
        by_month = {}
        for ym, rating, cnt in rows:
            if ym not in by_month:
                by_month[ym] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
            if rating in (1, 2, 3, 4, 5):
                by_month[ym][rating] = cnt
        result = []
        for ym in sorted(by_month.keys(), reverse=True)[:months]:
            c = by_month[ym]
            result.append((ym, c[1], c[2], c[3], c[4], c[5]))
        return result
    finally:
        conn.close()


def get_negative_ratings_list(limit: int = 50) -> list:
    """Тикеты с негативными оценками (1–3 звёзды). Кортеж: (ticket_id, user_id, username, full_name, rating, feedback, created_at)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT tr.ticket_id, t.user_id, t.username, t.full_name, tr.rating, tr.feedback, tr.created_at
               FROM ticket_ratings tr
               JOIN tickets t ON t.id = tr.ticket_id
               WHERE tr.rating BETWEEN 1 AND 3
               ORDER BY tr.created_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
    finally:
        conn.close()


# --- Статистика ---

def get_stats() -> dict:
    """total_tickets, open_tickets, closed_tickets, total_admins."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        open_ = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'").fetchone()[0]
        closed = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed'").fetchone()[0]
        admins = conn.execute("SELECT COUNT(*) FROM admins WHERE is_active = 1").fetchone()[0]
        return {"total_tickets": total, "open_tickets": open_, "closed_tickets": closed, "total_admins": admins}
    finally:
        conn.close()
