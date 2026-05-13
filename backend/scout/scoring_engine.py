"""Weighted mathematical scoring engine for trader evaluation.

Scoring is 100% deterministic — no AI involved. The final score is a
weighted combination of 5 categories:

  Category               Weight    What it measures
  ─────────────────────  ───────   ───────────────────────────────
  Performance Score      30%       ROI consistency, monthly profitability, long-term returns
  Risk Score             25%       Drawdown, volatility, risk score, leverage behavior
  Stability Score        20%       Consistency, trade frequency, survival rate
  Market Behavior        15%       Overtrading detection, panic trading, irrational spikes
  Copy Suitability       10%       Capital efficiency, copy slippage, realistic execution

Final score range: 0 - 100, higher is better.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────

WEIGHT_PERFORMANCE = 0.30
WEIGHT_RISK = 0.25
WEIGHT_STABILITY = 0.20
WEIGHT_MARKET_BEHAVIOR = 0.15
WEIGHT_COPY_SUITABILITY = 0.10

PENALTY_RISK_HIGH = 30    # subtract 30 pts if risk > 7
PENALTY_DRAWDOWN_HIGH = 20  # subtract 20 pts if drawdown > 25%
PENALTY_LOW_VOLUME = 10   # subtract 10 pts if very few trades

MAX_SCORE = 100.0
MIN_12M_RETURN_FLOOR = -50.0  # clamp to prevent extreme negatives


# ── Category Scorers ────────────────────────────────────────────────

def performance_score(trader: Dict) -> float:
    """Evaluate past returns and profitability. Range: 0-100."""
    r12 = trader.get("total_return_pct", 0.0) or 0.0
    r6 = trader.get("return_6m", r12 * 0.4) or 0.0
    monthly = trader.get("avg_monthly_return", 0.0) or 0.0

    r12_clamped = max(MIN_12M_RETURN_FLOOR, min(100, r12))
    r6_clamped = max(MIN_12M_RETURN_FLOOR, min(100, r6))

    # 12M return: 0% → 0 pts, 20% → 60 pts, 40%+ → 100 pts
    r12_score = min(100, max(0, r12_clamped * 3.0))
    # 6M return: 0% → 0 pts, 10% → 50 pts, 20%+ → 100 pts
    r6_score = min(100, max(0, r6_clamped * 5.0))
    # Monthly consistency bonus: positive monthly return adds up to 20pts
    monthly_bonus = min(20, monthly * 10) if monthly > 0 else 0

    return r12_score * 0.5 + r6_score * 0.3 + monthly_bonus


def risk_score(trader: Dict) -> float:
    """Evaluate risk metrics. Lower raw risk → higher score. Range: 0-100."""
    raw_risk = trader.get("risk_score", 5.0) or 5.0
    dd = trader.get("max_drawdown", 0.0) or 0.0
    vol = trader.get("volatility", 0.0) or 0.0

    # Risk score: 1 → 100, 5 → 60, 10 → 10
    risk_component = max(0, 100 - (raw_risk - 1) * 10)
    # Drawdown: 0% → 100, 10% → 60, 25% → 0
    dd_component = max(0, 100 - dd * 4)
    # Volatility: 0% → 100, 5% → 75, 20% → 0
    vol_component = max(0, 100 - vol * 5)

    return risk_component * 0.4 + dd_component * 0.35 + vol_component * 0.25


def stability_score(trader: Dict) -> float:
    """Evaluate consistency and sustainability. Range: 0-100."""
    consistency = trader.get("consistency_score", 50.0) or 50.0
    freq = trader.get("trade_frequency", 0.0) or 0.0
    sharpe = trader.get("sharpe_score", 0.0) or 0.0

    # Consistency: raw score (expected 0-100)
    cons_component = min(100, max(0, consistency))
    # Trade frequency: 1-5 trades/week ideal
    freq_component = 100 if 1 <= freq <= 5 else max(0, 80 - abs(freq - 3) * 15)
    # Sharpe: 0 → 0, 1 → 50, 2+ → 100
    sharpe_component = min(100, max(0, sharpe * 50))

    return cons_component * 0.4 + freq_component * 0.3 + sharpe_component * 0.3


def market_behavior_score(trader: Dict) -> float:
    """Detect unhealthy trading patterns. Range: 0-100."""
    dd = trader.get("max_drawdown", 0.0) or 0.0
    vol = trader.get("volatility", 0.0) or 0.0
    risk = trader.get("risk_score", 5.0) or 5.0
    freq = trader.get("trade_frequency", 0.0) or 0.0

    # Penalize extreme drawdown (panic indicator)
    dd_penalty = 0
    if dd > 20:
        dd_penalty = 30
    elif dd > 15:
        dd_penalty = 15

    # Penalize high volatility (overtrading / erratic behavior)
    vol_penalty = 0
    if vol > 15:
        vol_penalty = 25
    elif vol > 10:
        vol_penalty = 10

    # Penalize very high risk score
    risk_penalty = 0
    if risk > 8:
        risk_penalty = 20
    elif risk > 7:
        risk_penalty = 10

    # Penalize excessive trading (likely churn/scalping)
    freq_penalty = 0
    if freq > 20:
        freq_penalty = 20
    elif freq > 10:
        freq_penalty = 10

    raw = 100 - dd_penalty - vol_penalty - risk_penalty - freq_penalty
    return max(0, raw)


def copy_suitability_score(trader: Dict) -> float:
    """Evaluate how realistic it is to copy this trader. Range: 0-100."""
    allocation = trader.get("allocation_pct", 0.0) or 0.0
    total_return = trader.get("total_return_pct", 0.0) or 0.0

    # Very high allocation → less room for copy gains
    alloc_penalty = 0
    if allocation > 50:
        alloc_penalty = 25
    elif allocation > 30:
        alloc_penalty = 10

    # Positive return bonus
    return_bonus = min(20, total_return * 0.5) if total_return > 0 else 0

    raw = 80 - alloc_penalty + return_bonus
    return max(0, min(100, raw))


# ── Composite Score ─────────────────────────────────────────────────

def calculate_weighted_score(trader: Dict) -> Dict:
    """Compute the full weighted score breakdown for a single trader.

    Returns a dict with individual category scores and the final score.
    """
    perf = performance_score(trader)
    risk = risk_score(trader)
    stab = stability_score(trader)
    market = market_behavior_score(trader)
    copy = copy_suitability_score(trader)

    # Apply penalties for extreme risk/drawdown (legacy compatibility)
    raw_risk = trader.get("risk_score", 5.0) or 5.0
    dd = trader.get("max_drawdown", 0.0) or 0.0
    penalty = 0
    if raw_risk > 7:
        penalty += PENALTY_RISK_HIGH
    if dd > 25:
        penalty += PENALTY_DRAWDOWN_HIGH

    final = (
        perf * WEIGHT_PERFORMANCE
        + risk * WEIGHT_RISK
        + stab * WEIGHT_STABILITY
        + market * WEIGHT_MARKET_BEHAVIOR
        + copy * WEIGHT_COPY_SUITABILITY
    ) - penalty

    final = max(0, min(100, final))

    return {
        "username": trader.get("username", "unknown"),
        "trader_id": trader.get("trader_id", ""),
        "total_return_pct": trader.get("total_return_pct", 0.0),
        "risk_score": trader.get("risk_score", 5.0),
        "max_drawdown": trader.get("max_drawdown", 0.0),
        "volatility": trader.get("volatility", 0.0),
        "performance_score": round(perf, 1),
        "risk_score_category": round(risk, 1),
        "stability_score": round(stab, 1),
        "market_behavior_score": round(market, 1),
        "copy_suitability_score": round(copy, 1),
        "penalty": round(penalty, 1),
        "final_score": round(final, 1),
    }


def rank_traders(traders: List[Dict], top_n: int = 3) -> List[Dict]:
    """Score and rank a list of traders, returning the top N.

    Args:
        traders: List of trader dicts with at minimum 'username' and metrics.
        top_n: Number of top results to return (default 3).

    Returns:
        Ranked list of scored trader dicts, highest final_score first.
    """
    if not traders:
        return []

    scored = [calculate_weighted_score(t) for t in traders]
    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:top_n]


def generate_scout_report(holdings: List[Dict], candidates: List[Dict]) -> Dict:
    """Generate a full scout report comparing current holdings vs discovery candidates.

    Args:
        holdings: List of current copied trader dicts.
        candidates: List of discovered trader candidates.

    Returns:
        Dict with 'weakest' (lowest-scoring holding), 'top_swaps' (best candidates),
        'avg_score' (average of holdings), and 'holdings_ranked' (all holdings scored).
    """
    holdings_scored = rank_traders(holdings, top_n=len(holdings)) if holdings else []
    candidates_scored = rank_traders(candidates, top_n=len(candidates)) if candidates else []

    weakest = holdings_scored[-1] if holdings_scored else None
    top_swaps = candidates_scored[:3] if candidates_scored else []
    avg_score = (
        sum(h["final_score"] for h in holdings_scored) / len(holdings_scored)
        if holdings_scored
        else 0
    )

    return {
        "weakest": weakest,
        "top_swaps": top_swaps,
        "avg_score": round(avg_score, 1),
        "holdings_ranked": holdings_scored,
        "candidates_ranked": candidates_scored,
        "total_holdings": len(holdings),
        "total_candidates": len(candidates),
    }
