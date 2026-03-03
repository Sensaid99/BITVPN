@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Папка бота: %CD%
echo.
echo Останавливаем старые процессы Python (чтобы не было конфликта)...
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul
echo Запуск бота...
python run.py
pause
