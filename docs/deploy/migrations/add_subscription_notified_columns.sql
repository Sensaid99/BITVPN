-- Добавить колонки уведомлений об истечении подписки (для PostgreSQL / Neon).
-- Выполнить один раз в Neon Console (SQL Editor) или через psql, если колонок ещё нет.
-- API при первом запросе тоже добавит их автоматически (см. bot/models/database.py).

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS notified_3d BOOLEAN DEFAULT FALSE;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS notified_1d BOOLEAN DEFAULT FALSE;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS notified_expired BOOLEAN DEFAULT FALSE;
