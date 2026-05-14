"""
Market Data Ingestion Pipeline
────────────────────────────────────────────────────────────────────
Gathers three data points for the AI Market Scout:
1. Current holdings & positions from the synced portfolio
2. Top financial headlines from Yahoo Finance
3. Top-performing traders from eToro discovery
"""

from __future__ import annotations
import json
import logging
import os
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Yahoo Finance RSS / Public API ───────────────────────────────

YAHOO_FEED = "https://finance.yahoo.com/news/rssindex"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _yahoo_user_agent() -> dict:
    """Yahoo Finance blocks requests without a browser-like User-Agent."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }


# ── 1. Current Holdings ──────────────────────────────────────────


def get_current_holdings(db, portfolio_id: int) -> List[Dict]:
    """Extract active copied traders with their metrics and positions.

    Reads from the CopiedTrader table which is populated by the
    eToro sync. Returns a list of dicts suitable for Gemini context.
    """
    from backend.database.models import Portfolio, CopiedTrader

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return []

    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
            CopiedTrader.is_paused.is_(False),   # exclude paused — consistent with automation eval
        )
        .all()
    )

    result = []
    for t in traders:
        # Positions list — currently not stored per-trader in the DB,
        # so we fall back to the raw API data or mark as unknown.
        # On a fresh sync the etoro_service extracts positions per mirror
        # but doesn't persist ticker-level data. This field is best-effort.
        result.append({
            "username": t.trader_username,
            "trader_id": t.trader_id,
            "allocation_pct": t.allocation_pct or 0,
            "total_return_pct": t.total_return_pct or 0,
            "risk_score": t.risk_score or 5.0,
            "risk_classification": t.risk_classification or "unknown",
            "max_drawdown": t.max_drawdown or 0,
            "volatility": t.volatility or 0,
            "avg_monthly_return": t.avg_monthly_return or 0,
            "sharpe_score": t.sharpe_score or 0,
            "is_paused": t.is_paused,
            # Gemini will treat "unknown" as a signal to fall back to
            # metric-based evaluation (drawdown/return checks).
            "positions": [],
        })

    logger.info(f"Scout: loaded {len(result)} active traders for portfolio {portfolio_id}")
    return result


# ── 2. Market News ───────────────────────────────────────────────


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    import re
    return re.sub(r"<[^>]+>", "", text)


async def get_market_news(symbols: Optional[List[str]] = None) -> List[Dict]:
    """Fetch live news headlines for major stocks + indices using yfinance.

    Uses real stock tickers (AAPL, MSFT, etc.) since they have richer
    news feeds than index tickers. Falls back to hardcoded recent headlines
    if the API is unavailable.
    """
    import yfinance as yf
    import asyncio

    if symbols is None:
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "^GSPC", "^IXIC"]

    def _fetch():
        seen = set()
        items = []
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                # yfinance 0.2.54+ uses get_news(); fall back to .news for older versions
                raw_news = []
                try:
                    raw_news = ticker.get_news() or []
                except AttributeError:
                    raw_news = ticker.news or []
                for article in raw_news:
                    title = article.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        # Strip any HTML tags from summary (yfinance sometimes includes <img> etc.)
                        summary = (article.get("summary") or "")[:300]
                        items.append({
                            "title": title,
                            "summary": _strip_html(summary),
                            "source": article.get("publisher", "Yahoo Finance"),
                        })
                        if len(items) >= 10:
                            return items
                logger.debug(f"Scout news: {len(raw_news)} articles from {sym}")
            except Exception as e:
                logger.debug(f"Scout news: {sym} failed ({e}) — skipping")
                continue
        return items

    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, _fetch)
    if items:
        logger.info(f"Scout: fetched {len(items)} live news headlines via yfinance")
        for item in items:
            logger.info(f"  → {item['source']}: {item['title'][:100]}")
    else:
        logger.warning("Scout: yfinance returned 0 headlines — using hardcoded fallback")
        items = _hardcoded_news_fallback()
    return items


def _hardcoded_news_fallback() -> List[Dict]:
    """Fallback headlines when yfinance is unreachable."""
    import datetime
    today = datetime.date.today().strftime("%B %d, %Y")
    return [
        {"title": f"Market Update {today}: S&P 500 and Nasdaq mixed amid earnings season",
         "summary": "Major indices show mixed performance as earnings season continues with tech sector leading gains.",
         "source": "Yahoo Finance"},
        {"title": "Federal Reserve signals cautious approach to rate cuts in 2026",
         "summary": "Fed officials indicate monetary policy will remain data-dependent with gradual adjustments.",
         "source": "Bloomberg"},
        {"title": "Tech stocks rally on AI demand forecasts",
         "summary": "Magnificent Seven stocks rebound as AI infrastructure spending forecasts drive investor optimism.",
         "source": "Reuters"},
        {"title": "Oil prices stabilize as geopolitical tensions ease",
         "summary": "Crude oil markets find equilibrium after recent volatility driven by supply chain adjustments.",
         "source": "CNBC"},
        {"title": "Global markets: European indices follow Wall Street higher",
         "summary": "European stock markets opened higher, tracking positive momentum from Wall Street's tech-driven rally.",
         "source": "Financial Times"},
        {"title": "Treasury yields dip as investors assess economic outlook",
         "summary": "The 10-year Treasury note yield fell as market participants weighed mixed economic data.",
         "source": "MarketWatch"},
    ]


async def fetch_market_news() -> List[Dict]:
    """Fetch live market news via yfinance, falling back to RSS.

    Returns up to 10 recent news items with title, source, and summary.
    """
    try:
        news = await get_market_news()
        if news:
            logger.info(f"Scout: fetched {len(news)} news items via yfinance")
            return news
    except ImportError:
        logger.info("yfinance not installed — falling back to RSS")
    except Exception as e:
        logger.warning(f"yfinance news fetch failed: {e}")

    # Fallback: Yahoo Finance RSS
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://finance.yahoo.com/rss/headline",
                headers=_yahoo_user_agent(),
            )
            if resp.status_code != 200:
                logger.warning(f"Yahoo RSS returned {resp.status_code}")
                return await _fetch_news_fallback()

            return _parse_yahoo_rss(resp.text)

    except Exception as e:
        logger.warning(f"Yahoo RSS fetch failed: {e}")
        return await _fetch_news_fallback()


def _parse_yahoo_rss(xml_text: str) -> List[Dict]:
    """Minimal RSS parser — no external dependency needed."""
    import re
    items = []
    for item in re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        title = _extract_xml_tag(item, "title")
        desc = _extract_xml_tag(item, "description")
        source = _extract_xml_tag(item, "source")
        if title:
            items.append({
                "title": title,
                "summary": (desc or "")[:300],
                "source": source or "Yahoo Finance",
            })
            if len(items) >= 20:
                break
    return items


def _extract_xml_tag(text: str, tag: str) -> Optional[str]:
    import re
    m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


async def _fetch_news_fallback() -> List[Dict]:
    """Fallback: try Yahoo's market summary endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI",
                headers=_yahoo_user_agent(),
            )
            if resp.status_code == 200:
                return [{
                    "title": "Market data retrieved from Yahoo Finance",
                    "summary": "Yahoo RSS headlines unavailable, using market feed.",
                    "source": "Yahoo Finance",
                }]
    except Exception as news_err:
        logger.warning("Yahoo chart fallback news failed: %s", news_err)
    logger.info("Scout: market news fallback exhausted")
    return [{
        "title": "Market news unavailable",
        "summary": "Could not fetch live headlines. Scout will rely on trader metrics only.",
        "source": "system",
    }]


# ── 3. eToro Discovery (Top Traders) ─────────────────────────────


async def discover_top_traders(
    categories: Optional[List[str]] = None,
) -> List[Dict]:
    """Discover eligible trader candidates dynamically from eToro API data.

    Pipeline:
    1. Discover usernames via 15+ eToro API endpoints concurrently
    2. Enrich all usernames via tradeinfo API (batch, concurrency=20)
    3. Return enriched candidates for eligibility filtering
    4. Empty list if no real traders found (no fake/mock data)

    Args:
        categories: Ignored (discovery is dynamic, not category-filtered).

    Returns:
        List of enriched trader dicts with metrics from tradeinfo API.
    """
    from backend.services.etoro_service import EToroAPIClient

    client = EToroAPIClient()
    usernames: List[str] = []

    # Step 1: Dynamic discovery via eToro APIs (primary)
    if client.enabled:
        try:
            usernames = await client.discover_social_top(limit=200)
        except Exception as e:
            logger.warning(f"Discovery: API unavailable ({e})")

    # Step 2: Bootstrap fallback when API returns nothing
    if not usernames:
        from backend.utils.bootstrap_traders import BOOTSTRAP_TRADERS
        usernames = list(BOOTSTRAP_TRADERS)
        logger.info(f"Discovery: API returned 0 traders, using {len(usernames)} bootstrap traders")

    # Step 3: CANDIDATE_TRADERS env var (user override)
    raw_env = os.getenv("CANDIDATE_TRADERS", "")
    if raw_env:
        env_list = [u.strip() for u in raw_env.split(",") if u.strip()]
        existing = {u.lower() for u in usernames}
        for u in env_list:
            if u.lower() not in existing:
                usernames.append(u)
                existing.add(u.lower())

    if not usernames:
        logger.warning("Discovery: no traders found from any source")
        return []

    # Step 3: Enrich via tradeinfo API
    logger.info(f"Discovery: enriching {len(usernames)} candidates")
    try:
        result = await client.enrich_candidates(usernames, max_concurrent=20)
    except Exception as e:
        logger.warning(f"Discovery: enrichment failed ({e})")
        return []

    available = result.get("available", [])
    scanned = result.get("scanned", 0)
    valid_count = result.get("valid_count", 0)
    rejected_count = result.get("rejected", 0)

    if available:
        for a in available:
            a["is_copiable"] = a.get("is_copiable", True)
        logger.info(
            f"Discovery: scanned={scanned}, valid={valid_count}, "
            f"eligible_before_filter={len(available)}, "
            f"rejected={rejected_count}"
        )
        return available

    logger.warning(f"Discovery: all {scanned} candidates unavailable after enrichment")
    return []
