"""Trader filtering and constraint logic for the scout.

Applies hard constraints before scoring to eliminate traders that are
unsuitable for copying. All filters are deterministic.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Default seed traders for fallback ───────────────────────────────
DEFAULT_SEED_TRADERS = [
    "JeppeKirkBonde",
    "CPHequities",
    "Jaynemesis",
]

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
