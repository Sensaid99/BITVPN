"""
Configuration module for VPN Telegram Bot
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Корень проекта (папка, где run.py). Загружаем .env оттуда с override=True,
# чтобы значение из файла (Vercel) всегда перебивало переменную окружения (ngrok)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)


class Config:
    """Bot configuration settings"""
    
    # Telegram Bot Settings
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    
    # Database Settings (путь к sqlite делаем абсолютным, чтобы один и тот же файл использовался при любом cwd)
    _db_url = os.getenv('DATABASE_URL', 'sqlite:///vpn_bot.db')
    if _db_url.startswith('sqlite:///') and not _db_url.startswith('sqlite:////'):
        _db_path = _PROJECT_ROOT / _db_url.replace('sqlite:///', '').lstrip('/')
        DATABASE_URL = 'sqlite:///' + str(_db_path).replace('\\', '/')
    else:
        DATABASE_URL = _db_url
    
    # Payment Settings
    YOOMONEY_TOKEN = os.getenv('YOOMONEY_TOKEN')
    # ЮKassa (YooKassa) — shop_id и секретный ключ из личного кабинета ЮKassa
    YOOKASSA_SHOP_ID = (os.getenv('YOOKASSA_SHOP_ID') or '').strip() or None
    YOOKASSA_SECRET_KEY = (os.getenv('YOOKASSA_SECRET_KEY') or '').strip() or None
    QIWI_TOKEN = os.getenv('QIWI_TOKEN')
    CRYPTOMUS_API_KEY = os.getenv('CRYPTOMUS_API_KEY')
    CRYPTOMUS_MERCHANT_ID = os.getenv('CRYPTOMUS_MERCHANT_ID')
    
    # VPN Settings
    VPN_SERVER_URL = os.getenv('VPN_SERVER_URL')
    VPN_API_KEY = os.getenv('VPN_API_KEY')
    # Happ (Happ-Proxy) — лимитированные ссылки для приложения Happ
    HAPP_API_URL = (os.getenv('HAPP_API_URL') or 'https://happ-proxy.com').rstrip('/')
    HAPP_PROVIDER_CODE = (os.getenv('HAPP_PROVIDER_CODE') or '').strip() or None
    HAPP_AUTH_KEY = (os.getenv('HAPP_AUTH_KEY') or '').strip() or None
    HAPP_SUBSCRIPTION_URL = (os.getenv('HAPP_SUBSCRIPTION_URL') or '').strip() or None
    
    # Bot Settings
    DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', 'ru')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Subscription Plans (1 device, in rubles). Скидка 5% за каждые 3 мес.
    PLAN_1_MONTH_PRICE = int(os.getenv('PLAN_1_MONTH_PRICE', 100))
    PLAN_3_MONTH_PRICE = int(os.getenv('PLAN_3_MONTH_PRICE', 285))   # 100*3*0.95
    PLAN_6_MONTH_PRICE = int(os.getenv('PLAN_6_MONTH_PRICE', 540))   # 100*6*0.9
    PLAN_9_MONTH_PRICE = int(os.getenv('PLAN_9_MONTH_PRICE', 765))   # 100*9*0.85
    PLAN_12_MONTH_PRICE = int(os.getenv('PLAN_12_MONTH_PRICE', 960)) # 100*12*0.8
    
    # Referral System
    REFERRAL_BONUS_PERCENT = int(os.getenv('REFERRAL_BONUS_PERCENT', 10))
    REFERRAL_MIN_PAYOUT = int(os.getenv('REFERRAL_MIN_PAYOUT', 100))
    
    # Support Configuration
    SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', 'vpn_support')
    SUPPORT_CHAT_ID = os.getenv('SUPPORT_CHAT_ID')
    
    # Mini App (Web App) — HTTPS URL. Если задан, в меню показывается кнопка «Открыть приложение»
    WEBAPP_URL = (os.getenv('WEBAPP_URL') or '').strip() or None
    # API для личного кабинета в Mini App (проверка подписки). Если задан, в URL мини-апп добавляется ?api=...
    MINIAPP_API_URL = (os.getenv('MINIAPP_API_URL') or '').strip() or None
    # Username бота без @ — передаётся в мини-апп для кнопки «Оплатить» (открытие бота с start=pay_1month и т.д.)
    BOT_USERNAME = (os.getenv('BOT_USERNAME') or '').strip() or None
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.ADMIN_IDS:
            raise ValueError("At least one ADMIN_ID is required")
        return True


# Цена за месяц по количеству устройств (руб) — для расчёта при 2+ устройствах
DEVICE_BASE_PRICE = {1: 100, 3: 150, 5: 250, 10: 450}

# Соответствие сроков и переменных из .env (единый источник с мини-апп)
_MONTHS_TO_PLAN_PRICE = {
    1: Config.PLAN_1_MONTH_PRICE,
    3: Config.PLAN_3_MONTH_PRICE,
    6: Config.PLAN_6_MONTH_PRICE,
    9: Config.PLAN_9_MONTH_PRICE,
    12: Config.PLAN_12_MONTH_PRICE,
}


def get_plan_price_1_device(months: int) -> int:
    """Цена для 1 устройства на N месяцев — из .env (PLAN_*_PRICE), как в мини-апп."""
    return _MONTHS_TO_PLAN_PRICE.get(months, Config.PLAN_1_MONTH_PRICE)


def calc_subscription_price(devices: int, months: int) -> int:
    """Стоимость подписки: для 1 устройства — из .env; для 2+ — база по устройствам, скидка 5% за каждые 3 месяца (как в мини-апп)."""
    if devices == 1:
        return get_plan_price_1_device(months)
    base = DEVICE_BASE_PRICE.get(devices, 100)
    full = base * months
    discount_pct = (months // 3) * 5
    return int(round(full * (1 - discount_pct / 100)))


# Subscription plans configuration (1 device) — цены из того же источника, что и в мини-апп
SUBSCRIPTION_PLANS = {
    '1_month': {
        'name': '1 месяц',
        'price': get_plan_price_1_device(1),
        'duration_days': 30,
        'months': 1,
        'description': '🚀 Базовый план на 1 месяц',
        'emoji': '🥉',
        'popular': False
    },
    '3_months': {
        'name': '3 месяца',
        'price': get_plan_price_1_device(3),
        'duration_days': 90,
        'months': 3,
        'description': '🔥 Популярный план на 3 месяца',
        'emoji': '🥈',
        'popular': True
    },
    '6_months': {
        'name': '6 месяцев',
        'price': get_plan_price_1_device(6),
        'duration_days': 180,
        'months': 6,
        'description': '💎 Выгодный план на полгода',
        'emoji': '🥇',
        'popular': False
    },
    '9_months': {
        'name': '9 месяцев',
        'price': get_plan_price_1_device(9),
        'duration_days': 270,
        'months': 9,
        'description': '🎯 План на 9 месяцев',
        'emoji': '📦',
        'popular': False
    },
    '12_months': {
        'name': '1 год',
        'price': get_plan_price_1_device(12),
        'duration_days': 365,
        'months': 12,
        'description': '👑 Максимальная выгода на целый год',
        'emoji': '💰',
        'popular': False
    }
}

# Payment methods configuration
PAYMENT_METHODS = {
    'yoomoney': {
        'name': 'ЮMoney',
        'emoji': '💳',
        'description': 'Банковские карты, электронные кошельки'
    },
    'yookassa': {
        'name': 'Банковская карта',
        'emoji': '💳',
        'description': 'Банковские карты, ЮMoney'
    },
    'sbp': {
        'name': 'СБП',
        'emoji': '📱',
        'description': 'Система быстрых платежей'
    },
    'qiwi': {
        'name': 'QIWI',
        'emoji': '🥝',
        'description': 'QIWI кошелек, банковские карты'
    },
    'crypto': {
        'name': 'Криптовалюты',
        'emoji': '₿',
        'description': 'Bitcoin, Ethereum, USDT и другие'
    }
}