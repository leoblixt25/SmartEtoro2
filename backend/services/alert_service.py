"""
Alert Service — centralized alert access, filtering, and management.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import Alert, AlertType

logger = logging.getLogger(__name__)


LOSS_THRESHOLD = -10.0
PROFIT_MIN = 10.0
PROFIT_MAX = 20.0
DEDUP_HOURS = 24


async def check_return_thresholds(db: Session, portfolio_id: int, bot=None) -> List[Dict]:
    """Check active traders for return threshold breaches.

    Alerts when a trader's total return:
      - drops to -6% or worse (critical alert)
      - reaches 10-20% profit range (info alert)

    Deduplicates by checking if the same alert title was created in the last DEDUP_HOURS.
    Sends Telegram notification if a bot instance is provided.
    """
    from backend.database.models import CopiedTrader

    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
            CopiedTrader.is_paused.is_(False),
        )
        .all()
    )

    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_HOURS)
    new_alerts = []

    for t in traders:
        ret = t.total_return_pct
        if ret is None:
            continue
        username = t.trader_username

        if ret <= LOSS_THRESHOLD:
            title = f"\U0001f534 Loss Alert: {username}"
            exists = db.query(Alert).filter(
                Alert.portfolio_id == portfolio_id,
                Alert.title == title,
                Alert.created_at > cutoff,
            ).first()
            if not exists:
                new_alerts.append({
                    "title": title,
                    "message": f"{username} has lost <b>{ret:.2f}%</b> \u2014 exceeds {abs(LOSS_THRESHOLD):.0f}% threshold (alloc: {t.allocation_pct:.1f}%)",
                    "severity": "critical",
                    "alert_type": AlertType.MONITORING,
                })

        elif PROFIT_MIN <= ret <= PROFIT_MAX:
            title = f"\U0001f7e2 Profit Alert: {username}"
            exists = db.query(Alert).filter(
                Alert.portfolio_id == portfolio_id,
                Alert.title == title,
                Alert.created_at > cutoff,
            ).first()
            if not exists:
                new_alerts.append({
                    "title": title,
                    "message": f"{username} is up <b>{ret:.2f}%</b> ({PROFIT_MIN:.0f}-{PROFIT_MAX:.0f}% range)",
                    "severity": "info",
                    "alert_type": AlertType.PROFIT_MILESTONE,
                })

    for a in new_alerts:
        db.add(Alert(
            portfolio_id=portfolio_id,
            alert_type=a["alert_type"],
            title=a["title"],
            message=a["message"],
            severity=a["severity"],
        ))
    if new_alerts:
        db.commit()
        if bot and bot.enabled:
            for a in new_alerts:
                await bot.send_message(
                    f"{a['title']}\n{a['message']}\n\U0001f4c5 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                    show_keyboard=False,
                )

    return new_alerts


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
