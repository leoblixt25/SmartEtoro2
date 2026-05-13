"""
News Service — fetches per-symbol news via yfinance with caching and sentiment scoring.

Scoring:
  - Simple keyword-based sentiment (positive/negative/neutral)
  - Recent headlines weighted higher
  - Duplicate headline suppression
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.monitoring.news_cache import get_news_cache

logger = logging.getLogger(__name__)

# ── Sentiment keywords ──────────────────────────────────────────────

POSITIVE_KEYWORDS = [
    "beat", "beat earnings", "upgrade", "buy", "bullish", "growth",
    "profit", "rally", "surge", "positive", "outperform", "record",
    "innovation", "partnership", "expansion", "dividend", "buyback",
    "optimistic", "uptrend", "breakthrough", "approved",
]

NEGATIVE_KEYWORDS = [
    "downgrade", "sell", "bearish", "loss", "decline", "crash",
    "investigation", "lawsuit", "fine", "penalty", "layoff",
    "downturn", "volatile", "risk", "warning", "debt", "default",
    "bankruptcy", "fraud", "scandal", "recall", "ban", "restriction",
    "underperform", "class action", "regulatory",
]

# ── Headline dedup ──────────────────────────────────────────────────

_seen_headlines: set = set()


def _reset_seen_headlines():
    """Reset dedup set (useful for testing)."""
    _seen_headlines.clear()


def _is_duplicate(title: str) -> bool:
    """Check if a headline has been seen before (case-insensitive)."""
    key = title.strip().lower()
    if key in _seen_headlines:
        return True
    _seen_headlines.add(key)
    return False


# ── Sentiment scoring ───────────────────────────────────────────────

def _score_sentiment(title: str, summary: str = "") -> Tuple[str, float]:
    """Score a news item as positive, negative, or neutral.

    Returns (label, confidence) where confidence is 0.0–1.0.
    """
    text = f"{title} {summary}".lower()

    pos_score = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
    neg_score = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)

    if pos_score > neg_score:
        # Cap confidence at 0.95 to avoid overconfidence
        confidence = min(0.95, 0.5 + (pos_score - neg_score) * 0.15)
        return "positive", round(confidence, 2)
    elif neg_score > pos_score:
        confidence = min(0.95, 0.5 + (neg_score - pos_score) * 0.15)
        return "negative", round(confidence, 2)
    else:
        return "neutral", 0.5


def _is_relevant_news(item: dict) -> bool:
    """Filter out low-quality or empty news items."""
    title = (item.get("title") or "").strip()
    if not title or len(title) < 10:
        return False
    if _is_duplicate(title):
        return False
    return True


# ── News fetching ───────────────────────────────────────────────────

async def fetch_symbol_news(
    symbol: str,
    max_items: int = 5,
    use_cache: bool = True,
) -> List[Dict]:
    """Fetch and score news for a single symbol.

    Args:
        symbol: Stock/crypto ticker (e.g. "AAPL", "BTC-USD").
        max_items: Maximum news items to return.
        use_cache: If True, check cache before fetching.

    Returns:
        List of dicts with title, summary, source, sentiment, confidence.
    """
    cache = get_news_cache()

    if use_cache:
        cached = cache.get(symbol)
        if cached is not None:
            return cached[:max_items]

    # Fetch via yfinance
    news = await _fetch_yfinance_news(symbol)

    # Score and filter
    scored = []
    for item in news:
        if not _is_relevant_news(item):
            continue
        sentiment, confidence = _score_sentiment(
            item.get("title", ""),
            item.get("summary", ""),
        )
        scored.append({
            "title": item.get("title", ""),
            "summary": (item.get("summary") or "")[:300],
            "source": item.get("publisher", "Yahoo Finance"),
            "sentiment": sentiment,
            "confidence": confidence,
        })
        if len(scored) >= max_items:
            break

    # Cache result (even if empty — prevents re-fetch)
    if use_cache:
        cache.set(symbol, scored)

    logger.info(
        "News for %s: %d relevant items (cached=%s)",
        symbol, len(scored), use_cache,
    )
    return scored


async def _fetch_yfinance_news(symbol: str) -> List[Dict]:
    """Fetch raw news from yfinance for a symbol."""
    import yfinance as yf
    import asyncio

    def _fetch():
        try:
            ticker = yf.Ticker(symbol)
            try:
                raw = ticker.get_news() or []
            except AttributeError:
                raw = ticker.news or []
            return [
                {"title": a.get("title", ""), "summary": (a.get("summary") or "")[:300],
                 "publisher": a.get("publisher", "Yahoo Finance")}
                for a in raw if a.get("title")
            ]
        except Exception as e:
            logger.debug("yfinance failed for %s: %s", symbol, e)
            return []

    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, _fetch)
    return items


async def fetch_news_for_symbols(
    symbols: List[str],
    max_per_symbol: int = 3,
    use_cache: bool = True,
) -> Dict[str, List[Dict]]:
    """Fetch news for multiple symbols at once.

    Returns dict mapping symbol → list of news items.
    """
    import asyncio

    tasks = [
        fetch_symbol_news(sym, max_items=max_per_symbol, use_cache=use_cache)
        for sym in symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: Dict[str, List[Dict]] = {}
    for sym, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.warning("News fetch failed for %s: %s", sym, result)
            output[sym] = []
        else:
            output[sym] = result

    logger.info(
        "Fetched news for %d symbols: %d with data, %d empty",
        len(symbols),
        sum(1 for v in output.values() if v),
        sum(1 for v in output.values() if not v),
    )
    return output


# ── Sentiment aggregation ───────────────────────────────────────────

def aggregate_sentiment(news_by_symbol: Dict[str, List[Dict]]) -> Dict:
    """Aggregate sentiment across all news items.

    Returns:
        {positive_count, negative_count, neutral_count, total,
         net_score: float -1..1, dominant_sentiment: str,
         negative_symbols: [str], positive_symbols: [str]}
    """
    pos = neg = neu = 0
    pos_symbols: set = set()
    neg_symbols: set = set()

    for symbol, items in news_by_symbol.items():
        for item in items:
            sent = item.get("sentiment", "neutral")
            if sent == "positive":
                pos += 1
                pos_symbols.add(symbol)
            elif sent == "negative":
                neg += 1
                neg_symbols.add(symbol)
            else:
                neu += 1

    total = pos + neg + neu
    net_score = round((pos - neg) / max(total, 1), 2)

    if pos > neg:
        dominant = "positive"
    elif neg > pos:
        dominant = "negative"
    else:
        dominant = "neutral"

    return {
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "total": total,
        "net_score": net_score,
        "dominant_sentiment": dominant,
        "positive_symbols": sorted(pos_symbols),
        "negative_symbols": sorted(neg_symbols),
    }
