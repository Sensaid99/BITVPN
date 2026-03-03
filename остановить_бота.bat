@echo off
chcp 65001 >nul
echo Ищем процессы Python (бот)...
echo.
tasklist /FI "IMAGENAME eq python.exe" 2>nul
if errorlevel 1 (
    echo Процессов python.exe не найдено.
    pause
    exit /b 0
)
echo.
echo Остановить все процессы python.exe? (бот перестанет работать)
pause
taskkill /F /IM python.exe 2>nul
echo Готово.
pause
