#!/bin/bash
# Диагностика: почему https://IP/sub/КОД отдаёт Not Found.
# Запуск на сервере: bash deploy/check-sub-url.sh [КОД]
# Пример: bash deploy/check-sub-url.sh yHmESPsZKd76

CODE="${1:-yHmESPsZKd76}"
echo "=== 1. API напрямую (порт 8765) ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:8765/sub/$CODE"
echo "=== 2. Через nginx (localhost) ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1/sub/$CODE"
echo "=== 3. Есть ли location /sub/ в nginx? ==="
grep -n "location /sub/" /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default 2>/dev/null || echo "Не найдено — добавьте location /sub/ и перезагрузите nginx."
echo "=== 4. miniapp-api запущен? ==="
systemctl is-active miniapp-api 2>/dev/null || echo "Проверьте: sudo systemctl status miniapp-api"
