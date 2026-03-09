@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Перезапуск сервисов на сервере

echo.
echo ========================================
echo   Перезапуск на сервере (без деплоя)
echo ========================================
echo.

where ssh >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] SSH не найден. Установите OpenSSH-клиент.
    pause
    exit /b 1
)

if not exist "deploy_config.cmd" (
    echo Нет deploy_config.cmd. Создайте его (SERVER_USER, SERVER_IP, RESTART_CMD).
    pause
    exit /b 1
)
call deploy_config.cmd

if "%SERVER_IP%"=="" (
    echo Укажите SERVER_IP в deploy_config.cmd.
    pause
    exit /b 1
)

echo Выполняю на сервере: %RESTART_CMD%
echo Введите пароль от сервера, если попросит.
echo.
ssh %SERVER_USER%@%SERVER_IP% "%RESTART_CMD%"
if errorlevel 1 (
    echo [ОШИБКА] Подключение или команда не удались.
    pause
    exit /b 1
)

echo.
echo Готово.
pause
