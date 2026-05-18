"""
Background Scheduler — periodic tasks for portfolio assistant.
Keeps data fresh with eToro sync, risk checks, and trader health monitoring.
"""

from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

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

        interval_kwargs = {
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 120,
        }

        # Keep-alive ping every 4 minutes (prevents Render spin-down)
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

        # Trader Health Monitor every 4 hours
        self._scheduler.add_job(
            self._trader_monitor_job,
            CronTrigger(hour="*/4", minute=30),
            id="trader_monitor",
            name="Trader Health Monitor",
            **interval_kwargs,
        )

        # Daily Discovery Report (08:00 UTC)
        self._scheduler.add_job(
            self._daily_discovery_job,
            CronTrigger(hour=8, minute=0),
            id="daily_discovery",
            name="Daily Discovery Report",
            **interval_kwargs,
        )

        self._scheduler.start()
        logger.info("Scheduler started with 4 jobs (overlap prevention enabled)")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    # ── Jobs ──────────────────────────────────

    async def _keep_alive_job(self):
        import httpx
        try:
            base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/health")
                logger.debug(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Keep-alive ping skipped (expected on local dev): {e}")

    async def _etoro_sync_job(self):
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
                        logger.info(f"eToro sync successful for portfolio {portfolio.id}")
                    else:
                        logger.debug(f"eToro sync skipped for portfolio {portfolio.id}")
        except Exception as e:
            logger.error(f"eToro sync job failed: {e}")

    async def _trader_monitor_job(self):
        """Run Trader Health Monitor — evaluate active traders' holdings and news."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, Alert, AlertType
        from backend.services.etoro_service import EToroSyncService

        try:
            sync_service = EToroSyncService()
            etoro_client = sync_service.client if sync_service.client.enabled else None

            with db_session() as db:
                portfolios = db.query(Portfolio).all()
                for portfolio in portfolios:
                    logger.info("Monitor: checking portfolio %d", portfolio.id)

                    from backend.monitoring.orchestrator import run_monitoring_pipeline
                    result = await run_monitoring_pipeline(
                        db, portfolio.id, etoro_client=etoro_client,
                    )

                    alerts = result.get("alerts", [])
                    summary = result.get("watchlist_summary", {})
                    summary_text = summary.get("summary", "")

                    logger.info("Monitor portfolio %d: %s", portfolio.id, summary_text)

                    for alert_data in alerts:
                        db.add(Alert(
                            portfolio_id=portfolio.id,
                            alert_type=AlertType.MONITORING,
                            title=alert_data.get("title", ""),
                            message=alert_data.get("message", ""),
                            severity=alert_data.get("severity", "info"),
                        ))
                    if alerts:
                        db.commit()
                        logger.info("Monitor: %d alert(s) saved for portfolio %d",
                                    len(alerts), portfolio.id)

                    critical = [a for a in alerts if a.get("severity") in ("warning", "critical")]
                    if critical:
                        from backend.services.telegram_service import TelegramBot
                        bot = TelegramBot()
                        if bot.enabled:
                            for ca in critical:
                                await bot.send_message(
                                    f"Trader Monitor\n\n{ca['message']}",
                                    show_keyboard=False,
                                )
        except Exception as e:
            logger.exception("Trader monitor job failed")

    async def _daily_discovery_job(self):
        """Daily discovery report — 5-stage mass scan, send top results."""
        from backend.services.telegram_service import TelegramBot
        from backend.services.screener_service import run_screener_and_wait

        try:
            bot = TelegramBot()
            if not bot.enabled:
                return

            logger.info("Daily discovery: starting 5-stage scan (target=10000)")
            eligible, excluded, stats = await run_screener_and_wait(
                scan_target=10000, top_n=10, max_concurrent=10,
            )

            text = bot._build_discovery_message(eligible, stats)
            await bot.send_message(text)
            logger.info("Daily discovery report sent (scanned: %d, eligible: %d)",
                        stats.get("discovered", 0), len(eligible))
        except Exception as e:
            logger.exception("Daily discovery job failed")
