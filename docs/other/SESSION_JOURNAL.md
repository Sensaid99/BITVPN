# Журнал сессий с Cursor

Краткие факты для следующих сессий. Подробный архив старых записей удалён по запросу (не дублировать длинные разборы здесь).

---

## Актуально (последние правки)

- **`/start` без ответа в чате:** в **`bot/main.py`** у **`HTTPXRequest`** задан **`connection_pool_size`** (env **`TG_HTTP_POOL_SIZE`**, по умолчанию 16) — иначе при **`concurrent_updates(True)`** один пул HTTP даёт очередь без **`send_message ok`**. Таймауты: **`TG_HTTP_TIMEOUT`** (не ставить 15 с на медленном канале).
- **Мини-апп / Cursor:** **`.cursorignore`** — не индексировать **logs/**, **\*.glb**, копии **index.html** в корне/**public/**/**api/**; править **`webapp/index.html`**. Дубликаты **.glb** в корне и **api/** убраны из репо; батники копируют **`webapp\*.glb` → `public\`**.
- **Happ:** **`HAPP_API_URL`** = **`https://api.happ-proxy.com`**, **`HAPP_ADD_DOMAIN_URL`** = **`https://happ-proxy.com`** (не путать).

---

## Как вести дальше

При значимых правках: дата, запрос, 2–5 строк что сделано, файлы, что проверить. Без длинных логов переписки.

---

## 2026-03-27 — сжатие документации

Удалены длинные дублирующие файлы: **`SESSION_СЧЁТЧИК_УСТРОЙСТВ_ЛОГ`**, **`ПОШАГОВАЯ_НАСТРОЙКА_СЕРВЕРА_И_ХАПП`**, **`ЛОГИ_API_НА_СЕРВЕРЕ.txt`**, **`ПОШАГОВО_NGINX_И_ОШИБКА_ЗАГРУЗКИ.md`**. Логи API: **`docs/deploy/КАК_НАЙТИ_ЛОГИ_НА_СЕРВЕРЕ.txt`** и **`journalctl -u miniapp-api`**.

---

## 2026-03-28 — полный аудит «ошибок» бота + сверка `.env` (статический)

### Критично: безопасность
В чат попал **полный `.env`** с **прод**-секретами (**BOT_TOKEN**, **ЮKassa**, **Happ**, **PostgreSQL**, **HELPBIT_BOT_TOKEN**). **Рекомендация:** сменить у **@BotFather** токен основного бота и **HelpBit**; в **ЮKassa** перевыпустить секрет; при политике безопасности — пароль БД. В журнал **значения не записываются**.

### Синтаксис Python
**`python -m compileall`** по **`bot/`**, **`run.py`**, **`api_miniapp.py`**, **`support_bot/`** — **без ошибок**.

### Линтер (IDE)
По **`bot/handlers/main.py`**, **`bot/main.py`**, **`api_miniapp.py`** — **замечаний нет**.

### Автотесты **`test_bot.py`** (локально)
- **`test_config` падает**, если рядом есть **`.env`**: в **`bot/config/settings.py`** **`load_dotenv(..., override=True)`** при импорте **перезаписывает** переменные, выставленные тестом до **`import Config`** — тесты **не изолированы**.
- Устаревшая проверка: **`SUBSCRIPTION_PLANS['1_month']['price'] == 299`**, в коде/`.env` базово **100** (**`PLAN_1_MONTH_PRICE`**).
- **`test_localization` падает**: **`get_message('plan_template', ...)`** передаёт не все плейсхолдеры шаблона (**`price_per_month`**, **`duration`**, **`description`**, **`savings`** и т.д.) — **KeyError** / пустое сообщение об ошибке в выводе.
- На консоли **Windows** без **`PYTHONIOENCODING=utf-8`** возможен **`UnicodeEncodeError`** на эмодзи в **`print`**.

**Итог:** репозиторные тесты **не отражают** текущее состояние продукта; падают по дизайну/устареванию, а не обязательно из-за боя в проде.

### Сверка `.env` с **`settings.py`** / **`api_miniapp.py`** (логика, не секреты)
| Тема | Статус |
|------|--------|
| **Обязательные для бота** | **`BOT_TOKEN`**, **`ADMIN_IDS`**, **`DATABASE_URL`** — заданы; **`validate()`** их проверяет. |
| **ЮKassa + СБП** | **`YOOKASSA_*`** заданы — в **`payments.py`** СБП идёт через тот же клиент; отдельного токена СБП не требуется. |
| **Happ** | **`HAPP_API_URL`** / **`HAPP_ADD_DOMAIN_URL`** выровнены с докой (**api.** и **корень**). **`HAPP_SUBSCRIPTION_URL`**, **`HAPP_SUBSCRIPTION_REDIRECT_BASE`**, провайдер — заданы. |
| **Мини-апп** | **`WEBAPP_URL`** с **`?api=`** согласован с **`MINIAPP_API_URL`** (тот же хост API). **`MINIAPP_BYPASS_USER_IDS`** — в **`.env.example` не описан** (есть только в коде **`api_miniapp.py`**). |
| **`HAPP_ENCRYPT_SUBSCRIPTION_LINKS`** | В **`.env` нет** → в **`settings.py`** даёт **`False`** (пустая строка не **true**). В **`.env.example`** по умолчанию **`true`** — **расхождение с примером**; не баг, если сознательно показываете HTTPS, а не **happ://**. |
| **Прод безопасность API** | В **`.env` нет** **`MINIAPP_CORS_ORIGINS`**, **`API_EXPOSE_DOCS`**, **`MINIAPP_EXPOSE_DEBUG`** — **`api_miniapp`** берёт дефолты (**CORS `*`**, доки выкл. по коду — проверить актуальные дефолты в файле при хардненинге). |
| **Telegram HTTP** | **`TG_HTTP_TIMEOUT` / `TG_HTTP_POOL_SIZE`** в **`.env` нет** — используются дефолты **`bot/main.py`** (**60 с**, пул **16**). |
| **Мелочь** | В **`.env`** строка комментария **«Язык и режиму»** — опечатка (**режим**). |

### Что НЕ найдено статически
Массовых **`except: pass`** в **`bot/`** не видно. Конкретные **рантайм-ошибки** с VPS/Telegram/Happ без **логов** и **текста исключений** по репозиторию не восстановить — нужны **`journalctl`**, **`Traceback`**, сценарий (команда/кнопка).

### Рекомендованный порядок работ (на 6 часов)
1. **Ротация секретов** после утечки в чат.  
2. **Починить или пометить устаревшими** **`test_bot.py`** (изоляция от `.env`, актуальные цены, полный набор kwargs для **`plan_template`**).  
3. Собрать от пользователя **список реальных ошибок** (лог/скрин) и закрывать по одной.  
4. Опционально: выровнять **`.env.example`** (**`MINIAPP_BYPASS_USER_IDS`**, **`HAPP_ENCRYPT_SUBSCRIPTION_LINKS`**, прод **`MINIAPP_CORS_ORIGINS`**).

---

## 2026-03-28 — план работ по 8 пунктам + как слать логи

Добавлен файл **`docs/other/РАЗБОР_ОШИБОК_И_ПЛАН_ИСПРАВЛЕНИЙ.md`**: инструкция по **`journalctl`**, nginx, DevTools; разбор пунктов **/start**, разные ноды ПК/телефон, нестабильный мини-апп, сайт без VPN, цвет iOS, Happ↔мини-апп, скролл ПК, модалка «Мой конфиг»; таблица этапов **A–E**. В **`docs/README.md`** — строка в оглавлении **other/**.

---

## 2026-03-29 — miniapp-api логи: сканеры, Happ add-install, `os`, ЮKassa

### Лог пользователя
- Массовые **GET** `/.env*`, `/public/.env*`, **WordPress** — ботнет/сканеры (**179.43.x**, Cloudflare **104.23.x**), ответы **404** — не баг приложения.
- **Happ 404** на **`https://happ-proxy.com/api/add-install`** — неверная база для **add-install** (нужен **`api.happ-proxy.com`**).
- **`HAPP_ENCRYPT_SUBSCRIPTION_LINKS: local variable 'os' referenced before assignment`** — в **`miniapp_me`** внутри **`except`** был **`import os`**, из‑за чего **`os`** стал локальной переменной всей функции.
- **ЮKassa Read timed out (15 s)** — мало для медленного канала.

### Что сделано
- **`bot/utils/happ_client.py`**: **`resolve_happ_base_add_install()`**, **`_normalize_api_url_for_add_install()`**, **`_origin_for_happ_add_install()`** (**urlparse** по **hostname**): **`happ-proxy.com`** / **`www.happ-proxy.com`** (в т.ч. с путём в URL) для **add-install** → **`https://api.happ-proxy.com`**; **`create_happ_install_link`** нормализует URL.
- **`api_miniapp.py`**, **`bot/handlers/main.py`**: вызовы **add-install** через **`resolve_happ_base_add_install()`**; убран вложенный **`import os`** в **`miniapp_me`**.
- **`bot/utils/payments.py`**: таймауты **POST/GET** к API ЮKassa **15 → 30** с.

### Проверить
**`git pull`**, **`restart vpn-bot`** и **`miniapp-api`**; в `.env` на сервере лучше явно **`HAPP_API_URL=https://api.happ-proxy.com`** (не корень **happ-proxy.com**).

### Доп. 2026-03-29
- **`happ_client.create_happ_install_link`**: при **404** на **`happ-proxy.com` / `www`** — автоматический **повтор** запроса на **`https://api.happ-proxy.com/api/add-install`** (если на VPS ещё старая нормализация origin, но файл уже обновили). Host в **`_origin_for_happ_add_install`**: **`.rstrip('.')`**.
- **`api_miniapp.py`**: **`_os_getenv` / `_os_environ_get`** в **`miniapp_me`** вместо **`os.getenv` / `os.environ.get`** — убирает **`UnboundLocalError: os`** при вложенном **`import os`** в старых ветках.

