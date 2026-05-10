"""
Telegram Bot Service
────────────────────────────────────────────────────────────────────
Webhook-based Telegram bot for monitoring and approving automation rules.

Architecture:
  - Uses raw telegram.Bot (no Application/Dispatcher which has __slots__ issues on Py3.14)
  - Webhook dispatch via FastAPI endpoint
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

logger = logging.getLogger(__name__)

# Import telegram.Bot only — avoids Application.__slots__ bug on Python 3.14
try:
    import telegram
    from telegram import Bot, Update
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed")


class TelegramBot:
    """Webhook-based Telegram bot for CopyVault monitoring."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.allowed_user_id = self._parse_int("TELEGRAM_ALLOWED_USER_ID")
        self.chat_id = self._parse_int("TELEGRAM_CHAT_ID", self.allowed_user_id)
        self._bot: Optional[Bot] = None

        if not TELEGRAM_AVAILABLE:
            logger.info("python-telegram-bot not available")
            self.enabled = False
        elif not self.token:
            logger.info("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
            self.enabled = False
        elif not self.allowed_user_id:
            logger.warning("TELEGRAM_ALLOWED_USER_ID not set — Telegram bot disabled (no auth)")
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

    async def send_message(self, text: str, chat_id: Optional[int] = None) -> None:
        """Send a proactive message (e.g., startup notification)."""
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
        """Process an incoming Telegram update webhook payload."""
        if not self.enabled or not self._bot:
            return

        try:
            update = Update.de_json(payload, self._bot)
        except Exception as e:
            logger.error(f"Failed to parse Telegram update: {e}")
            return

        if not update.message or not update.message.text:
            return

        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or not self._is_authorized(user_id):
            logger.debug(f"Ignored message from unauthorized user {user_id}")
            return

        text = update.message.text.strip()
        if not text.startswith("/"):
            return

        parts = text.split()
        command = parts[0].lower()
        args = parts[1:]

        handlers = {
            "/ping": self._cmd_ping,
            "/status": self._cmd_status,
            "/pending": self._cmd_pending,
            "/approve": self._cmd_approve,
        }

        handler = handlers.get(command)
        if handler:
            await handler(update, args)
        else:
            await update.message.reply_text(
                f"Unknown command: {command}\nAvailable: /ping, /status, /pending, /approve <id>"
            )

    # ── Command handlers ─────────────────────────

    async def _cmd_ping(self, update: Update, args: list[str]) -> None:
        await update.message.reply_text("CopyVault Bot is active!")

    async def _cmd_status(self, update: Update, args: list[str]) -> None:
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

    async def _cmd_pending(self, update: Update, args: list[str]) -> None:
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

    async def _cmd_approve(self, update: Update, args: list[str]) -> None:
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /approve <action_id>")
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
                matching_action = next((a for a in actions if a.rule_id == action_id), None)

                if not matching_action:
                    await update.message.reply_text(
                        f"Rule '{rule.name}' is not currently triggered. "
                        "Conditions may no longer be met."
                    )
                    return

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

    # ── Webhook helpers ──────────────────────────

    def webhook_path(self) -> str:
        return "/api/telegram/webhook"

    def webhook_url(self) -> str:
        base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
        return f"{base}{self.webhook_path()}"
