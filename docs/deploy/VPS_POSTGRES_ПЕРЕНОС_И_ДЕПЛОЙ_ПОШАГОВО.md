# PostgreSQL на VPS вместо Neon: перенос и дальнейший деплой

Цель: **одна база на вашем сервере** (Aeza и т.п.), без зависимости от консоли Neon. Бот и **miniapp-api** используют **одинаковый** `DATABASE_URL`.

---

## Часть 1. Установить PostgreSQL на сервере (Ubuntu/Debian)

Подключитесь по SSH под `root` или пользователем с `sudo`.

### 1.1 Пакеты и сервис

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

### 1.2 Пользователь и база

Замените `vpn_bot` / пароль на свои (латиница, без пробелов в пароле или экранируйте в URL):

```bash
sudo -u postgres psql -c "CREATE USER vpn_bot WITH PASSWORD 'СИЛЬНЫЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE vpn_bot_db OWNER vpn_bot;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE vpn_bot_db TO vpn_bot;"
# Схема public (часто уже есть)
sudo -u postgres psql -d vpn_bot_db -c "GRANT ALL ON SCHEMA public TO vpn_bot;"
```

Или выполните готовый скрипт из репозитория (после `git pull`):

```bash
cd /opt/vpn-bot   # ваш BOT_PATH
sudo bash deploy/setup_postgresql_vps.sh
```

Скрипт спросит пароль и создаст пользователя/БД — проверьте вывод в конце: строка `DATABASE_URL=...`.

### 1.3 Строка подключения

Формат:

```env
DATABASE_URL=postgresql://vpn_bot:СИЛЬНЫЙ_ПАРОЛЬ@127.0.0.1:5432/vpn_bot_db
```

Спецсимволы в пароле нужно **URL-кодировать** (`@` → `%40` и т.д.).

Проверка с сервера:

```bash
sudo -u postgres psql -d vpn_bot_db -c "SELECT 1;"
# или, если установлен клиент под пользователем бота:
psql "postgresql://vpn_bot:ПАРОЛЬ@127.0.0.1:5432/vpn_bot_db" -c "SELECT 1;"
```

---

## Часть 2. Перенести данные из Neon (если нужны старые пользователи/оплаты)

Делайте, пока ещё есть доступ к Neon **или** с любой машины, где открывается Neon и работает `pg_dump`.

### 2.1 Дамп из Neon

На ПК с установленным PostgreSQL-клиентом (или на VPS, если `pg_dump` видит Neon):

Строку подключения возьмите в **Neon Dashboard → Connection string** (не копируйте буквально пример ниже).

```bash
export NEON_URL="postgresql://USER:PASSWORD@ep-ВАШ_ХОСТ.neon.tech/neondb?sslmode=require"
pg_dump "$NEON_URL" -Fc -f /tmp/neon_backup.dump
```

`ep-xxx.region.aws.neon.tech` в документации — **только шаблон**; иначе будет ошибка `could not translate host name`. Подставьте реальный хост из Neon. Если с VPS до Neon нет сети — выполните `pg_dump` на ПК, куда открывается консоль Neon, затем перенесите файл на сервер (`scp`).

Скопируйте `/tmp/neon_backup.dump` на VPS (`scp`), если дамп делали не на сервере.

### 2.2 Восстановление в локальную БД

```bash
export LOCAL_URL="postgresql://vpn_bot:ПАРОЛЬ@127.0.0.1:5432/vpn_bot_db"
pg_restore -d "$LOCAL_URL" --no-owner --role=vpn_bot -c /tmp/neon_backup.dump
```

Флаг `-c` чистит объекты перед созданием; при ошибках прав — смотрите лог, часто достаточно повторить или импортировать в пустую БД (см. ниже «с нуля»).

**Если данных не нужно** — пропустите дамп: при первом запуске бота таблицы создадутся сами (`create_tables()`).

---

## Часть 3. Подключить бота и API

### 3.1 Один `.env` на сервере

Файл обычно `/opt/vpn-bot/.env` (как у вас в `deploy_config.cmd`).

1. Замените строку:

```env
DATABASE_URL=postgresql://vpn_bot:...@127.0.0.1:5432/vpn_bot_db
```

2. Убедитесь, что **тот же** `DATABASE_URL` читает и **vpn-bot**, и **miniapp-api** (один файл или дубликат с тем же значением).

### 3.2 Перезапуск

```bash
sudo systemctl restart vpn-bot
sudo systemctl restart miniapp-api
```

### 3.3 Проверка

```bash
sudo journalctl -u vpn-bot -n 40 --no-pager
sudo journalctl -u miniapp-api -n 40 --no-pager
```

В логе бота должно быть что-то вроде «Database initialized». Ошибки SSL/connection — проверьте пароль, `127.0.0.1`, что PostgreSQL слушает локально (`ss -tlnp | grep 5432`).

---

## Часть 4. Дальнейшие обновления кода (быстрый цикл)

Как у вас уже настроено:

| Действие | Где |
|----------|-----|
| Правки на ПК, пуш в Git | Локально → `git push` |
| Обновление на сервере | `ДЕПЛОЙ_НА_СЕРВЕР.bat` или вручную: `git pull` в `/opt/vpn-bot`, затем рестарт сервисов |
| Только мини-апп + API | `ДЕПЛОЙ_МИНИАПП_API_ТОЛЬКО.bat` и т.д. |

После каждого деплоя с изменением зависимостей:

```bash
cd /opt/vpn-bot
source venv/bin/activate   # если venv
pip install -r requirements.txt
sudo systemctl restart vpn-bot miniapp-api
```

---

## Часть 5. Резервные копии (обязательно на проде)

Ежедневный cron под `root` или отдельный пользователь:

```bash
sudo -u postgres pg_dump vpn_bot_db -Fc -f /var/backups/vpn_bot_$(date +%F).dump
```

Храните копии **вне** сервера (другой диск / облако).

---

## Happ: на телефоне 1 сервер, на ПК 2

Уже исправлено в коде: запросы к 3x-ui идут с **фиксированным User-Agent** (не «мобильный» из Happ). Проверьте на сервере в `.env`:

- `HAPP_SUBSCRIPTION_URLS` — **два** URL через запятую (две панели или две подписки), **без** лишних пробелов внутри URL.
- При необходимости: `HAPP_SUBSCRIPTION_FETCH_UA` — десктопный Chrome (см. `.env.example`).
- После правок: `sudo systemctl restart miniapp-api`, в Happ — **обновить подписку** (круговые стрелки).

Отладка (включите `MINIAPP_EXPOSE_DEBUG=1` временно):

`GET /api/miniapp/debug-sub-content?install_code=ВАШ_12_СИМВОЛОВ` — покажет, сколько нод с каждого upstream.

Красивые имена нод: **`HAPP_SUBSCRIPTION_NODE_NAMES`** — см. `.env.example` и `docs/happ/HAPP_КНОПКА_ОБНОВЛЕНИЯ.md`.

---

## Краткий чеклист

1. [ ] PostgreSQL на VPS, пользователь и БД созданы  
2. [ ] `DATABASE_URL` в `.env` → локальный Postgres  
3. [ ] `pg_restore` из Neon **или** пустая БД и первый запуск  
4. [ ] `restart vpn-bot` + `restart miniapp-api`  
5. [ ] Проверка `/start` в боте и мини-аппа  
6. [ ] Бэкап `pg_dump` по cron  
