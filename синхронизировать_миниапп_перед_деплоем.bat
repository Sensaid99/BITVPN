@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Копирую public\index.html в корень и в api\ — чтобы мини-апп открывался после деплоя...
copy /Y "public\index.html" "index.html" >nul
copy /Y "public\index.html" "api\root_index.html" >nul
echo Готово. Можно пушить и деплоить.
pause
