"""Telegram command handlers — modular, with proper error handling.

Each handler is a standalone async function. Shared setup/teardown
lives in the main TelegramBot class (telegram_service.py).
"""

import logging
from typing import List, Optional

from telegram import Update

from backend.database.connection import db_session
from backend.database.models import Portfolio
from backend.services.market_data import discover_top_traders, fetch_market_news, get_current_holdings
from backend.telegram.notifications import (
    currency_symbol,
    format_alerts,
    format_pending_approvals,
    format_risk_violations,
    format_status,
    format_traders,
)

logger = logging.getLogger(__name__)


# ── Command Function Signatures ────────────────────────────────────
# Each command takes (update, args, bot_instance) where bot_instance
# is the TelegramBot from telegram_service.py. This avoids circular imports.


async def cmd_ping(update: Update, args: List[str], bot) -> None:
    """Simple liveness check."""
    await bot._reply(update, "✅ CopyVault Bot is active!")


async def cmd_help(update: Update, args: List[str], bot) -> None:
    lines = [
        "📋 **Available Commands**",
        "",
        "/status — Portfolio snapshot",
        "/portfolio — Full portfolio breakdown",
        "/traders — Per-trader details",
        "/risk — Risk violations",
        "/alerts — Recent alerts",
        "/pending — Pending approvals",
        "/approve <id> — Approve an action",
        "/scout — Run growth scout",
        "/swap <old> <new> — Swap traders",
        "/sync — Force eToro sync",
        "/pause — Emergency stop all rules",
        "/db_status — Database status",
        "/ping — Liveness check",
    ]
    await bot._reply(update, "\n".join(lines))


async def cmd_status(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found. Run /sync first.")
            return
        await bot._reply(update, format_status(p))


async def cmd_portfolio(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.database.models import CopiedTrader
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return

        base = format_status(p)
        traders = db.query(CopiedTrader).filter(CopiedTrader.portfolio_id == p.id).count()
        sym = currency_symbol(p.currency or "USD")
        extra = [
            "",
            f"Copying {traders} trader(s)",
            f"Daily PnL:  {sym}{p.daily_pnl or 0:+,.2f}",
            f"Weekly PnL: {sym}{p.weekly_pnl or 0:+,.2f}",
            f"Monthly PnL:{sym}{p.monthly_pnl or 0:+,.2f}",
        ]
        await bot._reply(update, base + "\n".join(extra))


async def cmd_traders(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.database.models import CopiedTrader
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        traders = (
            db.query(CopiedTrader)
            .filter(CopiedTrader.portfolio_id == p.id)
            .all()
        )
        await bot._reply(update, format_traders(traders))


async def cmd_risk(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.risk.risk_engine import RiskEngine
        from backend.database.models import RiskSettings
        from backend.database.storage import get_portfolio, get_risk_settings
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        settings = get_risk_settings(db, p.id)
        engine = RiskEngine()
        violations = engine.check_all(db, p, settings)
        engine.violations_to_alerts(db, p.id, violations)
        await bot._reply(update, format_risk_violations(violations))


async def cmd_alerts(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.database.storage import get_unread_alerts
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        alerts = get_unread_alerts(db, p.id)
        await bot._reply(update, format_alerts(alerts))


async def cmd_pending(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.database.storage import get_pending_approvals
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        alerts = get_pending_approvals(db, p.id)
        await bot._reply(update, format_pending_approvals(alerts))


async def cmd_approve(update: Update, args: List[str], bot) -> None:
    if not args:
        await bot._reply(update, "Usage: /approve <rule_id>")
        return
    try:
        rule_id = int(args[0])
    except ValueError:
        await bot._reply(update, "Rule ID must be a number.")
        return

    with db_session() as db:
        from backend.database.models import AutomationRule, Alert, Portfolio
        from backend.automation.automation_engine import AutomationEngine
        from backend.database.storage import get_portfolio
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return

        engine = AutomationEngine()
        try:
            actions = engine.evaluate_rules(db, p, [])
        except Exception as e:
            await bot._reply(update, f"Error evaluating rules: {e}")
            return

        target = None
        for action in actions:
            if action.rule_id == rule_id:
                target = action
                break

        if not target:
            await bot._reply(update, f"No pending action found for rule {rule_id}.")
            return

        from backend.services.etoro_service import EToroAPIClient
        client = EToroAPIClient()
        try:
            result = await engine.execute_etoro_action(client, target, p, db)
            engine.log_execution(db, p, target, approved_by="telegram", success=True, etoro_response=result)
            await bot._reply(update, f"✅ Action approved and executed. Result: {result}")
        except Exception as e:
            engine.log_execution(db, p, target, approved_by="telegram", success=False)
            logger.exception("Approval execution failed")
            await bot._reply(update, f"❌ Execution failed: {e}")


async def cmd_sync(update: Update, args: List[str], bot) -> None:
    await bot._reply(update, "🔄 Syncing portfolio data from eToro...")
    with db_session() as db:
        from backend.services.etoro_service import EToroSyncService
        from backend.database.storage import get_portfolio
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        try:
            success = await EToroSyncService().sync_portfolio_data(db, p.id)
            if success:
                db.refresh(p)
                await bot._reply(update, f"✅ Sync complete.\n{format_status(p)}")
            else:
                await bot._reply(update, "⚠️ Sync completed with issues. Check logs.")
        except Exception as e:
            logger.exception("Sync failed")
            await bot._reply(update, f"❌ Sync failed: {e}")


async def cmd_pause(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.automation.automation_engine import AutomationEngine
        from backend.database.storage import get_portfolio
        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return
        engine = AutomationEngine()
        count = engine.emergency_stop(db, p.id)
        await bot._reply(update, f"⏸️ Emergency stop — {count} rules paused.")


async def cmd_scout(update: Update, args: List[str], bot) -> None:
    """Run the deterministic growth scout."""
    await bot._reply(update, "🔍 Running Growth Scout...")

    try:
        news = await fetch_market_news()
        candidates = await discover_top_traders()
        logger.info(f"Scout: {len(news)} news, {len(candidates)} candidates")

        with db_session() as db:
            from backend.database.storage import get_portfolio
            p = db.query(Portfolio).first()
            if not p:
                await bot._reply(update, "No portfolio found.")
                return

            holdings = get_current_holdings(db, p.id)
            logger.info(f"Scout: loaded {len(holdings)} active traders for portfolio {p.id}")

            from backend.scout.trader_scout import get_scout_runner
            runner = get_scout_runner()
            report = await runner.run(holdings, candidates)

            # ── Optional AI narrator (1 sentence) ──
            ai_summary = None
            try:
                from backend.ai.groq_scout import GroqScout
                groq = GroqScout()
                if groq.enabled and report.get("holdings_ranked"):
                    prompt = (
                        "Summarise this portfolio scout report in ONE plain-English sentence "
                        "(max 20 words). No formatting, no JSON.\n\n"
                        f"Weakest trader: {report['weakest']['username']} "
                        f"(score {report['weakest']['final_score']}/100).\n"
                        f"Best swap: {report['top_swaps'][0]['username']} "
                        f"(score {report['top_swaps'][0]['final_score']}/100)"
                        if report.get("top_swaps") else ""
                        f"\nPortfolio avg score: {report['avg_score']}/100."
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
                    if resp and resp.choices:
                        ai_summary = resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning("AI narrator unavailable for scout: %s", e)

            display = report.get("display", "Scout report unavailable.")
            if ai_summary:
                display += f"\n\n_{ai_summary}_"

            await bot._reply(update, display)

    except Exception as e:
        logger.exception("Scout command failed")
        await bot._reply(update, f"❌ Scout error: {e}")


async def cmd_swap(update: Update, args: List[str], bot) -> None:
    if len(args) < 2:
        await bot._reply(update, "Usage: /swap <old_username> <new_username>")
        return

    old_user, new_user = args[0], args[1]

    with db_session() as db:
        from backend.database.models import CopiedTrader, Alert
        from backend.database.storage import get_portfolio
        from backend.services.etoro_service import EToroAPIClient

        p = db.query(Portfolio).first()
        if not p:
            await bot._reply(update, "No portfolio found.")
            return

        # Find the old trader
        trader = (
            db.query(CopiedTrader)
            .filter(
                CopiedTrader.portfolio_id == p.id,
                CopiedTrader.trader_username == old_user,
                CopiedTrader.is_active.is_(True),
            )
            .first()
        )
        if not trader:
            await bot._reply(update, f"Active trader '{old_user}' not found.")
            return

        await bot._reply(update, f"🔄 Closing mirror for {old_user}...")

        try:
            client = EToroAPIClient()
            mirror_id = int(trader.trader_id) if trader.trader_id else None
            if not mirror_id or mirror_id <= 0:
                await bot._reply(update, f"Invalid mirror ID for {old_user}. Cannot close automatically.")
                return

            result = await client.execute_close_mirror(mirror_id)
            trader.is_active = False
            trader.is_paused = True
            trader.paused_reason = f"Swapped to {new_user}"

            alert = Alert(
                portfolio_id=p.id,
                alert_type="ai_scout",
                title=f"Trader Swap: {old_user} → {new_user}",
                message=f"Closed mirror for {old_user}. Start copy of {new_user} via eToro UI.",
                severity="info",
            )
            db.add(alert)
            db.commit()

            await bot._reply(update, (
                f"✅ Swapped {old_user} → {new_user}\n\n"
                f"Mirror closed. To start copying {new_user}, use the eToro UI."
            ))
        except Exception as e:
            logger.exception("Swap failed")
            await bot._reply(update, f"❌ Swap failed: {e}")


async def cmd_db_status(update: Update, args: List[str], bot) -> None:
    with db_session() as db:
        from backend.database.models import AutomationRule, CopiedTrader, Alert, Portfolio, RiskSettings
        from sqlalchemy import text
        p = db.query(Portfolio).first()
        try:
            db.execute(text("SELECT 1"))
            db_status = "Connected"
        except Exception:
            db_status = "Disconnected"

        rule_count = db.query(AutomationRule).filter(AutomationRule.portfolio_id == (p.id if p else 0)).count() if p else 0
        trader_count = db.query(CopiedTrader).filter(CopiedTrader.portfolio_id == (p.id if p else 0)).count() if p else 0

        lines = [
            "🗄️ **Database Status**",
            f"Connection: {db_status}",
            f"Rules: {rule_count}",
            f"Traders: {trader_count}",
        ]
        await bot._reply(update, "\n".join(lines))
