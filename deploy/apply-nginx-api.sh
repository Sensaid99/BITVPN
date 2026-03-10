#!/bin/bash
# Скрипт для сервера: добавляет location /api/ в nginx и перезагружает.
# Запуск на сервере: sudo bash apply-nginx-api.sh
# (предварительно скопируйте файл на сервер в /opt/vpn-bot/deploy/)

set -e
CONF="/etc/nginx/sites-available/default"
BACKUP="${CONF}.bak.$(date +%Y%m%d%H%M%S)"
LOCATION_BLOCK='
        location /api/ {
            proxy_pass http://127.0.0.1:8765;
            proxy_http_version 1.1;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
'

if ! [ -f "$CONF" ]; then
    echo "Файл $CONF не найден."
    exit 1
fi

if grep -q "location /api/" "$CONF"; then
    echo "Блок location /api/ уже есть в конфиге. Ничего не делаю."
    sudo nginx -t && sudo systemctl reload nginx
    exit 0
fi

echo "Создаю резервную копию: $BACKUP"
sudo cp "$CONF" "$BACKUP"

echo "Добавляю location /api/ в первый блок server..."
sudo python3 << 'PYTHON'
import sys
conf = "/etc/nginx/sites-available/default"
with open(conf, "r") as f:
    content = f.read()

if "location /api/" in content:
    print("Уже есть location /api/. Выход.")
    sys.exit(0)

marker = "listen [::]:80 default_server;"
if marker not in content:
    marker = "listen 80 default_server;"

insert = """
        location /api/ {
            proxy_pass http://127.0.0.1:8765;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }"""

if marker in content:
    new_content = content.replace(marker, marker + insert, 1)
    with open(conf, "w") as f:
        f.write(new_content)
    print("Блок добавлен.")
else:
    print("Маркер listen 80 не найден. Добавьте location /api/ вручную.")
    sys.exit(1)
PYTHON

echo "Проверка nginx..."
sudo nginx -t
echo "Перезагрузка nginx..."
sudo systemctl reload nginx
echo "Готово. /api/ теперь проксируется на порт 8765."
