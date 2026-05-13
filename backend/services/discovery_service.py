"""
Discovery Service — finds genuinely eligible new traders.
Filters out already-copied, blocked, and unavailable traders.
"""

import logging
from typing import Dict, List, Optional, Tuple

from backend.ai.eligibility_engine import filter_candidates
from backend.ai.scoring_engine import rank_candidates
from backend.ai.portfolio_engine import get_active_usernames
from backend.ai.discovery_engine import build_discovery_list, widen_search, log_discovery_summary

logger = logging.getLogger(__name__)


async def discover_eligible_traders(
    db,
    portfolio_id: int,
    max_results: int = 10,
    categories: Optional[List[str]] = None,
) -> Tuple[List[Dict], List[Dict], Dict]:
    """Find new eligible traders not already copied.

    Discovers candidates from a large pool (seed data + social API),
    enriches via tradeinfo API, filters for eligibility, scores,
    and returns top results.

    Args:
        db: Database session.
        portfolio_id: Portfolio ID.
        max_results: Maximum scored results to return (default 10).
        categories: Optional category filter (e.g. ["balanced", "tech_focused"]).

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

    # ── 1. Discover candidates from seed data + social API ──
    candidates = await discover_top_traders(categories=categories)

    # ── 2. Eligibility filter ──
    eligible, excluded = filter_candidates(
        candidates, active_usernames, available_balance,
    )

    # ── 3. Build discovery list (no overlap, category filter) ──
    category = categories[0] if categories and len(categories) == 1 else None
    discovery = build_discovery_list(eligible, active_usernames, category=category)

    # ── 4. Smart fallback: widen search if too few ──
    if len(discovery) < 3:
        logger.info(
            "Discovery: only %d eligible — widening search",
            len(discovery),
        )
        discovery = widen_search(eligible, active_usernames, category=category)

    # ── 5. Score discovery candidates ──
    scored = rank_candidates(holdings, discovery, top_n=max_results)

    # ── 6. Stats and logging ──
    stats = {
        "total_scanned": len(candidates),
        "eligible": len(scored),
        "excluded": len(excluded),
        "active_traders": len(active_usernames),
        "candidate_pool_size": len(candidates),
        "category": category or "all",
    }

    log_discovery_summary(
        scanned_count=len(candidates),
        eligible_count=len(scored),
        excluded_count=len(excluded),
        active_count=len(active_usernames),
        top_scores=scored[:5],
        category_used=category,
    )

    return scored, excluded, stats
