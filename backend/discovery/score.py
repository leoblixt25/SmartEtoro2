"""Pure scoring functions — no I/O, no side effects.

Weighted component scoring (each component 0-100):
  - Return (25%):        sqrt curve — 10*sqrt(return), capped at 100
  - Risk-Adjusted (25%): return / max(drawdown, 5), 25*sqrt(ratio), capped at 100
  - Consistency (20%):   profitableMonthsPct linear from 30% floor
  - Drawdown (15%):      linear penalty — 3.3pt per % above 5
  - Risk Score (10%):    linear penalty — 15pt per risk point
  - Trend (5%):          experience + stability + win rate

When a component has no data, its weight is redistributed proportionally
to components that DO have data. This prevents data sparsity from
capping the total score.

Target score bands (with full data):
  80-90 excellent, 70-79 strong, 55-69 average, <55 weak
"""

from __future__ import annotations
import math
import logging
from typing import Optional, List
from backend.discovery.types import TraderProfile
from backend.discovery.validate import validate_data_source, check_constraints
from backend.discovery.validate import build_trader_profile

logger = logging.getLogger(__name__)


# ── Base weights (sum = 1.0) ──────────────────────────────────────

BASE_WEIGHTS = {
    "return": 0.25,
    "risk_adjusted": 0.25,
    "consistency": 0.20,
    "drawdown": 0.15,
    "risk": 0.10,
    "trend": 0.05,
}


def _available_weights(profile: TraderProfile) -> dict:
    """Return effective weights, redistributing missing-component weight.

    'Missing' means the underlying raw field is None.
    Distribution is proportional to the base weight of present components.
    """
    present: List[str] = []

    def _has(key: str) -> bool:
        return getattr(profile, f"raw_{key}", None) is not None

    # map component → field(s) to check
    checks = {
        "return": lambda: _has("return_12m") or _has("total_return_pct") or _has("avg_monthly_return"),
        "risk_adjusted": lambda: (_has("return_12m") or _has("total_return_pct")) and _has("peak_to_valley"),
        "consistency": lambda: _has("profitable_months_pct"),
        "drawdown": lambda: _has("peak_to_valley"),
        "risk": lambda: _has("risk_score"),
        "trend": lambda: _has("weeks_since_registration") or _has("volatility") or _has("win_ratio"),
    }

    for comp, check in checks.items():
        if check():
            present.append(comp)

    if not present:
        return {k: v for k, v in BASE_WEIGHTS.items()}

    total_base = sum(BASE_WEIGHTS[c] for c in present)
    return {c: BASE_WEIGHTS[c] / total_base for c in present}


# ── Backward-compat helpers ───────────────────────────────────────


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


# ── Helpers ───────────────────────────────────────────────────────


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

    0%→0, 25%→50, 50%→71, 100%→100, 150%→100, 200%+→100.
    """
    if best_return is None or best_return <= 0:
        return 0.0
    return round(min(100.0, 10.0 * math.sqrt(float(best_return))), 1)


def _risk_adjusted_component(
    best_return: Optional[float],
    drawdown: Optional[float],
) -> float:
    """Risk-adjusted return 0-100. return / max(dd, 5), sqrt curve.

    Ratio→Score:
      2→35, 5→56, 8→71, 12→87, 16→100
    """
    if best_return is None or best_return <= 0:
        return 0.0
    dd = _safe_drawdown(drawdown)
    if dd < 5.0:
        dd = 5.0
    ratio = float(best_return) / dd
    if ratio < 1.5:
        return 0.0
    return round(min(100.0, 25.0 * math.sqrt(min(ratio, 25.0))), 1)


def _consistency_component(profitable_months_pct: Optional[float]) -> float:
    """Consistency score 0-100. Linear from 30% floor.

    <30%→0, 50%→29, 60%→43, 70%→57, 80%→71, 90%→86, 100%→100
    """
    if profitable_months_pct is None:
        return 0.0
    pct = float(profitable_months_pct)
    if pct < 30.0:
        return 0.0
    return round(min(100.0, (pct - 30.0) * 1.43), 1)


def _drawdown_component(peak_to_valley: Optional[float]) -> float:
    """Drawdown score 0-100. Linear: -3.3pt per % above 5.

    5%→95, 10%→83, 15%→67, 20%→50, 25%→34, 30%→17, 35%→0
    """
    dd = _safe_drawdown(peak_to_valley)
    if dd > 35.0:
        return 0.0
    if dd < 5.0:
        return 95.0
    return round(max(0.0, 100.0 - 3.3 * (dd - 5.0)), 1)


def _risk_component(risk: Optional[float]) -> float:
    """Risk score 0-100. Linear: -15pt per risk point.

    1→100, 2→85, 3→70, 4→55, 5→40, 6→25, 7→10, 8+→0
    """
    if risk is None or risk < 1 or risk > 10:
        return 0.0
    return round(max(0.0, 115.0 - float(risk) * 15.0), 1)


def _trend_component(
    weeks: Optional[int],
    volatility: Optional[float],
    win_ratio: Optional[float],
    avg_monthly_return: Optional[float],
) -> float:
    """Trend score 0-100. Experience + stability + win rate + momentum.

    - Experience (30pt): weeks >= 156→30, >= 52→18, >= 26→8
    - Stability (35pt): vol < 10→35, < 20→25, < 30→15, >= 30→5
    - Win ratio (35pt): > 70%→35, > 60%→25, > 50%→15, <= 50%→5
    - Momentum bonus (+15): positive avg_monthly_return
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

    Missing-data weights are redistributed proportionally.
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

    # ── 1. Return component (0-100) ───────────────────────────────
    best_return = _best_return_pct(profile)
    ret_score = _return_component(best_return)

    # ── 2. Risk-adjusted return (0-100) ───────────────────────────
    dd = profile.raw_peak_to_valley
    ra_score = _risk_adjusted_component(best_return, dd)

    # ── 3. Consistency (0-100) ────────────────────────────────────
    prof_months = profile.raw_profitable_months_pct
    cons_score = _consistency_component(prof_months)

    # ── 4. Drawdown control (0-100) ──────────────────────────────
    dd_score = _drawdown_component(dd)

    # ── 5. Risk score (0-100) ─────────────────────────────────────
    risk = profile.raw_risk_score
    risk_score_val = _risk_component(risk)

    # ── 6. Trend (0-100) ─────────────────────────────────────────
    weeks = profile.raw_weeks_since_registration
    vol = profile.raw_volatility
    win = profile.raw_win_ratio
    avg_monthly = profile.raw_avg_monthly_return
    trend_score = _trend_component(weeks, vol, win, avg_monthly)

    # ── Weighted total with redistribution ───────────────────────
    component_scores = {
        "return": ret_score,
        "risk_adjusted": ra_score,
        "consistency": cons_score,
        "drawdown": dd_score,
        "risk": risk_score_val,
        "trend": trend_score,
    }

    weights = _available_weights(profile)

    total_score = 0.0
    for comp, w in weights.items():
        total_score += component_scores.get(comp, 0.0) * w
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
    """Backward-compatible wrapper. Scores discovery candidates."""
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
