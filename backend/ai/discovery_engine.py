"""
Discovery Engine — manages new trader candidates only.

This module receives eligibility-filtered candidates and ensures
ZERO overlap with the active portfolio before handing off to scoring.

Hard assertion: no trader in discovery matches any active trader.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def build_discovery_list(
    eligible_candidates: List[Dict],
    active_usernames: set,
) -> List[Dict]:
    """Build discovery list of genuinely NEW eligible traders.

    Enforces strict separation:
      - No trader in the active portfolio may appear here.
      - If one does, it's filtered out with a warning.

    Args:
        eligible_candidates: Traders that passed eligibility_filter.
        active_usernames: Set of lowercased active trader usernames.

    Returns:
        List of discovery-only trader dicts, ready for scoring.
    """
    discovery = []
    overlaps = 0

    for t in eligible_candidates:
        username = t.get("username", "")
        if username.lower() in active_usernames:
            overlaps += 1
            logger.warning(
                "Discovery OVERLAP: %s found in both eligible and active — excluding",
                username,
            )
        else:
            discovery.append(t)

    if overlaps:
        logger.warning(
            "Discovery separation: %d overlapping trader(s) removed — "
            "eligibility filter should have caught these",
            overlaps,
        )

    # Hard assertion: zero overlap
    discovery_usernames = {t.get("username", "").lower() for t in discovery if t.get("username")}
    if discovery_usernames & active_usernames:
        # This should never happen if eligibility_filter works correctly
        common = discovery_usernames & active_usernames
        logger.error(
            "CRITICAL: Discovery still contains active traders: %s — "
            "eligibility filter is buggy",
            common,
        )

    logger.info(
        "Discovery: %d new eligible candidates (excluded %d overlaps)",
        len(discovery), overlaps,
    )

    return discovery
