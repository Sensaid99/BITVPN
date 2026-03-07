@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Копирование .env на сервер

if not exist "deploy_server_config.cmd" (
    echo Создайте deploy_server_config.cmd с SERVER_USER, SERVER_IP, BOT_PATH.
    pause
    exit /b 1
)
call deploy_server_config.cmd

if not exist ".env" (
    echo В этой папке нет файла .env. Запустите скрипт из папки d:\VPN BOT.
    pause
    exit /b 1
)

echo Размер .env на ПК:
for %%A in (.env) do echo   %%~zA байт
echo.
echo Копирую .env на сервер %SERVER_USER%@%SERVER_IP%:%BOT_PATH%/.env
echo Введите пароль от сервера, когда попросит.
echo.
scp ".env" %SERVER_USER%@%SERVER_IP%:%BOT_PATH%/.env
if errorlevel 1 (
    echo Ошибка копирования.
    pause
    exit /b 1
)
echo.
echo Готово. На сервере выполните: sudo systemctl restart vpn-bot
pause
