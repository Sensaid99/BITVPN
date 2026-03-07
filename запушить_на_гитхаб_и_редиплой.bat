@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Пуш на GitHub (редиплой API на Render)
echo ========================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Git не найден. Установите: https://git-scm.com
    pause
    exit /b 1
)

if not exist ".git" (
    echo Репозиторий Git ещё не инициализирован. Создаю...
    git init
    echo.
    echo Теперь один раз привяжите репозиторий GitHub (адрес БЕЗ /tree/main/...^):
    echo   git remote add origin https://github.com/Sensaid99/BITVPN.git
    echo.
    echo Затем снова запустите этот файл.
    pause
    exit /b 0
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Удалённый репозиторий не задан. Выполните в этой папке ОДИН РАЗ:
    echo.
    echo   git remote add origin https://github.com/Sensaid99/BITVPN.git
    echo.
    echo Важно: используйте адрес репозитория с окончанием .git, НЕ ссылку на папку /tree/main/...
    echo.
    pause
    exit /b 1
)

git add -A
git status
echo.

set BRANCH=main
git rev-parse --verify main >nul 2>&1
if errorlevel 1 (
    set BRANCH=master
)

set MSG=Update %date% %time%
set MSG=%MSG: =_%
set MSG=%MSG::=-%
git commit -m "%MSG%" 2>nul
if errorlevel 1 (
    echo Нет изменений для коммита — всё уже запушено.
    goto :push
)
echo Коммит создан.
echo.

:push
echo Отправка на GitHub (ветка main — именно её смотрит Render)...
git push origin %BRANCH%:main 2>&1
if errorlevel 1 (
    echo.
    echo Повторная попытка...
    git push origin %BRANCH%:main 2>&1
)
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось отправить на GitHub. Проверьте:
    echo   - логин/пароль или токен (если спрашивает — используйте Personal Access Token вместо пароля);
    echo   - что репозиторий на GitHub создан и адрес в remote верный: git remote -v
    pause
    exit /b 1
)

echo.
echo Готово. Код отправлен на GitHub (ветка main).
echo Проверка: https://github.com/Sensaid99/BITVPN/tree/main — в корне должен быть render.yaml.
echo Если Render подключён к репозиторию — редиплой запустится автоматически.
echo.
pause
