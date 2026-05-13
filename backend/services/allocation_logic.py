"""
Equal-Weight Top-3 Allocation Logic
────────────────────────────────────────────────────────────────────
Transitions the portfolio from a 1‑trader heavy position to an
automated Equal‑Weight Top‑3 Growth Portfolio.

Rule:
  - Score all current holdings and discovery candidates.
  - Pick the top 3 scorers (regardless of source).
  - Assign each exactly Total_Equity / 3 = 33.3%.

This module is dependency‑free — it only needs a sorted list of
scored traders.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TARGET_COUNT = 3
TARGET_ALLOCATION_PCT = round(100.0 / TARGET_COUNT, 1)  # 33.3


def calculate_equal_weight_target(
    scored_top3: List[Dict],
    total_equity: float,
) -> Dict:
    """Build a target allocation dict for the top 3 scored traders.

    Args:
        scored_top3: Exactly 3 entries from the scoring engine, each
                     containing at least {'username', 'score', 'source'}.
        total_equity: Total portfolio value in USD.

    Returns:
        Dict with:
          target_portfolio: list of {'username', 'allocation_pct', 'reasoning'}
          target_value_per_trader: USD amount per trader
          warnings: list of any constraint messages
    """
    target_value = round(total_equity / TARGET_COUNT, 2)
    warnings: List[str] = []

    target_portfolio = []
    for t in scored_top3:
        score = t.get("final_score") or t.get("score", 0)
        target_portfolio.append({
            "username": t["username"],
            "allocation_pct": TARGET_ALLOCATION_PCT,
            "reasoning": (
                f"Equal-weight target (score {score}/100, "
                f"{t.get('source', 'current')})"
            ),
        })

    logger.info(
        f"Equal‑weight target: {[a['username'] for a in target_portfolio]} "
        f"at {TARGET_ALLOCATION_PCT}% each (${target_value:,.2f})"
    )

    return {
        "target_portfolio": target_portfolio,
        "target_value_per_trader": target_value,
        "warnings": warnings,
    }
