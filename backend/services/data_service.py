"""
Data Service
────────────────────────────────────────────────────────────────────
Abstracts data retrieval — supports both live eToro API (future)
and simulation/mock data for development and paper-trading mode.
"""

from __future__ import annotations
import random
from typing import List
from backend.database.models import CopiedTrader
from backend.analytics.trader_analytics import TraderMetrics


class DataService:
    """
    Provides market data and trader metrics.
    In simulation mode: generates realistic mock data.
    In live mode: calls eToro API (pluggable).
    """

    def build_trader_metrics(self, trader: CopiedTrader) -> TraderMetrics:
        """
        Build a TraderMetrics object from the trader record.
        If live data is not available, uses simulation data.
        """
        # In production: fetch from eToro API using trader.trader_id
        # For now: generate realistic simulation data based on trader's stored values
        return TraderMetrics(
            trader_id=trader.trader_id,
            username=trader.trader_username,
            monthly_returns=self._simulate_monthly_returns(
                avg=trader.avg_monthly_return or 1.5,
                volatility=trader.volatility or 8.0,
                months=max(6, 24),
            ),
            max_drawdown=trader.max_drawdown or random.uniform(5, 25),
            trade_frequency_per_week=trader.trade_frequency or random.uniform(2, 15),
            volatility_pct=trader.volatility or random.uniform(5, 35),
            portfolio_instruments=self._sample_instruments(),
            months_of_history=24,
        )

    def _simulate_monthly_returns(
        self,
        avg: float,
        volatility: float,
        months: int = 24,
    ) -> List[float]:
        """Generate synthetic monthly return series with realistic variance."""
        returns = []
        for _ in range(months):
            noise = random.gauss(0, volatility / 4)
            returns.append(round(avg + noise, 2))
        return returns

    def _sample_instruments(self) -> List[str]:
        all_instruments = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
            "BTC", "ETH", "XRP",
            "GOLD", "OIL",
            "EURUSD", "GBPUSD",
            "SPX500", "NDX100",
        ]
        count = random.randint(3, 10)
        return random.sample(all_instruments, min(count, len(all_instruments)))

    def seed_simulation_data(self, db, portfolio_id: int):
        """
        Seed a portfolio with realistic simulation data.
        Useful for demo and testing.
        """
        from backend.database.models import Portfolio, CopiedTrader, PortfolioSnapshot
        from datetime import datetime, timedelta
        import math

        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
        if not portfolio:
            return

        # Seed portfolio values
        portfolio.total_value = 10000.0
        portfolio.invested_amount = 9500.0
        portfolio.available_cash = 500.0
        portfolio.unrealized_pnl = 450.0
        portfolio.realized_pnl = 120.0
        portfolio.daily_pnl = 85.0
        portfolio.weekly_pnl = 320.0
        portfolio.monthly_pnl = 780.0
        portfolio.health_score = 72.5

        # Seed traders
        traders_data = [
            {"username": "AlphaTrader_99", "id": "et_001", "alloc": 3500, "pct": 35, "risk": 4.2},
            {"username": "GrowthSeeker", "id": "et_002", "alloc": 2500, "pct": 25, "risk": 5.8},
            {"username": "CryptoKing2024", "id": "et_003", "alloc": 2000, "pct": 20, "risk": 7.5},
            {"username": "DividendFocus", "id": "et_004", "alloc": 1500, "pct": 15, "risk": 3.1},
        ]

        for td in traders_data:
            existing = db.query(CopiedTrader).filter(
                CopiedTrader.portfolio_id == portfolio_id,
                CopiedTrader.trader_id == td["id"],
            ).first()
            if not existing:
                trader = CopiedTrader(
                    portfolio_id=portfolio_id,
                    trader_username=td["username"],
                    trader_id=td["id"],
                    allocated_amount=td["alloc"],
                    allocation_pct=td["pct"],
                    current_value=td["alloc"] * random.uniform(0.95, 1.15),
                    unrealized_pnl=random.uniform(-50, 200),
                    total_return_pct=random.uniform(-5, 20),
                    risk_score=td["risk"],
                    max_drawdown=random.uniform(3, 18),
                    avg_monthly_return=random.uniform(0.5, 3.5),
                    sharpe_score=random.uniform(0.3, 1.8),
                    volatility=random.uniform(8, 30),
                    trade_frequency=random.uniform(2, 12),
                    diversification_score=random.uniform(40, 90),
                    consistency_score=random.uniform(50, 85),
                )
                db.add(trader)

        # Seed 30 days of portfolio snapshots
        base_value = 9200.0
        for i in range(30):
            date = datetime.utcnow() - timedelta(days=30 - i)
            drift = math.sin(i / 4) * 200 + i * 25
            value = base_value + drift + random.uniform(-100, 100)
            db.add(PortfolioSnapshot(
                portfolio_id=portfolio_id,
                total_value=round(value, 2),
                daily_pnl=round(random.uniform(-80, 120), 2),
                unrealized_pnl=round(value - base_value, 2),
                health_score=round(random.uniform(65, 85), 1),
                recorded_at=date,
            ))

        db.commit()
