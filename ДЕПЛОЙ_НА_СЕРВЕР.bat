@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Деплой на сервер (пуш в Git + обновление на сервере)
echo ========================================
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
    git commit -m "%MSG%" 2>nul
    git push origin main 2>nul
    if errorlevel 1 git push origin master 2>nul
    echo    Готово.
) else (
    echo    Git не найден — пропускаем пуш. На сервере будет обновлено из текущего состояния репозитория.
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

echo 3. Подключение к серверу и перезапуск бота...
echo    (git pull выполняется только если папка — репозиторий; иначе только перезапуск)
echo.
echo    Введите пароль от сервера, когда появится запрос.
echo.
ssh %SERVER_USER%@%SERVER_IP% "cd %BOT_PATH% && (git pull 2>/dev/null || true) && %RESTART_CMD%"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось выполнить команды на сервере.
    echo Проверьте: логин, IP, путь BOT_PATH и команду RESTART_CMD в deploy_server_config.cmd.
    pause
    exit /b 1
)

echo.
echo Готово. Бот на сервере обновлён и перезапущен.
pause
