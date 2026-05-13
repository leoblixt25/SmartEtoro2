"""
Eligibility Engine — hard filter layer applied BEFORE scoring.

Rule: A trader is either eligible or excluded. No partial states.
Excluded traders never reach scoring, ranking, or recommendations.
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def is_already_copied(username: str, holdings_usernames: set) -> bool:
    """Case-insensitive check if a trader is already in the active portfolio."""
    return username.lower() in holdings_usernames


def passes_budget(min_copy_amount: float, available_balance: float) -> Tuple[bool, Optional[str]]:
    """Check if the trader's minimum copy amount is within budget."""
    min_copy = min_copy_amount or 200.0
    if min_copy > available_balance:
        return False, f"insufficient_capital (min=${min_copy:.0f}, available=${available_balance:.0f})"
    return True, None


def has_reliable_data(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Check if the trader has trustworthy performance data.

    Rules:
      - tradeinfo source (confidence 1.0) is always authoritative
      - Other sources require confidence >= 0.8
      - Zero return from a low-confidence source is rejected
    """
    source = trader.get("source", "unknown")
    confidence = trader.get("confidence", 0.0)
    total_return = trader.get("total_return_pct", 0.0) or 0.0

    if source == "tradeinfo" or confidence >= 1.0:
        return True, None

    if total_return == 0.0 and confidence < 1.0:
        return False, f"no_return_data (source={source}, confidence={confidence})"

    if confidence < 0.8:
        return False, f"low_confidence (source={source}, confidence={confidence})"

    # Must have at least one non-zero return metric
    has_return = any(
        (trader.get(k) or 0) != 0
        for k in ("total_return_pct", "avg_monthly_return", "avg_return", "return_12m", "return_6m")
    )
    if not has_return:
        return False, f"no_return_metrics (source={source})"

    return True, None


def passes_risk(trader: Dict, max_risk: float = 9.0) -> Tuple[bool, Optional[str]]:
    """Check risk score is within acceptable range."""
    risk = trader.get("risk_score", 5.0) or 5.0
    if risk > max_risk:
        return False, f"risk_score {risk:.1f} exceeds {max_risk:.0f}"
    return True, None


def is_copy_available(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Check if the trader is open for copying and not restricted."""
    is_copiable = trader.get("is_copiable", True)
    if not is_copiable:
        return False, "copy_not_available"
    return True, None


def filter_candidates(
    candidates: List[Dict],
    holdings_usernames: set,
    available_balance: float,
    max_risk: float = 9.0,
) -> Tuple[List[Dict], List[Dict]]:
    """Hard filter layer — apply ALL eligibility checks before scoring.

    A trader is eligible ONLY if all checks pass:
      - Not already copied
      - Trader is open for copying (is_copiable)
      - min_copy_amount <= available_balance
      - risk_score <= max_risk
      - Has trustworthy return data (non-zero from reliable source)

    Args:
        candidates: Raw trader dicts from discovery.
        holdings_usernames: Set of lowercased usernames in active portfolio.
        available_balance: Cash available for new copies.
        max_risk: Maximum acceptable risk score (default 9.0).

    Returns:
        (eligible, excluded) where excluded has 'exclusion_reasons' list.
    """
    eligible = []
    excluded = []

    for t in candidates:
        reasons = []
        username = t.get("username", "?")

        # 1. Already copied
        if is_already_copied(username, holdings_usernames):
            reasons.append("already_copied")

        # 2. Copy available
        ok, reason = is_copy_available(t)
        if not ok:
            reasons.append(reason)

        # 3. Budget check
        min_copy = t.get("min_copy_amount", 200.0) or 200.0
        ok, reason = passes_budget(min_copy, available_balance)
        if not ok:
            reasons.append(reason)

        # 4. Risk check
        ok, reason = passes_risk(t, max_risk)
        if not ok:
            reasons.append(reason)

        # 5. Data reliability check
        ok, reason = has_reliable_data(t)
        if not ok:
            reasons.append(reason)

        if reasons:
            excluded.append({**t, "exclusion_reasons": reasons})
        else:
            eligible.append(t)

    # Log summary
    if excluded:
        by_reason: Dict[str, int] = {}
        for e in excluded:
            for r in (e.get("exclusion_reasons") or []):
                key = r.split("(")[0].strip()
                by_reason[key] = by_reason.get(key, 0) + 1
        detail = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
        logger.info(
            "Eligibility: %d eligible, %d excluded (%s)",
            len(eligible), len(excluded), detail,
        )

    return eligible, excluded
