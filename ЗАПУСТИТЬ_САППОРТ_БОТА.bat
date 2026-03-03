@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запуск бота поддержки @HelpBit_bot...
echo.
python -m support_bot.run
pause
