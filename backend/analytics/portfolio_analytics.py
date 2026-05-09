"""
Portfolio Risk & Health Analytics
────────────────────────────────────────────────────────────────────
Calculates portfolio-level health, diversification, and risk exposure.
All assessments are explainable and threshold-driven.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from backend.database.models import Portfolio, CopiedTrader, Position, RiskSettings


@dataclass
class PortfolioHealthResult:
    health_score: float                     # 0–100
    diversification_score: float            # 0–100
    risk_exposure: str                      # low / medium / high / critical
    concentration_risk: bool
    overexposed_traders: List[str]
    underperforming_traders: List[str]
    recommendations: List[str]
    pnl_breakdown: Dict[str, float]
    allocation_by_trader: List[Dict]


class PortfolioAnalyticsEngine:
    """
    Computes portfolio-wide health metrics.
    Reads directly from the database; does not modify anything.
    """

    def analyze(
        self,
        db: Session,
        portfolio: Portfolio,
        risk_settings: RiskSettings | None = None,
    ) -> PortfolioHealthResult:
        traders = [t for t in portfolio.copied_traders if t.is_active]
        positions = [p for p in portfolio.positions if p.is_open]

        # Default risk settings if not configured
        max_alloc_pct = (risk_settings.max_allocation_per_trader_pct if risk_settings else None) or 30.0
        min_traders = (risk_settings.min_traders_for_diversification if risk_settings else None) or 3

        total_value = portfolio.total_value or 1.0  # Avoid division by zero

        diversification = self._diversification_score(traders, total_value, min_traders)
        concentration_risk, overexposed = self._check_concentration(traders, max_alloc_pct)
        underperforming = self._find_underperformers(traders)
        risk_exposure = self._risk_exposure_level(traders, portfolio)
        recommendations = self._build_recommendations(
            traders=traders,
            overexposed=overexposed,
            underperforming=underperforming,
            risk_exposure=risk_exposure,
            total_value=total_value,
            portfolio=portfolio,
            diversification=diversification,
            min_traders=min_traders,
        )

        health_score = self._composite_health(
            diversification=diversification,
            concentration_risk=concentration_risk,
            risk_exposure=risk_exposure,
            portfolio=portfolio,
            warnings_count=len(overexposed) + len(underperforming),
        )

        allocation_by_trader = [
            {
                "trader_username": t.trader_username,
                "amount": round(t.allocated_amount, 2),
                "pct": round(t.allocation_pct, 2),
                "pnl": round(t.unrealized_pnl, 2),
                "risk_score": round(t.risk_score, 1),
            }
            for t in traders
        ]

        return PortfolioHealthResult(
            health_score=round(health_score, 1),
            diversification_score=round(diversification, 1),
            risk_exposure=risk_exposure,
            concentration_risk=concentration_risk,
            overexposed_traders=overexposed,
            underperforming_traders=underperforming,
            recommendations=recommendations,
            pnl_breakdown={
                "daily": round(portfolio.daily_pnl, 2),
                "weekly": round(portfolio.weekly_pnl, 2),
                "monthly": round(portfolio.monthly_pnl, 2),
                "unrealized": round(portfolio.unrealized_pnl, 2),
                "realized": round(portfolio.realized_pnl, 2),
            },
            allocation_by_trader=allocation_by_trader,
        )

    # ── Private helpers ──────────────────────────

    def _diversification_score(
        self,
        traders: List[CopiedTrader],
        total_value: float,
        min_traders: int,
    ) -> float:
        if not traders:
            return 0.0

        # Penalize if below minimum traders
        count_score = min(100.0, (len(traders) / min_traders) * 60.0)

        # Penalize concentration: compute HHI (Herfindahl–Hirschman Index)
        allocations = [t.allocated_amount / total_value for t in traders]
        hhi = sum(a ** 2 for a in allocations)
        concentration_penalty = hhi * 40.0  # 0–40 penalty

        return max(0.0, count_score - concentration_penalty)

    def _check_concentration(
        self,
        traders: List[CopiedTrader],
        max_alloc_pct: float,
    ) -> Tuple[bool, List[str]]:
        overexposed = [
            t.trader_username
            for t in traders
            if t.allocation_pct > max_alloc_pct
        ]
        return bool(overexposed), overexposed

    def _find_underperformers(self, traders: List[CopiedTrader]) -> List[str]:
        """Traders with negative returns AND high risk score are flagged."""
        return [
            t.trader_username
            for t in traders
            if t.total_return_pct < -5.0 and t.risk_score >= 7
        ]

    def _risk_exposure_level(
        self,
        traders: List[CopiedTrader],
        portfolio: Portfolio,
    ) -> str:
        if not traders:
            return "low"

        avg_risk = sum(t.risk_score for t in traders) / len(traders)
        max_drawdown = max((t.max_drawdown for t in traders), default=0)

        if avg_risk >= 8 or max_drawdown > 35:
            return "critical"
        if avg_risk >= 6.5 or max_drawdown > 20:
            return "high"
        if avg_risk >= 5:
            return "medium"
        return "low"

    def _build_recommendations(
        self,
        traders: List[CopiedTrader],
        overexposed: List[str],
        underperforming: List[str],
        risk_exposure: str,
        total_value: float,
        portfolio: Portfolio,
        diversification: float,
        min_traders: int,
    ) -> List[str]:
        recs = []

        if overexposed:
            recs.append(
                f"Reduce allocation to {', '.join(overexposed)} — "
                "each exceeds the recommended maximum per-trader allocation."
            )

        if underperforming:
            recs.append(
                f"Review {', '.join(underperforming)} — "
                "negative returns combined with elevated risk score."
            )

        if len(traders) < min_traders:
            recs.append(
                f"Add more copied traders to improve diversification "
                f"(currently {len(traders)}, recommended minimum {min_traders})."
            )

        if diversification < 40:
            recs.append(
                "Portfolio diversification is below healthy levels. "
                "Consider spreading allocation across more traders or asset classes."
            )

        if risk_exposure in ("high", "critical"):
            recs.append(
                "Overall portfolio risk exposure is elevated. "
                "Review high-risk traders and consider reducing total exposure."
            )

        monthly_pnl_pct = (portfolio.monthly_pnl / total_value * 100) if total_value else 0
        if monthly_pnl_pct > 15:
            recs.append(
                "Significant gains this month. Consider locking partial profits "
                "to protect against reversals."
            )

        if not recs:
            recs.append(
                "Portfolio is within healthy parameters. "
                "Continue regular monitoring and scheduled reviews."
            )

        return recs

    def _composite_health(
        self,
        diversification: float,
        concentration_risk: bool,
        risk_exposure: str,
        portfolio: Portfolio,
        warnings_count: int,
    ) -> float:
        score = diversification  # Base: 0–100

        # Risk exposure penalty
        exposure_penalties = {"low": 0, "medium": 10, "high": 25, "critical": 40}
        score -= exposure_penalties.get(risk_exposure, 0)

        # Concentration penalty
        if concentration_risk:
            score -= 15

        # Warning count penalty
        score -= warnings_count * 5

        # Small PnL bonus (capped)
        if portfolio.monthly_pnl > 0:
            score = min(100, score + 5)

        return max(0.0, min(100.0, score))
