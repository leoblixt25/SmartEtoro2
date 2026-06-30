"""
SQLite / PostgreSQL database models using SQLAlchemy ORM.
Set DATABASE_URL to a PostgreSQL connection string for production.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime,
    Text, ForeignKey, Enum, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum

Base = declarative_base()


class RiskClassification(str, enum.Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    HIGH_RISK = "high_risk"


class AppSetting(Base):
    """Persistent application settings stored in the database."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow)


class AlertType(str, enum.Enum):
    DRAWDOWN = "drawdown"
    PROFIT_MILESTONE = "profit_milestone"
    VOLATILITY = "volatility"
    TRADER_RISK = "trader_risk"
    IMBALANCE = "imbalance"
    AUTOMATION = "automation"
    WEEKLY_SUMMARY = "weekly_summary"
    AI_SCOUT = "ai_scout"
    MONITORING = "monitoring"


class Portfolio(Base):
    """Main portfolio record for the user."""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    total_value = Column(Float, default=0.0)
    invested_amount = Column(Float, default=0.0)
    available_cash = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    weekly_pnl = Column(Float, default=0.0)
    monthly_pnl = Column(Float, default=0.0)
    health_score = Column(Float, default=0.0)   # 0–100
    currency = Column(String, default="USD")
    is_simulation = Column(Boolean, default=False)
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    positions = relationship("Position", back_populates="portfolio")
    snapshots = relationship("PortfolioSnapshot", back_populates="portfolio")
    copied_traders = relationship("CopiedTrader", back_populates="portfolio")


class Position(Base):
    """An open or closed position in the portfolio."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    instrument = Column(String, nullable=False)
    direction = Column(String, default="BUY")   # BUY / SELL
    amount = Column(Float, default=0.0)
    open_price = Column(Float, default=0.0)
    current_price = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    source = Column(String, default="manual")   # manual / copy

    portfolio = relationship("Portfolio", back_populates="positions")


class CopiedTrader(Base):
    """A trader being copied by the user."""
    __tablename__ = "copied_traders"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    trader_username = Column(String, nullable=False)
    trader_id = Column(String, nullable=False)
    allocated_amount = Column(Float, default=0.0)
    allocation_pct = Column(Float, default=0.0)
    current_value = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    total_return_pct = Column(Float, default=0.0)
    risk_score = Column(Float, nullable=True)       # 1–10, None = unset
    risk_classification = Column(
        Enum(RiskClassification),
        default=RiskClassification.BALANCED
    )
    max_drawdown = Column(Float, default=0.0)
    avg_monthly_return = Column(Float, default=0.0)
    sharpe_score = Column(Float, default=0.0)
    volatility = Column(Float, default=0.0)
    trade_frequency = Column(Float, default=0.0)  # trades/week
    diversification_score = Column(Float, default=0.0)
    consistency_score = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)
    paused_reason = Column(String, nullable=True)
    ai_summary = Column(Text, nullable=True)
    last_analyzed = Column(DateTime, nullable=True)
    health_status = Column(String, nullable=True)         # AI verdict: Strong/Good/Watch/Weak/Avoid
    watch_consecutive = Column(Integer, default=0)        # scans flagged WATCH before escalation
    copy_started = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="copied_traders")
    analytics_history = relationship(
        "TraderAnalyticsSnapshot", back_populates="trader")


class TraderAnalyticsSnapshot(Base):
    """Historical analytics snapshot for a trader."""
    __tablename__ = "trader_analytics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    trader_id = Column(Integer, ForeignKey("copied_traders.id"))
    risk_score = Column(Float, nullable=True)
    max_drawdown = Column(Float, default=0.0)
    monthly_return = Column(Float, default=0.0)
    sharpe_score = Column(Float, default=0.0)
    volatility = Column(Float, default=0.0)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    trader = relationship("CopiedTrader", back_populates="analytics_history")


class PortfolioSnapshot(Base):
    """Daily portfolio value snapshot for growth charts."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    total_value = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    health_score = Column(Float, default=0.0)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="snapshots")


class EtoroScrapedStats(Base):
    """Scraped stats from eToro trader profile Stats tab — 12-month rolling values."""
    __tablename__ = "etoro_scraped_stats"

    investor_id = Column(String, primary_key=True, index=True)
    avg_risk_score_7d = Column(Integer, nullable=True)
    yearly_max_dd = Column(Float, nullable=True)
    last_scraped_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    """System alerts sent to the user."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    alert_type = Column(Enum(AlertType))
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String, default="info")    # info / warning / critical
    is_read = Column(Boolean, default=False)
    was_sent_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────
# Database engine helpers
# ──────────────────────────────────────────────

def get_engine(database_url: str = "sqlite:///./etoro_platform.db"):
    """Create SQLAlchemy engine. Use DATABASE_URL for PostgreSQL in production."""
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 15}
        return create_engine(database_url, connect_args=connect_args)
    return create_engine(
        database_url,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def create_tables(engine):
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
