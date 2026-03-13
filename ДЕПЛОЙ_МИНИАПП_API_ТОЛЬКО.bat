@echo off
title Деплой только miniapp-API на сервер
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка: не удалось перейти в папку скрипта.
    goto :error
)

echo.
echo ========================================
echo   Деплой только miniapp-API на сервер
echo   Папка: %CD%
echo ========================================
echo.

REM 1. Синхронизация Mini App (webapp -> public -> index, api)
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

REM 2. Пуш на GitHub (HEAD -> master)
echo 2. Пуш на GitHub...
where git >nul 2>&1
if errorlevel 1 (
    echo    Git не найден - пуш пропущен.
) else (
    git add -A
    set MSG=Redeploy_miniapp_%date%_%time%
    set MSG=%MSG: =_%
    set MSG=%MSG::=-%
    git commit -m "%MSG%" 2>nul
    if errorlevel 1 (
        echo    Нет изменений для коммита или ошибка коммита.
    ) else (
        git push origin HEAD:master
        if errorlevel 1 (
            echo    [ВНИМАНИЕ] Пуш не удался. Проверьте доступ к GitHub.
        ) else (
            echo    Пуш выполнен.
        )
    )
)
echo.

REM 3. Обновление кода на сервере и перезапуск miniapp-api
echo 3. Обновление кода на сервере и перезапуск miniapp-api...
if not exist "%~dp0deploy_config.cmd" (
    echo    Нет deploy_config.cmd. Заполните SERVER_USER, SERVER_IP, BOT_PATH.
    goto :error
)
call "%~dp0deploy_config.cmd"

if "%SERVER_IP%"=="" (
    echo    Укажите SERVER_IP в deploy_config.cmd.
    goto :error
)

echo    Введите пароль от сервера, если попросит.
ssh %SERVER_USER%@%SERVER_IP% "cd %BOT_PATH% && git pull --ff-only && sudo systemctl restart miniapp-api && echo Готово."
if errorlevel 1 (
    echo    [ОШИБКА] Подключение или команды на сервере не удались.
    goto :error
)

echo.
echo ========================================
echo   Готово. miniapp-API обновлён.
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause

