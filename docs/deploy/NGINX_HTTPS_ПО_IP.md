# Вариант 2: чтобы ссылка https://155.212.164.135/sub/КОД работала

Чтобы по **IP** открывалась ссылка из бота (https://155.212.164.135/sub/...) и не было 404, нужен отдельный блок **server** в nginx для этого IP с `location /sub/` и `location /api/`. Для HTTPS по IP используют **самоподписанный сертификат** — браузер покажет «Не защищено», но ссылка будет открываться; приложение Happ обычно не проверяет сертификат и подписка подтягивается.

---

## Шаг 1. Создать папку и сертификат (один раз)

На сервере выполните:

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/155.212.164.135.key \
  -out /etc/nginx/ssl/155.212.164.135.crt \
  -subj "/CN=155.212.164.135" -addext "subjectAltName=IP:155.212.164.135"
```

Проверьте, что файлы появились:

```bash
ls -la /etc/nginx/ssl/
```

---

## Шаг 2. Добавить server-блок для IP в nginx

Откройте конфиг:

```bash
sudo nano /etc/nginx/sites-available/default
```

В **конец файла** (после всех закрывающих `}`) вставьте следующий блок целиком:

```nginx
server {
    listen 443 ssl;
    server_name 155.212.164.135;

    ssl_certificate     /etc/nginx/ssl/155.212.164.135.crt;
    ssl_certificate_key /etc/nginx/ssl/155.212.164.135.key;

    location /sub/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }

    location / {
        return 404;
    }
}
```

Сохраните: **Ctrl+O**, Enter, **Ctrl+X**.

---

## Шаг 3. Проверить конфиг и перезагрузить nginx

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Шаг 4. Проверка

На сервере или с ПК:

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -k "https://155.212.164.135/sub/yHmESPsZKd76"
```

Должно быть **HTTP 200**. В браузере по адресу https://155.212.164.135/sub/КОД откроется контент подписки; предупреждение «Не защищено» из‑за самоподписанного сертификата — нормально. В Happ ссылка из бота должна подтягиваться без ошибки.

---

## Если не хотите «Не защищено» по IP

Тогда удобнее **вариант 1**: в `.env` задать `HAPP_SUBSCRIPTION_REDIRECT_BASE=https://nikolay.lisobyk.fvds.ru` и выдавать ссылки с доменом; для домена у вас уже есть нормальный сертификат Let's Encrypt.
