"""
Telegram Bot Integration
────────────────────────────────────────────────────────────────────
Provides portfolio monitoring and control via Telegram commands.
Uses python-telegram-bot for async handling.

Commands:
  /start     — Welcome and help
  /status    — Quick portfolio overview
  /portfolio — Full portfolio details
  /risk      — Current risk violations
  /traders   — List copied traders
  /performance — PnL summary
  /alerts    — Recent unread alerts
  /pause     — Emergency pause all automation
  /resume    — Resume automation rules
"""

from __future__ import annotations
import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
DEFAULT_PORTFOLIO_ID = int(os.getenv("DEFAULT_PORTFOLIO_ID", "1"))

try:
    from telegram import Update, Bot
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed — Telegram bot disabled")


class TelegramBot:
    """
    Async Telegram bot for portfolio monitoring.
    Communicates with the FastAPI backend via HTTP.
    """

    def __init__(self, token: str = TELEGRAM_BOT_TOKEN):
        self.token = token
        self.portfolio_id = DEFAULT_PORTFOLIO_ID
        self._app = None

    def start(self):
        """Start the Telegram bot (blocking)."""
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram bot not available — install python-telegram-bot")
            return
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — bot not started")
            return

        self._app = Application.builder().token(self.token).build()
        self._register_handlers()
        logger.info("Telegram bot starting…")
        self._app.run_polling()

    def _register_handlers(self):
        app = self._app
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("portfolio", self._cmd_portfolio))
        app.add_handler(CommandHandler("risk", self._cmd_risk))
        app.add_handler(CommandHandler("traders", self._cmd_traders))
        app.add_handler(CommandHandler("performance", self._cmd_performance))
        app.add_handler(CommandHandler("alerts", self._cmd_alerts))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))
        app.add_handler(CommandHandler("help", self._cmd_help))

    # ── Command handlers ─────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 *eToro Portfolio Assistant*\n\n"
            "I monitor your portfolio and alert you to important changes.\n\n"
            "Use /help to see available commands.",
            parse_mode="Markdown",
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = (
            "📋 *Available Commands*\n\n"
            "/status — Quick portfolio snapshot\n"
            "/portfolio — Full portfolio details\n"
            "/risk — Active risk violations\n"
            "/traders — Copied traders overview\n"
            "/performance — PnL summary\n"
            "/alerts — Recent unread alerts\n"
            "/pause — Emergency pause all automation\n"
            "/resume — Resume automation\n"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        portfolio = await self._get(f"/api/portfolios/{self.portfolio_id}")
        if not portfolio:
            await update.message.reply_text("❌ Could not fetch portfolio data.")
            return

        sign = "📈" if portfolio["daily_pnl"] >= 0 else "📉"
        text = (
            f"*Portfolio Status*\n\n"
            f"💼 Value: `${portfolio['total_value']:,.2f}`\n"
            f"{sign} Daily PnL: `${portfolio['daily_pnl']:+,.2f}`\n"
            f"📊 Health Score: `{portfolio['health_score']:.1f}/100`\n"
            f"{'🧪 SIMULATION MODE' if portfolio['is_simulation'] else '🔴 LIVE MODE'}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_portfolio(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        portfolio = await self._get(f"/api/portfolios/{self.portfolio_id}")
        if not portfolio:
            await update.message.reply_text("❌ Could not fetch portfolio data.")
            return

        text = (
            f"*📊 Portfolio Details*\n\n"
            f"💰 Total Value: `${portfolio['total_value']:,.2f}`\n"
            f"💵 Cash Available: `${portfolio['available_cash']:,.2f}`\n"
            f"📈 Unrealized PnL: `${portfolio['unrealized_pnl']:+,.2f}`\n"
            f"✅ Realized PnL: `${portfolio['realized_pnl']:+,.2f}`\n\n"
            f"*Performance:*\n"
            f"• Daily: `${portfolio['daily_pnl']:+,.2f}`\n"
            f"• Weekly: `${portfolio['weekly_pnl']:+,.2f}`\n"
            f"• Monthly: `${portfolio['monthly_pnl']:+,.2f}`\n\n"
            f"🏥 Health: `{portfolio['health_score']:.1f}/100`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_risk(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        data = await self._get(f"/api/portfolios/{self.portfolio_id}/risk/check")
        if data is None:
            await update.message.reply_text("❌ Risk check failed.")
            return

        violations = data.get("violations", [])
        if not violations:
            await update.message.reply_text("✅ No active risk violations. Portfolio looks healthy.")
            return

        lines = [f"⚠️ *{len(violations)} Risk Violation(s) Detected*\n"]
        for v in violations[:5]:
            icon = "🔴" if v.get("severity") == "critical" else "🟡"
            lines.append(f"{icon} *{v.get('title', 'Unknown')}*")
            lines.append(f"  {v.get('message', '')}")
            lines.append(f"  → _{v.get('suggested_action', '')}_\n")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_traders(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        traders = await self._get(f"/api/portfolios/{self.portfolio_id}/traders")
        if not traders:
            await update.message.reply_text("No copied traders found.")
            return

        lines = ["*👥 Copied Traders*\n"]
        for t in traders:
            status = "⏸ Paused" if t["is_paused"] else "▶️ Active"
            lines.append(
                f"*{t['trader_username']}* {status}\n"
                f"  Alloc: `${t['allocated_amount']:,.0f}` ({t['allocation_pct']:.1f}%)\n"
                f"  Return: `{t['total_return_pct']:+.1f}%` | Risk: `{t['risk_score']:.1f}/10`\n"
                f"  Class: _{t['risk_classification']}_\n"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_performance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        portfolio = await self._get(f"/api/portfolios/{self.portfolio_id}")
        if not portfolio:
            await update.message.reply_text("❌ Could not fetch data.")
            return

        total_invested = portfolio.get("invested_amount", 0)
        total_val = portfolio.get("total_value", 0)
        overall_pct = ((total_val - total_invested) / total_invested * 100) if total_invested else 0

        text = (
            f"*📈 Performance Summary*\n\n"
            f"Overall Return: `{overall_pct:+.2f}%`\n\n"
            f"• Daily: `${portfolio['daily_pnl']:+,.2f}`\n"
            f"• Weekly: `${portfolio['weekly_pnl']:+,.2f}`\n"
            f"• Monthly: `${portfolio['monthly_pnl']:+,.2f}`\n"
            f"• Unrealized: `${portfolio['unrealized_pnl']:+,.2f}`\n"
            f"• Realized: `${portfolio['realized_pnl']:+,.2f}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def _cmd_alerts(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        alerts = await self._get(
            f"/api/portfolios/{self.portfolio_id}/alerts?unread_only=true&limit=5"
        )
        if not alerts:
            await update.message.reply_text("✅ No unread alerts.")
            return

        lines = [f"🔔 *{len(alerts)} Unread Alert(s)*\n"]
        for a in alerts:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a["severity"], "⚪")
            lines.append(f"{icon} *{a['title']}*")
            lines.append(f"{a['message']}\n")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        result = await self._post(
            f"/api/portfolios/{self.portfolio_id}/automation/emergency-stop", {}
        )
        if result:
            await update.message.reply_text(
                f"⛔ *Emergency Stop Activated*\n"
                f"{result.get('rules_paused', 0)} automation rules paused.\n"
                "Use /resume to re-enable them.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("❌ Could not activate emergency stop.")

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # Resume is handled manually via the dashboard for safety
        await update.message.reply_text(
            "ℹ️ To resume automation, please use the web dashboard.\n"
            "Individual rules can be re-enabled from the Automation section.\n"
            "This is intentional — resuming after an emergency stop requires manual review.",
        )

    # ── HTTP helpers ─────────────────────────────

    async def _get(self, path: str) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{BACKEND_URL}{path}")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"GET {path} failed: {e}")
            return None

    async def _post(self, path: str, data: dict) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{BACKEND_URL}{path}", json=data)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"POST {path} failed: {e}")
            return None


# ──────────────────────────────────────────────
# Notification sender (called from backend)
# ──────────────────────────────────────────────

async def send_notification(chat_id: str, message: str):
    """Send a Telegram message to a specific chat ID."""
    if not TELEGRAM_AVAILABLE or not TELEGRAM_BOT_TOKEN:
        logger.debug(f"Telegram notification skipped: {message[:60]}")
        return

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")


# ──────────────────────────────────────────────
# Entry point (run as standalone)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    bot = TelegramBot()
    bot.start()
