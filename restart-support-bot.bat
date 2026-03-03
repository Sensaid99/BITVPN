@echo off
chcp 65001 >nul
title Перезапуск бота поддержки
echo Подключение к серверу и перезапуск бота поддержки...
echo.
ssh root@155.212.164.135 "systemctl restart support-bot && echo OK: бот поддержки перезапущен"
echo.
pause
