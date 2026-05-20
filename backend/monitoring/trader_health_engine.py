"""
Trader Health Engine — evaluates each trader strictly on available data.

Rules:
  - If day/week/month all missing → INCOMPLETE (null score, REVIEW)
  - Missing risk/holdings/consistency → full marks, lower confidence
  - No news symbols → "unknown" news risk
  - Never assign a low score for missing data — only for real bad data
  - Never put INCOMPLETE traders in Avoid
"""

import logging
from typing import Dict, List, Optional, Tuple

from backend.monitoring.news_service import aggregate_sentiment

logger = logging.getLogger(__name__)

SCORE_STRONG = 80
SCORE_GOOD = 70
SCORE_WATCH = 60
SCORE_WEAK = 50

PERFORMANCE_MAX = 30
RISK_MAX = 25
NEWS_MAX = 20
CONCENTRATION_MAX = 15
CONSISTENCY_MAX = 10

DRAWDOWN_HIGH = 25.0
DRAWDOWN_ELEVATED = 15.0
RISK_HIGH = 8.0
RISK_ACCEPTABLE = 6.0
CONCENTRATION_HIGH = 40.0
CONSISTENCY_STABLE = 70.0
CONSISTENCY_MODERATE = 40.0

RECOMMENDATION_TO_SIGNAL = {
    "KEEP": "increase",
    "REDUCE": "reduce",
    "PAUSE": "watch",
    "REVIEW": "watch",
    "UNCOPY": "avoid",
}


def _is_real(val) -> bool:
    """Check if a value is actually populated (not None, not 0.0 default)."""
    if val is None:
        return False
    try:
        return float(val) != 0.0
    except (ValueError, TypeError):
        return True


def _has_clear_negative_risk(trader: Dict) -> bool:
    """Extreme risk evidence that can override missing perf data."""
    risk = trader.get("risk_score")
    dd = trader.get("max_drawdown")
    return _is_real(risk) and _is_real(dd) and float(risk) >= 8.0 and float(dd) >= 25.0


def _check_data_flags(trader: Dict, holdings: List[Dict]) -> Dict:
    return {
        "return_1d": _is_real(trader.get("return_1d")),
        "return_1w": _is_real(trader.get("return_1w")),
        "return_1m": _is_real(trader.get("return_1m")),
        "total_return": _is_real(trader.get("total_return_pct")) or _is_real(trader.get("return_12m")),
        "risk_score": _is_real(trader.get("risk_score")),
        "max_drawdown": _is_real(trader.get("max_drawdown")),
        "consistency": _is_real(trader.get("consistency_score")),
        "holdings": len(holdings) > 0,
    }


def _assess_data_quality(flags: Dict) -> str:
    has_any_perf = flags["return_1d"] or flags["return_1w"] or flags["return_1m"] or flags["total_return"]
    if not has_any_perf:
        return "insufficient"
    present = sum(1 for v in flags.values() if v)
    if present <= 2:
        return "low"
    elif present <= 4:
        return "medium"
    return "high"


def _score_performance(trader: Dict) -> Tuple[float, Dict]:
    ret_1d = trader.get("return_1d")
    ret_1w = trader.get("return_1w")
    ret_1m = trader.get("return_1m")
    total_ret_raw = trader.get("total_return_pct")
    if total_ret_raw is None:
        total_ret_raw = trader.get("return_12m")

    has_1d = _is_real(ret_1d)
    has_1w = _is_real(ret_1w)
    has_1m = _is_real(ret_1m)
    score = 0.0
    details = {}

    if has_1m:
        m = float(ret_1m)
        if m > 10:
            score += 14
        elif m > 5:
            score += 11
        elif m > 2:
            score += 8
        elif m > 0:
            score += 5
        elif m > -5:
            score += 2
        details["month"] = round(m, 2)

    if has_1w:
        w = float(ret_1w)
        if w > 5:
            score += 10
        elif w > 2:
            score += 7
        elif w > 0:
            score += 4
        elif w > -5:
            score += 1
        details["week"] = round(w, 2)

    if has_1d:
        d = float(ret_1d)
        if d > 3:
            score += 6
        elif d > 1:
            score += 4
        elif d > 0:
            score += 2
        elif d > -3:
            score += 0
        details["day"] = round(d, 2)

    if not has_1d and not has_1w and not has_1m:
        if total_ret_raw is not None:
            tr = float(total_ret_raw)
            if tr > 50:
                score = 26
            elif tr > 20:
                score = 20
            elif tr >= 10:
                score = 14
            elif tr > 0:
                score = 10
            elif tr > -20:
                score = 4
            else:
                score = 2
            details["overall"] = round(tr, 2)

    score = min(score, PERFORMANCE_MAX)
    return round(score, 1), details


def _score_risk(trader: Dict) -> Tuple[float, Dict]:
    dd_raw = trader.get("max_drawdown")
    risk_raw = trader.get("risk_score")
    vol_raw = trader.get("volatility")
    sharpe_raw = trader.get("sharpe_score")

    score = float(RISK_MAX)
    has_any = False
    details = {}

    if _is_real(dd_raw):
        has_any = True
        dd = float(dd_raw)
        if dd > DRAWDOWN_HIGH:
            score -= 10
            details["drawdown"] = {"value": round(dd, 1), "level": "High"}
        elif dd > DRAWDOWN_ELEVATED:
            score -= 5
            details["drawdown"] = {"value": round(dd, 1), "level": "Elevated"}
        else:
            details["drawdown"] = {"value": round(dd, 1), "level": "Low"}

    if _is_real(risk_raw):
        has_any = True
        risk = float(risk_raw)
        if risk > RISK_HIGH:
            score -= 8
            details["risk_score"] = {"value": round(risk, 1), "level": "High"}
        elif risk > RISK_ACCEPTABLE:
            score -= 4
            details["risk_score"] = {"value": round(risk, 1), "level": "Elevated"}
        else:
            details["risk_score"] = {"value": round(risk, 1), "level": "Low"}

    if _is_real(vol_raw):
        has_any = True
        vol = float(vol_raw)
        if vol > 50:
            score -= 4
            details["volatility"] = round(vol, 1)
        elif vol > 30:
            score -= 2
            details["volatility"] = round(vol, 1)

    if _is_real(sharpe_raw):
        has_any = True
        s = float(sharpe_raw)
        if s < 0:
            score -= 3
        elif s < 0.5:
            score -= 1
        details["sharpe"] = round(s, 2)

    if not has_any:
        score = float(RISK_MAX * 0.6)

    score = max(0, score)
    return round(score, 1), details


def _score_news(holdings: List[Dict], news_by_symbol: Dict) -> Tuple[float, Dict]:
    has_news = any(bool(v) for v in news_by_symbol.values())

    if not holdings or not has_news:
        return float(NEWS_MAX * 0.5), {"impact": "unknown", "details": "No recent news data"}

    sent = aggregate_sentiment(news_by_symbol)
    neg = sent.get("negative_symbols", [])
    pos = sent.get("positive_symbols", [])

    total_syms = len(set(h["symbol"] for h in holdings if h.get("symbol"))) or 1
    affected_neg = sum(1 for h in holdings if h.get("symbol", "").upper() in neg)
    affected_pos = sum(1 for h in holdings if h.get("symbol", "").upper() in pos)
    neg_ratio = affected_neg / total_syms
    pos_ratio = affected_pos / total_syms

    score = float(NEWS_MAX)
    if neg_ratio > 0.3:
        penalty = min(neg_ratio * 12, 12)
        score -= penalty
        impact = "negative"
    elif pos_ratio > 0.4:
        score = min(NEWS_MAX, score + 2)
        impact = "positive"
    elif pos_ratio > 0 and neg_ratio > 0:
        impact = "mixed"
    elif pos_ratio > 0:
        impact = "positive"
    else:
        impact = "neutral"

    score = max(0, min(NEWS_MAX, score))

    details = {
        "impact": impact,
        "positive_symbols": pos[:3],
        "negative_symbols": neg[:3],
        "details": f"{len(pos)} positive, {len(neg)} negative symbols",
    }
    return round(score, 1), details


def _score_concentration(holdings: List[Dict]) -> Tuple[float, Dict]:
    if not holdings:
        return float(CONCENTRATION_MAX * 0.5), {"top_holding": "N/A", "top_weight": 0, "warning": "No holdings data"}

    max_weight = max((h.get("weight", 0) for h in holdings), default=0)
    top = max(holdings, key=lambda h: h.get("weight", 0)) if holdings else {}

    score = float(CONCENTRATION_MAX)
    warnings = []

    if max_weight > CONCENTRATION_HIGH:
        score -= 10
        warnings.append(f"High concentration in {top.get('symbol', '?')} ({max_weight:.0f}%)")
    elif max_weight > 25:
        score -= 4
        warnings.append(f"Moderate concentration in {top.get('symbol', '?')} ({max_weight:.0f}%)")
    if len(holdings) <= 1:
        score -= 3
        warnings.append(f"Only {len(holdings)} holding")

    score = max(0, score)
    return round(score, 1), {"top_holding": top.get("symbol", "N/A"), "top_weight": round(max_weight, 1), "warning": warnings[0] if warnings else "Well diversified"}


def _score_consistency(trader: Dict) -> float:
    c = trader.get("consistency_score")
    if not _is_real(c):
        return float(CONSISTENCY_MAX * 0.4)
    c = float(c)
    if c >= CONSISTENCY_STABLE:
        return float(CONSISTENCY_MAX)
    elif c >= CONSISTENCY_MODERATE:
        return 6.0
    return 2.0


def _determine_confidence(flags: Dict, data_quality: str) -> str:
    if data_quality == "insufficient":
        return "INCOMPLETE"
    has_perf = flags["return_1d"] or flags["return_1w"] or flags["return_1m"] or flags["total_return"]
    has_risk = flags["risk_score"] or flags["max_drawdown"]
    key_present = sum([has_perf, has_risk, flags["holdings"], flags["consistency"]])
    if key_present <= 1:
        return "LOW"
    elif key_present <= 3:
        return "MEDIUM"
    return "HIGH"


def _health_status(score: float, confidence: str) -> str:
    if confidence == "INCOMPLETE":
        return "Incomplete"
    if score >= SCORE_STRONG:
        return "Strong"
    elif score >= SCORE_GOOD:
        return "Good"
    elif score >= SCORE_WATCH:
        return "Watch"
    elif score >= SCORE_WEAK:
        return "Weak"
    return "Avoid"


def _has_real_risk_data(trader: Dict) -> bool:
    return _is_real(trader.get("risk_score")) or _is_real(trader.get("max_drawdown"))


def _get_action(total: float, status: str, confidence: str, risk_detail: Dict, flags: Dict) -> str:
    if confidence == "INCOMPLETE":
        return "REVIEW"
    if status in ("Strong", "Good"):
        return "KEEP"
    if status == "Watch":
        return "REDUCE"
    if status == "Weak":
        return "PAUSE"
    # Avoid — UNCOPY only with clear negative evidence
    dd = risk_detail.get("drawdown", {})
    rs = risk_detail.get("risk_score", {})
    has_negative = dd.get("level") in ("High",) or rs.get("level") in ("High", "Critical")
    if has_negative:
        return "UNCOPY"
    return "REVIEW"


def _build_reason(status: str, action: str, perf_detail: Dict, risk_detail: Dict, flags: Dict) -> str:
    if action == "REVIEW":
        missing = [k for k in ["risk", "holdings", "consistency"]
                   if (k == "risk" and not (flags["risk_score"] or flags["max_drawdown"]))
                   or (k == "holdings" and not flags["holdings"])
                   or (k == "consistency" and not flags["consistency"])]
        if len(missing) >= 2:
            return "Limited data"
        return f"Missing: {', '.join(missing)}" if missing else "Limited data"
    if action == "PAUSE":
        parts = []
        dd = risk_detail.get("drawdown")
        if dd and dd.get("level") in ("Elevated", "High"):
            parts.append(f"DD {dd['value']:.0f}%")
        rs = risk_detail.get("risk_score")
        if rs and rs.get("level") in ("High", "Critical"):
            parts.append(f"Risk {rs['value']:.1f}")
        if not parts:
            m = perf_detail.get("month")
            if m is not None:
                parts.append(f"Mth: {m:+.1f}%")
            o = perf_detail.get("overall")
            if o is not None:
                parts.append(f"Ret: {o:+.1f}%")
        return " | ".join(parts) if parts else "Volatile"
    parts = []
    m = perf_detail.get("month")
    if m is not None:
        parts.append(f"Mth: {m:+.1f}%")
    o = perf_detail.get("overall")
    if o is not None:
        parts.append(f"Ret: {o:+.1f}%")
    if not parts:
        return "Stable"
    return " | ".join(parts)


def _confidence_to_float(confidence: str) -> float:
    return {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5, "INCOMPLETE": 0.3}.get(confidence, 0.5)


def _insufficient_result(username: str, holdings: List[Dict], news_by_symbol: Dict, trader: Optional[Dict] = None) -> Dict:
    has_news = any(bool(v) for v in news_by_symbol.values())
    return {
        "name": username,
        "trader": username,
        "score": None,
        "health_score": None,
        "confidence": "INCOMPLETE",
        "confidence_label": "INSUFFICIENT",
        "data_quality": "insufficient",
        "status": "Incomplete",
        "health_status": "Incomplete",
        "action": "REVIEW",
        "recommendation": "REVIEW",
        "signal": "watch",
        "performance": {"day": None, "week": None, "month": None},
        "performance_summary": {"day": None, "week": None, "month": None, "overall_return": None},
        "risk_analysis": {"note": "No data"},
        "news_exposure": {"level": "unknown", "summary": ""},
        "news_analysis": {"impact": "unknown", "details": "No data"},
        "total_return_pct": trader.get("total_return_pct") if trader else None,
        "allocation_pct": trader.get("allocation_pct") if trader else None,
        "reason": "insufficient performance data",
        "reasons": ["Insufficient performance data"],
        "warning_signs": [],
        "holdings_health": None,
        "holdings_count": len(holdings),
        "holdings_source": "unknown",
        "top_negative_holdings": [],
        "top_positive_holdings": [],
        "news_exists": has_news,
        "performance_score": 0,
    }


def analyze_trader_health(trader: Dict, holdings: List[Dict], news_by_symbol: Dict) -> Dict:
    username = trader.get("username", "?")

    flags = _check_data_flags(trader, holdings)
    data_quality = _assess_data_quality(flags)

    if data_quality == "insufficient":
        if _has_clear_negative_risk(trader):
            data_quality = "low"
        else:
            return _insufficient_result(username, holdings, news_by_symbol, trader)

    perf_score, perf_detail = _score_performance(trader)
    risk_score_val, risk_detail = _score_risk(trader)
    news_score, news_detail = _score_news(holdings, news_by_symbol)
    conc_score, conc_detail = _score_concentration(holdings)
    cons_score = _score_consistency(trader)

    total = perf_score + risk_score_val + news_score + conc_score + cons_score
    total = max(0, min(100, total))

    confidence = _determine_confidence(flags, data_quality)
    status = _health_status(total, confidence)
    action = _get_action(total, status, confidence, risk_detail, flags)
    signal = RECOMMENDATION_TO_SIGNAL.get(action, "watch")
    reason = _build_reason(status, action, perf_detail, risk_detail, flags)

    impact = news_detail.get("impact", "unknown")
    news_risk = "high" if impact == "negative" else ("medium" if impact == "mixed" else ("unknown" if impact == "unknown" else "low"))

    has_news = any(bool(v) for v in news_by_symbol.values())

    reasons_list = [f"Score: {round(total)}/100 ({status})", f"Action: {action}"]
    if reason:
        reasons_list.append(reason)

    return {
        "name": username,
        "trader": username,
        "score": round(total),
        "health_score": round(total),
        "confidence": confidence,
        "confidence_label": confidence.title() if confidence != "INCOMPLETE" else "INSUFFICIENT",
        "status": status,
        "health_status": status,
        "data_quality": data_quality,
        "data_flags": flags,
        "action": action,
        "recommendation": action,
        "signal": signal,
        "performance": {"day": perf_detail.get("day"), "week": perf_detail.get("week"), "month": perf_detail.get("month")},
        "performance_summary": {"day": {"return_pct": perf_detail.get("day")} if perf_detail.get("day") else None,
                                "week": {"return_pct": perf_detail.get("week")} if perf_detail.get("week") else None,
                                "month": {"return_pct": perf_detail.get("month")} if perf_detail.get("month") else None,
                                "overall_return": perf_detail.get("overall")},
        "risk_analysis": risk_detail,
        "portfolio_concentration": conc_detail,
        "risk": {"drawdown": risk_detail.get("drawdown"), "risk_score": risk_detail.get("risk_score"),
                 "leverage": None, "concentration": conc_detail.get("top_weight")},
        "news_exposure": {"level": news_risk, "summary": news_detail.get("details", "")},
        "news_analysis": {"impact": news_detail.get("impact", "neutral"), "details": news_detail.get("details", "")},
        "total_return_pct": trader.get("total_return_pct"),
        "allocation_pct": trader.get("allocation_pct"),
        "reason": reason,
        "reasons": reasons_list,
        "warning_signs": [],
        "holdings_health": round(total),
        "holdings_count": len(holdings),
        "holdings_source": trader.get("_holdings_source", "unknown"),
        "performance_score": round(perf_score, 1),
        "top_negative_holdings": [s.upper() for s in news_detail.get("negative_symbols", [])],
        "top_positive_holdings": [s.upper() for s in news_detail.get("positive_symbols", [])],
        "news_exists": has_news,
    }
