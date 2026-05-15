"""Pure scoring functions — no I/O, no side effects.

Takes a TraderProfile (or raw dict for backward compat) and returns
a ScoreResult.  Never uses fake defaults as if they were real values.
"""

from __future__ import annotations
import math
import logging
from typing import Dict, List, Optional
from backend.discovery.types import TraderProfile
from backend.discovery.validate import validate_data_source, check_constraints
from backend.discovery.config import (
    W_12M, W_6M, W_RISK, W_MAX_DRAWDOWN, W_CONSISTENCY,
    PENALTY_RISK_HIGH, PENALTY_DRAWDOWN_HIGH,
    GROWTH_FILTER_MIN_12M,
    COPIER_BONUS_MAX, COPIER_BONUS_LOG_BASE, COPIER_BONUS_SCALE,
    MATURITY_BONUS, MATURITY_MIN_POSITIONS,
    CONFIDENCE_FLOOR,
    MISSING_RISK_PENALTY, MISSING_COPIERS_PENALTY,
    MISSING_RETURN_PENALTY, MISSING_DD_PENALTY, MISSING_VOL_PENALTY,
)
from backend.discovery.validate import build_trader_profile

logger = logging.getLogger(__name__)


def _compute_confidence_score(profile: TraderProfile) -> float:
    """Compute data completeness score 0-1 based on available fields."""
    checks = [
        ("return_12m", lambda p: p.raw_return_12m is not None and p.raw_return_12m != 0),
        ("total_return_pct", lambda p: p.raw_total_return_pct is not None and p.raw_total_return_pct != 0),
        ("risk_score", lambda p: p.raw_risk_score is not None and p.raw_risk_score > 0),
        ("max_drawdown", lambda p: p.raw_drawdown is not None and p.raw_drawdown > 0),
        ("volatility", lambda p: p.raw_volatility is not None and p.raw_volatility > 0),
        ("avg_monthly_return", lambda p: p.raw_avg_monthly_return is not None and p.raw_avg_monthly_return > 0),
        ("sharpe_score", lambda p: p.raw_sharpe is not None and p.raw_sharpe != 0),
    ]
    present = sum(1 for _, check in checks if check(profile))
    if not checks:
        return 0.0
    ratio = present / len(checks)
    return round(0.3 + ratio * 0.7, 2)


def _confidence_penalty(profile: TraderProfile) -> float:
    """Compute confidence modifier (0.3-1.0) based on missing fields.

    Each missing key metric reduces confidence below 1.0.
    Lower floor (0.3) ensures different data quality levels produce
    meaningfully different modifiers.
    """
    modifier = 1.0
    if profile.raw_risk_score is None:
        modifier -= MISSING_RISK_PENALTY
    if profile.raw_copiers is None:
        modifier -= MISSING_COPIERS_PENALTY
    if profile.raw_avg_monthly_return is None:
        modifier -= MISSING_RETURN_PENALTY
    if profile.raw_drawdown is None:
        modifier -= MISSING_DD_PENALTY
    if profile.raw_volatility is None:
        modifier -= MISSING_VOL_PENALTY
    return max(modifier, CONFIDENCE_FLOOR)


def _has_return_data(profile: TraderProfile) -> bool:
    return any(v is not None and v > 0 for v in [
        profile.raw_return_12m,
        profile.raw_return_6m,
        profile.raw_total_return_pct,
        profile.raw_avg_monthly_return,
    ])


def _get_return_12m(profile: TraderProfile) -> Optional[float]:
    if profile.raw_return_12m is not None and profile.raw_return_12m > 0:
        return profile.raw_return_12m
    if profile.raw_total_return_pct is not None and profile.raw_total_return_pct > 0:
        return profile.raw_total_return_pct
    if profile.raw_avg_monthly_return is not None and profile.raw_avg_monthly_return > 0:
        return profile.raw_avg_monthly_return * 12
    return None


def _get_return_6m(profile: TraderProfile) -> Optional[float]:
    if profile.raw_return_6m is not None and profile.raw_return_6m > 0:
        return profile.raw_return_6m
    if profile.raw_total_return_pct is not None and profile.raw_total_return_pct > 0:
        return profile.raw_total_return_pct * 0.5
    if profile.raw_avg_monthly_return is not None and profile.raw_avg_monthly_return > 0:
        return profile.raw_avg_monthly_return * 6
    return None


def _get_consistency(profile: TraderProfile) -> float:
    """Score consistency 0-100. Returns 0 if no data."""
    if profile.raw_consistency_score is not None and profile.raw_consistency_score > 0:
        return min(100.0, max(0.0, profile.raw_consistency_score))
    if profile.raw_sharpe is not None and profile.raw_sharpe > 0:
        return min(100.0, max(0.0, profile.raw_sharpe * 20))
    if profile.raw_volatility is not None and profile.raw_volatility > 0:
        return min(100.0, max(0.0, 100.0 - (profile.raw_volatility - 10.0) * 2.5))
    return 0.0


def _growth_efficiency(profile: TraderProfile) -> float:
    """Growth Efficiency = avg_monthly_return / max_drawdown, scaled 0-100."""
    if profile.raw_avg_monthly_return is None or profile.raw_drawdown is None:
        return 0.0
    if profile.raw_drawdown <= 0:
        return 0.0
    ratio = profile.raw_avg_monthly_return / profile.raw_drawdown
    return round(min(100.0, max(0.0, ratio * 200)), 1)


def calculate_score_from_profile(profile: TraderProfile) -> TraderProfile:
    """Score a trader from a validated TraderProfile. Mutates and returns it."""
    username = profile.username

    # ── Source validation ─────────────────────────────────────────
    source_reason = validate_data_source(profile)
    if source_reason is not None:
        logger.info("Rejected %s: unreliable source (%s)", username, source_reason)
        profile.score = 0.0
        profile.final_score = 0.0
        profile.confidence_modifier = 0.0
        profile.confidence_score = _compute_confidence_score(profile)
        profile.explanation = [f"rejected: {source_reason}"]
        return profile

    # ── Growth filter ─────────────────────────────────────────────
    r12 = _get_return_12m(profile)
    r6 = _get_return_6m(profile)
    risk = profile.raw_risk_score
    dd = profile.raw_drawdown
    consistency = _get_consistency(profile)

    if _has_return_data(profile) and (r12 is not None and r12 < GROWTH_FILTER_MIN_12M):
        logger.info("Growth filter: %s 12M=%.1f%% — score=0", username, r12)
        profile.score = 0.0
        profile.final_score = 0.0
        profile.confidence_score = _compute_confidence_score(profile)
        profile.confidence_modifier = _confidence_penalty(profile)
        profile.growth_filter = True
        profile.penalties = [f"12M return {r12:.1f}% below {GROWTH_FILTER_MIN_12M}% threshold"]
        profile.explanation = _build_explanation(profile, 0.0, profile.confidence, source="...", penalties=profile.penalties)
        return profile

    # ── Normalize ─────────────────────────────────────────────────
    r12_norm = min(100.0, max(0.0, r12 * 0.8)) if r12 is not None else 0.0
    r6_norm = min(100.0, max(0.0, r6 * 1.5)) if r6 is not None else 0.0
    risk_norm = min(100.0, max(0.0, (10.0 - risk) * 12.5)) if risk is not None else 0.0
    dd_norm = min(100.0, max(0.0, 100.0 - dd * 4)) if dd is not None else 0.0
    cons_norm = min(100.0, max(0.0, consistency))

    profile.norm_return_12m = r12_norm
    profile.norm_return_6m = r6_norm
    profile.norm_risk = risk_norm
    profile.norm_drawdown = dd_norm
    profile.norm_consistency = cons_norm

    # ── Base score ────────────────────────────────────────────────
    base_score = (
        r12_norm * W_12M +
        r6_norm * W_6M +
        risk_norm * W_RISK +
        dd_norm * W_MAX_DRAWDOWN +
        cons_norm * W_CONSISTENCY
    )

    score = base_score
    penalties = []

    # ── Penalties ─────────────────────────────────────────────────
    if risk is not None and risk > 7:
        score -= PENALTY_RISK_HIGH
        penalties.append(f"risk={risk:.1f} > 7: -{PENALTY_RISK_HIGH}pts")
    if dd is not None and dd > 25:
        score -= PENALTY_DRAWDOWN_HIGH
        penalties.append(f"dd={dd:.1f}% > 25%: -{PENALTY_DRAWDOWN_HIGH}pts")

    # ── Verified-data bonuses ─────────────────────────────────────
    copier_bonus = 0.0
    if profile.raw_copiers is not None and profile.raw_copiers > 0:
        copier_bonus = min(COPIER_BONUS_MAX, max(0.0, math.log10(profile.raw_copiers) * COPIER_BONUS_SCALE))
        score += copier_bonus
        penalties.append(f"copiers={profile.raw_copiers}: +{copier_bonus:.0f}pts")

    maturity_bonus = 0.0
    if profile.raw_positions_count is not None and profile.raw_positions_count >= MATURITY_MIN_POSITIONS:
        maturity_bonus = MATURITY_BONUS
        score += maturity_bonus
        penalties.append(f"positions={profile.raw_positions_count}: +{maturity_bonus:.0f}pts")

    profile.copier_bonus = copier_bonus
    profile.maturity_bonus = maturity_bonus

    score = max(0.0, round(score, 1))
    confidence_mod = _confidence_penalty(profile)
    confidence_score = _compute_confidence_score(profile)
    final_score = round(score * confidence_mod, 1)

    profile.score = score
    profile.final_score = final_score
    profile.confidence_modifier = confidence_mod
    profile.confidence_score = confidence_score
    profile.penalties = penalties
    profile.explanation = _build_explanation(profile, final_score, profile.confidence, profile.source, penalties)

    logger.info(
        "Score %s: base=%.1f bonus(cop=%.1f mat=%.1f) penalty=%s "
        "mod=%.2f score=%.1f final=%.1f missing=[%s]",
        username, base_score, copier_bonus, maturity_bonus,
        penalties or "none",
        confidence_mod, score, final_score,
        ", ".join(profile.missing_fields) if profile.missing_fields else "none",
    )
    return profile


def _build_explanation(profile: TraderProfile, score: float, confidence: float, source: str, penalties: list) -> list:
    parts = [f"source={source}", f"confidence={confidence}"]
    if profile.raw_return_12m is not None:
        parts.append(f"12M={profile.raw_return_12m:.1f}%")
    if profile.raw_return_6m is not None:
        parts.append(f"6M={profile.raw_return_6m:.1f}%")
    if profile.raw_risk_score is not None:
        parts.append(f"risk={profile.raw_risk_score:.1f}")
    if profile.raw_drawdown is not None:
        parts.append(f"dd={profile.raw_drawdown:.1f}%")
    for p in penalties:
        parts.append(p)
    if score >= 70:
        parts.append("strong candidate")
    elif score >= 40:
        parts.append("moderate candidate")
    else:
        parts.append("weak candidate")
    return parts


# ── Backward-compatible wrappers ─────────────────────────────────────


def calculate_growth_score(trader: dict) -> dict:
    """Backward-compatible wrapper for calculate_growth_score.

    Accepts raw trader dict, returns result dict matching old format.
    """
    profile = build_trader_profile(trader)
    constraint_reason = check_constraints(profile)
    if constraint_reason and False:
        pass  # constraints are applied in rank_candidates, not here

    profile = calculate_score_from_profile(profile)

    return {
        "score": profile.score,
        "final_score": profile.final_score,
        "confidence_score": profile.confidence_score,
        "confidence_mod": profile.confidence_modifier,
        "source": profile.source,
        "source_valid": validate_data_source(profile) is None,
        "source_reason": validate_data_source(profile),
        "explanation": profile.explanation,
        "details": {
            "return_12m": round(profile.raw_return_12m, 1) if profile.raw_return_12m is not None else None,
            "return_6m": round(profile.raw_return_6m, 1) if profile.raw_return_6m is not None else None,
            "risk_score": profile.raw_risk_score,
            "max_drawdown": profile.raw_drawdown,
            "consistency": round(_get_consistency(profile), 1),
            "growth_efficiency": _growth_efficiency(profile),
            "components": {
                "r12_norm": round(profile.norm_return_12m, 1),
                "r6_norm": round(profile.norm_return_6m, 1),
                "risk_norm": round(profile.norm_risk, 1),
                "dd_norm": round(profile.norm_drawdown, 1),
                "cons_norm": round(profile.norm_consistency, 1),
            },
        },
        "penalties": profile.penalties,
        "growth_filter": profile.growth_filter,
        "missing_fields": profile.missing_fields,
    }


def rank_candidates(holdings: list[dict], candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Backward-compatible wrapper. Scores discovery candidates and returns best swaps."""
    from backend.discovery.validate import apply_constraints as apply_constraints_raw

    # Apply constraints to raw candidates
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
            logger.info("Disqualified %s: %s", c.get("username", "?"), "; ".join(reasons))
            continue
        qualified.append(c)

    rejected = len(candidates) - len(qualified)
    if rejected:
        logger.info("Constraints: %d/%d passed (%d disqualified)", len(qualified), len(candidates), rejected)

    # Score holdings to find weakest
    holdings_scored = [{**h, **calculate_growth_score(h)} for h in holdings]
    holdings_scored.sort(key=lambda x: x["score"])
    weakest_score = holdings_scored[0]["score"] if holdings_scored else 0.0

    # Score candidates
    scored = []
    for c in qualified:
        result = calculate_growth_score(c)
        scored.append({
            **c,
            **result,
            "delta": round(result["score"] - weakest_score, 1),
        })

    scored.sort(key=lambda x: x["delta"], reverse=True)
    return scored[:top_n]


def scout_holdings(holdings: list[dict]) -> dict:
    """Backward-compatible wrapper for scout_holdings."""
    if not holdings:
        return {"scored": [], "weakest": None, "top": None, "avg_score": 0.0}
    scored = [{**h, **calculate_growth_score(h)} for h in holdings]
    scored.sort(key=lambda x: x["score"])
    weakest = scored[0] if scored else None
    top = scored[-1] if scored else None
    avg = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else 0.0
    return {"scored": scored, "weakest": weakest, "top": top, "avg_score": avg}


def rank_combined(holdings: list[dict], candidates: list[dict], top_n: int = 3) -> list[dict]:
    """Backward-compatible wrapper for rank_combined."""
    qualified = []
    for c in candidates:
        dd = c.get("max_drawdown")
        tr_days = c.get("track_record_days")
        if dd is not None and float(dd) > 15:
            continue
        if tr_days is not None and int(tr_days) > 0 and int(tr_days) < 365:
            continue
        qualified.append(c)

    discovery_scored = [{**c, **calculate_growth_score(c), "allocation_pct": c.get("allocation_pct", 0)} for c in qualified]
    discovery_scored.sort(key=lambda x: x["score"], reverse=True)

    if len(discovery_scored) >= top_n:
        return discovery_scored[:top_n]

    holdings_scored = [{**h, **calculate_growth_score(h)} for h in holdings]
    holdings_scored.sort(key=lambda x: x["score"], reverse=True)
    result = discovery_scored[:]
    result.extend(holdings_scored[:top_n - len(result)])
    return result


def generate_scout_report(holdings: list[dict], candidates: list[dict]) -> dict:
    """Backward-compatible wrapper for generate_scout_report."""
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
        reasoning_lines.append(f"Weakest link: {weakest['username']} (score {weakest['score']:.1f}/100)")
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
