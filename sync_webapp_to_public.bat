@echo off
REM После правок в webapp\index.html запустите этот скрипт и задеплойте API на Vercel.
if not exist "public" mkdir public
copy /Y "webapp\index.html" "public\index.html"
echo Done. public\index.html updated.
