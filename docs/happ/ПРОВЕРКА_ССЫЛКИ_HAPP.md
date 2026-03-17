# Проверка: почему нет ссылки Happ в мини-аппе

Ссылку в приложении отдаёт **API на сервере** (у вас: `https://nikolay.lisobyk.fvds.ru`). Данные берутся из **сервера**, а не из локального `.env` на ПК.

**Важно:** мини-апп открывается с Vercel (bitvpn.vercel.app), но запросы к данным идут на **ваш сервер** — адрес берётся из параметра `?api=...` в ссылке. Деплой на Vercel обновляет только интерфейс; логика ссылок и счётчика устройств работает в **API на вашем сервере**. Поэтому после правок нужно обязательно обновить код на сервере (`git pull`) и перезапустить `miniapp-api`.

---

## Ошибка в Happ: «Error transferring https://IP/sub/КОД - server replied: Not Found»

Если в приложении Happ при обновлении подписки появляется **Not Found** по ссылке вида `https://155.212.164.135/sub/XXXXXXXXXXXX`, значит запрос **не доходит до API** — его перехватывает **nginx** и отдаёт 404, потому что у него нет правила для пути `/sub/`.

**Что сделать на сервере (155.212.164.135):**

1. **Диагностика** — выполните на сервере (подставьте свой код из ссылки):
   ```bash
   cd /opt/vpn-bot
   bash deploy/check-sub-url.sh yHmESPsZKd76
   ```
   Смотрите: если шаг 1 (API напрямую) даёт 200 или 302 — API работает; если 404 — проверьте в `.env` на сервере: `HAPP_SUBSCRIPTION_URL` должен быть **https://...** (не `happ://`). Если шаг 2 (через nginx) даёт 404 — в nginx нет или не в том блоке `location /sub/`.

2. **Добавить `location /sub/` в nginx.** В конфиге `default` часто **два** блока `server` (порт 80 и 443). Ссылка из Happ идёт по **https** (порт 443), поэтому `location /sub/` должен быть **в том же блоке server, где есть `location /api/` для 443**. Запустите (обновлённый скрипт добавит `/sub/` перед каждым `location /api/`):
   ```bash
   cd /opt/vpn-bot
   sudo bash deploy/apply-nginx-sub.sh
   ```
   Если скрипт уже запускали раньше и пишет «location /sub/ уже есть» — откройте конфиг и проверьте, что `location /sub/` есть **внутри блока server с listen 443** (или в default_server для HTTPS):
   ```bash
   sudo grep -n "listen\|location /sub/\|location /api/" /etc/nginx/sites-available/default
   ```
   При необходимости добавьте блок `location /sub/ { ... }` вручную **перед** каждым `location /api/` (и в блоке 80, и в блоке 443), как в `deploy/nginx-miniapp-api.conf`. Затем:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

3. **Проверка:** откройте в браузере `https://155.212.164.135/sub/yHmESPsZKd76` (код из бота) — не должно быть «Not Found». Убедитесь, что API запущен: `sudo systemctl status miniapp-api`, при необходимости `sudo systemctl restart miniapp-api`.

После этого ссылка из бота должна открываться в Happ без ошибки.

---

## Если после деплоя ссылка всё равно старая (95.181.175.67...?installid=...)

1. **Проверьте, что API на сервере обновлён и видит правильный redirect_base.**  
   Откройте в браузере (подставьте свой домен API):  
   **https://николай.lisobyk.fvds.ru/api/miniapp/debug-link-format**

   В ответе смотрите:
   - `rewrite_version`: должно быть `"redirect_v2"` (значит на сервере новый код).
   - `redirect_base`: должен быть ваш домен, например `https://николай.lisobyk.fvds.ru`. Если там пусто или `http://127.0.0.1:8765` — API не знает, куда подставлять ссылку.

2. **Если redirect_base пустой или внутренний** — на сервере в `.env` добавьте и перезапустите API:
   ```env
   HAPP_SUBSCRIPTION_REDIRECT_BASE=https://николай.lisobyk.fvds.ru
   ```
   Затем: `sudo systemctl restart miniapp-api`.

3. **Перезагрузите nginx** (чтобы передавались заголовки X-Forwarded-Host / X-Forwarded-Proto):
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
   В конфиге для `location /api/` должны быть строки:  
   `proxy_set_header X-Forwarded-Proto $scheme;` и `proxy_set_header X-Forwarded-Host $host;`

4. **Убедитесь, что деплой на сервер действительно обновил код.** По SSH:
   ```bash
   cd /opt/vpn-bot   # или ваш BOT_PATH
   git pull --ff-only
   sudo systemctl restart miniapp-api
   sudo systemctl restart vpn-bot
   ```

---

## Лимит устройств по одной ссылке (автоматически)

Когда **Happ API доступен** с сервера, лимит уже работает автоматически:

- Тариф «1 устройство» → ссылка с лимитом **1** (Happ не даст подключить второе).
- Тариф «3 устройства» → ссылка с лимитом **3** и т.д.

В API передаётся `install_limit` по полю `plan_type` подписки (например `6_months_3` → 3 устройства). Happ возвращает ссылку с уникальным `installid`, их сервер считает подключённые устройства и блокирует лишние. Дополнительно настраивать ничего не нужно.

Если с сервера приходит **404** от Happ API, мы отдаём базовый URL подписки (fallback) — у этой ссылки лимита по устройствам нет (это ограничивает только Happ при работе их API). Чтобы снова был лимит по ссылке, нужно восстановить доступ к Happ API (актуальный URL, при необходимости белый список IP).

---

## 0. Быстрая проверка: видит ли API переменные Happ

Откройте в браузере (с ПК или телефона):

**https://nikolay.lisobyk.fvds.ru/api/miniapp/check-happ-env**

Ожидаемый ответ при правильной настройке:

```json
{
  "ok": true,
  "message": "Все HAPP_* заданы. Ссылка должна генерироваться.",
  "env_set": {
    "HAPP_API_URL": true,
    "HAPP_PROVIDER_CODE": true,
    "HAPP_AUTH_KEY": true,
    "HAPP_SUBSCRIPTION_URL": true
  }
}
```

Если **`"ok": false`** или какое-то из `env_set` равно **false** — переменные на **сервере** не заданы или API не перезапускали после правок `.env`. Добавьте в `.env` на сервере (п. 1) и выполните `sudo systemctl restart miniapp-api`.

---

## 1. Переменные на сервере (обязательно)

На **сервере**, где крутится API (uvicorn / api_miniapp), должен быть файл `.env` **в папке проекта** (например `/opt/vpn-bot/.env`) с теми же переменными, что и у вас локально.

Если в `deploy_config.cmd` задано `COPY_ENV_TO_SERVER=1`, скрипт `ДЕПЛОЙ_НА_СЕРВЕР.bat` копирует ваш локальный `.env` на сервер при каждом деплое. Иначе переменные **HAPP_*** нужно прописать на сервере вручную.

Проверьте на сервере:

```bash
ssh root@nikolay.lisobyk.fvds.ru
cd /opt/vpn-bot   # или ваш BOT_PATH из deploy_config.cmd
grep -E "HAPP_|MINIAPP" .env
```

Должны быть (значения подставьте свои):

```env
MINIAPP_API_URL=https://nikolay.lisobyk.fvds.ru
HAPP_API_URL=https://happ-proxy.com
HAPP_PROVIDER_CODE=ZzQ4DIUe
HAPP_AUTH_KEY=h6LDyDkZr_ne01k_LK371xIB9FPzkfCl
HAPP_SUBSCRIPTION_URL=https://95.181.175.67:2096/sub_bitvpn/bgmdn1s016p08yfb
```

- **HAPP_SUBSCRIPTION_URL** — базовая ссылка подписки **без** `?installid=...` (бот сам добавит параметр). Обычно это ссылка из 3x-ui или панели, которую вы раздаёте пользователям.
- Если какой-то из `HAPP_*` отсутствует или пустой — ссылка в API не сгенерируется.

После правок `.env` на сервере **перезапустите API**:

```bash
sudo systemctl restart miniapp-api
```

(в проекте используется **miniapp-api**; если на сервере назвали иначе — подставьте своё имя).

---

## 2. Локальный .env (у вас уже есть)

На ПК в `d:\VPN BOT\.env` у вас указано:

- `HAPP_API_URL=https://happ-proxy.com` — **обязательно** (на happ-proxy.com без api. — 404).
- `HAPP_PROVIDER_CODE=ZzQ4DIUe` — верно.
- `HAPP_AUTH_KEY=...` — верно.
- `HAPP_SUBSCRIPTION_URL=https://95.181.175.67:2096/sub_bitvpn/bgmdn1s016p08yfb` — базовая ссылка без `installid`, формат верный.

Эти же значения должны быть **на сервере** (п. 1).

---

## 3. Куда смотреть логи API

После того как откроете мини-апп из бота и зайдёте в «Устройства», API при запросе `/api/miniapp/me` попытается выдать или сгенерировать ссылку. В логах API на сервере может появиться:

- `Happ fallback skipped — HAPP_PROVIDER_CODE, HAPP_AUTH_KEY or HAPP_SUBSCRIPTION_URL missing` — на сервере в окружении API нет одной из переменных.
- `Happ API returned no link` — запрос к Happ выполнился, но ссылку не вернули (проверить ключи и URL подписки в кабинете Happ и в `.env`).
- `Happ link generated and saved for user ...` — ссылка создана и сохранена.

Как смотреть логи (пример для systemd):

```bash
ssh root@nikolay.lisobyk.fvds.ru
journalctl -u miniapp-api -n 100 --no-pager
```

или если API запускаете вручную — смотреть вывод в консоли.

---

## 4. Краткий чек-лист

| Где | Что проверить |
|-----|----------------|
| Сервер, папка бота | В `.env` есть `HAPP_PROVIDER_CODE`, `HAPP_AUTH_KEY`, `HAPP_SUBSCRIPTION_URL` (и при необходимости `HAPP_API_URL`) |
| Сервер | После правок `.env` перезапущен процесс API (`systemctl restart miniapp-api`) |
| Кабинет Happ | `provider_code` и `auth_key` совпадают с теми, что в `.env` |
| HAPP_SUBSCRIPTION_URL | Базовая ссылка подписки без `?installid=...`; доступна с сервера (curl с сервера к этому URL) |
| Мини-апп | Открыт **из меню бота** (чтобы ушёл запрос к вашему API с initData) |

Если всё выставлено, но ссылки по-прежнему нет — пришлите последние 30–50 строк логов API с сервера после открытия приложения и перехода в «Устройства».

---

## 5. Ошибка 404 при запросе к Happ API

Если в логах видно **404** и в ответе **HTML** с `nginx/1.24.0 (Ubuntu)` или другим веб-сервером — до API Happ запрос **не доходит**. То есть по адресу `HAPP_API_URL` отвечает не сервис Happ, а другой сервер (или другой виртуальный хост).

**Что сделать:**

1. **Проверить с заголовком `Accept: application/json`** (в документации Happ он обязателен в примерах). С сервера или ПК:
   ```bash
   curl -s -H "Accept: application/json" "https://happ-proxy.com/api/add-install?provider_code=ВАШ_8_СИМВОЛОВ&auth_key=ВАШ_32_СИМВОЛА&install_limit=1"
   ```
   Бот при запросах к Happ уже отправляет этот заголовок. Если с заголовком приходит JSON — значит, без заголовка сервер отдаёт 404.

2. **Проверить в браузере** (подставьте свои `provider_code` и `auth_key`):
   ```
   https://happ-proxy.com/api/add-install?provider_code=ВАШ_8_СИМВОЛОВ&auth_key=ВАШ_32_СИМВОЛА&install_limit=1
   ```
   - Если в браузере приходит **JSON** (`{"rc":1,...}` или `{"rc":0,...}`) — API по этому URL работает с вашего ПК. Тогда с сервера запрос может блокироваться (другой IP, гео, файрвол) или DNS на сервере отдаёт другой IP.
   - Если в браузере тоже **404 или HTML** — попробуйте запрос выше с `curl` и заголовком. Если и так 404 — уточните у поддержки Happ **точный базовый URL API** (возможно, другой путь или поддомен).

3. **Уточнить у поддержки Happ** (например, в Telegram или на сайте):
   - Какой **текущий базовый URL API** для эндпоинта создания лимитированных ссылок (`/api/add-install`)?
   - Есть ли ограничения по IP (нужна ли белая список для IP сервера)?

4. **Проверить DNS с сервера:**
   ```bash
   dig happ-proxy.com +short
   # или
   getent hosts happ-proxy.com
   ```
   Убедиться, что разрешается ожидаемый IP, а не внутренний или подменённый.

5. После смены **HAPP_API_URL** в `.env` на сервере обязательно перезапустить API:
   ```bash
   sudo systemctl restart miniapp-api
   ```

---

## 6. Счётчик «Подключено» не показывается (0 устройств)

Счётчик берётся из Happ API `list-install`. Если показывается 0 или «Нет устройств» при том что ссылку вы уже добавили в Happ (Подписки → +) и прошло больше 2 минут:

**Важно:** в Happ нужно добавлять **именно ссылку из приложения** (кнопка «Скопировать ссылку» в мини-аппе) — вида `https://ваш-домен-api/sub/XXXXXXXXXXXX`. Если добавить прямую ссылку на сервер подписки (например `https://95.181.175.67:2096/...`), счётчик не будет работать, т.к. у неё другой код.

1. **Проверка через отладочный эндпоинт**  
   Возьмите из своей ссылки подписки код из 12 символов (после `/sub/` в ссылке вида `https://.../sub/XXXXXXXXXXXX`). Откройте в браузере (подставьте свой домен API и код):
   ```text
   https://ваш-домен-api/api/miniapp/debug-install-stats?install_code=XXXXXXXXXXXX
   ```
   В ответе смотрите:
   - **found: true** — ваш код есть в Happ; тогда **install_count** может быть 0, пока вы только добавили подписку (Happ иногда обновляет счётчик при первом подключении VPN). Если **found: false** — код не найден в списке Happ; убедитесь, что добавили в Happ **ту же** ссылку, что выдал бот (кнопка «Скопировать ссылку» в мини-аппе).
   - **list_total** — сколько всего записей вернул Happ; если 0, проверьте HAPP_PROVIDER_CODE и HAPP_AUTH_KEY на сервере.
   - **raw_keys** / **first_item_keys** — какие поля вернул Happ (для отладки).
   - **hint** — подсказка, что не так.

2. **URL для list-install:** счётчик запрашивает `list-install` по тому же базовому URL. Если у вас `HAPP_API_URL=https://api.happ-proxy.com` (для выдачи ссылок), то **list-install** там может отдавать 404. Задайте отдельно:
   ```bash
   HAPP_LIST_INSTALL_URL=https://happ-proxy.com
   ```
   Тогда для счётчика будет использоваться этот URL. Либо поставьте единый `HAPP_API_URL=https://happ-proxy.com`, если и выдача ссылок, и list-install у вас работают с ним.

3. **Перезапустите API** после смены:  
   `sudo systemctl restart miniapp-api`

4. **Откройте мини-апп → «Устройства»** и на сервере посмотрите логи:
   ```bash
   journalctl -u miniapp-api -n 50 --no-pager
   ```
   Ищите строку `miniapp_me: get_install_stats api=... install_code=...*** -> used=... limit=...`  
   - Если видите `used=0 limit=3` — Happ вернул 0 устройств (добавьте ссылку в приложение Happ на телефоне и подождите 1–2 мин).  
   - Если видите `not_found or error` — ваш `install_code` не найден в ответе Happ или запрос к API упал; проверьте, что `HAPP_API_URL` именно `https://happ-proxy.com`.

5. **Проверить вручную с сервера** (подставьте свой `auth_key` и при необходимости `provider_code`):
   ```bash
   curl -s -H "Accept: application/json" "https://happ-proxy.com/api/list-install?provider_code=ZzQ4DIUe&auth_key=ВАШ_КЛЮЧ" | head -500
   ```
   В ответе найдите объект с вашим `install_code` (из ссылки после `installid=`). Посмотрите поля `install_count` и `install_limit`. Если вашей записи нет — вопрос к поддержке Happ.
