"""Pure scoring functions — no I/O, no side effects.

Professional-grade scoring system:
  - Return (35pt):      linear up to 150%, diminished returns beyond
  - Risk (30pt):        step function. Risk 1-2→30, 3-4→25, 5-6→15, 7→5, 8+→0
  - Positions (15pt):   linear up to 50 positions
  - Drawdown (10pt):    optional bonus. peakToValley <10%→10pt, <15%→7pt, <20%→3pt
  - Consistency (5pt):  optional bonus. profitableMonthsPct >70%→5pt, >50%→3pt
  - Experience (5pt):   optional bonus. weeks >156→5pt, >52→3pt

No confidence modifier, no data quality gate, no penalty trees.
Missing optional fields simply get 0 for that component.
Total capped at 100. Score 80+ = strong and copy-worthy.

Scoring reflects professional copy-trading values:
  - Risk > 7 is heavily penalized (no professional allocates to these)
  - Extreme returns (>150%) get no extra credit (likely unsustainable)
  - Drawdown, consistency, and experience reward complete data
  - Missing data naturally lowers score (no fake defaults)
"""

from __future__ import annotations
import logging
from typing import Optional
from backend.discovery.types import TraderProfile
from backend.discovery.validate import validate_data_source, check_constraints
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
    """Max 35 points, capped at 150% return (diminishing returns beyond)."""
    if best_return is None:
        return 0.0
    return round(min(best_return, 150.0) / 150.0 * 35.0, 1)


def _risk_score_step(risk: Optional[float]) -> float:
    """Max 30 points, step function. Risk 1-2→30, 3-4→25, 5-6→15, 7→5, 8+→0.

    Professional analysts heavily penalize risk > 6.
    Risk 8+ is considered untouchable for copy trading.
    """
    if risk is None or risk < 1 or risk > 10:
        return 0.0
    if risk <= 2:
        return 30.0
    if risk <= 4:
        return 25.0
    if risk <= 6:
        return 15.0
    if risk <= 7:
        return 5.0
    return 0.0


def _positions_score(positions: Optional[int]) -> float:
    """Max 15 points, linear up to 50 positions."""
    if positions is None or positions <= 0:
        return 0.0
    return round(min(float(positions), 50.0) / 50.0 * 15.0, 1)


def _drawdown_score(peak_to_valley: Optional[float]) -> float:
    """Max 10 points. Lower drawdown = higher score.

    peakToValley is a negative percentage (e.g. -16.24 means -16.24%).
    We use the absolute value.
    """
    if peak_to_valley is None:
        return 0.0
    dd = abs(float(peak_to_valley))
    if dd < 10.0:
        return 10.0
    if dd < 15.0:
        return 7.0
    if dd < 20.0:
        return 3.0
    return 0.0


def _consistency_score(profitable_months_pct: Optional[float]) -> float:
    """Max 5 points. >70% profitable months → bonus."""
    if profitable_months_pct is None:
        return 0.0
    pct = float(profitable_months_pct)
    if pct >= 70.0:
        return 5.0
    if pct >= 50.0:
        return 3.0
    return 0.0


def _experience_score(weeks: Optional[int]) -> float:
    """Max 5 points. 3+ years → bonus, 1+ year → partial."""
    if weeks is None:
        return 0.0
    if weeks >= 156:  # 3+ years
        return 5.0
    if weeks >= 52:   # 1+ year
        return 3.0
    return 0.0



def _confidence_label(profile: TraderProfile) -> str:
    """HIGH if all 6 core metrics present, MEDIUM if 4-5, LOW if <4."""
    core_metrics = [
        profile.raw_total_return_pct is not None,
        profile.raw_risk_score is not None and profile.raw_risk_score > 0,
        profile.raw_positions_count is not None and profile.raw_positions_count > 0,
        profile.raw_peak_to_valley is not None,
        profile.raw_profitable_months_pct is not None,
        profile.raw_weeks_since_registration is not None,
    ]
    present = sum(core_metrics)
    if present >= 5:
        return "HIGH"
    if present >= 3:
        return "MEDIUM"
    return "LOW"


# ── Core scoring ─────────────────────────────────────────────────────


def calculate_score_from_profile(profile: TraderProfile) -> TraderProfile:
    """Score a trader using base metrics + optional professional bonuses.

    Base: return (35), risk (30), positions (15) = 80 max
    Bonuses (optional): drawdown (10), consistency (5), experience (5) = 20 max
    Total capped at 100. Missing data = 0 for that component.
    """
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

    # ── 1. Return score (max 35) ──
    best_return = _best_return_pct(profile)
    ret_score = _return_score(best_return)

    # ── 2. Risk score (max 30) ──
    risk = profile.raw_risk_score
    risk_score = _risk_score_step(risk)

    # ── 3. Positions score (max 15) ──
    positions = profile.raw_positions_count
    pos_score = _positions_score(positions)

    # ── 4. Drawdown bonus (max 10, optional) ──
    dd = profile.raw_peak_to_valley
    dd_score = _drawdown_score(dd)

    # ── 5. Consistency bonus (max 5, optional) ──
    prof_months = profile.raw_profitable_months_pct
    cons_score = _consistency_score(prof_months)

    # ── 6. Experience bonus (max 5, optional) ──
    weeks = profile.raw_weeks_since_registration
    exp_score = _experience_score(weeks)

    total_score = min(100.0, ret_score + risk_score + pos_score + dd_score + cons_score + exp_score)

    profile.score = round(total_score, 1)
    profile.final_score = round(total_score, 1)
    profile.confidence_modifier = 1.0
    profile.confidence_score = 1.0
    profile.growth_filter = False
    profile.penalties = []
    profile.explanation = [
        f"source={profile.source}",
        f"return={best_return:.1f}%" if best_return else "return=none",
        f"risk={risk:.1f}" if risk and risk > 0 else "risk=none",
        f"positions={positions}" if positions and positions > 0 else "positions=none",
        f"drawdown={abs(dd):.1f}%" if dd else "drawdown=none",
        f"consistency={prof_months:.0f}%" if prof_months else "consistency=none",
        f"experience={weeks}w" if weeks else "experience=none",
    ]

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
