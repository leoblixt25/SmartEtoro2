"""
Deterministic High-Growth Scoring Engine
────────────────────────────────────────────────────────────────────
Replaces AI-driven /scout with a repeatable, transparent math model.
Every trader gets a score (0-100) using fixed weights and penalties.

Weights:
  12M Return   35%  — long-term track record
  6M Return    25%  — recent momentum
  Risk Score   15%  — lower is better (inverted)
  Max Drawdown 15%  — lower is better (inverted)
  Consistency  10%  — stable monthly performance

Penalties:
  Risk > 7                  → subtract 30 points
  Max Drawdown > 25%        → subtract 20 points
  12M Return < 10%          → score = 0 (growth filter fails)
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# ── Weights ────────────────────────────────────────────────────────
W_12M = 0.35
W_6M = 0.25
W_RISK = 0.15
W_DRAWDOWN = 0.15
W_CONSISTENCY = 0.10

# ── Penalties ──────────────────────────────────────────────────────
PENALTY_RISK_HIGH = 30       # risk > 7
PENALTY_DRAWDOWN_HIGH = 20   # max_drawdown > 25%
GROWTH_FILTER_MIN_12M = 10.0 # if 12M return < 10%, score = 0


def _get_return_12m(trader: dict) -> float:
    """Derive 12‑month return from available fields."""
    v = trader.get("return_12m")
    if v is not None:
        return float(v)
    v = trader.get("total_return_pct")
    if v is not None:
        return float(v)
    v = trader.get("avg_monthly_return")
    if v is not None:
        return float(v) * 12
    return 0.0


def _get_return_6m(trader: dict) -> float:
    """Derive 6‑month return from available fields."""
    v = trader.get("return_6m")
    if v is not None:
        return float(v)
    v = trader.get("avg_monthly_return")
    if v is not None:
        return float(v) * 6
    # fallback to total_return_pct / 2 as rough estimate
    v = trader.get("total_return_pct")
    if v is not None:
        return float(v) * 0.5
    return 0.0


def _get_risk(trader: dict) -> float:
    return float(trader.get("risk_score", 5.0) or 5.0)


def _get_drawdown(trader: dict) -> float:
    return float(trader.get("max_drawdown", 0.0) or 0.0)


def _get_consistency(trader: dict) -> float:
    """Consistency score 0–100. Higher = more stable."""
    v = trader.get("consistency_score")
    if v is not None:
        return min(100.0, max(0.0, float(v)))
    # derive from sharpe * 20, capped at 100
    sharpe = trader.get("sharpe_score")
    if sharpe is not None:
        return min(100.0, max(0.0, float(sharpe) * 20))
    # derive from volatility (lower = more consistent), inverted
    vol = trader.get("volatility")
    if vol is not None:
        v = float(vol)
        if v <= 0:
            return 50.0
        return min(100.0, max(0.0, 100.0 - (v - 10.0) * 2.5))
    return 50.0


def calculate_growth_score(trader: dict) -> dict:
    """Compute deterministic growth score (0–100) for a single trader.

    Returns a dict with:
      score         — final score (0–100)
      details       — breakdown of each component
      penalties     — list of applied penalty descriptions
      growth_filter — True if score zeroed by growth filter
    """
    r12 = _get_return_12m(trader)
    r6 = _get_return_6m(trader)
    risk = _get_risk(trader)
    dd = _get_drawdown(trader)
    consistency = _get_consistency(trader)

    penalties = []
    growth_filter = False

    # ── Growth filter — hard stop ─────────────────────────────────------
    if r12 < GROWTH_FILTER_MIN_12M:
        logger.info(f"Growth filter: 12M return {r12:.1f}% < 10% — score = 0")
        return {
            "score": 0.0,
            "details": {
                "return_12m": r12,
                "return_6m": r6,
                "risk_score": risk,
                "max_drawdown": dd,
                "consistency": consistency,
            },
            "penalties": [f"12M return {r12:.1f}% below 10% threshold — growth filter"],
            "growth_filter": True,
        }

    # ── Normalise each component to 0–100 ────────────────────────────────
    # Return: cap at 100% for scoring purposes
    r12_norm = min(100.0, max(0.0, r12 * 5))       # 20% return → 100
    r6_norm = min(100.0, max(0.0, r6 * 8))          # 12.5% return → 100

    # Risk: invert so lower risk = higher score (0.5 scale step = 1 point)
    risk_norm = min(100.0, max(0.0, (10.0 - risk) * 12.5))  # risk 2 → 100, risk 10 → 0

    # Drawdown: invert so lower drawdown = higher score (1% = ~4 points)
    dd_norm = min(100.0, max(0.0, 100.0 - dd * 4))

    # Consistency: already 0–100
    cons_norm = min(100.0, max(0.0, consistency))

    # ── Compute base score ──────────────────────────────────────────────
    base_score = (
        r12_norm * W_12M +
        r6_norm * W_6M +
        risk_norm * W_RISK +
        dd_norm * W_DRAWDOWN +
        cons_norm * W_CONSISTENCY
    )

    # ── Apply penalties ─────────────────────────────────────────────────
    score = base_score
    if risk > 7:
        score -= PENALTY_RISK_HIGH
        penalties.append(f"Risk {risk:.1f} > 7: −{PENALTY_RISK_HIGH} pts")

    if dd > 25:
        score -= PENALTY_DRAWDOWN_HIGH
        penalties.append(f"Drawdown {dd:.1f}% > 25%: −{PENALTY_DRAWDOWN_HIGH} pts")

    score = max(0.0, round(score, 1))

    return {
        "score": score,
        "details": {
            "return_12m": round(r12, 1),
            "return_6m": round(r6, 1),
            "risk_score": risk,
            "max_drawdown": dd,
            "consistency": round(consistency, 1),
            "components": {
                "r12_norm": round(r12_norm, 1),
                "r6_norm": round(r6_norm, 1),
                "risk_norm": round(risk_norm, 1),
                "dd_norm": round(dd_norm, 1),
                "cons_norm": round(cons_norm, 1),
            },
        },
        "penalties": penalties,
        "growth_filter": False,
    }


def scout_holdings(holdings: list[dict]) -> dict:
    """Score all current holdings and identify the weakest link.

    Returns:
      scored     — list of {username, score, details, penalties, growth_filter}
      weakest    — the trader dict with lowest score
      top        — the trader dict with highest score
      avg_score  — average score across all holdings
    """
    if not holdings:
        return {"scored": [], "weakest": None, "top": None, "avg_score": 0.0}

    scored = []
    for h in holdings:
        result = calculate_growth_score(h)
        scored.append({
            "username": h.get("username", "?"),
            "allocation_pct": h.get("allocation_pct", 0),
            **result,
        })

    scored.sort(key=lambda x: x["score"])
    weakest = scored[0] if scored else None
    top = scored[-1] if scored else None
    avg_score = round(sum(s["score"] for s in scored) / len(scored), 1)

    return {"scored": scored, "weakest": weakest, "top": top, "avg_score": avg_score}


def rank_candidates(holdings: list[dict], candidates: list[dict], top_n: int = 3) -> list[dict]:
    """Score discovery candidates and return best swaps by score delta.

    The delta is measured against the weakest current holding.
    If no holdings, delta = candidate score.
    """
    holdings_result = scout_holdings(holdings)
    weakest_score = holdings_result["weakest"]["score"] if holdings_result["weakest"] else 0.0

    scored = []
    for c in candidates:
        result = calculate_growth_score(c)
        scored.append({
            "username": c.get("username", "?"),
            "risk_score": c.get("risk_score", "?"),
            "total_return_pct": c.get("total_return_pct", "?"),
            **result,
            "delta": round(result["score"] - weakest_score, 1),
        })

    scored.sort(key=lambda x: x["delta"], reverse=True)
    return scored[:top_n]


def generate_scout_report(holdings: list[dict], candidates: list[dict]) -> dict:
    """Full deterministic scout report — no AI required.

    Returns a dict usable anywhere the old AI scout output was expected.
    """
    hs = scout_holdings(holdings)
    top_swaps = rank_candidates(holdings, candidates)

    weakest = hs["weakest"]
    best_swap = top_swaps[0] if top_swaps else None

    # Build a simple "action_required" flag
    # Flag if weakest score < 50 OR weakest delta to best swap > 20
    action_required = False
    flagged_trader = None
    recommended_swap = None
    reasoning_lines = []

    if weakest and weakest["score"] < 50:
        action_required = True
        flagged_trader = weakest["username"]
        reasoning_lines.append(
            f"Weakest link: {weakest['username']} (score {weakest['score']:.1f}/100)"
        )
        for p in weakest.get("penalties", []):
            reasoning_lines.append(f"  ⚠ {p}")
        if best_swap and best_swap["score"] > weakest["score"]:
            recommended_swap = best_swap["username"]
            reasoning_lines.append(
                f"Top swap: {best_swap['username']} "
                f"(score {best_swap['score']:.1f}, delta +{best_swap['delta']})"
            )
        else:
            reasoning_lines.append("No suitable swap found among candidates.")
    else:
        reasoning_lines.append("All traders score ≥ 50. Portfolio is healthy.")

    return {
        "action_required": action_required,
        "flagged_trader": flagged_trader,
        "recommended_swap": recommended_swap,
        "reasoning": "\n".join(reasoning_lines),
        "scored_holdings": hs["scored"],
        "weakest": weakest,
        "top_swaps": top_swaps,
        "avg_score": hs["avg_score"],
    }
