"""
eToro API Service
────────────────────────────────────────────────────────────────────
Handles real-time data synchronization with the official eToro API
at https://public-api.etoro.com.
"""

from __future__ import annotations
import os
import uuid
import logging
from typing import Dict, List, Optional
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)


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

        # ETORO_ENV overrides the environment segment in all API URLs.
        # Set to "demo" to force /demo/ paths even when portfolio.is_simulation=False.
        # This is needed when your API keys only have demo permissions.
        self.forced_env = os.getenv("ETORO_ENV", "").strip().lower()

        if not self.api_key or not self.user_key:
            logger.warning("eToro API credentials not configured")
            self.enabled = False
        else:
            self.enabled = True

    def _resolve_env(self, is_simulation: bool) -> str:
        """Return the environment segment for API URL paths.

        If ETORO_ENV is set (e.g. "demo"), it takes precedence over
        the portfolio's simulation flag. Otherwise falls back to
        ``"demo" if is_simulation else "real"``.
        """
        if self.forced_env in ("demo", "real"):
            return self.forced_env
        return "demo" if is_simulation else "real"

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

    async def get_portfolio_data(self, is_simulation: bool = True) -> Optional[Dict]:
        """
        Fetch portfolio + PnL + positions + mirrors in one call.
        Retries up to 3 times with 5-second backoff on failure.
        """
        if not self.enabled:
            return None

        env = self._resolve_env(is_simulation)
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

    async def execute_close_mirror(self, mirror_id: int, is_simulation: bool = True) -> Optional[Dict]:
        """Close a copy-trade mirror position on eToro.

        Uses the same auth headers (x-api-key, x-user-key, x-request-id)
        as the read endpoint. Demo/real selection matches the account type.

        eToro 2026 API: DELETE /api/v1/sub-portfolios/{id}
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "close_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot close"}

        env = self._resolve_env(is_simulation)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{self.BASE_URL}/api/v1/sub-portfolios/{mirror_id}",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                result = response.json() if response.text else {}
                logger.info(f"Closed mirror {mirror_id} on eToro ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"eToro close-mirror error {e.response.status_code}: {e.response.text}")
            return {"error": True, "status": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"Network error closing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error closing mirror {mirror_id}: {e}")
            return {"error": True, "detail": str(e)}

    async def execute_change_mirror_amount(self, mirror_id: int, new_amount: float, is_simulation: bool = True) -> Optional[Dict]:
        """Change the allocated amount of a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/change-amount
        Body: {"amount": <new_amount>}
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "change_mirror_amount"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot change amount"}

        env = self._resolve_env(is_simulation)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{mirror_id}/change-amount",
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

    async def execute_pause_mirror(self, mirror_id: int, is_simulation: bool = True) -> Optional[Dict]:
        """Pause a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/pause
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "pause_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot pause"}

        env = self._resolve_env(is_simulation)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{mirror_id}/pause",
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

    async def execute_unpause_mirror(self, mirror_id: int, is_simulation: bool = True) -> Optional[Dict]:
        """Unpause a copy-trade mirror on eToro.

        eToro API: POST /api/v1/trading/mirrors/{mirrorId}/unpause
        """
        if not self.enabled:
            return None

        if not self._validate_mirror_id(mirror_id, "unpause_mirror"):
            return {"error": True, "detail": f"Invalid mirror_id={mirror_id} — cannot unpause"}

        env = self._resolve_env(is_simulation)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors/{mirror_id}/unpause",
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

    async def execute_start_mirror(self, username: str, amount: float, is_simulation: bool = True) -> Dict:
        """Start copying a trader on eToro.

        eToro API: POST /api/v1/trading/mirrors
        Body: {"username": "<trader>", "amount": <usd>, "isDemo": <bool>}

        Falls back to a guided message in live mode if the endpoint
        is not available on the current plan.
        """
        if not self.enabled:
            return {"error": True, "detail": "eToro API not configured"}

        env = self._resolve_env(is_simulation)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/api/v1/trading/mirrors",
                    headers=self._get_headers(),
                    json={"username": username, "amount": amount, "isDemo": is_simulation},
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Started mirror for {username} on eToro ({env}): {result}")
                return result
        except httpx.HTTPStatusError as e:
            logger.error(f"eToro start-mirror error {e.response.status_code}: {e.response.text}")
            return {"error": True, "status": e.response.status_code, "detail": e.response.text}
        except httpx.RequestError as e:
            logger.error(f"Network error starting mirror for {username}: {e}")
            return {"error": True, "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error starting mirror for {username}: {e}")
            return {"error": True, "detail": str(e)}

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

            raw = await self.client.get_portfolio_data(
                is_simulation=portfolio.is_simulation
            )
            if not raw:
                logger.error("eToro API returned no data — sync aborted")
                return False

            summary = self._extract_summary(raw)
            traders = self._extract_traders(raw)
            logger.info("Synced live data from eToro API")
            logger.info(f"RAW clientPortfolio: credit={raw.get('clientPortfolio', {}).get('credit')}, "
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
        
        Formula (per user): Total Value = Invested + Realized PnL + Unrealized PnL + credit
        - Invested       = sum of all initialInvestment (mirrors) + positions amount
        - Realized PnL   = sum of closedPositionsNetProfit (mirrors)
        - Unrealized PnL = sum of unrealizedPnL.pnL (all positions)
        - credit         = account-level available cash
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

        # Total Value per user's formula
        total_value = invested + realized_pnl + unrealized_pnl + available_cash

        currency = "EUR" if cp.get("accountCurrencyId") == 2 else "USD"

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

    def _extract_traders(self, raw: Dict) -> List[Dict]:
        """Extract copied trader info from mirrors array.
        
        Allocation % per user formula:
          (initialInvestment + closedPositionsNetProfit + unrealizedPnL) / Total Value * 100
        
        Where Total Value = Invested + Realized PnL + Unrealized PnL + credit
        (same as _extract_summary)
        """
        cp = raw.get("clientPortfolio", {})
        mirrors = cp.get("mirrors", [])
        positions = cp.get("positions", [])
        
        # Compute total_value same way as _extract_summary
        invested = sum(p.get("amount", 0.0) for p in positions) + sum(m.get("initialInvestment", 0.0) for m in mirrors)
        positions_pnl = sum(p.get("unrealizedPnL", {}).get("pnL", 0.0) for p in positions)
        mirrors_pnl = sum(
            pos.get("unrealizedPnL", {}).get("pnL", 0.0) for m in mirrors for pos in m.get("positions", [])
        )
        unrealized_pnl = positions_pnl + mirrors_pnl
        realized_pnl = sum(m.get("closedPositionsNetProfit", 0.0) for m in mirrors)
        available_cash = cp.get("credit", 0.0)
        total_value = invested + realized_pnl + unrealized_pnl + available_cash
        
        result = []
        for m in mirrors:
            unrealized_pnl_mirror = sum(pos.get("unrealizedPnL", {}).get("pnL", 0.0) for pos in m.get("positions", []))
            total_pnl = m.get("closedPositionsNetProfit", 0.0) + unrealized_pnl_mirror
            initial_investment = m.get("initialInvestment", 1.0)
            
            # Mirror equity = initialInvestment + closedPositionsNetProfit + unrealizedPnL
            mirror_equity = initial_investment + m.get("closedPositionsNetProfit", 0.0) + unrealized_pnl_mirror
            
            mirror_id = m.get("agentPortfolioId") or m.get("AgentPortfolioID") or m.get("mirrorId") or m.get("portfolioId") or 0
            result.append({
                "trader_id": str(mirror_id),
                "username": m.get("parentUsername", "Unknown"),
                "allocation_pct": (mirror_equity / max(total_value, 1.0)) * 100,
                "avg_return": 0.0,
                "max_drawdown": 0.0,
                "volatility": 0.0,
                "risk_score": 5.0,
                "total_return_pct": (total_pnl / max(initial_investment, 1.0)) * 100,
            })
        return result

    def _sync_traders(self, db, portfolio_id: int, traders_data: List[Dict], total_equity: float):
        """Update or create copied trader records."""
        from backend.database.models import CopiedTrader

        for info in traders_data:
            trader = db.query(CopiedTrader).filter(
                CopiedTrader.portfolio_id == portfolio_id,
                CopiedTrader.trader_id == info.get("trader_id"),
            ).first()

            if trader:
                trader.trader_username = info.get("username", trader.trader_username)
                trader.allocation_pct = info.get("allocation_pct", trader.allocation_pct)
                trader.avg_monthly_return = info.get("avg_return", trader.avg_monthly_return)
                trader.max_drawdown = info.get("max_drawdown", trader.max_drawdown)
                trader.volatility = info.get("volatility", trader.volatility)
                trader.risk_score = info.get("risk_score", trader.risk_score)
                trader.total_return_pct = info.get("total_return_pct", trader.total_return_pct)
                trader.last_updated = datetime.utcnow()
            else:
                trader = CopiedTrader(
                    portfolio_id=portfolio_id,
                    trader_id=info.get("trader_id"),
                    trader_username=info.get("username", "Unknown"),
                    allocation_pct=info.get("allocation_pct", 0.0),
                    avg_monthly_return=info.get("avg_return", 0.0),
                    max_drawdown=info.get("max_drawdown", 0.0),
                    volatility=info.get("volatility", 0.0),
                    risk_score=info.get("risk_score", 0.0),
                    total_return_pct=info.get("total_return_pct", 0.0),
                )
                db.add(trader)

        db.commit()
        logger.info(f"Synced {len(traders_data)} traders for portfolio {portfolio_id}")
