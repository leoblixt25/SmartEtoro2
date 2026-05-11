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

        # Self-ping keep-alive every 4 minutes (prevents Render free-tier spin-down)
        self._scheduler.add_job(
            self._keep_alive_job,
            IntervalTrigger(minutes=4),
            id="keep_alive",
            name="Render Keep-Alive Ping",
        )

        # eToro data sync every 5 minutes
        self._scheduler.add_job(
            self._etoro_sync_job,
            IntervalTrigger(minutes=5),
            id="etoro_sync",
            name="eToro Portfolio Sync",
        )

        # Automation rule evaluation every 10 minutes
        self._scheduler.add_job(
            self._automation_eval_job,
            IntervalTrigger(minutes=10),
            id="automation_eval",
            name="Automation Rule Evaluation",
        )

        # Risk check every 15 minutes
        self._scheduler.add_job(
            self._risk_check_job,
            IntervalTrigger(minutes=15),
            id="risk_check",
            name="Portfolio Risk Check",
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
        logger.info("Scheduler started with 7 jobs")

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
                    from backend.services.market_data import discover_top_traders
                    from backend.ai.scoring_engine import generate_scout_report
                    from backend.services.market_data import get_current_holdings
                    discovery = await discover_top_traders()
                    if discovery and portfolios:
                        holdings = get_current_holdings(db, portfolios[0].id)
                        if holdings:
                            scored_data = generate_scout_report(holdings, discovery)
                except Exception as e:
                    logger.info(f"Scout data unavailable for rule eval (non-fatal): {e}")

                for portfolio in portfolios:
                    traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]
                    actions = engine.evaluate_rules(db, portfolio, traders, scored_data=scored_data)
                    for action in actions:
                        if action.requires_approval:
                            # Create pending alert — user must approve via Telegram or UI
                            engine.create_pending_alert(db, portfolio.id, action)
                            logger.info(f"Pending approval: '{action.rule_name}' — {action.description}")
                        else:
                            # Auto-execute: call eToro API directly
                            sync_service = EToroSyncService()
                            etoro_response = await engine.execute_etoro_action(
                                sync_service.client, action, portfolio, db
                            )
                            success = not (etoro_response or {}).get("error", False)
                            engine.log_execution(
                                db, portfolio, action,
                                approved_by="auto",
                                success=success,
                                etoro_response=etoro_response,
                            )
                            if success:
                                logger.info(f"Auto-executed rule '{action.rule_name}': {action.description}")
                            else:
                                logger.error(f"Auto-execution FAILED for rule '{action.rule_name}': {etoro_response.get('detail')}")
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

        Primary:   Pure math scoring engine (always works, no deps).
        Secondary: If AI is configured, append a 1‑sentence plain‑English summary.

        Never executes trades — only reports findings.
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, Alert, AlertType
        from backend.services.market_data import get_current_holdings, fetch_market_news, discover_top_traders
        from backend.ai.scoring_engine import generate_scout_report

        try:
            news = await fetch_market_news()
            candidates = await discover_top_traders()

            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    holdings = get_current_holdings(db, portfolio.id)
                    if not holdings:
                        continue

                    # ── Step 1: Deterministic growth scoring — ALWAYS runs ──
                    report = generate_scout_report(holdings, candidates)

                    # ── Step 2: Optional AI narrator (1 sentence only) ──
                    ai_summary = None
                    try:
                        from backend.ai.groq_scout import GroqScout
                        groq = GroqScout()
                        if groq.enabled:
                            prompt = (
                                "Summarise this portfolio scout report in ONE plain-English sentence "
                                "(max 20 words). No formatting, no JSON.\n\n"
                                f"Weakest trader: {report['weakest']['username']} "
                                f"(score {report['weakest']['score']}/100).\n"
                                f"Best swap: {report['top_swaps'][0]['username']} "
                                f"(score {report['top_swaps'][0]['score']}/100).\n"
                                f"Portfolio avg score: {report['avg_score']}/100."
                            )
                            import asyncio
                            def _call():
                                return groq._ensure_client().chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    temperature=0,
                                    max_tokens=40,
                                )
                            resp = await asyncio.to_thread(_call)
                            ai_summary = resp.choices[0].message.content.strip()
                    except Exception as e:
                        logger.info(f"AI narrator unavailable (non‑fatal): {e}")

                    # ── Step 3: Build alert ──────────────────────────────
                    alert_type = AlertType.AI_SCOUT
                    if report["action_required"]:
                        w = report["weakest"]
                        title = f"⚠️ Growth Scout Alert: {w['username']} ({w['score']}/100)"
                        message_parts = [
                            f"Weakest link in portfolio.",
                            f"Score: {w['score']}/100",
                        ]
                        for pnl in w.get("penalties", []):
                            message_parts.append(f"⚠ {pnl}")
                        if report["top_swaps"]:
                            message_parts.append(
                                f"Recommended swap: {report['top_swaps'][0]['username']} "
                                f"(score {report['top_swaps'][0]['score']}/100, "
                                f"delta +{report['top_swaps'][0]['delta']})"
                            )
                        severity = "warning"
                    else:
                        title = f"✅ Growth Scout: All Clear (avg {report['avg_score']}/100)"
                        message_parts = [f"All traders score ≥ 50/100. Portfolio avg: {report['avg_score']}/100."]
                        severity = "info"

                    if ai_summary:
                        message_parts.append(f"\n🤖 {ai_summary}")
                    message = "\n".join(message_parts)

                    # ── Step 4: Allocation plan (deterministic) ──────────
                    top_by_score = sorted(
                        report["scored_holdings"], key=lambda x: x["score"], reverse=True
                    )[:3]
                    if top_by_score:
                        eq_pct = round(100 / len(top_by_score), 1)
                        allocs = [
                            {"username": t["username"], "allocation_pct": eq_pct}
                            for t in top_by_score
                        ]
                        from backend.services.rebalance_service import calculate_rebalance_orders
                        current_positions = [
                            {"username": h["username"],
                             "current_value": h.get("allocation_pct", 0) * 0.01 * (portfolio.total_value or 10000)}
                            for h in holdings
                        ]
                        orders = calculate_rebalance_orders(
                            portfolio.total_value or 0, current_positions,
                            {"target_portfolio": allocs}
                        )
                        alloc_lines = []
                        for a in allocs:
                            alloc_lines.append(f"• {a['username']} — {a['allocation_pct']}%")
                        if orders.get("warnings"):
                            alloc_lines.extend([f"⚠️ {w}" for w in orders["warnings"]])
                        message += "\n\n📊 Allocation Plan:\n" + "\n".join(alloc_lines)
                        title += " + Allocation Plan"

                    db.add(Alert(
                        portfolio_id=portfolio.id,
                        alert_type=alert_type,
                        title=title,
                        message=message,
                        severity=severity,
                    ))
                    db.commit()

                    # Send Telegram alert if action required
                    if report["action_required"]:
                        from backend.services.telegram_service import TelegramBot
                        bot = TelegramBot()
                        if bot.enabled:
                            msg = (
                                f"⚠️ <b>Growth Scout Alert</b>\n\n"
                                f"Weakest link: <b>{report['weakest']['username']}</b> "
                                f"(score {report['weakest']['score']}/100)\n\n"
                            )
                            for pnl in report["weakest"].get("penalties", []):
                                msg += f"⚠️ {pnl}\n"
                            if report["top_swaps"]:
                                msg += (
                                    f"\n<b>Top swap:</b> {report['top_swaps'][0]['username']} "
                                    f"(score {report['top_swaps'][0]['score']}/100, "
                                    f"delta +{report['top_swaps'][0]['delta']})\n\n"
                                    f"Reply <code>/swap {report['flagged_trader']} {report['top_swaps'][0]['username']}</code>"
                                )
                            if ai_summary:
                                msg += f"\n\n🤖 <i>{ai_summary}</i>"
                            await bot.send_message(msg, show_keyboard=True)

                    logger.info(
                        f"Growth scout {'flagged' if report['action_required'] else 'cleared'} "
                        f"portfolio {portfolio.id}"
                    )

        except Exception as e:
            logger.error(f"Market scout job failed: {e}")

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
