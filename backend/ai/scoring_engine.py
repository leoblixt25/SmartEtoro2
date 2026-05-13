"""
Deterministic Scoring Engine — single source of truth per trader.

Rule: One trader → one data source. No mixing endpoints.
If the data source is unreliable, the trader is not scored.

Weights:
  12M Return   35%  — long-term track record
  6M Return    25%  — recent momentum
  Risk Score   15%  — lower is better (inverted)
  Max Drawdown 15%  — lower is better (inverted)
  Consistency  10%  — stable monthly performance

Penalties:
  Risk > 7           → subtract 30 points
  Max Drawdown > 25% → subtract 20 points
  12M Return < 10%   → score = 0 (growth filter fails)

Source validation:
  tradeinfo (confidence=1.0) → authoritative, always score
  Other sources with confidence >= 0.8 → score normally
  confidence < 0.8 or zero return from low-confidence → reject
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Weights ────────────────────────────────────────────────────────
W_12M = 0.35
W_6M = 0.25
W_RISK = 0.15
W_MAX_DRAWDOWN = 0.15
W_CONSISTENCY = 0.10

# ── Penalties ──────────────────────────────────────────────────────
PENALTY_RISK_HIGH = 30
PENALTY_DRAWDOWN_HIGH = 20
GROWTH_FILTER_MIN_12M = 10.0

# ── Source validation thresholds ───────────────────────────────────
MIN_CONFIDENCE_TO_SCORE = 0.8


def validate_data_source(trader: dict) -> Optional[str]:
    """Validate that the trader's data comes from a single reliable source.

    Returns None if valid, or a string reason if the source is unreliable.
    """
    source = trader.get("source", "unknown")
    confidence = float(trader.get("confidence", 0.0) or 0.0)
    total_return = float(trader.get("total_return_pct", 0.0) or 0.0)

    # tradeinfo is always authoritative
    if source == "tradeinfo" or confidence >= 1.0:
        return None

    # Zero return from non-authoritative source = no real data
    if total_return == 0.0 and confidence < 1.0:
        return f"zero return from {source} (confidence={confidence})"

    # Low confidence = unreliable
    if confidence < MIN_CONFIDENCE_TO_SCORE:
        return f"low confidence {confidence} from {source} (min {MIN_CONFIDENCE_TO_SCORE})"

    return None


def apply_constraints(candidates: list[dict]) -> list[dict]:
    """Filter out candidates that fail hard constraint checks.

    Applied AFTER source validation but BEFORE scoring.
    """
    qualified = []
    for c in candidates:
        dd = float(c.get("max_drawdown", 0) or 0)
        tr_days = int(c.get("track_record_days", 0) or 0)

        reasons = []
        if dd > 15:
            reasons.append(f"max_drawdown {dd:.1f}% > 15%")
        if tr_days > 0 and tr_days < 365:
            reasons.append(f"track_record {tr_days}d < 365d")

        if reasons:
            logger.info(f"Disqualified {c.get('username', '?')}: {'; '.join(reasons)}")
            continue

        qualified.append(c)

    rejected = len(candidates) - len(qualified)
    if rejected:
        logger.info(f"Constraints: {len(qualified)}/{len(candidates)} passed ({rejected} disqualified)")
    return qualified


def calculate_growth_efficiency_score(trader: dict) -> float:
    """Compute Growth Efficiency = avg_monthly_return / max_drawdown, scaled 0-100."""
    avg_monthly = float(trader.get("avg_monthly_return", 0) or 0)
    max_dd = float(trader.get("max_drawdown", 1) or 1)

    if max_dd <= 0:
        return 50.0

    ratio = avg_monthly / max_dd
    score = min(100.0, max(0.0, ratio * 200))
    return round(score, 1)


def _compute_confidence(trader: dict) -> float:
    """Compute data confidence score 0-1 based on available fields."""
    checks = {
        "return_12m":          lambda v: v is not None and float(v) != 0,
        "total_return_pct":    lambda v: v is not None and float(v) != 0,
        "risk_score":          lambda v: v is not None and float(v) != 5.0,
        "max_drawdown":        lambda v: v is not None and float(v) != 0,
        "volatility":          lambda v: v is not None and float(v) != 0,
        "avg_monthly_return":  lambda v: v is not None and float(v) != 0,
        "sharpe_score":        lambda v: v is not None and float(v) != 0,
    }
    present = sum(1 for field, check in checks.items() if check(trader.get(field)))
    ratio = present / len(checks) if checks else 0
    return round(0.3 + ratio * 0.7, 2)


def _has_return_data(trader: dict) -> bool:
    """Check if trader has actual return data (not defaults)."""
    for key in ["return_12m", "return_6m", "total_return_pct", "avg_monthly_return"]:
        val = trader.get(key)
        if val is not None and float(val) != 0:
            return True
    return False


def _get_return_12m(trader: dict) -> float:
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
    v = trader.get("return_6m")
    if v is not None:
        return float(v)
    v = trader.get("avg_monthly_return")
    if v is not None:
        return float(v) * 6
    v = trader.get("total_return_pct")
    if v is not None:
        return float(v) * 0.5
    return 0.0


def _get_risk(trader: dict) -> float:
    return float(trader.get("risk_score", 5.0) or 5.0)


def _get_drawdown(trader: dict) -> float:
    return float(trader.get("max_drawdown", 0.0) or 0.0)


def _get_consistency(trader: dict) -> float:
    v = trader.get("consistency_score")
    if v is not None:
        return min(100.0, max(0.0, float(v)))
    sharpe = trader.get("sharpe_score")
    if sharpe is not None:
        return min(100.0, max(0.0, float(sharpe) * 20))
    vol = trader.get("volatility")
    if vol is not None:
        v = float(vol)
        if v <= 0:
            return 50.0
        return min(100.0, max(0.0, 100.0 - (v - 10.0) * 2.5))
    return 50.0


def _build_explanation(trader: dict, score: float, confidence: float, source: str, penalties: list) -> list:
    """Build human-readable explanation for a score."""
    parts = []
    username = trader.get("username", "?")

    parts.append(f"source={source}")
    parts.append(f"confidence={confidence}")

    r12 = _get_return_12m(trader)
    r6 = _get_return_6m(trader)
    risk = _get_risk(trader)
    dd = _get_drawdown(trader)

    if r12 > 0:
        parts.append(f"12M={r12:.1f}%")
    if r6 > 0:
        parts.append(f"6M={r6:.1f}%")
    parts.append(f"risk={risk:.1f}")
    parts.append(f"dd={dd:.1f}%")

    for p in penalties:
        parts.append(p)

    if score >= 70:
        parts.append("strong candidate")
    elif score >= 40:
        parts.append("moderate candidate")
    else:
        parts.append("weak candidate")

    return parts


def calculate_growth_score(trader: dict) -> dict:
    """Compute deterministic growth score (0-100) for a single trader.

    Validates data source before scoring. Rejects unreliable data.

    Returns:
      score            — final score (0-100), 0.0 if rejected
      confidence_score — data completeness (0-1)
      source           — data source used
      source_valid     — True if source passed validation
      explanation      — human-readable scoring reasons
      details          — component breakdown
      penalties        — applied penalties
      growth_filter    — True if zeroed by growth filter
    """
    # ── Step 1: Validate data source ──
    source = trader.get("source", "unknown")
    source_valid = False
    source_reason = validate_data_source(trader)
    if source_reason is None:
        source_valid = True

    if not source_valid:
        logger.info(
            "Rejected %s: unreliable source (%s)",
            trader.get("username", "?"), source_reason,
        )
        return {
            "score": 0.0,
            "confidence_score": _compute_confidence(trader),
            "source": source,
            "source_valid": False,
            "source_reason": source_reason or "unknown",
            "explanation": [f"rejected: {source_reason}"],
            "details": {},
            "penalties": [],
            "growth_filter": False,
        }

    # ── Step 2: Compute score ──
    confidence = _compute_confidence(trader)
    r12 = _get_return_12m(trader)
    r6 = _get_return_6m(trader)
    risk = _get_risk(trader)
    dd = _get_drawdown(trader)
    consistency = _get_consistency(trader)

    penalties = []
    growth_filter = False

    if _has_return_data(trader) and r12 < GROWTH_FILTER_MIN_12M:
        result = {
            "score": 0.0,
            "confidence_score": confidence,
            "source": source,
            "source_valid": True,
            "source_reason": None,
            "explanation": _build_explanation(
                trader, 0.0, confidence, source,
                [f"12M return {r12:.1f}% below 10% threshold"],
            ),
            "details": {
                "return_12m": r12,
                "return_6m": r6,
                "risk_score": risk,
                "max_drawdown": dd,
                "consistency": consistency,
                "growth_efficiency": calculate_growth_efficiency_score(trader),
            },
            "penalties": [f"12M return {r12:.1f}% below 10% threshold"],
            "growth_filter": True,
        }
        logger.info("Growth filter: %s 12M=%.1f%% — score=0", trader.get("username", "?"), r12)
        return result

    r12_norm = min(100.0, max(0.0, r12 * 5))
    r6_norm = min(100.0, max(0.0, r6 * 8))
    risk_norm = min(100.0, max(0.0, (10.0 - risk) * 12.5))
    dd_norm = min(100.0, max(0.0, 100.0 - dd * 4))
    cons_norm = min(100.0, max(0.0, consistency))

    base_score = (
        r12_norm * W_12M +
        r6_norm * W_6M +
        risk_norm * W_RISK +
        dd_norm * W_MAX_DRAWDOWN +
        cons_norm * W_CONSISTENCY
    )

    score = base_score
    if risk > 7:
        score -= PENALTY_RISK_HIGH
        penalties.append(f"risk={risk:.1f} > 7: -{PENALTY_RISK_HIGH}pts")
    if dd > 25:
        score -= PENALTY_DRAWDOWN_HIGH
        penalties.append(f"dd={dd:.1f}% > 25%: -{PENALTY_DRAWDOWN_HIGH}pts")

    score = max(0.0, round(score, 1))

    result = {
        "score": score,
        "confidence_score": confidence,
        "source": source,
        "source_valid": True,
        "source_reason": None,
        "explanation": _build_explanation(trader, score, confidence, source, penalties),
        "details": {
            "return_12m": round(r12, 1),
            "return_6m": round(r6, 1),
            "risk_score": risk,
            "max_drawdown": dd,
            "consistency": round(consistency, 1),
            "growth_efficiency": calculate_growth_efficiency_score(trader),
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

    logger.info(
        "Scored %s: %.1f (source=%s, conf=%.2f, r12=%.1f%%, risk=%.1f, dd=%.1f%%)",
        trader.get("username", "?"), score, source, confidence, r12, risk, dd,
    )
    return result


def scout_holdings(holdings: list[dict]) -> dict:
    """Score all current holdings and identify the weakest link."""
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
    avg_score = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else 0.0

    return {"scored": scored, "weakest": weakest, "top": top, "avg_score": avg_score}


def rank_candidates(holdings: list[dict], candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Score discovery candidates and return best swaps by score delta."""
    candidates = apply_constraints(candidates)
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
    """Full deterministic scout report."""
    hs = scout_holdings(holdings)
    top_swaps = rank_candidates(holdings, candidates)

    weakest = hs["weakest"]
    best_swap = top_swaps[0] if top_swaps else None
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
            reasoning_lines.append(f"  \u26a0 {p}")
        if best_swap and best_swap["score"] > weakest["score"]:
            recommended_swap = best_swap["username"]
            reasoning_lines.append(
                f"Top swap: {best_swap['username']} "
                f"(score {best_swap['score']:.1f}, delta +{best_swap['delta']})"
            )
        else:
            reasoning_lines.append("No suitable swap found among candidates.")
    else:
        reasoning_lines.append("All traders score \u2265 50. Portfolio is healthy.")

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


def rank_combined(holdings: list[dict], candidates: list[dict], top_n: int = 3) -> list[dict]:
    """Return the top N discovery candidates for the allocation plan."""
    candidates = apply_constraints(candidates)
    discovery_scored = []
    for c in candidates:
        result = calculate_growth_score(c)
        discovery_scored.append({
            "username": c.get("username", "?"),
            "allocation_pct": 0,
            "source": "discovery",
            **result,
        })
    discovery_scored.sort(key=lambda x: x["score"], reverse=True)

    if len(discovery_scored) >= top_n:
        return discovery_scored[:top_n]

    holdings_scored = []
    for h in holdings:
        result = calculate_growth_score(h)
        holdings_scored.append({
            "username": h.get("username", "?"),
            "allocation_pct": h.get("allocation_pct", 0),
            "source": "current",
            **result,
        })
    holdings_scored.sort(key=lambda x: x["score"], reverse=True)

    result = discovery_scored[:]
    result.extend(holdings_scored[:top_n - len(result)])
    return result
