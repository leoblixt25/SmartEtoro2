"""
Risk Management Enforcement Engine
────────────────────────────────────────────────────────────────────
Mandatory risk protections that run on every portfolio update.
These checks cannot be disabled by the user — they are safety rails.

Actions are logged, never silently executed.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.database.models import (
    Portfolio, CopiedTrader, RiskSettings, AutomationLog,
    Alert, AlertType
)

logger = logging.getLogger(__name__)


@dataclass
class RiskViolation:
    """Represents a detected risk threshold breach."""
    violation_type: str
    severity: str               # info / warning / critical
    title: str
    message: str
    suggested_action: str
    affected_trader: Optional[str] = None
    requires_immediate_action: bool = False


class RiskEngine:
    """
    Evaluates portfolio against risk settings and returns violations.
    Does NOT execute any trades — only flags and logs.

    Execution decisions are handled by the AutomationEngine,
    which always requires user approval for critical actions.
    """

    def check_all(
        self,
        db: Session,
        portfolio: Portfolio,
        settings: Optional[RiskSettings],
    ) -> List[RiskViolation]:
        """Run all risk checks and return list of violations."""
        if settings is None:
            return []

        violations: List[RiskViolation] = []
        traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]

        violations.extend(self._check_portfolio_drawdown(portfolio, settings))
        violations.extend(self._check_trader_allocations(traders, settings))
        violations.extend(self._check_diversification(traders, settings))
        violations.extend(self._check_trader_risk_scores(traders))
        violations.extend(self._check_emergency_mode(portfolio, settings))
        violations.extend(self._check_cooldown_compliance(db, portfolio, settings))

        return violations

    # ── Individual risk checks ───────────────────

    def _check_portfolio_drawdown(
        self,
        portfolio: Portfolio,
        settings: RiskSettings,
    ) -> List[RiskViolation]:
        violations = []

        if portfolio.total_value <= 0 or portfolio.invested_amount <= 0:
            return violations

        current_drawdown_pct = (
            (portfolio.invested_amount - portfolio.total_value)
            / portfolio.invested_amount * 100
        )

        warn_threshold = settings.max_portfolio_drawdown_pct * 0.75
        crit_threshold = settings.max_portfolio_drawdown_pct

        if current_drawdown_pct >= crit_threshold:
            violations.append(RiskViolation(
                violation_type="portfolio_drawdown_critical",
                severity="critical",
                title="Maximum Drawdown Threshold Breached",
                message=(
                    f"Portfolio has drawn down {current_drawdown_pct:.1f}%, "
                    f"exceeding the {crit_threshold:.1f}% maximum limit."
                ),
                suggested_action=(
                    "Consider reducing exposure to highest-risk traders "
                    "and review whether to pause copy relationships."
                ),
                requires_immediate_action=True,
            ))
        elif current_drawdown_pct >= warn_threshold:
            violations.append(RiskViolation(
                violation_type="portfolio_drawdown_warning",
                severity="warning",
                title="Drawdown Approaching Limit",
                message=(
                    f"Portfolio drawdown at {current_drawdown_pct:.1f}% "
                    f"({warn_threshold:.1f}% warning threshold)."
                ),
                suggested_action="Monitor closely and prepare risk reduction plan.",
            ))

        return violations

    def _check_trader_allocations(
        self,
        traders: List[CopiedTrader],
        settings: RiskSettings,
    ) -> List[RiskViolation]:
        violations = []
        for trader in traders:
            if trader.allocation_pct > settings.max_allocation_per_trader_pct:
                violations.append(RiskViolation(
                    violation_type="trader_overallocation",
                    severity="warning",
                    title=f"Over-Allocation: {trader.trader_username}",
                    message=(
                        f"{trader.trader_username} represents {trader.allocation_pct:.1f}% "
                        f"of portfolio, exceeding the {settings.max_allocation_per_trader_pct:.1f}% limit."
                    ),
                    suggested_action=(
                        f"Reduce allocation to {trader.trader_username} "
                        f"to below {settings.max_allocation_per_trader_pct:.1f}%."
                    ),
                    affected_trader=trader.trader_username,
                ))
        return violations

    def _check_diversification(
        self,
        traders: List[CopiedTrader],
        settings: RiskSettings,
    ) -> List[RiskViolation]:
        violations = []
        if len(traders) < settings.min_traders_for_diversification:
            violations.append(RiskViolation(
                violation_type="insufficient_diversification",
                severity="info",
                title="Low Diversification",
                message=(
                    f"Portfolio has {len(traders)} active copied trader(s). "
                    f"Recommended minimum is {settings.min_traders_for_diversification}."
                ),
                suggested_action=(
                    "Add more copied traders to improve diversification "
                    "and reduce single-trader dependency."
                ),
            ))
        return violations

    def _check_trader_risk_scores(
        self,
        traders: List[CopiedTrader],
    ) -> List[RiskViolation]:
        violations = []
        for trader in traders:
            if trader.risk_score >= 9:
                violations.append(RiskViolation(
                    violation_type="trader_extreme_risk",
                    severity="critical",
                    title=f"Extreme Risk: {trader.trader_username}",
                    message=(
                        f"{trader.trader_username} has a risk score of {trader.risk_score:.1f}/10. "
                        "This indicates very high potential for significant losses."
                    ),
                    suggested_action="Strongly consider reducing or stopping copy for this trader.",
                    affected_trader=trader.trader_username,
                    requires_immediate_action=True,
                ))
            elif trader.risk_score >= 7.5:
                violations.append(RiskViolation(
                    violation_type="trader_high_risk",
                    severity="warning",
                    title=f"High Risk Trader: {trader.trader_username}",
                    message=(
                        f"{trader.trader_username} risk score is {trader.risk_score:.1f}/10."
                    ),
                    suggested_action="Consider reducing allocation to this trader.",
                    affected_trader=trader.trader_username,
                ))
        return violations

    def _check_emergency_mode(
        self,
        portfolio: Portfolio,
        settings: RiskSettings,
    ) -> List[RiskViolation]:
        if not settings.emergency_protection_enabled:
            return []

        violations = []
        if portfolio.total_value <= 0 or portfolio.invested_amount <= 0:
            return violations

        drawdown_pct = (
            (portfolio.invested_amount - portfolio.total_value)
            / portfolio.invested_amount * 100
        )

        if drawdown_pct >= settings.emergency_drawdown_trigger_pct:
            violations.append(RiskViolation(
                violation_type="emergency_trigger",
                severity="critical",
                title="⛔ Emergency Protection Triggered",
                message=(
                    f"Portfolio drawdown of {drawdown_pct:.1f}% has reached the "
                    f"emergency threshold of {settings.emergency_drawdown_trigger_pct:.1f}%. "
                    "All automation has been paused."
                ),
                suggested_action=(
                    "Manual review required. Consider pausing all copy relationships "
                    "until market conditions stabilize."
                ),
                requires_immediate_action=True,
            ))

        return violations

    def _check_cooldown_compliance(
        self,
        db: Session,
        portfolio: Portfolio,
        settings: RiskSettings,
    ) -> List[RiskViolation]:
        """Check if actions were taken too soon after a loss event."""
        violations = []
        if settings.cooldown_after_loss_hours <= 0:
            return violations

        # Find recent loss automation logs
        cutoff = datetime.utcnow() - timedelta(hours=settings.cooldown_after_loss_hours)
        recent_loss_actions = (
            db.query(AutomationLog)
            .filter(
                AutomationLog.portfolio_id == portfolio.id,
                AutomationLog.action_type == "loss_event",
                AutomationLog.triggered_at >= cutoff,
            )
            .count()
        )

        if recent_loss_actions > 0:
            violations.append(RiskViolation(
                violation_type="cooldown_active",
                severity="info",
                title="Loss Cooldown Active",
                message=(
                    f"A loss event was recorded within the last {settings.cooldown_after_loss_hours}h. "
                    "Trading automation is in cooldown to prevent reactive decisions."
                ),
                suggested_action="Wait for cooldown to expire before resuming automation.",
            ))

        return violations

    # ── Alert creation helper ────────────────────

    def violations_to_alerts(
        self,
        db: Session,
        portfolio_id: int,
        violations: List[RiskViolation],
    ) -> None:
        """Persist risk violations as alerts in the database."""
        for v in violations:
            severity_map = {"info": AlertType.DRAWDOWN, "warning": AlertType.TRADER_RISK,
                            "critical": AlertType.DRAWDOWN}
            alert = Alert(
                portfolio_id=portfolio_id,
                alert_type=severity_map.get(v.severity, AlertType.DRAWDOWN),
                title=v.title,
                message=v.message,
                severity=v.severity,
            )
            db.add(alert)
            logger.info(f"Risk alert created: [{v.severity.upper()}] {v.title}")

        if violations:
            db.commit()
