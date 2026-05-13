"""
Discovery Service — finds genuinely eligible new traders.
Filters out already-copied, blocked, and unavailable traders.
"""

import logging
from typing import Dict, List, Tuple

from backend.ai.eligibility_engine import filter_candidates
from backend.ai.scoring_engine import rank_candidates
from backend.ai.portfolio_engine import get_active_usernames

logger = logging.getLogger(__name__)


async def discover_eligible_traders(
    db,
    portfolio_id: int,
    max_results: int = 10,
) -> Tuple[List[Dict], List[Dict], Dict]:
    """Find new eligible traders not already copied.

    Returns:
        (eligible_scored, excluded, stats)
    """
    from backend.database.models import Portfolio
    from backend.services.market_data import get_current_holdings, discover_top_traders

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return [], [], {"error": "Portfolio not found"}

    holdings = get_current_holdings(db, portfolio_id)
    active_usernames = get_active_usernames(holdings)
    available_balance = portfolio.available_cash or (portfolio.total_value or 0) * 0.1

    candidates = await discover_top_traders()
    eligible, excluded = filter_candidates(
        candidates, active_usernames, available_balance,
    )

    scored = rank_candidates(holdings, eligible, top_n=max_results)

    stats = {
        "total_scanned": len(candidates),
        "eligible": len(scored),
        "excluded": len(excluded),
        "active_traders": len(active_usernames),
    }

    return scored, excluded, stats
