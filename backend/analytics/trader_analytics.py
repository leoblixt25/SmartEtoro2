"""
Copied Trader Analytics Engine
────────────────────────────────────────────────────────────────────
Evaluates copied traders using multi-factor risk scoring.
Produces human-readable summaries and risk classifications.

All scores are deterministic and explainable — no black-box logic.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Optional
from backend.database.models import RiskClassification


# ──────────────────────────────────────────────
# Weights for composite scoring
# ──────────────────────────────────────────────

SCORE_WEIGHTS = {
    "consistency":      0.25,
    "drawdown":         0.25,
    "sharpe":           0.20,
    "volatility":       0.15,
    "diversification":  0.10,
    "trade_frequency":  0.05,
}


@dataclass
class TraderMetrics:
    """Raw metrics for a trader — usually sourced from eToro API or mock data."""
    trader_id: str
    username: str

    # Performance
    monthly_returns: List[float] = field(default_factory=list)   # e.g. [3.2, -1.1, 4.5 ...]
    max_drawdown: float = 0.0          # as positive percentage, e.g. 12.5 = 12.5%
    trade_frequency_per_week: float = 5.0

    # Risk
    volatility_pct: float = 0.0        # annualized volatility %
    portfolio_instruments: List[str] = field(default_factory=list)

    # Meta
    months_of_history: int = 0


@dataclass
class TraderAnalysisResult:
    trader_id: str
    username: str
    risk_score: float                  # 1–10, higher = riskier
    risk_classification: RiskClassification
    avg_monthly_return: float
    max_drawdown: float
    sharpe_score: float
    volatility: float
    consistency_score: float           # 0–100
    diversification_score: float       # 0–100
    composite_health_score: float      # 0–100, higher = healthier

    strengths: List[str]
    weaknesses: List[str]
    warning_signs: List[str]
    sustainability: str
    overall_verdict: str


class TraderAnalyticsEngine:
    """
    Evaluates a trader's metrics and produces a scored, classified result
    with human-readable explanations.
    """

    # ── Public API ──────────────────────────────

    def analyze(self, metrics: TraderMetrics) -> TraderAnalysisResult:
        """Run full analysis pipeline on a set of trader metrics."""
        avg_return = self._avg_monthly_return(metrics.monthly_returns)
        consistency = self._consistency_score(metrics.monthly_returns)
        drawdown_score = self._drawdown_score(metrics.max_drawdown)
        sharpe = self._sharpe_like_score(metrics.monthly_returns)
        volatility_score = self._volatility_score(metrics.volatility_pct)
        diversification = self._diversification_score(metrics.portfolio_instruments)
        freq_score = self._frequency_score(metrics.trade_frequency_per_week)

        composite = self._composite_health(
            consistency=consistency,
            drawdown_score=drawdown_score,
            sharpe=sharpe,
            volatility_score=volatility_score,
            diversification=diversification,
            freq_score=freq_score,
        )

        risk_score = self._risk_score(metrics)
        classification = self._classify(risk_score, metrics.max_drawdown, metrics.volatility_pct)

        strengths, weaknesses, warnings = self._narrative_analysis(
            metrics, avg_return, consistency, sharpe,
            risk_score, diversification
        )
        sustainability = self._sustainability_statement(metrics, risk_score, composite)
        verdict = self._overall_verdict(composite, risk_score, warnings)

        return TraderAnalysisResult(
            trader_id=metrics.trader_id,
            username=metrics.username,
            risk_score=round(risk_score, 2),
            risk_classification=classification,
            avg_monthly_return=round(avg_return, 2),
            max_drawdown=round(metrics.max_drawdown, 2),
            sharpe_score=round(sharpe, 2),
            volatility=round(metrics.volatility_pct, 2),
            consistency_score=round(consistency, 1),
            diversification_score=round(diversification, 1),
            composite_health_score=round(composite, 1),
            strengths=strengths,
            weaknesses=weaknesses,
            warning_signs=warnings,
            sustainability=sustainability,
            overall_verdict=verdict,
        )

    # ── Individual metric scorers ────────────────

    def _avg_monthly_return(self, returns: List[float]) -> float:
        if not returns:
            return 0.0
        return sum(returns) / len(returns)

    def _consistency_score(self, returns: List[float]) -> float:
        """Percentage of positive months. Higher = more consistent."""
        if not returns:
            return 50.0
        positive = sum(1 for r in returns if r > 0)
        return round((positive / len(returns)) * 100, 1)

    def _drawdown_score(self, max_drawdown: float) -> float:
        """
        Convert max drawdown % to a 0–100 health score.
        0% drawdown → 100; 50%+ drawdown → 0.
        """
        clamped = min(max_drawdown, 50.0)
        return 100.0 - (clamped * 2)

    def _sharpe_like_score(self, returns: List[float]) -> float:
        """
        Simplified Sharpe-like ratio: mean return / std deviation.
        Risk-free rate assumed ~0 for simplicity.
        """
        if len(returns) < 3:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        return round(mean / std, 3)

    def _volatility_score(self, volatility_pct: float) -> float:
        """Lower volatility → higher score. Clamp at 80%."""
        clamped = min(volatility_pct, 80.0)
        return 100.0 - (clamped * 1.25)

    def _diversification_score(self, instruments: List[str]) -> float:
        """
        More unique instrument types = better diversification.
        Classify instruments into broad asset classes.
        """
        if not instruments:
            return 20.0

        classes = set()
        for inst in instruments:
            inst_upper = inst.upper()
            if any(k in inst_upper for k in ["BTC", "ETH", "XRP", "CRYPTO", "DOGE"]):
                classes.add("crypto")
            elif any(k in inst_upper for k in ["GOLD", "OIL", "SILVER", "COMMODITY"]):
                classes.add("commodity")
            elif any(k in inst_upper for k in ["USD", "EUR", "GBP", "JPY", "FOREX"]):
                classes.add("forex")
            elif any(k in inst_upper for k in ["SPX", "NDX", "DAX", "INDEX"]):
                classes.add("index")
            else:
                classes.add("equity")

        # Score: 1 class = 20, 5+ classes = 100
        return min(100.0, len(classes) * 20.0)

    def _frequency_score(self, trades_per_week: float) -> float:
        """
        Ideal: 1–10 trades/week. Very high frequency penalized (HFT risk).
        Very low frequency also slightly penalized.
        """
        if trades_per_week < 1:
            return 60.0
        if trades_per_week <= 10:
            return 100.0
        if trades_per_week <= 30:
            return 80.0
        return max(0.0, 100.0 - (trades_per_week - 30) * 2)

    def _composite_health(self, **component_scores: float) -> float:
        """Weighted composite of component scores → 0–100."""
        weighted = (
            component_scores["consistency"]    * SCORE_WEIGHTS["consistency"]
            + component_scores["drawdown_score"]  * SCORE_WEIGHTS["drawdown"]
            + (min(max(component_scores["sharpe"], -1), 3) / 3 * 100) * SCORE_WEIGHTS["sharpe"]
            + component_scores["volatility_score"] * SCORE_WEIGHTS["volatility"]
            + component_scores["diversification"]  * SCORE_WEIGHTS["diversification"]
            + component_scores["freq_score"]       * SCORE_WEIGHTS["trade_frequency"]
        )
        return min(100.0, max(0.0, weighted))

    def _risk_score(self, m: TraderMetrics) -> float:
        """
        Composite risk score 1–10.
        Higher = riskier. Based on drawdown, volatility, frequency, and history length.
        """
        base = 5.0

        # Drawdown risk (0–3 points)
        base += min(3.0, m.max_drawdown / 15.0)

        # Volatility risk (0–2 points)
        base += min(2.0, m.volatility_pct / 20.0)

        # High frequency bonus risk
        if m.trade_frequency_per_week > 20:
            base += 0.5

        # Limited history → uncertain, bump slightly
        if m.months_of_history < 6:
            base += 0.5

        # Good diversification reduces risk
        diversification = self._diversification_score(m.portfolio_instruments)
        if diversification > 60:
            base -= 0.5

        return min(10.0, max(1.0, base))

    def _classify(
        self,
        risk_score: float,
        max_drawdown: float,
        volatility: float,
    ) -> RiskClassification:
        """Map risk score + metrics to classification."""
        if risk_score <= 4.0 and max_drawdown < 10 and volatility < 15:
            return RiskClassification.CONSERVATIVE
        if risk_score <= 6.0 and max_drawdown < 20:
            return RiskClassification.BALANCED
        if risk_score <= 7.5:
            return RiskClassification.AGGRESSIVE
        return RiskClassification.HIGH_RISK

    # ── Narrative generators ─────────────────────

    def _narrative_analysis(
        self,
        m: TraderMetrics,
        avg_return: float,
        consistency: float,
        sharpe: float,
        risk_score: float,
        diversification: float,
    ):
        strengths, weaknesses, warnings = [], [], []

        # Strengths
        if consistency >= 65:
            strengths.append(f"Strong consistency: positive returns in {consistency:.0f}% of months")
        if avg_return >= 2.0:
            strengths.append(f"Above-average monthly returns of {avg_return:.1f}%")
        if sharpe >= 1.0:
            strengths.append("Good risk-adjusted returns (Sharpe-like ratio ≥ 1.0)")
        if m.max_drawdown < 10:
            strengths.append(f"Controlled drawdown at {m.max_drawdown:.1f}% — well within safe range")
        if diversification >= 60:
            strengths.append("Diversified across multiple asset classes")
        if m.months_of_history >= 24:
            strengths.append(f"Substantial track record: {m.months_of_history} months of data")

        # Weaknesses
        if consistency < 50:
            weaknesses.append(f"Inconsistent performance — only {consistency:.0f}% positive months")
        if avg_return < 0:
            weaknesses.append(f"Negative average monthly return of {avg_return:.1f}%")
        if m.max_drawdown > 20:
            weaknesses.append(f"High historical drawdown of {m.max_drawdown:.1f}%")
        if diversification < 40:
            weaknesses.append("Limited diversification — concentrated in few asset classes")
        if m.months_of_history < 6:
            weaknesses.append("Limited historical data — classification may not be reliable")

        # Warning signs
        if m.max_drawdown > 30:
            warnings.append(f"⚠ Extreme drawdown detected: {m.max_drawdown:.1f}%")
        if m.volatility_pct > 40:
            warnings.append(f"⚠ Very high volatility ({m.volatility_pct:.1f}%) — expect large swings")
        if m.trade_frequency_per_week > 30:
            warnings.append("⚠ Very high trade frequency may indicate overtrading")
        if risk_score >= 8:
            warnings.append("⚠ Risk score in the danger zone — consider reducing allocation")
        if sharpe < -0.5:
            warnings.append("⚠ Negative risk-adjusted returns — returns do not justify risk taken")

        return strengths, weaknesses, warnings

    def _sustainability_statement(
        self,
        m: TraderMetrics,
        risk_score: float,
        health_score: float,
    ) -> str:
        if health_score >= 70 and risk_score <= 5:
            return (
                "Sustainability outlook is positive. The trader shows disciplined risk management "
                "and consistent returns, suggesting a long-term viable strategy."
            )
        if health_score >= 50:
            return (
                "Sustainability outlook is moderate. Performance has been reasonable but carries "
                "elevated risk. Monitor for signs of strategy deterioration."
            )
        return (
            "Sustainability outlook is uncertain. High risk and inconsistent performance "
            "raise concerns about long-term viability. Consider reducing or pausing allocation."
        )

    def _overall_verdict(
        self,
        health_score: float,
        risk_score: float,
        warnings: List[str],
    ) -> str:
        has_critical_warnings = len(warnings) >= 2

        if health_score >= 75 and not has_critical_warnings:
            return "HOLD — Performing well. No action required."
        if health_score >= 55 and risk_score <= 6:
            return "MONITOR — Acceptable performance. Review allocation quarterly."
        if has_critical_warnings or risk_score >= 8:
            return "REVIEW — Risk level elevated. Consider reducing allocation."
        return "CAUTION — Performance below expectations. Evaluate carefully before continuing."
