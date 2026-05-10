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


async def get_market_news(symbols: Optional[List[str]] = None) -> List[Dict]:
    """Fetch live news headlines for major indices using yfinance.

    Args:
        symbols: List of Yahoo Finance ticker symbols (default: S&P 500,
                 Nasdaq, Dow Jones).

    Returns up to 10 unique news items with title, summary, source.
    """
    import yfinance as yf
    import asyncio

    if symbols is None:
        symbols = ["^GSPC", "^IXIC", "^DJI"]

    def _fetch():
        seen = set()
        items = []
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                news = ticker.news or []
                for article in news:
                    title = article.get("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        items.append({
                            "title": title,
                            "summary": (article.get("summary") or "")[:300],
                            "source": article.get("publisher", "Yahoo Finance"),
                        })
                        if len(items) >= 10:
                            return items
            except Exception:
                continue
        return items

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


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
    except Exception:
        pass
    logger.info("Scout: no market news available")
    return [{
        "title": "Market news unavailable",
        "summary": "Could not fetch live headlines. Scout will rely on trader metrics only.",
        "source": "system",
    }]


# ── 3. eToro Discovery (Top Traders) ─────────────────────────────


async def discover_top_traders() -> List[Dict]:
    """Fetch top-performing traders from eToro's public discovery API.

    Returns up to 15 trader candidates with username, risk, and return
    data. Falls back to static defaults if API is unreachable.
    """
    etoro_url = "https://public-api.etoro.com/api/v1/markets/copy/top"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                etoro_url,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"Scout: fetched top traders from eToro discovery")
                return _parse_etoro_discovery(data)

            logger.warning(f"eToro discovery returned {resp.status_code}")
            return _default_trader_candidates()

    except Exception as e:
        logger.warning(f"eToro discovery unavailable: {e}")
        return _default_trader_candidates()


def _parse_etoro_discovery(data: dict) -> List[Dict]:
    """Extract relevant fields from eToro discovery API response."""
    raw_list = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("data", data.get("results", data.get("PopularCopyTraders", [])))

    candidates = []
    for entry in raw_list[:15]:
        if isinstance(entry, dict):
            candidates.append({
                "username": entry.get("Username") or entry.get("username", "unknown"),
                "risk_score": entry.get("RiskScore") or entry.get("risk_score", 5),
                "total_return_pct": entry.get("TotalReturn") or entry.get("total_return_pct", 0),
                "copiers": entry.get("Copiers") or entry.get("copiers", 0),
            })
    return candidates


def _default_trader_candidates() -> List[Dict]:
    """Static candidate list when eToro discovery API is unavailable."""
    return [
        {"username": "ConsistentCapital", "risk_score": 3, "total_return_pct": 8.5, "copiers": 1200},
        {"username": "ValueHunterPro",    "risk_score": 4, "total_return_pct": 12.2, "copiers": 890},
        {"username": "SectorTrader",      "risk_score": 5, "total_return_pct": 15.0, "copiers": 650},
        {"username": "MacroView",         "risk_score": 3, "total_return_pct": 9.8, "copiers": 1100},
        {"username": "BalancedReturns",   "risk_score": 4, "total_return_pct": 11.4, "copiers": 750},
    ]
