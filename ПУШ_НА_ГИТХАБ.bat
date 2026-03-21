@echo off
title Пуш на GitHub - редеплой Vercel
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if errorlevel 1 (
    echo Ошибка: не удалось перейти в папку скрипта.
    goto :error
)

echo.
echo ========================================
echo   Пуш на GitHub - редеплой на Vercel
echo   Папка: %CD%
echo ========================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Git не найден. Установите Git и добавьте в PATH.
    goto :error
)

echo 1. Синхронизация Mini App: webapp -^> public -^> index, api...
if exist "webapp\index.html" (
    copy /Y "webapp\index.html" "public\index.html" >nul 2>nul
)
if exist "public\index.html" (
    copy /Y "public\index.html" "index.html" >nul
    if exist "api" copy /Y "public\index.html" "api\root_index.html" >nul 2>nul
    echo    Готово.
) else (
    echo    Пропущено - нет public\index.html
)
echo.

echo 2. Пуш на GitHub...
for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set GIT_BRANCH=%%i
if not defined GIT_BRANCH set GIT_BRANCH=main
git add -A
set MSG=Redeploy %date% %time%
set MSG=%MSG: =_%
set MSG=%MSG::=-%
git commit -m "%MSG%" 2>nul
if errorlevel 1 (
    echo    Нет изменений для коммита или ошибка коммита.
) else (
    git push origin %GIT_BRANCH% 2>nul
    if errorlevel 1 (
        echo    [ОШИБКА] Пуш не удался. Проверьте доступ к GitHub.
        goto :error
    )
    echo    Пуш выполнен. Vercel подхватит изменения и задеплоит.
)
echo.
echo ========================================
echo   Готово.
echo ========================================
goto :finish

:error
echo.
echo Скрипт завершился с ошибкой.
:finish
pause
