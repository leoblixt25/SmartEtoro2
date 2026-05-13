"""
News Cache — TTL-based in-memory cache for per-symbol news results.

Prevents repeated API calls for the same symbol within the TTL window.
Thread-safe for async use (single-process, no locking needed).
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 1800  # 30 minutes


class NewsCache:
    """In-memory cache for news results keyed by symbol.

    Each entry stores:
      - news: list of news item dicts
      - expires_at: unix timestamp when the entry expires
      - symbol: the stock/crypto symbol
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._store: Dict[str, dict] = {}

    def get(self, symbol: str) -> Optional[List[dict]]:
        """Return cached news for symbol, or None if expired/missing."""
        entry = self._store.get(symbol.upper())
        if entry is None:
            logger.debug("CACHE MISS for %s", symbol.upper())
            return None
        if time.time() > entry["expires_at"]:
            logger.debug("CACHE EXPIRED for %s", symbol.upper())
            del self._store[symbol.upper()]
            return None
        logger.debug("CACHE HIT for %s (%d items)", symbol.upper(), len(entry["news"]))
        return entry["news"]

    def set(self, symbol: str, news: List[dict]) -> None:
        """Store news for symbol with TTL."""
        self._store[symbol.upper()] = {
            "news": news,
            "expires_at": time.time() + self._ttl,
            "symbol": symbol.upper(),
        }
        logger.debug("CACHE SET %s (%d items, ttl=%ds)", symbol.upper(), len(news), self._ttl)

    def invalidate(self, symbol: Optional[str] = None) -> None:
        """Clear cache for one symbol, or all if symbol is None."""
        if symbol:
            self._store.pop(symbol.upper(), None)
            logger.debug("CACHE INVALIDATED %s", symbol.upper())
        else:
            self._store.clear()
            logger.debug("CACHE CLEARED all entries")

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def symbols(self) -> List[str]:
        return list(self._store.keys())


_default_cache = NewsCache()


def get_news_cache() -> NewsCache:
    return _default_cache
