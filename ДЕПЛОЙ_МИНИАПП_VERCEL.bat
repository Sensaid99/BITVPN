@echo off
title Деплой мини-аппа на Vercel
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка: не удалось перейти в папку скрипта.
    goto :error
)

echo.
echo ========================================
echo   Деплой мини-аппа на Vercel (bitvpn.vercel.app)
echo   Папка: %CD%
echo ========================================
echo.

REM Синхронизация: если правили public — подтянуть в webapp
if exist "public\index.html" (
    echo 1. Синхронизация public -^> webapp...
    copy /Y "public\index.html" "webapp\index.html" >nul 2>nul
    echo    Готово.
) else (
    echo 1. public\index.html не найден — деплоим текущий webapp.
)
echo.

echo 2. Деплой папки webapp на Vercel...
where npx >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] npx не найден. Установите Node.js: https://nodejs.org/
    goto :error
)
cd webapp
npx vercel --prod
set VERCEL_EXIT=%errorlevel%
cd ..
if %VERCEL_EXIT% neq 0 (
    echo [ОШИБКА] Деплой Vercel не удался.
    goto :error
)

echo.
echo ========================================
echo   Готово. Откройте приложение из бота или bitvpn.vercel.app
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause
