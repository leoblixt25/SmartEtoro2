"""Shared fetch layer — rate-limited, cached, safe HTTP client.

All outbound requests go through SafeFetcher, which enforces:
  - Global semaphore (max 8 concurrent, configurable)
  - Jittered exponential backoff (transient errors only)
  - Early-stop after repeated 429s
  - In-memory response cache (TTL-based)
  - Structured logging via utils.safe_log
"""

from __future__ import annotations
import asyncio
import json
import logging
import random
import time
from typing import Any, Dict, Optional

import httpx

from backend.discovery.config import (
    API_SEMAPHORE_MAX,
    RATE_LIMIT_HIT_STOP,
    REQUEST_TIMEOUT,
    RETRY_MAX_ATTEMPTS,
    RETRY_BASE_DELAY,
)
from backend.utils.safe_log import safe_fmt

logger = logging.getLogger(__name__)


class SafeFetcher:
    """Thread-safe, rate-limited HTTP client for eToro API calls.

    Usage:
        fetcher = SafeFetcher(api_key="...", user_key="...")
        data = await fetcher.get("https://public-api.etoro.com/api/v1/...")
    """

    _shared_semaphore = asyncio.Semaphore(API_SEMAPHORE_MAX)
    _rate_limit_hits: int = 0
    _cache: Dict[str, tuple[float, Any]] = {}
    _cache_ttl: float = 60.0  # seconds; overridden per-request

    def __init__(
        self,
        api_key: Optional[str] = None,
        user_key: Optional[str] = None,
        semaphore_max: int = API_SEMAPHORE_MAX,
    ):
        self._api_key = api_key
        self._user_key = user_key
        self._instance_sem = asyncio.Semaphore(semaphore_max)

    # ── Public API ──────────────────────────────────────────────────

    async def get(
        self,
        url: str,
        params: Optional[Dict] = None,
        timeout: float = REQUEST_TIMEOUT,
        headers: Optional[Dict] = None,
        cache_ttl: float = 0.0,
    ) -> Optional[Any]:
        """GET request with rate limiting, retry, and optional caching.

        Args:
            url: Target URL.
            params: Optional query parameters.
            timeout: Request timeout in seconds.
            headers: Optional override headers.
            cache_ttl: Cache TTL in seconds. 0 = no caching.

        Returns:
            Parsed JSON on success, None on failure.
        """
        cache_key = self._cache_key(url, params)

        # ── Cache check ───────────────────────────────────────────
        if cache_ttl > 0 and cache_key in self._cache:
            cached_at, cached_val = self._cache[cache_key]
            if time.time() - cached_at < cache_ttl:
                logger.debug("Cache HIT %s (%.0fs old)", url, time.time() - cached_at)
                return cached_val

        # ── Rate limit guard ──────────────────────────────────────
        if SafeFetcher._rate_limit_hits >= RATE_LIMIT_HIT_STOP:
            logger.error("FETCH DEGRADED: %d+ rate limit hits — skipping %s",
                         RATE_LIMIT_HIT_STOP, url)
            return None

        # ── Retry loop ────────────────────────────────────────────
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                async with SafeFetcher._shared_semaphore, self._instance_sem:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.get(url, params=params, headers=headers or {})

                body = resp.text[:500] if resp.text else "(empty)"

                # ── Success ───────────────────────────────────────
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        logger.debug("GET %s → 200 (%d bytes)", url, len(resp.text))
                        if cache_ttl > 0:
                            SafeFetcher._cache[cache_key] = (time.time(), data)
                        return data
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.error("GET %s → 200 INVALID JSON: %s | body=%s", url, e, body)
                        return None

                # ── No content ────────────────────────────────────
                if resp.status_code == 204:
                    logger.info("GET %s → 204", url)
                    return None

                # ── Auth errors (not retryable) ───────────────────
                if resp.status_code in (401, 403):
                    logger.error("GET %s → %d (auth)", url, resp.status_code)
                    return None

                # ── Not found (not retryable) ─────────────────────
                if resp.status_code == 404:
                    logger.info("GET %s → 404", url)
                    return None

                # ── Rate limited (retry with jitter) ──────────────
                if resp.status_code == 429:
                    SafeFetcher._rate_limit_hits += 1
                    if SafeFetcher._rate_limit_hits >= RATE_LIMIT_HIT_STOP:
                        logger.error("GET %s → 429 (%d hits) — stopping retries", url, SafeFetcher._rate_limit_hits)
                        return None
                    if attempt < RETRY_MAX_ATTEMPTS:
                        delay = (RETRY_BASE_DELAY ** attempt) + random.uniform(0, 1)
                        logger.warning("GET %s → 429 (hit #%d), retry %d/%d after %.1fs",
                                       url, SafeFetcher._rate_limit_hits, attempt, RETRY_MAX_ATTEMPTS, delay)
                        await asyncio.sleep(delay)
                        continue
                    logger.error("GET %s → 429, retries exhausted", url)
                    return None

                # ── Server errors (retry) ─────────────────────────
                if 500 <= resp.status_code < 600:
                    if attempt < RETRY_MAX_ATTEMPTS:
                        delay = RETRY_BASE_DELAY ** attempt
                        logger.warning("GET %s → %d, retry %d/%d after %.1fs | body=%s",
                                       url, resp.status_code, attempt, RETRY_MAX_ATTEMPTS, delay, body)
                        await asyncio.sleep(delay)
                        continue
                    logger.error("GET %s → %d, retries exhausted | body=%s", url, resp.status_code, body)
                    return None

                # ── Other (300, 400 without auth/404) ─────────────
                logger.warning("GET %s → %d (unhandled) | body=%s", url, resp.status_code, body)
                return None

            except httpx.TimeoutException:
                if attempt < RETRY_MAX_ATTEMPTS:
                    delay = (RETRY_BASE_DELAY ** attempt) + random.uniform(0, 1)
                    logger.warning("GET %s → Timeout, retry %d/%d after %.1fs", url, attempt, RETRY_MAX_ATTEMPTS, delay)
                    await asyncio.sleep(delay)
                    continue
                logger.error("GET %s → Timeout, retries exhausted", url)
                return None

            except httpx.RequestError as e:
                if attempt < RETRY_MAX_ATTEMPTS:
                    delay = (RETRY_BASE_DELAY ** attempt) + random.uniform(0, 1)
                    logger.warning("GET %s → RequestError, retry %d/%d after %.1fs: %s",
                                   url, attempt, RETRY_MAX_ATTEMPTS, delay, e)
                    await asyncio.sleep(delay)
                    continue
                logger.error("GET %s → RequestError, retries exhausted: %s", url, e)
                return None

            except Exception as e:
                logger.error("GET %s → Unexpected: %s", url, e)
                return None

        return None

    async def get_browser(
        self,
        url: str,
        params: Optional[Dict] = None,
        timeout: float = 10.0,
        cache_ttl: float = 0.0,
    ) -> Optional[Any]:
        """GET with browser-like headers (for public/non-API endpoints)."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.etoro.com/",
        }
        return await self.get(url, params=params, timeout=timeout, headers=headers, cache_ttl=cache_ttl)

    def clear_cache(self) -> None:
        SafeFetcher._cache.clear()

    def reset_rate_limit(self) -> None:
        SafeFetcher._rate_limit_hits = 0

    @property
    def rate_limit_hits(self) -> int:
        return SafeFetcher._rate_limit_hits

    @property
    def is_degraded(self) -> bool:
        return SafeFetcher._rate_limit_hits >= RATE_LIMIT_HIT_STOP

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(url: str, params: Optional[Dict]) -> str:
        if params:
            return f"{url}?{json.dumps(params, sort_keys=True)}"
        return url
