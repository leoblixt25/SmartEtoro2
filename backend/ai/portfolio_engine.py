"""
Portfolio Engine — analyzes active traders only.

This module has NO discovery logic, NO scoring, NO recommendations.
It analyzes current holdings: allocation, diversification, risk concentration.

Active traders and discovery/new traders are kept strictly separate.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def analyze_portfolio(
    holdings: List[Dict],
    total_value: float = 0.0,
    available_cash: float = 0.0,
) -> Dict:
    """Analyze the active portfolio of copied traders.

    Args:
        holdings: List of current active CopiedTrader dicts.
        total_value: Portfolio total equity.
        available_cash: Uninvested cash.

    Returns:
        Dict with analysis results:
          - total_traders: count
          - total_value: portfolio equity
          - available_cash: uninvested cash
          - total_allocated: sum of allocated_amount
          - allocation_map: {username: allocation_pct}
          - concentration_risk: True if any single trader > 40%
          - under_diversified: True if < 3 traders
          - avg_score: average final_score of holdings
          - weakest: lowest-scoring holding (or None)
          - holdings_detail: each trader's key metrics
    """
    traders = []
    allocation_total = 0.0
    scores = []

    for h in holdings:
        ap = h.get("allocation_pct", 0.0) or 0.0
        allocation_total += ap
        score = h.get("final_score", 0) or h.get("score", 0) or 0
        scores.append(score)
        traders.append({
            "username": h.get("username", "?"),
            "allocation_pct": round(ap, 2),
            "allocated_amount": h.get("allocated_amount", 0) or 0,
            "total_return_pct": h.get("total_return_pct", 0.0) or 0.0,
            "risk_score": h.get("risk_score"),
            "final_score": score,
            "max_drawdown": h.get("max_drawdown", 0.0) or 0.0,
            "volatility": h.get("volatility", 0.0) or 0.0,
        })

    # Sort by allocation descending
    traders.sort(key=lambda x: x["allocation_pct"], reverse=True)

    # Concentration risk: any single trader > 40% of total
    max_allocation = max((t["allocation_pct"] for t in traders), default=0.0)
    concentration_risk = max_allocation > 40.0

    # Diversification
    trader_count = len(traders)
    under_diversified = trader_count < 3

    # Weakest holding (lowest score)
    traders_by_score = sorted(traders, key=lambda x: x["final_score"])
    weakest = traders_by_score[0] if traders_by_score else None
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    result = {
        "total_traders": trader_count,
        "total_value": total_value,
        "available_cash": available_cash,
        "total_allocated_pct": round(allocation_total, 2),
        "allocation_map": {t["username"]: t["allocation_pct"] for t in traders},
        "concentration_risk": concentration_risk,
        "under_diversified": under_diversified,
        "avg_score": avg_score,
        "weakest": weakest,
        "holdings_detail": traders,
    }

    logger.info(
        "Portfolio: %d traders, value=%.2f, cash=%.2f, "
        "allocated=%.1f%%, diversified=%s, concentration_risk=%s",
        trader_count, total_value, available_cash,
        allocation_total, not under_diversified, concentration_risk,
    )

    return result


def get_active_usernames(holdings: List[Dict]) -> set:
    """Extract lowercased usernames from active holdings list."""
    return {h.get("username", "").lower() for h in holdings if h.get("username")}
