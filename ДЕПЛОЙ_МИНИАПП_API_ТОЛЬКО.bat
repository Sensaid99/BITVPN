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
if not exist "webapp\index.html" (
    echo    [ОШИБКА] Нет webapp\index.html. Создайте или восстановите файл.
    goto :error
)
copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
if errorlevel 1 (
    echo    [ОШИБКА] Не удалось скопировать в public\index.html
    goto :error
)
copy /Y "public\index.html" "index.html" >nul 2>nul
if exist "webapp\iphone_15_pro_max.glb" (
    copy /Y "webapp\iphone_15_pro_max.glb" "public\iphone_15_pro_max.glb" >nul 2>nul
    copy /Y "webapp\iphone_15_pro_max.glb" "iphone_15_pro_max.glb" >nul 2>nul
)
if exist "api" (
    copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
    if exist "public\iphone_15_pro_max.glb" copy /Y "public\iphone_15_pro_max.glb" "api\iphone_15_pro_max.glb" >nul 2>nul
)
echo    Скопировано: webapp -^> public, index.html, api\root_index.html, iphone_15_pro_max.glb
echo.

REM 2. Пуш на GitHub (HEAD -> master)
echo 2. Пуш на GitHub...
where git >nul 2>&1
if errorlevel 1 (
    echo    Git не найден - пуш пропущен.
) else (
    git add -A
    git status --short
    git commit -m "Redeploy_miniapp" 2>nul
    if errorlevel 1 (
        echo    Нет изменений для коммита. Сохранили ли вы webapp\index.html?
        echo    Пуш пропущен.
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

REM 2.5 Деплой мини-аппа на Vercel (bitvpn.vercel.app)
echo 2.5 Деплой мини-аппа на Vercel (bitvpn.vercel.app)...
where npx >nul 2>&1
if errorlevel 1 (
    echo    npx не найден - деплой Vercel пропущен. Установите Node.js.
) else (
    cd /d "%~dp0webapp"
    if errorlevel 1 (
        echo    [ОШИБКА] Папка webapp не найдена.
    ) else (
        echo    Запуск: npx vercel --prod --yes --no-wait
        echo    (деплой уходит на Vercel, скрипт не ждёт сборки — окно закроется за ~5 сек)
        call npx vercel --prod --yes --no-wait
        if errorlevel 1 (
            echo    [ВНИМАНИЕ] Vercel вернул ошибку. Проверьте вывод выше. Логин: vercel login
        ) else (
            echo    Vercel: деплой отправлен. Сайт обновится через 1-2 мин. Статус: vercel.com/dashboard
        )
        cd /d "%~dp0"
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
    echo    [ВНИМАНИЕ] SSH или команды на сервере не удались. Vercel уже обновлён, если шаг 2.5 прошёл.
    echo    Проверьте deploy_config.cmd и доступ по SSH.
    goto :finish
)

echo.
echo ========================================
echo   Готово. Мини-апп: Vercel + сервер miniapp-api обновлены.
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause

