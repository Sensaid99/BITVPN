@echo off
title Деплой на сервер
REM Запуск в отдельном окне, которое не закроется после выполнения (удобно при двойном клике)
if not "%~1"=="KEEPOPEN" (
    start "Деплой на сервер" cmd /k "%~f0" KEEPOPEN
    exit /b 0
)
chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion
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
    if exist "%~dp0deploy_config.example.cmd" (
        copy /Y "%~dp0deploy_config.example.cmd" "%~dp0deploy_config.cmd" >nul
        echo Создан deploy_config.cmd из deploy_config.example.cmd — укажите SERVER_IP и при необходимости пути, затем запустите снова.
    )
)
if not exist "%~dp0deploy_config.cmd" (
    echo Нет deploy_config.cmd. Скопируйте deploy_config.example.cmd -^> deploy_config.cmd и задайте SERVER_USER, SERVER_IP, BOT_PATH, RESTART_CMD
    goto :error
)
call "%~dp0deploy_config.cmd"
if not defined RESTART_MINIAPP_CMD set RESTART_MINIAPP_CMD=sudo systemctl restart miniapp-api

if "%SERVER_IP%"=="" (
    echo Укажите SERVER_IP в deploy_config.cmd.
    goto :error
)

echo 1. Синхронизация Mini App: webapp -^> public -^> index, api...
if exist "webapp\index.html" (
    copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
    copy /Y "webapp\*.glb" "public\" >nul 2>nul
)
if exist "public\index.html" (
    copy /Y "public\index.html" "index.html" >nul
    if exist "api" copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
    echo    Готово.
) else (
    echo    Пропущено - нет public\index.html
)
echo.

echo 2. Пуш на GitHub, ветка %GIT_BRANCH% — в репозиторий попадут все файлы: код, deploy/, docs/, public, webapp...
where git >nul 2>&1
if errorlevel 1 goto :git_skip
git add -A
git status --short
git commit -m "Deploy" 2>nul
if errorlevel 1 echo    Нет изменений для коммита или ошибка коммита.
git push origin %GIT_BRANCH% 2>nul
if errorlevel 1 (
    git push origin HEAD:%GIT_BRANCH% 2>nul
)
if errorlevel 1 (
    echo    [ВНИМАНИЕ] Пуш не удался. Проверьте deploy_config.cmd GIT_BRANCH=main и доступ к GitHub.
    echo    Деплой на сервер продолжится.
) else (
    echo    Пуш выполнен.
)
goto :git_done
:git_skip
echo    Git не найден — пуш пропущен.
:git_done
echo.

echo 3. Копирование .env на сервер...
if "%COPY_ENV_TO_SERVER%"=="1" (
    set "ENVFILE=%~dp0.env"
    if exist "!ENVFILE!" (
        scp -q "!ENVFILE!" %SERVER_USER%@%SERVER_IP%:%BOT_PATH%/.env 2>nul
        if errorlevel 1 (echo    [ВНИМАНИЕ] Не удалось, проверьте SSH) else (echo    Файл .env скопирован на сервер)
    ) else (
        echo    Файл .env не найден — пропущено
    )
) else (
    echo    Отключено: COPY_ENV_TO_SERVER не 1 в deploy_config.cmd
)
echo.

echo 4. На сервере: обновление из GitHub, ветка %GIT_BRANCH%, и перезапуск...
echo    Введите пароль от сервера, если попросит.
ssh %SERVER_USER%@%SERVER_IP% "cd %BOT_PATH% && git fetch origin && git checkout %GIT_BRANCH% && git reset --hard origin/%GIT_BRANCH% && %RESTART_CMD% && %RESTART_MINIAPP_CMD% && (sudo bash deploy/apply-nginx-sub.sh 2>/dev/null || true) && echo Готово."
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
