"""
eToro API Service
────────────────────────────────────────────────────────────────────
Handles real-time data synchronization with the official eToro API
at https://public-api.etoro.com.
"""

from __future__ import annotations
import json
import os
import uuid
import logging
from typing import Dict, List, Optional
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

from backend.utils.safe_log import safe_fmt


class EToroAPIClient:
    """
    Client for the official eToro Public API.

    Authentication uses two keys from your eToro Settings > Trading:
      - x-api-key  : Public API Key (alphanumeric app identifier)
      - x-user-key : User Key (JWT token, starts with "eyJ")

    Both keys are required. Generate them at https://www.etoro.com -> Settings -> Trading.
    """

    BASE_URL = "https://public-api.etoro.com"

    def __init__(self):
        # NOTE: env var ETORO_API_KEY stores the User Key (JWT),
        #       ETORO_API_SECRET stores the Public API Key (alphanumeric).
        self.user_key = os.getenv("ETORO_API_KEY")
        self.api_key = os.getenv("ETORO_API_SECRET")
        self.account_id = os.getenv("ETORO_ACCOUNT_ID", "")
        # ETORO_ENV overrides the API environment segment (e.g. "demo").
        # Some API keys only have demo permissions — set this to "demo" in that case.
        self.env = os.getenv("ETORO_ENV", "real").strip().lower()

        if not self.api_key or not self.user_key:
            logger.warning("eToro API credentials not configured")
            self.enabled = False
        else:
            self.enabled = True

    def _get_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "x-user-key": self.user_key,
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    def _validate_mirror_id(self, mirror_id: int, operation: str = "") -> bool:
        """Reject mirror_id=0 before hitting the eToro API.

        A mirror ID of 0 means the trader was never properly synced
        (e.g. the sync call failed and the DB was never populated).
        Returns False if the ID is invalid, True otherwise.
        """
        if not mirror_id or mirror_id <= 0:
            logger.error(f"Cannot execute '{operation}' — invalid mirror_id={mirror_id}. "
                         "Run /sync first to populate mirror IDs from eToro.")
            return False
        return True

    async def get_portfolio_data(self) -> Optional[Dict]:
        """
        Fetch portfolio + PnL + positions + mirrors in one call.
        Retries up to 3 times with 5-second backoff on failure.
        """
        if not self.enabled:
            return None

        env = self.env
        last_error = None
        import asyncio

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/api/v1/trading/info/{env}/pnl",
                        headers=self._get_headers(),
                    )
                    response.raise_for_status()
                    data = response.json()
                    logger.info(
                        f"Fetched portfolio data from eToro ({env}) attempt {attempt}")
                    return data
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    f"eToro API error {e.response.status_code} (attempt {attempt}/3): {e.response.text[:200]}")
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    f"Network error (attempt {attempt}/3): {e}")
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Unexpected error (attempt {attempt}/3): {e}")

            if attempt < 3:
                await asyncio.sleep(5)

        logger.error(f"eToro API failed after 3 attempts: {last_error}")
        return None

    async def execute_close_mirror(self, mirror_id: int) -> Optional[Dict]:
        """Close a copy-trade mirror position on eToro using the retail API.

        Uses DELETE /api/v1/trading/mirrors/{env}/{mirrorId} — the standard
        retail endpoint for stopping a copy relationship.

        If the endpoint returns 404 RouteNotFound, mirror closing is not
        available on this API plan. The method will log the reason and return
        an error without crashing.
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "close_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot close"}

        # Retail/demo API does not support mirror closing — skip HTTP call entirely
        if self.env in ("demo", "retail"):
            logger.warning(
                f"Mirror close not supported on {self.env} API — "
                f"skipping DELETE for mirror {mirror_id}"
            )
            return {
                "error": True,
                "status": 404,
                "detail": (
                    f"Mirror closing is not available on {self.env} API plan. "
                    f"This feature requires eToro Agent API access."
                ),
                "not_supported": True,
            }

        env = self.env
        url = f"{self.BASE_URL}/api/v1/trading/mirrors/{env}/{mirror_id}"
        logger.info(f"Closing mirror via DELETE {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(url, headers=self._get_headers())
                if response.status_code == 404:
                    detail = (
                        f"DELETE {url} returned 404 RouteNotFound — mirror closing "
                        "not available on retail/demo API plan. This feature requires "
                        "eToro Agent API access which is not available."
                    )
                    logger.error(detail)
                    return {
                        "error": True,
                        "status": 404,
                        "detail": detail,
                        "endpoint": url,
                    }
                response.raise_for_status()
                result = response.json() if response.text else {}
                logger.info(f"Closed mirror {mirror_id} ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            resp_body = e.response.text[:500]
            logger.error(
                f"eToro close-mirror error {e.response.status_code} "
                f"on {url}: {resp_body}"
            )
            return {
                "error": True,
                "status": e.response.status_code,
                "detail": f"HTTP {e.response.status_code} closing mirror {mirror_id}: {resp_body}",
                "endpoint": url,
            }
        except httpx.RequestError as e:
            logger.error(f"Network error closing mirror {mirror_id} via {url}: {e}")
            return {"error": True, "detail": str(e), "endpoint": url}
        except Exception as e:
            logger.error(f"Unexpected error closing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e), "endpoint": url}

    async def execute_change_mirror_amount(self, mirror_id: int, new_amount: float) -> Optional[Dict]:
        """Change the allocated amount of a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/change-amount
        Body: {"amount": <new_amount>}
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "change_mirror_amount"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot change amount"}

        env = self.env
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{env}/{mirror_id}/change-amount",
                    headers=self._get_headers(),
                    json={"mirrorId": mirror_id, "amount": new_amount},
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Changed mirror {mirror_id} amount to {new_amount} ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"eToro change-amount error {e.response.status_code}: {e.response.text}")
            return {"error": True, "status": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"Network error changing mirror {mirror_id} amount: {e}")
            return {"error": True, "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error changing mirror {mirror_id} amount: {e}")
            return {"error": True, "detail": str(e)}

    async def execute_pause_mirror(self, mirror_id: int) -> Optional[Dict]:
        """Pause a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/pause
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "pause_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot pause"}

        env = self.env
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{env}/{mirror_id}/pause",
                    headers=self._get_headers(),
                    json={"mirrorId": mirror_id},
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Paused mirror {mirror_id} on eToro ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"eToro pause-mirror error {e.response.status_code}: {e.response.text}")
            return {"error": True, "status": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"Network error pausing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error pausing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}

    async def execute_unpause_mirror(self, mirror_id: int) -> Optional[Dict]:
        """Unpause a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/unpause
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "unpause_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot unpause"}

        env = self.env
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{env}/{mirror_id}/unpause",
                    headers=self._get_headers(),
                    json={"mirrorId": mirror_id},
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Unpaused mirror {mirror_id} on eToro ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"eToro unpause-mirror error {e.response.status_code}: {e.response.text}")
            return {"error": True, "status": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"Network error unpausing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error unpausing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}

    async def execute_start_mirror(self, username: str, amount: float) -> Dict:
        """Start copying a trader on eToro via the retail API.

        Tries multiple endpoint formats since the retail/demo API may not
        support programmatic mirror creation:
          1. POST /api/v1/trading/mirrors/{env}  (original, may 404)
          2. POST /api/v1/trading/mirrors          (without env segment)

        If both return 404 RouteNotFound, the feature is not available on
        the current API plan. Returns an error instead of silent failure.
        """
        if not self.enabled:
            return {"error": True, "detail": "eToro API not configured"}

        if amount < 200:
            logger.error(f"Cannot start mirror for {username}: amount ${amount:,.2f} is below eToro's $200 minimum")
            return {"error": True, "detail": f"Amount ${amount:,.2f} is below eToro's $200 minimum copy amount"}

        env = self.env
        body = {"username": username, "amount": amount, "isDemo": False}

        # Attempt 1: POST /api/v1/trading/mirrors/{env}
        urls_to_try = [
            f"{self.BASE_URL}/api/v1/trading/mirrors/{env}",
            f"{self.BASE_URL}/api/v1/trading/mirrors",
        ]

        last_error = None
        for url in urls_to_try:
            logger.info(f"Starting mirror for {username} via POST {url}")
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, headers=self._get_headers(), json=body)
                    if response.status_code == 404:
                        logger.warning(f"POST {url} returned 404 — trying next endpoint format")
                        last_error = {
                            "status": 404,
                            "detail": f"POST {url} — 404 RouteNotFound. Endpoint not available on retail/demo API plan.",
                            "endpoint_tried": url,
                        }
                        continue
                    response.raise_for_status()
                    result = response.json()
                    logger.info(f"Started mirror for {username} via {url}: {result}")
                    return result
            except httpx.HTTPStatusError as e:
                resp_body = e.response.text[:500]
                logger.warning(f"POST {url} failed ({e.response.status_code}): {resp_body}")
                last_error = {
                    "status": e.response.status_code,
                    "detail": f"HTTP {e.response.status_code} on {url}: {resp_body}",
                    "endpoint_tried": url,
                }
                continue
            except httpx.RequestError as e:
                logger.warning(f"Network error on {url}: {e}")
                last_error = {"error": True, "detail": str(e), "endpoint_tried": url}
                continue
            except Exception as e:
                logger.warning(f"Unexpected error on {url}: {e}")
                last_error = {"error": True, "detail": str(e), "endpoint_tried": url}
                continue

        logger.error(
            f"All start-mirror endpoints failed for {username}. "
            f"Last error: {last_error}"
        )
        return {
            "error": True,
            "detail": (
                f"Cannot start copy of {username}: mirror creation endpoint "
                f"not available on retail/demo API plan. "
                f"Use the eToro UI to start copying manually. "
                f"Last attempt: {last_error.get('endpoint_tried', 'unknown')} "
                f"→ {last_error.get('detail', 'unknown')}"
            ),
            "attempts": len(urls_to_try),
            "last_error": last_error,
        }

    @staticmethod
    def _get_browser_headers() -> Dict[str, str]:
        """Return browser-like headers for public endpoints that block httpx."""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.etoro.com/",
            "Origin": "https://www.etoro.com",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    def _empty_metrics(self, username: str) -> Dict:
        """Return default metrics structure for a trader with no data."""
        return {
            "username": username,
            "avg_return": None,
            "risk_score": None,
            "max_drawdown": None,
            "volatility": None,
            "total_return_pct": None,
            "available": False,
            "source": "none",
            "confidence": 0.0,
            "is_copyable": True,
            "min_copy_amount": None,
            "copiers": None,
            "positions_count": None,
            "peak_to_valley": None,
            "profitable_months_pct": None,
            "win_ratio": None,
            "trades_count": None,
            "weeks_since_registration": None,
            "missing_fields": [],
        }

    async def _api_get_with_retry(
        self,
        url: str,
        params: Optional[Dict] = None,
        timeout: float = 15.0,
        browser_headers: bool = False,
    ) -> Optional[Dict]:
        """GET with 3-retry exponential backoff, jitter, and adaptive rate limiting.

        Args:
            url: Target URL.
            params: Optional query parameters.
            timeout: Request timeout in seconds.
            browser_headers: If True, use browser-like headers instead of API auth headers.
                             Use this for public/unauthenticated endpoints.

        Returns parsed JSON on 200, None on non-retryable errors.
        Retries 429 and 5xx with jittered exponential backoff.
        Rate limit degradation auto-recovers after 10 seconds.
        All outbound requests go through a semaphore (max 5 concurrent).
        """
        import asyncio
        import random
        import time
        if not hasattr(self, "_api_sem"):
            self._api_sem = asyncio.Semaphore(5)
            self._rate_limit_hits = 0
            self._rate_limit_reset_time = 0.0
        # Auto-recover rate limit state after 10 seconds
        if self._rate_limit_hits >= 10 and time.time() - self._rate_limit_reset_time > 10:
            logger.info("Rate limit state reset after 10s cooldown")
            self._rate_limit_hits = 0
        for attempt in range(1, 4):
            try:
                async with self._api_sem:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        headers = self._get_browser_headers() if browser_headers else self._get_headers()
                        response = await client.get(url, params=params, headers=headers)
                body_snippet = response.text[:500] if response.text else "(empty body)"

                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.debug("GET %s → 200 OK (%d bytes, %d keys)",
                                     url, len(response.text), len(data) if isinstance(data, dict) else 0)
                        return data
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.error("GET %s → 200 OK BUT INVALID JSON: %s | body=%s",
                                      url, e, body_snippet)
                        return None

                if response.status_code == 204:
                    logger.info("GET %s → 204 No Content (user has no trade data for this period)", url)
                    return None

                if response.status_code == 401:
                    logger.error("GET %s → 401 Unauthorized — check ETORO_API_KEY / ETORO_API_SECRET credentials", url)
                    return None

                if response.status_code == 403:
                    logger.error("GET %s → 403 Forbidden — API key lacks access to this endpoint", url)
                    return None

                if response.status_code == 404:
                    logger.info("GET %s → 404 Not Found (user or endpoint does not exist)", url)
                    return None

                if response.status_code == 429:
                    self._rate_limit_hits += 1
                    if self._rate_limit_hits >= 10:
                        logger.error("GET %s → 10+ rate limits hit — cooling down for 10s", url)
                        return None
                    # Longer backoff for 429s to actually give the API time to recover
                    backoff = 5.0 + random.uniform(0, 2)
                    logger.warning("GET %s → 429 Rate Limited, retry %d/3 after %.1fs (hit #%d)",
                                   url, attempt, backoff, self._rate_limit_hits)
                    await asyncio.sleep(backoff)
                    if attempt < 3:
                        continue
                    logger.error("GET %s → 429 Rate Limited, exhausted all 3 retries (%d total hits)",
                                  url, self._rate_limit_hits)
                    return None

                if 500 <= response.status_code < 600:
                    if attempt < 3:
                        backoff = 2 ** attempt
                        logger.warning("GET %s → %d Server Error, retry %d/3 after %ds | body=%s",
                                       url, response.status_code, attempt, backoff, body_snippet)
                        await asyncio.sleep(backoff)
                        continue
                    logger.error("GET %s → %d Server Error, exhausted all 3 retries | body=%s",
                                  url, response.status_code, body_snippet)
                    return None

                # Any other status (300, 400 without 401/403/404, etc.)
                logger.warning("GET %s → %d (unhandled status) | body=%s",
                               url, response.status_code, body_snippet)
                return None

            except httpx.TimeoutException:
                if attempt < 3:
                    backoff = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("GET %s → Timeout (attempt %d/3), retrying after %.1fs",
                                   url, attempt, backoff)
                    await asyncio.sleep(backoff)
                    continue
                logger.error("GET %s → Timeout after 3 retries", url)
                return None
            except httpx.RequestError as e:
                if attempt < 3:
                    backoff = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("GET %s → RequestError (attempt %d/3, retry %.1fs): %s", url, attempt, backoff, e)
                    await asyncio.sleep(backoff)
                    continue
                logger.error("GET %s → RequestError after 3 retries: %s", url, e)
                return None
            except Exception as e:
                logger.error("GET %s → Unexpected error: %s", url, e)
                return None
        return None

    async def get_trader_metrics(self, username: str) -> Dict:
        """Resilient multi-endpoint trader metrics fetcher.

        Strategy:
          1. Primary: GET /api/v1/user-info/people/{username}/tradeinfo?period=LastTwoYears
          2. Fallback A: GET /api/v1/user-info/people/{username}/portfolio/live
          3. Fallback B: GET /api/v1/user-info/people/{username}/gain?period=LastTwoYears
          4. Fallback C: GET /api/v1/user-info/people/{username}/daily-gain

        Returns normalized dict with available=True if ANY endpoint succeeded.
        Never raises — always returns the normalized structure.
        """
        base = self.BASE_URL
        result = self._empty_metrics(username)

        # Step 1: Primary tradeinfo endpoint (v1 as documented by eToro)
        tradeinfo = await self._api_get_with_retry(
            f"{base}/api/v1/user-info/people/{username}/tradeinfo",
            params={"period": "LastTwoYears"},
        )
        if tradeinfo:
            # Log raw response keys for debugging
            resp_keys = list(tradeinfo.keys()) if isinstance(tradeinfo, dict) else []
            logger.debug("Tradeinfo raw keys for %s: %s", username, resp_keys)

            # Extract copyability info if available in the response
            is_copyable = tradeinfo.get("IsCopyable", tradeinfo.get("isCopyable"))
            if is_copyable is None:
                logger.debug(f"No copyability info in tradeinfo for {username} — assuming copyable")
                is_copyable = True
            else:
                logger.debug("Tradeinfo %s: isCopyable=%s", username, is_copyable)

            min_copy_raw = tradeinfo.get("MinimumInvestment", tradeinfo.get("minCopyAmount"))
            min_copy = float(min_copy_raw) if min_copy_raw is not None else None
            copiers_raw = tradeinfo.get("Copiers", tradeinfo.get("numOfCopiers"))
            positions_raw = tradeinfo.get("NumberOfOpenPositions", tradeinfo.get("numOfOpenPositions"))

            gain_raw = tradeinfo.get("gainPerc") or tradeinfo.get("gain")
            risk_raw = tradeinfo.get("riskScore")
            dd_raw = tradeinfo.get("maxMonthlyDrawdown")
            vol_raw = tradeinfo.get("volatility")
            avg_raw = tradeinfo.get("avgReturn")

            # Advanced metrics for professional analysis
            peak_raw = tradeinfo.get("peakToValley")
            prof_months_raw = tradeinfo.get("profitableMonthsPct")
            win_raw = tradeinfo.get("winRatio")
            trades_raw = tradeinfo.get("trades")
            weeks_raw = tradeinfo.get("weeksSinceRegistration")

            logger.debug(
                "Tradeinfo extracted for %s: gainPerc=%s riskScore=%s "
                "maxMonthlyDrawdown=%s volatility=%s avgReturn=%s "
                "Copiers=%s NumberOfOpenPositions=%s MinInvestment=%s "
                "peakToValley=%s profitableMonthsPct=%s winRatio=%s",
                username, gain_raw, risk_raw, dd_raw, vol_raw,
                avg_raw, copiers_raw, positions_raw, min_copy,
                peak_raw, prof_months_raw, win_raw,
            )

            missing_fields = []
            if risk_raw is None or risk_raw == 0:
                missing_fields.append("riskScore")
            if dd_raw is None:
                missing_fields.append("maxMonthlyDrawdown")
            if vol_raw is None:
                missing_fields.append("volatility")
            if avg_raw is None:
                missing_fields.append("avgReturn")
            if gain_raw is None:
                missing_fields.append("gainPerc")
            if min_copy_raw is None:
                missing_fields.append("minCopyAmount")
            if copiers_raw is None:
                missing_fields.append("copiers")
            if peak_raw is None:
                missing_fields.append("peakToValley")
            if prof_months_raw is None:
                missing_fields.append("profitableMonthsPct")
            if win_raw is None:
                missing_fields.append("winRatio")

            # Check for AUC/AUM fields in tradeinfo response (signals capacity limits)
            auc_value = None
            for auc_field in (
                "TotalAssetsUnderCopy", "totalAssetsUnderCopy",
                "AUM", "aum", "AUC", "auc",
                "assetsUnderCopy", "AssetsUnderCopy",
                "totalPositionSize", "TotalPositionSize",
            ):
                v = tradeinfo.get(auc_field)
                if v is not None:
                    try:
                        auc_value = float(v)
                        # is_copyable = False when AUC is very high (heuristic: >1M)
                        if auc_value > 1_000_000:
                            is_copyable = False
                        break
                    except (ValueError, TypeError):
                        continue

            result.update({
                "avg_return": float(avg_raw) if avg_raw is not None else None,
                "risk_score": float(risk_raw) if risk_raw is not None and risk_raw != 0 else None,
                "max_drawdown": float(dd_raw) if dd_raw is not None else None,
                "volatility": float(vol_raw) if vol_raw is not None else None,
                "total_return_pct": float(gain_raw) if gain_raw is not None else None,
                "is_copyable": bool(is_copyable),
                "min_copy_amount": min_copy,
                "available": True,
                "source": "tradeinfo",
                "confidence": 1.0,
                "copiers": int(copiers_raw) if copiers_raw is not None else None,
                "positions_count": int(positions_raw) if positions_raw is not None else None,
                "peak_to_valley": float(peak_raw) if peak_raw is not None else None,
                "profitable_months_pct": float(prof_months_raw) if prof_months_raw is not None else None,
                "win_ratio": float(win_raw) if win_raw is not None else None,
                "trades_count": int(trades_raw) if trades_raw is not None else None,
                "weeks_since_registration": int(weeks_raw) if weeks_raw is not None else None,
                "assets_under_copy": auc_value,
                "missing_fields": missing_fields,
            })
            logger.info(
                "Tradeinfo for %s: return=%s risk=%s copiers=%s positions=%s",
                username,
                safe_fmt(result["total_return_pct"], suffix="%"),
                safe_fmt(result["risk_score"]),
                result["copiers"] if result["copiers"] is not None else "missing",
                result["positions_count"] if result["positions_count"] is not None else "missing",
            )
            return result

        logger.info("Tradeinfo unavailable for %s, trying fallback endpoints", username)

        # Step 2: Fallback A — portfolio/live
        live = await self._api_get_with_retry(
            f"{base}/api/v1/user-info/people/{username}/portfolio/live",
        )
        if live:
            missing_fields = []
            ret_raw = live.get("totalReturn") or live.get("return")
            risk_raw = live.get("riskScore")
            dd_raw = live.get("maxDrawdown")
            vol_raw = live.get("volatility")
            avg_raw = live.get("avgReturn") or live.get("averageReturn")
            if ret_raw is None: missing_fields.append("totalReturn")
            if risk_raw is None or risk_raw == 0: missing_fields.append("riskScore")
            if dd_raw is None: missing_fields.append("maxDrawdown")
            if vol_raw is None: missing_fields.append("volatility")
            if avg_raw is None: missing_fields.append("avgReturn")
            result.update({
                "total_return_pct": float(ret_raw) if ret_raw is not None else None,
                "risk_score": float(risk_raw) if risk_raw is not None and risk_raw != 0 else None,
                "max_drawdown": float(dd_raw) if dd_raw is not None else None,
                "volatility": float(vol_raw) if vol_raw is not None else None,
                "avg_return": float(avg_raw) if avg_raw is not None else None,
                "available": True,
                "source": "portfolio_live",
                "confidence": 0.7,
                "missing_fields": missing_fields,
            })
            logger.info(
                "Fallback portfolio/live for %s: return=%s risk=%s",
                username,
                safe_fmt(result["total_return_pct"], suffix="%"),
                safe_fmt(result["risk_score"]),
            )
            return result

        # Step 3: Fallback B — gain
        gain = await self._api_get_with_retry(
            f"{base}/api/v1/user-info/people/{username}/gain",
            params={"period": "LastTwoYears"},
        )
        if gain:
            missing_fields = []
            ret_raw = gain.get("gain") or gain.get("gainPerc")
            if ret_raw is None: missing_fields.append("gain")
            result.update({
                "total_return_pct": float(ret_raw) if ret_raw is not None else None,
                "available": True,
                "source": "gain",
                "confidence": 0.5,
                "missing_fields": missing_fields,
            })
            logger.info(f"Tradeinfo unavailable for {username}, using gain endpoint")
            return result

        # Step 4: Fallback C — daily-gain
        daily = await self._api_get_with_retry(
            f"{base}/api/v1/user-info/people/{username}/daily-gain",
        )
        if daily:
            missing_fields = []
            ret_raw = daily.get("gain") or daily.get("dailyGain")
            if ret_raw is None: missing_fields.append("gain")
            result.update({
                "total_return_pct": float(ret_raw) if ret_raw is not None else None,
                "available": True,
                "source": "daily_gain",
                "confidence": 0.3,
                "missing_fields": missing_fields,
            })
            logger.info(
                "Fallback daily-gain for %s: return=%s",
                username,
                safe_fmt(result["total_return_pct"], suffix="%"),
            )
            return result

        # All endpoints failed
        logger.warning(
            "%s unavailable across all 4 endpoints (tradeinfo, portfolio/live, gain, daily-gain)",
            username,
        )
        return result

    async def get_trader_extended_metrics(self, username: str) -> Dict:
        """Fetch extended trader metrics across multiple periods and sources.

        Returns the base metrics from get_trader_metrics plus:
          - return_3yr:     3-year return (tradeinfo LastThreeYears)
          - return_ytd:     Year-to-date return (tradeinfo YearToDate)
          - holdings:       List of current holding symbols (from portfolio/live)
          - assets_under_copy:  Total AUM from tradeinfo
          - track_record_days:  Estimated track record length

        Never raises — always returns a dict with all keys present.
        """
        base = await self.get_trader_metrics(username)

        import asyncio

        async def fetch_period(period: str) -> Optional[Dict]:
            return await self._api_get_with_retry(
                f"{self.BASE_URL}/api/v1/user-info/people/{username}/tradeinfo",
                params={"period": period},
            )

        # Fetch 3yr and YTD in parallel
        t3, ytd, live = await asyncio.gather(
            fetch_period("LastThreeYears"),
            fetch_period("YearToDate"),
            self._api_get_with_retry(
                f"{self.BASE_URL}/api/v1/user-info/people/{username}/portfolio/live",
            ),
            return_exceptions=True,
        )

        extended = {
            "return_3yr": None,
            "return_ytd": None,
            "holdings": [],
            "assets_under_copy": None,
            "track_record_days": None,
        }

        # Extract 3yr return
        if isinstance(t3, dict) and t3:
            extended["return_3yr"] = float(
                t3.get("gainPerc") or t3.get("gain") or 0.0
            )

        # Extract YTD return
        if isinstance(ytd, dict) and ytd:
            extended["return_ytd"] = float(
                ytd.get("gainPerc") or ytd.get("gain") or 0.0
            )

        # Extract assets under copy from either tradeinfo response
        for response in [t3, ytd]:
            if isinstance(response, dict):
                for auc_field in (
                    "TotalAssetsUnderCopy", "totalAssetsUnderCopy",
                    "AUM", "aum", "TotalAssets", "totalAssets",
                    "totalPositionSize", "TotalPositionSize",
                ):
                    v = response.get(auc_field)
                    if v is not None:
                        try:
                            extended["assets_under_copy"] = float(v)
                            break
                        except (ValueError, TypeError):
                            continue

        # Extract holdings from live portfolio
        if isinstance(live, dict) and live:
            positions = live.get("positions", live.get("Positions", []))
            if isinstance(positions, list):
                symbols = []
                for pos in positions:
                    sym = (pos.get("symbol") or pos.get("instrument")
                           or pos.get("Symbol") or pos.get("Instrument") or pos.get("name"))
                    if sym and isinstance(sym, str) and sym.strip():
                        symbols.append(sym.strip())
                extended["holdings"] = symbols

        # Estimate track record from base data
        copiers = base.get("copiers")
        positions_count = base.get("positions_count")
        if copiers is not None and positions_count is not None:
            extended["track_record_days"] = max(365, min(365 * 5, copiers * 2))

        r3_str = f"{extended['return_3yr']:.1f}%" if extended['return_3yr'] is not None else "N/A"
        ytd_str = f"{extended['return_ytd']:.1f}%" if extended['return_ytd'] is not None else "N/A"
        logger.info(
            "Extended metrics for %s: 3yr=%s, YTD=%s, "
            "holdings=%d, auc=%s",
            username, r3_str, ytd_str,
            len(extended["holdings"]),
            extended["assets_under_copy"] or "N/A",
        )
        return {**base, **extended}

    @staticmethod
    def _is_fake_username(username: str) -> bool:
        """Detect fake/placeholder usernames that are NOT real eToro profiles.

        Real eToro usernames follow patterns like:
          - Real names: JeppeKirkBonde, OlivierDanvel, AndreiCup
          - Handles: booker03, Jaynemesis, NiCKeLiT, PatStocks
          - Brand-like: ConsistentCapital, AlphaPulse, SmartMoneyFX

        Fake usernames look like strategy descriptions:
          - Category names: LowVolatility, DividendHunter, GlobalPortfolio
          - Strategy/type names: GrowthPath, BalancedApproach, ConservativeEdge
          - Placeholder patterns: "XxxPro", "XxxTrader", "XxxFund" with descriptive prefixes

        This list of KNOWN FAKE names acts as a hard deny list.
        """
        KNOWN_FAKE = {
            "LowVolatility", "DividendHunter", "GlobalPortfolio", "DividendGrowth",
            "StableReturns", "CapitalPreserve", "WealthBalanced", "SafeHaven",
            "CapitalShield", "TradeBalanced", "ModerateGrowth", "SteadyReturns",
            "CapitalProtect", "RiskAversePro", "MomentumTrader", "HighReturnPro",
            "AggressiveAlpha", "TurboReturns", "RapidGrowth", "AlphaSeeker",
            "MomentumKing", "BreakoutTrader", "TrendFollowerPro", "VolatilityTrader",
            "PowerGrowth", "ETFInvestorPro", "IndexTracker", "PassiveIncomeETF",
            "GlobalETF", "SectorETF", "ETFAllWeather", "IndexFundPro", "MarketETF",
            "BondETF", "SmartBetaPro", "DividendKing", "IncomeStream", "YieldFocus",
            "PassiveDividend", "DividendGrower", "IncomeFocus", "DividendAristocrat",
            "CashFlowPro", "PayoutTrader", "TechInvestorPro", "InnovationTrader",
            "TechGrowth", "DigitalAssets", "TechTrends", "AIInvestor", "CloudCapital",
            "CyberSecure", "SemiConductorPro", "SoftwareGrowth", "CryptoModerate",
            "DigitalBalance", "BlockchainSmart", "CryptoSavvy", "CryptoGrowth",
            "CryptoCore", "BlockchainValue", "CryptoStable", "DigitalAssetPro",
            "Web3Investor", "MultiAssetPro", "WorldWideInvest", "SectorDiversified",
            "AllWeatherTrader", "GlobalMarketsPro", "CrossAssetTrader", "MacroTrader",
            "GlobalMacroPro", "MultiMarketTrader", "ConservativeEdge", "BalancedApproach",
            "ModerateRiskPro", "GrowthPath", "AggressiveStrat", "ValueHunter",
            "QualityGrowth", "IncomePlus", "CapitalEfficiency", "RiskOptimizer",
            "TrendQuality", "MomentumValue", "SizeMatters", "LowBetaPro",
            "HighBetaTrader", "QualityFactor",
        }
        return username in KNOWN_FAKE

    async def enrich_candidates(
        self, usernames: List[str], max_concurrent: int = 10,
    ) -> Dict:
        """Enrich a list of usernames via tradeinfo API with concurrency limit.

        Args:
            usernames: List of eToro usernames to enrich.
            max_concurrent: Maximum concurrent API calls (default 10).

        Returns:
            Dict with available, unavailable, scanned, valid_count, rejected.
        """
        if not usernames:
            return {"available": [], "unavailable": [], "scanned": 0, "valid_count": 0, "rejected": 0}

        import asyncio
        sem = asyncio.Semaphore(max_concurrent)

        fake_count = 0
        for u in usernames:
            if self._is_fake_username(u):
                fake_count += 1

        if fake_count:
            logger.warning(
                "Enrichment: %d/%d usernames are known fake/placeholder names — removing",
                fake_count, len(usernames),
            )

        usernames = [u for u in usernames if not self._is_fake_username(u)]

        if not usernames:
            return {"available": [], "unavailable": [], "scanned": 0, "valid_count": 0, "rejected": 0}

        async def _fetch(username: str) -> tuple:
            async with sem:
                metrics = await self.get_trader_metrics(username)
                return username, metrics

        logger.info(f"Enriching {len(usernames)} candidates (concurrency={max_concurrent})")

        results = await asyncio.gather(*[_fetch(u) for u in usernames], return_exceptions=True)

        available = []
        unavailable = []

        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Enrichment error: {r}")
                continue
            username, metrics = r

            if self._is_fake_username(username):
                unavailable.append({
                    "username": username,
                    "reason": "fake_username",
                    "detail": f"Username '{username}' matches known fake/placeholder patterns",
                })
                continue

            if metrics["available"]:
                is_copyable = metrics.get("is_copyable", True)
                min_copy = metrics.get("min_copy_amount")

                if metrics.get("total_return_pct") is None and metrics.get("confidence", 0.0) < 1.0:
                    unavailable.append({
                        "username": username,
                        "reason": "no_return_data",
                        "detail": (
                            f"source={metrics['source']} returned None return "
                            f"(confidence={metrics.get('confidence', 0.0)})"
                        ),
                    })
                    continue

                if not is_copyable:
                    unavailable.append({
                        "username": username,
                        "reason": "not_copyable",
                        "detail": f"is_copyable={is_copyable}",
                    })
                    continue

                available.append({
                    "username": username,
                    "risk_score": metrics.get("risk_score"),
                    "total_return_pct": metrics.get("total_return_pct"),
                    "max_drawdown": metrics.get("max_drawdown"),
                    "volatility": metrics.get("volatility"),
                    "avg_return": metrics.get("avg_return"),
                    "avg_monthly_return": metrics.get("avg_return"),
                    "copiers": metrics.get("copiers"),
                    "positions_count": metrics.get("positions_count"),
                    "is_copiable": is_copyable,
                    "min_copy_amount": min_copy,
                    "available": metrics.get("available", True),
                    "confidence": metrics.get("confidence", 0.0),
                    "source": metrics.get("source", "unknown"),
                    "missing_fields": metrics.get("missing_fields", []),
                    "peak_to_valley": metrics.get("peak_to_valley"),
                    "profitable_months_pct": metrics.get("profitable_months_pct"),
                    "win_ratio": metrics.get("win_ratio"),
                    "trades_count": metrics.get("trades_count"),
                    "weeks_since_registration": metrics.get("weeks_since_registration"),
                    "assets_under_copy": metrics.get("assets_under_copy"),
                })
            else:
                unavailable.append({"username": username, "reason": "all_endpoints_failed"})

        result = {
            "available": available,
            "unavailable": unavailable,
            "scanned": len(usernames),
            "valid_count": len(available),
            "rejected": len(unavailable),
        }

        logger.info(
            f"Enrichment: {len(available)} valid / {len(unavailable)} rejected "
            f"(total {len(usernames)} scanned)"
        )
        return result

    async def discover_via_search(self, target: int = 300) -> List[str]:
        """Discover traders via the working search/people API endpoint.

        Uses GET /api/v1/user-info/people/search with pagination to fetch
        real eToro traders dynamically. Returns deduplicated usernames.

        Args:
            target: Target number of traders to fetch (via pagination).

        Returns:
            Deduplicated list of eToro usernames. Empty if API fails.
        """
        discovered: List[str] = []
        page_size = 50
        pages_needed = (target // page_size) + 1

        import asyncio

        for page in range(1, pages_needed + 1):
            url = (
                f"{self.BASE_URL}/api/v1/user-info/people/search"
                f"?period=CurrYear&page={page}&pageSize={page_size}"
            )
            try:
                data = await self._api_get_with_retry(url, timeout=15.0, browser_headers=False)
                if data is None:
                    logger.info("Discovery search: page %d returned no data — stopping", page)
                    break
                items = data.get("items", []) if isinstance(data, dict) else []
                page_usernames = []
                page_blocked = 0
                for item in items:
                    if isinstance(item, dict):
                        uname = item.get("userName")
                        if not uname or not isinstance(uname, str) or not uname.strip():
                            continue
                        is_copyable = item.get("IsCopyable", item.get("isCopyable"))
                        if is_copyable is False:
                            page_blocked += 1
                            continue
                        page_usernames.append(uname.strip())
                discovered.extend(page_usernames)
                logger.info(
                    "Discovery search: page %d returned %d usernames "
                    "(%d blocked, total: %d)",
                    page, len(page_usernames), page_blocked, len(discovered),
                )
                if len(page_usernames) < page_size:
                    logger.info("Discovery search: last page reached at page %d", page)
                    break
            except Exception as e:
                logger.warning("Discovery search: page %d error: %s", page, e)
                break

        unique = list(dict.fromkeys(discovered))
        fake_usernames = [u for u in unique if self._is_fake_username(u)]

        logger.info(
            "Discovery search complete: %d raw, %d unique, %d fake filtered",
            len(discovered), len(unique), len(fake_usernames),
        )

        return [u for u in unique if not self._is_fake_username(u)]

    async def discover_bulk(self, target: int = 10000, max_concurrent: int = 10) -> List[Dict]:
        """Mass discovery with concurrent pagination and lightweight metadata.

        Fetches up to `target` traders from the eToro search API using
        parallel page requests. Extracts lightweight metadata from each
        result (risk, gain, copiers, weeks, country) for Stage 1 filtering.

        Returns list of lightweight candidate dicts (no tradeinfo data).
        """
        import asyncio
        page_size = 50
        pages_needed = (target // page_size) + 1
        discovered: Dict[str, Dict] = {}

        async def _fetch_page(page: int) -> List[Dict]:
            url = (
                f"{self.BASE_URL}/api/v1/user-info/people/search"
                f"?period=CurrYear&page={page}&pageSize={page_size}"
            )
            try:
                data = await self._api_get_with_retry(url, timeout=15.0, browser_headers=False)
                if data is None:
                    return []
                items = data.get("items", []) if isinstance(data, dict) else []
                page_results = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    uname = item.get("userName")
                    if not uname or not isinstance(uname, str) or not uname.strip():
                        continue
                    is_copyable = item.get("IsCopyable", item.get("isCopyable"))
                    if is_copyable is False:
                        continue
                    page_results.append({
                        "username": uname.strip(),
                        "risk_score": item.get("RiskScore", item.get("riskScore")),
                        "total_return_pct": item.get("GainPercentage", item.get("gainPerc")),
                        "copiers": item.get("Copiers", item.get("copiers", item.get("NumberOfCopiers"))),
                        "weeks_since_registration": item.get("WeeksSinceRegistration", item.get("weeks")),
                        "country": item.get("Country", item.get("country")),
                        "is_copyable": True,
                        "source": "search_api",
                        "confidence": 0.5,
                        "available": True,
                    })
                return page_results
            except Exception as e:
                logger.warning("Bulk discovery page %d error: %s", page, e)
                return []

        sem = asyncio.Semaphore(max_concurrent)

        async def _fetch_page_throttled(page: int) -> None:
            async with sem:
                results = await _fetch_page(page)
                for r in results:
                    discovered[r["username"]] = r

        # Fetch pages in concurrent batches
        batch_size = max_concurrent * 2
        for start in range(1, pages_needed + 1, batch_size):
            batch = range(start, min(start + batch_size, pages_needed + 1))
            await asyncio.gather(*[_fetch_page_throttled(p) for p in batch])
            if len(discovered) >= target * 1.5:
                logger.info("Bulk discovery: reached %d candidates — stopping", len(discovered))
                break

        # Filter fake usernames and limit
        all_candidates = [v for k, v in discovered.items() if not self._is_fake_username(k)]
        limited = all_candidates[:target]

        logger.info(
            "Bulk discovery complete: %d raw, %d unique, %d after filter, returning %d",
            pages_needed * page_size, len(discovered), len(all_candidates), len(limited),
        )
        return limited

    def _get_mock_account_summary(self) -> Dict:
        import random
        base_value = 15000 + random.uniform(-2000, 3000)
        return {
            "equity": round(base_value, 2),
            "available_cash": round(base_value * 0.15, 2),
            "invested": round(base_value * 0.85, 2),
            "unrealized_pnl": round(random.uniform(-500, 800), 2),
            "realized_pnl": round(random.uniform(200, 1500), 2),
            "daily_pnl": round(random.uniform(-100, 150), 2),
            "weekly_pnl": round(random.uniform(-300, 400), 2),
            "monthly_pnl": round(random.uniform(-800, 1200), 2),
        }

    def _get_mock_portfolio_data(self) -> Dict:
        return {"instruments": ["AAPL", "TSLA", "NVDA", "MSFT"], "allocations": [0.25, 0.20, 0.15, 0.40]}

    def _get_mock_positions(self) -> List[Dict]:
        return [
            {"instrument": "AAPL", "quantity": 50, "avg_price": 180.50, "current_price": 185.20},
            {"instrument": "TSLA", "quantity": 25, "avg_price": 220.00, "current_price": 235.80},
            {"instrument": "NVDA", "quantity": 15, "avg_price": 450.00, "current_price": 475.60},
        ]

    def _get_mock_traders(self) -> List[Dict]:
        return [
            {"trader_id": "et_001", "username": "AlphaTrader_99", "allocation_pct": 35.0, "avg_return": 2.1, "max_drawdown": 12.5, "volatility": 18.3, "risk_score": 3.2},
            {"trader_id": "et_002", "username": "GrowthSeeker", "allocation_pct": 25.0, "avg_return": 1.8, "max_drawdown": 15.2, "volatility": 22.1, "risk_score": 4.1},
            {"trader_id": "et_003", "username": "CryptoKing2024", "allocation_pct": 20.0, "avg_return": 3.5, "max_drawdown": 28.7, "volatility": 35.2, "risk_score": 6.8},
            {"trader_id": "et_004", "username": "DividendFocus", "allocation_pct": 20.0, "avg_return": 1.2, "max_drawdown": 8.9, "volatility": 12.4, "risk_score": 2.5},
        ]


class EToroSyncService:
    """
    Syncs eToro account data with local database.
    Pulls real-time portfolio metrics and trader information.
    """

    def __init__(self):
        self.client = EToroAPIClient()

    async def sync_portfolio_data(self, db, portfolio_id: int) -> bool:
        """
        Sync portfolio with real eToro data.
        Falls back to simulation data when API is unavailable.
        """
        from backend.database.models import Portfolio, CopiedTrader, PortfolioSnapshot

        try:
            portfolio = db.query(Portfolio).filter(
                Portfolio.id == portfolio_id
            ).first()

            if not portfolio:
                logger.error(f"Portfolio {portfolio_id} not found")
                return False

            # Production: real API only, no mock fallback
            if not self.client.enabled:
                logger.error("eToro API not configured — sync aborted")
                return False

            raw = await self.client.get_portfolio_data()
            if not raw:
                logger.error("eToro API returned no data — sync aborted")
                return False

            summary = self._extract_summary(raw)
            total_equity = summary.get("equity", 0.0)
            traders = self._extract_traders(raw, total_equity)
            logger.info("Synced live data from eToro API")
            logger.info(f"RAW clientPortfolio: equity={raw.get('clientPortfolio', {}).get('equity')}, "
                        f"credit={raw.get('clientPortfolio', {}).get('credit')}, "
                        f"accountCurrencyId={raw.get('clientPortfolio', {}).get('accountCurrencyId')}, "
                        f"mirrors={len(raw.get('clientPortfolio', {}).get('mirrors', []))}")
            for m in raw.get("clientPortfolio", {}).get("mirrors", []):
                logger.info(f"MIRROR {m.get('mirrorId')}: user={m.get('parentUsername')}, "
                            f"initInvest={m.get('initialInvestment')}, "
                            f"available={m.get('availableAmount')}, "
                            f"closedPnL={m.get('closedPositionsNetProfit')}, "
                            f"positions={len(m.get('positions', []))}")
            logger.info(f"EXTRACTED summary: {summary}")
            logger.info(f"EXTRACTED traders: {traders}")

            portfolio.total_value = summary.get("equity", 0.0)
            portfolio.available_cash = summary.get("available_cash", 0.0)
            portfolio.invested_amount = summary.get("invested", 0.0)
            portfolio.unrealized_pnl = summary.get("unrealized_pnl", 0.0)
            portfolio.realized_pnl = summary.get("realized_pnl", 0.0)
            portfolio.currency = summary.get("currency", "USD")
            portfolio.last_updated = datetime.utcnow()
            db.commit()

            if traders:
                self._sync_traders(db, portfolio_id, traders, portfolio.total_value)

            # ── Validation: compare API equity field vs computed total ──
            etoro_api_total = None
            etoro_field = None
            for field in ("equity", "netValue", "NetValue", "totalValue", "TotalValue", "NetLiquidatingValue"):
                v = raw.get("clientPortfolio", {}).get(field)
                if v is not None and float(v) > 0:
                    etoro_api_total = float(v)
                    etoro_field = field
                    break

            app_total = float(portfolio.total_value or 0)
            if etoro_api_total is not None:
                diff = app_total - etoro_api_total
                diff_pct = (diff / etoro_api_total) * 100 if etoro_api_total else 0
                log_level = logger.warning if abs(diff_pct) > 1.0 else logger.info
                log_level(
                    f"VALUE CHECK: eToro({etoro_field})={etoro_api_total:.2f}, "
                    f"app={app_total:.2f}, diff={diff:.2f} ({diff_pct:+.4f}%)"
                )
            else:
                logger.info(f"VALUE CHECK: no API equity field found, using computed total={app_total:.2f}")

            snapshot = PortfolioSnapshot(
                portfolio_id=portfolio_id,
                total_value=portfolio.total_value,
                daily_pnl=portfolio.daily_pnl,
                health_score=portfolio.health_score,
                recorded_at=datetime.utcnow(),
            )
            db.add(snapshot)
            db.commit()
            return True

        except Exception as e:
            logger.error(f"Sync error: {e}")
            return False

    def _extract_summary(self, raw: Dict) -> Dict:
        """Parse eToro API portfolio response into flat summary dict.

        Total Value priority:
          1. Direct API equity field (try multiple field names)
          2. Sum of ACTIVE mirror current values + available_cash
             (mirror current value = initialInvestment + unrealizedPnL,
              NOT including closedPositionsNetProfit which is already
              paid out to the account)

        Never adds realized PnL to total_value — it is already reflected
        in the mirror current values and/or available cash.
        """
        cp = raw.get("clientPortfolio", {})
        positions = cp.get("positions", [])
        mirrors = cp.get("mirrors", [])

        # Invested = cost basis (initial investments in mirrors + direct stock positions)
        positions_invested = sum(p.get("amount", 0.0) for p in positions)
        mirrors_invested = sum(m.get("initialInvestment", 0.0) for m in mirrors)
        invested = positions_invested + mirrors_invested

        # Unrealized PnL from all open positions (direct + mirror)
        positions_pnl = sum(p.get("unrealizedPnL", {}).get("pnL", 0.0) for p in positions)
        mirrors_pnl = sum(
            pos.get("unrealizedPnL", {}).get("pnL", 0.0) for m in mirrors for pos in m.get("positions", [])
        )
        unrealized_pnl = positions_pnl + mirrors_pnl

        # Realized PnL = net profit from closed copy-trading positions
        realized_pnl = sum(m.get("closedPositionsNetProfit", 0.0) for m in mirrors)

        # Available cash = account-level credit only
        available_cash = cp.get("credit", 0.0)

        # ── Try multiple API equity field names ────────────────────────────
        api_equity = None
        equity_field = None
        for field in ("equity", "netValue", "NetValue", "totalValue", "TotalValue", "NetLiquidatingValue"):
            v = cp.get(field)
            if v is not None and float(v) > 0:
                api_equity = float(v)
                equity_field = field
                break

        if api_equity is not None:
            total_value = api_equity
            equity_source = f"api_{equity_field}"
        else:
            # Fallback: sum of mirror current values + direct positions + cash
            # Mirror current value = initialInvestment + unrealizedPnL only
            # (NOT including closedPositionsNetProfit — already paid out)
            sum_mirror_current = 0.0
            for m in mirrors:
                mirror_init = m.get("initialInvestment", 0.0)
                mirror_upnl = sum(
                    pos.get("unrealizedPnL", {}).get("pnL", 0.0)
                    for pos in m.get("positions", [])
                )
                sum_mirror_current += mirror_init + mirror_upnl

            # Direct positions current value = amount + unrealizedPnL
            sum_direct_current = 0.0
            for p in positions:
                sum_direct_current += p.get("amount", 0.0) + p.get("unrealizedPnL", {}).get("pnL", 0.0)

            total_value = sum_mirror_current + sum_direct_current + available_cash
            equity_source = "mirror_sum"

        currency = "EUR" if cp.get("accountCurrencyId") == 2 else "USD"

        # ── Validation: compare API equity vs computed total ──
        if api_equity is not None and api_equity > 0:
            diff = total_value - api_equity
            diff_pct = (diff / api_equity) * 100
            log_level = logger.warning if abs(diff_pct) > 5.0 else logger.info
            log_level(
                f"EQUITY CHECK: api_{equity_field}={api_equity:.2f}, "
                f"computed={total_value:.2f}, diff={diff:.2f} ({diff_pct:+.2f}%)"
            )
        else:
            logger.info(
                f"EQUITY CHECK: no API equity field found — using computed total={total_value:.2f}"
            )

        logger.info(
            f"  invested={invested}, unrealized_pnl={unrealized_pnl}, "
            f"realized_pnl={realized_pnl}, cash={available_cash}"
        )

        return {
            "equity": total_value,
            "available_cash": available_cash,
            "invested": invested,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "currency": currency,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "monthly_pnl": 0.0,
        }

    def _extract_traders(self, raw: Dict, total_value: float = 0.0) -> List[Dict]:
        """Extract copied trader info from mirrors array.

        Uses the provided total_value (from _extract_summary's equity) as
        the denominator for allocation_pct. If not provided, falls back
        to invested + unrealized_pnl + available_cash (no realized_pnl).

        Allocation % per user formula:
          (initialInvestment + unrealizedPnL) / Total Value * 100
        """
        cp = raw.get("clientPortfolio", {})
        mirrors = cp.get("mirrors", [])
        positions = cp.get("positions", [])

        if total_value <= 0:
            # Fallback: compute without realized_pnl to avoid double-count
            invested = sum(p.get("amount", 0.0) for p in positions) + sum(m.get("initialInvestment", 0.0) for m in mirrors)
            positions_pnl = sum(p.get("unrealizedPnL", {}).get("pnL", 0.0) for p in positions)
            mirrors_pnl = sum(
                pos.get("unrealizedPnL", {}).get("pnL", 0.0) for m in mirrors for pos in m.get("positions", [])
            )
            unrealized_pnl = positions_pnl + mirrors_pnl
            available_cash = cp.get("credit", 0.0)
            total_value = invested + unrealized_pnl + available_cash

        result = []
        for m in mirrors:
            unrealized_pnl_mirror = sum(pos.get("unrealizedPnL", {}).get("pnL", 0.0) for pos in m.get("positions", []))
            total_pnl = m.get("closedPositionsNetProfit", 0.0) + unrealized_pnl_mirror
            initial_investment = m.get("initialInvestment", 1.0)
            
            # Mirror equity = initialInvestment + unrealizedPnL (no closedPositionsNetProfit — already in cash)
            mirror_equity = initial_investment + unrealized_pnl_mirror
            
            import json
            # eToro API mirrorId key can vary by account type (retail vs non-retail).
            # Use a best-effort string key rather than integer — some plans don't
            # expose mirrorId at all, but we still want trader metrics for the scout.
            raw_id = (
                m.get("mirrorId")
                or m.get("mirrorID")
                or m.get("id")
                or m.get("Id")
                or 0
            )
            try:
                mirror_id = int(raw_id) if raw_id else 0
            except (ValueError, TypeError):
                mirror_id = 0

            username = m.get("parentUsername", "Unknown")

            # If mirror_id is 0, use a synthetic stable ID (username hash) for DB storage.
            # The trader will appear in the scout but execution commands will fail gracefully.
            if not mirror_id or mirror_id <= 0:
                logger.warning(
                    f"Mirror for {username}: no mirrorId in API response. "
                    f"Trader data will sync but execution commands (close/change) won't work."
                )
                mirror_id = abs(hash(username)) % (10 ** 8)  # synthetic stable 8-digit ID
            # allocated_amount = mirror equity (what's actually at stake for this trader)
            # Used by partial_profit_lock and reduce_on_drawdown to compute new amounts
            allocated_amount = mirror_equity

            result.append({
                "trader_id": str(mirror_id),
                "username": username,
                "allocation_pct": (mirror_equity / max(total_value, 1.0)) * 100,
                "allocated_amount": round(allocated_amount, 2),
                "avg_return": None,
                "max_drawdown": None,
                "volatility": None,
                "risk_score": None,
                "total_return_pct": (total_pnl / max(initial_investment, 1.0)) * 100,
            })
        logger.info(f"Extracted {len(result)} valid traders from {len(mirrors)} mirrors")
        return result

    def _sync_traders(self, db, portfolio_id: int, traders_data: List[Dict], total_equity: float):
        """Update or create copied trader records."""
        from backend.database.models import CopiedTrader

        # Normalize allocation percentages if they exceed 100%
        total_pct = sum(info.get("allocation_pct", 0.0) for info in traders_data)
        if total_pct > 100.0:
            scale = 100.0 / total_pct
            for info in traders_data:
                info["allocation_pct"] = info.get("allocation_pct", 0.0) * scale
            logger.warning(
                f"Allocation sum was {total_pct:.2f}% — "
                f"normalized by {scale:.4f}x to total 100%"
            )

        for info in traders_data:
            trader_id = info.get("trader_id")
            username = info.get("username")

            trader = db.query(CopiedTrader).filter(
                CopiedTrader.portfolio_id == portfolio_id,
                CopiedTrader.trader_id == trader_id,
            ).first()

            # Fallback: match by username if trader_id didn't match any existing record
            if not trader and username:
                trader = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio_id,
                    CopiedTrader.trader_username == username,
                ).first()
                if trader:
                    logger.info(f"Matched {username} by username — updating trader_id from {trader.trader_id} to {trader_id}")
                    trader.trader_id = trader_id

            if trader:
                trader.trader_username = info.get("username", trader.trader_username)
                trader.allocation_pct = info.get("allocation_pct", trader.allocation_pct)
                trader.allocated_amount = info.get("allocated_amount", trader.allocated_amount)
                # Only update DB fields that are not None (preserve existing values for missing API data)
                avg_r = info.get("avg_return")
                if avg_r is not None:
                    trader.avg_monthly_return = avg_r
                dd = info.get("max_drawdown")
                if dd is not None:
                    trader.max_drawdown = dd
                vol = info.get("volatility")
                if vol is not None:
                    trader.volatility = vol
                risk = info.get("risk_score")
                if risk is not None:
                    trader.risk_score = risk
                ret = info.get("total_return_pct")
                if ret is not None:
                    trader.total_return_pct = ret
                trader.is_active = True
                trader.is_paused = False
                trader.last_updated = datetime.utcnow()
            else:
                trader = CopiedTrader(
                    portfolio_id=portfolio_id,
                    trader_id=info.get("trader_id"),
                    trader_username=info.get("username", "Unknown"),
                    allocation_pct=info.get("allocation_pct", 0.0),
                    avg_monthly_return=info.get("avg_return") or 0.0,
                    max_drawdown=info.get("max_drawdown") or 0.0,
                    volatility=info.get("volatility") or 0.0,
                    risk_score=info.get("risk_score"),
                    total_return_pct=info.get("total_return_pct") or 0.0,
                    is_active=True,
                    is_paused=False,
                )
                db.add(trader)

        # Mark as inactive any trader in DB that's no longer in the API response
        api_usernames = {info.get("username") for info in traders_data if info.get("username")}
        if api_usernames:
            stale = (
                db.query(CopiedTrader)
                .filter(
                    CopiedTrader.portfolio_id == portfolio_id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.trader_username.isnot(None),
                    ~CopiedTrader.trader_username.in_(api_usernames),
                )
                .all()
            )
            for s in stale:
                s.is_active = False
                s.last_updated = datetime.utcnow()
            if stale:
                logger.info(
                    f"Marked {len(stale)} stale traders as inactive: "
                    f"{[s.trader_username for s in stale]}"
                )

        db.commit()
        logger.info(f"Synced {len(traders_data)} traders for portfolio {portfolio_id}")
