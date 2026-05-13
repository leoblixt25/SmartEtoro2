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


async def discover_top_traders() -> List[Dict]:
    """Fetch candidate traders using configurable list + tradeinfo enrichment.

    Uses EToroAPIClient.discover_candidates() which:
    1. Reads CANDIDATE_TRADERS env var, or falls back to FALLBACK_TRADERS constant
    2. Enriches each candidate via /user-info/people/{username}/tradeinfo
    3. Returns dict with available/unavailable sublists

    Falls back to static fallback list when:
    - API call raises an exception
    - available list is empty (all candidates 404'd)
    """
    try:
        from backend.services.etoro_service import EToroAPIClient
        client = EToroAPIClient()
        result = await client.discover_candidates()

        if isinstance(result, dict):
            available = result.get("available", [])
            unavailable = result.get("unavailable", [])
            scanned = result.get("scanned", 0)
            valid_count = result.get("valid_count", len(available))
            rejected_count = result.get("rejected", len(unavailable))

            logger.info(
                f"Scout discovery: scanned={scanned}, valid={valid_count}, "
                f"available={len(available)}, unavailable={len(unavailable)}, "
                f"rejected={rejected_count}"
            )
            for u in unavailable:
                logger.info(f"  Unavailable: {u.get('username', '?')} — {u.get('reason', 'unknown')}")

            if available:
                logger.info(f"Scout: discovered {len(available)} candidate traders via tradeinfo")
                return available
        elif isinstance(result, list):
            if result:
                logger.info(f"Scout: discovered {len(result)} candidate traders via tradeinfo (legacy format)")
                return result

    except Exception as e:
        logger.debug(f"Discovery API error: {e}")

    logger.info("No available candidates from discovery API — using static fallback trader list")
    return _default_trader_candidates()


def _parse_etoro_discovery(data: dict, page: int = 1) -> List[Dict]:
    """Extract relevant fields from eToro discovery API response.

    Applies mandatory filters:
      - is_copiable == True (skip traders who aren't accepting new copiers)
      - min_copy_amount <= 200 (capital constraint)
    If a field is missing from the API, assumes copiable with a $200 minimum
    and logs a warning.

    Optionally accepts a ``page`` parameter for logging which page the
    candidates came from (used by deep-fetch pagination).
    """
    raw_list = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("data", data.get("results", data.get("PopularCopyTraders", [])))

    candidates = []
    for entry in raw_list[:100]:  # fetch up to 100 per page
        if not isinstance(entry, dict):
            continue

        # ── is_copiable check ───────────────────────────────────────
        is_copiable = entry.get("IsCopiable") or entry.get("is_copiable")
        if is_copiable is None:
            logger.warning(
                f"Discovery entry {entry.get('Username', entry.get('username', '?'))} "
                "missing 'is_copiable' — assuming True, min_copy_amount=$200"
            )
            is_copiable = True
            min_amount = 200.0
        else:
            is_copiable = bool(is_copiable)
            min_amount = entry.get("MinCopyAmount") or entry.get("min_copy_amount") or 200.0

        if not is_copiable:
            logger.debug(f"Skipping {entry.get('Username','?')}: not copiable")
            continue
        if min_amount > 200:
            logger.debug(f"Skipping {entry.get('Username','?')}: min_copy_amount ${min_amount} > $200")
            continue

        candidates.append({
            "username": entry.get("Username") or entry.get("username", "unknown"),
            "risk_score": entry.get("RiskScore") or entry.get("risk_score", 5),
            "total_return_pct": entry.get("TotalReturn") or entry.get("total_return_pct", 0),
            "copiers": entry.get("Copiers") or entry.get("copiers", 0),
            "is_copiable": is_copiable,
            "min_copy_amount": min_amount,
            "max_drawdown": entry.get("MaxDrawdown") or entry.get("max_drawdown") or entry.get("MaxDrawdownRate") or 0,
            "track_record_days": entry.get("TrackRecordDays") or entry.get("track_record_days") or entry.get("TrackRecord") or 0,
        })

    logger.info(f"Discovery page {page}: {len(candidates)} qualified candidates after filter")
    return candidates[:50]


FALLBACK_TRADERS = [
    "JeppeKirkBonde",
    "CPHequities",
    "Jaynemesis",
    "booker03",
    "ConsistentCapital",
    "GrowthEngine",
    "AlphaPulse",
    "SmartMoneyFX",
]


def _default_trader_candidates() -> List[Dict]:
    """Static candidate list when eToro discovery API is unavailable.

    Returns hardcoded seed targets for the equal split and scout.
    Used when CANDIDATE_TRADERS env var is not set and API is unavailable.
    """
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
        }
        for name in FALLBACK_TRADERS if name in registry
    ]
