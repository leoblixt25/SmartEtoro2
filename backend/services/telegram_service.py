"""
Telegram Bot Service
Smart portfolio assistant commands: monitor, analyze, decide.
"""

from __future__ import annotations
import asyncio
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
                overview = get_portfolio_overview(db, p.id)
                s = self._sym(overview.get("currency", "USD"))
                text = (
                    f"Portfolio Status\n\n"
                    f"Value: {s}{overview['total_value']:,.2f}\n"
                    f"Cash: {s}{overview['available_cash']:,.2f}\n"
                    f"Return: {overview['total_return_pct']:+.2f}%\n"
                    f"Active traders: {overview['active_traders']}\n"
                    f"Health: {overview['health_score']:.0f}/100\n"
                    f"Sentiment: {overview['sentiment']}\n"
                    f"Updated: {overview.get('last_sync', '\u2014')[:16] if overview.get('last_sync') else '\u2014'}"
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
                overview = get_portfolio_overview(db, p.id)
                traders = get_active_traders(db, p.id)
                s = self._sym(overview.get("currency", "USD"))

                lines = [f"Portfolio Summary\n"]
                lines.append(
                    f"Value: {s}{overview['total_value']:,.2f}  "
                    f"Cash: {s}{overview['available_cash']:,.2f}"
                )
                lines.append(
                    f"Return: {overview['total_return_pct']:+.2f}%  "
                    f"Health: {overview['health_score']:.0f}/100"
                )
                lines.append(
                    f"Active: {overview['active_traders']} traders  "
                    f"Sentiment: {overview['sentiment']}"
                )
                if overview.get("concentration_risk"):
                    lines.append("Concentration risk detected")

                if traders:
                    lines.append(f"\nActive Traders ({len(traders)}):")
                    for t in traders[:5]:
                        ret = t["total_return_pct"]
                        icon = "+" if ret >= 0 else ""
                        paused = " (paused)" if t.get("is_paused") else ""
                        lines.append(
                            f"  {t['username']}{paused} \u2014 "
                            f"{t['allocation_pct']:.1f}%  "
                            f"{icon}{ret:+.2f}%  "
                            f"risk {t['risk_score']:.1f}"
                        )

                if overview.get("last_sync"):
                    lines.append(f"\nLast sync: {overview['last_sync'][:16]}")

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
                traders = get_active_traders(db, p.id)
                if not traders:
                    await self._reply(update, "No active copied traders.")
                    return

                lines = [f"Active Traders ({len(traders)})\n"]
                for t in traders:
                    ret = t["total_return_pct"]
                    ret_icon = "+" if ret >= 0 else ""
                    paused = " (paused)" if t.get("is_paused") else ""
                    lines.append(
                        f"{t['username']}{paused}\n"
                        f"  Alloc: {t['allocation_pct']:.1f}%  "
                        f"Return: {ret_icon}{ret:+.2f}%\n"
                        f"  Risk: {t['risk_score']:.1f}/10  "
                        f"DD: {t['max_drawdown']:.1f}%"
                    )
                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/active error: {e}")
            await self._reply(update, f"Error: {e}")

    async def _cmd_discovery(self, update: Update, args: list[str]) -> None:
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

                live_usernames = set()
                if etoro_client and etoro_client.enabled:
                    port_data = await etoro_client.get_portfolio_data()
                    if port_data:
                        mirrors = port_data.get("clientPortfolio", {}).get("mirrors", [])
                        live_usernames = {m.get("parentUsername") for m in mirrors if m.get("parentUsername")}

                if live_usernames:
                    traders = (
                        db.query(CopiedTrader)
                        .filter(
                            CopiedTrader.portfolio_id == p.id,
                            CopiedTrader.trader_username.in_(live_usernames),
                        )
                        .all()
                    )
                else:
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

                results = []
                for t in traders:
                    trader_data = {
                        "username": t.trader_username,
                        "source": "tradeinfo" if t.trader_id else "unknown",
                        "confidence": 1.0,
                        "total_return_pct": t.total_return_pct,
                        "risk_score": t.risk_score,
                        "max_drawdown": t.max_drawdown,
                        "consistency_score": t.consistency_score,
                    }

                    holdings, holdings_source = await get_trader_holdings(
                        db, p.id, t.trader_username, etoro_client=etoro_client,
                    )
                    trader_data["_holdings_source"] = holdings_source
                    symbols = extract_symbols(holdings)
                    news_by_symbol = await fetch_news_for_symbols(symbols)

                    result = analyze_trader_health(trader_data, holdings, news_by_symbol)
                    results.append(result)

                    import asyncio
                    await asyncio.sleep(0.5)

                if not results:
                    await self._reply(update, "Health analysis complete. No signals to report.")
                    return

                summary = _build_health_summary(results, live=bool(live_usernames))
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
                alerts = get_alerts(db, p.id, unread_only=True, limit=5)
                if not alerts:
                    await self._reply(update, "No unread alerts.")
                    return

                lines = [f"Recent Alerts ({len(alerts)})\n"]
                for a in alerts:
                    icon = {"critical": "!", "warning": "\u26a0", "info": "i"}.get(
                        a["severity"], "?"
                    )
                    lines.append(
                        f"{icon} {a['title']}\n"
                        f"  {a['message'][:150]}"
                    )
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
            await self._reply(update, "Fetching watchlist...")

            sync_service = EToroSyncService()
            etoro_client = sync_service.client if sync_service.client.enabled else None

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                result = await run_monitoring_pipeline(
                    db, p.id, etoro_client=etoro_client,
                )

                summary = result.get("watchlist_summary", {})
                results = result.get("results", [])

                if not results:
                    await self._reply(update, "Watchlist is empty.")
                    return

                by_signal = summary.get("by_signal", {})
                lines = [f"Monitored Traders\n"]
                lines.append(
                    f"Increase: {by_signal.get('increase', 0)}  "
                    f"Hold: {by_signal.get('hold', 0)}  "
                    f"Reduce: {by_signal.get('reduce', 0)}  "
                    f"Watch: {by_signal.get('watch', 0)}\n"
                )

                for r in results:
                    lines.append(
                        f"{r['trader']} \u2014 {r['signal']} "
                        f"(score: {r.get('performance_score', 0):.0f})"
                    )

                overall = summary.get("sentiment", "neutral")
                lines.append(f"\nOverall sentiment: {overall}")

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

                text = (
                    f"Current Settings\n\n"
                    f"Portfolio ID: {p.id}\n"
                    f"Currency: {p.currency or 'USD'}\n"
                    f"Mode: {'Simulation' if p.is_simulation else 'Live'}\n"
                    f"Total Value: ${p.total_value:,.2f}\n"
                    f"Available Cash: ${p.available_cash:,.2f}\n\n"
                    f"Health Score: {p.health_score:.0f}/100\n"
                    f"Active Traders: {len([t for t in (p.copied_traders or []) if t.is_active and not t.is_paused])}\n\n"
                    f"Settings can be changed via the web dashboard."
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


def _short_reason(r: dict) -> str:
    """One-line reason for a trader."""
    warns = r.get("warning_signs", [])
    if warns:
        return warns[0].rstrip(".")
    dq = r.get("data_quality", "medium")
    perf = r.get("performance_summary", {})
    risk = r.get("risk_analysis", {})
    m = perf.get("month", {})
    ml = m.get("label", "N/A")
    ov = perf.get("overall_return")
    rl = risk.get("risk_label", "N/A")
    dd = risk.get("drawdown_label", "N/A")
    st = risk.get("stability", "N/A")

    if dq in ("insufficient", "low"):
        missing = []
        flags = r.get("data_flags", {})
        if not flags.get("performance"):
            missing.append("perf data")
        if not flags.get("risk"):
            missing.append("risk data")
        if not flags.get("holdings"):
            missing.append("holdings")
        if not flags.get("consistency"):
            missing.append("consistency")
        return f"Missing: {', '.join(missing[:2])}" if missing else "Low confidence"
    if rl == "High":
        return "High risk"
    if dd == "High":
        return "High drawdown"
    if st == "Volatile":
        return "Unstable returns"
    if st == "Unknown":
        return "Stability unknown"
    if ml not in ("N/A", "insufficient"):
        return f"Monthly: {ml}"
    if ov is not None:
        return f"Return: {ov:+.1f}%"
    if rl not in ("Unknown", "N/A"):
        return f"Risk: {rl}"
    return "Limited data"


def _build_health_summary(results: list[dict], live: bool = False) -> str:
    """Build a compact /health summary string."""
    total = len(results)

    buckets = {"Strong": [], "Good": [], "Watch": [], "Weak": [], "Avoid": []}
    for r in results:
        buckets.setdefault(r.get("health_status", "Watch"), []).append(r)

    _ic = "\U0001f4ca"
    _gn = "\U0001f7e2"
    _bl = "\U0001f535"
    _yw = "\U0001f7e1"
    _or = "\U0001f7e0"
    _rd = "\U0001f534"

    source_tag = "Live" if live else "Cached"
    lines = [f"{_ic} 7Health Report ({source_tag})"]
    lines.append(f"Scanned: {total} traders")
    lines.append(f"{_gn} Strong: {len(buckets['Strong'])}")
    lines.append(f"{_bl} Good: {len(buckets['Good'])}")
    lines.append(f"{_yw} Watch: {len(buckets['Watch'])}")
    lines.append(f"{_or} Weak: {len(buckets['Weak'])}")
    lines.append(f"{_rd} Avoid: {len(buckets['Avoid'])}")

    dq_counts = {"high": 0, "medium": 0, "low": 0, "insufficient": 0}
    for r in results:
        dq = r.get("data_quality", "medium")
        dq_counts[dq] = dq_counts.get(dq, 0) + 1
    lines.append(f"\n\U0001f4de Data Quality")
    lines.append(f"  High: {dq_counts['high']}")
    lines.append(f"  Medium: {dq_counts['medium']}")
    lines.append(f"  Low: {dq_counts['low']}")
    lines.append(f"  Incomplete: {dq_counts['insufficient']}")

    all_warnings = []
    for r in results:
        dq = r.get("data_quality", "medium")
        for w in r.get("warning_signs", []):
            text = w.rstrip(".")
            if dq in ("low", "insufficient") and "unknown" in text.lower():
                continue
            all_warnings.append((r["trader"], text))
    unique_risks = []
    seen = set()
    for trader, warn in all_warnings:
        key = warn.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_risks.append(f"- {trader} | {warn}")

    if unique_risks:
        lines.append(f"\n\U0001f6a8 Main Risks")
        for risk in unique_risks[:3]:
            lines.append(risk)

    STATUS_ICONS = {"Strong": _gn, "Good": _bl, "Watch": _yw, "Weak": _or, "Avoid": _rd}

    def trader_line(r: dict) -> str:
        score = r.get("health_score", 0)
        rec = r.get("recommendation", "KEEP")
        reason = _short_reason(r)
        status = r.get("health_status", "Watch")
        icon = STATUS_ICONS.get(status, "⚪")
        return f"{icon} {r['trader']} | {score:.0f}/100 | {rec} | {reason}"

    best = buckets["Strong"] + buckets["Good"]
    watch = buckets["Watch"]
    reduce_or_review = buckets["Weak"] + buckets["Avoid"]

    if best:
        lines.append(f"\n\U0001f3c6 Best Traders")
        for r in best:
            lines.append(trader_line(r))

    if watch:
        lines.append(f"\n\u26a0\ufe0f Traders to Watch")
        for r in watch:
            lines.append(trader_line(r))

    if reduce_or_review:
        lines.append(f"\n\u274c Traders to Reduce or Review")
        for r in reduce_or_review:
            lines.append(trader_line(r))

    has_neg_news = any(r.get("news_analysis", {}).get("impact") == "negative" for r in results)
    has_pos_news = any(r.get("news_analysis", {}).get("impact") == "positive" for r in results)
    if has_neg_news or has_pos_news:
        lines.append(f"\n\U0001f4f0 News Impact")
        if has_neg_news:
            lines.append("- Negative news risks on some holdings - monitor positions closely")
        if has_pos_news:
            lines.append("- Positive news on select holdings adds tailwinds")

    low_conf = dq_counts.get("low", 0) + dq_counts.get("insufficient", 0)
    high_conf = dq_counts.get("high", 0) + dq_counts.get("medium", 0)
    good_count = len(buckets["Strong"]) + len(buckets["Good"])
    bad_count = len(buckets["Weak"]) + len(buckets["Avoid"])

    if low_conf > high_conf:
        advice = "Most traders have incomplete data - focus on improving data quality before major decisions"
    elif good_count > bad_count and good_count >= total / 2:
        advice = "Portfolio is broadly healthy - continue copying with routine monitoring"
    elif bad_count > good_count:
        advice = "Multiple weak traders flagged - review before adding new positions"
    else:
        advice = "Mixed signals - monitor closely and follow per-trader actions"

    lines.append(f"\n\U0001f3af Final Recommendation")
    lines.append(f"- {advice}")

    return "\n".join(lines)
