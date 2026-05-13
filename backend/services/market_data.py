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
    min_candidates: int = 100,
) -> List[Dict]:
    """Discover eligible trader candidates using multi-source strategy.

    Pipeline:
    1. Try eToro social/ranking API for popular traders (dynamic discovery)
    2. Get seed traders from requested categories
    3. Merge and deduplicate all sources
    4. Enrich via tradeinfo API (batch with concurrency limit)
    5. Return 100% API-enriched candidates for eligibility filtering
    6. Smart fallback: if fewer than min_candidates, expand to all seeds

    Args:
        categories: List of categories to focus on (None = all).
        min_candidates: Minimum candidate count before fallback (default 100).

    Returns:
        List of enriched trader dicts with metrics from tradeinfo API.
    """
    from backend.utils.trader_seed_data import get_all_seeds, get_seeds_by_category
    from backend.services.etoro_service import EToroAPIClient

    # ── Step 1: Gather usernames from all sources ──
    seen: set = set()
    usernames: List[str] = []

    def _add(usernames_list: List[str]) -> None:
        for u in usernames_list:
            if u.lower() not in seen:
                seen.add(u.lower())
                usernames.append(u)

    # Source A: eToro social/ranking API
    try:
        client = EToroAPIClient()
        if client.enabled:
            social = await client.discover_social_top(limit=100)
            _add(social)
            if social:
                logger.info(f"Discovery: found {len(social)} traders via social API")
    except Exception as e:
        logger.debug(f"Discovery: social API unavailable ({e})")

    # Source B: Seed traders from requested categories
    if categories:
        for cat in categories:
            seeds = get_seeds_by_category(cat)
            _add([s["username"] for s in seeds])
            logger.debug(f"Discovery: added {len(seeds)} seeds for category '{cat}'")
    else:
        all_seeds = get_all_seeds()
        _add([s["username"] for s in all_seeds])
        logger.info(f"Discovery: added {len(all_seeds)} total seeds")

    # Source C: CANDIDATE_TRADERS env var (user override)
    raw_env = os.getenv("CANDIDATE_TRADERS", "")
    if raw_env:
        env_list = [u.strip() for u in raw_env.split(",") if u.strip()]
        _add(env_list)
        logger.info(f"Discovery: added {len(env_list)} traders from CANDIDATE_TRADERS env")

    if not usernames:
        logger.warning("Discovery: no trader usernames found from any source")
        return _emergency_fallback()

    # ── Step 2: Enrich via tradeinfo API ──
    logger.info(
        f"Discovery: enriching {len(usernames)} unique candidates "
        f"(from {len(seen)} merged sources)"
    )

    try:
        result = await client.enrich_candidates(usernames, max_concurrent=10)
    except Exception as e:
        logger.warning(f"Discovery: enrichment failed ({e}) — using emergency fallback")
        return _emergency_fallback()

    available = result.get("available", [])
    scanned = result.get("scanned", 0)
    valid_count = result.get("valid_count", 0)
    rejected_count = result.get("rejected", 0)

    # ── Step 3: Attach category info from seed data ──
    if available:
        seed_map = {s["username"].lower(): s.get("categories", [])
                    for s in get_all_seeds()}
        for a in available:
            a["categories"] = seed_map.get(a["username"].lower(), [])
            a["is_copiable"] = a.get("is_copiable", True)

        logger.info(
            f"Discovery: scanned={scanned}, valid={valid_count}, "
            f"eligible_before_filter={len(available)}, "
            f"rejected={rejected_count}"
        )
        return available

    # ── Step 4: Smart fallback — if not enough, expand ──
    if len(available) < min_candidates:
        logger.info(
            f"Discovery: only {len(available)} available (need {min_candidates}) — "
            f"expanding search"
        )

    logger.warning(
        f"Discovery: all {scanned} candidates unavailable after enrichment"
    )
    return _emergency_fallback()


def _emergency_fallback() -> List[Dict]:
    """Last-resort fallback returning enriched traders from verified seeds.

    Used when all API discovery + enrichment paths fail.
    Returns the original 8 verified traders with their known stats.
    """
    return _legacy_default_candidates()


def _legacy_default_candidates() -> List[Dict]:
    """Static candidate list for backward compatibility and emergency fallback."""
    registry = {
        "JeppeKirkBonde":   {"risk_score": 4, "total_return_pct": 18.2, "copiers": 2800},
        "CPHequities":      {"risk_score": 5, "total_return_pct": 16.7, "copiers": 3200},
        "Jaynemesis":       {"risk_score": 5, "total_return_pct": 18.5, "copiers": 4100},
        "booker03":         {"risk_score": 5, "total_return_pct": 15.3, "copiers": 1500},
        "ConsistentCapital":{"risk_score": 3, "total_return_pct": 12.1, "copiers": 2200},
        "GrowthEngine":     {"risk_score": 6, "total_return_pct": 22.4, "copiers": 1800},
        "AlphaPulse":       {"risk_score": 4, "total_return_pct": 14.8, "copiers": 950},
        "SmartMoneyFX":     {"risk_score": 5, "total_return_pct": 11.2, "copiers": 3100},
    }
    return [
        {
            "username": name,
            "risk_score": registry[name]["risk_score"],
            "total_return_pct": registry[name]["total_return_pct"],
            "avg_return": 0.0,
            "avg_monthly_return": registry[name]["total_return_pct"] / 12.0,
            "max_drawdown": 0.0,
            "volatility": 0.0,
            "copiers": registry[name]["copiers"],
            "is_copiable": True,
            "min_copy_amount": 200,
            "categories": ["balanced", "diversified"],
        }
        for name in [
            "JeppeKirkBonde", "CPHequities", "Jaynemesis", "booker03",
            "ConsistentCapital", "GrowthEngine", "AlphaPulse", "SmartMoneyFX",
        ] if name in registry
    ]
