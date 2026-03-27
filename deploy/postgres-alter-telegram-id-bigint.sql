-- Выполнить в Neon/PostgreSQL, если бот падает на INSERT пользователя с большим Telegram ID (> 2147483647).
-- После: перезапустить vpn-bot и miniapp-api.
ALTER TABLE public.users ALTER COLUMN telegram_id TYPE BIGINT;
