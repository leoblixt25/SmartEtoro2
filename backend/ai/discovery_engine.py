"""
Discovery Engine — manages new trader candidates.

Ensures ZERO overlap between discovery and active traders.
Supports category-based filtering. Produces detailed logs.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def build_discovery_list(
    eligible_candidates: List[Dict],
    active_usernames: set,
    category: Optional[str] = None,
) -> List[Dict]:
    """Build discovery list of genuinely NEW eligible traders.

    Enforces strict separation between active portfolio and new candidates.

    Args:
        eligible_candidates: Traders that passed eligibility_filter.
        active_usernames: Set of lowercased active trader usernames.
        category: Optional category filter.

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

        if category:
            trader_categories = t.get("categories", [])
            if category not in trader_categories and trader_categories:
                filtered_by_category += 1
                rejection_reasons["wrong_category"] = rejection_reasons.get("wrong_category", 0) + 1
                continue

        discovery.append(t)

    if overlaps:
        logger.info("Discovery: %d overlapping trader(s) excluded", overlaps)
    if filtered_by_category:
        logger.info("Discovery: %d traders filtered by category '%s'", filtered_by_category, category or "all")

    discovery_usernames = {t.get("username", "").lower() for t in discovery if t.get("username")}
    common = discovery_usernames & active_usernames
    if common:
        logger.error("CRITICAL: Discovery still contains active traders: %s", common)

    total_input = len(eligible_candidates)
    excluded_count = overlaps + filtered_by_category
    logger.info(
        "Discovery: %d new eligible candidates (input=%d, excluded=%d)",
        len(discovery), total_input, excluded_count,
    )

    return discovery


def widen_search(
    eligible_candidates: List[Dict],
    active_usernames: set,
    min_target: int = 3,
    category: Optional[str] = None,
) -> List[Dict]:
    """Widen search when too few eligible traders found.

    Removes category filter only — NEVER lowers quality thresholds
    or re-introduces traders that failed hard eligibility checks.

    Returns:
        Expanded discovery list.
    """
    if category:
        logger.info("Widen: removing category filter '%s'", category)
        widened = build_discovery_list(eligible_candidates, active_usernames, category=None)
        if len(widened) >= min_target:
            logger.info("Widen: category removal yielded %d candidates", len(widened))
            return widened
    else:
        widened = build_discovery_list(eligible_candidates, active_usernames, category=None)

    if len(widened) < min_target:
        logger.warning(
            "Widen: only %d eligible traders after widening (target %d) — "
            "insufficient real traders found",
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
    """Log detailed summary of the discovery run."""
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
