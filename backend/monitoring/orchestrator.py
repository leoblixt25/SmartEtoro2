"""
Monitoring Orchestrator — runs the full trader health monitoring pipeline.

Flow:
  1. Fetch active traders from portfolio
  2. Parse holdings per trader (API mirrors → DB positions)
  3. Collect unique symbols, fetch news for all
  4. Run health analysis per trader
  5. Compare to previous state → alerts
  6. Build portfolio summary
"""

import logging
from typing import Dict, List, Optional

from backend.database.models import Portfolio
from backend.services.market_data import get_current_holdings
from backend.monitoring.holding_parser import (
    get_trader_holdings,
    extract_symbols,
    parse_holdings_from_mirrors,
)
from backend.monitoring.news_service import fetch_news_for_symbols
from backend.monitoring.trader_health_engine import analyze_trader_health
from backend.monitoring.monitor_state import get_monitor_state
from backend.monitoring.watchlist_summary import build_watchlist_summary

logger = logging.getLogger(__name__)


async def run_monitoring_pipeline(
    db,
    portfolio_id: int,
    etoro_client=None,
) -> Dict:
    """Run the full trader health monitoring pipeline.

    Args:
        db: Database session.
        portfolio_id: Portfolio to analyze.
        etoro_client: Optional EToroAPIClient for live mirror data.

    Returns:
        Dict with trader_results, alerts, watchlist_summary, and display.
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        logger.error("Monitoring: portfolio %d not found", portfolio_id)
        return {"error": f"Portfolio {portfolio_id} not found"}

    # ── 1. Get active traders ──
    holdings = get_current_holdings(db, portfolio_id)
    if not holdings:
        logger.info("Monitoring: no active traders for portfolio %d", portfolio_id)
        return {
            "trader_results": [],
            "alerts": [],
            "watchlist_summary": build_watchlist_summary([]),
            "display": "No active traders to monitor.",
        }

    logger.info("Monitoring: %d active traders found", len(holdings))

    # ── 2. Try to get live mirror data for holdings ──
    mirror_holdings: Dict[str, List[Dict]] = {}
    if etoro_client and etoro_client.enabled:
        try:
            raw = await etoro_client.get_portfolio_data()
            if raw:
                mirrors = raw.get("clientPortfolio", {}).get("mirrors", [])
                mirror_holdings = parse_holdings_from_mirrors(mirrors)
                logger.info(
                    "Monitoring: got mirror holdings for %d traders",
                    len(mirror_holdings),
                )
        except Exception as e:
            logger.warning("Monitoring: API mirror fetch failed: %s", e)

    # ── 3. Get holdings + news per trader ──
    all_symbols: set = set()
    trader_holdings_map: Dict[str, List[Dict]] = {}

    for h in holdings:
        username = h.get("username", "")
        if not username:
            continue

        # Holdings from mirror data or DB fallback
        if username in mirror_holdings:
            holdings_list = mirror_holdings[username]
            source = "api_mirror"
        else:
            holdings_list, source = await get_trader_holdings(
                db, portfolio_id, username, etoro_client=None,
            )

        trader_holdings_map[username] = holdings_list
        if holdings_list:
            symbols = extract_symbols(holdings_list)
            all_symbols.update(symbols)

        h["_holdings_source"] = source
        h["_holdings_count"] = len(holdings_list)

    # ── 4. Fetch news for all unique symbols ──
    symbols_list = sorted(all_symbols)
    news_by_symbol: Dict[str, List[Dict]] = {}
    if symbols_list:
        news_by_symbol = await fetch_news_for_symbols(symbols_list, max_per_symbol=3)
        logger.info(
            "Monitoring: fetched news for %d symbols (%d with data)",
            len(symbols_list),
            sum(1 for v in news_by_symbol.values() if v),
        )
    else:
        logger.info("Monitoring: no symbols to fetch news for")

    # ── 5. Health analysis per trader ──
    results = []
    for h in holdings:
        username = h.get("username", "")
        if not username:
            continue

        trader_holdings = trader_holdings_map.get(username, [])
        trader_news = {
            sym: news_by_symbol.get(sym, [])
            for sym in extract_symbols(trader_holdings)
        }
        result = analyze_trader_health(h, trader_holdings, trader_news)
        results.append(result)

    # ── 6. Alerts from state changes ──
    monitor_state = get_monitor_state()
    alerts = monitor_state.get_changes(results)

    if alerts:
        logger.info("Monitoring: %d new alert(s)", len(alerts))

    # ── 7. Portfolio summary ──
    summary = build_watchlist_summary(results)
    logger.info("Monitoring: %s", summary["summary"])

    # ── 8. Display ──
    display = _build_display(results, summary)

    return {
        "trader_results": results,
        "alerts": alerts,
        "watchlist_summary": summary,
        "display": display,
        "news_symbols_fetched": symbols_list,
    }


def _build_display(results: List[Dict], summary: Dict) -> str:
    """Build a human-readable monitoring report."""
    lines = []
    lines.append("📊 **Trader Health Monitor**")
    lines.append("")

    if not results:
        lines.append("No active traders to monitor.")
        return "\n".join(lines)

    for r in results:
        sig = r["signal"]
        if sig == "increase":
            icon = "🟢"
        elif sig == "hold":
            icon = "🟡"
        elif sig == "reduce":
            icon = "🔴"
        elif sig == "avoid":
            icon = "🚨"
        else:
            icon = "⚪"

        lines.append(
            f"{icon} **{r['trader']}** — {sig.upper()} "
            f"(conf={r['confidence']:.2f})"
        )
        for reason in r.get("reasons", [])[:3]:
            lines.append(f"  • {reason}")
        if r.get("top_negative_holdings"):
            lines.append(
                f"  ⚠️ Negative: {', '.join(r['top_negative_holdings'][:3])}"
            )
        if r.get("top_positive_holdings"):
            lines.append(
                f"  ✅ Positive: {', '.join(r['top_positive_holdings'][:3])}"
            )
        lines.append("")

    lines.append("---")
    lines.append(summary.get("summary", ""))
    lines.append("")
    lines.append(
        f"Sentiment: {summary.get('sentiment', 'neutral').upper()} "
        f"({summary.get('sentiment_score', 0):+.2f})"
    )

    return "\n".join(lines)
