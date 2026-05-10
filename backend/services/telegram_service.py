"""
Telegram Bot Service
────────────────────────────────────────────────────────────────────
Webhook-based Telegram bot for monitoring and approving automation rules.

Architecture (avoids asyncio conflicts on Render):
  - Uses python-telegram-bot with webhooks tied to a FastAPI endpoint
  - Bot is initialized once and mounted at /api/telegram/webhook
  - Only responds to TELEGRAM_ALLOWED_USER_ID
  - Commands: /ping, /status, /pending, /approve <action_id>

Environment variables:
  TELEGRAM_BOT_TOKEN       – Bot token from @BotFather
  TELEGRAM_ALLOWED_USER_ID – Your Telegram user ID (integer)
  TELEGRAM_CHAT_ID         – Your Telegram chat ID (integer, same as user ID typically)
"""

from __future__ import annotations
import logging
import os
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


class TelegramBot:
    """Webhook-based Telegram bot for CopyVault monitoring."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.allowed_user_id = self._parse_int("TELEGRAM_ALLOWED_USER_ID")
        self.chat_id = self._parse_int("TELEGRAM_CHAT_ID", self.allowed_user_id)
        self._app: Optional[Application] = None

        if not self.token:
            logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
            self.enabled = False
        elif not self.allowed_user_id:
            logger.warning("TELEGRAM_ALLOWED_USER_ID not set — Telegram bot disabled (no auth)")
            self.enabled = False
        else:
            self.enabled = True

    def _parse_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        raw = os.getenv(key)
        if raw and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())
        return default

    def _is_authorized(self, user_id: int) -> bool:
        """Only allow the configured user ID."""
        return user_id == self.allowed_user_id

    async def send_message(self, text: str, chat_id: Optional[int] = None) -> None:
        """Send a proactive message (e.g., startup notification)."""
        if not self.enabled or not self._app:
            return
        target = chat_id or self.chat_id
        if not target:
            return
        try:
            await self._app.bot.send_message(chat_id=target, text=text)
            logger.info(f"Telegram message sent to {target}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    # ── Command handlers ─────────────────────────

    async def _cmd_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("CopyVault Bot is active!")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                portfolio = db.query(Portfolio).first()
                if not portfolio:
                    await update.message.reply_text("No portfolio found.")
                    return

                sym = "€" if portfolio.currency == "EUR" else "$"
                text = (
                    f"📊 *CopyVault Status*\n"
                    f"Total Value: {sym}{portfolio.total_value:,.2f}\n"
                    f"Invested: {sym}{portfolio.invested_amount:,.2f}\n"
                    f"Cash: {sym}{portfolio.available_cash:,.2f}\n"
                    f"Unrealized PnL: {sym}{portfolio.unrealized_pnl:,.2f}\n"
                    f"Realized PnL: {sym}{portfolio.realized_pnl:,.2f}\n"
                    f"Currency: {portfolio.currency}\n"
                    f"Mode: {'Simulation' if portfolio.is_simulation else 'Live'}\n"
                    f"Updated: {portfolio.last_updated.strftime('%Y-%m-%d %H:%M UTC') if portfolio.last_updated else 'Never'}"
                )
                await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Telegram /status error: {e}")
            await update.message.reply_text(f"Error fetching status: {e}")

    async def _cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        from backend.database.connection import db_session
        from backend.database.models import Alert

        try:
            with db_session() as db:
                alerts = (
                    db.query(Alert)
                    .filter(
                        Alert.severity.in_(["warning", "critical"]),
                        Alert.is_read.is_(False),
                    )
                    .order_by(Alert.created_at.desc())
                    .limit(5)
                    .all()
                )

                if not alerts:
                    await update.message.reply_text("No pending actions.")
                    return

                lines = ["⏳ *Pending Actions*"]
                for a in alerts:
                    lines.append(f"\n• [{a.severity.upper()}] {a.title}")
                    lines.append(f"  {a.created_at.strftime('%H:%M UTC')}")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Telegram /pending error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return

        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Usage: /approve <action_id>")
            return

        action_id = int(context.args[0])
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, AutomationRule, AutomationLog
        from backend.automation.automation_engine import AutomationEngine
        from backend.services.etoro_service import EToroSyncService

        engine = AutomationEngine()
        sync_service = EToroSyncService()

        try:
            with db_session() as db:
                # Find the rule
                rule = db.query(AutomationRule).filter(AutomationRule.id == action_id).first()
                if not rule:
                    await update.message.reply_text(f"No rule found with ID {action_id}.")
                    return

                portfolio = db.query(Portfolio).filter(Portfolio.id == rule.portfolio_id).first()
                if not portfolio:
                    await update.message.reply_text("Portfolio not found.")
                    return

                traders = [t for t in portfolio.copied_traders if t.is_active and not t.is_paused]

                # Re-evaluate the specific rule to get the action
                actions = engine.evaluate_rules(db, portfolio, traders)
                matching_action = next((a for a in actions if a.rule_id == action_id), None)

                if not matching_action:
                    await update.message.reply_text(
                        f"Rule '{rule.name}' is not currently triggered. "
                        "Conditions may no longer be met."
                    )
                    return

                # Execute on eToro
                await update.message.reply_text(f"Executing '{rule.name}' on eToro...")
                etoro_response = await engine.execute_etoro_action(
                    sync_service.client, matching_action, portfolio, db
                )
                success = not (etoro_response or {}).get("error", False)

                engine.log_execution(
                    db, portfolio, matching_action,
                    approved_by="telegram",
                    success=success,
                    etoro_response=etoro_response,
                )

                if success:
                    await update.message.reply_text(
                        f"✅ *{rule.name}* executed successfully.\n{matching_action.description}",
                        parse_mode="Markdown",
                    )
                else:
                    detail = (etoro_response or {}).get("detail", "Unknown error")
                    await update.message.reply_text(
                        f"❌ *{rule.name}* FAILED.\n{detail}",
                        parse_mode="Markdown",
                    )
        except Exception as e:
            logger.error(f"Telegram /approve error: {e}")
            await update.message.reply_text(f"Execution error: {e}")

    # ── Webhook setup ────────────────────────────

    def build_application(self) -> Optional[Application]:
        """Build and configure the Application (call once at startup)."""
        if not self.enabled:
            return None

        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("ping", self._cmd_ping))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("pending", self._cmd_pending))
        app.add_handler(CommandHandler("approve", self._cmd_approve))

        self._app = app
        logger.info(f"Telegram bot built — authorized user ID: {self.allowed_user_id}")
        return app

    def webhook_path(self) -> str:
        """FastAPI path for the webhook endpoint."""
        return f"/api/telegram/webhook"

    def webhook_url(self) -> str:
        """Full webhook URL for the bot."""
        base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
        return f"{base}{self.webhook_path()}"
