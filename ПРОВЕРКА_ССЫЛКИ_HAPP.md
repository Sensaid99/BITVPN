# Проверка: почему нет ссылки Happ в мини-аппе

Ссылку в приложении отдаёт **API на сервере** (у вас: `https://nikolay.lisobyk.fvds.ru`). Данные берутся из **сервера**, а не из локального `.env` на ПК.

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

Скрипт `ДЕПЛОЙ_НА_СЕРВЕР.bat` **не копирует** `.env` на сервер (чтобы не затереть настройки). Поэтому **HAPP_*** нужно прописать на сервере вручную.

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

- `HAPP_API_URL=https://happ-proxy.com` — верно.
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
