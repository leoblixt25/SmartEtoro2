"""
eToro Stats Scraper — ingests live Stats Tab metrics into etoro_scraped_stats.
Reads yearly max drawdown and 7-day avg risk score from the tradeinfo API.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import EtoroScrapedStats

logger = logging.getLogger(__name__)


def validate_and_clean_metrics(yearly_max_dd_raw: Optional[float]) -> Optional[float]:
    """Validate yearly max drawdown before DB write.

    Rejects values > 99 (lifetime peak artifacts) and None.
    Returns cleaned float or None.
    """
    if yearly_max_dd_raw is None:
        return None
    yearly_dd = abs(float(yearly_max_dd_raw))
    if yearly_dd > 99.0:
        logger.warning("Rejected yearly_max_dd=%.2f (exceeds 99%% guardrail)", yearly_dd)
        return None
    return yearly_dd


def upsert_scraped_stats(
    db: Session,
    investor_id: str,
    avg_risk_score_7d: Optional[int],
    yearly_max_dd: Optional[float],
) -> None:
    """Insert or update scraped stats for a trader.

    Uses SQLAlchemy merge() for cross-dialect UPSERT (works on PostgreSQL and SQLite).
    """
    cleaned_dd = validate_and_clean_metrics(yearly_max_dd)
    cleaned_risk = int(avg_risk_score_7d) if avg_risk_score_7d is not None else None

    stats = EtoroScrapedStats(
        investor_id=investor_id,
        avg_risk_score_7d=cleaned_risk,
        yearly_max_dd=cleaned_dd,
        last_scraped_at=datetime.utcnow(),
    )
    db.merge(stats)
    logger.info(
        "Scraped stats for %s: risk=%s dd=%s",
        investor_id, cleaned_risk, cleaned_dd,
    )


def get_scraped_stats(db: Session, investor_id: str) -> Optional[EtoroScrapedStats]:
    """Retrieve the latest scraped stats for a trader."""
    return (
        db.query(EtoroScrapedStats)
        .filter(EtoroScrapedStats.investor_id == investor_id)
        .first()
    )
