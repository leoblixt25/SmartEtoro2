"""
Discovery Engine — manages new trader candidates with category support.

This module:
  1. Receives eligibility-filtered candidates and active portfolio
  2. Ensures ZERO overlap between discovery and active traders
  3. Supports category-based filtering for targeted discovery
  4. Provides smart fallback when too few traders are eligible
  5. Produces detailed logs: scanned count, eligible, rejections, top scores
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────
MIN_ELIGIBLE_TARGET = 3
"""Minimum eligible traders we want before widening search."""

SCORE_THRESHOLD_FALLBACK = 30
"""Score threshold to lower when widening (any score > 0 is accepted)."""


def build_discovery_list(
    eligible_candidates: List[Dict],
    active_usernames: set,
    category: Optional[str] = None,
) -> List[Dict]:
    """Build discovery list of genuinely NEW eligible traders.

    Enforces strict separation:
      - No trader in the active portfolio may appear here.
      - If one does, it's filtered out with a warning.

    Args:
        eligible_candidates: Traders that passed eligibility_filter.
        active_usernames: Set of lowercased active trader usernames.
        category: Optional category filter (e.g. "balanced", "tech_focused").

    Returns:
        List of discovery-only trader dicts, ready for scoring.
    """
    discovery = []
    overlaps = 0
    filtered_by_category = 0
    rejection_reasons: Dict[str, int] = {}

    for t in eligible_candidates:
        username = t.get("username", "")
        if username.lower() in active_usernames:
            overlaps += 1
            continue

        # Category filter
        if category:
            trader_categories = t.get("categories", [])
            if category not in trader_categories and trader_categories:
                filtered_by_category += 1
                rejection_reasons["wrong_category"] = rejection_reasons.get("wrong_category", 0) + 1
                continue

        discovery.append(t)

    # ── Logging ──
    if overlaps:
        logger.info(
            "Discovery: %d overlapping trader(s) excluded from eligibility list",
            overlaps,
        )

    if filtered_by_category:
        logger.info(
            "Discovery: %d traders filtered by category '%s'",
            filtered_by_category, category or "all",
        )

    if rejection_reasons:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(rejection_reasons.items()))
        logger.info("Discovery rejections: %s", detail)

    # ── Cross-check — zero overlap assertion ──
    discovery_usernames = {t.get("username", "").lower() for t in discovery if t.get("username")}
    common = discovery_usernames & active_usernames
    if common:
        logger.error(
            "CRITICAL: Discovery still contains active traders: %s — "
            "eligibility filter is buggy",
            common,
        )

    # ── Summary log ──
    total_input = len(eligible_candidates)
    excluded_count = overlaps + filtered_by_category
    logger.info(
        "Discovery: %d new eligible candidates (input=%d, excluded=%d: "
        "overlap=%d, category=%d)",
        len(discovery), total_input, excluded_count, overlaps, filtered_by_category,
    )

    return discovery


def widen_search(
    eligible_candidates: List[Dict],
    active_usernames: set,
    min_target: int = MIN_ELIGIBLE_TARGET,
    category: Optional[str] = None,
) -> List[Dict]:
    """Widen the search when too few eligible traders are found.

    Strategies (applied in order until target met):
      1. Remove category filter (include all categories)
      2. Include traders that would normally be excluded by score threshold

    Returns:
        Expanded discovery list, never less than the original discovery.

    Note: This does NOT re-introduce already-copied traders or traders
    that failed hard eligibility checks (budget, risk, copyability).
    """
    # Strategy 1: Remove category filter
    if category:
        logger.info(
            "Widen: removing category filter '%s' to expand candidate pool",
            category,
        )
        widened = build_discovery_list(eligible_candidates, active_usernames, category=None)
        if len(widened) >= min_target:
            logger.info("Widen: category removal yielded %d candidates", len(widened))
            return widened
        # Use widened as base and continue
    else:
        widened = build_discovery_list(eligible_candidates, active_usernames, category=None)

    # If still not enough, log what we have
    if len(widened) < min_target:
        logger.warning(
            "Widen: only %d eligible traders after widening (target %d) — "
            "insufficient candidates from current scan",
            len(widened), min_target,
        )

    return widened


def log_discovery_summary(
    scanned_count: int,
    eligible_count: int,
    excluded_count: int,
    active_count: int,
    top_scores: List[Dict],
    category_used: Optional[str] = None,
) -> None:
    """Log a detailed summary of the discovery run."""
    lines = [
        f"Discovery Summary:",
        f"  Scanned: {scanned_count}",
        f"  Active traders: {active_count}",
        f"  Eligible: {eligible_count}",
        f"  Excluded: {excluded_count}",
    ]
    if category_used:
        lines.append(f"  Category: {category_used}")
    if top_scores:
        lines.append("  Top scores:")
        for i, s in enumerate(top_scores[:5], 1):
            username = s.get("username", "?")
            score = s.get("score", 0)
            risk = s.get("risk_score", "?")
            ret = s.get("total_return_pct", "?")
            lines.append(f"    {i}. {username} — score={score}, risk={risk}, return={ret}%")

    logger.info("\n".join(lines))
