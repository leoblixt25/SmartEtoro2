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
    total_return = trader.get("total_return_pct")

    # tradeinfo is always authoritative
    if source == "tradeinfo" or confidence >= 1.0:
        return None

    # None return from non-authoritative source = no real data
    if total_return is None and confidence < 1.0:
        return f"no return data from {source} (confidence={confidence})"

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
        dd = c.get("max_drawdown")
        tr_days = c.get("track_record_days")

        reasons = []
        if dd is not None and float(dd) > 15:
            reasons.append(f"max_drawdown {float(dd):.1f}% > 15%")
        if tr_days is not None and int(tr_days) > 0 and int(tr_days) < 365:
            reasons.append(f"track_record {int(tr_days)}d < 365d")

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
    avg_monthly = trader.get("avg_monthly_return")
    max_dd = trader.get("max_drawdown")

    if avg_monthly is None or max_dd is None or max_dd <= 0:
        return 0.0

    ratio = float(avg_monthly) / float(max_dd)
    score = min(100.0, max(0.0, ratio * 200))
    return round(score, 1)


def _compute_confidence(trader: dict) -> float:
    """Compute data confidence score 0-1 based on available fields.

    Only counts a field as 'present' if it is both not None AND non-zero
    (zero means the API didn't return real data for that field).
    """
    checks = {
        "return_12m":          lambda v: v is not None and float(v) != 0,
        "total_return_pct":    lambda v: v is not None and float(v) != 0,
        "risk_score":          lambda v: v is not None and float(v) > 0,
        "max_drawdown":        lambda v: v is not None and float(v) > 0,
        "volatility":          lambda v: v is not None and float(v) > 0,
        "avg_monthly_return":  lambda v: v is not None and float(v) > 0,
        "sharpe_score":        lambda v: v is not None and float(v) != 0,
    }
    present = sum(1 for field, check in checks.items() if check(trader.get(field)))
    ratio = present / len(checks) if checks else 0
    return round(0.3 + ratio * 0.7, 2)


def _has_return_data(trader: dict) -> bool:
    """Check if trader has actual return data (not defaults)."""
    for key in ["return_12m", "return_6m", "total_return_pct", "avg_monthly_return"]:
        val = trader.get(key)
        if val is not None and float(val) > 0:
            return True
    return False


def _get_return_12m(trader: dict) -> Optional[float]:
    v = trader.get("return_12m")
    if v is not None and float(v) > 0:
        return float(v)
    v = trader.get("total_return_pct")
    if v is not None and float(v) > 0:
        return float(v)
    v = trader.get("avg_monthly_return")
    if v is not None and float(v) > 0:
        return float(v) * 12
    return None


def _get_return_6m(trader: dict) -> Optional[float]:
    v = trader.get("return_6m")
    if v is not None and float(v) > 0:
        return float(v)
    # Prefer total_return_pct over avg_monthly_return when both exist,
    # because avg_monthly_return is often default 0.0 from missing API data
    v = trader.get("total_return_pct")
    if v is not None and float(v) > 0:
        return float(v) * 0.5
    v = trader.get("avg_monthly_return")
    if v is not None and float(v) > 0:
        return float(v) * 6
    return None


def _get_risk(trader: dict) -> Optional[float]:
    v = trader.get("risk_score")
    if v is None:
        return None
    return float(v)


def _get_drawdown(trader: dict) -> Optional[float]:
    v = trader.get("max_drawdown")
    if v is None:
        return None
    return float(v)


def _get_consistency(trader: dict) -> float:
    v = trader.get("consistency_score")
    if v is not None and float(v) > 0:
        return min(100.0, max(0.0, float(v)))
    sharpe = trader.get("sharpe_score")
    if sharpe is not None and float(sharpe) > 0:
        return min(100.0, max(0.0, float(sharpe) * 20))
    vol = trader.get("volatility")
    if vol is not None and float(vol) > 0:
        v = float(vol)
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

    if r12 is not None:
        parts.append(f"12M={r12:.1f}%")
    if r6 is not None:
        parts.append(f"6M={r6:.1f}%")
    if risk is not None:
        parts.append(f"risk={risk:.1f}")
    if dd is not None:
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


def _confidence_penalty(trader: dict) -> float:
    """Compute confidence modifier (0.5-1.0) based on missing fields.

    Each missing key metric reduces confidence by:
      - risk_score missing: -0.15
      - copiers missing: -0.10
      - avg_monthly_return missing/zero: -0.20
      - max_drawdown missing/zero: -0.15
      - volatility missing/zero: -0.10

    Minimum modifier is 0.5 (score halved when data is very sparse).
    """
    modifier = 1.0
    risk = trader.get("risk_score")
    if risk is None:
        modifier -= 0.15
    copiers = trader.get("copiers")
    if copiers is None:
        modifier -= 0.10
    avg_monthly = trader.get("avg_monthly_return")
    if avg_monthly is None or float(avg_monthly) == 0:
        modifier -= 0.20
    dd = trader.get("max_drawdown")
    if dd is None or float(dd) == 0:
        modifier -= 0.15
    vol = trader.get("volatility")
    if vol is None or float(vol) == 0:
        modifier -= 0.10
    return max(modifier, 0.5)


def calculate_growth_score(trader: dict) -> dict:
    """Compute deterministic growth score (0-100) for a single trader.

    Validates data source before scoring. Rejects unreliable data.

    Returns:
      score            — final score (0-100), 0.0 if rejected
      final_score      — score adjusted for data confidence (0-100)
      confidence_score — data completeness (0-1)
      confidence_mod   — multiplier applied (0.5-1.0)
      source           — data source used
      source_valid     — True if source passed validation
      explanation      — human-readable scoring reasons
      details          — component breakdown
      penalties        — applied penalties
      growth_filter    — True if zeroed by growth filter
      missing_fields   — list of fields missing from API
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
            "final_score": 0.0,
            "confidence_score": _compute_confidence(trader),
            "confidence_mod": 0.0,
            "source": source,
            "source_valid": False,
            "source_reason": source_reason or "unknown",
            "explanation": [f"rejected: {source_reason}"],
            "details": {},
            "penalties": [],
            "growth_filter": False,
            "missing_fields": trader.get("missing_fields", []),
        }

    # ── Step 2: Compute score ──
    username = trader.get("username", "?")
    confidence = _compute_confidence(trader)
    confidence_mod = _confidence_penalty(trader)
    missing = trader.get("missing_fields", [])
    r12 = _get_return_12m(trader)
    r6 = _get_return_6m(trader)
    risk = _get_risk(trader)
    dd = _get_drawdown(trader)
    consistency = _get_consistency(trader)
    raw_risk = trader.get("risk_score")
    raw_return = trader.get("total_return_pct")
    raw_dd = trader.get("max_drawdown")
    raw_copiers = trader.get("copiers")
    raw_min_copy = trader.get("min_copy_amount")

    penalties = []
    growth_filter = False

    if _has_return_data(trader) and (r12 is not None and r12 < GROWTH_FILTER_MIN_12M):
        logger.info("Growth filter: %s 12M=%.1f%% — score=0", username, r12)
        return {
            "score": 0.0,
            "final_score": 0.0,
            "confidence_score": confidence,
            "confidence_mod": confidence_mod,
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
            "missing_fields": missing,
        }

    # Normalize each component, using None-safe defaults
    r12_norm = min(100.0, max(0.0, r12 * 5)) if r12 is not None else 0.0
    r6_norm = min(100.0, max(0.0, r6 * 8)) if r6 is not None else 0.0
    risk_norm = min(100.0, max(0.0, (10.0 - risk) * 12.5)) if risk is not None else 50.0
    dd_norm = min(100.0, max(0.0, 100.0 - dd * 4)) if dd is not None else 50.0
    cons_norm = min(100.0, max(0.0, consistency))

    base_score = (
        r12_norm * W_12M +
        r6_norm * W_6M +
        risk_norm * W_RISK +
        dd_norm * W_MAX_DRAWDOWN +
        cons_norm * W_CONSISTENCY
    )

    score = base_score
    if risk is not None and risk > 7:
        score -= PENALTY_RISK_HIGH
        penalties.append(f"risk={risk:.1f} > 7: -{PENALTY_RISK_HIGH}pts")
    if dd is not None and dd > 25:
        score -= PENALTY_DRAWDOWN_HIGH
        penalties.append(f"dd={dd:.1f}% > 25%: -{PENALTY_DRAWDOWN_HIGH}pts")

    score = max(0.0, round(score, 1))
    final_score = round(score * confidence_mod, 1)

    result = {
        "score": score,
        "final_score": final_score,
        "confidence_score": confidence,
        "confidence_mod": confidence_mod,
        "source": source,
        "source_valid": True,
        "source_reason": None,
        "explanation": _build_explanation(trader, final_score, confidence, source, penalties),
        "details": {
            "return_12m": round(r12, 1) if r12 is not None else None,
            "return_6m": round(r6, 1) if r6 is not None else None,
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
        "missing_fields": missing,
    }

    # ── Per-trader debug logging (STEP 4 requirement) ──
    logger.info(
        f"""
    ===== TRADER DEBUG =====
    Username: {username}

    RAW API:
    risk={raw_risk}
    copiers={raw_copiers}
    return={raw_return}
    drawdown={raw_dd}
    min_copy={raw_min_copy}

    NORMALIZED:
    risk={risk}
    copiers={raw_copiers}
    return_12m={r12}
    consistency={consistency}

    MISSING:
    {missing}

    SCORE BREAKDOWN:
    return_12m_score={round(r12_norm, 1) if r12_norm else 0}
    risk_score={round(risk_norm, 1) if risk_norm else 0}
    consistency_score={round(cons_norm, 1) if cons_norm else 0}
    confidence_modifier={confidence_mod}
    base_score={round(score, 1)}
    final_score={final_score}
    ========================
    """
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
            **h,
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
            **c,
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
            **c,
            **result,
            "allocation_pct": c.get("allocation_pct", 0),
        })
    discovery_scored.sort(key=lambda x: x["score"], reverse=True)

    if len(discovery_scored) >= top_n:
        return discovery_scored[:top_n]

    holdings_scored = []
    for h in holdings:
        result = calculate_growth_score(h)
        holdings_scored.append({
            **h,
            **result,
        })
    holdings_scored.sort(key=lambda x: x["score"], reverse=True)

    result = discovery_scored[:]
    result.extend(holdings_scored[:top_n - len(result)])
    return result
