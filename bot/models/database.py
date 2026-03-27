"""Database models for VPN Telegram Bot"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy import create_engine, inspect, text

Base = declarative_base()

# Порядок удаления таблиц для SQLite (сначала зависимые, потом users)
_TABLES_DROP_ORDER = [
    "referral_payouts", "admin_logs", "payments", "subscriptions", "vpn_keys", "bot_stats", "users"
]


class User(Base):
    """User model"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    # Telegram выдаёт ID > 2^31-1; в PostgreSQL INTEGER не вмещает — нужен BIGINT
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    language_code = Column(String(10), default='ru')
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Referral system
    referrer_id = Column(Integer, ForeignKey('users.id'))
    referral_code = Column(String(20), unique=True)
    referral_balance = Column(Float, default=0.0)  # Баланс с рефералов
    total_referrals = Column(Integer, default=0)   # Общее количество рефералов
    
    # User stats
    total_spent = Column(Float, default=0.0)       # Общая потраченная сумма
    last_activity = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    referrals = relationship("User", remote_side=[id])
    
    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, username={self.username})>"
    
    @property
    def full_name(self):
        """Get user's full name"""
        parts = [self.first_name, self.last_name]
        return ' '.join(filter(None, parts)) or self.username or f"User {self.telegram_id}"
    
    @property
    def active_subscription(self):
        """Get user's active subscription"""
        return next((sub for sub in self.subscriptions if sub.is_active and not sub.is_expired), None)
    
    @property
    def has_active_subscription(self):
        """Check if user has active subscription"""
        return self.active_subscription is not None


class Subscription(Base):
    """Subscription model"""
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plan_type = Column(String(50), nullable=False)  # 1_month, 3_months, etc.
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    vpn_config = Column(Text)  # VPN configuration data
    config_name = Column(String(255))  # Имя конфигурации
    server_location = Column(String(100))  # Локация сервера
    created_at = Column(DateTime, default=datetime.utcnow)
    # Флаги одноразовых уведомлений об истечении (чтобы не слать повторно)
    notified_3d = Column(Boolean, default=False)
    notified_1d = Column(Boolean, default=False)
    notified_expired = Column(Boolean, default=False)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    
    def __repr__(self):
        return f"<Subscription(user_id={self.user_id}, plan={self.plan_type}, active={self.is_active})>"
    
    @property
    def is_expired(self):
        """Check if subscription is expired"""
        return datetime.utcnow() > self.end_date
    
    @property
    def days_remaining(self):
        """Get days remaining in subscription"""
        if self.is_expired:
            return 0
        return (self.end_date - datetime.utcnow()).days
    
    @property
    def time_remaining_text(self):
        """Get human-readable time remaining"""
        if self.is_expired:
            return "Истекла"
        
        diff = self.end_date - datetime.utcnow()
        days = diff.days
        
        if days > 30:
            months = days // 30
            return f"{months} мес."
        elif days > 0:
            return f"{days} дн."
        else:
            hours = diff.seconds // 3600
            return f"{hours} ч."


class Payment(Base):
    """Payment model"""
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Integer, nullable=False)  # Amount in kopecks
    currency = Column(String(3), default='RUB')
    plan_type = Column(String(50), nullable=False)
    payment_method = Column(String(50))  # yoomoney, qiwi, crypto
    payment_id = Column(String(255))  # External payment ID
    payment_url = Column(String(500))  # Payment URL for user
    status = Column(String(20), default='pending')  # pending, completed, failed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    expires_at = Column(DateTime)  # Время истечения счета
    
    # Relationships
    user = relationship("User", back_populates="payments")
    
    def __repr__(self):
        return f"<Payment(user_id={self.user_id}, amount={self.amount}, status={self.status})>"
    
    @property
    def amount_rubles(self):
        """Get amount in rubles"""
        return self.amount / 100
    
    @property
    def is_expired(self):
        """Check if payment is expired"""
        return self.expires_at and datetime.utcnow() > self.expires_at


class VPNKey(Base):
    """VPN Key model for managing available keys"""
    __tablename__ = 'vpn_keys'
    
    id = Column(Integer, primary_key=True)
    key_data = Column(Text, nullable=False)  # VPN configuration or key
    server_location = Column(String(100))  # Server location
    is_used = Column(Boolean, default=False)
    assigned_user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime)
    
    def __repr__(self):
        return f"<VPNKey(id={self.id}, is_used={self.is_used}, location={self.server_location})>"


class ReferralPayout(Base):
    """Referral payout model"""
    __tablename__ = 'referral_payouts'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)  # Amount in rubles
    status = Column(String(20), default='pending')  # pending, completed, failed
    payment_method = Column(String(50))
    payment_details = Column(String(500))  # Card number, wallet, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    def __repr__(self):
        return f"<ReferralPayout(user_id={self.user_id}, amount={self.amount}, status={self.status})>"


class AdminLog(Base):
    """Admin action logs"""
    __tablename__ = 'admin_logs'
    
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(255), nullable=False)
    target_user_id = Column(Integer, ForeignKey('users.id'))
    details = Column(Text)
    ip_address = Column(String(45))  # IPv4 or IPv6
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<AdminLog(admin_id={self.admin_id}, action={self.action})>"


class BotStats(Base):
    """Bot statistics model"""
    __tablename__ = 'bot_stats'
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.utcnow)
    total_users = Column(Integer, default=0)
    active_subscriptions = Column(Integer, default=0)
    daily_revenue = Column(Float, default=0.0)
    new_users = Column(Integer, default=0)
    new_payments = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<BotStats(date={self.date.date()}, users={self.total_users})>"


class DatabaseManager:
    """Database management class"""
    
    def __init__(self, database_url: str):
        # Для PostgreSQL: проверка соединения перед использованием; короткий recycle из-за Neon (SSL closed)
        engine_opts = {"pool_pre_ping": True}
        if database_url and "postgres" in (database_url.split(":")[0] or "").lower():
            engine_opts["pool_recycle"] = 60   # не держать соединения дольше минуты (Neon закрывает idle SSL)
        self.engine = create_engine(database_url, **engine_opts)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def _migrate_postgres_telegram_id_bigint(self) -> None:
        """ALTER public.users.telegram_id INTEGER → BIGINT (Telegram ID может быть > 2147483647)."""
        logger = logging.getLogger(__name__)
        if self.engine.dialect.name != "postgresql":
            return
        try:
            # Явно public: на Neon/current_schema() иногда не совпадает с таблицей — миграция молча пропускалась
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        DO $migrate$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name = 'users'
                                  AND column_name = 'telegram_id'
                                  AND data_type IN ('integer', 'smallint')
                            ) THEN
                                ALTER TABLE public.users ALTER COLUMN telegram_id TYPE BIGINT;
                            END IF;
                        END;
                        $migrate$;
                        """
                    )
                )
            logger.info("PostgreSQL: users.telegram_id checked → BIGINT (public.users)")
        except Exception as e:
            logger.error("PostgreSQL telegram_id BIGINT migration failed: %s", e, exc_info=True)

    def _schema_ok(self) -> bool:
        """Проверка, что таблица users имеет нужную схему (telegram_id)."""
        try:
            insp = inspect(self.engine)
            if "users" not in insp.get_table_names():
                return False
            cols = [c["name"] for c in insp.get_columns("users")]
            return "telegram_id" in cols
        except Exception:
            return False
        
    def create_tables(self):
        """Create all database tables. Если БД от старого бота (нет telegram_id) — пересоздаёт таблицы (только SQLite)."""
        # PRAGMA — только для SQLite; для PostgreSQL не выполняем
        is_sqlite = self.engine.dialect.name == "sqlite"
        if is_sqlite and not self._schema_ok():
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                for table in _TABLES_DROP_ORDER:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                conn.commit()
                conn.execute(text("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(bind=self.engine)

        # PostgreSQL: старые БД могли иметь users.telegram_id INTEGER — миграция в BIGINT
        if not is_sqlite:
            self._migrate_postgres_telegram_id_bigint()

        # Добавить колонки уведомлений об истечении в существующую таблицу subscriptions
        insp = inspect(self.engine)
        if "subscriptions" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("subscriptions")]
            with self.engine.connect() as conn:
                for col in ("notified_3d", "notified_1d", "notified_expired"):
                    if col not in cols:
                        try:
                            if is_sqlite:
                                conn.execute(text(f"ALTER TABLE subscriptions ADD COLUMN {col} BOOLEAN DEFAULT 0"))
                            else:
                                conn.execute(text(f"ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT FALSE"))
                            conn.commit()
                        except Exception:
                            conn.rollback()

    def get_session(self):
        """Get database session"""
        return self.SessionLocal()
        
    def close(self):
        """Close database connection"""
        self.engine.dispose()