# Сервер bitecosystem.ru + Vercel — с нуля

Актуальные значения продакшена в этом репозитории:

| Параметр | Значение |
|----------|----------|
| **Домен API (бот + miniapp-api)** | `bitecosystem.ru` |
| **IP VPS (бот + API)** | `213.165.38.222` |
| **Мини-апп (интерфейс)** | `https://bitvpn.vercel.app` (или ваш URL на Vercel) |

**Важно:** сервер **подписки VPN** (3x-ui и т.п.) часто на **другом** IP — его вписывают в `HAPP_SUBSCRIPTION_URL`, это **не** обязательно `213.165.38.222`.

---

## 1. DNS

У регистратора домена:

- **A** `@` → `213.165.38.222`
- **A** `www` → `213.165.38.222`

Проверка: `nslookup bitecosystem.ru 8.8.8.8` → должен быть `213.165.38.222`.

---

## 2. Сервер (Ubuntu)

```bash
ssh root@213.165.38.222
apt update && apt install -y git python3 python3-pip python3-venv nginx certbot python3-certbot-nginx
cd /opt && git clone https://github.com/Sensaid99/BITVPN.git vpn-bot
cd /opt/vpn-bot && git checkout main
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

Скопируйте `.env` с ПК на сервер: `/opt/vpn-bot/.env`.

### Обязательные строки в `/opt/vpn-bot/.env`

```env
MINIAPP_API_URL=https://bitecosystem.ru
HAPP_SUBSCRIPTION_REDIRECT_BASE=https://bitecosystem.ru
WEBAPP_URL=https://bitvpn.vercel.app?api=https://bitecosystem.ru

HAPP_API_URL=https://api.happ-proxy.com
HAPP_LIST_INSTALL_URL=https://happ-proxy.com
```

Остальное — `BOT_TOKEN`, `DATABASE_URL`, `HAPP_*`, тарифы, ЮKassa — по вашему кабинету.

```bash
chmod 600 /opt/vpn-bot/.env
cp deploy/vpn-bot.service deploy/miniapp-api.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vpn-bot miniapp-api
```

Проверка: `curl -sS http://127.0.0.1:8765/api/miniapp/plans | head`

---

## 3. Nginx + HTTPS

Файл ` /etc/nginx/sites-available/bitecosystem.ru`:

- Порт **80**: `server_name bitecosystem.ru www.bitecosystem.ru;` → затем `certbot --nginx -d bitecosystem.ru -d www.bitecosystem.ru`
- Порт **443**: внутри блока `location /api/` и `location /sub/` → `proxy_pass http://127.0.0.1:8765;`

Примеры блоков: `deploy/nginx-miniapp-api.conf`, полный пример — `deploy/nginx-default-full.conf`.

```bash
nginx -t && systemctl reload nginx
curl -sS "https://bitecosystem.ru/api/miniapp/plans" | head
```

HTTPS по IP (если нужен запасной вход): `docs/deploy/NGINX_HTTPS_ПО_IP.md` (IP `213.165.38.222` в примерах).

---

## 4. Vercel

1. Проект с **Root Directory** = `webapp`.
2. **Settings → Environment Variables** — те же по смыслу, что в `.env`: `BOT_TOKEN`, `DATABASE_URL`, `PLAN_*`, `SUPPORT_USERNAME`, рефералка и т.д. (см. `docs/miniapp/СИНХРОНИЗАЦИЯ_БОТ_МИНИАПП.md`).
3. После изменений — **Redeploy**.

Мини-апп берёт адрес API из **`?api=https://bitecosystem.ru`** в `WEBAPP_URL` (открытие из Telegram).

---

## 5. Telegram и ЮKassa

- **BotFather** → Web App URL =  
  `https://bitvpn.vercel.app?api=https://bitecosystem.ru`  
  (подставьте свой домен Vercel, если другой).
- **ЮKassa** → webhook:  
  `https://bitecosystem.ru/api/webhook/yookassa`

---

## 6. Проверка

| Проверка | Команда / действие |
|----------|-------------------|
| API локально | `curl -sS http://127.0.0.1:8765/api/miniapp/plans` |
| API снаружи | `curl -sS https://bitecosystem.ru/api/miniapp/plans` |
| Бот | Ответ в Telegram |
| Мини-апп | Профиль и тарифы открываются |

---

## См. также

- `НАСТРОЙКА_С_НУЛЯ.md` — полная общая инструкция (те же имена в примерах).
- `СМЕНА_СЕРВЕРА_БОТ_И_MINIAPP.md` — перенос на новый VPS.
- `MINI_APP_VERCEL.md` — деплой папки `webapp`.
