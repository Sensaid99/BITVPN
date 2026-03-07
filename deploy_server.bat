@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Деплой VPN Bot — не закрывайте окно

echo.
echo ========================================
echo   Деплой на сервер (пуш в Git + обновление на сервере)
echo ========================================
echo.
echo   Если окно не видно — посмотрите в панель задач (иконка CMD).
echo.

where ssh >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] SSH не найден. Установите OpenSSH: Параметры Windows - Приложения - Дополнительные компоненты - OpenSSH-клиент
    pause
    exit /b 1
)

if not exist "deploy_server_config.cmd" (
    echo Создайте файл deploy_server_config.cmd с настройками сервера.
    echo Скопируйте deploy_server_config.cmd из папки проекта и укажите: SERVER_USER, SERVER_IP, BOT_PATH, RESTART_CMD
    pause
    exit /b 1
)
call deploy_server_config.cmd

if "%SERVER_IP%"=="192.168.1.100" (
    echo.
    echo [ВНИМАНИЕ] Откройте deploy_server_config.cmd и укажите реальные:
    echo   SERVER_USER  - логин на сервере
    echo   SERVER_IP    - IP или домен сервера
    echo   BOT_PATH     - папка с ботом на сервере
    echo   RESTART_CMD  - команда перезапуска бота
    echo.
    pause
    exit /b 1
)

echo 1. Пуш изменений на GitHub...
where git >nul 2>&1
if not errorlevel 1 (
    git add -A
    set MSG=Deploy %date% %time%
    set MSG=%MSG: =_%
    set MSG=%MSG::=-%
    git status -s
    git commit -m "%MSG%" 2>nul
    if errorlevel 1 (
        echo    Нет изменений для коммита или ошибка коммита.
    ) else (
        echo    Коммит создан. Пушу...
    )
    for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
    if not defined GIT_BRANCH set GIT_BRANCH=master
    echo    Ветка: %GIT_BRANCH%
    git push origin %GIT_BRANCH%
    if errorlevel 1 (
        echo    [ВНИМАНИЕ] Пуш в GitHub не выполнен. На сервере код НЕ обновится.
    ) else (
        echo    Пуш на GitHub выполнен.
    )
) else (
    echo    Git не найден — пуш пропущен. На сервере код не обновится без ручного копирования.
)
echo.

echo 2. Копирование .env на сервер (чтобы цены и настройки совпадали)...
scp -q ".env" %SERVER_USER%@%SERVER_IP%:%BOT_PATH%/.env 2>nul
if errorlevel 1 (
    echo    Не удалось скопировать .env — возможно, на сервере другой путь. Продолжаем без этого.
) else (
    echo    .env скопирован.
)
echo.

echo 3. Подключение к серверу: git pull и перезапуск бота...
echo    Введите пароль от сервера, когда появится запрос.
echo.
ssh %SERVER_USER%@%SERVER_IP% "cd %BOT_PATH% && echo '--- git pull ---' && (git pull 2>&1 || echo 'git pull не сработал (папка не репо?)') && echo '--- перезапуск ---' && %RESTART_CMD% && echo '--- готово ---'"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось выполнить команды на сервере.
    echo Проверьте: логин, IP, путь BOT_PATH и команду RESTART_CMD в deploy_server_config.cmd.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Готово. Проверьте бота: отправьте /start в Telegram.
echo.
echo   Если выше было "not a git repository" или "git pull не сработал" —
echo   на сервере папка не репозиторий. Один раз настройте Git по инструкции:
echo   СЕРВЕР_НАСТРОИТЬ_ГИТ_ОДИН_РАЗ.txt
echo ========================================
pause
