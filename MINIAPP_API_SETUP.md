# Mini App API — что это и что нужно подготовить

## Главное: отдельный API готовить не нужно

**API уже есть в проекте** — это файл **`api_miniapp.py`**. В нём два эндпоинта:

| Метод | URL | Назначение |
|-------|-----|------------|
| **GET** | `/api/miniapp/plans` | Тарифы и цены (единый источник для Mini App) |
| **POST** | `/api/miniapp/me` | Данные пользователя: подписка, список подписок, история платежей. Тело: `{"initData": "..."}` — строка `initData` из Telegram Web App. |

Mini App (на Vercel) при открытии с параметром `?api=<URL вашего API>` сама дергает эти два запроса и подставляет реальные данные вместо заглушек.

---

## Что от вас требуется

### 1. Запустить API по публичному HTTPS-адресу

Telegram Mini App открывается по HTTPS и запросы из него тоже идут по HTTPS. Поэтому API должен быть доступен по **HTTPS**, а не только по `http://localhost:8765`.

**Варианты:**

#### Вариант А: тот же VDS, что и боты (155.212.164.135)

- Поднять `api_miniapp` на сервере (например, как systemd-сервис на порту 8765).
- Поставить перед ним **nginx** с SSL (сертификат через Let's Encrypt / certbot) и отдавать API по `https://api.nikolay.lisobyk.fvds.ru` (или отдельный поддомен).
- В **.env** на сервере указать:  
  `MINIAPP_API_URL=https://api.nikolay.lisobyk.fvds.ru`  
  (без слэша в конце.)
- В **.env** же заполнить `BOT_USERNAME=` (username вашего VPN-бота без @), чтобы кнопка «Оплатить» в Mini App открывала бота.

Тогда при открытии приложения бот подставит в ссылку Mini App параметр `api=https://api.nikolay.lisobyk.fvds.ru`, и приложение начнёт тянуть планы и данные пользователя с вашего API.

#### Вариант Б: отдельный хостинг с HTTPS

- Развернуть `api_miniapp.py` на любом сервере/хостинге с HTTPS (Railway, Render, свой VPS с nginx и т.д.).
- Указать этот HTTPS-URL в **MINIAPP_API_URL** в .env (и по желанию в переменных окружения на сервере бота).

#### Вариант В: временно для теста — ngrok

- На ПК: `ЗАПУСТИТЬ_МИНИАПП_API.bat` (слушает порт 8765).
- В другом терминале: `ngrok http 8765` → получите `https://xxxx.ngrok.io`.
- В .env: `MINIAPP_API_URL=https://xxxx.ngrok.io` (без слэша).
- Перезапустить бота. Пока ngrok и API на ПК запущены, Mini App будет ходить в этот API. Для продакшена лучше Вариант А или Б.

---

### 2. Что прописать в .env

Обязательно для работы Mini App с API:

```env
# Уже есть — ссылка на Mini App (Vercel)
WEBAPP_URL=https://bitvpn.vercel.app

# Сюда — публичный HTTPS-адрес вашего API (без слэша в конце)
MINIAPP_API_URL=https://ваш-домен-или-ngrok.io

# Username VPN-бота без @ — чтобы кнопка «Оплатить» открывала бота
BOT_USERNAME=Bitvpnproxy_bot
```

После смены .env перезапустите VPN-бота (на сервере: `systemctl restart vpn-bot` или через ваш `restart-bots.bat`).

---

### 3. Итог: что вы «подготавливаете»

- **Не** отдельный новый API — используется только **api_miniapp.py** из этого репозитория.
- Нужно: **запустить этот API по HTTPS** (VDS + nginx, или другой хостинг, или ngrok для теста) и **прописать этот URL в MINIAPP_API_URL** (и при желании BOT_USERNAME) в .env.

После этого Mini App «доведена до ума» в части: тарифы и цены из API, реальные подписки и платежи в приложении, кнопка «Оплатить» ведёт в бота.

---

## Запуск API на том же VDS (порт 8765)

На сервере после деплоя проекта:

```bash
cp /opt/vpn-bot/deploy/miniapp-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable miniapp-api
systemctl start miniapp-api
```

API будет слушать порт **8765**. Чтобы к нему ходить по **HTTPS**, нужен nginx с SSL перед ним. Пример конфига nginx (подставьте свой домен, например `api.nikolay.lisobyk.fvds.ru`):

```nginx
server {
    listen 443 ssl;
    server_name api.nikolay.lisobyk.fvds.ru;
    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key  /path/to/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Сертификаты можно получить через **certbot** (Let's Encrypt). После настройки nginx в .env укажите:

`MINIAPP_API_URL=https://api.nikolay.lisobyk.fvds.ru`
