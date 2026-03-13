@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Деплой мини-аппа на Vercel...
call "ДЕПЛОЙ_МИНИАПП_VERCEL.bat"
echo.

echo Деплой кода и API на сервер...
call "ДЕПЛОЙ_НА_СЕРВЕР.bat"
echo.

echo Готово. Нажмите любую клавишу для выхода.
pause >nul