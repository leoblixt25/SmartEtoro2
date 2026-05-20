"""
Telegram Bot Service
Smart portfolio assistant commands: monitor, analyze, decide.
"""

from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Tuple

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
        BotCommand("start", "Welcome and main menu"),
        BotCommand("status", "Quick portfolio snapshot"),
        BotCommand("overview", "Full portfolio summary"),
        BotCommand("active", "List active copied traders"),
        BotCommand("discovery", "New eligible traders to copy"),
        BotCommand("health", "Trader health analysis"),
        BotCommand("alerts", "Recent important alerts"),
        BotCommand("watchlist", "Monitored traders"),
        BotCommand("settings", "Current limits and preferences"),
        BotCommand("help", "Show all commands"),
    ]

    MAIN_KEYBOARD = [
        ["/status", "/overview"],
        ["/active", "/health"],
        ["/discovery", "/alerts"],
        ["/watchlist", "/settings"],
    ]

    async def setup_commands(self) -> None:
        if self._bot:
            try:
                await self._bot.set_my_commands(self.COMMANDS)
                logger.info("Telegram command menu registered")
            except Exception as e:
                logger.warning(f"Failed to register commands: {e}")

    def _keyboard(self) -> dict:
        return {"keyboard": self.MAIN_KEYBOARD, "resize_keyboard": True}

    def _parse_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        raw = os.getenv(key)
        if raw and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())
        return default

    def _is_authorized(self, user_id: int) -> bool:
        return user_id == self.allowed_user_id

    def _sym(self, currency: str) -> str:
        return "\u20ac" if currency == "EUR" else "$"

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

    async def _force_sync_before(self, db, portfolio) -> Tuple[bool, str, str]:
        """Force a live eToro sync and return (fresh, timestamp, label).

        Also checks return thresholds and triggers alerts after a successful sync.
        """
        from backend.services.etoro_service import EToroSyncService
        from backend.services.alert_service import check_return_thresholds
        now = datetime.utcnow()
        timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
        try:
            sync = EToroSyncService()
            ok = await sync.sync_portfolio_data(db, portfolio.id)
            if ok:
                await check_return_thresholds(db, portfolio.id, bot=self)
                return True, timestamp, "Live"
        except Exception as e:
            logger.error(f"Pre-command sync failed: {e}")
        return False, timestamp, "Cached"

    async def _reply(self, update: Update, text: str, **kwargs) -> None:
        markup = self._keyboard()
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML, **kwargs)

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
            "/start": self._cmd_start,
            "/status": self._cmd_status,
            "/overview": self._cmd_overview,
            "/active": self._cmd_active,
            "/discovery": self._cmd_discovery,
            "/health": self._cmd_health,
            "/alerts": self._cmd_alerts,
            "/watchlist": self._cmd_watchlist,
            "/settings": self._cmd_settings,
            "/help": self._cmd_help,
        }
        handler = handlers.get(command)
        if handler:
            await handler(update, args)
        else:
            await self._reply(
                update,
                "Unknown command. Send /help for available commands.",
            )

    # ── Commands ─────────────────────────────────

    async def _cmd_start(self, update: Update, args: list[str]) -> None:
        text = (
            "Welcome to your Smart Portfolio Assistant.\n\n"
            "I monitor your copied traders, check what they hold, "
            "analyse news, and warn you when action is needed.\n\n"
            "Quick start:\n"
            "/status \u2014 Portfolio snapshot\n"
            "/active \u2014 Your copied traders\n"
            "/health \u2014 Trader health analysis\n"
            "/discovery \u2014 New eligible traders\n"
            "/alerts \u2014 Important notifications\n\n"
            "Use the menu below or send /help for all commands."
        )
        await self._reply(update, text)

    async def _cmd_help(self, update: Update, args: list[str]) -> None:
        text = (
            "Available Commands\n\n"
            "/start \u2013 Welcome and main menu\n"
            "/status \u2013 Quick portfolio snapshot\n"
            "/overview \u2013 Full portfolio summary\n"
            "/active \u2013 List active copied traders\n"
            "/discovery \u2013 New eligible traders\n"
            "/health \u2013 Trader health analysis\n"
            "/alerts \u2013 Recent important alerts\n"
            "/watchlist \u2013 Monitored traders\n"
            "/settings \u2013 Current limits and preferences\n"
            "/help \u2013 Show this message"
        )
        await self._reply(update, text)

    async def _cmd_status(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.portfolio_service import get_portfolio_overview

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                fresh, ts, label = await self._force_sync_before(db, p)
                overview = get_portfolio_overview(db, p.id)
                s = self._sym(overview.get("currency", "USD"))
                ret = overview['total_return_pct']
                ret_icon = "\U0001f4c8" if ret >= 0 else "\U0001f4c9"
                health = overview['health_score']
                health_icon = "\U0001f7e2" if health >= 70 else ("\U0001f7e1" if health >= 40 else "\U0001f534")
                text = (
                    f"\U0001f4ca <b>Portfolio Status</b>\n"
                    f"{s}<b>{overview['total_value']:,.2f}</b>  "
                    f"\U0001f4b0 {s}{overview['available_cash']:,.2f}\n"
                    f"{ret_icon} <b>{ret:+.2f}%</b>  "
                    f"{health_icon} Health <b>{health:.0f}/100</b>\n"
                    f"\U0001f465 <b>{overview['active_traders']}</b> traders  "
                    f"\U0001f4a1 {overview['sentiment']}\n"
                    f"\U0001f4c5 {ts} ({label})"
                )
                await self._reply(update, text)
        except Exception as e:
            logger.error(f"/status error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_overview(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.portfolio_service import get_portfolio_overview, get_active_traders

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                fresh, ts, label = await self._force_sync_before(db, p)
                overview = get_portfolio_overview(db, p.id)
                traders = get_active_traders(db, p.id)
                s = self._sym(overview.get("currency", "USD"))
                ret = overview['total_return_pct']
                ret_icon = "\U0001f4c8" if ret >= 0 else "\U0001f4c9"
                health = overview['health_score']
                health_icon = "\U0001f7e2" if health >= 70 else ("\U0001f7e1" if health >= 40 else "\U0001f534")

                lines = [f"\U0001f4ca <b>Portfolio Summary</b>\n"]
                lines.append(
                    f"\U0001f4b0 <b>{s}{overview['total_value']:,.2f}</b>  "
                    f"\U0001f4b5 Cash {s}{overview['available_cash']:,.2f}"
                )
                lines.append(
                    f"{ret_icon} <b>{ret:+.2f}%</b>  "
                    f"{health_icon} Health <b>{health:.0f}/100</b>"
                )
                lines.append(
                    f"\U0001f465 <b>{overview['active_traders']}</b> traders  "
                    f"\U0001f4a1 {overview['sentiment']}"
                )
                if overview.get("concentration_risk"):
                    lines.append("\u26a0\ufe0f Concentration risk detected")

                if traders:
                    lines.append(f"\n\U0001f465 <b>Active Traders ({len(traders)})</b>")
                    for t in traders:
                        ret = t["total_return_pct"]
                        pnl_icon = "\U0001f7e2" if ret >= 0 else "\U0001f534"
                        ret_str = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
                        paused = " \u23f8\ufe0f paused" if t.get("is_paused") else ""
                        lines.append(
                            f"{pnl_icon} <b>{t['username']}</b>{paused}  "
                            f"\U0001f4ca {t['allocation_pct']:.1f}%  "
                            f"\U0001f4c8 {ret_str}  "
                            f"\u26a0\ufe0f {t['risk_score']:.1f}"
                        )

                lines.append(f"\n\U0001f4c5 {ts} ({label})")

                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/overview error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_active(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.portfolio_service import get_active_traders

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                fresh, ts, label = await self._force_sync_before(db, p)
                traders = get_active_traders(db, p.id)

                if not traders:
                    await self._reply(update, "No active copied traders.")
                    return

                lines = [f"\U0001f465 <b>Active Traders ({len(traders)})</b>\n"]
                for t in traders:
                    ret = t["total_return_pct"]
                    pnl_icon = "\U0001f7e2" if ret >= 0 else "\U0001f534"
                    ret_str = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
                    paused = " \u23f8\ufe0f paused" if t.get("is_paused") else ""
                    dd = t.get("max_drawdown", 0)
                    dd_icon = "\U0001f7e2" if dd < 10 else ("\U0001f7e1" if dd < 18 else "\U0001f534")
                    lines.append(
                        f"{pnl_icon} <b>{t['username']}</b>{paused}\n"
                        f"    \U0001f4ca <b>{t['allocation_pct']:.1f}%</b>  "
                        f"\U0001f4c8 <b>{ret_str}</b>\n"
                        f"    \u26a0\ufe0f Risk {t['risk_score']:.1f}/10  "
                        f"{dd_icon} DD {dd:.1f}%"
                    )
                lines.append(f"\n\U0001f4c5 {ts} ({label})")
                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/active error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_discovery(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.screener_service import run_screener_and_wait
        from backend.discovery.config import SCAN_PRESETS

        # Parse optional scan level from args, e.g. /discovery 5000
        scan_target = 10000
        if args:
            try:
                parsed = int(args[0])
                valid = set(SCAN_PRESETS.values())
                if parsed in valid:
                    scan_target = parsed
                else:
                    valid_str = ", ".join(str(v) for v in sorted(valid))
                    await self._reply(update, f"Invalid scan level. Use one of: {valid_str}")
                    return
            except ValueError:
                await self._reply(update, "Usage: /discovery [scan_level] where scan_level is 500, 2000, 5000, or 10000")
                return

        # Lock to prevent concurrent discovery commands
        if not hasattr(self, "_discovery_lock"):
            self._discovery_lock = asyncio.Lock()
        if self._discovery_lock.locked():
            logger.info("Discovery command already running — skipping duplicate")
            return

        async with self._discovery_lock:
            status_msg = None
            try:
                with db_session() as db:
                    p = db.query(Portfolio).first()
                    if p:
                        await self._force_sync_before(db, p)

                status_msg = await update.message.reply_text(
                    f"\U0001f50d Scanning up to {scan_target:,} traders... please wait",
                    reply_markup=self._keyboard(),
                )

                eligible, excluded, stats = await run_screener_and_wait(
                    scan_target=scan_target, top_n=10, max_concurrent=10,
                )

                text = self._build_discovery_message(eligible, stats)
                if status_msg:
                    try:
                        await status_msg.edit_text(text, parse_mode="HTML")
                    except Exception:
                        await self._reply(update, text)
                else:
                    await self._reply(update, text)

            except Exception as e:
                logger.error(f"/discovery error: {e}")
                if status_msg:
                    try:
                        await status_msg.edit_text(f"Error: {e}")
                    except Exception:
                        pass
                await self._reply(update, f"Error: {e}")

    def _build_discovery_message(self, eligible: list, stats: dict) -> str:
        scanned = stats.get("total_scanned", stats.get("discovered", 0))
        eligible_count = stats.get("eligible", stats.get("final_count", len(eligible)))
        now = datetime.now().strftime("%b %d, %H:%M UTC")

        lines = [
            "\U0001f3c6 <b>TOP COPY TRADERS</b>",
            f"\U0001f4c5 <b>{now}</b>",
            f"\U0001f4ca <b>{scanned} Scanned</b> \u2022 \u2705 <b>Real Data Only</b>",
            "",
        ]

        if eligible:
            medals = ["\U0001f947", "\U0001f948", "\U0001f949", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
            for i, t in enumerate(eligible[:5]):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                username = t.get("username", "?")
                score = t.get("final_score", t.get("score", 0))
                ret = t.get("total_return_pct")
                risk = t.get("risk_score")
                dd = t.get("peak_to_valley") or t.get("max_drawdown")
                prof_months = t.get("profitable_months_pct")
                weeks = t.get("weeks_since_registration")

                ret_str = f"+{ret:.1f}%" if ret is not None else "N/A"
                risk_str = f"{int(risk)}/10" if risk is not None else "N/A"
                dd_abs = abs(dd) if dd is not None else None
                dd_str = f"{dd_abs:.1f}%" if dd_abs is not None else "N/A"

                comp = t.get("details", {}).get("components", {})

                is_high_ret = ret is not None and ret > 100
                is_mod_ret = ret is not None and 50 < ret <= 100
                is_low_ret = ret is not None and ret <= 50
                is_low_risk = risk is not None and risk <= 3
                is_mod_risk = risk is not None and 4 <= risk <= 5
                is_low_dd = dd_abs is not None and dd_abs < 10
                is_mod_dd = dd_abs is not None and 10 <= dd_abs < 18
                is_high_dd = dd_abs is not None and dd_abs >= 18
                is_high_cons = prof_months is not None and prof_months > 70
                is_long_exp = weeks is not None and weeks >= 156

                if is_high_ret and is_low_risk and is_low_dd:
                    insight = "Elite risk-adjusted returns."
                elif is_high_ret and is_mod_risk and is_low_dd:
                    insight = "Strong return with controlled risk."
                elif is_high_ret and is_mod_risk and is_mod_dd and is_high_cons:
                    insight = "High returns with reliable consistency."
                elif is_high_ret and is_mod_risk and is_mod_dd:
                    insight = "Good return with manageable drawdown."
                elif is_high_ret and is_mod_risk and is_high_dd:
                    insight = "Strong returns but elevated drawdown."
                elif is_high_ret and (risk is not None and risk > 5):
                    insight = "Aggressive profile with high upside."
                elif is_high_cons and is_mod_ret:
                    insight = "Remarkable consistency."
                elif is_high_cons and is_low_dd and is_mod_ret:
                    insight = "Consistency plus capital preservation."
                elif is_low_risk and is_low_dd and is_high_cons:
                    insight = "Textbook capital preservation."
                elif is_low_risk and is_low_dd:
                    insight = "Very stable with low drawdown."
                elif is_low_risk and is_mod_ret:
                    insight = "Solid and disciplined risk taker."
                elif is_mod_ret and is_mod_risk and is_low_dd:
                    insight = "Solid returns with capital preservation."
                elif is_mod_ret and is_mod_risk and is_mod_dd:
                    insight = "Consistent long-term performer."
                elif is_long_exp and is_low_dd:
                    insight = "Proven stability over years."
                elif is_long_exp and is_mod_ret:
                    insight = "Reliable veteran performer."
                elif is_high_cons and is_high_ret:
                    insight = "Rare combo of consistency and returns."
                elif is_low_ret:
                    insight = "Low return profile, limited upside."
                else:
                    insight = "Balanced across key metrics."

                ret_c = comp.get("return", 0)
                ra_c = comp.get("risk_adjusted", 0)
                cons_c = comp.get("consistency", 0)
                dd_c = comp.get("drawdown", 0)
                risk_c = comp.get("risk", 0)

                lines.append(
                    f'{medal} <b>{username}</b> \u2b50 <b>{score:.0f}/100</b>'
                )
                lines.append(
                    f'\U0001f4c8 <b>{ret_str}</b> \u2022 \u26a0\ufe0f Risk <b>{risk_str}</b> \u2022 \U0001f4c9 DD <b>{dd_str}</b>'
                )
                lines.append(
                    f'\U0001f4ca Ret:{ret_c:.0f} RA:{ra_c:.0f} Con:{cons_c:.0f} DD:{dd_c:.0f} Rsk:{risk_c:.0f}'
                )
                lines.append(f'\U0001f4a1 {insight}')
                lines.append('\u2501' * 16)

            def _balance_score(t):
                c = t.get("details", {}).get("components", {})
                return (
                    c.get("consistency", 0) * 0.30
                    + c.get("drawdown", 0) * 0.25
                    + c.get("risk_adjusted", 0) * 0.20
                    + c.get("return", 0) * 0.15
                )

            top = max(eligible, key=_balance_score)
            top_user = top.get("username", "?")
            top_ret = top.get("total_return_pct")
            top_risk = top.get("risk_score")
            top_dd = top.get("peak_to_valley") or top.get("max_drawdown")
            top_comp = top.get("details", {}).get("components", {})
            top_cons = top_comp.get("consistency", 0)
            top_dd_val = top_comp.get("drawdown", 0)
            top_ra = top_comp.get("risk_adjusted", 0)

            best_reason = "Most well-rounded performer."
            if top_cons >= 70 and top_dd_val >= 70 and top_ra >= 60:
                best_reason = "Best mix of safety, consistency, and efficiency."
            elif top_cons >= 60 and top_dd_val >= 70:
                best_reason = "Strongest capital preservation with consistency."
            elif top_cons >= 60 and top_dd_val >= 60 and top_ra >= 60:
                best_reason = "Well-balanced with solid risk-adjusted returns."
            elif top_ra >= 60 and top_dd_val >= 60:
                best_reason = "Top-tier risk-adjusted returns."
            elif top_cons >= 50 and top_dd_val >= 50:
                best_reason = "Reliable performer with controlled downside."
            elif top_ret is not None and top_ret > 80 and (top_risk is None or top_risk <= 5):
                best_reason = "Top return with acceptable risk."

            lines.append("")
            lines.append(f"\U0001f3af <b>BEST PICK</b>")
            lines.append(f"<b>{top_user}</b> \u2192 {best_reason}")
            lines.append(f"\U0001f4cc <b>{eligible_count} eligible traders</b> from <b>{scanned} scanned</b>")
        else:
            lines.append("No eligible traders found at this time.")

        return "\n".join(lines)

    async def _cmd_health(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader
        from backend.monitoring.trader_health_engine import analyze_trader_health
        from backend.monitoring.ai_health_engine import ai_analyze_traders
        from backend.monitoring.holding_parser import get_trader_holdings, extract_symbols
        from backend.monitoring.news_service import fetch_news_for_symbols
        from backend.services.etoro_service import EToroSyncService

        try:
            await self._reply(update, "Analysing trader health...")

            sync_service = EToroSyncService()
            etoro_client = sync_service.client if sync_service.client.enabled else None

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                freshness, ts, label = await self._force_sync_before(db, p)

                traders = (
                    db.query(CopiedTrader)
                    .filter(
                        CopiedTrader.portfolio_id == p.id,
                        CopiedTrader.is_active.is_(True),
                        CopiedTrader.is_paused.is_(False),
                    )
                    .all()
                )

                if not traders:
                    await self._reply(update, "No active traders to analyse.")
                    return

                # First pass: collect all data for each trader
                enriched = []
                for t in traders:
                    trader_data = {
                        "username": t.trader_username,
                        "source": "tradeinfo" if t.trader_id else "unknown",
                        "confidence": 1.0,
                        "total_return_pct": t.total_return_pct,
                        "return_1m": t.avg_monthly_return,
                        "return_1w": getattr(t, 'return_1w', None),
                        "return_1d": getattr(t, 'return_1d', None),
                        "risk_score": t.risk_score,
                        "max_drawdown": t.max_drawdown,
                        "consistency_score": t.consistency_score,
                        "volatility": t.volatility,
                        "sharpe_score": t.sharpe_score,
                        "diversification_score": t.diversification_score,
                        "allocation_pct": t.allocation_pct,
                    }

                    holdings, holdings_source = await get_trader_holdings(
                        db, p.id, t.trader_username, etoro_client=etoro_client,
                    )
                    trader_data["_holdings_source"] = holdings_source
                    trader_data["_holdings"] = holdings
                    symbols = extract_symbols(holdings)
                    news_by_symbol = await fetch_news_for_symbols(symbols)
                    trader_data["_news_by_symbol"] = news_by_symbol
                    news_summary = "N/A"
                    if news_by_symbol:
                        pos = sum(1 for v in news_by_symbol.values() if any(a.get("sentiment") == "positive" for a in v))
                        neg = sum(1 for v in news_by_symbol.values() if any(a.get("sentiment") == "negative" for a in v))
                        news_summary = f"{pos} pos, {neg} neg symbols"
                    trader_data["_news_summary"] = news_summary
                    enriched.append(trader_data)

                    import asyncio
                    await asyncio.sleep(0.5)

                # Try AI analysis on the full batch
                ai_results = await ai_analyze_traders(enriched)

                results = []
                if ai_results:
                    # Map AI results back to enriched data
                    ai_by_name = {r.get("name", "").lower(): r for r in ai_results}
                    _STATUS_NORM = {"ELITE": "Strong", "STRONG": "Strong", "GOOD": "Good",
                                    "WATCH": "Watch", "WEAK": "Weak", "AVOID": "Avoid",
                                    "INCOMPLETE": "Incomplete"}
                    for td in enriched:
                        name = td["username"].lower()
                        ai_r = ai_by_name.get(name, {})
                        raw_status = (ai_r.get("status") or "INCOMPLETE").upper()
                        norm_status = _STATUS_NORM.get(raw_status, "Incomplete")
                        results.append({
                            "name": td["username"],
                            "trader": td["username"],
                            "score": ai_r.get("score"),
                            "health_score": ai_r.get("score"),
                            "confidence": ai_r.get("confidence", "LOW"),
                            "status": norm_status,
                            "health_status": norm_status,
                            "data_quality": "low" if ai_r.get("confidence") in ("LOW", "INCOMPLETE") else "medium",
                            "action": ai_r.get("action", "REVIEW"),
                            "recommendation": ai_r.get("action", "REVIEW"),
                            "signal": "increase" if ai_r.get("action") == "KEEP" else ("reduce" if ai_r.get("action") == "REDUCE" else "watch"),
                            "reason": ai_r.get("reason", "AI analysis"),
                            "performance": ai_r.get("performance", {"day": None, "week": None, "month": None}),
                            "risk": ai_r.get("risk", {"drawdown": None, "risk_score": None, "leverage": None, "concentration": None}),
                            "risk_analysis": {},
                            "news_exposure": {"level": ai_r.get("news_risk", "unknown"), "summary": ""},
                            "news_analysis": {"impact": ai_r.get("news_risk", "unknown"), "details": td.get("_news_summary", "")},
                            "holdings_count": len(td.get("_holdings", [])),
                            "total_return_pct": td.get("total_return_pct"),
                            "allocation_pct": td.get("allocation_pct"),
                            "holdings_source": td.get("_holdings_source", "unknown"),
                            "data_flags": {},
                            "portfolio_concentration": {"warning": "Well diversified"},
                        })
                else:
                    # Fall back to rule-based engine
                    for td in enriched:
                        result = analyze_trader_health(td, td.get("_holdings", []), td.get("_news_by_symbol", {}))
                        results.append(result)

                if not results:
                    await self._reply(update, "Health analysis complete. No signals to report.")
                    return

                summary = _build_health_summary(results, live=freshness, source_label=label, ts=ts)
                await self._reply(update, summary)
        except Exception as e:
            logger.error(f"/health error: {e}")
            await self._reply(update, f"Health analysis failed: {e}")

    async def _cmd_alerts(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.alert_service import get_alerts

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return
                fresh, ts, label = await self._force_sync_before(db, p)
                alerts = get_alerts(db, p.id, unread_only=True, limit=5)
                if not alerts:
                    await self._reply(update, "\u2705 No unread alerts.")
                    return

                severity_icons = {"critical": "\U0001f534", "warning": "\u26a0\ufe0f", "info": "\U0001f7e1"}
                lines = [f"\U0001f514 <b>Recent Alerts ({len(alerts)})</b>\n"]
                for a in alerts:
                    icon = severity_icons.get(a["severity"], "\u2753")
                    lines.append(
                        f"{icon} <b>{a['title']}</b>\n"
                        f"  {a['message'][:200]}"
                    )
                lines.append(f"\n\U0001f4c5 {ts} ({label})")
                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/alerts error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_watchlist(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.monitoring.orchestrator import run_monitoring_pipeline
        from backend.services.etoro_service import EToroSyncService

        try:
            await self._reply(update, "\U0001f50d Fetching watchlist...")

            sync_service = EToroSyncService()
            etoro_client = sync_service.client if sync_service.client.enabled else None

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                fresh, ts, label = await self._force_sync_before(db, p)

                result = await run_monitoring_pipeline(
                    db, p.id, etoro_client=etoro_client,
                )

                summary = result.get("watchlist_summary", {})
                results = result.get("results", [])

                if not results:
                    await self._reply(update, "\U0001f4ed Watchlist is empty.")
                    return

                by_signal = summary.get("by_signal", {})
                signal_icons = {"increase": "\U0001f7e2", "hold": "\U0001f7e1", "reduce": "\U0001f534", "watch": "\U0001f50d"}
                lines = [f"\U0001f6e1\ufe0f <b>Monitored Traders</b>\n"]
                signal_parts = []
                for sig, count in by_signal.items():
                    icon = signal_icons.get(sig, "\u2753")
                    signal_parts.append(f"{icon} {sig} <b>{count}</b>")
                lines.append("  ".join(signal_parts))

                for r in results:
                    sig = r.get("signal", "watch")
                    sig_icon = signal_icons.get(sig, "\U0001f50d")
                    score = r.get("performance_score", 0)
                    lines.append(
                        f"\n{sig_icon} <b>{r['trader']}</b> \u2014 {sig} "
                        f"(\U0001f4ca {score:.0f})"
                    )

                lines.append(f"\n\U0001f4c5 {ts} ({label})")

                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/watchlist error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_settings(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio

        try:
            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                fresh, ts, label = await self._force_sync_before(db, p)
                mode_icon = "\U0001f6e1\ufe0f" if not p.is_simulation else "\U0001f6f0\ufe0f"
                active = len([t for t in (p.copied_traders or []) if t.is_active and not t.is_paused])
                health = p.health_score or 0
                health_icon = "\U0001f7e2" if health >= 70 else ("\U0001f7e1" if health >= 40 else "\U0001f534")

                text = (
                    f"\u2699\ufe0f <b>Settings</b>\n"
                    f"\U0001f3e6 Portfolio <b>#{p.id}</b>  "
                    f"\U0001f4b1 {p.currency or 'USD'}  "
                    f"{mode_icon} {'Sim' if p.is_simulation else 'Live'}\n"
                    f"\U0001f4b0 <b>${p.total_value:,.2f}</b>  "
                    f"\U0001f4b5 ${p.available_cash:,.2f}\n"
                    f"{health_icon} Health <b>{health:.0f}/100</b>  "
                    f"\U0001f465 <b>{active}</b> active\n"
                    f"\U0001f4c5 {ts} ({label})"
                )
                await self._reply(update, text)
        except Exception as e:
            logger.error(f"/settings error: {e}")
            await self._reply(update, f"Error: {e}")

    # ── Webhook helpers ──────────────────────────

    def webhook_path(self) -> str:
        return "/api/telegram/webhook"

    def webhook_url(self) -> str:
        base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
        return f"{base}{self.webhook_path()}"





def _build_health_summary(results: list[dict], live: bool = False, source_label: str = "Cached", ts: str = "") -> str:
    def ret_val(r):
        tr = r.get("total_return_pct")
        if tr is not None and tr != 0:
            return tr
        perf = r.get("performance", {})
        for k in ("month", "week", "day"):
            v = perf.get(k)
            if v is not None and v != 0:
                return v
        ps = r.get("performance_summary", {})
        ov = ps.get("overall_return")
        if ov is not None and ov != 0:
            return ov
        return 0.0

    def ret_str(v):
        return f"{v:+.1f}%" if v else "0.0%"

    uncopy = []
    keep = []
    watch = []
    for r in results:
        ret = ret_val(r)
        alloc = r.get("allocation_pct") or 0
        name = r.get("trader", "?")
        entry = (name, ret, alloc, r)
        if ret < -1.0 and alloc > 5:
            uncopy.append(entry)
        elif ret < -3.0:
            uncopy.append(entry)
        elif ret > 0.5:
            keep.append(entry)
        else:
            watch.append(entry)

    uncopy.sort(key=lambda x: -(x[2] * abs(x[1])))
    keep.sort(key=lambda x: -x[1])
    watch.sort(key=lambda x: -x[1])

    total = len(results)
    source_tag = source_label if source_label else ("Live" if live else "Cached")
    pos = len(keep)
    neg = sum(1 for r in results if ret_val(r) < 0)
    flat = total - pos - neg

    lines = [f"\U0001f4ca <b>Health \u2014 {total} traders</b> ({source_tag})"]
    lines.append(f"\u2705 {pos} good  \u274c {neg} bad  \u26aa {flat} flat\n")

    if uncopy:
        lines.append(f"\u274c <b>UNCOPY</b> \u2014 losing on big positions")
        for name, ret, alloc, _ in uncopy:
            lines.append(
                f"\U0001f534 <b>{name}</b>  "
                f"\U0001f4c9 <b>{ret_str(ret)}</b>  "
                f"\U0001f4ca {alloc:.0f}% alloc"
            )
        lines.append("")

    if keep:
        lines.append(f"\u2705 <b>KEEP</b> \u2014 making money")
        for name, ret, alloc, _ in keep:
            pct = f"  \U0001f4ca {alloc:.0f}%" if alloc else ""
            lines.append(
                f"\U0001f7e2 <b>{name}</b>  "
                f"\U0001f4c8 <b>{ret_str(ret)}</b>{pct}"
            )
        lines.append("")

    if watch:
        lines.append(f"\U0001f50d <b>WATCH</b> \u2014 flat or tiny positions")
        for name, ret, alloc, _ in watch:
            pct = f"  \U0001f4ca {alloc:.0f}%" if alloc else ""
            lines.append(
                f"\U0001f7e1 <b>{name}</b>  "
                f"{ret_str(ret)}{pct}"
            )

    if uncopy:
        lines.append(f"\n\U0001f6a8 <b>Action:</b> UNCOPY <b>{uncopy[0][0]}</b> first ({uncopy[0][1]:+.1f}% at {uncopy[0][2]:.0f}% alloc)")
    elif not keep:
        lines.append(f"\n\U0001f6a8 <b>No traders making money</b> \u2014 review entire portfolio")
    elif len(keep) >= total * 0.6:
        lines.append(f"\n\U0001f535 <b>Portfolio healthy</b> \u2014 {pos}/{total} profitable")

    if ts:
        lines.append(f"\n\U0001f4c5 {ts} ({source_tag})")

    return "\n".join(lines)


def _collect_risks(results: list[dict]) -> list[str]:
    """Collect unique, meaningful portfolio-level risks."""
    risks = []
    seen = set()
    limited_data_traders = []

    for r in results:
        ra = r.get("risk_analysis", {})
        dd = ra.get("drawdown")
        rs = ra.get("risk_score")

        if dd and dd.get("level") in ("Elevated", "High"):
            text = f"{r['trader']}: Drawdown {dd['value']:.0f}% ({dd['level']})"
            key = text.lower()
            if key not in seen:
                seen.add(key)
                risks.append(text)

        if rs and rs.get("level") in ("High", "Critical"):
            text = f"{r['trader']}: Risk score {rs['value']:.1f} ({rs['level']})"
            key = text.lower()
            if key not in seen:
                seen.add(key)
                risks.append(text)

        pconc = r.get("portfolio_concentration", {})
        cw = pconc.get("warning")
        if cw and cw != "Well diversified":
            key = cw.lower().rstrip(".")
            if key not in seen:
                seen.add(key)
                risks.append(cw.rstrip("."))

        action = r.get("recommendation")
        dq = r.get("data_quality")
        if action == "REVIEW" and dq in ("low", "insufficient"):
            limited_data_traders.append(r['trader'])

    if limited_data_traders:
        if len(limited_data_traders) <= 3:
            for name in limited_data_traders:
                risks.append(f"{name}: Weak signal but limited data \u2014 manual check needed")
        else:
            risks.append(f"{len(limited_data_traders)} traders with limited data \u2014 manual checks needed")
            for name in limited_data_traders[:3]:
                risks.append(f"  {name}: check needed")

    return risks
