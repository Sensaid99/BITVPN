@echo off
chcp 65001 >nul
echo ========================================
echo   Деплой Mini App на Vercel
echo ========================================
echo.

where npx >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Не найден npx. Установите Node.js: https://nodejs.org
    pause
    exit /b 1
)

echo Открываю окно, в котором запустится деплой.
echo Окно НЕ закроется — вы сможете прочитать вывод и войти в Vercel.
echo.
start "Vercel Deploy" cmd /k "cd /d ""%~dp0webapp"" && echo При первом запуске откроется браузер для входа. && echo. && npx vercel --prod && echo. && echo Скопируйте адрес Production выше в .env как WEBAPP_URL=... && echo. && pause"
