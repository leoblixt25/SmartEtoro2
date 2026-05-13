"""Data access layer for CopyVault.

Provides clean CRUD helpers for the most common database operations.
Keeps SQLAlchemy query logic out of service/handler modules.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import (
    Alert,
    AutomationLog,
    AutomationRule,
    CopiedTrader,
    Portfolio,
    PortfolioSnapshot,
    RiskSettings,
)


# ── Portfolio ───────────────────────────────────────────────────────

def get_portfolio(db: Session, portfolio_id: int) -> Optional[Portfolio]:
    return db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()


def get_first_portfolio(db: Session) -> Optional[Portfolio]:
    return db.query(Portfolio).order_by(Portfolio.id).first()


def update_portfolio(db: Session, portfolio_id: int, **kwargs) -> Optional[Portfolio]:
    p = get_portfolio(db, portfolio_id)
    if not p:
        return None
    for key, val in kwargs.items():
        if hasattr(p, key):
            setattr(p, key, val)
    p.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return p


# ── Copied Traders ──────────────────────────────────────────────────

def get_active_traders(db: Session, portfolio_id: int) -> List[CopiedTrader]:
    """Return traders that are active and not paused."""
    return (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
            CopiedTrader.is_paused.is_(False),
        )
        .all()
    )


def get_all_traders(db: Session, portfolio_id: int) -> List[CopiedTrader]:
    return (
        db.query(CopiedTrader)
        .filter(CopiedTrader.portfolio_id == portfolio_id)
        .all()
    )


def get_trader_by_id(db: Session, trader_id: str, portfolio_id: int) -> Optional[CopiedTrader]:
    return (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.trader_id == trader_id,
        )
        .first()
    )


def get_trader_by_username(db: Session, username: str, portfolio_id: int) -> Optional[CopiedTrader]:
    return (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.trader_username == username,
        )
        .first()
    )


def trader_count(db: Session, portfolio_id: int) -> int:
    return (
        db.query(CopiedTrader)
        .filter(CopiedTrader.portfolio_id == portfolio_id)
        .count()
    )


# ── Automation Rules ────────────────────────────────────────────────

def get_enabled_rules(db: Session, portfolio_id: int) -> List[AutomationRule]:
    return (
        db.query(AutomationRule)
        .filter(
            AutomationRule.portfolio_id == portfolio_id,
            AutomationRule.status == "enabled",
        )
        .all()
    )


def get_rule(db: Session, rule_id: int) -> Optional[AutomationRule]:
    return db.query(AutomationRule).filter(AutomationRule.id == rule_id).first()


# ── Alerts ──────────────────────────────────────────────────────────

def get_unread_alerts(db: Session, portfolio_id: int, limit: int = 5) -> List[Alert]:
    return (
        db.query(Alert)
        .filter(Alert.portfolio_id == portfolio_id, Alert.is_read.is_(False))
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )


def get_pending_approvals(db: Session, portfolio_id: int) -> List[Alert]:
    return (
        db.query(Alert)
        .filter(
            Alert.portfolio_id == portfolio_id,
            Alert.is_read.is_(False),
            Alert.alert_type == "automation",
        )
        .order_by(Alert.created_at.desc())
        .all()
    )


# ── Snapshots ───────────────────────────────────────────────────────

def get_recent_snapshots(db: Session, portfolio_id: int, days: int = 30) -> List[PortfolioSnapshot]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.recorded_at >= cutoff,
        )
        .order_by(PortfolioSnapshot.recorded_at)
        .all()
    )


# ── Risk Settings ───────────────────────────────────────────────────

def get_risk_settings(db: Session, portfolio_id: int) -> Optional[RiskSettings]:
    return (
        db.query(RiskSettings)
        .filter(RiskSettings.portfolio_id == portfolio_id)
        .first()
    )
