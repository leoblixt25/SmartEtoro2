"""
Trader Health Engine — combines performance, risk, and news into a health score and recommendation.

Health Score (0-100):
  - Performance (0-30): day/week/month returns
  - Risk (0-25): drawdown, risk score, leverage, stability
  - News Impact (0-20): sentiment analysis of holdings news
  - Portfolio Concentration (0-15): top holding weight, diversification
  - Consistency (0-10): stability of returns

Score → Status → Recommendation:
  80-100  Strong  → KEEP
  70-79   Good    → KEEP
  60-69   Watch   → REDUCE COPY AMOUNT
  50-59   Weak    → PAUSE
  0-49    Avoid   → UNCOPY

Backward-compat fields kept for monitoring pipeline:
  - `signal` → maps recommendation to old values (increase/reduce/avoid/watch)
  - `confidence` → 0-1 float derived from health_score
  - `holdings_health` → mirrors health_score
  - `performance_score` → performance component score
  - `reasons` → generated reasons
  - `top_negative/positive_holdings` → from news analysis
"""

import logging
from typing import Dict, List, Tuple

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

RISK_HIGH = 8.0
RISK_ACCEPTABLE = 6.0
DRAWDOWN_HIGH = 25.0
DRAWDOWN_ELEVATED = 15.0
LEVERAGE_HIGH = 3.0
CONCENTRATION_HIGH = 40.0
CONSISTENCY_STABLE = 70.0
CONSISTENCY_MODERATE = 40.0
NEGATIVE_NEWS_RATIO = 0.3

RECOMMENDATION_TO_SIGNAL = {
    "KEEP": "increase",
    "REDUCE": "reduce",
    "PAUSE": "watch",
    "REVIEW": "watch",
    "UNCOPY": "avoid",
}


def _score_performance(trader: Dict) -> Tuple[float, Dict]:
    ret_1d = trader.get("return_1d")
    ret_1w = trader.get("return_1w")
    ret_1m = trader.get("return_1m")
    ret_12m_raw = trader.get("total_return_pct")
    if ret_12m_raw is None:
        ret_12m_raw = trader.get("return_12m")
    ret_12m = float(ret_12m_raw) if ret_12m_raw is not None else 0.0
    win_rate_raw = trader.get("win_rate")
    win_rate = float(win_rate_raw) if win_rate_raw is not None else None

    score = 0.0
    has_any_perf = False

    if ret_1d is not None:
        has_any_perf = True
        d = float(ret_1d)
        if d > 2:
            day_label = "up"
            score += 10
        elif d > 0:
            day_label = "up"
            score += 6
        elif d < -2:
            day_label = "down"
        else:
            day_label = "flat"
            score += 3
    else:
        day_label = "N/A"

    if ret_1w is not None:
        has_any_perf = True
        w = float(ret_1w)
        if w > 5:
            week_label = "up"
            score += 10
        elif w > 0:
            week_label = "up"
            score += 7
        elif w < -5:
            week_label = "down"
        else:
            week_label = "flat"
            score += 3
    else:
        week_label = "N/A"

    if ret_1m is not None:
        has_any_perf = True
        m = float(ret_1m)
        if m > 10:
            month_label = "up"
            score += 10
        elif m > 0:
            month_label = "up"
            score += 7
        elif m < -10:
            month_label = "down"
        else:
            month_label = "flat"
            score += 3
    else:
        month_label = "N/A"

    if not has_any_perf and ret_12m_raw is not None:
        fallback_label = "up" if ret_12m > 5 else ("down" if ret_12m < -5 else "flat")
        if ret_12m > 50:
            score = 22
        elif ret_12m > 20:
            score = 18
        elif ret_12m > 5:
            score = 14
        elif ret_12m > 0:
            score = 10
        elif ret_12m > -20:
            score = 6
        else:
            score = 2
        month_label = f"est.{fallback_label}"
    elif not has_any_perf:
        score = 6
        month_label = "insufficient"

    score = min(score, PERFORMANCE_MAX)

    details = {
        "day": {"return_pct": float(ret_1d) if ret_1d is not None else None, "label": day_label},
        "week": {"return_pct": float(ret_1w) if ret_1w is not None else None, "label": week_label},
        "month": {"return_pct": float(ret_1m) if ret_1m is not None else None, "label": month_label},
        "overall_return": round(ret_12m, 2) if ret_12m_raw is not None else None,
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
    }
    return score, details


def _score_risk(trader: Dict) -> Tuple[float, Dict]:
    risk_raw = trader.get("risk_score")
    dd_raw = trader.get("max_drawdown")
    leverage = float(trader.get("leverage", 0) or 0)
    consistency_raw = trader.get("consistency_score")

    score = RISK_MAX

    if dd_raw is not None:
        dd = float(dd_raw)
        if dd > DRAWDOWN_HIGH:
            score -= 10
            dd_label = "High"
        elif dd > DRAWDOWN_ELEVATED:
            score -= 5
            dd_label = "Moderate"
        else:
            dd_label = "Low"
    else:
        dd = None
        dd_label = "Unknown"
        score -= 2

    if risk_raw is not None:
        risk = float(risk_raw)
        if risk > RISK_HIGH:
            score -= 8
            risk_label = "High"
        elif risk > RISK_ACCEPTABLE:
            score -= 4
            risk_label = "Moderate"
        else:
            risk_label = "Low"
    else:
        risk = None
        risk_label = "Unknown"
        score -= 3

    if leverage > LEVERAGE_HIGH:
        score -= 5
    elif leverage > 2:
        score -= 2

    if consistency_raw is not None:
        consistency = float(consistency_raw)
        if consistency >= CONSISTENCY_STABLE:
            stability = "Stable"
        elif consistency >= CONSISTENCY_MODERATE:
            stability = "Moderate"
        else:
            stability = "Volatile"
            score -= 2
    else:
        consistency = None
        stability = "Unknown"

    score = max(0, score)

    details = {
        "max_drawdown": round(dd, 1) if dd is not None else None,
        "drawdown_label": dd_label,
        "risk_score": round(risk, 1) if risk is not None else None,
        "risk_label": risk_label,
        "leverage": round(leverage, 1),
        "stability": stability,
        "consistency_score": round(consistency, 1) if consistency is not None else None,
    }
    return score, details


def _score_news(holdings: List[Dict], news_by_symbol: Dict[str, List[Dict]]) -> Tuple[float, Dict]:
    has_news = any(bool(v) for v in news_by_symbol.values())

    if not holdings or not has_news:
        return 10.0, {"impact": "neutral", "details": "No recent news data available"}

    sent = aggregate_sentiment(news_by_symbol)
    neg_symbols = sent.get("negative_symbols", [])
    pos_symbols = sent.get("positive_symbols", [])

    total_syms = len(set(h["symbol"] for h in holdings if h.get("symbol"))) or 1
    affected_neg = sum(1 for h in holdings if h.get("symbol", "").upper() in neg_symbols)
    affected_pos = sum(1 for h in holdings if h.get("symbol", "").upper() in pos_symbols)
    neg_ratio = affected_neg / total_syms
    pos_ratio = affected_pos / total_syms

    score = NEWS_MAX

    if neg_ratio > NEGATIVE_NEWS_RATIO:
        penalty = min(neg_ratio * 15, 15)
        score -= penalty
        impact = "negative"
    elif pos_ratio > 0.4:
        score = min(NEWS_MAX, score + 3)
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
        "positive_symbols": pos_symbols[:5],
        "negative_symbols": neg_symbols[:5],
        "details": f"{len(pos_symbols)} positive, {len(neg_symbols)} negative symbols",
    }
    return score, details


def _score_concentration(holdings: List[Dict]) -> Tuple[float, Dict, List[str]]:
    warnings = []
    if not holdings:
        return 7.5, {"top_holding": "N/A", "top_weight": 0, "warning": "No holdings data"}, warnings

    max_weight = max((h.get("weight", 0) for h in holdings), default=0)
    top = max(holdings, key=lambda h: h.get("weight", 0)) if holdings else {}

    score = CONCENTRATION_MAX

    if max_weight > CONCENTRATION_HIGH:
        score -= 10
        warnings.append(f"High concentration in {top.get('symbol', '?')} ({max_weight:.0f}%)")
    elif max_weight > 25:
        score -= 4
        warnings.append(f"Moderate concentration in {top.get('symbol', '?')} ({max_weight:.0f}%)")

    if len(holdings) <= 1:
        score -= 3
        warnings.append(f"Only {len(holdings)} holding - low diversification")

    score = max(0, score)

    details = {
        "top_holding": top.get("symbol", "N/A"),
        "top_weight": round(max_weight, 1),
        "warning": warnings[0] if warnings else "Well diversified",
    }
    return score, details, warnings


def _score_consistency(trader: Dict) -> float:
    consistency_raw = trader.get("consistency_score")
    if consistency_raw is None:
        return 4.0
    consistency = float(consistency_raw)
    if consistency >= CONSISTENCY_STABLE:
        return 10.0
    elif consistency >= CONSISTENCY_MODERATE:
        return 6.0
    return 2.0


def _health_status(score: float) -> str:
    if score >= SCORE_STRONG:
        return "Strong"
    elif score >= SCORE_GOOD:
        return "Good"
    elif score >= SCORE_WATCH:
        return "Watch"
    elif score >= SCORE_WEAK:
        return "Weak"
    return "Avoid"


def _assess_data_quality(trader: Dict, holdings: List[Dict]) -> Tuple[str, Dict]:
    flags = {}
    has_perf = (
        trader.get("return_1d") is not None
        or trader.get("return_1w") is not None
        or trader.get("return_1m") is not None
        or trader.get("total_return_pct") is not None
        or trader.get("return_12m") is not None
    )
    flags["performance"] = has_perf
    flags["risk"] = trader.get("risk_score") is not None or trader.get("max_drawdown") is not None
    flags["holdings"] = len(holdings) > 0
    flags["consistency"] = trader.get("consistency_score") is not None

    available = sum(1 for v in flags.values() if v)
    if available <= 1:
        level = "insufficient" if available == 0 else "low"
    elif available == 2:
        level = "medium"
    else:
        level = "high"
    return level, flags


def _get_recommendation(score: float, status: str, data_quality: str) -> str:
    if data_quality == "insufficient":
        return "REVIEW"
    if status in ("Strong", "Good"):
        return "KEEP"
    if data_quality == "low":
        return "REVIEW" if status in ("Watch", "Weak", "Avoid") else "KEEP"
    if status == "Watch":
        return "REDUCE"
    if status == "Weak":
        return "PAUSE"
    return "UNCOPY" if data_quality in ("high", "medium") else "REVIEW"


def _confidence_label(data_quality: str) -> str:
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(data_quality, "INSUFFICIENT")


def _collect_warnings(
    risk_details: Dict,
    conc_warnings: List[str],
    holdings: List[Dict],
    news_details: Dict,
) -> List[str]:
    warnings = list(conc_warnings)
    if risk_details.get("drawdown_label") in ("High",):
        dd_v = risk_details.get("max_drawdown")
        if dd_v is not None:
            warnings.append(f"Max drawdown is high ({dd_v:.0f}%)")
        else:
            warnings.append("Max drawdown is high")
    if risk_details.get("drawdown_label") == "Unknown":
        warnings.append("Max drawdown unknown - reduced confidence")
    if risk_details.get("risk_label") == "High":
        r_v = risk_details.get("risk_score")
        if r_v is not None:
            warnings.append(f"Risk score is high ({r_v:.1f})")
    if risk_details.get("risk_label") == "Unknown":
        warnings.append("Risk score unknown - reduced confidence")
    if risk_details.get("stability") == "Volatile":
        warnings.append("Returns are volatile with low consistency")
    if risk_details.get("stability") == "Unknown":
        warnings.append("Consistency unknown - reduced confidence")
    if risk_details.get("leverage", 0) > LEVERAGE_HIGH:
        warnings.append(f"Leverage is high ({risk_details['leverage']:.1f}x)")
    if not holdings:
        warnings.append("No holdings data - reduced confidence")
    if news_details.get("impact") == "negative":
        warnings.append("Negative news affecting holdings")
    return warnings[:5]


def _build_reasons(
    status: str,
    perf_score: float,
    risk_details: Dict,
    news_details: Dict,
    recommendation: str,
    health_score: float,
) -> List[str]:
    rl = risk_details.get("risk_label", "N/A")
    rs = risk_details.get("risk_score")
    risk_str = f"Risk: {rl}" + (f" ({rs:.1f})" if rs is not None else "")
    reasons = [
        f"Health score: {health_score:.0f}/100 ({status})",
        f"Performance: {perf_score:.0f}/{PERFORMANCE_MAX}",
        risk_str,
    ]
    ri = news_details.get("impact", "neutral")
    if ri == "negative":
        reasons.append("Negative news impact on holdings")
    elif ri == "positive":
        reasons.append("Positive news impact on holdings")
    reasons.append(f"Action: {recommendation}")
    return reasons


def analyze_trader_health(
    trader: Dict,
    holdings: List[Dict],
    news_by_symbol: Dict[str, List[Dict]],
) -> Dict:
    username = trader.get("username", "?")

    perf_score, perf_details = _score_performance(trader)
    risk_score_val, risk_details = _score_risk(trader)
    news_score, news_details = _score_news(holdings, news_by_symbol)
    conc_score, conc_details, conc_warnings = _score_concentration(holdings)
    cons_score = _score_consistency(trader)

    health_score = perf_score + risk_score_val + news_score + conc_score + cons_score
    health_score = max(0, min(100, health_score))

    data_quality, data_flags = _assess_data_quality(trader, holdings)
    status = _health_status(health_score)
    recommendation = _get_recommendation(health_score, status, data_quality)
    signal = RECOMMENDATION_TO_SIGNAL.get(recommendation, "watch")
    conf_label = _confidence_label(data_quality)
    confidence_float = round(health_score / 100, 2)

    warning_signs = _collect_warnings(risk_details, conc_warnings, holdings, news_details)
    reasons = _build_reasons(status, perf_score, risk_details, news_details, recommendation, health_score)
    holdings_source = trader.get("_holdings_source", "unknown")

    return {
        "trader": username,
        "health_score": round(health_score, 1),
        "health_status": status,
        "recommendation": recommendation,
        "confidence_label": conf_label,
        "data_quality": data_quality,
        "data_flags": data_flags,
        "performance_summary": perf_details,
        "risk_analysis": risk_details,
        "news_analysis": news_details,
        "portfolio_concentration": conc_details,
        "warning_signs": warning_signs,
        "signal": signal,
        "confidence": confidence_float,
        "holdings_health": round(health_score, 1),
        "holdings_source": holdings_source,
        "holdings_count": len(holdings),
        "risk_score": risk_details.get("risk_score", 0),
        "performance_score": round(perf_score, 1),
        "reasons": reasons,
        "top_negative_holdings": news_details.get("negative_symbols", []),
        "top_positive_holdings": news_details.get("positive_symbols", []),
        "news_exists": any(bool(v) for v in news_by_symbol.values()),
    }
