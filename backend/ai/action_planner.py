"""
Action Planner — builds the dashboard-ready output from all engine results.

Answers:
  - What changed?
  - Who is eligible now?
  - What should I do next?
  - Why was each trader included or excluded?

Output sections:
  Active Portfolio   — current copied traders with allocation and risk
  Discovery          — new eligible traders ranked by score
  Excluded           — why each trader was rejected (grouped by reason)
  Recommendations    — suggested swaps and equal-weight plan
  Summary            — compact debug report
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TARGET_COUNT = 3
TARGET_ALLOCATION_PCT = round(100.0 / TARGET_COUNT, 1)  # 33.3


def build_action_plan(
    portfolio_analysis: Dict,
    discovery_scored: List[Dict],
    excluded: List[Dict],
    holdings: List[Dict],
) -> Dict:
    """Build the complete action plan from all engine outputs.

    Args:
        portfolio_analysis: Output from portfolio_engine.analyze_portfolio().
        discovery_scored: Scored discovery candidates (from scoring_engine).
        excluded: Excluded candidates with reasons (from eligibility_engine).
        holdings: Raw active holdings list.

    Returns:
        Dict with dashboard-ready sections.
    """
    # ── 1. Active Portfolio ──
    active_section = []
    for h in portfolio_analysis.get("holdings_detail", []):
        active_section.append({
            "username": h["username"],
            "allocation_pct": h["allocation_pct"],
            "value_pct": h["allocation_pct"],
            "risk_score": h["risk_score"],
            "total_return_pct": h["total_return_pct"],
            "final_score": h["final_score"],
            "max_drawdown": h["max_drawdown"],
        })

    # ── 2. Discovery (new eligible, ranked) ──
    discovery_ranked = sorted(
        [s for s in discovery_scored if s.get("score", 0) > 0],
        key=lambda x: x.get("score", 0),
        reverse=True,
    )
    discovery_section = []
    for s in discovery_ranked:
        discovery_section.append({
            "username": s.get("username", "?"),
            "score": s.get("score", 0),
            "source": s.get("source", "unknown"),
            "confidence": s.get("confidence_score", 0),
            "source_valid": s.get("source_valid", False),
            "explanation": s.get("explanation", []),
            "details": {
                "return_12m": s.get("details", {}).get("return_12m", 0),
                "risk_score": s.get("details", {}).get("risk_score"),
                "max_drawdown": s.get("details", {}).get("max_drawdown", 0),
            },
        })

    # ── 3. Excluded (grouped by reason) ──
    excluded_grouped: Dict[str, List[str]] = {}
    for e in excluded:
        reasons = e.get("exclusion_reasons", [])
        for r in reasons:
            key = r.split("(")[0].strip()
            if key not in excluded_grouped:
                excluded_grouped[key] = []
            excluded_grouped[key].append(e.get("username", "?"))

    excluded_section = []
    for reason, usernames in sorted(excluded_grouped.items()):
        excluded_section.append({
            "reason": reason,
            "count": len(usernames),
            "traders": sorted(usernames),
        })

    # ── Quality gate: too few high-confidence traders ──
    quality_gate_message = None
    if len(discovery_section) < 2 and len(eligible_candidates := [s for s in discovery_scored if s.get("score", 0) > 0]) < 2:
        total_excluded = sum(g["count"] for g in excluded_section)
        total_scanned = total_excluded + len(discovery_scored)
        quality_gate_message = (
            f"No high-confidence traders found today. "
            f"Only {len(discovery_section)} trader(s) met quality requirements "
            f"out of {total_scanned} scanned."
        )
        logger.warning("Quality gate: %s", quality_gate_message)

    # ── 5. Recommendations ──
    recommended_swap = None
    equal_weight_plan = []
    weakest = portfolio_analysis.get("weakest")

    if discovery_ranked and weakest:
        best = discovery_ranked[0]
        if best.get("score", 0) > weakest.get("final_score", 0):
            recommended_swap = {
                "replace": weakest["username"],
                "with": best["username"],
                "reason": (
                    f"{best['username']} ({best['score']}/100) "
                    f"scores higher than {weakest['username']} "
                    f"({weakest['final_score']}/100)"
                ),
                "delta": round(best["score"] - weakest["final_score"], 1),
            }

    # Equal-weight plan: combine current weakest + top 2 discovery
    eq_targets = []
    if weakest:
        eq_targets.append({
            "username": weakest["username"],
            "allocation_pct": TARGET_ALLOCATION_PCT,
            "source": "current",
        })
    for s in discovery_ranked[:2]:
        eq_targets.append({
            "username": s["username"],
            "allocation_pct": TARGET_ALLOCATION_PCT,
            "source": "discovery",
            "score": s["score"],
        })

    if eq_targets:
        equal_weight_plan = eq_targets[:3]
        # Pad with more discovery if less than 3
        while len(equal_weight_plan) < 3 and len(discovery_ranked) >= len(equal_weight_plan) + 1:
            idx = len(equal_weight_plan)
            if idx < len(discovery_ranked):
                equal_weight_plan.append({
                    "username": discovery_ranked[idx]["username"],
                    "allocation_pct": TARGET_ALLOCATION_PCT,
                    "source": "discovery",
                    "score": discovery_ranked[idx]["score"],
                })
            else:
                break

    # ── 5. Summary ──
    total_scanned = (
        len(active_section)
        + len(discovery_section)
        + sum(g["count"] for g in excluded_section)
    )

    summary = (
        f"Portfolio: {len(active_section)} active, "
        f"{len(discovery_section)} eligible, "
        f"{sum(g['count'] for g in excluded_section)} excluded, "
        f"{total_scanned} total scanned. "
        f"{'Diversified' if not portfolio_analysis.get('under_diversified', True) else 'Under-diversified'}. "
        f"{'Concentration risk' if portfolio_analysis.get('concentration_risk', False) else 'No concentration risk'}. "
    )
    if quality_gate_message:
        summary += f" {quality_gate_message}"
    if recommended_swap:
        summary += f" Swap {recommended_swap['replace']} -> {recommended_swap['with']} (delta +{recommended_swap['delta']})."

    result = {
        "active_portfolio": active_section,
        "discovery": discovery_section,
        "excluded": excluded_section,
        "recommendations": {
            "recommended_swap": recommended_swap,
            "equal_weight_plan": equal_weight_plan,
        },
        "quality_gate_message": quality_gate_message,
        "summary": summary,
        "debug": {
            "active_count": len(active_section),
            "eligible_count": len(discovery_section),
            "excluded_count": sum(g["count"] for g in excluded_section),
            "total_scanned": total_scanned,
            "under_diversified": portfolio_analysis.get("under_diversified", True),
            "concentration_risk": portfolio_analysis.get("concentration_risk", False),
            "avg_score": portfolio_analysis.get("avg_score", 0),
        },
    }

    logger.info("Action plan built: %s", summary)
    return result


def format_display(action_plan: Dict) -> str:
    """Format the action plan into a Telegram/console-ready display string."""
    lines = []

    # Header
    lines.append("\U0001f4ca **Decision Dashboard**")
    lines.append("")

    # Active Portfolio
    active = action_plan.get("active_portfolio", [])
    lines.append(f"**Active Portfolio ({len(active)}):**")
    if active:
        for t in active:
            score = t.get("final_score", 0)
            icon = "\U0001f7e2" if score >= 60 else ("\U0001f7e1" if score >= 30 else "\U0001f534")
            lines.append(
                f"  {icon} {t['username']} \u2014 {score}/100"
                f" (alloc {t['allocation_pct']:.1f}%, risk {t['risk_score']:.1f})"
            )
    else:
        lines.append("  No active traders.")
    lines.append("")

    # Discovery
    discovery = action_plan.get("discovery", [])
    lines.append(f"**New Eligible Traders ({len(discovery)}):**")
    if discovery:
        for i, s in enumerate(discovery[:5], 1):
            expl = s.get("explanation", [])
            expl_str = f" \u2014 {'; '.join(str(e) for e in expl[:3])}" if expl else ""
            lines.append(
                f"  {i}. {s['username']} \u2014 {s['score']}/100"
                f" (src={s['source']}, conf={s['confidence']}){expl_str}"
            )
        if len(discovery) > 5:
            lines.append(f"  ... and {len(discovery) - 5} more")
    else:
        lines.append("  No eligible traders found.")
    lines.append("")

    # Excluded
    excluded = action_plan.get("excluded", [])
    if excluded:
        lines.append(f"**Excluded ({sum(g['count'] for g in excluded)}):**")
        for g in excluded[:4]:
            lines.append(f"  \u274c {g['reason']} ({g['count']}): {', '.join(g['traders'][:3])}")
            if len(g['traders']) > 3:
                lines.append(f"    ... and {len(g['traders']) - 3} more")
        if len(excluded) > 4:
            lines.append(f"  ... and {len(excluded) - 4} other exclusion reasons")
        lines.append("")

    # Recommendations
    recs = action_plan.get("recommendations", {})
    swap = recs.get("recommended_swap")
    eq_plan = recs.get("equal_weight_plan", [])

    if swap:
        lines.append("\U0001f3c6 **Recommended Swap:**")
        lines.append(f"  \U0001f519 {swap['replace']} \u2192 {swap['with']}")
        lines.append(f"  {swap['reason']}")
        lines.append("")

    if eq_plan:
        lines.append("**Equal-Weight Plan (target 33.3% each):**")
        for t in eq_plan:
            src_tag = "\U0001fa84" if t.get("source") == "discovery" else "\U0001f4cc"
            lines.append(f"  {src_tag} {t['username']} \u2014 {t['allocation_pct']}%")
        lines.append("")

    # Summary
    debug = action_plan.get("debug", {})
    qgm = action_plan.get("quality_gate_message")
    if qgm:
        lines.append("\u26a0\ufe0f **Quality Gate:**")
        lines.append(f"  {qgm}")
        lines.append("")
    lines.append(f"**Summary:** {action_plan.get('summary', '')}")
    lines.append(f"  Avg score: {debug.get('avg_score', 0)}/100")
    if debug.get("under_diversified"):
        lines.append("  \u26a0\ufe0f Under-diversified (less than 3 traders)")
    if debug.get("concentration_risk"):
        lines.append("  \u26a0\ufe0f Concentration risk (>40% in one trader)")

    return "\n".join(lines)


def summarize_constraints(trader: Dict) -> List[str]:
    """Return a list of constraint warnings for a trader (non-blocking, for display)."""
    warnings = []
    dd = trader.get("max_drawdown")
    if dd is not None and dd > 15:
        warnings.append(f"High drawdown ({dd:.1f}%)")
    risk = trader.get("risk_score")
    if risk is not None and risk > 7:
        warnings.append(f"High risk score ({float(risk):.1f})")
    vol = trader.get("volatility")
    if vol is not None and vol > 10:
        warnings.append(f"High volatility ({vol:.1f}%)")
    return warnings


def explain_recommendation(trader: Dict) -> List[str]:
    """Generate human-readable reasons why a trader was recommended."""
    reasons = []
    perf = trader.get("performance_score", 0)
    risk_cat = trader.get("risk_score_category", 0)
    rtrn = trader.get("total_return_pct")
    risk = trader.get("risk_score")
    dd = trader.get("max_drawdown")
    vol = trader.get("volatility")
    monthly = trader.get("avg_monthly_return") or trader.get("avg_return")
    min_copy = trader.get("min_copy_amount")
    sharpe = trader.get("sharpe_score")
    copiers = trader.get("copiers")

    if rtrn is not None and rtrn > 15:
        reasons.append(f"Strong {rtrn:.1f}% return")
    elif rtrn is not None and rtrn > 5:
        reasons.append(f"Positive {rtrn:.1f}% return")
    if dd is not None and dd < 10:
        reasons.append(f"Low drawdown ({dd:.1f}%)")
    if risk is not None and risk <= 5:
        reasons.append(f"Risk score within range ({risk:.1f})")
    if min_copy is not None and min_copy <= 500:
        reasons.append(f"Affordable to copy (${min_copy:.0f} minimum)")
    elif min_copy is not None and min_copy <= 2000:
        reasons.append(f"Copiable with ${min_copy:.0f} minimum")
    if monthly is not None and monthly > 0.5:
        reasons.append(f"Consistent monthly returns ({monthly:.2f}%)")
    if sharpe is not None and sharpe > 1.0:
        reasons.append(f"Strong risk-adjusted returns (Sharpe {sharpe:.2f})")
    if copiers is not None and copiers > 1000:
        reasons.append(f"Popular with {copiers}+ copiers")
    trade_freq = trader.get("trade_frequency")
    if trade_freq is not None and 1 <= trade_freq <= 5:
        reasons.append("Stable trade frequency")
    if perf >= 60:
        reasons.append("High performance score")
    if risk_cat >= 60:
        reasons.append("Low risk profile")

    reasons.append("Not already copied")
    return reasons


def explain_exclusion(excluded: Dict) -> List[str]:
    """Format exclusion reasons for display."""
    reasons = excluded.get("exclusion_reasons", [])
    if not reasons:
        raw = excluded.get("exclusion_reason", "")
        reasons = [raw] if raw else ["unknown"]
    return reasons
