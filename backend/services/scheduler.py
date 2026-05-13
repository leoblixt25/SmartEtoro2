"""
Background Scheduler
────────────────────────────────────────────────────────────────────
Runs periodic tasks: risk checks, analytics refresh, daily snapshots.
Uses APScheduler for simple, reliable job scheduling.
"""

from __future__ import annotations
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed — background tasks disabled")


class SchedulerService:
    """Wraps APScheduler for periodic background jobs."""

    def __init__(self):
        self._scheduler: Optional[object] = None

    def start(self):
        if not SCHEDULER_AVAILABLE:
            return

        self._scheduler = AsyncIOScheduler()

        # Common kwargs to prevent overlaps on all interval jobs
        interval_kwargs = {
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 120,
        }

        # Self-ping keep-alive every 4 minutes (prevents Render free-tier spin-down)
        self._scheduler.add_job(
            self._keep_alive_job,
            IntervalTrigger(minutes=4),
            id="keep_alive",
            name="Render Keep-Alive Ping",
            **interval_kwargs,
        )

        # eToro data sync every 5 minutes
        self._scheduler.add_job(
            self._etoro_sync_job,
            IntervalTrigger(minutes=5),
            id="etoro_sync",
            name="eToro Portfolio Sync",
            **interval_kwargs,
        )

        # Automation rule evaluation every 2 minutes (was 1m — increased to
        # prevent overlap with 60s rebalance cash-settlement wait)
        self._scheduler.add_job(
            self._automation_eval_job,
            IntervalTrigger(minutes=2),
            id="automation_eval",
            name="Automation Rule Evaluation",
            **interval_kwargs,
        )

        # Risk check every 15 minutes
        self._scheduler.add_job(
            self._risk_check_job,
            IntervalTrigger(minutes=15),
            id="risk_check",
            name="Portfolio Risk Check",
            **interval_kwargs,
        )

        # Daily portfolio snapshot at midnight
        self._scheduler.add_job(
            self._daily_snapshot_job,
            CronTrigger(hour=0, minute=5),
            id="daily_snapshot",
            name="Daily Portfolio Snapshot",
        )

        # Weekly AI summary every Sunday at 8am
        self._scheduler.add_job(
            self._weekly_summary_job,
            CronTrigger(day_of_week="sun", hour=8, minute=0),
            id="weekly_summary",
            name="Weekly AI Summary",
        )

        # AI Market Scout evaluation every 6 hours
        self._scheduler.add_job(
            self._market_scout_job,
            CronTrigger(hour="*/6", minute=15),
            id="market_scout",
            name="AI Market Scout Evaluation",
        )

        self._scheduler.start()
        logger.info("Scheduler started with 7 jobs (overlap prevention enabled)")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    # ── Job implementations ──────────────────────

    async def _keep_alive_job(self):
        """Self-ping to keep the Render web service awake.

        Render free tier spins down after 15 min of inactivity.
        This pings our own /health endpoint every 4 minutes.
        """
        import httpx
        try:
            base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/health")
                logger.debug(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Keep-alive ping skipped (expected on local dev): {e}")

    async def _automation_eval_job(self):
        """Evaluate all enabled automation rules and dispatch execution.

        - requires_approval=True  → creates a pending alert for user review
        - requires_approval=False → executes directly on eToro, logs success/failure
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.automation.automation_engine import AutomationEngine
        from backend.services.etoro_service import EToroSyncService

        engine = AutomationEngine()
        try:
            with db_session() as db:
                portfolios = db.query(Portfolio).all()

                # Fetch discovery candidates for growth_swap evaluation
                scored_data = None
                try:
                    from backend.services.market_data import discover_top_traders, _default_trader_candidates
                    from backend.ai.scoring_engine import generate_scout_report
                    from backend.services.market_data import get_current_holdings
                    discovery = await discover_top_traders()
                    # Force fallback if API returned fewer than 3 candidates
                    if not discovery or len(discovery) < 3:
                        logger.warning("Discovery returned < 3 candidates — forcing static fallback")
                        discovery = _default_trader_candidates()
                    if discovery and portfolios:
                        holdings = get_current_holdings(db, portfolios[0].id)
                        if holdings:
                            scored_data = generate_scout_report(holdings, discovery)
                except Exception as e:
                    logger.info(f"Scout data unavailable for rule eval, using fallback (non-fatal): {e}")
                    try:
                        from backend.services.market_data import _default_trader_candidates
                        from backend.ai.scoring_engine import generate_scout_report
                        from backend.services.market_data import get_current_holdings
                        discovery = _default_trader_candidates()
                        if discovery and portfolios:
                            holdings = get_current_holdings(db, portfolios[0].id)
                            if holdings:
                                scored_data = generate_scout_report(holdings, discovery)
                    except Exception as fallback_err:
                        logger.warning("Scout fallback also failed: %s", fallback_err)

                for portfolio in portfolios:
                    traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]
                    actions = engine.evaluate_rules(db, portfolio, traders, scored_data=scored_data)
                    for action in actions:
                        if action.requires_approval:
                            engine.create_pending_alert(db, portfolio.id, action)
                            logger.info(f"Pending approval: '{action.rule_name}' — {action.description}")
                        else:
                            sync_service = EToroSyncService()
                            etoro_response = await engine.execute_etoro_action(
                                sync_service.client, action, portfolio, db
                            )
                            # Validate real success: check error flag AND success_count
                            has_error = (etoro_response or {}).get("error", False)
                            success_count = (etoro_response or {}).get("success_count", None)
                            total = (etoro_response or {}).get("total", None)
                            # success = no error AND (no count metric OR at least 1 succeeded OR nothing to act on)
                            if has_error:
                                success = False
                            elif success_count is not None and total is not None:
                                # 0/0 = nothing to do (no active traders) — not a failure
                                success = success_count > 0 or total == 0
                            else:
                                success = True  # legacy actions without success_count
                            engine.log_execution(
                                db, portfolio, action,
                                approved_by="auto",
                                success=success,
                                etoro_response=etoro_response,
                            )
                            if success:
                                detail = etoro_response.get("action", action.action_type)
                                count_info = f" ({etoro_response.get('success_count', '?')}/{etoro_response.get('total', '?')} succeeded)" if "success_count" in (etoro_response or {}) else ""
                                logger.info(f"Auto-executed rule '{action.rule_name}': {detail}{count_info}")
                            else:
                                err_detail = (etoro_response or {}).get("detail", "No details")
                                logger.error(f"Auto-execution FAILED for rule '{action.rule_name}': {err_detail}")
                                # Notify Telegram on failure
                                try:
                                    from backend.services.telegram_service import TelegramBot
                                    bot = TelegramBot()
                                    if bot.enabled:
                                        await bot.send_message(
                                            f"❌ <b>Automation Failed</b>\n\n"
                                            f"Rule: <b>{action.rule_name}</b>\n"
                                            f"Action: {action.action_type}\n"
                                            f"Error: {err_detail}",
                                            show_keyboard=True,
                                        )
                                except Exception as tg_err:
                                    logger.warning(f"Failed to send Telegram failure notification: {tg_err}")

                # ── Risk → Auto-Rebalance Bridge ──────────────────────────
                # Check for insufficient_diversification violations and
                # immediately trigger a seed-list rebalance without waiting
                # for the 15-min risk check job cycle.
                try:
                    from backend.risk.risk_engine import RiskEngine
                    risk_engine = RiskEngine()
                    for portfolio in portfolios:
                        from backend.database.models import RiskSettings
                        settings = db.query(RiskSettings).filter(
                            RiskSettings.portfolio_id == portfolio.id
                        ).first()
                        violations = risk_engine.check_all(db, portfolio, settings)
                        low_div = [v for v in violations
                                   if v.violation_type == "insufficient_diversification"]
                        active_traders = [t for t in portfolio.copied_traders
                                          if t.is_active and not t.is_paused]
                        if low_div and len(active_traders) == 1:
                            # Bridge: create an equal_rebalance action with the seed list
                            logger.warning(
                                f"LOW DIVERSIFICATION + 1 trader detected — "
                                f"initiating seed-list rebalance for portfolio {portfolio.id}"
                            )
                            # Look up (or auto-create) the equal_rebalance rule
                            # so log_execution doesn't fail with FK violation.
                            from backend.database.models import AutomationRule, AutomationStatus
                            eq_rule = db.query(AutomationRule).filter(
                                AutomationRule.portfolio_id == portfolio.id,
                                AutomationRule.rule_type == "equal_rebalance",
                            ).first()
                            if not eq_rule:
                                eq_rule = AutomationRule(
                                    portfolio_id=portfolio.id,
                                    name="Risk-Bridge Equal Rebalance",
                                    rule_type="equal_rebalance",
                                    status=AutomationStatus.ENABLED,
                                    threshold=0,
                                    cooldown_hours=0,
                                    requires_approval=False,
                                    config={},
                                )
                                db.add(eq_rule)
                                db.commit()
                                logger.info(
                                    f"Auto-created equal_rebalance rule for risk bridge "
                                    f"(portfolio {portfolio.id})"
                                )
                            seed_action = engine._eval_equal_rebalance(
                                eq_rule, portfolio, active_traders, scored_data=None
                            )
                            if seed_action:
                                sync_service = EToroSyncService()
                                etoro_response = await engine.execute_etoro_action(
                                    sync_service.client, seed_action, portfolio, db
                                )
                                has_error = (etoro_response or {}).get("error", False)
                                success_count = (etoro_response or {}).get("success_count", None)
                                total = (etoro_response or {}).get("total", None)
                                if has_error:
                                    success = False
                                elif success_count is not None and total is not None:
                                    success = success_count > 0 or total == 0
                                else:
                                    success = True
                                engine.log_execution(
                                    db, portfolio, seed_action,
                                    approved_by="risk_bridge",
                                    success=success,
                                    etoro_response=etoro_response,
                                )
                                if success:
                                    count_info = f" ({etoro_response.get('success_count', '?')}/{etoro_response.get('total', '?')} started)" if "success_count" in (etoro_response or {}) else ""
                                    logger.info(
                                        f"Risk → Rebalance bridge EXECUTED: "
                                        f"{seed_action.description}{count_info}"
                                    )
                                else:
                                    err_detail = (etoro_response or {}).get("detail", "No details")
                                    logger.error(
                                        f"Risk → Rebalance bridge FAILED: "
                                        f"{err_detail}"
                                    )
                                    try:
                                        from backend.services.telegram_service import TelegramBot
                                        bot = TelegramBot()
                                        if bot.enabled:
                                            await bot.send_message(
                                                f"❌ <b>Risk Bridge Failed</b>\n\n"
                                                f"Error: {err_detail}",
                                                show_keyboard=True,
                                            )
                                    except Exception as tg_err:
                                        logger.warning(f"Failed to send Telegram notification: {tg_err}")
                except Exception as e:
                    logger.error(f"Risk → Rebalance bridge error: {e}")
        except Exception as e:
            logger.error(f"Automation eval job failed: {e}")

    async def _risk_check_job(self):
        """Run risk checks for all active portfolios."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, RiskSettings
        from backend.risk.risk_engine import RiskEngine

        engine = RiskEngine()
        try:
            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    settings = db.query(RiskSettings).filter(
                        RiskSettings.portfolio_id == portfolio.id
                    ).first()
                    violations = engine.check_all(db, portfolio, settings)
                    if violations:
                        engine.violations_to_alerts(
                            db, portfolio.id, violations)
                        logger.info(
                            f"Risk check: {len(violations)} violations for portfolio {portfolio.id}"
                        )
        except Exception as e:
            logger.error(f"Risk check job failed: {e}")

    async def _daily_snapshot_job(self):
        """Take daily portfolio value snapshot."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, PortfolioSnapshot

        try:
            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    snapshot = PortfolioSnapshot(
                        portfolio_id=portfolio.id,
                        total_value=portfolio.total_value,
                        daily_pnl=portfolio.daily_pnl,
                        unrealized_pnl=portfolio.unrealized_pnl,
                        health_score=portfolio.health_score,
                        recorded_at=datetime.utcnow(),
                    )
                    db.add(snapshot)
                logger.info(
                    f"Daily snapshots taken for {len(portfolios)} portfolios")
        except Exception as e:
            logger.error(f"Daily snapshot job failed: {e}")

    async def _weekly_summary_job(self):
        """Generate and send weekly AI summaries."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader, Alert, AlertType
        from backend.ai.analysis_engine import AIAnalysisEngine

        engine = AIAnalysisEngine()
        try:
            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    traders = db.query(CopiedTrader).filter(
                        CopiedTrader.portfolio_id == portfolio.id,
                        CopiedTrader.is_active.is_(True),
                    ).all()
                    result = await engine.generate_weekly_summary(portfolio, traders)
                    summary = result.get(
                        "weekly_summary", "Weekly summary unavailable.")

                    db.add(Alert(
                        portfolio_id=portfolio.id,
                        alert_type=AlertType.WEEKLY_SUMMARY,
                        title="📊 Weekly Portfolio Summary",
                        message=summary,
                        severity="info",
                    ))
                logger.info(
                    f"Weekly summaries generated for {len(portfolios)} portfolios")
        except Exception as e:
            logger.error(f"Weekly summary job failed: {e}")

    async def _market_scout_job(self):
        """Run Growth Scout — evaluate portfolio using deterministic scoring.

        Uses ScoutRunner from scout/trader_scout.py (shared with Telegram /scout).
        AI narrator is optional — pure math is primary.
        Never executes trades — only reports findings via Alerts + Telegram.
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, Alert, AlertType
        from backend.services.market_data import get_current_holdings, fetch_market_news, discover_top_traders
        from backend.scout.trader_scout import get_scout_runner
        from backend.services.rebalance_service import calculate_rebalance_orders

        try:
            news = await fetch_market_news()
            candidates = await discover_top_traders()

            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    holdings = get_current_holdings(db, portfolio.id)
                    if not holdings:
                        logger.info("Skipping market scout — no active traders for portfolio %d", portfolio.id)
                        continue

                    runner = get_scout_runner()
                    report = await runner.run(holdings, candidates)

                    holdings_ranked = report.get("holdings_ranked", [])
                    top_swaps = report.get("top_swaps", [])
                    weakest = report.get("weakest")
                    avg_score = report.get("avg_score", 0)

                    # ── Determine if action is needed ──
                    action_required = bool(weakest and weakest["final_score"] < 50 and top_swaps)
                    flagged_user = weakest["username"] if weakest else None

                    # ── AI narrator (optional) ──
                    ai_summary = None
                    try:
                        from backend.ai.groq_scout import GroqScout
                        groq = GroqScout()
                        if groq.enabled and holdings_ranked:
                            import asyncio
                            _best = top_swaps[0]["username"] if top_swaps else "none"
                            prompt = (
                                "Summarise this portfolio scout report in ONE plain-English sentence "
                                "(max 20 words). No formatting, no JSON.\n\n"
                                f"Weakest trader: {weakest['username']} "
                                f"(score {weakest['final_score']}/100).\n"
                                f"Best swap: {_best}.\n"
                                f"Portfolio avg score: {avg_score}/100."
                            )
                            def _call():
                                return groq._ensure_client().chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    temperature=0,
                                    max_tokens=40,
                                )
                            resp = await asyncio.to_thread(_call)
                            if resp and resp.choices:
                                ai_summary = resp.choices[0].message.content.strip()
                    except Exception as e:
                        logger.info("AI narrator unavailable (non‑fatal): %s", e)

                    # ── Build alert ──
                    if action_required:
                        title = f"⚠️ Growth Scout Alert: {flagged_user} ({weakest['final_score']}/100)"
                        message_parts = [
                            f"Weakest link in portfolio: {flagged_user}",
                            f"Score: {weakest['final_score']}/100",
                        ]
                        if top_swaps:
                            _ts = top_swaps[0]
                            message_parts.append(
                                f"Recommended swap: {_ts['username']} ({_ts['final_score']}/100)"
                            )
                        severity = "warning"
                    else:
                        title = f"✅ Growth Scout: All Clear (avg {avg_score}/100)"
                        message_parts = [f"Portfolio avg score: {avg_score}/100."]
                        severity = "info"

                    if ai_summary:
                        message_parts.append(f"\n🤖 {ai_summary}")
                    message = "\n".join(message_parts)

                    # ── Allocation plan ──
                    top3 = holdings_ranked[:3]
                    if top3:
                        eq_pct = round(100 / len(top3), 1)
                        allocs = [{"username": t["username"], "allocation_pct": eq_pct} for t in top3]
                        current_positions = [
                            {"username": h["username"],
                             "current_value": h.get("allocation_pct", 0) * 0.01 * (portfolio.total_value or 10000)}
                            for h in holdings
                        ]
                        orders = calculate_rebalance_orders(
                            portfolio.total_value or 0, current_positions,
                            {"target_portfolio": allocs}
                        )
                        alloc_lines = [f"• {a['username']} — {a['allocation_pct']}%" for a in allocs]
                        if orders.get("warnings"):
                            alloc_lines.extend([f"⚠️ {w}" for w in orders["warnings"]])
                        message += "\n\n📊 Allocation Plan:\n" + "\n".join(alloc_lines)
                        title += " + Allocation Plan"

                    db.add(Alert(
                        portfolio_id=portfolio.id,
                        alert_type=AlertType.AI_SCOUT,
                        title=title,
                        message=message,
                        severity=severity,
                    ))
                    db.commit()

                    # Send Telegram alert if action required
                    if action_required:
                        from backend.services.telegram_service import TelegramBot
                        bot = TelegramBot()
                        if bot.enabled and top_swaps:
                            msg = (
                                f"⚠️ <b>Growth Scout Alert</b>\n\n"
                                f"Weakest link: <b>{flagged_user}</b> "
                                f"(score {weakest['final_score']}/100)\n\n"
                                f"<b>Top swap:</b> {top_swaps[0]['username']} "
                                f"(score {top_swaps[0]['final_score']}/100)\n\n"
                                f"Reply <code>/swap {flagged_user} {top_swaps[0]['username']}</code>"
                            )
                            if ai_summary:
                                msg += f"\n\n🤖 <i>{ai_summary}</i>"
                            await bot.send_message(msg, show_keyboard=True)

                    logger.info(
                        "Growth scout %s portfolio %d",
                        "flagged" if action_required else "cleared",
                        portfolio.id,
                    )

        except Exception as e:
            logger.exception("Market scout job failed")

    async def _etoro_sync_job(self):
        """Sync portfolio data from eToro API."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.etoro_service import EToroSyncService

        sync_service = EToroSyncService()
        try:
            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    success = await sync_service.sync_portfolio_data(db, portfolio.id)
                    if success:
                        logger.info(
                            f"eToro sync successful for portfolio {portfolio.id}")
                    else:
                        logger.debug(
                            f"eToro sync skipped for portfolio {portfolio.id}")
        except Exception as e:
            logger.error(f"eToro sync job failed: {e}")
