"""
Alert Service — centralized alert access, filtering, and management.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import Alert

logger = logging.getLogger(__name__)


def get_alerts(
    db: Session,
    portfolio_id: int,
    unread_only: bool = False,
    limit: int = 50,
    alert_types: Optional[List[str]] = None,
) -> List[Dict]:
    """Get alerts for a portfolio with optional filters."""
    q = db.query(Alert).filter(Alert.portfolio_id == portfolio_id)

    if unread_only:
        q = q.filter(Alert.is_read.is_(False))
    if alert_types:
        q = q.filter(Alert.alert_type.in_(alert_types))

    alerts = q.order_by(Alert.created_at.desc()).limit(limit).all()

    return [
        {
            "id": a.id,
            "type": a.alert_type.value if hasattr(a.alert_type, 'value') else str(a.alert_type),
            "title": a.title,
            "message": a.message,
            "severity": a.severity,
            "is_read": a.is_read,
            "was_sent_telegram": a.was_sent_telegram,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


def mark_alert_read(db: Session, alert_id: int) -> bool:
    """Mark a single alert as read. Returns True if found."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return False
    alert.is_read = True
    db.commit()
    return True


def mark_all_read(db: Session, portfolio_id: int) -> int:
    """Mark all alerts as read for a portfolio. Returns count."""
    count = (
        db.query(Alert)
        .filter(Alert.portfolio_id == portfolio_id, Alert.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return count


def get_alert_summary(db: Session, portfolio_id: int) -> Dict:
    """Return counts of unread alerts by severity."""
    alerts = (
        db.query(Alert)
        .filter(Alert.portfolio_id == portfolio_id, Alert.is_read.is_(False))
        .all()
    )
    return {
        "total": len(alerts),
        "critical": sum(1 for a in alerts if a.severity == "critical"),
        "warning": sum(1 for a in alerts if a.severity == "warning"),
        "info": sum(1 for a in alerts if a.severity == "info"),
    }
