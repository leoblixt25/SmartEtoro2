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

    async def get_portfolio_data(self, is_simulation: bool = True) -> Optional[Dict]:
        """
        Fetch portfolio + PnL + positions + mirrors in one call.
        Uses demo or real endpoint based on is_simulation flag.
        """
        if not self.enabled:
            return None

        env = "demo" if is_simulation else "real"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/api/v1/trading/info/{env}/pnl",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                data = response.json()
                logger.info(
                    f"Fetched portfolio data from eToro ({env})")
                return data
        except httpx.HTTPStatusError as e:
            logger.error(
                f"eToro API error {e.response.status_code}: {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Network error connecting to eToro API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching eToro portfolio: {e}")
            return None

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

            # Try real API, fall back to mock data
            if self.client.enabled:
                raw = await self.client.get_portfolio_data(
                    is_simulation=portfolio.is_simulation
                )
                if raw:
                    summary = self._extract_summary(raw)
                    traders = self._extract_traders(raw)
                    logger.info("Synced live data from eToro API")
                else:
                    logger.info("eToro API unavailable — using simulation data")
                    summary = self.client._get_mock_account_summary()
                    traders = self.client._get_mock_traders()
            else:
                logger.info("eToro API not configured — using simulation data")
                summary = self.client._get_mock_account_summary()
                traders = self.client._get_mock_traders()

            portfolio.total_value = summary.get("equity", 0.0)
            portfolio.available_cash = summary.get("available_cash", 0.0)
            portfolio.invested_amount = summary.get("invested", 0.0)
            portfolio.unrealized_pnl = summary.get("unrealized_pnl", 0.0)
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
        """Parse eToro API portfolio response into flat summary dict."""
        cp = raw.get("clientPortfolio", {})
        
        # 1. Cash Balance
        cash = cp.get("credit", 0.0)
        
        # 2. Open Positions value
        positions = cp.get("positions", [])
        invested_positions = sum(p.get("amount", 0.0) for p in positions)
        
        # 3. Mirror (Copy Trading) value
        mirrors = cp.get("mirrors", [])
        invested_mirrors = sum(m.get("initialInvestment", 0.0) for m in mirrors)
        
        # 4. Total PnL
        unrealized_pnl = cp.get("unrealizedPnL", 0.0)
        
        # eToro API Currency ID 1=USD, 2=EUR
        currency = "EUR" if cp.get("accountCurrencyId") == 2 else "USD"

        return {
            "equity": cash + invested_positions + invested_mirrors + unrealized_pnl,
            "available_cash": cash,
            "invested": invested_positions + invested_mirrors,
            "unrealized_pnl": unrealized_pnl,
            "currency": currency,
            "realized_pnl": 0.0,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "monthly_pnl": 0.0,
        }

    def _extract_traders(self, raw: Dict) -> List[Dict]:
        """Extract copied trader info from mirrors array."""
        cp = raw.get("clientPortfolio", {})
        mirrors = cp.get("mirrors", [])
        total_equity = cp.get("credit", 0.0) + sum(p.get("initialAmountInDollars", 0.0) for p in cp.get("positions", [])) + cp.get("unrealizedPnL", 0.0)
        
        result = []
        for m in mirrors:
            result.append({
                "trader_id": str(m.get("mirrorId", 0)),
                "username": m.get("parentUsername", "Unknown"),
                "allocation_pct": (m.get("initialInvestment", 0.0) / max(total_equity, 1.0)) * 100,
                "avg_return": 0.0,
                "max_drawdown": 0.0,
                "volatility": 0.0,
                "risk_score": 5.0,
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
                )
                db.add(trader)

        db.commit()
        logger.info(f"Synced {len(traders_data)} traders for portfolio {portfolio_id}")
