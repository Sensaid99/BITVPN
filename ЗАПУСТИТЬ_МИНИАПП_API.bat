@echo off
chcp 65001 >nul
echo ========================================
echo   API для личного кабинета Mini App
echo ========================================
echo.
echo Запуск на http://0.0.0.0:8765
echo Для доступа из интернета используйте ngrok: ngrok http 8765
echo Полученный https URL укажите в .env как MINIAPP_API_URL=...
echo.
cd /d "%~dp0"
python -m uvicorn api_miniapp:app --host 0.0.0.0 --port 8765
pause
