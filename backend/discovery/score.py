"""Pure scoring functions — no I/O, no side effects.

Simple 4-metric system: return (50pt), risk (25pt), copiers (15pt),
multiplied by confidence (0.65/0.85/1.0). No growth filter, no penalty
trees, no fake defaults.
"""

from __future__ import annotations
import logging
from typing import Optional
from backend.discovery.types import TraderProfile
from backend.discovery.validate import validate_data_source, check_constraints
from backend.discovery.config import MIN_VERIFIED_FIELDS
from backend.discovery.validate import build_trader_profile

logger = logging.getLogger(__name__)


# ── Backward-compat helpers (kept for scoring_engine imports) ─────


def _compute_confidence_score(profile: TraderProfile) -> float:
    """Backward-compat: data completeness 0-1 (7 checks)."""
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
    return round(0.3 + (present / len(checks)) * 0.7, 2)


def _has_return_data(profile: TraderProfile) -> bool:
    """Backward-compat: check if trader has any return data."""
    return any(v is not None and v > 0 for v in [
        profile.raw_return_12m,
        profile.raw_return_6m,
        profile.raw_total_return_pct,
        profile.raw_avg_monthly_return,
    ])


# ── Simple scoring helpers ─────────────────────────────────────────


def _best_return_pct(profile: TraderProfile) -> Optional[float]:
    """Longest available return: total_return_pct > return_12m > avg_monthly*12."""
    if profile.raw_total_return_pct is not None and profile.raw_total_return_pct > 0:
        return profile.raw_total_return_pct
    if profile.raw_return_12m is not None and profile.raw_return_12m > 0:
        return profile.raw_return_12m
    if profile.raw_avg_monthly_return is not None and profile.raw_avg_monthly_return > 0:
        return profile.raw_avg_monthly_return * 12
    return None


def _return_score(best_return: Optional[float]) -> float:
    """Max 50 points, capped at 150% return."""
    if best_return is None:
        return 0.0
    return round(min(best_return, 150.0) / 150.0 * 50.0, 1)


def _risk_score_bucket(risk: Optional[float]) -> float:
    """Max 25 points. 3-6 ideal, 2/7 acceptable, 1/8 marginal, else 0."""
    if risk is None or risk <= 0:
        return 0.0
    if 3 <= risk <= 6:
        return 25.0
    if risk in (2, 7):
        return 18.0
    if risk in (1, 8):
        return 10.0
    return 0.0


def _copier_score(copiers: Optional[int]) -> float:
    """Max 15 points: >=500->15, >=100->10, >=20->5, else 0."""
    if copiers is None or copiers <= 0:
        return 0.0
    if copiers >= 500:
        return 15.0
    if copiers >= 100:
        return 10.0
    if copiers >= 20:
        return 5.0
    return 0.0


def _confidence_multiplier(verified_fields: int) -> float:
    """>=4 fields = 1.0, >=2 = 0.85, else = 0.65."""
    if verified_fields >= 4:
        return 1.0
    if verified_fields >= 2:
        return 0.85
    return 0.65


def _build_explanation(profile: TraderProfile, ret: Optional[float],
                       risk: Optional[float], copiers: Optional[int],
                       confidence: float) -> list:
    parts = [f"source={profile.source}"]
    if ret:
        parts.append(f"return={ret:.1f}%")
    if risk and risk > 0:
        parts.append(f"risk={risk:.1f}")
    if copiers and copiers > 0:
        parts.append(f"copiers={copiers}")
    parts.append(f"confidence={confidence}")
    return parts


# ── Core scoring ─────────────────────────────────────────────────────


def calculate_score_from_profile(profile: TraderProfile) -> TraderProfile:
    """Score a trader using 4 metrics: return, risk, copiers, confidence."""
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

    # ── Data quality gate ─────────────────────────────────────────
    if profile.verified_fields < MIN_VERIFIED_FIELDS:
        logger.info("Rejected %s: insufficient data (%d verified, need %d)",
                    username, profile.verified_fields, MIN_VERIFIED_FIELDS)
        profile.score = 0.0
        profile.final_score = 0.0
        profile.confidence_modifier = 0.0
        profile.confidence_score = _compute_confidence_score(profile)
        profile.explanation = [
            f"insufficient data: {profile.verified_fields}/{MIN_VERIFIED_FIELDS} fields verified",
        ]
        return profile

    # ── 1. Return score (max 50) ──
    best_return = _best_return_pct(profile)
    ret_score = _return_score(best_return)

    # ── 2. Risk score (max 25) ──
    risk = profile.raw_risk_score
    risk_score = _risk_score_bucket(risk)

    # ── 3. Copier score (max 15) ──
    copiers = profile.raw_copiers
    copier_score = _copier_score(copiers)

    # ── 4. Confidence multiplier ──
    confidence = _confidence_multiplier(profile.verified_fields)

    raw_score = ret_score + risk_score + copier_score
    final_score = raw_score * confidence

    profile.score = round(raw_score, 1)
    profile.final_score = round(final_score, 1)
    profile.confidence_modifier = confidence
    profile.confidence_score = confidence
    profile.growth_filter = False
    profile.penalties = []
    profile.explanation = _build_explanation(profile, best_return, risk, copiers, confidence)

    return profile


# ── Backward-compatible wrappers ─────────────────────────────────────


def calculate_growth_score(trader: dict) -> dict:
    """Backward-compatible. Returns result dict matching old format."""
    profile = build_trader_profile(trader)

    constraint_reason = check_constraints(profile)
    if constraint_reason:
        logger.info("Disqualified %s: %s", profile.username, constraint_reason)
        source_valid = validate_data_source(profile) is None
        return {
            "score": 0.0, "final_score": 0.0,
            "confidence_score": 0.0, "confidence_mod": 0.0,
            "source": profile.source, "source_valid": source_valid,
            "source_reason": constraint_reason,
            "explanation": [f"disqualified: {constraint_reason}"],
            "details": {}, "penalties": [constraint_reason],
            "growth_filter": True, "missing_fields": profile.missing_fields,
        }

    profile = calculate_score_from_profile(profile)
    source_valid = validate_data_source(profile) is None
    best_return = _best_return_pct(profile)

    return {
        "score": profile.score,
        "final_score": profile.final_score,
        "confidence_score": profile.confidence_score,
        "confidence_mod": profile.confidence_modifier,
        "source": profile.source,
        "source_valid": source_valid,
        "source_reason": None if source_valid else "unreliable source",
        "explanation": profile.explanation,
        "details": {
            "return_12m": round(best_return, 1) if best_return is not None else None,
            "return_6m": None,
            "risk_score": profile.raw_risk_score,
            "max_drawdown": profile.raw_drawdown,
            "consistency": 0.0,
            "growth_efficiency": 0.0,
            "components": {
                "r12_norm": 0.0, "r6_norm": 0.0,
                "risk_norm": 0.0, "dd_norm": 0.0, "cons_norm": 0.0,
            },
        },
        "penalties": [],
        "growth_filter": False,
        "missing_fields": profile.missing_fields,
    }


def rank_candidates(holdings: list[dict], candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Backward-compatible wrapper. Scores discovery candidates and returns best swaps."""
    from backend.discovery.validate import apply_constraints as apply_constraints_raw

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

    holdings_scored = [{**h, **calculate_growth_score(h)} for h in holdings]
    holdings_scored.sort(key=lambda x: x["score"])
    weakest_score = holdings_scored[0]["score"] if holdings_scored else 0.0

    scored = []
    for c in qualified:
        result = calculate_growth_score(c)
        scored.append({
            **c,
            **result,
            "delta": round(result["final_score"] - weakest_score, 1),
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
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
    discovery_scored.sort(key=lambda x: x["final_score"], reverse=True)

    if len(discovery_scored) >= top_n:
        return discovery_scored[:top_n]

    holdings_scored = [{**h, **calculate_growth_score(h)} for h in holdings]
    holdings_scored.sort(key=lambda x: x["final_score"], reverse=True)
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
