"""
Background Scheduler
────────────────────────────────────────────────────────────────────
Runs periodic tasks: risk checks, analytics refresh, daily snapshots.
Uses APScheduler for simple, reliable job scheduling.
"""

from __future__ import annotations
import logging
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

        # Risk check every 15 minutes
        self._scheduler.add_job(
            self._risk_check_job,
            IntervalTrigger(minutes=15),
            id="risk_check",
            name="Portfolio Risk Check",
        )

        # eToro data sync every 5 minutes
        self._scheduler.add_job(
            self._etoro_sync_job,
            IntervalTrigger(minutes=5),
            id="etoro_sync",
            name="eToro Portfolio Sync",
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

        self._scheduler.start()
        logger.info("Scheduler started with 4 jobs")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    # ── Job implementations ──────────────────────

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
