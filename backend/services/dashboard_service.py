"""
Dashboard Service — aggregates data from all services for the dashboard.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def build_dashboard_data(db: Session, portfolio_id: int) -> Dict:
    """Build the complete dashboard data structure.

    Sections:
      - portfolio_overview
      - active_traders
      - discovery
      - trader_health
      - alerts
    """
    from backend.services.portfolio_service import get_portfolio_overview, get_active_traders
    from backend.services.discovery_service import discover_eligible_traders
    from backend.services.alert_service import get_alerts, get_alert_summary

    overview = get_portfolio_overview(db, portfolio_id)
    active = get_active_traders(db, portfolio_id)

    discovery_scored, excluded, discovery_stats = await discover_eligible_traders(
        db, portfolio_id,
    )

    alert_summary = get_alert_summary(db, portfolio_id)
    recent_alerts = get_alerts(db, portfolio_id, unread_only=True, limit=10)

    return {
        "portfolio_overview": overview,
        "active_traders": active,
        "discovery": {
            "eligible": [
                {
                    "username": s.get("username", "?"),
                    "score": s.get("score", 0),
                    "total_return_pct": s.get("total_return_pct", 0),
                    "risk_score": s.get("risk_score", 5),
                    "max_drawdown": s.get("max_drawdown", 0),
                    "min_copy_amount": s.get("min_copy_amount", 200),
                    "confidence": s.get("confidence_score", 0),
                    "source": s.get("source", "unknown"),
                }
                for s in discovery_scored[:10]
            ],
            "stats": discovery_stats,
        },
        "alerts": {
            "summary": alert_summary,
            "recent": recent_alerts[:5],
        },
    }
