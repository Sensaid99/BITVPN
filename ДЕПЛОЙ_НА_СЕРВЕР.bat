@echo off
title Деплой на сервер
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка: не удалось перейти в папку скрипта.
    goto :error
)

echo.
echo ========================================
echo   Деплой всего на сервер
echo   Папка: %CD%
echo ========================================
echo.

where ssh >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] SSH не найден. Установите OpenSSH-клиент в Параметры Windows.
    goto :error
)

if not exist "%~dp0deploy_config.cmd" (
    echo Нет deploy_config.cmd в папке скрипта. Создайте его с переменными:
    echo   SERVER_USER, SERVER_IP, BOT_PATH, RESTART_CMD
    echo Пример: SERVER_USER=root  SERVER_IP=ваш.ip  BOT_PATH=/opt/vpn-bot  RESTART_CMD=sudo systemctl restart vpn-bot
    goto :error
)
call "%~dp0deploy_config.cmd"

if "%SERVER_IP%"=="" (
    echo Укажите SERVER_IP в deploy_config.cmd.
    goto :error
)

echo 1. Синхронизация Mini App (webapp -^> public -^> index, api)...
if exist "webapp\index.html" (
    copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
)
if exist "public\index.html" (
    copy /Y "public\index.html" "index.html" >nul
    if exist "api" copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
    echo    Готово.
) else (
    echo    Пропущено - нет public\index.html
)
echo.

echo 2. Пуш на GitHub...
where git >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
    if not defined GIT_BRANCH set GIT_BRANCH=main
    git add -A
    set MSG=Deploy %date% %time%
    set MSG=%MSG: =_%
    set MSG=%MSG::=-%
    git commit -m "%MSG%" 2>nul
    git push origin %GIT_BRANCH% 2>nul
    if errorlevel 1 (echo    Пуш пропущен или не удался.) else (echo    Пуш выполнен.)
) else (
    echo    Git не найден — пуш пропущен.
)
echo.

echo 3. Копирование .env на сервер — ОТКЛЮЧЕНО (чтобы не затирать WEBAPP_URL с ?api= на сервере).
echo    Если нужно обновить .env на сервере — скопируйте вручную или раскомментируйте строки ниже.
REM scp -q ".env" %SERVER_USER%@%SERVER_IP%:%BOT_PATH%/.env 2>nul
REM if errorlevel 1 (echo    Не удалось.) else (echo    .env скопирован.)
echo.

echo 4. На сервере: обновление из GitHub и перезапуск...
echo    Локальные изменения на сервере будут заменены кодом из репозитория.
echo    Введите пароль от сервера, если попросит.
ssh %SERVER_USER%@%SERVER_IP% "cd %BOT_PATH% && git fetch origin && BRANCH=$(git rev-parse --abbrev-ref HEAD) && git reset --hard origin/$BRANCH && %RESTART_CMD% && echo Готово."
if errorlevel 1 (
    echo [ОШИБКА] Подключение к серверу не удалось. Проверьте deploy_config.cmd.
    goto :error
)

echo.
echo ========================================
echo   Готово. Проверьте бота в Telegram.
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause
