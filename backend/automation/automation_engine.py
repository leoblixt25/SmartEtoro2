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

        rule = db.query(AutomationRule).filter(AutomationRule.id == action.rule_id).first()
        if rule:
            if success:
                rule.last_triggered = datetime.utcnow()
                rule.trigger_count += 1
            else:
                # On failure, set a 5-minute cooldown to avoid spamming eToro API.
                # _in_cooldown checks: last_triggered + cooldown_hours > now.
                # Setting last_triggered = now - cooldown_hours + 5min gives exactly 5 min of cooldown.
                rule.last_triggered = datetime.utcnow() - timedelta(hours=rule.cooldown_hours) + timedelta(minutes=5)

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

        Tracks success_count for every sub-action. If zero sub-actions succeed,
        the overall result is marked as FAILED with error=True.
        """
        is_sim = portfolio.is_simulation
        action_type = action.action_type
        trader_id = action.details.get("trader_id")

        def _count_successes(results: list, resp_key: str = "response") -> int:
            """Count how many individual actions succeeded."""
            count = 0
            for r in results:
                resp = r.get(resp_key, {}) if isinstance(r, dict) else {}
                if isinstance(resp, dict) and not resp.get("error"):
                    count += 1
            return count

        def _is_exec_result_successful(resp) -> bool:
            """Check if an individual execution response is successful."""
            if resp is None:
                return False
            if isinstance(resp, dict):
                return not resp.get("error", False)
            return True

        try:
            if action_type == "take_profit":
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.is_paused.is_(False),
                ).all()
                results = []
                for m in mirrors:
                    mirror_id = int(m.trader_id) if m.trader_id and m.trader_id.isdigit() and int(m.trader_id) > 0 else None
                    if mirror_id is None:
                        logger.warning(f"Skipping mirror for {m.trader_username}: invalid trader_id={m.trader_id}. Run /sync first.")
                        results.append({"mirror_id": m.trader_id, "skipped": True,
                                        "detail": "Invalid mirror ID — run /sync first"})
                        continue
                    resp = await etoro_client.execute_close_mirror(
                        mirror_id, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to close mirror {m.trader_id}: {resp.get('detail')}")
                success_count = _count_successes(results)
                if success_count == 0 and len(results) > 0:
                    return {"error": True, "action": "take_profit", "results": results,
                            "detail": "All mirror close operations failed",
                            "success_count": 0, "total": len(results)}
                return {"action": "take_profit", "results": results,
                        "success_count": success_count, "total": len(results)}

            elif action_type == "partial_profit_lock":
                lock_amount = action.details.get("lock_amount", 0)
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.is_active.is_(True),
                    CopiedTrader.is_paused.is_(False),
                ).all()
                results = []
                for m in mirrors:
                    new_amount = max(0, (m.allocated_amount or 0) - lock_amount / max(len(mirrors), 1))
                    mirror_id = int(m.trader_id) if m.trader_id and str(m.trader_id).isdigit() and int(m.trader_id) > 0 else None
                    if mirror_id is None:
                        logger.warning(f"Skipping mirror for {m.trader_username}: invalid trader_id={m.trader_id}. Run /sync first.")
                        results.append({"mirror_id": m.trader_id, "skipped": True, "detail": "Invalid mirror ID"})
                        continue
                    resp = await etoro_client.execute_change_mirror_amount(
                        mirror_id, new_amount, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "new_amount": new_amount, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to change mirror {m.trader_id}: {resp.get('detail')}")
                success_count = _count_successes(results)
                if success_count == 0 and len(results) > 0:
                    return {"error": True, "action": "partial_profit_lock", "results": results,
                            "detail": "All reduce-amount operations failed",
                            "success_count": 0, "total": len(results)}
                return {"action": "partial_profit_lock", "results": results,
                        "success_count": success_count, "total": len(results)}

            elif action_type == "pause_copy":
                traders_to_pause = action.details.get("traders_to_pause", [])
                mirrors = db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.trader_username.in_(traders_to_pause),
                ).all()
                results = []
                for m in mirrors:
                    mirror_id = int(m.trader_id) if m.trader_id and str(m.trader_id).isdigit() and int(m.trader_id) > 0 else None
                    if mirror_id is None:
                        logger.warning(f"Skipping pause for {m.trader_username}: invalid trader_id={m.trader_id}. Run /sync first.")
                        results.append({"mirror_id": m.trader_id, "skipped": True, "detail": "Invalid mirror ID"})
                        continue
                    resp = await etoro_client.execute_pause_mirror(
                        mirror_id, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to pause mirror {m.trader_id}: {resp.get('detail')}")
                success_count = _count_successes(results)
                if success_count == 0 and len(results) > 0:
                    return {"error": True, "action": "pause_copy", "results": results,
                            "detail": "All pause operations failed",
                            "success_count": 0, "total": len(results)}
                return {"action": "pause_copy", "results": results,
                        "success_count": success_count, "total": len(results)}

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
                    mirror_id = int(m.trader_id) if m.trader_id and str(m.trader_id).isdigit() and int(m.trader_id) > 0 else None
                    if mirror_id is None:
                        logger.warning(f"Skipping reduction for {m.trader_username}: invalid trader_id={m.trader_id}. Run /sync first.")
                        results.append({"mirror_id": m.trader_id, "skipped": True, "detail": "Invalid mirror ID"})
                        continue
                    resp = await etoro_client.execute_change_mirror_amount(
                        mirror_id, new_amount, is_simulation=is_sim
                    )
                    results.append({"mirror_id": m.trader_id, "new_amount": new_amount, "response": resp})
                    if resp and resp.get("error"):
                        logger.error(f"Failed to reduce mirror {m.trader_id}: {resp.get('detail')}")
                success_count = _count_successes(results)
                if success_count == 0 and len(results) > 0:
                    return {"error": True, "action": action_type, "results": results,
                            "detail": "All reduction operations failed",
                            "success_count": 0, "total": len(results)}
                return {"action": action_type, "results": results,
                        "success_count": success_count, "total": len(results)}

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
                        rebal_id = int(mirror.trader_id) if mirror.trader_id and str(mirror.trader_id).isdigit() and int(mirror.trader_id) > 0 else None
                        if rebal_id is None:
                            logger.warning(f"Skipping rebalance for {trader_name}: invalid trader_id={mirror.trader_id}. Run /sync first.")
                            results.append({"mirror_id": mirror.trader_id, "skipped": True, "detail": "Invalid mirror ID"})
                            continue
                        resp = await etoro_client.execute_change_mirror_amount(
                            rebal_id, new_amount, is_simulation=is_sim
                        )
                        results.append({"mirror_id": mirror.trader_id, "new_amount": new_amount, "response": resp})
                        if resp and resp.get("error"):
                            logger.error(f"Failed to rebalance mirror {mirror.trader_id}: {resp.get('detail')}")
                success_count = _count_successes(results)
                if success_count == 0 and len(results) > 0:
                    return {"error": True, "action": "rebalance", "results": results,
                            "detail": "All rebalance operations failed",
                            "success_count": 0, "total": len(results)}
                return {"action": "rebalance", "results": results,
                        "success_count": success_count, "total": len(results)}

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
                close_ok = _is_exec_result_successful(close_resp)
                if not close_ok:
                    logger.warning(f"Swap step 1 (close) failed: {close_resp.get('detail') if close_resp else 'no response'}")
                    # Non-fatal — mark trader inactive in DB anyway and skip steps 2-3
                    db.query(CopiedTrader).filter(
                        CopiedTrader.portfolio_id == portfolio.id,
                        CopiedTrader.trader_username == old_username,
                    ).update({"is_active": False, "is_paused": True,
                              "paused_reason": f"Swap to {new_username} — close failed, needs manual cleanup"})
                    db.commit()
                    return {"error": True, "step": "close",
                            "detail": close_resp.get("detail") if close_resp else "Close mirror returned no response",
                            "action": "swap"}

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
                start_ok = _is_exec_result_successful(start_resp)
                if not start_ok:
                    logger.warning(f"Swap step 3 (start) failed: {start_resp.get('detail') if start_resp else 'no response'}")
                    return {
                        "error": True,
                        "action": "swap",
                        "step_1_close": close_resp,
                        "step_2_delay": "ok",
                        "step_3_start": start_resp,
                        "detail": f"Closed {old_username} but could not start {new_username}: {start_resp.get('detail') if start_resp else 'unknown'}",
                        "close_ok": True,
                        "start_ok": False,
                    }

                logger.info(f"Swap complete: {old_username} → {new_username}")
                return {
                    "action": "swap",
                    "old_username": old_username,
                    "new_username": new_username,
                    "close_response": close_resp,
                    "start_response": start_resp,
                    "new_amount": new_amount,
                    "success_count": 2,
                    "total": 2,
                }

            elif action_type == "equal_rebalance":
                current_trader = action.details.get("current_trader")
                current_trader_id = action.details.get("current_trader_id")
                new_traders = action.details.get("new_traders", [])
                replacement_traders = action.details.get("replacement_traders")
                amount_per = action.details.get("amount_per_trader", 0)

                if not current_trader or not current_trader_id:
                    return {"error": True, "detail": "equal_rebalance missing required fields"}

                if replacement_traders:
                    all_targets = replacement_traders
                else:
                    if len(new_traders) < 2:
                        return {"error": True, "detail": "equal_rebalance missing new_traders"}
                    all_targets = [current_trader] + new_traders

                results = []
                close_ok = False
                start_successes = 0

                # Step 1: Close the current mirror
                logger.info(f"EqualRebalance step 1/4: closing mirror {current_trader_id} ({current_trader})")
                close_resp = await etoro_client.execute_close_mirror(
                    int(current_trader_id), is_simulation=is_sim
                )
                if close_resp and not close_resp.get("error"):
                    close_ok = True
                else:
                    logger.warning(f"EqualRebalance close failed (continuing): {close_resp.get('detail') if close_resp else 'no response'}")
                results.append({"step": "close", "username": current_trader, "response": close_resp})

                # Step 2: Safety delay — wait 60s for Available Cash to settle
                logger.info("EqualRebalance step 2/4: waiting 60s for cash to settle")
                import asyncio
                await asyncio.sleep(60)

                # Mark old trader inactive in DB regardless of close success
                db.query(CopiedTrader).filter(
                    CopiedTrader.portfolio_id == portfolio.id,
                    CopiedTrader.trader_username == current_trader,
                ).update({
                    "is_active": False,
                    "is_paused": True,
                    "paused_reason": "Rebalanced to 3-way equal split via equal_rebalance",
                })
                db.commit()

                # Step 3+4: Start ALL target traders at 33.3% each
                for target in all_targets:
                    logger.info(f"EqualRebalance step 3/4: starting mirror for {target} with ${amount_per:,.2f}")
                    resp = await etoro_client.execute_start_mirror(
                        target, amount_per, is_simulation=is_sim
                    )
                    if resp and not resp.get("error"):
                        start_successes += 1
                    else:
                        logger.warning(f"EqualRebalance warning starting {target}: {resp.get('detail') if resp else 'no response'}")
                    results.append({"step": "start", "username": target, "response": resp})

                total_ops = 1 + len(all_targets)  # close + starts
                if start_successes == 0:
                    return {
                        "error": True,
                        "action": "equal_rebalance",
                        "current_trader": current_trader,
                        "new_traders": new_traders,
                        "replacement_traders": replacement_traders,
                        "amount_per_trader": amount_per,
                        "results": results,
                        "detail": f"Equal rebalance failed: closed={close_ok}, 0/{len(all_targets)} new mirrors started",
                        "close_ok": close_ok,
                        "start_successes": start_successes,
                        "total_attempts": len(all_targets),
                    }

                logger.info(f"EqualRebalance complete: targets={all_targets}, {start_successes}/{len(all_targets)} started")
                return {
                    "action": "equal_rebalance",
                    "current_trader": current_trader,
                    "new_traders": new_traders,
                    "replacement_traders": replacement_traders,
                    "amount_per_trader": amount_per,
                    "results": results,
                    "close_ok": close_ok,
                    "success_count": start_successes,
                    "total": len(all_targets),
                }

            else:
                return {"error": True, "detail": f"Unknown action type: {action_type}"}

        except Exception as e:
            logger.error(f"eToro execution failed for action {action.action_type}: {e}")
            return {"error": True, "detail": str(e)}

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
            if (t.volatility or 0.0) >= volatility_threshold
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

                _w_score = w.get("final_score") or w.get("score", 0)
                _b_score = best.get("final_score") or best.get("score", 0)
                return ProposedAction(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    action_type="swap",
                    description=(
                        f"Swap {w['username']} (score {_w_score}/100) → "
                        f"{best['username']} (score {_b_score}/100, "
                        f"delta +{best.get('delta', 0)}). Amount: ${new_amount:,.2f}"
                    ),
                    details={
                        "old_username": w["username"],
                        "new_username": best["username"],
                        "mirror_id": str(mirror_id) if mirror_id else None,
                        "new_amount": round(new_amount, 2),
                        "old_score": _w_score,
                        "new_score": _b_score,
                        "delta": best.get("delta", 0),
                    },
                    severity="info",
                    requires_approval=False,
                )

        return None

    REBALANCE_SEED_LIST = ["JeppeKirkBonde", "CPHequities", "Jaynemesis"]

    def _eval_equal_rebalance(
        self,
        rule: Optional[AutomationRule],
        portfolio: Portfolio,
        traders: List,
        scored_data: Optional[dict] = None,
    ) -> Optional[ProposedAction]:
        """Evaluate if portfolio has 1 trader and 3+ qualified candidates.

        Two trigger paths:
          1. Scout-triggered:  scored_data has 3+ top_swaps → use discovery picks
          2. Risk-triggered:   scored_data is None/missing → use REBALANCE_SEED_LIST

        Both paths close the current trader, wait 60s for cash settlement,
        then start all 3 traders at 33.3% each (risk path replaces ALL three
        with the seed list; scout path keeps current + 2 new).
        """
        if len(traders) != 1:
            return None

        current = traders[0]
        total_value = portfolio.total_value or 10000
        amount_per = round(total_value / 3, 2)

        top_swaps = (scored_data or {}).get("top_swaps", []) if scored_data else []

        # rule can be None (called from risk bridge) — use safe defaults
        rule_id = rule.id if rule else 0
        rule_name = rule.name if rule else "equal_rebalance"

        if len(top_swaps) >= 3:
            # Path 1: Scout-triggered — keep current + 2 new from discovery
            new_traders = [t["username"] for t in top_swaps[:2]]
            return ProposedAction(
                rule_id=rule_id,
                rule_name=rule_name,
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
                        {"username": t["username"], "score": t.get("final_score") or t.get("score", 0)}
                        for t in top_swaps[:2]
                    ],
                },
                severity="info",
                requires_approval=False,
            )

        # Path 2: Risk-triggered — replace ALL 3 from REBALANCE_SEED_LIST
        seed_list = self.REBALANCE_SEED_LIST[:3]
        logger.info(
            f"Risk-triggered rebalance: closing {current.trader_username}, "
            f"splitting into {seed_list} at ${amount_per:,.2f} each"
        )
        return ProposedAction(
            rule_id=rule_id,
            rule_name=rule_name,
            action_type="equal_rebalance",
            description=(
                f"Risk-triggered rebalance: close {current.trader_username}, "
                f"split into {', '.join(seed_list)} at ${amount_per:,.2f} each"
            ),
            details={
                "current_trader": current.trader_username,
                "current_trader_id": str(current.trader_id) if current.trader_id else None,
                "amount_per_trader": amount_per,
                "total_value": total_value,
                "replacement_traders": seed_list,
                "trigger": "risk_insufficient_diversification",
            },
            severity="warning",
            requires_approval=False,
        )

    def reset_cooldowns(self, db: Session, portfolio_id: int) -> int:
        """Clear last_triggered for all rules in a portfolio — 0 cooldown."""
        rules = (
            db.query(AutomationRule)
            .filter(AutomationRule.portfolio_id == portfolio_id)
            .all()
        )
        count = 0
        for rule in rules:
            if rule.last_triggered is not None:
                rule.last_triggered = None
                count += 1
        if count:
            db.commit()
            logger.info(f"Reset cooldown for {count} rules in portfolio {portfolio_id}")
        return count

    # ── Helpers ──────────────────────────────────

    def _in_cooldown(self, rule: AutomationRule) -> bool:
        if not rule.last_triggered:
            return False
        cooldown_ends = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
        return datetime.utcnow() < cooldown_ends
