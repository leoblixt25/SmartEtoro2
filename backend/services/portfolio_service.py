"""
Portfolio Service — single source for portfolio overview & active traders.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import Portfolio, CopiedTrader, Alert

logger = logging.getLogger(__name__)


def get_portfolio_overview(db: Session, portfolio_id: int) -> Dict:
    """Build full portfolio overview: value, cash, traders, health, sentiment."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return {"error": "Portfolio not found"}

    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
        )
        .all()
    )

    active_traders = [t for t in traders if not t.is_paused]
    total_return_pct = (
        (portfolio.total_value - portfolio.invested_amount)
        / max(portfolio.invested_amount, 1) * 100
    )

    # Concentration risk: any trader > 40% allocation?
    concentration_risk = any(
        t.allocation_pct > 40 for t in active_traders
    )

    # Overall sentiment from recent monitoring alerts
    recent = (
        db.query(Alert)
        .filter(
            Alert.portfolio_id == portfolio_id,
            Alert.alert_type.in_(["monitoring"]),
        )
        .order_by(Alert.created_at.desc())
        .limit(5)
        .all()
    )
    sentiment = "neutral"
    for alert in recent:
        if alert.severity == "critical":
            sentiment = "negative"
            break
        if alert.severity == "warning" and sentiment == "neutral":
            sentiment = "watch"

    return {
        "id": portfolio.id,
        "total_value": portfolio.total_value or 0,
        "invested_amount": portfolio.invested_amount or 0,
        "available_cash": portfolio.available_cash or 0,
        "total_return_pct": round(total_return_pct, 2),
        "unrealized_pnl": portfolio.unrealized_pnl or 0,
        "health_score": portfolio.health_score or 0,
        "active_traders": len(active_traders),
        "total_traders": len(traders),
        "concentration_risk": concentration_risk,
        "sentiment": sentiment,
        "currency": portfolio.currency or "USD",
        "last_sync": portfolio.last_updated.isoformat() if portfolio.last_updated else None,
    }


def get_active_traders(db: Session, portfolio_id: int) -> List[Dict]:
    """List all active copied traders with key metrics."""
    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
        )
        .all()
    )

    results = []
    for t in traders:
        results.append({
            "id": t.id,
            "username": t.trader_username,
            "allocation_pct": t.allocation_pct or 0,
            "allocated_amount": t.allocated_amount or 0,
            "current_value": t.current_value or 0,
            "total_return_pct": t.total_return_pct or 0,
            "risk_score": t.risk_score or 5,
            "risk_classification": str(t.risk_classification.value) if t.risk_classification else "unknown",
            "max_drawdown": t.max_drawdown or 0,
            "is_paused": t.is_paused,
            "paused_reason": t.paused_reason,
            "last_updated": t.last_updated.isoformat() if t.last_updated else None,
        })

    results.sort(key=lambda x: x["allocation_pct"], reverse=True)
    return results
