#!/usr/bin/env python3
"""
Run the VPN Telegram Bot
Usage: python run.py
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Удалить старую БД (от прежнего бота), чтобы не путалась со схемой
_old_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vpn_users.db")
if os.path.isfile(_old_db):
    try:
        os.remove(_old_db)
    except OSError:
        pass  # занята процессом — не страшно, бот использует vpn_bot.db

from bot.main import main

if __name__ == '__main__':
    main()