#!/bin/bash
# Копирует nginx-default-full.conf в /etc/nginx/sites-available/default и перезагружает nginx.
# Запуск на сервере после деплоя: sudo bash /opt/vpn-bot/deploy/apply-nginx-default.sh
# Перед первым запуском создайте сертификат для IP (см. комментарии в nginx-default-full.conf).

set -e
BOT_PATH="${BOT_PATH:-/opt/vpn-bot}"
CONF_SOURCE="$BOT_PATH/deploy/nginx-default-full.conf"
CONF_DEST="/etc/nginx/sites-available/default"

if [ ! -f "$CONF_SOURCE" ]; then
    echo "Файл не найден: $CONF_SOURCE. Сначала выполните деплой (git pull)."
    exit 1
fi

echo "Бэкап текущего конфига: $CONF_DEST -> ${CONF_DEST}.bak"
sudo cp "$CONF_DEST" "${CONF_DEST}.bak" 2>/dev/null || true

echo "Копирование $CONF_SOURCE -> $CONF_DEST"
sudo cp "$CONF_SOURCE" "$CONF_DEST"

echo "Проверка nginx..."
if ! sudo nginx -t 2>/dev/null; then
    echo "Ошибка nginx -t. Возможно, нет файлов Let's Encrypt для домена."
    echo "Проверьте: ls /etc/letsencrypt/live/bitecosystem.ru/"
    echo "Если блок для домена не нужен, отредактируйте $CONF_DEST и закомментируйте последний server { }."
    echo "Восстановление бэкапа..."
    sudo cp "${CONF_DEST}.bak" "$CONF_DEST"
    exit 1
fi

echo "Перезагрузка nginx..."
sudo systemctl reload nginx
echo "Готово. Проверьте: https://bitecosystem.ru/api/miniapp/plans и https://213.165.38.222/sub/КОД"
