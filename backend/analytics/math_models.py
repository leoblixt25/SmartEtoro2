"""Shared mathematical utilities for portfolio and trader analytics.

Provides consistent math functions used across the analytics layer.
All functions are pure (no side effects, no I/O).
"""

import math
from typing import List


def sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02) -> float:
    """Compute Sharpe-like ratio from a list of periodic returns.

    Uses population standard deviation (ddof=0) for consistency.
    If insufficient data, returns 0.0.
    """
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    variance = sum((r - avg) ** 2 for r in returns) / len(returns)
    if variance == 0:
        return 0.0
    std = math.sqrt(variance)
    excess = avg - risk_free_rate / 12  # convert annual risk-free to monthly
    return excess / std if std > 0 else 0.0


def max_drawdown_from_returns(returns: List[float]) -> float:
    """Calculate maximum drawdown from a sequence of periodic returns.

    Returns the max drawdown as a positive percentage (e.g., 15.0 for 15%).
    Returns 0.0 if data is insufficient or no drawdown occurred.
    """
    if not returns:
        return 0.0
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cumulative *= 1 + r / 100
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


def consistency_score(returns: List[float]) -> float:
    """Calculate consistency of returns. Higher is more consistent.

    Uses the ratio of positive months to total months, adjusted for
    return magnitude consistency. Range: 0-100.
    """
    if not returns:
        return 0.0
    positive_ratio = sum(1 for r in returns if r > 0) / len(returns)
    # Magnitude consistency: low std of returns means consistent magnitude
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns) if len(returns) > 1 else 0
    std = math.sqrt(variance)
    # Normalize magnitude consistency: std of 0 → 100, std of 20 → 0
    magnitude_score = max(0, 100 - std * 5) if std > 0 else 100

    return positive_ratio * 50 + magnitude_score * 0.5


def win_rate(returns: List[float]) -> float:
    """Calculate the percentage of positive returns."""
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns) * 100


def annualized_return(monthly_returns: List[float]) -> float:
    """Convert average monthly return to annualized return."""
    if not monthly_returns:
        return 0.0
    avg_monthly = sum(monthly_returns) / len(monthly_returns)
    return (1 + avg_monthly / 100) ** 12 - 1
