@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ========================================
echo   Деплой всего: Vercel + сервер
echo ========================================
echo.

echo 1. Деплой мини-аппа на Vercel...
call "%~dp0ДЕПЛОЙ_МИНИАПП_VERCEL.bat"
echo.

echo 2. Деплой кода и API на сервер (в этом же окне)...
call "%~dp0ДЕПЛОЙ_НА_СЕРВЕР.bat" KEEPOPEN
echo.

echo Готово. Нажмите любую клавишу для выхода.
pause >nul