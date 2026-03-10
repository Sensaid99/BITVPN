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

echo Если была ошибка "Git author ... must have access to the team":
echo   В папке проекта выполните: git config user.email "ваш_email@example.com"
echo   (подставьте тот же email, под которым вы вошли в Vercel)
echo.
echo Открываю окно, в котором запустится деплой.
echo Окно НЕ закроется — вы сможете прочитать вывод и войти в Vercel.
echo.
start "Vercel Deploy" cmd /k "cd /d ""%~dp0webapp"" && echo При первом запуске откроется браузер для входа. && echo. && npx vercel --prod && echo. && echo Используйте стабильный адрес Aliased: https://bitvpn.vercel.app && echo В .env НЕ подставляйте адрес Production с хешем. Оставьте WEBAPP_URL=https://bitvpn.vercel.app?api=https://nikolay.lisobyk.fvds.ru && echo. && pause"
