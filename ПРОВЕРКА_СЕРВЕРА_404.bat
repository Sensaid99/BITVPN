@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Проверка: URL мини-приложения на сервере

if not exist "deploy_server_config.cmd" (
    echo Создайте deploy_server_config.cmd с SERVER_USER, SERVER_IP, BOT_PATH.
    pause
    exit /b 1
)
call deploy_server_config.cmd

echo.
echo Проверяем .env и логи бота на сервере...
echo (введите пароль от сервера, если попросит)
echo.
ssh %SERVER_USER%@%SERVER_IP% "echo '=== WEBAPP_URL в .env ===' && grep WEBAPP_URL %BOT_PATH%/.env 2>nul || echo '(файл или переменная не найдены)' && echo '' && echo '=== Последние строки лога vpn-bot ===' && sudo journalctl -u vpn-bot -n 35 --no-pager"
echo.
echo Готово. Смотрите выше: должен быть WEBAPP_URL=https://bitvpn.vercel.app
echo и в логах строка «Mini App URL: https://bitvpn.vercel.app».
pause
