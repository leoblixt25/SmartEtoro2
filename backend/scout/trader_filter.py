"""Trader filtering and constraint logic for the scout.

Applies hard constraints before scoring to eliminate traders that are
unsuitable for copying. All filters are deterministic.
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Default seed traders for fallback ───────────────────────────────
DEFAULT_SEED_TRADERS = [
    "JeppeKirkBonde",
    "CPHequities",
    "Jaynemesis",
]


# ── Eligibility Filters (pre-scoring) ──────────────────────────────

def filter_already_copied(candidates: List[Dict], holdings_usernames: set) -> Tuple[List[Dict], List[Dict]]:
    """Split candidates into not-copied (eligible) and already-copied (excluded)."""
    eligible = []
    excluded = []
    for t in candidates:
        username = t.get("username", "")
        if username.lower() in holdings_usernames:
            excluded.append({**t, "exclusion_reason": "already_copied"})
        else:
            eligible.append(t)
    return eligible, excluded


def filter_minimum_capital(candidates: List[Dict], available_balance: float) -> Tuple[List[Dict], List[Dict]]:
    """Split candidates into affordable (eligible) and too-expensive (excluded)."""
    eligible = []
    excluded = []
    for t in candidates:
        min_copy = t.get("min_copy_amount", 200.0) or 200.0
        if min_copy > available_balance:
            excluded.append({
                **t,
                "exclusion_reason": "insufficient_capital",
                "min_copy_amount": min_copy,
                "available_balance": available_balance,
            })
        else:
            eligible.append(t)
    return eligible, excluded


def eligibility_filter(
    candidates: List[Dict],
    holdings_usernames: set,
    available_balance: float,
    max_risk: float = 9.0,
    min_copier_count: int = -1,
) -> Tuple[List[Dict], List[Dict]]:
    """Apply all eligibility checks BEFORE scoring.

    A trader is eligible ONLY if:
      - Not already copied
      - min_copy_amount <= available_balance
      - risk_score <= max_risk
      - Has recent activity (non-zero return data)
      - copier_count > min_copier_count

    Note: min_copier_count defaults to -1 (effectively no filter)
    because the eToro discovery API often sets copiers=0. Set to a
    positive value to require a minimum copier base.

    Returns (eligible, excluded_with_reasons).
    """
    eligible = []
    excluded = []

    for t in candidates:
        reasons = []

        # 1. Already copied
        username = t.get("username", "")
        if username.lower() in holdings_usernames:
            reasons.append("already_copied")

        # 2. Minimum capital
        min_copy = t.get("min_copy_amount", 200.0) or 200.0
        if min_copy > available_balance:
            reasons.append(f"insufficient_capital (min=${min_copy:.0f}, available=${available_balance:.0f})")

        # 3. Risk score cap
        risk = t.get("risk_score", 5.0) or 5.0
        if risk > max_risk:
            reasons.append(f"risk_score {risk:.1f} exceeds {max_risk:.0f}")

        # 4. Recent activity — must have non-zero return data
        has_return = any(
            (t.get(k) or 0) != 0
            for k in ("total_return_pct", "avg_monthly_return", "avg_return", "return_12m", "return_6m")
        )
        if not has_return:
            reasons.append("no_return_data")

        # 5. Copier count threshold (default -1 = no filter)
        copiers = t.get("copiers", 0) or 0
        if min_copier_count >= 0 and copiers <= min_copier_count:
            reasons.append(f"copier_count {copiers} <= {min_copier_count}")

        if reasons:
            excluded.append({**t, "exclusion_reasons": reasons})
        else:
            eligible.append(t)

    return eligible, excluded

# ── Hard Constraints ────────────────────────────────────────────────

def apply_hard_constraints(trader: Dict) -> Optional[str]:
    """Check a trader against hard constraints.

    Args:
        trader: Trader data dict.

    Returns:
        None if the trader passes all constraints, or a string reason
        explaining why the trader was rejected.
    """
    dd = trader.get("max_drawdown", 0.0) or 0.0
    if dd > 25:
        return f"max_drawdown {dd:.1f}% exceeds 25% limit"

    risk = trader.get("risk_score", 5.0) or 5.0
    if risk > 9:
        return f"risk_score {risk:.1f} exceeds 9.0 limit"

    return_pct = trader.get("total_return_pct", 0.0) or 0.0
    if return_pct < -50:
        return f"total_return_pct {return_pct:.1f}% below -50% threshold"

    return None


def filter_traders(traders: List[Dict]) -> List[Dict]:
    """Apply hard constraints and return only passing traders.

    Logs each rejection with the reason.
    """
    passing = []
    for t in traders:
        reason = apply_hard_constraints(t)
        if reason:
            username = t.get("username", "unknown")
            logger.info("Trader %s rejected: %s", username, reason)
        else:
            passing.append(t)
    return passing


# ── Deduplication ───────────────────────────────────────────────────

def deduplicate_traders(traders: List[Dict]) -> List[Dict]:
    """Remove duplicate traders by username (keeps first occurrence)."""
    seen: set = set()
    result = []
    for t in traders:
        uid = t.get("username") or t.get("trader_id")
        if uid and uid not in seen:
            seen.add(uid)
            result.append(t)
    return result


# ── Candidate scoring for display ───────────────────────────────────

def summarize_constraints(trader: Dict) -> List[str]:
    """Return a list of constraint warnings for a trader (non-blocking)."""
    warnings = []
    dd = trader.get("max_drawdown", 0.0) or 0.0
    if dd > 15:
        warnings.append(f"High drawdown ({dd:.1f}%)")
    risk = trader.get("risk_score", 5.0) or 5.0
    if risk > 7:
        warnings.append(f"High risk score ({risk:.1f})")
    vol = trader.get("volatility", 0.0) or 0.0
    if vol > 10:
        warnings.append(f"High volatility ({vol:.1f}%)")
    return warnings
