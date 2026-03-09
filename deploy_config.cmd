@echo off
REM Настройки сервера для DEPLOY.bat. Укажите свои: SERVER_IP, при необходимости BOT_PATH и RESTART_CMD.
set SERVER_USER=root
set SERVER_IP=155.212.164.135
set BOT_PATH=/opt/vpn-bot
set RESTART_CMD=sudo systemctl restart vpn-bot
