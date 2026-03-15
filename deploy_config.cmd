@echo off
REM Настройки сервера для DEPLOY.bat. Укажите свои: SERVER_IP, при необходимости BOT_PATH и RESTART_CMD.
set SERVER_USER=root
set SERVER_IP=155.212.164.135
set BOT_PATH=/opt/vpn-bot
set RESTART_CMD=sudo systemctl restart vpn-bot
REM Ветка Git для пуша и обновления на сервере (main или master — должна совпадать с GitHub).
set GIT_BRANCH=main
REM Копировать ли .env на сервер при каждом деплое (1=да, 0=нет). Если 1 — в локальном .env держите актуальные HAPP_*, MINIAPP_API_URL и т.д.
set COPY_ENV_TO_SERVER=1
REM Папки deploy/ и docs/ в репозитории — при git push и обновлении на сервере (git reset --hard) подтягиваются актуальные скрипты nginx и инструкции.
