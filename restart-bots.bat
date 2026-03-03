@echo off
chcp 65001 >nul
title Перезапуск ботов на сервере
echo Подключение к серверу и перезапуск обоих ботов...
echo.
ssh root@155.212.164.135 "systemctl restart vpn-bot support-bot && echo OK: оба бота перезапущены"
echo.
pause
