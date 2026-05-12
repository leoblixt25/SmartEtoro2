"""
Telegram Bot Service
────────────────────────────────────────────────────────────────────
Webhook-based Telegram bot for monitoring, control, and approval.

Architecture:
  - Uses raw telegram.Bot (no Application/Dispatcher — __slots__ bug on Py3.14)
  - Webhook dispatch via FastAPI endpoint
  - Only responds to TELEGRAM_ALLOWED_USER_ID

Commands:
  /help              – List all commands
  /ping              – Liveness check
  /status            – Quick portfolio snapshot
  /portfolio         – Full portfolio details (value, PnL, currency)
  /traders           – List copied traders with PnL %, allocation, risk
  /risk              – Active risk violations
  /alerts            – Recent unread alerts
  /pending           – Actions waiting for your approval
  /approve <rule_id> – Approve and execute a pending action
  /sync              – Trigger an eToro data sync now
  /pause             – Emergency stop all automation rules
  /scout             – Run AI Market Scout now
  /swap <old> <new>  – Execute a trader swap recommended by Scout

Environment variables:
  TELEGRAM_BOT_TOKEN       – Bot token from @BotFather
  TELEGRAM_ALLOWED_USER_ID – Your Telegram user ID (integer)
  TELEGRAM_CHAT_ID         – Your Telegram chat ID (integer)
"""

from __future__ import annotations
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import telegram
    from telegram import Bot, Update, BotCommand
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class TelegramBot:

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.allowed_user_id = self._parse_int("TELEGRAM_ALLOWED_USER_ID")
        self.chat_id = self._parse_int("TELEGRAM_CHAT_ID", self.allowed_user_id)
        self._bot: Optional[Bot] = None
        self._started_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

        if not TELEGRAM_AVAILABLE:
            self.enabled = False
        elif not self.token:
            logger.info("TELEGRAM_BOT_TOKEN not set — Telegram disabled")
            self.enabled = False
        elif not self.allowed_user_id:
            logger.warning("TELEGRAM_ALLOWED_USER_ID not set — Telegram disabled")
            self.enabled = False
        else:
            self._bot = Bot(token=self.token)
            self.enabled = True

    @property
    def status(self) -> dict:
        uptime = None
        if self._started_at:
            delta = datetime.utcnow() - self._started_at
            mins = int(delta.total_seconds() // 60)
            uptime = f"{mins}m" if mins < 60 else f"{mins // 60}h{mins % 60}m"
        return {
            "enabled": self.enabled,
            "has_token": bool(self.token),
            "has_allowed_user": self.allowed_user_id is not None,
            "has_chat_id": self.chat_id is not None,
            "webhook_url": self.webhook_url() if self.enabled else None,
            "uptime": uptime,
            "last_error": self.last_error,
        }

    COMMANDS = [
        BotCommand("help", "Show all commands"),
        BotCommand("ping", "Liveness check"),
        BotCommand("status", "Quick portfolio snapshot"),
        BotCommand("portfolio", "Full portfolio breakdown"),
        BotCommand("traders", "Copied traders with PnL"),
        BotCommand("risk", "Active risk violations"),
        BotCommand("alerts", "Recent unread alerts"),
        BotCommand("pending", "Actions awaiting approval"),
        BotCommand("approve", "Approve & execute a pending action"),
        BotCommand("sync", "Force eToro sync now"),
        BotCommand("pause", "Emergency stop all automation"),
        BotCommand("scout", "Run AI Market Scout now"),
        BotCommand("swap", "Execute a trader swap from Scout recommendation"),
        BotCommand("db_check", "Verify database persistence"),
        BotCommand("db_status", "Database status overview"),
        BotCommand("mode", "Toggle simulation/real mode"),
    ]

    MAIN_KEYBOARD = [
        ["/status", "/traders"],
        ["/portfolio", "/risk"],
        ["/pending", "/alerts"],
        ["/sync", "/scout"],
    ]

    async def setup_commands(self) -> None:
        """Register the slash-command menu with Telegram."""
        if self._bot:
            try:
                await self._bot.set_my_commands(self.COMMANDS)
                logger.info("Telegram command menu registered")
            except Exception as e:
                logger.warning(f"Failed to register commands: {e}")

    def _keyboard(self) -> dict:
        """Inline reply keyboard markup for easy command access."""
        return {"keyboard": self.MAIN_KEYBOARD, "resize_keyboard": True}

    def _parse_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        raw = os.getenv(key)
        if raw and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())
        return default

    def _is_authorized(self, user_id: int) -> bool:
        return user_id == self.allowed_user_id

    def _sym(self, currency: str) -> str:
        return "€" if currency == "EUR" else "$"

    async def send_message(self, text: str, chat_id: Optional[int] = None, show_keyboard: bool = False) -> None:
        if not self.enabled or not self._bot:
            return
        target = chat_id or self.chat_id
        if not target:
            return
        try:
            kwargs = {"chat_id": target, "text": text, "parse_mode": "HTML"}
            if show_keyboard:
                kwargs["reply_markup"] = self._keyboard()
            await self._bot.send_message(**kwargs)
            logger.info(f"Telegram message sent to {target}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def _reply(self, update: Update, text: str, **kwargs) -> None:
        """Reply with text + persistent keyboard."""
        markup = self._keyboard()
        await update.message.reply_text(text, reply_markup=markup, **kwargs)

    async def process_update(self, payload: dict) -> None:
        if not self.enabled or not self._bot:
            return
        try:
            update = Update.de_json(payload, self._bot)
        except Exception:
            return
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or not self._is_authorized(user_id):
            return
        text = update.message.text.strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:]

        handlers = {
            "/help": self._cmd_help,
            "/ping": self._cmd_ping,
            "/status": self._cmd_status,
            "/portfolio": self._cmd_portfolio,
            "/traders": self._cmd_traders,
            "/risk": self._cmd_risk,
            "/alerts": self._cmd_alerts,
            "/pending": self._cmd_pending,
            "/approve": self._cmd_approve,
            "/sync": self._cmd_sync,
            "/pause": self._cmd_pause,
            "/scout": self._cmd_scout,
            "/swap": self._cmd_swap,
            "/db_check": self._cmd_db_check,
            "/db_status": self._cmd_db_status,
            "/mode": self._cmd_mode,
        }
        handler = handlers.get(command)
        if handler:
            await handler(update, args)
        else:
            await self._reply(update, "Unknown command. Send /help for available commands.")

    # ── Commands ─────────────────────────────────

    async def _cmd_help(self, update: Update, args: list[str]) -> None:
        text = (
            "*🤖 CopyVault Bot Commands*\n\n"
            "Tap a button below or type a command:\n\n"
            "/status – Portfolio snapshot\n"
            "/portfolio – Full breakdown\n"
            "/traders – Copied traders\n"
            "/risk – Risk violations\n"
            "/alerts – Unread alerts\n"
            "/pending – Pending approvals\n"
            "/approve <id> – Approve action\n"
            "/sync – Sync eToro now\n"
            "/pause – Emergency stop\n"
            "/scout – Run AI Market Scout\n"
            "/swap <old> <new> – Execute Scout swap\n"
            "/db_check – Database diagnostics\n"
            "/db_status – Database status overview\n"
            "/mode <real|simulation> – Toggle live/simulation mode"
        )
        await self._reply(update, text, parse_mode="Markdown")

    async def _cmd_ping(self, update: Update, args: list[str]) -> None:
        await self._reply(update, "✅ CopyVault Bot is active!")

    async def _cmd_db_check(self, update: Update, args: list[str]) -> None:
        """Diagnostic: verify database persistence."""
        from backend.database.connection import DATABASE_URL
        from backend.database.connection import engine
        from sqlalchemy import text
        import os

        db_type = "PostgreSQL" if DATABASE_URL.startswith("postgresql") else "SQLite"
        lines = [f"<b>🔍 Database Diagnostics</b>\n"]
        lines.append(f"<b>Type:</b> {db_type}")

        # Rule count
        try:
            from backend.database.connection import SessionLocal
            db = SessionLocal()
            from backend.database.models import AutomationRule, AppSetting
            rule_count = db.query(AutomationRule).count()
            lines.append(f"<b>Rules in DB:</b> {rule_count}")

            # Test write/read
            test_key = "_db_check_test"
            existing = db.query(AppSetting).filter(AppSetting.key == test_key).first()
            if existing:
                db.delete(existing)
                db.commit()

            test = AppSetting(key=test_key, value="ok")
            db.add(test)
            db.commit()

            re_read = db.query(AppSetting).filter(AppSetting.key == test_key).first()
            if re_read and re_read.value == "ok":
                lines.append(f"<b>Write/Read:</b> ✅ passed")
            else:
                lines.append(f"<b>Write/Read:</b> ❌ failed — value mismatch")

            db.delete(re_read)
            db.commit()
        except Exception as e:
            lines.append(f"<b>Write/Read:</b> ❌ FAILED — {e}")
        finally:
            db.close()

        # Connection check
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.scalar()
            lines.append(f"<b>Connection:</b> ✅ OK")
        except Exception as e:
            lines.append(f"<b>Connection:</b> ❌ FAILED — {e}")

        await self._reply(update, "\n".join(lines), parse_mode="HTML")

    async def _cmd_db_status(self, update: Update, args: list[str]) -> None:
        """Quick database status overview."""
        from backend.database.connection import DATABASE_URL
        from backend.database.connection import SessionLocal
        from backend.database.models import AutomationRule

        db_type = "PostgreSQL" if DATABASE_URL.startswith("postgresql") else "SQLite"
        lines = [f"<b>Database Status</b>\n"]
        lines.append(f"<b>Type:</b> {db_type}")

        try:
            db = SessionLocal()
            rule_count = db.query(AutomationRule).count()
            lines.append(f"<b>Rules:</b> {rule_count}")
        except Exception as e:
            lines.append(f"<b>Rules:</b> Error — {e}")
        finally:
            db.close()

        await self._reply(update, "\n".join(lines), parse_mode="HTML")

    async def _cmd_mode(self, update: Update, args: list[str]) -> None:
        """Toggle between simulation and real (live) trading mode.

        Usage: /mode real      → disables simulation, enables live trading
               /mode simulation → enables simulation (safe for testing)
        """
        if not args or args[0].lower() not in ("real", "simulation"):
            await self._reply(update,
                "Usage: <code>/mode real</code> or <code>/mode simulation</code>",
                parse_mode="HTML",
            )
            return

        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        target_sim = args[0].lower() == "simulation"

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                old_mode = p.is_simulation
                p.is_simulation = target_sim
                db.commit()

                mode_label = "🧪 SIMULATION" if target_sim else "🔴 LIVE"
                await self._reply(update,
                    f"<b>Mode Changed</b>\n\n"
                    f"Was: {'Simulation' if old_mode else 'Live'}\n"
                    f"Now: {mode_label}\n\n"
                    f"{'⚠️ Live trades will execute on eToro.' if not target_sim else '✅ Safe — no real trades.'}",
                    parse_mode="HTML",
                )
                logger.info(f"Portfolio mode changed: simulation={old_mode} → {target_sim}")
        except Exception as e:
            logger.error(f"/mode error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_status(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                s = self._sym(p.currency)
                total_return = p.total_value - p.invested_amount
                return_pct = (total_return / p.invested_amount * 100) if p.invested_amount else 0
                mode = "🧪 SIM" if p.is_simulation else "🔴 LIVE"
                text = (
                    f"<b>📊 CopyVault Status</b>\n"
                    f"Value: {s}{p.total_value:,.2f}  |  Invested: {s}{p.invested_amount:,.2f}\n"
                    f"Return: {s}{total_return:+,.2f} ({return_pct:+.2f}%)\n"
                    f"Unrealized: {s}{p.unrealized_pnl:+,.2f}  |  Realized: {s}{p.realized_pnl:+,.2f}\n"
                    f"Cash: {s}{p.available_cash:,.2f}  |  Health: {p.health_score:.0f}/100\n"
                    f"{mode}  |  {p.currency}\n"
                    f"Updated: {p.last_updated.strftime('%H:%M UTC') if p.last_updated else '—'}"
                )
                await self._reply(update, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"/status error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_portfolio(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                s = self._sym(p.currency)
                total_return = p.total_value - p.invested_amount
                return_pct = (total_return / p.invested_amount * 100) if p.invested_amount else 0
                trader_count = len(p.copied_traders) if p.copied_traders else 0
                mode = "Simulation" if p.is_simulation else "LIVE"
                text = (
                    f"<b>📋 Portfolio Breakdown</b>\n\n"
                    f"💰 <b>Value</b>\n"
                    f"Total: {s}{p.total_value:,.2f}\n"
                    f"Invested: {s}{p.invested_amount:,.2f}\n"
                    f"Cash: {s}{p.available_cash:,.2f}\n\n"
                    f"📈 <b>PnL</b>\n"
                    f"Total Return: {s}{total_return:+,.2f} ({return_pct:+.2f}%)\n"
                    f"Unrealized: {s}{p.unrealized_pnl:+,.2f}\n"
                    f"Realized: {s}{p.realized_pnl:+,.2f}\n"
                    f"Daily: {s}{p.daily_pnl:+,.2f}\n"
                    f"Weekly: {s}{p.weekly_pnl:+,.2f}\n"
                    f"Monthly: {s}{p.monthly_pnl:+,.2f}\n\n"
                    f"🏥 Health: {p.health_score:.0f}/100\n"
                    f"👥 Copied Traders: {trader_count}\n"
                    f"💱 {p.currency}  |  Mode: {mode}\n"
                    f"🕐 {p.last_updated.strftime('%Y-%m-%d %H:%M UTC') if p.last_updated else '—'}"
                )
                await self._reply(update, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"/portfolio error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_traders(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                traders = p.copied_traders
                if not traders:
                    await self._reply(update, "No copied traders.")
                    return
                lines = [f"👥 <b>Copied Traders ({len(traders)})</b>\n"]
                for t in traders:
                    status = "⏸" if t.is_paused else ("▶️" if t.is_active else "⏹")
                    risk_color = "🟢" if t.risk_score < 4 else ("🟡" if t.risk_score < 7 else "🔴")
                    ret = t.total_return_pct or 0
                    ret_sign = "📈" if ret >= 0 else "📉"
                    # Use HTML bold tags — Markdown breaks when username contains underscores
                    lines.append(
                        f"{status} <b>{t.trader_username}</b>\n"
                        f"  {ret_sign} Return: {ret:+.2f}%  |  Alloc: {t.allocation_pct:.1f}%\n"
                        f"  {risk_color} Risk: {t.risk_score:.1f}/10  |  {t.risk_classification.upper() if t.risk_classification else '—'}\n"
                    )
                await self._reply(update, "\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logger.error(f"/traders error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_risk(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, RiskSettings
        from backend.risk.risk_engine import RiskEngine

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                settings = db.query(RiskSettings).filter(
                    RiskSettings.portfolio_id == p.id
                ).first()
                engine = RiskEngine()
                violations = engine.check_all(db, p, settings)
                if not violations:
                    await self._reply(update, "✅ No risk violations. Portfolio is healthy.")
                    return
                lines = [f"⚠️ *{len(violations)} Risk Violation(s)*\n"]
                for v in violations:
                    icon = "🔴" if v.severity == "critical" else ("🟡" if v.severity == "warning" else "🔵")
                    lines.append(f"{icon} *{v.title}*")
                    lines.append(f"  {v.message}")
                    if v.suggested_action:
                        lines.append(f"  💡 {v.suggested_action}")
                    lines.append("")
                await self._reply(update, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/risk error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_alerts(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Alert

        try:
            with db_session() as db:
                alerts = (
                    db.query(Alert)
                    .filter(Alert.is_read.is_(False))
                    .order_by(Alert.created_at.desc())
                    .limit(5)
                    .all()
                )
                if not alerts:
                    await self._reply(update, "✅ No unread alerts.")
                    return
                lines = [f"🔔 *{len(alerts)} Unread Alerts*\n"]
                for a in alerts:
                    icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.severity, "⚪")
                    lines.append(f"{icon} *{a.title}*")
                    lines.append(f"  {a.message[:200]}")
                    lines.append(f"  _{a.created_at.strftime('%m/%d %H:%M')}_\n")
                await self._reply(update, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/alerts error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_pending(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Alert

        try:
            with db_session() as db:
                alerts = (
                    db.query(Alert)
                    .filter(
                        Alert.alert_type == "automation",
                        Alert.is_read.is_(False),
                    )
                    .order_by(Alert.created_at.desc())
                    .limit(10)
                    .all()
                )
                if not alerts:
                    await self._reply(update, "✅ No pending approvals.")
                    return
                lines = [f"⏳ *{len(alerts)} Pending Approval(s)*\n"]
                for a in alerts:
                    lines.append(f"• {a.title}")
                    lines.append(f"  {a.message[:200]}")
                    lines.append(f"  _{a.created_at.strftime('%m/%d %H:%M')}_\n")
                lines.append("Use /approve <rule_id> to execute.")
                await self._reply(update, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/pending error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_approve(self, update: Update, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            await self._reply(update, "Usage: /approve <rule_id>")
            return
        action_id = int(args[0])
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, AutomationRule
        from backend.automation.automation_engine import AutomationEngine
        from backend.services.etoro_service import EToroSyncService

        engine = AutomationEngine()
        sync_service = EToroSyncService()

        try:
            with db_session() as db:
                rule = db.query(AutomationRule).filter(AutomationRule.id == action_id).first()
                if not rule:
                    await self._reply(update, f"No rule found with ID {action_id}.")
                    return
                portfolio = db.query(Portfolio).filter(Portfolio.id == rule.portfolio_id).first()
                if not portfolio:
                    await self._reply(update, "Portfolio not found.")
                    return
                traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]
                actions = engine.evaluate_rules(db, portfolio, traders)
                match = next((a for a in actions if a.rule_id == action_id), None)
                if not match:
                    await self._reply(update, 
                        f"Rule '{rule.name}' is not currently triggered. Conditions may no longer be met."
                    )
                    return
                await self._reply(update, f"⚙️ Executing '{rule.name}' on eToro...")
                resp = await engine.execute_etoro_action(sync_service.client, match, portfolio, db)
                has_error = (resp or {}).get("error", False)
                success_count = (resp or {}).get("success_count", None)
                if has_error:
                    success = False
                elif success_count is not None:
                    success = success_count > 0
                else:
                    success = True
                engine.log_execution(db, portfolio, match, approved_by="telegram", success=success, etoro_response=resp)
                if success:
                    count_info = f" ({resp.get('success_count', '?')}/{resp.get('total', '?')} actions succeeded)" if "success_count" in (resp or {}) else ""
                    await self._reply(update, 
                        f"✅ *{rule.name}* executed.{count_info}\n{match.description}",
                        parse_mode="Markdown",
                    )
                else:
                    detail = (resp or {}).get("detail", "Unknown")
                    await self._reply(update, f"❌ *{rule.name}* FAILED.\n{detail}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/approve error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_sync(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.etoro_service import EToroSyncService

        try:
            await self._reply(update, "🔄 Syncing with eToro...")
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                sync_service = EToroSyncService()
                success = await sync_service.sync_portfolio_data(db, p.id)
                if success:
                    db.refresh(p)
                    s = self._sym(p.currency)
                    await self._reply(update, 
                        f"✅ Sync complete.\n"
                        f"Value: {s}{p.total_value:,.2f}  |  "
                        f"Updated: {p.last_updated.strftime('%H:%M UTC')}",
                        parse_mode="Markdown",
                    )
                else:
                    await self._reply(update, "❌ Sync failed. Check API credentials / logs.")
        except Exception as e:
            logger.error(f"/sync error: {e}")
            await self._reply(update, f"Sync error: {e}")

    async def _cmd_pause(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.automation.automation_engine import AutomationEngine

        engine = AutomationEngine()
        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                count = engine.emergency_stop(db, p.id)
                await self._reply(update, 
                    f"⛔ *Emergency Stop Activated*\n"
                    f"{count} automation rule(s) paused.\n"
                    "Use the web dashboard to re-enable.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"/pause error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_scout(self, update: Update, args: list[str]) -> None:
        """Run Deterministic Growth Scout on demand via Telegram.

        Primary:   Pure math scoring engine (always works, no deps).
        Secondary: If AI is configured, append a 1‑sentence plain‑English summary.
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.market_data import get_current_holdings, fetch_market_news, discover_top_traders
        from backend.ai.scoring_engine import generate_scout_report, rank_candidates, scout_holdings, rank_combined
        from backend.services.allocation_logic import calculate_equal_weight_target

        await self._reply(update, "🔍 Running Growth Scout...")

        try:
            news = await fetch_market_news()
            candidates = await discover_top_traders()
            logger.info(f"Scout: {len(news)} news, {len(candidates)} candidates")

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                holdings = get_current_holdings(db, p.id)
                if not holdings:
                    await self._reply(update, "No active copied traders found.")
                    return

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
                            "(max 20 words). No formatting, no JSON, no commentary.\n\n"
                            f"Weakest trader: {report['weakest']['username']} "
                            f"(score {report['weakest']['score']}/100).\n"
                            f"Best swap: {report['top_swaps'][0]['username']} "
                            f"(score {report['top_swaps'][0]['score']}/100, "
                            f"delta +{report['top_swaps'][0]['delta']}).\n"
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
                    ai_summary = None

                # ── Step 3: Build message ───────────────────────────
                lines = []

                # Score table
                lines.append("<b>📊 Growth Scores</b>")
                for s in report["scored_holdings"]:
                    icon = "🟢" if s["score"] >= 60 else ("🟡" if s["score"] >= 30 else "🔴")
                    lines.append(
                        f"{icon} <b>{s['username']}</b> — {s['score']}/100 "
                        f"(alloc {s['allocation_pct']:.1f}%)"
                    )
                lines.append(f"\n<b>Portfolio Avg:</b> {report['avg_score']}/100")

                # AI narrator (optional)
                if ai_summary:
                    lines.append(f"\n🤖 <i>{ai_summary}</i>")

                # Weakest link
                if report["action_required"]:
                    w = report["weakest"]
                    lines.append(
                        f"\n⚠️ <b>Weakest Link:</b> {w['username']} ({w['score']}/100)"
                    )
                    for pnl in w.get("penalties", []):
                        lines.append(f"  {pnl}")

                    # Top swaps
                    lines.append(f"\n<b>Top Swap Recommendations</b>")
                    for i, swap in enumerate(report["top_swaps"], 1):
                        lines.append(
                            f"{i}. <b>{swap['username']}</b> — score {swap['score']}/100 "
                            f"(delta +{swap['delta']})"
                        )
                    lines.append(
                        f"\nReply <code>/swap {report['flagged_trader']} {report['top_swaps'][0]['username']}</code> "
                        f"to execute the top swap."
                    )
                else:
                    lines.append(f"\n✅ <b>Portfolio Healthy</b> — all traders score ≥ 50/100")

                # Top 3 Discovery Candidates (always shown)
                scored_candidates = rank_candidates(holdings, candidates, top_n=3)
                if scored_candidates:
                    lines.append(f"\n<b>🔍 Top 3 Discovery Candidates</b>")
                    for i, c in enumerate(scored_candidates, 1):
                        lines.append(
                            f"{i}. <b>{c['username']}</b> — score {c['score']}/100 "
                            f"(risk {c.get('risk_score','?')}, Δ {c['delta']:+.1f})"
                        )

                # ── Step 4: 33.3% Equal‑Weight Allocation Plan ──────────
                top3_combined = rank_combined(holdings, candidates, top_n=3)
                if top3_combined:
                    target = calculate_equal_weight_target(top3_combined, p.total_value or 10000)
                    from backend.services.rebalance_service import calculate_rebalance_orders
                    current_positions = [
                        {"username": h["username"],
                         "current_value": h.get("allocation_pct", 0) * 0.01 * (p.total_value or 10000)}
                        for h in holdings
                    ]
                    orders = calculate_rebalance_orders(
                        p.total_value or 0, current_positions, target
                    )
                    lines.append(f"\n---\n<b>📊 33.3% Equal‑Weight Plan</b>")
                    for a in target["target_portfolio"]:
                        src = "discovery" if a["username"] not in {h["username"] for h in holdings} else "current"
                        icon = "🆕" if src == "discovery" else "🔄"
                        lines.append(
                            f"{icon} <b>{a['username']}</b> — {a['allocation_pct']}% "
                            f"({src})"
                        )
                    if orders.get("warnings"):
                        for w in orders["warnings"]:
                            lines.append(f"⚠️ {w}")

                text = "\n".join(lines)
                await self._reply(update, text, parse_mode="HTML")

        except Exception as e:
            logger.error(f"/scout error: {e}")
            err_str = str(e)
            if "rate" in err_str.lower() or "429" in err_str or "quota" in err_str.lower():
                await self._reply(update, "⚠️ Scout Error: Rate limit exceeded.")
            elif "api" in err_str.lower() or "401" in err_str or "403" in err_str or "not found" in err_str.lower():
                await self._reply(update, "⚠️ Scout Error: API configuration issue.")
            elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
                await self._reply(update, "⚠️ Scout Error: Request timed out.")
            else:
                await self._reply(update, f"❌ Scout failed: {e}")


    async def _cmd_swap(self, update: Update, args: list[str]) -> None:
        """Execute a trader swap: stop copying old, start copying new.

        Usage: /swap <old_trader_username> <new_trader_username>
        """
        if len(args) < 2:
            await self._reply(update,
                "Usage: `/swap <old_username> <new_username>`\n\n"
                "Example: `/swap booker03 ConsistentCapital`\n"
                "Run /scout first to get a recommendation.",
                parse_mode="Markdown",
            )
            return

        old_username = args[0]
        new_username = args[1]

        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader, Alert, AlertType
        from backend.services.etoro_service import EToroSyncService

        await self._reply(update, f"⚙️ Processing swap: *{old_username}* → *{new_username}*...", parse_mode="Markdown")

        sync_service = EToroSyncService()
        client = sync_service.client

        if not client.enabled:
            await self._reply(update, "❌ eToro API not configured. Set ETORO_API_KEY and ETORO_API_SECRET.")
            return

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                # Find the old trader in our DB
                old_trader = (
                    db.query(CopiedTrader)
                    .filter(
                        CopiedTrader.portfolio_id == p.id,
                        CopiedTrader.trader_username == old_username,
                        CopiedTrader.is_active.is_(True),
                    )
                    .first()
                )
                if not old_trader:
                    await self._reply(update, f"❌ Active trader '{old_username}' not found.")
                    return

                mirror_id = int(old_trader.trader_id) if old_trader.trader_id and old_trader.trader_id.isdigit() else None

                if mirror_id:
                    # Step 1: Close the old mirror position
                    await self._reply(update, f"⏳ Closing copy of {old_username}...")
                    close_result = await client.execute_close_mirror(mirror_id, is_simulation=p.is_simulation)
                    if close_result and close_result.get("error"):
                        detail = close_result.get("detail", "Unknown error")
                        await self._reply(update, f"❌ Failed to close {old_username}: {detail}")
                        return

                # Step 2: Mark old trader as inactive in DB
                old_trader.is_active = False
                old_trader.is_paused = True
                old_trader.paused_reason = f"Swapped to {new_username} via Scout"

                # Step 3: Log the swap as an alert
                db.add(Alert(
                    portfolio_id=p.id,
                    alert_type=AlertType.AI_SCOUT,
                    title=f"🔄 Swap Executed: {old_username} → {new_username}",
                    message=(
                        f"Copy of {old_username} closed and marked inactive.\n"
                        f"To start copying {new_username}, use the eToro UI or add via the dashboard."
                    ),
                    severity="info",
                ))
                db.commit()

                await self._reply(update,
                    f"✅ *Swap Complete*\n\n"
                    f"❌ Stopped copying *{old_username}*\n"
                    f"➡️ Ready to copy *{new_username}*\n\n"
                    f"Note: Starting a new copy must be done via the eToro UI "
                    f"or by adding the trader through the dashboard.",
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.error(f"/swap error: {e}")
            await self._reply(update, f"❌ Swap failed: {e}")

    # ── Webhook helpers ──────────────────────────

    def webhook_path(self) -> str:
        return "/api/telegram/webhook"

    def webhook_url(self) -> str:
        base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
        return f"{base}{self.webhook_path()}"
