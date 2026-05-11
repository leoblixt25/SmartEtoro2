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


class AutomationStatus(str, enum.Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PAUSED = "paused"


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
    risk_score = Column(Float, default=5.0)       # 1–10
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
    risk_score = Column(Float, default=5.0)
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


class AutomationRule(Base):
    """User-defined automation rules with full audit capability."""
    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    # take_profit / rebalance / pause_copy etc.
    rule_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(AutomationStatus), default=AutomationStatus.DISABLED)
    config = Column(JSON, default={})            # Flexible rule parameters
    threshold = Column(Float, nullable=True)
    cooldown_hours = Column(Integer, default=24)
    last_triggered = Column(DateTime, nullable=True)
    trigger_count = Column(Integer, default=0)
    requires_approval = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AutomationLog(Base):
    """Full audit trail for every automation action."""
    __tablename__ = "automation_logs"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("automation_rules.id"), nullable=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    action_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    details = Column(JSON, default={})
    was_simulated = Column(Boolean, default=True)
    was_approved = Column(Boolean, default=False)
    was_reversed = Column(Boolean, default=False)
    triggered_at = Column(DateTime, default=datetime.utcnow)


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


class AIRecommendation(Base):
    """AI-generated recommendations with confidence scoring."""
    __tablename__ = "ai_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    recommendation_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    confidence = Column(Float, default=0.5)      # 0.0–1.0
    risk_level = Column(String, default="low")   # low / medium / high
    is_acted_on = Column(Boolean, default=False)
    related_trader_id = Column(Integer, ForeignKey(
        "copied_traders.id"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RiskSettings(Base):
    """User-defined risk management thresholds."""
    __tablename__ = "risk_settings"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), unique=True)
    max_portfolio_drawdown_pct = Column(Float, default=20.0)
    max_allocation_per_trader_pct = Column(Float, default=30.0)
    min_traders_for_diversification = Column(Integer, default=3)
    max_single_asset_exposure_pct = Column(Float, default=25.0)
    volatility_reduction_threshold = Column(Float, default=15.0)
    cooldown_after_loss_hours = Column(Integer, default=48)
    emergency_protection_enabled = Column(Boolean, default=True)
    emergency_drawdown_trigger_pct = Column(Float, default=15.0)
    updated_at = Column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────
# Database engine helpers
# ──────────────────────────────────────────────

def get_engine(database_url: str = "sqlite:///./etoro_platform.db"):
    """Create SQLAlchemy engine. Use DATABASE_URL for PostgreSQL in production."""
    connect_args = {"check_same_thread": False, "timeout": 15} if database_url.startswith(
        "sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def create_tables(engine):
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
