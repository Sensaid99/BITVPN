# -*- coding: utf-8 -*-
"""Конфигурация бота поддержки @HelpBit_bot"""

import os
from pathlib import Path

# Корень проекта
BASE_DIR = Path(__file__).resolve().parent

# Токен от @BotFather для бота поддержки
BOT_TOKEN = os.getenv("HELPBIT_BOT_TOKEN", "").strip()

# ID главного админа (может добавлять других). Остальные админы хранятся в БД.
MASTER_ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("HELPBIT_ADMIN_IDS", "0").split(",") if x.strip().isdigit()
]

# Название сервиса (отображается в приветствии)
SERVICE_NAME = os.getenv("HELPBIT_SERVICE_NAME", "BitVPN")

# База данных тикетов и админов
DATABASE_PATH = BASE_DIR / "helpbit.db"
