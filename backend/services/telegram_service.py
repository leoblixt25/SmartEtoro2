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
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.services.discovery_service import discover_eligible_traders

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
                    "\U0001f50d Scanning traders... please wait",
                    reply_markup=self._keyboard(),
                )
                with db_session() as db:
                    p = db.query(Portfolio).first()
                    if not p:
                        text = "No portfolio found."
                        if status_msg:
                            try:
                                await status_msg.edit_text(text, parse_mode="HTML")
                            except Exception:
                                await self._reply(update, text)
                        else:
                            await self._reply(update, text)
                        return

                    eligible, excluded, stats = await discover_eligible_traders(db, p.id)

                scanned = stats.get("total_scanned", 0)
                eligible_count = stats.get("eligible", 0)
                now = datetime.now().strftime("%b %d, %H:%M UTC")

                lines = [
                    "\U0001f3c6 <b>TOP COPY TRADERS SCAN</b>",
                    f"\U0001f4c5 <b>{now}</b> | \U0001f4ca <b>{scanned} scanned</b> | \u2705 <b>Real data</b> | \U0001f3af <b>{eligible_count} passed</b>",
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
                        positions = t.get("positions_count")

                        ret_str = f"+{ret:.1f}%" if ret is not None else "N/A"
                        risk_str = f"{int(risk)}/10" if risk is not None else "N/A"
                        dd_abs = abs(dd) if dd is not None else None
                        dd_str = f"{dd_abs:.1f}%" if dd_abs is not None else "N/A"

                        present = sum(1 for f in [ret, risk, dd, positions, prof_months, weeks] if f is not None)
                        conf = "HIGH" if present >= 5 else "MEDIUM" if present >= 3 else "LOW"

                        if risk is not None:
                            if risk <= 3:
                                style = "\U0001f7e2 Conservative"
                            elif risk <= 5:
                                style = "\U0001f7e1 Balanced"
                            elif risk <= 7:
                                style = "\U0001f7e0 Aggressive"
                            else:
                                style = "\U0001f534 High Risk"
                        else:
                            style = "\u26aa Unknown"

                        # ── Dynamic insight sentence ────────────────
                        is_high_ret = ret is not None and ret > 100
                        is_mod_ret = ret is not None and 50 < ret <= 100
                        is_low_risk = risk is not None and risk <= 3
                        is_mod_risk = risk is not None and 4 <= risk <= 5
                        is_low_dd = dd_abs is not None and dd_abs < 10
                        is_mod_dd = dd_abs is not None and 10 <= dd_abs < 18
                        is_high_cons = prof_months is not None and prof_months > 70
                        is_long_exp = weeks is not None and weeks >= 156

                        if is_high_ret and is_low_risk and is_low_dd:
                            insight = "Elite risk-adjusted returns with excellent drawdown control."
                        elif is_high_ret and is_mod_risk and is_low_dd:
                            insight = "Excellent balance between strong returns and controlled risk."
                        elif is_high_ret and is_mod_risk and is_mod_dd:
                            insight = "Good return profile with manageable drawdown and risk."
                        elif is_mod_ret and is_low_risk and is_low_dd:
                            insight = "Very stable profile with unusually low drawdown."
                        elif is_mod_ret and is_mod_risk and is_low_dd:
                            insight = "Solid and consistent with strong capital preservation."
                        elif is_low_risk and is_low_dd and is_high_cons:
                            insight = "Remarkable consistency paired with disciplined risk management."
                        elif is_high_ret and (not is_low_risk) and (not is_low_dd):
                            insight = "Higher return profile with slightly elevated risk."
                        elif is_mod_ret and is_mod_risk and is_mod_dd:
                            insight = "Consistent long-term growth and disciplined risk."
                        elif is_high_ret and (risk is not None and risk > 5):
                            insight = "Strong performance but more aggressive profile."
                        elif is_long_exp and is_low_dd:
                            insight = "Proven long-term track record with excellent stability."
                        elif is_high_cons and is_mod_ret:
                            insight = "Impressive month-to-month consistency with solid returns."
                        elif is_long_exp and is_mod_ret:
                            insight = "Reliable performer with years of steady returns."
                        elif is_high_ret and is_high_cons:
                            insight = "Attractive combination of high returns and consistency."
                        else:
                            insight = "Balanced profile across return, risk, and stability."

                        lines.append(
                            f'{medal} <b>{username}</b> | \U0001f3c5 <b>Score: {score:.0f}/100</b> '
                            f'| {style} | \U0001f512 {conf}'
                        )
                        lines.append(
                            f'\U0001f4c8 <b>{ret_str}</b> Return '
                            f'| \u26a0\ufe0f <b>{risk_str}</b> Risk '
                            f'| \U0001f4c9 <b>{dd_str}</b> DD'
                        )
                        lines.append(f'\U0001f4a1 {insight}')
                        lines.append("")
                        lines.append('\u2501' * 20)

                    # ── BEST PICK ───────────────────────────────────
                    top = eligible[0]
                    top_user = top.get("username", "?")
                    top_ret = top.get("total_return_pct")
                    top_risk = top.get("risk_score")
                    top_dd = top.get("peak_to_valley") or top.get("max_drawdown")
                    ret_val = f"+{top_ret:.1f}%" if top_ret is not None else "N/A"
                    risk_val = f"Risk {int(top_risk)}" if top_risk is not None else "N/A"
                    dd_val = f"{abs(top_dd):.1f}% DD" if top_dd is not None else "N/A"

                    # Generate best-pick diamond insight
                    if top_ret is not None and top_ret > 100 and top_risk is not None and top_risk <= 4:
                        diamond = "Best balance of return, risk control, and consistency."
                    elif top_dd is not None and abs(top_dd) < 12:
                        diamond = "Strongest capital preservation with solid upside."
                    elif top_ret is not None and top_ret > 80:
                        diamond = "Top return potential with acceptable risk levels."
                    else:
                        diamond = "Most well-rounded trader across all metrics."

                    lines.append("")
                    lines.append(f"\U0001f451 <b>BEST PICK: {top_user}</b>")
                    lines.append(f"\U0001f48e {diamond}")
                    lines.append(f"\U0001f4c8 <b>{ret_val}</b> | \u26a0\ufe0f <b>{risk_val}</b> | \U0001f4c9 <b>{dd_val}</b>")
                    lines.append("")
                    lines.append(f"\U0001f525 <b>Insight:</b> Only <b>{eligible_count}/{scanned}</b> traders passed strict filtering.")

                else:
                    lines.append("No eligible traders found at this time.")

                text = "\n".join(lines)
                if status_msg:
                    try:
                        await status_msg.edit_text(text)
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

                for t in traders:
                    trader_data = {
                        "username": t.trader_username,
                        "source": "tradeinfo" if t.trader_id else "unknown",
                        "confidence": 1.0,
                        "return_12m": t.total_return_pct,
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

                    # Wait 0.5s between traders to avoid rate limits
                    import asyncio
                    await asyncio.sleep(0.5)

                # Get the latest monitoring results for all traders
                from backend.monitoring.orchestrator import run_monitoring_pipeline
                monitor_result = await run_monitoring_pipeline(
                    db, p.id, etoro_client=etoro_client,
                )

                results = monitor_result.get("results", [])
                if not results:
                    await self._reply(update, "Health analysis complete. No signals to report.")
                    return

                lines = [f"Trader Health Analysis\n"]
                for r in results:
                    signal_icon = {
                        "increase": "+",
                        "hold": "\u25b6",
                        "reduce": "\u25bc",
                        "avoid": "x",
                        "watch": "\u25cb",
                    }.get(r.get("signal", "watch"), "?")
                    lines.append(
                        f"{signal_icon} {r['trader']} \u2014 {r['signal']} "
                        f"(conf: {r['confidence']:.2f})"
                    )
                    if r.get("holdings_count", 0) > 0:
                        lines.append(f"   Holdings: {r['holdings_count']}  "
                                     f"Health: {r.get('holdings_health', 0):.0f}/100")
                    for reason in r.get("reasons", [])[:2]:
                        lines.append(f"   {reason}")

                await self._reply(update, "\n".join(lines))
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
