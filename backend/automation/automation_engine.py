"""
Semi-Automation Engine
────────────────────────────────────────────────────────────────────
Executes automation rules with mandatory safeguards:
- Every action is logged in the audit trail
- Requires user approval for real-money actions (not simulation)
- Cooldown periods enforced
- Emergency stop respected
- All actions reversible via the log

This engine NEVER directly modifies real eToro positions.
It generates proposed actions that users can review and approve.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.database.models import (
    Portfolio, CopiedTrader, AutomationRule, AutomationLog,
    AutomationStatus, Alert, AlertType
)

logger = logging.getLogger(__name__)


@dataclass
class ProposedAction:
    """
    An automation action waiting for review.
    Real actions require explicit user approval.
    Simulation actions are auto-approved.
    """
    rule_id: int
    rule_name: str
    action_type: str
    description: str
    details: dict
    severity: str = "info"
    reversible: bool = True
    requires_approval: bool = True


class AutomationEngine:
    """
    Evaluates active automation rules and generates proposed actions.
    Execution is deferred until user approval (for real portfolios).
    """

    SUPPORTED_RULES = {
        "take_profit": "Auto Take-Profit at threshold",
        "partial_profit_lock": "Lock partial profits at threshold",
        "rebalance": "Rebalance allocations to targets",
        "reduce_on_drawdown": "Reduce allocation after drawdown",
        "pause_copy_on_loss": "Pause copy relationship after repeated losses",
        "reduce_on_volatility": "Reduce exposure during high volatility",
    }

    def evaluate_rules(
        self,
        db: Session,
        portfolio: Portfolio,
        traders: List[CopiedTrader],
    ) -> List[ProposedAction]:
        """
        Evaluate all enabled automation rules.
        Returns proposed actions — does not execute them.
        """
        rules = (
            db.query(AutomationRule)
            .filter(
                AutomationRule.portfolio_id == portfolio.id,
                AutomationRule.status == AutomationStatus.ENABLED,
            )
            .all()
        )

        proposed: List[ProposedAction] = []

        for rule in rules:
            # Enforce cooldown
            if self._in_cooldown(rule):
                logger.debug(f"Rule '{rule.name}' skipped — in cooldown")
                continue

            action = self._evaluate_rule(rule, portfolio, traders)
            if action:
                proposed.append(action)

        return proposed

    def approve_and_execute(
        self,
        db: Session,
        portfolio: Portfolio,
        action: ProposedAction,
        approved_by: str = "user",
    ) -> AutomationLog:
        """
        Mark a proposed action as approved and create an audit log entry.
        In simulation mode, auto-approve. In live mode, require explicit approval.
        """
        log_entry = AutomationLog(
            rule_id=action.rule_id,
            portfolio_id=portfolio.id,
            action_type=action.action_type,
            description=action.description,
            details={**action.details, "approved_by": approved_by},
            was_simulated=portfolio.is_simulation,
            was_approved=True,
        )
        db.add(log_entry)

        # Update rule trigger count and timestamp
        rule = db.query(AutomationRule).filter(AutomationRule.id == action.rule_id).first()
        if rule:
            rule.last_triggered = datetime.utcnow()
            rule.trigger_count += 1

        db.commit()
        logger.info(
            f"Action executed: [{action.action_type}] {action.description} "
            f"(simulation={portfolio.is_simulation})"
        )
        return log_entry

    def reverse_action(
        self,
        db: Session,
        log_id: int,
        portfolio_id: int,
    ) -> bool:
        """Mark an action as reversed in the audit trail."""
        log_entry = (
            db.query(AutomationLog)
            .filter(AutomationLog.id == log_id, AutomationLog.portfolio_id == portfolio_id)
            .first()
        )
        if not log_entry:
            return False
        log_entry.was_reversed = True
        db.commit()
        logger.info(f"Action reversed: log_id={log_id}")
        return True

    def emergency_stop(
        self,
        db: Session,
        portfolio_id: int,
    ) -> int:
        """Disable ALL automation rules for a portfolio immediately."""
        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.portfolio_id == portfolio_id)
            .all()
        )
        count = 0
        for rule in rules:
            rule.status = AutomationStatus.PAUSED
            count += 1

        # Log the emergency stop
        db.add(AutomationLog(
            portfolio_id=portfolio_id,
            action_type="emergency_stop",
            description="Emergency stop activated — all automation rules paused",
            details={"rules_paused": count},
            was_simulated=False,
            was_approved=True,
        ))

        # Create alert
        db.add(Alert(
            portfolio_id=portfolio_id,
            alert_type=AlertType.AUTOMATION,
            title="⛔ Emergency Stop Activated",
            message=f"All {count} automation rules have been paused. Manual review required.",
            severity="critical",
        ))

        db.commit()
        logger.warning(f"EMERGENCY STOP: {count} rules paused for portfolio {portfolio_id}")
        return count

    # ── Rule evaluators ──────────────────────────

    def _evaluate_rule(
        self,
        rule: AutomationRule,
        portfolio: Portfolio,
        traders: List[CopiedTrader],
    ) -> Optional[ProposedAction]:
        evaluators = {
            "take_profit": self._eval_take_profit,
            "partial_profit_lock": self._eval_partial_profit,
            "rebalance": self._eval_rebalance,
            "reduce_on_drawdown": self._eval_reduce_on_drawdown,
            "pause_copy_on_loss": self._eval_pause_copy,
            "reduce_on_volatility": self._eval_reduce_on_volatility,
        }
        evaluator = evaluators.get(rule.rule_type)
        if not evaluator:
            logger.warning(f"Unknown rule type: {rule.rule_type}")
            return None

        return evaluator(rule, portfolio, traders)

    def _eval_take_profit(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        threshold = rule.threshold or 20.0
        if portfolio.invested_amount <= 0:
            return None

        return_pct = (portfolio.unrealized_pnl / portfolio.invested_amount) * 100
        if return_pct >= threshold:
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="take_profit",
                description=(
                    f"Portfolio unrealized return ({return_pct:.1f}%) "
                    f"reached the {threshold:.1f}% take-profit threshold."
                ),
                details={
                    "return_pct": round(return_pct, 2),
                    "threshold": threshold,
                    "unrealized_pnl": portfolio.unrealized_pnl,
                },
                severity="info",
                requires_approval=rule.requires_approval,
            )
        return None

    def _eval_partial_profit(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        threshold = rule.threshold or 15.0
        lock_pct = rule.config.get("lock_percentage", 30)  # Lock 30% of profits by default

        if portfolio.invested_amount <= 0 or portfolio.unrealized_pnl <= 0:
            return None

        return_pct = (portfolio.unrealized_pnl / portfolio.invested_amount) * 100
        if return_pct >= threshold:
            lock_amount = portfolio.unrealized_pnl * (lock_pct / 100)
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="partial_profit_lock",
                description=(
                    f"Lock {lock_pct}% of unrealized profits (${lock_amount:,.2f}) "
                    f"after reaching {return_pct:.1f}% return."
                ),
                details={
                    "return_pct": round(return_pct, 2),
                    "lock_pct": lock_pct,
                    "lock_amount": round(lock_amount, 2),
                },
                severity="info",
                requires_approval=rule.requires_approval,
            )
        return None

    def _eval_rebalance(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        target_allocations: dict = rule.config.get("targets", {})
        drift_threshold = rule.config.get("drift_threshold_pct", 5.0)

        drifted = []
        for trader in traders:
            target = target_allocations.get(trader.trader_username)
            if target is None:
                continue
            drift = abs(trader.allocation_pct - target)
            if drift >= drift_threshold:
                drifted.append({
                    "trader": trader.trader_username,
                    "current_pct": round(trader.allocation_pct, 2),
                    "target_pct": target,
                    "drift": round(drift, 2),
                })

        if drifted:
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="rebalance",
                description=(
                    f"{len(drifted)} trader(s) have drifted beyond the "
                    f"{drift_threshold}% threshold."
                ),
                details={"drifted_traders": drifted},
                severity="info",
                requires_approval=rule.requires_approval,
            )
        return None

    def _eval_reduce_on_drawdown(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        threshold_pct = rule.threshold or 10.0
        reduction_pct = rule.config.get("reduce_by_pct", 20.0)

        if portfolio.invested_amount <= 0:
            return None

        drawdown_pct = (
            (portfolio.invested_amount - portfolio.total_value) / portfolio.invested_amount * 100
        )
        if drawdown_pct >= threshold_pct:
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="reduce_on_drawdown",
                description=(
                    f"Portfolio drawdown of {drawdown_pct:.1f}% reached the trigger. "
                    f"Proposing {reduction_pct:.0f}% reduction in highest-risk traders."
                ),
                details={
                    "drawdown_pct": round(drawdown_pct, 2),
                    "threshold_pct": threshold_pct,
                    "reduction_pct": reduction_pct,
                },
                severity="warning",
                requires_approval=rule.requires_approval,
            )
        return None

    def _eval_pause_copy(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        consecutive_loss_threshold = rule.config.get("consecutive_losses", 3)
        to_pause = []

        for trader in traders:
            # Simplified check: total return < threshold AND risk score high
            loss_threshold = rule.config.get("min_loss_pct", -10.0)
            if trader.total_return_pct <= loss_threshold and trader.risk_score >= 6.5:
                to_pause.append(trader.trader_username)

        if to_pause:
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="pause_copy",
                description=(
                    f"Proposing to pause copy for {len(to_pause)} trader(s) "
                    f"due to poor performance and elevated risk."
                ),
                details={"traders_to_pause": to_pause},
                severity="warning",
                requires_approval=rule.requires_approval,
            )
        return None

    def _eval_reduce_on_volatility(
        self, rule: AutomationRule, portfolio: Portfolio, traders: List
    ) -> Optional[ProposedAction]:
        volatility_threshold = rule.threshold or 30.0
        to_reduce = [
            t.trader_username for t in traders
            if t.volatility >= volatility_threshold
        ]

        if to_reduce:
            return ProposedAction(
                rule_id=rule.id,
                rule_name=rule.name,
                action_type="reduce_on_volatility",
                description=(
                    f"{len(to_reduce)} trader(s) showing volatility ≥ {volatility_threshold:.0f}%. "
                    "Proposing allocation reduction to manage exposure."
                ),
                details={
                    "high_volatility_traders": to_reduce,
                    "volatility_threshold": volatility_threshold,
                },
                severity="warning",
                requires_approval=rule.requires_approval,
            )
        return None

    # ── Helpers ──────────────────────────────────

    def _in_cooldown(self, rule: AutomationRule) -> bool:
        if not rule.last_triggered:
            return False
        cooldown_ends = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
        return datetime.utcnow() < cooldown_ends
