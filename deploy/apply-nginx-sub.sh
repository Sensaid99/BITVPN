#!/bin/bash
# Добавляет location /sub/ в nginx (редирект для Happ) и перезагружает nginx.
# Запуск на сервере: sudo bash /opt/vpn-bot/deploy/apply-nginx-sub.sh
# Или при деплое вызывается автоматически из ДЕПЛОЙ_НА_СЕРВЕР.bat.

set -e
SITES="/etc/nginx/sites-available"
CONF=""
for f in "$SITES"/default "$SITES"/vpn-api "$SITES"/*; do
    [ -f "$f" ] && grep -q "location /api/" "$f" 2>/dev/null && CONF="$f" && break
done
if [ -z "$CONF" ]; then
    echo "Не найден конфиг nginx с location /api/. Добавьте /sub/ вручную."
    exit 1
fi
if grep -q "location /sub/" "$CONF"; then
    echo "location /sub/ уже есть в $CONF."
    sudo nginx -t && sudo systemctl reload nginx
    exit 0
fi
echo "Добавляю location /sub/ в $CONF"
sudo python3 - "$CONF" << 'PYTHON'
import sys
if len(sys.argv) < 2:
    print("Укажите путь к конфигу nginx.")
    sys.exit(1)
conf = sys.argv[1]
with open(conf, "r") as f:
    content = f.read()
if "location /sub/" in content:
    print("Уже есть location /sub/. Выход.")
    sys.exit(0)
insert = '''    location /sub/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }
'''
# Вставить перед первым "location /api/"
if "location /api/" not in content:
    print("В конфиге нет location /api/. Выход.")
    sys.exit(1)
new_content = content.replace("location /api/", insert + "    location /api/", 1)
with open(conf, "w") as f:
    f.write(new_content)
print("Блок location /sub/ добавлен.")
PYTHON
echo "Проверка nginx..."
sudo nginx -t
echo "Перезагрузка nginx..."
sudo systemctl reload nginx
echo "Готово. /sub/ проксируется на порт 8765."
