"""
Eligibility Engine — hard filter layer applied BEFORE scoring.

Rule: A trader is either eligible or excluded. No partial states.
Excluded traders never reach scoring, ranking, or recommendations.

Strict rules:
  - Empty traders (no holdings, no positions, no data) are rejected
  - Unknown min_copy_amount is rejected (no default to $200)
  - Fallback/default sources with no real data are rejected
  - Only traders with verified substance + reliable data are eligible
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def is_already_copied(username: str, holdings_usernames: set) -> bool:
    """Case-insensitive check if a trader is already in the active portfolio."""
    return username.lower() in holdings_usernames


def passes_budget(min_copy_amount: float, available_balance: float) -> Tuple[bool, Optional[str]]:
    """Check if the trader's minimum copy amount is within budget.

    Strict: does NOT default to $200. If min_copy_amount is unknown
    (None/0/missing), the trader is rejected with missing_min_copy.
    """
    if not min_copy_amount:
        return False, "missing_min_copy"
    if min_copy_amount > available_balance:
        return False, f"insufficient_capital (min=${min_copy_amount:.0f}, available=${available_balance:.0f})"
    return True, None


def has_substance(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Check if a trader has real substance beyond fake/fallback data.

    Rejects traders with:
      - Empty holdings list
      - Empty positions list
      - Zero portfolio_size
      - Unknown or fallback source
      - No copied positions
      - No valid data at all (combined emptiness)
    """
    reasons = []

    source = trader.get("source", "unknown")
    holdings = trader.get("holdings")
    positions = trader.get("positions")
    portfolio_size = trader.get("portfolio_size")
    copied_positions = trader.get("copied_positions", None)

    # Extract counts from lists or scalars
    holdings_count = len(holdings) if isinstance(holdings, list) else (int(holdings) if isinstance(holdings, (int, float)) else None)
    positions_count = len(positions) if isinstance(positions, list) else (int(positions) if isinstance(positions, (int, float)) else None)

    if holdings_count is not None and holdings_count == 0:
        reasons.append("no_holdings")
    if positions_count is not None and positions_count == 0:
        reasons.append("no_positions")
    if portfolio_size is not None and portfolio_size == 0:
        reasons.append("zero_portfolio_size")
    if copied_positions is not None and copied_positions == 0:
        reasons.append("no_copied_positions")

    # Reject any source with zero return data — no substance
    has_any_return = any(
        (trader.get(k) or 0) != 0
        for k in ("total_return_pct", "avg_monthly_return", "avg_return", "return_12m", "return_6m")
    )
    if not has_any_return:
        reasons.append("no_valid_data")

    # Reject unknown/fallback/default source entirely
    if source in ("fallback", "default", "unknown"):
        reasons.append(f"invalid_source={source}")

    if reasons:
        return False, ", ".join(reasons)
    return True, None


def has_reliable_data(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Check if the trader has trustworthy performance data.

    Rules:
      - tradeinfo source (confidence 1.0) is always authoritative
      - Fallback/default/unknown sources without return data → no_valid_data
      - Other sources require confidence >= 0.8
      - Zero return from a low-confidence source is rejected
    """
    source = trader.get("source", "unknown")
    confidence = trader.get("confidence", 0.0)
    total_return = trader.get("total_return_pct", 0.0) or 0.0

    # Reject any source with no real return data
    has_any_return = any(
        (trader.get(k) or 0) != 0
        for k in ("total_return_pct", "avg_monthly_return", "avg_return", "return_12m", "return_6m")
    )
    if not has_any_return and total_return == 0.0:
        return False, "no_valid_return_data"

    # tradeinfo with non-zero return is authoritative
    if source == "tradeinfo" or confidence >= 1.0:
        return True, None

    if total_return == 0.0 and confidence < 1.0:
        return False, f"no_return_data (source={source}, confidence={confidence})"

    if confidence < 0.8:
        return False, f"low_confidence (source={source}, confidence={confidence})"

    # Must have at least one non-zero return metric
    if not has_any_return:
        return False, f"no_return_metrics (source={source})"

    return True, None


def passes_risk(trader: Dict, max_risk: float = 9.0) -> Tuple[bool, Optional[str]]:
    """Check risk score is within acceptable range."""
    risk = trader.get("risk_score", 5.0) or 5.0
    if risk > max_risk:
        return False, f"risk_score {risk:.1f} exceeds {max_risk:.0f}"
    return True, None


def is_copy_available(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Check if the trader is open for copying and not restricted.

    Checks:
      - is_copiable must be True
      - is_blocked must be False
      - is_paused must be False
      - is_restricted must be False
    """
    is_copiable = trader.get("is_copiable", True)
    is_blocked = trader.get("is_blocked", False)
    is_paused = trader.get("is_paused", False)
    is_restricted = trader.get("is_restricted", False)

    if not is_copiable:
        return False, "copy_not_available"
    if is_blocked:
        return False, "trader_blocked"
    if is_paused:
        return False, "trader_paused"
    if is_restricted:
        return False, "trader_restricted"
    return True, None


def is_real_trader(trader: Dict) -> Tuple[bool, Optional[str]]:
    """Strict pre-filter: only accept traders with verified real eToro stats.

    Auto-reject if:
      - No tradeinfo response (available=False)
      - Empty username
      - Risk score is 0 or default (no data)
      - total_return_pct is None (no performance data)
      - Source is not authoritative tradeinfo (confidence 1.0)
      - Copiers < 50 (only when API provides copiers data)
      - Open positions < 5 (only when API provides positions data)

    Returns:
        (True, None) if trader is real, (False, reason) otherwise.
    """
    available = trader.get("available", False)
    username = trader.get("username", "")
    copiers = trader.get("copiers")
    positions = trader.get("positions_count")
    risk = float(trader.get("risk_score", 0) or 0)
    total_return = trader.get("total_return_pct")
    source = trader.get("source", "unknown")

    if not available:
        return False, "trader_not_found"
    if not username:
        return False, "missing_username"
    if risk <= 0:
        return False, "missing_risk_score"
    if total_return is None:
        return False, "missing_return_data"
    if source != "tradeinfo":
        return False, f"unreliable_source ({source})"
    if copiers is not None and copiers < 50:
        return False, f"insufficient_copiers ({copiers})"
    if positions is not None and positions < 5:
        return False, f"insufficient_positions ({positions})"
    return True, None


def filter_candidates(
    candidates: List[Dict],
    holdings_usernames: set,
    available_balance: float,
    max_risk: float = 9.0,
) -> Tuple[List[Dict], List[Dict]]:
    """Hard filter layer — apply ALL eligibility checks before scoring.

    A trader is eligible ONLY if all checks pass:
      - 0. Verified real eToro trader (has copiers, positions, risk, return)
      - 1. Not already copied
      - 2. Copy available (is_copiable, not blocked/paused/restricted)
      - 3. min_copy_amount is known and <= available_balance
      - 4. risk_score <= max_risk
      - 5. Has real substance (holdings, positions, valid source)
      - 6. Has trustworthy return data (non-zero from reliable source)

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

        # 0. Must be a real eToro trader with verified stats
        ok, reason = is_real_trader(t)
        if not ok:
            reasons.append(reason)

        # 1. Already copied
        if is_already_copied(username, holdings_usernames):
            reasons.append("already_copied")

        # 2. Copy available (is_copiable, not blocked/paused/restricted)
        ok, reason = is_copy_available(t)
        if not ok:
            reasons.append(reason)

        # 3. Budget check (no default — reject unknown min_copy)
        min_copy = t.get("min_copy_amount")
        ok, reason = passes_budget(min_copy, available_balance)
        if not ok:
            reasons.append(reason)

        # 4. Risk check
        ok, reason = passes_risk(t, max_risk)
        if not ok:
            reasons.append(reason)

        # 5. Substance check (holdings, positions, source validity)
        ok, reason = has_substance(t)
        if not ok:
            reasons.append(reason)

        # 6. Data reliability check
        ok, reason = has_reliable_data(t)
        if not ok:
            reasons.append(reason)

        if reasons:
            excluded.append({**t, "exclusion_reasons": reasons})
        else:
            eligible.append(t)

    # Strict per-candidate logging
    for e in excluded:
        reasons_str = ", ".join(e.get("exclusion_reasons", []))
        logger.info(
            "Rejected %s: %s",
            e.get("username", "?"), reasons_str,
        )
    for e in eligible:
        h = e.get("holdings", "?")
        p = e.get("positions", "?")
        logger.info(
            "Eligible %s: holdings=%s positions=%s source=%s min_copy=%s copyable=%s",
            e.get("username", "?"),
            len(h) if isinstance(h, list) else h,
            len(p) if isinstance(p, list) else p,
            e.get("source", "unknown"),
            e.get("min_copy_amount", "?"),
            e.get("is_copiable", "?"),
        )

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
