"""
Discovery Service — finds genuinely eligible new traders.
Filters out already-copied, blocked, and unavailable traders.

Includes run-lock, cooldown, and caching to prevent overlapping
or duplicate discovery runs.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

from backend.ai.eligibility_engine import filter_candidates
from backend.ai.scoring_engine import rank_candidates
from backend.ai.portfolio_engine import get_active_usernames
from backend.ai.discovery_engine import build_discovery_list, widen_search, log_discovery_summary

logger = logging.getLogger(__name__)

# ── Run guard ────────────────────────────────────────────────────────

_discovery_lock = asyncio.Lock()
_last_run_time = 0.0
_cache: Optional[Tuple[List[Dict], List[Dict], Dict]] = None
_cache_time = 0.0
COOLDOWN_SECONDS = 60.0
CACHE_TTL_SECONDS = 300.0


async def discover_eligible_traders(
    db,
    portfolio_id: int,
    max_results: int = 10,
    categories: Optional[List[str]] = None,
    force: bool = False,
) -> Tuple[List[Dict], List[Dict], Dict]:
    """Find new eligible traders not already copied.

    Guarded by a lock (prevents overlapping runs) and cooldown
    (prevents spamming). Results are cached for CACHE_TTL_SECONDS
    unless force=True.

    Args:
        db: Database session.
        portfolio_id: Portfolio ID.
        max_results: Maximum scored results to return (default 10).
        categories: Optional category filter.
        force: Bypass cooldown and cache.

    Returns:
        (eligible_scored, excluded, stats)
    """
    global _last_run_time, _cache, _cache_time

    now = time.time()

    # Serve cached result if fresh
    if not force and _cache is not None and (now - _cache_time) < CACHE_TTL_SECONDS:
        logger.info("Discovery cache hit (%.0fs old)", now - _cache_time)
        return _cache

    # Cooldown check
    if not force and (now - _last_run_time) < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - (now - _last_run_time)
        logger.info("Discovery cooldown active (%.0fs remaining) — returning cached", remaining)
        if _cache is not None:
            return _cache
        # No cache — force run anyway
        logger.info("No cache available — running despite cooldown")

    # Lock check
    if _discovery_lock.locked():
        logger.warning("Discovery already running — returning cached result")
        if _cache is not None:
            return _cache
        logger.info("No cache available — waiting for lock")
        async with _discovery_lock:
            pass  # previous run completed while we waited
        if _cache is not None:
            return _cache

    async with _discovery_lock:
        # Double-check after acquiring lock (another coroutine may have updated cache)
        if not force and _cache is not None and (time.time() - _cache_time) < CACHE_TTL_SECONDS:
            logger.info("Discovery cache refreshed while waiting for lock")
            return _cache

        _last_run_time = time.time()
        logger.info("Discovery run starting")

        from backend.database.models import Portfolio
        from backend.services.market_data import get_current_holdings, discover_top_traders

        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
        if not portfolio:
            result = ([], [], {"error": "Portfolio not found"})
            _cache = result
            _cache_time = time.time()
            return result

        holdings = get_current_holdings(db, portfolio_id)
        active_usernames = get_active_usernames(holdings)
        available_balance = portfolio.available_cash or (portfolio.total_value or 0) * 0.1

        # ── 1. Discover candidates from seed data + social API ──
        candidates = await discover_top_traders(categories=categories, min_traders=30)

        # ── 2. Eligibility filter ──
        eligible, excluded = filter_candidates(
            candidates, active_usernames, available_balance,
        )

        # ── 3. Build discovery list ──
        category = categories[0] if categories and len(categories) == 1 else None
        discovery = build_discovery_list(eligible, active_usernames, category=category)

        # ── 4. Smart fallback ──
        if len(discovery) < 3:
            logger.info("Discovery: only %d eligible — widening search", len(discovery))
            discovery = widen_search(eligible, active_usernames, category=category)

        # ── 5. Score ──
        scored = rank_candidates(holdings, discovery, top_n=max_results)

        # ── 6. Stats and logging ──
        enrichment_scanned = getattr(candidates, "_enrich_scanned", len(candidates))
        stats = {
            "total_scanned": enrichment_scanned,
            "eligible": len(scored),
            "excluded": len(excluded),
            "active_traders": len(active_usernames),
            "candidate_pool_size": len(candidates),
            "category": category or "all",
        }

        log_discovery_summary(
            scanned_count=enrichment_scanned,
            eligible_count=len(scored),
            excluded_count=len(excluded),
            active_count=len(active_usernames),
            top_scores=scored[:5],
            category_used=category,
        )

        result = (scored, excluded, stats)
        _cache = result
        _cache_time = time.time()
        logger.info("Discovery run complete — %d eligible, %d excluded", len(scored), len(excluded))
        return result
