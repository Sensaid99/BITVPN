@echo off
REM Скопируйте в deploy_config.cmd и подставьте свой IP/пользователя.
REM Файл deploy_config.cmd не коммитьте в Git с реальным IP (см. .gitignore).
set SERVER_USER=root
set SERVER_IP=YOUR_SERVER_IP
set BOT_PATH=/opt/vpn-bot
set RESTART_CMD=sudo systemctl restart vpn-bot
set RESTART_MINIAPP_CMD=sudo systemctl restart miniapp-api
set GIT_BRANCH=main
set COPY_ENV_TO_SERVER=1
REM Папки deploy/ и docs/ в репозитории — при git push подтягиваются актуальные скрипты nginx и инструкции.
