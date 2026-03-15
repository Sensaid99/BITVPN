#!/bin/bash
# Добавляет location /sub/ в nginx (редирект для Happ) и перезагружает nginx.
# Запуск на сервере: sudo bash /opt/vpn-bot/deploy/apply-nginx-sub.sh
# Или при деплое вызывается автоматически из ДЕПЛОЙ_НА_СЕРВЕР.bat.

set -e
SITES_AVAILABLE="/etc/nginx/sites-available"
SITES_ENABLED="/etc/nginx/sites-enabled"
CONF=""
# Ищем любой конфиг, где уже есть location /api/ (сначала типичные имена, потом все)
for f in "$SITES_AVAILABLE"/default "$SITES_AVAILABLE"/vpn-api "$SITES_AVAILABLE"/vpn-bot; do
    [ -f "$f" ] && grep -q "location /api/" "$f" 2>/dev/null && CONF="$f" && break
done
[ -z "$CONF" ] && for f in "$SITES_AVAILABLE"/*; do
    [ -f "$f" ] && grep -q "location /api/" "$f" 2>/dev/null && CONF="$f" && break
done
[ -z "$CONF" ] && [ -d "$SITES_ENABLED" ] && for f in "$SITES_ENABLED"/*; do
    [ -f "$f" ] && grep -q "location /api/" "$f" 2>/dev/null && CONF="$f" && break
done
if [ -z "$CONF" ]; then
    echo "Не найден конфиг nginx с location /api/. Добавьте /sub/ вручную."
    echo "Проверьте: grep -l 'location /api/' $SITES_AVAILABLE/* $SITES_ENABLED/* 2>/dev/null"
    exit 1
fi
echo "Используется конфиг: $CONF"
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
# Вставить перед КАЖДЫМ "location /api/" (в default часто два server — 80 и 443; оба должны иметь /sub/)
if "location /api/" not in content:
    print("В конфиге нет location /api/. Выход.")
    sys.exit(1)
new_content = content.replace("    location /api/", insert + "    location /api/")
with open(conf, "w") as f:
    f.write(new_content)
print("Блок location /sub/ добавлен перед каждым location /api/.")
PYTHON
echo "Проверка nginx..."
sudo nginx -t
echo "Перезагрузка nginx..."
sudo systemctl reload nginx
echo "Готово. /sub/ проксируется на порт 8765."
