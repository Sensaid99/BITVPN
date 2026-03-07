@echo off
REM Ваш сервер (nikolay). Если сервис перезапуска не сработает — на сервере выполните: systemctl list-units | grep bot
set SERVER_USER=root
set SERVER_IP=155.212.164.135
set BOT_PATH=/opt/vpn-bot
set RESTART_CMD=sudo systemctl restart vpn-bot
