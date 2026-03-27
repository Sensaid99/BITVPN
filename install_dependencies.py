#!/usr/bin/env python3
"""
Автоматическая установка зависимостей для VPN Telegram Bot
"""

import subprocess
import sys
import os
from pathlib import Path

def install_package(package):
    """Install a package using pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    """Main installation function"""
    print("🚀 Установка зависимостей для VPN Telegram Bot...\n")
    
    # Check if requirements.txt exists
    requirements_file = Path("requirements.txt")
    if not requirements_file.exists():
        print("❌ Файл requirements.txt не найден!")
        return False
    
    # Read requirements
    with open(requirements_file, 'r') as f:
        packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"📦 Найдено {len(packages)} пакетов для установки:\n")
    
    # Install each package
    failed_packages = []
    for i, package in enumerate(packages, 1):
        print(f"[{i}/{len(packages)}] Установка {package}...", end=' ')
        
        if install_package(package):
            print("✅")
        else:
            print("❌")
            failed_packages.append(package)
    
    print(f"\n{'='*50}")
    print("РЕЗУЛЬТАТЫ УСТАНОВКИ")
    print('='*50)
    
    if not failed_packages:
        print("🎉 Все зависимости успешно установлены!")
        print("\n✅ Теперь вы можете запустить бота:")
        print("python bot/main.py")
        return True
    else:
        print(f"⚠️ Не удалось установить {len(failed_packages)} пакетов:")
        for package in failed_packages:
            print(f"   ❌ {package}")
        
        print("\n💡 Попробуйте установить вручную:")
        print("pip install -r requirements.txt")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)