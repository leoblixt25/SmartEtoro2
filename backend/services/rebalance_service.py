"""
Rebalance Order Calculator
────────────────────────────────────────────────────────────────────
Calculates the exact buy/sell orders to transition from current
holdings to target allocations, respecting eToro's $200 minimum
position size.
"""

from __future__ import annotations
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

MIN_POSITION_SIZE = 200.0


def calculate_rebalance_orders(
    total_portfolio_value: float,
    current_positions: List[Dict],
    target_allocations: List[Dict],
) -> Dict:
    """Produce executable rebalance orders respecting eToro constraints.

    Args:
        total_portfolio_value: Current total portfolio value in USD.
        current_positions: List of dicts with keys ['username', 'current_value'].
        target_allocations: List of dicts with keys ['username', 'allocation_pct'].

    Returns:
        Dict with:
          - orders: List of {'username', 'action', 'amount'}
          - skipped: List of usernames below the $200 minimum
          - total_required_cash: Float
          - warnings: List[str]
    """
    orders: List[Dict] = []
    skipped: List[str] = []
    warnings: List[str] = []

    current_map: Dict[str, float] = {}
    for pos in current_positions:
        current_map[pos["username"]] = pos.get("current_value", 0.0)

    total_target_pct = sum(a.get("allocation_pct", 0) for a in target_allocations)
    if abs(total_target_pct - 100.0) > 0.5:
        logger.warning(f"Target allocations sum to {total_target_pct}%, not 100%")

    for target in target_allocations:
        username = target["username"]
        target_pct = target.get("allocation_pct", 0)
        target_value = total_portfolio_value * (target_pct / 100.0)
        current_value = current_map.pop(username, 0.0)
        diff = round(target_value - current_value, 2)

        if abs(diff) < 0.01:
            orders.append({"username": username, "action": "hold", "amount": current_value})
            continue

        if diff > 0 and target_value < MIN_POSITION_SIZE:
            skipped.append(username)
            warnings.append(
                f"Cannot allocate ${target_value:.2f} to {username} — "
                f"below ${MIN_POSITION_SIZE:.0f} minimum. "
                f"Consider increasing total allocation or skipping."
            )
            continue

        if diff > 0:
            orders.append({"username": username, "action": "buy", "amount": round(diff, 2)})
        else:
            orders.append({"username": username, "action": "sell", "amount": round(abs(diff), 2)})

    for username, value in current_map.items():
        if value > 0:
            orders.append({"username": username, "action": "sell", "amount": round(value, 2)})

    buys = sum(o["amount"] for o in orders if o["action"] == "buy")
    sells = sum(o["amount"] for o in orders if o["action"] == "sell")
    total_required_cash = round(buys - sells, 2) if buys > sells else 0.0

    return {
        "orders": orders,
        "skipped": skipped,
        "total_required_cash": total_required_cash,
        "warnings": warnings,
    }
