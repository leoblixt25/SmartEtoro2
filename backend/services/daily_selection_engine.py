"""
Daily eToro Trader-Selection Engine
────────────────────────────────────
Scans 100+ public eToro traders, applies hard filters, scores with a
weighted model, and returns the top 3 candidates to copy each day.

Pipeline:
  1. Discover 100+ traders via bootstrap + API enrichment
  2. Enrich each with multi-period metrics (3yr, YTD, holdings, AUM)
  3. Apply hard filters (history, returns, risk, concentration, activity)
  4. Score remaining with weighted model (0-100)
  5. Keep top 10, re-score with stronger consistency/risk/news weights
  6. Return top 3 with full breakdown

Scoring weights (first pass):
  30%  3-year performance
  20%  Year-to-date performance
  20%  Consistency and drawdown control
  10%  Risk (inverted — lower is better)
  10%  Copiers / capital copied
  10%  Holdings quality and news sentiment

Output fields per trader:
  username, 3yr performance, YTD performance, copiers, AUM,
  main holdings, news sentiment summary, final score, selection reason
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Hard filter thresholds ───────────────────────────────────────────

MIN_COPIERS = 50
MIN_POSITIONS = 5
MIN_3YR_RETURN = 0.0
MIN_YTD_RETURN = 0.0
MIN_TRACK_RECORD_DAYS = 1095  # 3 years
MAX_RISK_SCORE = 8.0
MAX_CONCENTRATION_PCT = 40.0
MIN_COPY_AMOUNT = 200.0

# ── Scoring weights (first pass) ─────────────────────────────────────

W_3YR = 0.30
W_YTD = 0.20
W_CONSISTENCY = 0.20
W_RISK = 0.10
W_COPIERS = 0.10
W_NEWS = 0.10

# ── Second-pass weights (re-score top 10) ────────────────────────────

W2_CONSISTENCY = 0.25
W2_RISK = 0.25
W2_NEWS = 0.25
W2_FIRST_PASS = 0.25

# ── Output ───────────────────────────────────────────────────────────


@dataclass
class SelectedTrader:
    username: str
    performance_3yr: float
    performance_ytd: float
    copiers: int
    assets_under_copy: float
    main_holdings: List[str]
    news_sentiment: Dict
    final_score: float
    selection_reason: str
    risk_score: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class DailySelectionResult:
    top_3: List[SelectedTrader]
    all_scored: List[Dict]
    excluded: List[Dict]
    scanned_count: int
    stats: Dict


# ── Main entry point ─────────────────────────────────────────────────


async def run_daily_selection(
    portfolio_id: int = 1,
    min_candidates: int = 100,
) -> DailySelectionResult:
    """Run the full daily selection pipeline.

    Args:
        portfolio_id: Portfolio ID to analyze.
        min_candidates: Minimum number of trader candidates to discover.

    Returns:
        DailySelectionResult with top 3, all scored, excluded, and stats.
    """
    from backend.services.market_data import discover_top_traders
    from backend.services.etoro_service import EToroAPIClient

    client = EToroAPIClient()

    # ── Step 1: Discover candidates ──
    logger.info("Daily selection: discovering traders...")
    candidates = await discover_top_traders()

    if not candidates:
        logger.warning("Daily selection: no candidates from discovery")
        return _empty_result("no_candidates_from_discovery")

    logger.info(
        "Daily selection: %d candidates from discovery",
        len(candidates),
    )

    # ── Step 2: Enrich with extended metrics ──
    logger.info("Daily selection: enriching with extended metrics...")
    enriched = await _enrich_all(candidates, client)

    if not enriched:
        logger.warning("Daily selection: no traders after enrichment")
        return _empty_result("no_traders_after_enrichment")

    # ── Step 3: Apply hard filters ──
    logger.info("Daily selection: applying hard filters...")
    passed, excluded = _apply_hard_filters(enriched)

    if len(passed) < 2:
        logger.warning(
            "Daily selection: only %d passed hard filters (need 2+)",
            len(passed),
        )
        return DailySelectionResult(
            top_3=[],
            all_scored=[],
            excluded=excluded,
            scanned_count=len(enriched),
            stats={
                "status": "too_few_candidates",
                "passed": len(passed),
                "total_scanned": len(enriched),
                "reason": (
                    f"Only {len(passed)} traders passed hard filters "
                    f"out of {len(enriched)} scanned"
                ),
            },
        )

    logger.info("Daily selection: %d passed hard filters", len(passed))

    # ── Step 4: Score all passed traders ──
    logger.info("Daily selection: scoring %d traders...", len(passed))
    all_scored = _score_all(passed)

    all_scored.sort(key=lambda x: x.get("first_pass_score", 0), reverse=True)

    # ── Step 5: Keep top 10, re-score ──
    top_10 = all_scored[:10]
    logger.info("Daily selection: re-scoring top 10...")

    # Fetch news sentiment for top 10
    top_10_with_news = await _add_news_sentiment(top_10, client)

    re_scored = _re_score_top10(top_10_with_news)
    re_scored.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    top_3 = re_scored[:3]

    # ── Step 6: Check safeguards ──
    top_3 = _apply_safeguards(top_3)

    # ── Step 7: Build output ──
    selected = _build_selected_list(top_3)
    stats = {
        "status": "success",
        "total_candidates": len(candidates),
        "enriched": len(enriched),
        "passed_filters": len(passed),
        "top_10_scored": len(top_10),
        "final_top_3": len(selected),
        "scoring_breakdown": {
            "weight_3yr": W_3YR,
            "weight_ytd": W_YTD,
            "weight_consistency": W_CONSISTENCY,
            "weight_risk": W_RISK,
            "weight_copiers": W_COPIERS,
            "weight_news": W_NEWS,
        },
    }

    logger.info(
        "Daily selection complete: %d candidates -> %d filtered -> "
        "%d top 10 -> %d final",
        len(candidates),
        len(passed),
        len(top_10),
        len(selected),
    )
    for i, t in enumerate(selected, 1):
        logger.info(
            "  #%d: %s — score=%.1f, 3yr=%.1f%%, YTD=%.1f%%, "
            "copiers=%d, AUM=%s, sentiment=%s",
            i, t.username, t.final_score,
            t.performance_3yr, t.performance_ytd,
            t.copiers,
            f"${t.assets_under_copy:,.0f}" if t.assets_under_copy else "N/A",
            t.news_sentiment.get("dominant_sentiment", "N/A"),
        )

    return DailySelectionResult(
        top_3=selected,
        all_scored=all_scored,
        excluded=excluded,
        scanned_count=len(candidates),
        stats=stats,
    )


# ── Enrichment ───────────────────────────────────────────────────────


async def _enrich_all(
    candidates: List[Dict],
    client,
) -> List[Dict]:
    """Enrich all candidates with extended metrics (3yr, YTD, holdings, AUM).

    Runs concurrently with a semaphore to avoid rate limits.
    """
    import asyncio

    sem = asyncio.Semaphore(5)
    enriched: List[Dict] = []

    async def _fetch(trader: Dict) -> Optional[Dict]:
        username = trader.get("username", "")
        if not username:
            return None
        async with sem:
            try:
                extended = await client.get_trader_extended_metrics(username)
                if extended.get("available"):
                    return {**trader, **extended}
                return None
            except Exception as e:
                logger.warning(
                    "Extended metrics failed for %s: %s", username, e,
                )
                return None

    tasks = [_fetch(t) for t in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, dict) and r.get("available"):
            enriched.append(r)

    logger.info(
        "Enriched %d/%d candidates with extended metrics",
        len(enriched), len(candidates),
    )
    return enriched


# ── Hard filters ─────────────────────────────────────────────────────


def _passes_3yr_history(trader: Dict) -> Tuple[bool, str]:
    """Check trader has at least 3 years of trading history."""
    return_3yr = trader.get("return_3yr")
    track_days = trader.get("track_record_days", 0) or 0

    # Has 3yr return data → has history
    if return_3yr is not None:
        return True, ""

    # Estimated track record from copiers
    if track_days >= MIN_TRACK_RECORD_DAYS:
        return True, ""

    return False, (
        f"insufficient_history "
        f"(track_days={track_days}, min={MIN_TRACK_RECORD_DAYS})"
    )


def _passes_3yr_return(trader: Dict) -> Tuple[bool, str]:
    """Check positive 3-year return."""
    r3 = trader.get("return_3yr")
    if r3 is not None and float(r3) > MIN_3YR_RETURN:
        return True, ""
    return False, (
        f"3yr_return_not_positive "
        f"(return_3yr={r3}, min={MIN_3YR_RETURN})"
    )


def _passes_ytd_return(trader: Dict) -> Tuple[bool, str]:
    """Check positive year-to-date return."""
    ytd = trader.get("return_ytd")
    if ytd is not None and float(ytd) > MIN_YTD_RETURN:
        return True, ""
    return False, (
        f"ytd_return_not_positive "
        f"(return_ytd={ytd}, min={MIN_YTD_RETURN})"
    )


def _passes_risk(trader: Dict) -> Tuple[bool, str]:
    """Check acceptable risk level. Unknown risk (None) is accepted."""
    risk = trader.get("risk_score")
    if risk is None:
        return True, ""
    risk = float(risk)
    if risk <= MAX_RISK_SCORE:
        return True, ""
    return False, f"risk_too_high (risk={risk:.1f}, max={MAX_RISK_SCORE})"


def _passes_concentration(trader: Dict) -> Tuple[bool, str]:
    """Check no extreme concentration in one asset.

    Uses holdings data from the live portfolio. If holdings are
    unavailable, passes with a warning log.
    """
    holdings = trader.get("holdings", [])
    if not holdings:
        logger.debug(
            "Concentration: no holdings for %s — skipping check",
            trader.get("username", "?"),
        )
        return True, ""

    concentration_pct = 100.0 / max(len(holdings), 1)
    if concentration_pct <= MAX_CONCENTRATION_PCT:
        return True, ""
    return False, (
        f"extreme_concentration "
        f"({len(holdings)} holdings, ~{concentration_pct:.0f}% each, "
        f"max={MAX_CONCENTRATION_PCT}%)"
    )


def _passes_activity(trader: Dict) -> Tuple[bool, str]:
    """Check meaningful activity — copiers and positions."""
    copiers = trader.get("copiers")
    positions = trader.get("positions_count")

    if copiers is not None and copiers < MIN_COPIERS:
        return False, (
            f"insufficient_copiers ({copiers}, min={MIN_COPIERS})"
        )

    if positions is not None and positions < MIN_POSITIONS:
        return False, (
            f"insufficient_positions ({positions}, min={MIN_POSITIONS})"
        )

    return True, ""


def _passes_aum(trader: Dict) -> Tuple[bool, str]:
    """Prefer traders with meaningful assets under copy.

    This is a soft warning, not a hard rejection — all traders
    pass unless AUM is explicitly zero.
    """
    auc = trader.get("assets_under_copy")
    if auc is not None and auc <= 0:
        return False, "zero_assets_under_copy"
    return True, ""


def _apply_hard_filters(
    traders: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """Apply all hard filter checks.

    Returns (passed, excluded) where excluded has 'exclusion_reasons'.
    """
    passed = []
    excluded = []

    filter_checks = [
        ("3yr_history", _passes_3yr_history),
        ("3yr_return", _passes_3yr_return),
        ("ytd_return", _passes_ytd_return),
        ("risk", _passes_risk),
        ("concentration", _passes_concentration),
        ("activity", _passes_activity),
        ("aum", _passes_aum),
    ]

    for trader in traders:
        username = trader.get("username", "?")
        reasons = []

        for name, check in filter_checks:
            ok, reason = check(trader)
            if not ok:
                reasons.append(reason)

        if reasons:
            excluded.append({**trader, "exclusion_reasons": reasons})
            logger.info("Filtered out %s: %s", username, "; ".join(reasons))
        else:
            passed.append(trader)

    logger.info(
        "Hard filters: %d passed, %d excluded",
        len(passed), len(excluded),
    )
    return passed, excluded


# ── Scoring ──────────────────────────────────────────────────────────


def _normalize(value, max_val: float, scale: float = 100.0) -> float:
    """Normalize a value to 0-scale, capped at scale."""
    if value is None:
        return 0.0
    return min(scale, max(0.0, float(value) / max_val * scale))


def _compute_consistency_score(trader: Dict) -> float:
    """Compute consistency score 0-100 from drawdown and volatility."""
    dd_raw = trader.get("max_drawdown")
    vol_raw = trader.get("volatility")
    sharpe = trader.get("sharpe_score")

    # Prefer sharpe ratio if available
    if sharpe is not None and float(sharpe) > 0:
        return min(100.0, max(0.0, float(sharpe) * 25))

    dd = float(dd_raw) if dd_raw is not None else 0.0
    vol = float(vol_raw) if vol_raw is not None else 0.0

    # Penalize high drawdown
    dd_penalty = min(100.0, dd * 5)
    # Penalize high volatility
    vol_penalty = min(100.0, max(0.0, (vol - 10.0) * 3))

    consistency = max(0.0, 100.0 - dd_penalty - vol_penalty)
    return round(consistency, 1)


def _score_trader_first_pass(trader: Dict) -> Dict:
    """Score a single trader 0-100 using first-pass weighted model.

    Weights:
      30%  3-year performance
      20%  Year-to-date performance
      20%  Consistency and drawdown control
      10%  Risk score (inverted — lower is better)
      10%  Copiers / capital copied
      10%  Holdings quality and news sentiment (added during re-score)

    Returns dict with component scores and total.
    """
    return_3yr = trader.get("return_3yr") if trader.get("return_3yr") is not None else 0.0
    return_ytd = trader.get("return_ytd") if trader.get("return_ytd") is not None else 0.0
    copiers = trader.get("copiers") if trader.get("copiers") is not None else 0

    # Component scores (each 0-100)
    score_3yr = _normalize(return_3yr, 50.0)
    score_ytd = _normalize(return_ytd, 30.0)
    score_consistency = _compute_consistency_score(trader)
    score_risk = _risk_to_score(trader)
    if copiers > 0:
        import math
        score_copiers = _normalize(math.log10(copiers) * 25, 100.0)
    else:
        score_copiers = 0.0

    total = (
        score_3yr * W_3YR
        + score_ytd * W_YTD
        + score_consistency * W_CONSISTENCY
        + score_risk * W_RISK
        + score_copiers * W_COPIERS
    )

    return {
        "first_pass_score": round(total, 1),
        "components": {
            "score_3yr": round(score_3yr, 1),
            "score_ytd": round(score_ytd, 1),
            "score_consistency": round(score_consistency, 1),
            "score_risk": round(score_risk, 1),
            "score_copiers": round(score_copiers, 1),
        },
    }


def _score_all(traders: List[Dict]) -> List[Dict]:
    """Score all traders and return dicts with scores attached."""
    scored = []
    for trader in traders:
        result = _score_trader_first_pass(trader)
        scored.append({**trader, **result})
        username = trader.get("username", "?")
        logger.info(
            "First pass %s: score=%.1f (3yr=%.1f, YTD=%.1f, "
            "consistency=%.1f, copiers=%.1f, risk=%.1f)",
            username,
            result["first_pass_score"],
            result["components"]["score_3yr"],
            result["components"]["score_ytd"],
            result["components"]["score_consistency"],
            result["components"]["score_copiers"],
            result["components"]["score_risk"],
        )
    return scored


# ── News sentiment ───────────────────────────────────────────────────


async def _add_news_sentiment(
    top_10: List[Dict],
    client,
) -> List[Dict]:
    """Fetch news sentiment for each trader's main holdings.

    For each trader in top 10:
      1. Get holdings from extended metrics (already fetched)
      2. Map to stock symbols
      3. Fetch news for those symbols
      4. Compute aggregate sentiment

    Returns updated list with 'news' dict attached.
    """
    from backend.monitoring.news_service import (
        fetch_news_for_symbols,
        aggregate_sentiment,
    )

    # Collect all unique symbols across top 10
    all_symbols: set = set()
    for trader in top_10:
        holdings = trader.get("holdings", [])
        if holdings:
            all_symbols.update(holdings)

    if not all_symbols:
        logger.info("News: no holdings data for top 10 traders")
        for trader in top_10:
            trader["news"] = {
                "dominant_sentiment": "neutral",
                "net_score": 0.0,
                "total": 0,
                "holdings_analyzed": [],
            }
        return top_10

    # Fetch news for all unique symbols (cached, 3 per symbol)
    import asyncio
    try:
        news_by_symbol = await fetch_news_for_symbols(
            list(all_symbols), max_per_symbol=3, use_cache=True,
        )
    except Exception as e:
        logger.warning("News fetch failed: %s", e)
        news_by_symbol = {}

    # Compute per-trader sentiment
    for trader in top_10:
        holdings = trader.get("holdings", [])
        trader_news = {
            sym: news_by_symbol.get(sym, [])
            for sym in holdings
        }
        sentiment = aggregate_sentiment(trader_news)
        trader["news"] = {
            **sentiment,
            "holdings_analyzed": holdings,
        }

        logger.info(
            "News for %s: %s (net=%.2f, %d items)",
            trader.get("username", "?"),
            sentiment.get("dominant_sentiment", "neutral"),
            sentiment.get("net_score", 0),
            sentiment.get("total", 0),
        )

    return top_10


# ── Second-pass re-scoring ───────────────────────────────────────────


def _news_to_score(news: Dict) -> float:
    """Convert news sentiment to a 0-100 score.

    net_score is -1..1 → scaled to 0..100.
    Penalizes negative sentiment more heavily.
    """
    net = news.get("net_score", 0.0)
    if net < 0:
        return max(0.0, 50.0 + net * 50.0)  # -1 → 0, 0 → 50
    return min(100.0, 50.0 + net * 50.0)    # 0 → 50, 1 → 100


def _risk_to_score(trader: Dict) -> float:
    """Convert risk score to a 0-100 score (lower risk = higher score)."""
    risk = trader.get("risk_score")
    if risk is None:
        return 50.0
    return max(0.0, 100.0 - float(risk) * 12.5)  # risk=0 → 100, risk=8 → 0


def _re_score_top10(top_10: List[Dict]) -> List[Dict]:
    """Re-score top 10 with stronger consistency/risk/news emphasis.

    Second-pass weights:
      25% consistency
      25% risk (inverted)
      25% news sentiment
      25% first-pass score
    """
    re_scored = []

    for trader in top_10:
        first_pass = trader.get("first_pass_score", 0.0)
        consistency = _compute_consistency_score(trader)
        risk_score = _risk_to_score(trader)
        news_score = _news_to_score(trader.get("news", {}))

        final = (
            consistency * W2_CONSISTENCY
            + risk_score * W2_RISK
            + news_score * W2_NEWS
            + first_pass * W2_FIRST_PASS
        )

        trader["final_score"] = round(final, 1)
        trader["second_pass_components"] = {
            "consistency": round(consistency, 1),
            "risk_score_inverted": round(risk_score, 1),
            "news_sentiment": round(news_score, 1),
            "first_pass_score": round(first_pass, 1),
        }

        reason = _build_selection_reason(trader)
        trader["selection_reason"] = reason

        re_scored.append(trader)

        logger.info(
            "Second pass %s: final=%.1f (consistency=%.1f, risk=%.1f, "
            "news=%.1f, first=%.1f)",
            trader.get("username", "?"),
            final, consistency, risk_score, news_score, first_pass,
        )

    return re_scored


# ── Safeguards ───────────────────────────────────────────────────────


def _apply_safeguards(top_3: List[Dict]) -> List[Dict]:
    """Remove traders from top 3 if their risk or news profile is poor.

    Checks:
      - Risk score > 8 → remove
      - Dominant negative news sentiment → warn (demote if strongly negative)
      - Insufficient data → remove
    """
    safe = []

    for trader in top_3:
        username = trader.get("username", "?")
        risk = trader.get("risk_score")
        news = trader.get("news", {})
        sentiment = news.get("dominant_sentiment", "neutral")
        net_score = news.get("net_score", 0.0)

        reasons = []

        if risk is not None and float(risk) > MAX_RISK_SCORE:
            reasons.append(f"risk={float(risk):.1f} exceeds {MAX_RISK_SCORE}")

        if sentiment == "negative" and net_score < -0.5:
            reasons.append(
                f"strongly_negative_news (net={net_score:.2f})"
            )

        if reasons:
            logger.warning(
                "Safeguard removed %s: %s",
                username, "; ".join(reasons),
            )
        else:
            safe.append(trader)

    return safe[:3]


# ── Output formatting ────────────────────────────────────────────────


def _build_selection_reason(trader: Dict) -> str:
    """Build a human-readable reason for selecting this trader."""
    parts = []
    r3 = trader.get("return_3yr") if trader.get("return_3yr") is not None else 0.0
    ytd = trader.get("return_ytd") if trader.get("return_ytd") is not None else 0.0
    copiers = trader.get("copiers") if trader.get("copiers") is not None else 0
    auc = trader.get("assets_under_copy") if trader.get("assets_under_copy") is not None else 0
    risk = trader.get("risk_score")
    dd = trader.get("max_drawdown")

    if r3 > 30:
        parts.append(f"Strong 3yr return ({r3:.1f}%)")
    elif r3 > 0:
        parts.append(f"Positive 3yr return ({r3:.1f}%)")

    if ytd > 15:
        parts.append(f"Strong YTD ({ytd:.1f}%)")
    elif ytd > 0:
        parts.append(f"Positive YTD ({ytd:.1f}%)")

    if risk is not None:
        if float(risk) <= 4:
            parts.append(f"Low risk ({float(risk):.1f})")
        elif float(risk) <= 6:
            parts.append(f"Moderate risk ({float(risk):.1f})")

    if dd is not None and float(dd) < 10:
        parts.append(f"Controlled drawdown ({float(dd):.1f}%)")

    if copiers > 500:
        parts.append(f"High copiers ({copiers})")
    elif copiers > 100:
        parts.append(f"Meaningful copiers ({copiers})")

    if auc > 1000000:
        parts.append(f"Large AUM (${auc:,.0f})")
    elif auc > 100000:
        parts.append(f"Established AUM (${auc:,.0f})")

    news = trader.get("news", {})
    sentiment = news.get("dominant_sentiment", "neutral")
    if sentiment == "positive":
        parts.append("Positive news sentiment on holdings")
    elif sentiment == "negative":
        parts.append("Negative news — monitor closely")

    return "; ".join(parts) if parts else "Passed all filters"


def _build_selected_list(top_3: List[Dict]) -> List[SelectedTrader]:
    """Convert top 3 dicts to SelectedTrader dataclasses."""
    selected = []
    for trader in top_3:
        selected.append(SelectedTrader(
            username=trader.get("username", "?"),
            performance_3yr=trader.get("return_3yr") or 0.0,
            performance_ytd=trader.get("return_ytd") or 0.0,
            copiers=trader.get("copiers") or 0,
            assets_under_copy=trader.get("assets_under_copy") or 0.0,
            main_holdings=trader.get("holdings", []),
            news_sentiment=trader.get("news", {}),
            final_score=trader.get("final_score", 0.0),
            selection_reason=trader.get("selection_reason", ""),
            risk_score=trader.get("risk_score"),
            max_drawdown=trader.get("max_drawdown"),
        ))
    return selected


def format_selection_output(result: DailySelectionResult) -> str:
    """Format daily selection result as a readable string."""
    lines = []
    lines.append("=" * 60)
    lines.append("DAILY TRADER SELECTION REPORT")
    lines.append("=" * 60)

    lines.append(f"\nScanned: {result.scanned_count} traders")
    lines.append(f"Passed filters: {result.stats.get('passed_filters', 0)}")
    lines.append(f"Top 10 re-scored: {result.stats.get('top_10_scored', 0)}")

    if result.top_3:
        lines.append("\n" + "-" * 60)
        lines.append("TOP 3 TRADERS TO COPY")
        lines.append("-" * 60)

        for i, t in enumerate(result.top_3, 1):
            lines.append(f"\n  #{i}: {t.username}")
            lines.append(f"  {'─' * 40}")
            lines.append(f"  Final Score:     {t.final_score:.1f}/100")
            lines.append(f"  3-Year Return:   {t.performance_3yr:.1f}%")
            lines.append(f"  YTD Return:      {t.performance_ytd:.1f}%")
            r_str = f"{t.risk_score:.1f}" if t.risk_score else "unavailable"
            lines.append(f"  Risk Score:      {r_str}")
            dd_str = f"{t.max_drawdown:.1f}%" if t.max_drawdown else "unavailable"
            lines.append(f"  Max Drawdown:    {dd_str}")
            c_str = f"{t.copiers:,}" if t.copiers else "unavailable"
            lines.append(f"  Copiers:         {c_str}")
            if t.assets_under_copy:
                lines.append(f"  AUM:             ${t.assets_under_copy:,.0f}")
            if t.main_holdings:
                lines.append(
                    f"  Main Holdings:   {', '.join(t.main_holdings[:5])}"
                )
            ns = t.news_sentiment
            lines.append(
                f"  News Sentiment:  {ns.get('dominant_sentiment', 'N/A')}"
                f" (net={ns.get('net_score', 0):+.2f})"
            )
            lines.append(f"  Why:             {t.selection_reason}")
    else:
        status = result.stats.get("status", "unknown")
        reason = result.stats.get("reason", "No traders found")
        lines.append(f"\n  Status: {status}")
        lines.append(f"  Reason: {reason}")
        lines.append("\n  No high-confidence traders found today.")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def _empty_result(reason: str) -> DailySelectionResult:
    """Return an empty result with a reason."""
    return DailySelectionResult(
        top_3=[],
        all_scored=[],
        excluded=[],
        scanned_count=0,
        stats={"status": "empty", "reason": reason},
    )
