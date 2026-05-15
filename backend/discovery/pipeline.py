"""Discovery pipeline orchestrator — one job at a time, with cooldown and cache.

The single entry point is `discover_eligible_traders()` (backward compatible).
Internally it:
  1. Checks lock/cache/cooldown (never overlaps)
  2. Fetches portfolio holdings from DB
  3. Discovers candidates via eToro API
  4. Filters for eligibility
  5. Builds discovery list (no overlap with active)
  6. Scores candidates using the typed scoring engine
  7. Caches and returns results
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

from backend.discovery.config import (
    COOLDOWN_SECONDS,
    CACHE_TTL_SECONDS,
    MIN_TRADERS_TARGET,
    DISCOVERY_TOP_N,
    DISCOVERY_SEMAPHORE_MAX,
    ENRICH_CONCURRENCY,
)
from backend.discovery.types import DiscoveryResult, DiscoveryStats
from backend.discovery.score import calculate_growth_score
from backend.utils.safe_log import safe_fmt

logger = logging.getLogger(__name__)

# ── Run guard ────────────────────────────────────────────────────────

_discovery_lock = asyncio.Lock()
_last_run_time = 0.0
_cache: Optional[Tuple[List[Dict], List[Dict], Dict]] = None
_cache_time = 0.0


async def discover_eligible_traders(
    db,
    portfolio_id: int,
    max_results: int = DISCOVERY_TOP_N,
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

    # ── Cache check ───────────────────────────────────────────────
    if not force and _cache is not None and (now - _cache_time) < CACHE_TTL_SECONDS:
        logger.info("Discovery cache hit (%.0fs old)", now - _cache_time)
        return _cache

    # ── Cooldown check ────────────────────────────────────────────
    if not force and (now - _last_run_time) < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - (now - _last_run_time)
        logger.info("Discovery cooldown (%.0fs remaining) — cached result", remaining)
        if _cache is not None:
            return _cache
        logger.info("No cache — running despite cooldown")

    # ── Lock check ────────────────────────────────────────────────
    if _discovery_lock.locked():
        logger.warning("Discovery already running — returning cached")
        if _cache is not None:
            return _cache
        logger.info("No cache — waiting for lock")
        async with _discovery_lock:
            pass
        if _cache is not None:
            return _cache

    async with _discovery_lock:
        # Double-check after lock acquisition
        if not force and _cache is not None and (time.time() - _cache_time) < CACHE_TTL_SECONDS:
            return _cache

        _last_run_time = time.time()
        start_time = time.time()
        logger.info("Discovery pipeline starting (pid=%s portfolio_id=%d)", id(db), portfolio_id)

        try:
            result = await _run_pipeline(db, portfolio_id, max_results, categories)
            result[2]["duration_seconds"] = round(time.time() - start_time, 2)
            _cache = result
            _cache_time = time.time()
            logger.info(
                "Discovery pipeline complete — %d eligible, %d excluded in %.1fs",
                len(result[0]), len(result[1]),
                time.time() - start_time,
            )
            return result
        except Exception as e:
            logger.exception("Discovery pipeline failed: %s", e)
            error_result = ([], [], {"error": str(e), "duration_seconds": round(time.time() - start_time, 2)})
            _cache = error_result
            _cache_time = time.time()
            return error_result


async def _run_pipeline(
    db,
    portfolio_id: int,
    max_results: int,
    categories: Optional[List[str]],
) -> Tuple[List[Dict], List[Dict], Dict]:
    """Internal pipeline execution — no lock/cooldown checks.

    Separated so it can be tested independently.
    """
    from backend.database.models import Portfolio
    from backend.services.market_data import get_current_holdings, discover_top_traders

    # ── 0. Portfolio check ────────────────────────────────────────────
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return [], [], {"error": "Portfolio not found"}

    # ── 1. Current holdings & active traders ─────────────────────────
    holdings = get_current_holdings(db, portfolio_id)
    from backend.ai.portfolio_engine import get_active_usernames
    active_usernames = get_active_usernames(holdings)
    available_balance = portfolio.available_cash or (portfolio.total_value or 0) * 0.1

    # ── 2. Discover candidates ───────────────────────────────────────
    candidates = await discover_top_traders(categories=categories, min_traders=MIN_TRADERS_TARGET)

    # ── 3. Eligibility filter ────────────────────────────────────────
    from backend.ai.eligibility_engine import filter_candidates
    eligible, excluded = filter_candidates(candidates, active_usernames, available_balance)

    # ── 4. Build discovery list ─────────────────────────────────────
    from backend.ai.discovery_engine import build_discovery_list, widen_search, log_discovery_summary
    category = categories[0] if categories and len(categories) == 1 else None
    discovery = build_discovery_list(eligible, active_usernames, category=category)

    if len(discovery) < 3:
        logger.info("Discovery: only %d eligible — widening search", len(discovery))
        discovery = widen_search(eligible, active_usernames, category=category)

    # ── 5. Score ────────────────────────────────────────────────────
    scored = _score_discovery_candidates(holdings, discovery, top_n=max_results)

    # ── 6. Stats ────────────────────────────────────────────────────
    enrichment_scanned = getattr(candidates, "_enrich_scanned", len(candidates)) if hasattr(candidates, "_enrich_scanned") else len(candidates)
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

    # Debug log each scored trader
    for s in scored:
        logger.info(
            "CANDIDATE %s: score=%s/100 final=%s mod=%s source=%s missing=[%s]",
            s.get("username", "?"),
            safe_fmt(s.get("score")),
            safe_fmt(s.get("final_score")),
            safe_fmt(s.get("confidence_mod")),
            s.get("source", "?"),
            ", ".join(str(m) for m in s.get("missing_fields", [])) if s.get("missing_fields") else "none",
        )

    return scored, excluded, stats


def _score_discovery_candidates(
    holdings: List[Dict],
    candidates: List[Dict],
    top_n: int = 10,
) -> List[Dict]:
    """Score discovery candidates using the typed scoring engine.

    Returns top_n candidates sorted by delta (score minus weakest holding).
    """
    from backend.discovery.score import calculate_growth_score, scout_holdings

    # Score holdings to find weakest
    holdings_scored = scout_holdings(holdings)
    weakest_score = holdings_scored["weakest"]["score"] if holdings_scored["weakest"] else 0.0

    # Apply constraints before scoring
    qualified = []
    for c in candidates:
        dd = c.get("max_drawdown")
        tr_days = c.get("track_record_days")
        reasons = []
        if dd is not None and float(dd) > 15:
            reasons.append(f"max_drawdown {float(dd):.1f}% > 15%")
        if tr_days is not None and int(tr_days) > 0 and int(tr_days) < 365:
            reasons.append(f"track_record {int(tr_days)}d < 365d")
        if reasons:
            logger.info("Disqualified %s: %s", c.get("username", "?"), "; ".join(reasons))
            continue
        qualified.append(c)

    rejected = len(candidates) - len(qualified)
    if rejected:
        logger.info("Constraints: %d/%d passed (%d disqualified)", len(qualified), len(candidates), rejected)

    # Score each candidate using the typed engine
    scored = []
    for c in qualified:
        result = calculate_growth_score(c)
        scored.append({
            **c,
            **result,
            "delta": round(result["final_score"] - weakest_score, 1),
        })

    # Filter to only traders above minimum final_score threshold
    from backend.discovery.config import MIN_FINAL_SCORE_FOR_RECOMMENDATION
    qualified_for_recommendation = [s for s in scored if s.get("final_score", 0) >= MIN_FINAL_SCORE_FOR_RECOMMENDATION]

    filtered_out = len(scored) - len(qualified_for_recommendation)
    if filtered_out:
        logger.info(
            "Discovery: %d candidates below final_score=%.0f threshold — excluded from top list",
            filtered_out, MIN_FINAL_SCORE_FOR_RECOMMENDATION,
        )

    # Sort by final_score descending (data quality + raw score combined)
    qualified_for_recommendation.sort(key=lambda x: x["final_score"], reverse=True)
    return qualified_for_recommendation[:top_n]
