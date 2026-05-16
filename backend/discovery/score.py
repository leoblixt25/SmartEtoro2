"""Pure scoring functions — no I/O, no side effects.

Weighted component scoring system (each component scores 0-100):
  - Return (25%):        sqrt curve — rewards high returns with diminishing marginal benefit
  - Risk-Adjusted (25%): return / max(drawdown, 5) — rewards efficient returns
  - Consistency (20%):   profitableMonthsPct — rewards steady gains over luck
  - Drawdown (15%):      linear penalty — severe for >20%
  - Risk Score (10%):    linear penalty — risk 8+ gets 0
  - Trend (5%):          volatility + experience + win ratio — rewards stable recent performance

Final = Return * 0.25 + RiskAdj * 0.25 + Consistency * 0.20 + Drawdown * 0.15 + Risk * 0.10 + Trend * 0.05
All components mandatory — missing data = 0 for that component.
Score targets: 80-90 excellent, 70-79 good, 55-69 average, <55 poor.
"""

from __future__ import annotations
import math
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


# ── Helpers ──────────────────────────────────────────────────────


def _best_return_pct(profile: TraderProfile) -> Optional[float]:
    """Longest available return: total_return_pct > return_12m > avg_monthly*12."""
    if profile.raw_total_return_pct is not None and profile.raw_total_return_pct > 0:
        return profile.raw_total_return_pct
    if profile.raw_return_12m is not None and profile.raw_return_12m > 0:
        return profile.raw_return_12m
    if profile.raw_avg_monthly_return is not None and profile.raw_avg_monthly_return > 0:
        return profile.raw_avg_monthly_return * 12
    return None


def _safe_drawdown(dd: Optional[float]) -> float:
    """Get absolute drawdown, default large if missing."""
    if dd is None:
        return 999.0
    return abs(float(dd))


# ── Component scores (all 0-100) ─────────────────────────────────


def _return_component(best_return: Optional[float]) -> float:
    """Return score 0-100. Nonlinear sqrt curve.

    0%→0, 25%→40, 50%→57, 100%→80, 150%→93, 200%+→100.
    Missing data = 0.
    """
    if best_return is None or best_return <= 0:
        return 0.0
    r = min(float(best_return), 250.0)
    return round(min(100.0, 8.0 * math.sqrt(r)), 1)


def _risk_adjusted_component(
    best_return: Optional[float],
    drawdown: Optional[float],
) -> float:
    """Risk-adjusted return score 0-100.

    Formula: return / max(drawdown, 5)
    Rewards efficient returns: 120% return with 12% DD = 10.0 ratio
    283% return with 16% DD = 17.7 ratio
    107% return with 14% DD = 7.6 ratio

    Ratio→Score (sqrt curve, 20*sqrt):
      <2→0, 5→45, 8→57, 10→63, 15→77, 20→89, 30+→100
    """
    if best_return is None or best_return <= 0:
        return 0.0
    dd = _safe_drawdown(drawdown)
    if dd < 5.0:
        dd = 5.0
    ratio = float(best_return) / dd
    if ratio < 2.0:
        return 0.0
    return round(min(100.0, 20.0 * math.sqrt(min(ratio, 40.0))), 1)


def _consistency_component(profitable_months_pct: Optional[float]) -> float:
    """Consistency score 0-100. Linear from 40% threshold.

    <40%→0, 50%→17, 60%→33, 70%→50, 80%→67, 90%→83, 100%→100
    Missing data = 0.
    """
    if profitable_months_pct is None:
        return 0.0
    pct = float(profitable_months_pct)
    if pct < 40.0:
        return 0.0
    return round(min(100.0, (pct - 40.0) * 1.67), 1)


def _drawdown_component(peak_to_valley: Optional[float]) -> float:
    """Drawdown score 0-100. Linear penalty.

    <5%→95, 10%→80, 15%→60, 20%→40, 25%→20, 30%→0
    Missing data = 0.
    """
    dd = _safe_drawdown(peak_to_valley)
    if dd >= 30.0:
        return 0.0
    if dd < 5.0:
        return 95.0
    return round(max(0.0, 100.0 - 4.0 * (dd - 5.0)), 1)


def _risk_component(risk: Optional[float]) -> float:
    """Risk score 0-100. Linear penalty.

    1→98, 2→86, 3→74, 4→62, 5→50, 6→38, 7→26, 8→14, 9→2, 10→0
    Missing data = 0.
    """
    if risk is None or risk < 1 or risk > 10:
        return 0.0
    return round(max(0.0, 110.0 - float(risk) * 12.0), 1)


def _trend_component(
    weeks: Optional[int],
    volatility: Optional[float],
    win_ratio: Optional[float],
    avg_monthly_return: Optional[float],
) -> float:
    """Trend score 0-100. Best-effort from available data.

    Components:
    - Experience (30pt): weeks >= 156→30, >= 52→18, >= 26→8
    - Stability (35pt): low volatility rewards consistent recent performance
      vol < 10→35, < 20→25, < 30→15, >= 30→5
    - Win ratio (35pt): high win rate = good recent execution
      > 70%→35, > 60%→25, > 50%→15, <= 50%→5
    - Momentum bonus (up to +15): positive avg_monthly_return adds confidence
    """
    score = 0.0

    if weeks is not None and weeks > 0:
        if weeks >= 156:
            score += 30.0
        elif weeks >= 52:
            score += 18.0
        elif weeks >= 26:
            score += 8.0

    if volatility is not None and volatility > 0:
        v = float(volatility)
        if v < 10.0:
            score += 35.0
        elif v < 20.0:
            score += 25.0
        elif v < 30.0:
            score += 15.0
        else:
            score += 5.0

    if win_ratio is not None and win_ratio > 0:
        wr = float(win_ratio)
        if wr >= 70.0:
            score += 35.0
        elif wr >= 60.0:
            score += 25.0
        elif wr >= 50.0:
            score += 15.0
        else:
            score += 5.0

    if avg_monthly_return is not None and float(avg_monthly_return) > 0:
        score = min(100.0, score + 15.0)

    return round(min(100.0, score), 1)


# ── Weights (0-1) ────────────────────────────────────────────────

RETURN_WEIGHT = 0.25
RISK_ADJ_WEIGHT = 0.25
CONSISTENCY_WEIGHT = 0.20
DRAWDOWN_WEIGHT = 0.15
RISK_WEIGHT = 0.10
TREND_WEIGHT = 0.05


def _confidence_label(profile: TraderProfile) -> str:
    """HIGH if all 5 core metrics present, MEDIUM if 3-4, LOW if <3."""
    core_metrics = [
        profile.raw_total_return_pct is not None,
        profile.raw_risk_score is not None and profile.raw_risk_score > 0,
        profile.raw_peak_to_valley is not None,
        profile.raw_profitable_months_pct is not None,
        profile.raw_weeks_since_registration is not None,
    ]
    present = sum(core_metrics)
    if present >= 4:
        return "HIGH"
    if present >= 2:
        return "MEDIUM"
    return "LOW"


# ── Core scoring ─────────────────────────────────────────────────


def calculate_score_from_profile(profile: TraderProfile) -> TraderProfile:
    """Score a trader across 6 weighted components (each 0-100).

    Return (25%) + RiskAdj (25%) + Consistency (20%)
    + Drawdown (15%) + Risk (10%) + Trend (5%).
    Total 0-100. Score 80+ = excellent, 70+ = good, 55+ = average.
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

    # ── 1. Return component (0-100, weight 25%) ───────────────────
    best_return = _best_return_pct(profile)
    ret_score = _return_component(best_return)

    # ── 2. Risk-adjusted return (0-100, weight 25%) ───────────────
    dd = profile.raw_peak_to_valley
    ra_score = _risk_adjusted_component(best_return, dd)

    # ── 3. Consistency (0-100, weight 20%) ────────────────────────
    prof_months = profile.raw_profitable_months_pct
    cons_score = _consistency_component(prof_months)

    # ── 4. Drawdown control (0-100, weight 15%) ──────────────────
    dd_score = _drawdown_component(dd)

    # ── 5. Risk score (0-100, weight 10%) ─────────────────────────
    risk = profile.raw_risk_score
    risk_score_val = _risk_component(risk)

    # ── 6. Trend (0-100, weight 5%) ──────────────────────────────
    weeks = profile.raw_weeks_since_registration
    vol = profile.raw_volatility
    win = profile.raw_win_ratio
    avg_monthly = profile.raw_avg_monthly_return
    trend_score = _trend_component(weeks, vol, win, avg_monthly)

    # ── Weighted total ───────────────────────────────────────────
    total_score = (
        ret_score * RETURN_WEIGHT
        + ra_score * RISK_ADJ_WEIGHT
        + cons_score * CONSISTENCY_WEIGHT
        + dd_score * DRAWDOWN_WEIGHT
        + risk_score_val * RISK_WEIGHT
        + trend_score * TREND_WEIGHT
    )
    total_score = min(100.0, total_score)

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
        f"drawdown={abs(dd):.1f}%" if dd else "drawdown=none",
        f"consistency={prof_months:.0f}%" if prof_months else "consistency=none",
        f"experience={weeks}w" if weeks else "experience=none",
    ]

    # Store sub-scores for explainability
    profile.norm_return_12m = ret_score
    profile.norm_return_6m = ra_score
    profile.norm_risk = risk_score_val
    profile.norm_drawdown = dd_score
    profile.norm_consistency = cons_score

    return profile


# ── Backward-compatible wrappers ─────────────────────────────────


def calculate_growth_score(trader: dict) -> dict:
    """Backward-compatible. Returns result dict with component breakdown."""
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
    dd = profile.raw_peak_to_valley

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
                "return": profile.norm_return_12m,
                "risk_adjusted": profile.norm_return_6m,
                "consistency": profile.norm_consistency,
                "drawdown": profile.norm_drawdown,
                "risk": profile.norm_risk,
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
