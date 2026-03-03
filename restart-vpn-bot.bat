@echo off
chcp 65001 >nul
title Перезапуск VPN-бота
echo Подключение к серверу и перезапуск VPN-бота...
echo.
ssh root@155.212.164.135 "systemctl restart vpn-bot && echo OK: VPN-бот перезапущен"
echo.
pause
