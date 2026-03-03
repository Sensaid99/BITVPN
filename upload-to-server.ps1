# Создаёт архив проекта и загружает его на сервер.
# Запуск: правый клик по файлу → "Выполнить с помощью PowerShell"
# или в PowerShell: cd "d:\VPN BOT"; .\upload-to-server.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Папка проекта: $PWD" -ForegroundColor Cyan
if (-not (Test-Path "run.py") -or -not (Test-Path "bot")) {
    Write-Host "Ошибка: run.py или папка bot не найдены. Запустите скрипт из папки VPN BOT." -ForegroundColor Red
    pause
    exit 1
}

$archive = "vpn-bot.tar.gz"
if (Test-Path $archive) { Remove-Item $archive -Force }
Write-Host "Создаю архив..." -ForegroundColor Yellow
tar --exclude=venv --exclude=__pycache__ --exclude=*.db --exclude=.git -czvf $archive .
$size = (Get-Item $archive).Length
Write-Host "Архив создан: $archive ($([math]::Round($size/1KB)) KB)" -ForegroundColor Green
if ($size -lt 50000) {
    Write-Host "Внимание: архив очень маленький. Проверьте, что в папке есть bot, support_bot, run.py." -ForegroundColor Red
}
Write-Host "Загружаю на сервер (введите пароль root)..." -ForegroundColor Yellow
scp $archive root@155.212.164.135:/opt/
Write-Host "Готово. Дальше на сервере выполните:" -ForegroundColor Green
Write-Host "  rm -rf /opt/vpn-bot" -ForegroundColor White
Write-Host "  mkdir -p /opt/vpn-bot" -ForegroundColor White
Write-Host "  tar -xzvf /opt/vpn-bot.tar.gz -C /opt/vpn-bot" -ForegroundColor White
Write-Host "  ls /opt/vpn-bot" -ForegroundColor White
pause
