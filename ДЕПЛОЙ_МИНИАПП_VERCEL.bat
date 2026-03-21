@echo off
title Деплой мини-аппа: GitHub + Vercel
REM При двойном клике — отдельное окно (как ДЕПЛОЙ_НА_СЕРВЕР)
if not "%~1"=="KEEPOPEN" (
    start "Деплой мини-аппа Vercel" cmd /k "%~f0" KEEPOPEN
    exit /b 0
)
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка: не удалось перейти в папку скрипта.
    goto :error
)

echo.
echo ========================================
echo   Мини-апп одной кнопкой: синхронизация, GitHub, Vercel
echo   Папка: %CD%
echo ========================================
echo.

if not exist "webapp\index.html" (
    echo [ОШИБКА] Нет webapp\index.html
    goto :error
)

echo 1. Синхронизация webapp -^> public, index.html, api\root_index.html...
copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
copy /Y "public\index.html" "index.html" >nul 2>nul
if exist "api" copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
echo    Готово.
echo.

echo 2. Пуш на GitHub (Vercel привязан к репо — подхватит сборку)...
if exist "%~dp0deploy_config.cmd" call "%~dp0deploy_config.cmd"
if not defined GIT_BRANCH (
    for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
)
if not defined GIT_BRANCH set GIT_BRANCH=main
where git >nul 2>&1
if errorlevel 1 (
    echo    Git не найден — шаг 2 пропущен (только Vercel CLI).
    goto :vercel_cli
)
git add -A
git status --short
git commit -m "Deploy miniapp" 2>nul
if errorlevel 1 echo    Нет новых файлов для коммита или ошибка коммита.
git push origin %GIT_BRANCH% 2>nul
if errorlevel 1 (
    git push origin HEAD:%GIT_BRANCH% 2>nul
)
if errorlevel 1 (
    echo    [ВНИМАНИЕ] Пуш не удался. Проверьте GIT_BRANCH в deploy_config.cmd и SSH-ключи GitHub.
) else (
    echo    Пуш выполнен.
)
echo.

:vercel_cli
echo 3. Деплой папки webapp на Vercel (npx vercel --prod)...
where npx >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] npx не найден. Установите Node.js: https://nodejs.org/
    goto :error
)
pushd webapp
call npx vercel --prod
if errorlevel 1 (
    popd
    echo [ОШИБКА] Деплой Vercel не удался. Выполните: cd webapp ^&^& npx vercel login
    goto :error
)
popd

echo.
echo ========================================
echo   Готово.
echo   • Проект на Vercel: https://vercel.com/dashboard
echo   • Обычно URL: https://bitvpn.vercel.app (см. настройки проекта)
echo   • WEBAPP_URL в .env должен совпадать с этим URL + ?api=https://ваш-API
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause
