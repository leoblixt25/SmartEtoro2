"""
Trader Health Engine — combines performance, risk, and news into a recommendation.

Signal mapping:
  - increase: strong performance + favorable news
  - hold: stable performance + mixed/neutral news
  - reduce: weakening performance + negative news
  - avoid: critical risk or major negative events
  - watch: insufficient data

Rules:
  - Never recommend based on news alone
  - Never recommend based on performance alone
  - Both dimensions must agree for increase/reduce
  - Unknown holdings data reduces confidence
"""

import logging
from typing import Dict, List, Optional, Tuple

from backend.ai.scoring_engine import calculate_growth_score
from backend.monitoring.news_service import aggregate_sentiment

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────

PERFORMANCE_STRONG = 70.0
PERFORMANCE_STABLE = 40.0
PERFORMANCE_WEAK = 20.0

RISK_ACCEPTABLE = 6.0
RISK_HIGH = 8.0

CONCENTRATION_THRESHOLD = 40.0  # single holding weight %
NEGATIVE_NEWS_THRESHOLD = 0.3   # fraction of holdings with negative news


def _score_performance(trader: Dict) -> Tuple[float, str]:
    """Score trader performance using the existing scoring engine.

    Returns (score, label).
    """
    scored = calculate_growth_score(trader)
    score = scored.get("score", 0)

    if score >= PERFORMANCE_STRONG:
        label = "strong"
    elif score >= PERFORMANCE_STABLE:
        label = "stable"
    elif score >= PERFORMANCE_WEAK:
        label = "weak"
    else:
        label = "critical"

    return score, label


def _score_risk(trader: Dict) -> Tuple[float, str]:
    """Score risk level.

    Returns (risk_value, label).
    """
    risk_raw = trader.get("risk_score")
    risk = float(risk_raw) if risk_raw is not None else 0.0
    dd = float(trader.get("max_drawdown", 0.0) or 0.0)

    if risk > RISK_HIGH or dd > 25:
        label = "critical"
    elif risk > RISK_ACCEPTABLE or dd > 15:
        label = "elevated"
    else:
        label = "acceptable"

    return risk, label


def _score_holdings_health(
    holdings: List[Dict],
    news_by_symbol: Dict[str, List[Dict]],
) -> Tuple[float, List[str], List[str], List[str]]:
    """Score the health of a trader's holdings based on news.

    Returns:
        (health_score 0-100, negative_symbols, positive_symbols, warnings)
    """
    if not holdings:
        return 50.0, [], [], ["No holdings data — reduced confidence"]

    # Get aggregate sentiment
    sent = aggregate_sentiment(news_by_symbol)
    neg_symbols = sent.get("negative_symbols", [])
    pos_symbols = sent.get("positive_symbols", [])

    # Holdings affected by negative news
    total_syms = len(set(
        h["symbol"] for h in holdings if h.get("symbol")
    ))
    affected = sum(1 for h in holdings if h.get("symbol", "").upper() in neg_symbols)
    neg_ratio = affected / max(total_syms, 1)

    warnings = []

    # Check concentration
    max_weight = max((h.get("weight", 0) for h in holdings), default=0)
    if max_weight > CONCENTRATION_THRESHOLD:
        top = max(holdings, key=lambda h: h.get("weight", 0))
        warnings.append(
            f"High concentration in {top['symbol']} ({top['weight']:.0f}%)"
        )

    # Check negative news impact
    if neg_ratio > NEGATIVE_NEWS_THRESHOLD:
        warnings.append(
            f"{affected}/{total_syms} holdings affected by negative news"
        )

    # Compute health score: start at 100, penalize
    health = 100.0
    health -= neg_ratio * 60  # up to -60 for negative news
    if max_weight > CONCENTRATION_THRESHOLD:
        health -= 15  # concentration penalty
    if not news_by_symbol or all(not v for v in news_by_symbol.values()):
        health -= 10  # no news data

    health = max(0, min(100, health))

    return health, neg_symbols, pos_symbols, warnings


def _determine_signal(
    perf_label: str,
    risk_label: str,
    holdings_health: float,
    neg_symbols: List[str],
    holdings_source: str,
    has_news_data: bool,
) -> Tuple[str, float]:
    """Determine the final signal and confidence.

    Returns (signal, confidence).
    """
    confidence = 0.5

    # Both dimensions must agree for strong signals
    if holdings_source == "unknown":
        confidence = 0.3

    if perf_label == "strong" and risk_label in ("acceptable", "elevated"):
        if not neg_symbols:
            confidence = 0.85
            return "increase", confidence
        elif holdings_health >= 60:
            confidence = 0.7
            return "increase", confidence
        else:
            confidence = 0.5
            return "hold", confidence

    if perf_label == "stable":
        if risk_label == "critical" or holdings_health < 40:
            confidence = 0.6
            return "reduce", confidence
        if not has_news_data:
            confidence = 0.4
            return "watch", confidence
        if neg_symbols:
            confidence = 0.5
            return "reduce", confidence
        confidence = 0.7
        return "hold", confidence

    if perf_label == "weak":
        if risk_label == "critical" or holdings_health < 30:
            confidence = 0.8
            return "avoid", confidence
        confidence = 0.65
        return "reduce", confidence

    if perf_label == "critical":
        confidence = 0.9
        return "avoid", confidence

    # Default: watch
    confidence = 0.3
    return "watch", confidence


def analyze_trader_health(
    trader: Dict,
    holdings: List[Dict],
    news_by_symbol: Dict[str, List[Dict]],
) -> Dict:
    """Run full health analysis for a single trader.

    Args:
        trader: Trader data dict (from get_current_holdings or similar).
        holdings: Parsed holdings list (from holding_parser).
        news_by_symbol: Dict mapping symbol → list of news items (from news_service).

    Returns:
        Dict with signal, confidence, scores, reasons, and flagged holdings.
    """
    username = trader.get("username", "?")

    # Step 1: Performance
    perf_score, perf_label = _score_performance(trader)
    logger.info("HEALTH %s: performance=%.1f (%s)", username, perf_score, perf_label)

    # Step 2: Risk
    risk_value, risk_label = _score_risk(trader)
    logger.info("HEALTH %s: risk=%.1f (%s)", username, risk_value, risk_label)

    # Step 3: Holdings health
    news_exists = any(bool(v) for v in news_by_symbol.values())
    holdings_health, neg_symbols, pos_symbols, warnings = _score_holdings_health(
        holdings, news_by_symbol,
    )
    holdings_source = trader.get("_holdings_source", "unknown")
    logger.info(
        "HEALTH %s: holdings_health=%.1f, neg=%d, pos=%d, warnings=%s",
        username, holdings_health, len(neg_symbols), len(pos_symbols), warnings,
    )

    # Step 4: Determine signal
    signal, confidence = _determine_signal(
        perf_label, risk_label, holdings_health,
        neg_symbols, holdings_source, news_exists,
    )
    logger.info(
        "HEALTH %s: signal=%s (conf=%.2f)",
        username, signal, confidence,
    )

    # Step 5: Build reasons
    reasons = []
    if perf_label == "strong":
        reasons.append(f"Strong recent performance ({perf_score:.0f}/100)")
    elif perf_label == "stable":
        reasons.append(f"Stable performance ({perf_score:.0f}/100)")
    elif perf_label == "weak":
        reasons.append(f"Weakening performance ({perf_score:.0f}/100)")
    else:
        reasons.append(f"Critical performance ({perf_score:.0f}/100)")

    if risk_label == "acceptable":
        reasons.append("Risk is acceptable")
    elif risk_label == "elevated":
        reasons.append(f"Risk is elevated ({risk_value:.1f})")
    else:
        reasons.append(f"Risk is critical ({risk_value:.1f})")

    if pos_symbols:
        reasons.append(f"Holdings with positive news: {', '.join(pos_symbols[:3])}")
    if neg_symbols:
        reasons.append(f"Holdings with negative news: {', '.join(neg_symbols[:3])}")
    if not news_exists:
        reasons.append("No recent news data for holdings")
    reasons.extend(warnings[:2])

    return {
        "trader": username,
        "signal": signal,
        "confidence": round(confidence, 2),
        "performance_score": round(perf_score, 1),
        "risk_score": round(risk_value, 1),
        "risk_label": risk_label,
        "holdings_health": round(holdings_health, 1),
        "news_exists": news_exists,
        "holdings_source": holdings_source,
        "reasons": reasons,
        "top_negative_holdings": neg_symbols[:5],
        "top_positive_holdings": pos_symbols[:5],
        "holdings_count": len(holdings),
    }
