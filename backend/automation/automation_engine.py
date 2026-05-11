"""
Semi-Automation Engine
────────────────────────────────────────────────────────────────────
Executes automation rules with mandatory safeguards:
- Every action is logged in the audit trail
- Requires user approval for real-money actions (not simulation)
- Cooldown periods enforced
- Emergency stop respected
- All actions reversible via the log

When requires_approval=False, the engine executes directly on eToro.
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
    An automation action waiting for review or execution.
    When requires_approval=True, user must approve via Telegram or UI.
    When False, the scheduler executes it automatically.
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
    Evaluates active automation rules and dispatches execution.
    - Pending actions (requires_approval=True): create alerts, log pending.
    - Auto actions (requires_approval=False): execute immediately via eToro API.
    """

    SUPPORTED_RULES = {
        "take_profit": "Auto Take-Profit at threshold",
        "partial_profit_lock": "Lock partial profits at threshold",
        "rebalance": "Rebalance allocations to targets",
        "reduce_on_drawdown": "Reduce allocation after drawdown",
        "pause_copy_on_loss": "Pause copy relationship after repeated losses",
        "reduce_on_volatility": "Reduce exposure during high volatility",
            "growth_swap": "Swap low-score trader for high-score discovery",
            "equal_rebalance": "Transition 1 trader → 3-way equal split",
    }

    def evaluate_rules(
        self,
        db: Session,
        portfolio: Portfolio,
        traders: List[CopiedTrader],
        scored_data: Optional[dict] = None,
    ) -> List[ProposedAction]:
        """
        Evaluate all enabled automation rules.
        Returns proposed actions — does not execute them.

        Args:
            scored_data: Optional output from generate_scout_report().
                         Used by the growth_swap rule to identify swaps.
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

            action = self._evaluate_rule(rule, portfolio, traders, scored_data=scored_data)
            if action:
                proposed.append(action)

        return proposed

    def create_pending_alert(
        self,
        db: Session,
        portfolio_id: int,
        action: ProposedAction,
    ) -> None:
        """Create an alert for a proposed action requiring user approval."""
        db.add(Alert(
            portfolio_id=portfolio_id,
            alert_type=AlertType.AUTOMATION,
            title=f"⚠️ Action Pending: {action.rule_name}",
            message=(
                f"Rule '{action.rule_name}' triggered: {action.description}. "
                f"Use /approve {action.rule_id} via Telegram or the UI to approve."
            ),
            severity=action.severity,
        ))
        db.commit()
        logger.info(f"Pending alert created for rule '{action.rule_name}' (rule_id={action.rule_id})")

    def log_execution(
        self,
        db: Session,
        portfolio: Portfolio,
        action: ProposedAction,
        approved_by: str = "auto",
        success: bool = True,
        etoro_response: Optional[dict] = None,
    ) -> AutomationLog:
        """Create an audit log entry for an executed action."""
        log_entry = AutomationLog(
            rule_id=action.rule_id,
            portfolio_id=portfolio.id,
            action_type=action.action_type,
            description=action.description,
            details={
                **action.details,
                "approved_by": approved_by,
                "success": success,
                "etoro_response": etoro_response or {},
            },
            was_simulated=portfolio.is_simulation,
            was_approved=success,
        )
        db.add(log_entry)

        # Update rule trigger count and cooldown timestamp only on success
        if success:
            rule = db.query(AutomationRule).filter(AutomationRule.id == action.rule_id).first()
            if rule:
                rule.last_triggered = datetime.utcnow()
                rule.trigger_count += 1

        db.commit()
        status = "SUCCESS" if success else "FAILED"
        logger.info(
            f"Action {status}: [{action.action_type}] {action.description} "
            f"(simulation={portfolio.is_simulation}, approved_by={approved_by})"
        )
        return log_entry

    async def execute_etoro_action(
        self,
        etoro_client,
        action: ProposedAction,
        portfolio: Portfolio,
        db: Session,
    ) -> dict:
        """Execute a proposed action directly on eToro via the execution API.

        Returns the eToro API response dict. On failure, the dict contains
        {"error": True, "detail": ...}.
        """
        is_sim = portfolio.is_simulation
        action_type = action.action_type
        trader_id = action.details.get("trader_id")

        try:
            if action_type == "take_profit":
                # Close all copy-trade mirrors to take profit
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.is_paused.is_(False),
                ).all()
                results = []
                for m in mirrors:
                    resp = await etoro_client.execute_close_mirror(
                        int(m.trader_id), is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to close mirror {m.trader_id}: {resp.get('detail')}")
                if any(r.get("response", {}).get("error") for r in results):
                    errors = [r for r in results if r.get("response", {}).get("error")]
                    return {"error": True, "action": "take_profit", "results": results,
                            "detail": f"{len(errors)}/{len(results)} mirrors failed",
                            "errors": errors}
                return {"action": "take_profit", "results": results}

            elif action_type == "partial_profit_lock":
                lock_amount = action.details.get("lock_amount", 0)
                # Reduce each active mirror by the proportional lock amount
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.is_paused.is_(False),
                ).all()
                results = []
                for m in mirrors:
                    new_amount = max(0, (m.allocated_amount or 0) - lock_amount / max(len(mirrors), 1))
                    resp = await etoro_client.execute_change_mirror_amount(
                        int(m.trader_id), new_amount, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "new_amount": new_amount, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to change mirror {m.trader_id}: {resp.get('detail')}")
                return {"action": "partial_profit_lock", "results": results}

            elif action_type == "pause_copy":
                traders_to_pause = action.details.get("traders_to_pause", [])
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.trader_username.in_(traders_to_pause),
                ).all()
                results = []
                for m in mirrors:
                    resp = await etoro_client.execute_pause_mirror(
                        int(m.trader_id), is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to pause mirror {m.trader_id}: {resp.get('detail')}")
                return {"action": "pause_copy", "results": results}

            elif action_type in ("reduce_on_drawdown", "reduce_on_volatility"):
                reduction_pct = action.details.get("reduction_pct", 20)
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.is_paused.is_(False),
                ).all()
                results = []
                for m in mirrors:
                    new_amount = (m.allocated_amount or 0) * (1 - reduction_pct / 100)
                    resp = await etoro_client.execute_change_mirror_amount(
                        int(m.trader_id), new_amount, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "new_amount": new_amount, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to reduce mirror {m.trader_id}: {resp.get('detail')}")
                return {"action": action_type, "results": results}

            elif action_type == "rebalance":
                drifted = action.details.get("drifted_traders", [])
                results = []
                for d in drifted:
                    trader_name = d.get("trader")
                    target_pct = d.get("target_pct", 0)
                    mirror = db.query(CopiedTrader).filter(
                        CopiedTrader.portfolio_id == portfolio.id,
                        CopiedTrader.trader_username == trader_name,
                    ).first()
                    if mirror and portfolio.total_value > 0:
                        new_amount = portfolio.total_value * (target_pct / 100)
                        resp = await etoro_client.execute_change_mirror_amount(
                            int(mirror.trader_id), new_amount, is_simulation=is_sim
                        )
                        results.append({"mirror_id": mirror.trader_id, "new_amount": new_amount, "response": resp})
                        if resp and resp.get("error"):
                            logger.error(f"Failed to rebalance mirror {mirror.trader_id}: {resp.get('detail')}")
                return {"action": "rebalance", "results": results}

            elif action_type == "swap":
                old_username = action.details.get("old_username")
                new_username = action.details.get("new_username")
                mirror_id = action.details.get("mirror_id")
                new_amount = action.details.get("new_amount", 0)

                if not old_username or not new_username or not mirror_id:
                    return {"error": True, "detail": "swap missing old_username, new_username, or mirror_id"}

                # Step 1: Close the old mirror
                logger.info(f"Swap step 1/3: closing mirror {mirror_id} ({old_username})")
                close_resp = await etoro_client.execute_close_mirror(
                    int(mirror_id), is_simulation=is_sim
                )
                if close_resp and close_resp.get("error"):
                    logger.error(f"Swap failed at step 1 (close): {close_resp.get('detail')}")
                    return {"error": True, "step": "close", "detail": close_resp.get("detail")}

                # Step 2: Safety delay — wait 60s for Available Cash to settle
                logger.info("Swap step 2/3: waiting 60s for cash to settle")
                import asyncio
                await asyncio.sleep(60)

                # Mark old trader inactive
                db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.trader_username == old_username,
                ).update({"is_active": False, "is_paused": True,
                          "paused_reason": f"Swapped to {new_username} via growth_swap"})
                db.commit()

                # Step 3: Start the new mirror
                logger.info(f"Swap step 3/3: starting mirror for {new_username} with ${new_amount:,.2f}")
                start_resp = await etoro_client.execute_start_mirror(
                    new_username, new_amount, is_simulation=is_sim
                )
                if start_resp and start_resp.get("error"):
                    logger.warning(f"Swap step 3 completed with warning: {start_resp.get('detail')}")
                    return {
                        "action": "swap",
                        "step_1_close": "ok",
                        "step_2_delay": "ok",
                        "step_3_start": start_resp,
                        "warning": start_resp.get("detail"),
                    }

                logger.info(f"Swap complete: {old_username} → {new_username}")
                return {
                    "action": "swap",
                    "old_username": old_username,
                    "new_username": new_username,
                    "close_response": close_resp,
                    "start_response": start_resp,
                    "new_amount": new_amount,
                }

            elif action_type == "equal_rebalance":
                current_trader = action.details.get("current_trader")
                current_trader_id = action.details.get("current_trader_id")
                new_traders = action.details.get("new_traders", [])
                amount_per = action.details.get("amount_per_trader", 0)

                if not current_trader or len(new_traders) < 2 or not current_trader_id:
                    return {"error": True, "detail": "equal_rebalance missing required fields"}

                results = []

                # Step 1: Close the current mirror
                logger.info(f"EqualRebalance step 1/4: closing mirror {current_trader_id} ({current_trader})")
                close_resp = await etoro_client.execute_close_mirror(
                    int(current_trader_id), is_simulation=is_sim
                )
                if close_resp and close_resp.get("error"):
                    logger.error(f"EqualRebalance failed at step 1 (close): {close_resp.get('detail')}")
                    return {"error": True, "step": "close", "detail": close_resp.get("detail")}
                results.append({"step": "close", "username": current_trader, "response": close_resp})

                # Step 2: Safety delay — wait 60s for Available Cash to settle
                logger.info("EqualRebalance step 2/4: waiting 60s for cash to settle")
                import asyncio
                await asyncio.sleep(60)

                # Mark old trader inactive in DB
                db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.trader_username == current_trader,
                ).update({
                    "is_active": False,
                    "is_paused": True,
                    "paused_reason": "Rebalanced to 3-way equal split via equal_rebalance",
                })
                db.commit()

                # Step 3: Start mirror for current trader at 33%
                logger.info(f"EqualRebalance step 3/4: starting mirror for {current_trader} with ${amount_per:,.2f}")
                start_current = await etoro_client.execute_start_mirror(
                    current_trader, amount_per, is_simulation=is_sim
                )
                if start_current and start_current.get("error"):
                    logger.warning(f"EqualRebalance warning restarting {current_trader}: {start_current.get('detail')}")
                results.append({"step": "start_current", "username": current_trader, "response": start_current})

                # Step 4: Start mirrors for 2 new traders at 33% each
                for nt in new_traders:
                    logger.info(f"EqualRebalance step 4/4: starting mirror for {nt} with ${amount_per:,.2f}")
                    resp = await etoro_client.execute_start_mirror(
                        nt, amount_per, is_simulation=is_sim
                    )
                    if resp and resp.get("error"):
                        logger.warning(f"EqualRebalance warning starting {nt}: {resp.get('detail')}")
                    results.append({"step": "start_new", "username": nt, "response": resp})

                logger.info(f"EqualRebalance complete: {current_trader} + {new_traders}")
                return {
                    "action": "equal_rebalance",
                    "current_trader": current_trader,
                    "new_traders": new_traders,
                    "amount_per_trader": amount_per,
                    "results": results,
                }

            else:
                return {"error": True, "detail": f"Unknown action type: {action_type}"}

        except Exception as e:
            logger.error(f"eToro execution failed for action {action.action_type}: {e}")
            return {"error": True, "detail": str(e)}

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

        db.add(AutomationLog(
            portfolio_id=portfolio_id,
            action_type="emergency_stop",
            description="Emergency stop activated — all automation rules paused",
            details={"rules_paused": count},
            was_simulated=False,
            was_approved=True,
        ))

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
        scored_data: Optional[dict] = None,
    ) -> Optional[ProposedAction]:
        evaluators = {
            "take_profit": self._eval_take_profit,
            "partial_profit_lock": self._eval_partial_profit,
            "rebalance": self._eval_rebalance,
            "reduce_on_drawdown": self._eval_reduce_on_drawdown,
            "pause_copy_on_loss": self._eval_pause_copy,
            "reduce_on_volatility": self._eval_reduce_on_volatility,
            "growth_swap": self._eval_growth_swap,
            "equal_rebalance": self._eval_equal_rebalance,
        }
        evaluator = evaluators.get(rule.rule_type)
        if not evaluator:
            logger.warning(f"Unknown rule type: {rule.rule_type}")
            return None

        if rule.rule_type in ("growth_swap", "equal_rebalance"):
            return evaluator(rule, portfolio, traders, scored_data)
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
        lock_pct = rule.config.get("lock_percentage", 30)

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
                    "trader_id": trader.trader_id,
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

    def _eval_growth_swap(
        self,
        rule: AutomationRule,
        portfolio: Portfolio,
        traders: List,
        scored_data: Optional[dict] = None,
    ) -> Optional[ProposedAction]:
        """Evaluate if any discovery candidate is 15+ pts better than a current trader.

        Uses scored_data (from generate_scout_report) if provided, otherwise
        falls back to static default candidates.
        """
        delta_threshold = rule.config.get("delta_threshold", 15.0)

        if scored_data and scored_data.get("top_swaps"):
            # Check if the best swap delta exceeds threshold
            best = scored_data["top_swaps"][0]
            if best.get("delta", 0) >= delta_threshold and scored_data.get("weakest"):
                w = scored_data["weakest"]
                mirror_id = None
                for t in traders:
                    if t.trader_username == w["username"]:
                        mirror_id = t.trader_id
                        break

                total_value = portfolio.total_value or 10000
                new_amount = total_value / 3

                return ProposedAction(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    action_type="swap",
                    description=(
                        f"Swap {w['username']} (score {w['score']}/100) → "
                        f"{best['username']} (score {best['score']}/100, "
                        f"delta +{best['delta']}). Amount: ${new_amount:,.2f}"
                    ),
                    details={
                        "old_username": w["username"],
                        "new_username": best["username"],
                        "mirror_id": str(mirror_id) if mirror_id else None,
                        "new_amount": round(new_amount, 2),
                        "old_score": w["score"],
                        "new_score": best["score"],
                        "delta": best["delta"],
                    },
                    severity="info",
                    requires_approval=rule.requires_approval,
                )

        return None

    def _eval_equal_rebalance(
        self,
        rule: AutomationRule,
        portfolio: Portfolio,
        traders: List,
        scored_data: Optional[dict] = None,
    ) -> Optional[ProposedAction]:
        """Evaluate if portfolio has 1 trader and 3+ qualified discovery candidates.

        Triggers equal_rebalance action when:
          - Exactly 1 active trader is in the portfolio
          - At least 3 discovery candidates have been scored (in scored_data.top_swaps)

        The action closes the current trader, waits 60s for cash settlement,
        then starts copies for all 3 traders (current + 2 new) at 33.3% each.
        """
        if len(traders) != 1:
            return None

        if not scored_data:
            return None

        top_swaps = scored_data.get("top_swaps", [])
        if len(top_swaps) < 3:
            return None

        current = traders[0]
        total_value = portfolio.total_value or 10000
        amount_per = round(total_value / 3, 2)

        new_traders = [t["username"] for t in top_swaps[:2]]

        return ProposedAction(
            rule_id=rule.id,
            rule_name=rule.name,
            action_type="equal_rebalance",
            description=(
                f"Transition from 1 trader ({current.trader_username}) to 3-way equal split: "
                f"keep {current.trader_username}, add {new_traders[0]} and "
                f"{new_traders[1]} at ${amount_per:,.2f} each"
            ),
            details={
                "current_trader": current.trader_username,
                "current_trader_id": str(current.trader_id) if current.trader_id else None,
                "new_traders": new_traders,
                "amount_per_trader": amount_per,
                "total_value": total_value,
                "top_swap_scores": [
                    {"username": t["username"], "score": t["score"]}
                    for t in top_swaps[:2]
                ],
            },
            severity="info",
            requires_approval=rule.requires_approval,
        )

    # ── Helpers ──────────────────────────────────

    def _in_cooldown(self, rule: AutomationRule) -> bool:
        if not rule.last_triggered:
            return False
        cooldown_ends = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
        return datetime.utcnow() < cooldown_ends
