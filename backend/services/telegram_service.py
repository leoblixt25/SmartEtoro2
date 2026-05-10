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

Environment variables:
  TELEGRAM_BOT_TOKEN       – Bot token from @BotFather
  TELEGRAM_ALLOWED_USER_ID – Your Telegram user ID (integer)
  TELEGRAM_CHAT_ID         – Your Telegram chat ID (integer)
"""

from __future__ import annotations
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import telegram
    from telegram import Bot, Update
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class TelegramBot:

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.allowed_user_id = self._parse_int("TELEGRAM_ALLOWED_USER_ID")
        self.chat_id = self._parse_int("TELEGRAM_CHAT_ID", self.allowed_user_id)
        self._bot: Optional[Bot] = None

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

    def _parse_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        raw = os.getenv(key)
        if raw and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())
        return default

    def _is_authorized(self, user_id: int) -> bool:
        return user_id == self.allowed_user_id

    def _sym(self, currency: str) -> str:
        return "€" if currency == "EUR" else "$"

    async def send_message(self, text: str, chat_id: Optional[int] = None) -> None:
        if not self.enabled or not self._bot:
            return
        target = chat_id or self.chat_id
        if not target:
            return
        try:
            await self._bot.send_message(chat_id=target, text=text, parse_mode="Markdown")
            logger.info(f"Telegram message sent to {target}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

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
        }
        handler = handlers.get(command)
        if handler:
            await handler(update, args)
        else:
            await update.message.reply_text(
                "Unknown command. Send /help for available commands."
            )

    # ── Commands ─────────────────────────────────

    async def _cmd_help(self, update: Update, args: list[str]) -> None:
        text = (
            "*🤖 CopyVault Bot Commands*\n\n"
            "/ping – Liveness check\n"
            "/status – Quick portfolio snapshot\n"
            "/portfolio – Full portfolio breakdown\n"
            "/traders – Copied traders with PnL\n"
            "/risk – Active risk violations\n"
            "/alerts – Recent unread alerts\n"
            "/pending – Actions awaiting approval\n"
            "/approve <id> – Approve & execute an action\n"
            "/sync – Force eToro sync now\n"
            "/pause – Emergency stop all automation\n"
            "/help – This message"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_ping(self, update: Update, args: list[str]) -> None:
        await update.message.reply_text("✅ CopyVault Bot is active!")

    async def _cmd_status(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from datetime import datetime

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                s = self._sym(p.currency)
                total_return = p.total_value - p.invested_amount
                return_pct = (total_return / p.invested_amount * 100) if p.invested_amount else 0
                mode = "🧪 SIM" if p.is_simulation else "🔴 LIVE"
                text = (
                    f"📊 *CopyVault Status*\n"
                    f"Value: {s}{p.total_value:,.2f}  |  Invested: {s}{p.invested_amount:,.2f}\n"
                    f"Return: {s}{total_return:+,.2f} ({return_pct:+.2f}%)\n"
                    f"Unrealized: {s}{p.unrealized_pnl:+,.2f}  |  Realized: {s}{p.realized_pnl:+,.2f}\n"
                    f"Cash: {s}{p.available_cash:,.2f}  |  Health: {p.health_score:.0f}/100\n"
                    f"{mode}  |  {p.currency}\n"
                    f"Updated: {p.last_updated.strftime('%H:%M UTC') if p.last_updated else '—'}"
                )
                await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/status error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_portfolio(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                s = self._sym(p.currency)
                total_return = p.total_value - p.invested_amount
                return_pct = (total_return / p.invested_amount * 100) if p.invested_amount else 0
                trader_count = len(p.copied_traders) if p.copied_traders else 0
                mode = "Simulation" if p.is_simulation else "LIVE"
                text = (
                    f"📋 *Portfolio Breakdown*\n\n"
                    f"💰 *Value*\n"
                    f"Total: {s}{p.total_value:,.2f}\n"
                    f"Invested: {s}{p.invested_amount:,.2f}\n"
                    f"Cash: {s}{p.available_cash:,.2f}\n\n"
                    f"📈 *PnL*\n"
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
                await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/portfolio error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_traders(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                traders = p.copied_traders
                if not traders:
                    await update.message.reply_text("No copied traders.")
                    return
                lines = [f"👥 *Copied Traders ({len(traders)})*\n"]
                for t in traders:
                    status = "⏸" if t.is_paused else ("▶️" if t.is_active else "⏹")
                    risk_color = "🟢" if t.risk_score < 4 else ("🟡" if t.risk_score < 7 else "🔴")
                    ret = t.total_return_pct or 0
                    ret_sign = "📈" if ret >= 0 else "📉"
                    lines.append(
                        f"{status} *{t.trader_username}*\n"
                        f"  {ret_sign} Return: {ret:+.2f}%  |  Alloc: {t.allocation_pct:.1f}%\n"
                        f"  {risk_color} Risk: {t.risk_score:.1f}/10  |  {t.risk_classification.upper() if t.risk_classification else '—'}\n"
                    )
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/traders error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_risk(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, RiskSettings
        from backend.risk.risk_engine import RiskEngine

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                settings = db.query(RiskSettings).filter(
                    RiskSettings.portfolio_id == p.id
                ).first()
                engine = RiskEngine()
                violations = engine.check_all(db, p, settings)
                if not violations:
                    await update.message.reply_text("✅ No risk violations. Portfolio is healthy.")
                    return
                lines = [f"⚠️ *{len(violations)} Risk Violation(s)*\n"]
                for v in violations:
                    icon = "🔴" if v.severity == "critical" else ("🟡" if v.severity == "warning" else "🔵")
                    lines.append(f"{icon} *{v.title}*")
                    lines.append(f"  {v.message}")
                    if v.suggested_action:
                        lines.append(f"  💡 {v.suggested_action}")
                    lines.append("")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/risk error: {e}")
            await update.message.reply_text(f"Error: {e}")

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
                    await update.message.reply_text("✅ No unread alerts.")
                    return
                lines = [f"🔔 *{len(alerts)} Unread Alerts*\n"]
                for a in alerts:
                    icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.severity, "⚪")
                    lines.append(f"{icon} *{a.title}*")
                    lines.append(f"  {a.message[:200]}")
                    lines.append(f"  _{a.created_at.strftime('%m/%d %H:%M')}_\n")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/alerts error: {e}")
            await update.message.reply_text(f"Error: {e}")

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
                    await update.message.reply_text("✅ No pending approvals.")
                    return
                lines = [f"⏳ *{len(alerts)} Pending Approval(s)*\n"]
                for a in alerts:
                    lines.append(f"• {a.title}")
                    lines.append(f"  {a.message[:200]}")
                    lines.append(f"  _{a.created_at.strftime('%m/%d %H:%M')}_\n")
                lines.append("Use /approve <rule_id> to execute.")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/pending error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_approve(self, update: Update, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /approve <rule_id>")
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
                    await update.message.reply_text(f"No rule found with ID {action_id}.")
                    return
                portfolio = db.query(Portfolio).filter(Portfolio.id == rule.portfolio_id).first()
                if not portfolio:
                    await update.message.reply_text("Portfolio not found.")
                    return
                traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]
                actions = engine.evaluate_rules(db, portfolio, traders)
                match = next((a for a in actions if a.rule_id == action_id), None)
                if not match:
                    await update.message.reply_text(
                        f"Rule '{rule.name}' is not currently triggered. Conditions may no longer be met."
                    )
                    return
                await update.message.reply_text(f"⚙️ Executing '{rule.name}' on eToro...")
                resp = await engine.execute_etoro_action(sync_service.client, match, portfolio, db)
                success = not (resp or {}).get("error", False)
                engine.log_execution(db, portfolio, match, approved_by="telegram", success=success, etoro_response=resp)
                if success:
                    await update.message.reply_text(
                        f"✅ *{rule.name}* executed.\n{match.description}",
                        parse_mode="Markdown",
                    )
                else:
                    detail = (resp or {}).get("detail", "Unknown")
                    await update.message.reply_text(f"❌ *{rule.name}* FAILED.\n{detail}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"/approve error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_sync(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.etoro_service import EToroSyncService

        try:
            await update.message.reply_text("🔄 Syncing with eToro...")
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                sync_service = EToroSyncService()
                success = await sync_service.sync_portfolio_data(db, p.id)
                if success:
                    db.refresh(p)
                    s = self._sym(p.currency)
                    await update.message.reply_text(
                        f"✅ Sync complete.\n"
                        f"Value: {s}{p.total_value:,.2f}  |  "
                        f"Updated: {p.last_updated.strftime('%H:%M UTC')}",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text("❌ Sync failed. Check API credentials / logs.")
        except Exception as e:
            logger.error(f"/sync error: {e}")
            await update.message.reply_text(f"Sync error: {e}")

    async def _cmd_pause(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.automation.automation_engine import AutomationEngine

        engine = AutomationEngine()
        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await update.message.reply_text("No portfolio found.")
                    return
                count = engine.emergency_stop(db, p.id)
                await update.message.reply_text(
                    f"⛔ *Emergency Stop Activated*\n"
                    f"{count} automation rule(s) paused.\n"
                    "Use the web dashboard to re-enable.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"/pause error: {e}")
            await update.message.reply_text(f"Error: {e}")

    # ── Webhook helpers ──────────────────────────

    def webhook_path(self) -> str:
        return "/api/telegram/webhook"

    def webhook_url(self) -> str:
        base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
        return f"{base}{self.webhook_path()}"
