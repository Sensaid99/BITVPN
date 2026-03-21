@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ========================================
echo   Деплой всего: синхронизация, GitHub, сервер, Vercel
echo   Чтобы нигде не оставалась старая версия
echo ========================================
echo.

REM Сначала синхронизируем webapp -^> public, чтобы в пуш и на сервер попала одна и та же версия
echo 0. Синхронизация webapp -^> public, index, api...
if exist "webapp\index.html" (
    copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
    copy /Y "public\index.html" "index.html" >nul 2>nul
    if exist "api" copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
    echo    Готово.
) else (
    echo    Нет webapp\index.html — пропущено.
)
echo.

echo 1. Деплой на сервер: пуш GitHub, копирование .env, обновление на сервере, nginx...
call "%~dp0ДЕПЛОЙ_НА_СЕРВЕР.bat" KEEPOPEN
echo.

echo 2. Деплой мини-аппа на Vercel bitvpn.vercel.app...
call "%~dp0ДЕПЛОЙ_МИНИАПП_VERCEL.bat" KEEPOPEN
echo.

echo ========================================
echo   Готово. Проверьте бота и приложение.
echo ========================================
pause >nul