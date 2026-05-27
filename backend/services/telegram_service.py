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
    from telegram.request import HTTPXRequest
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
            request = HTTPXRequest(connection_pool_size=16, read_timeout=30.0, write_timeout=30.0, connect_timeout=15.0)
            self._bot = Bot(token=self.token, request=request)
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
        BotCommand("sync", "Force fresh sync with eToro"),
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
        ["/sync", "/status"],
        ["/overview", "/active"],
        ["/health", "/discovery"],
        ["/alerts", "/watchlist"],
        ["/settings", "/help"],
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
        # Deduplicate: skip if we already processed this update_id
        update_id = update.update_id
        if hasattr(self, '_processed_updates') and update_id in self._processed_updates:
            logger.debug(f"Skipping duplicate update_id={update_id}")
            return
        if not hasattr(self, '_processed_updates'):
            self._processed_updates = set()
        self._processed_updates.add(update_id)
        # Trim old IDs (keep last 100)
        if len(self._processed_updates) > 100:
            self._processed_updates = set(list(self._processed_updates)[-100:])
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
            "/sync": self._cmd_sync,
            "/status": self._cmd_status,
            "/overview": self._cmd_overview,
            "/active": self._cmd_active,
            "/discovery": self._cmd_discovery,
            "/health": self._cmd_health,
            "/alerts": self._cmd_alerts,
            "/watchlist": self._cmd_watchlist,
            "/settings": self._cmd_settings,
            "/news": self._cmd_news,
            "/allocate": self._cmd_allocate,
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
            "/alerts \u2014 Important notifications\n"
            "/news \u2014 Latest market news\n\n"
            "Use the menu below or send /help for all commands."
        )
        await self._reply(update, text)

    async def _cmd_news(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio
        from backend.monitoring.holding_parser import get_trader_holdings, extract_symbols
        from backend.monitoring.news_service import fetch_news_for_symbols

        try:
            await self._reply(update, "\U0001f4f0 Fetching news for your portfolio...")

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                from backend.services.etoro_service import EToroSyncService
                sync_service = EToroSyncService()
                etoro_client = sync_service.client if sync_service.client.enabled else None

                fresh, ts, label = await self._force_sync_before(db, p)

                traders = [t for t in (p.copied_traders or []) if t.is_active and not t.is_paused]
                if not traders:
                    await self._reply(update, "No active traders with holdings to track.")
                    return

                all_symbols = set()
                symbol_to_traders = {}

                # Fetch holdings for ALL traders in a single API call to avoid rate limits
                if etoro_client and etoro_client.enabled:
                    raw = await etoro_client.get_portfolio_data()
                    mirrors_raw = raw.get("clientPortfolio", {}).get("mirrors", []) if raw else []

                    # Resolve instrument IDs from ordersForOpen to ticker symbols
                    from backend.monitoring.holding_parser import parse_holdings_from_mirrors
                    all_instrument_ids = set()
                    for m in mirrors_raw:
                        if not m.get("positions"):
                            for order in m.get("ordersForOpen", []):
                                iid = order.get("instrumentID")
                                if iid:
                                    all_instrument_ids.add(iid)
                    instrument_id_map = {}
                    if all_instrument_ids:
                        instrument_id_map = await etoro_client.resolve_instrument_ids(list(all_instrument_ids))

                    all_holdings = parse_holdings_from_mirrors(mirrors_raw, instrument_id_map)
                    for t in traders:
                        holdings = all_holdings.get(t.trader_username, [])
                        symbols = extract_symbols(holdings)
                        for sym in symbols:
                            all_symbols.add(sym)
                            symbol_to_traders.setdefault(sym, []).append(t.trader_username)
                else:
                    for t in traders:
                        holdings, _ = await get_trader_holdings(db, p.id, t.trader_username, etoro_client=None)
                        symbols = extract_symbols(holdings)
                        for sym in symbols:
                            all_symbols.add(sym)
                            symbol_to_traders.setdefault(sym, []).append(t.trader_username)

                if not all_symbols:
                    # Fallback: fetch major market headlines when no holdings found
                    fallback_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "SPY", "BTC-USD"]
                    news_by_symbol = await fetch_news_for_symbols(fallback_symbols, max_per_symbol=2)
                    total_articles = sum(len(items) for items in news_by_symbol.values())
                    if not total_articles:
                        await self._reply(update, "No symbols found and no market headlines available.")
                        return
                    lines = [f"\U0001f4f0 <b>Market Headlines</b> (no portfolio symbols — showing major markets)\n"]
                    sent_icons = {"positive": "\U0001f7e2", "negative": "\U0001f534", "neutral": "\U0001f7e1"}
                    tbl = [f"{'Sym':<6} {'Sentiment':<10} {'Headline':<30}"]
                    tbl.append("\u2500" * 48)
                    for sym in sorted(news_by_symbol.keys()):
                        items = news_by_symbol.get(sym, [])
                        for item in items:
                            sent = item.get("sentiment", "neutral")
                            icon = sent_icons.get(sent, "\u26aa")
                            title = item.get("title", "")[:28]
                            tbl.append(f"{sym:<6} {icon}{sent:<9} {title:<30}")
                    lines.append(f"<code>{chr(10).join(tbl)}</code>")
                    lines.append(f"\n\U0001f4c5 {ts} ({label})")
                    await self._reply(update, "\n".join(lines))
                    return

                news_by_symbol = await fetch_news_for_symbols(list(all_symbols), max_per_symbol=2)

                total_articles = sum(len(items) for items in news_by_symbol.values())
                lines = [f"\U0001f4f0 <b>Portfolio News ({total_articles} articles)</b>\n"]

                sent_icons = {"positive": "\U0001f7e2", "negative": "\U0001f534", "neutral": "\U0001f7e1"}
                tbl = [f"{'Sym':<6} {'Sentiment':<10} {'Headline':<30}"]
                tbl.append("\u2500" * 48)
                for sym in sorted(all_symbols):
                    items = news_by_symbol.get(sym, [])
                    if not items:
                        tbl.append(f"{sym:<6} {'no data':<10} {'-':<30}")
                    for item in items:
                        sent = item.get("sentiment", "neutral")
                        icon = sent_icons.get(sent, "\u26aa")
                        title = item.get("title", "")[:28]
                        tbl.append(f"{sym:<6} {icon}{sent:<9} {title:<30}")
                lines.append(f"<code>{chr(10).join(tbl)}</code>")

                lines.append(f"\n\U0001f5e3\ufe0f <b>Who holds what</b>")
                for sym in sorted(all_symbols):
                    traders_list = symbol_to_traders.get(sym, [])
                    if traders_list:
                        lines.append(f"  {sym}: {', '.join(t[:10] for t in traders_list)}")

                lines.append(f"\n\U0001f4c5 {ts} ({label})")
                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/news error: {e}")
            await self._reply(update, f"News fetch failed: {e}")

    async def _cmd_allocate(self, update: Update, args: list[str]) -> None:
        """Usage: /allocate <trader_name> <new_amount>

        Changes the copy amount for a trader on eToro.
        Use the amount shown in /active or /health as reference.
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader
        from backend.services.etoro_service import EToroSyncService

        if len(args) < 2:
            await self._reply(update, "Usage: /allocate &lt;trader_name&gt; &lt;amount&gt;\nExample: /allocate QuantumComputing 5000")
            return

        trader_name = args[0]
        try:
            new_amount = float(args[1])
        except ValueError:
            await self._reply(update, "Amount must be a number.")
            return

        if new_amount <= 0:
            await self._reply(update, "Amount must be positive.")
            return

        try:
            sync_service = EToroSyncService()
            client = sync_service.client

            if not client or not client.enabled:
                await self._reply(update, "eToro API not configured.")
                return

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                fresh, ts, label = await self._force_sync_before(db, p)

                trader = (
                    db.query(CopiedTrader)
                    .filter(
                        CopiedTrader.portfolio_id == p.id,
                        CopiedTrader.trader_username.ilike(f"%{trader_name}%"),
                    )
                    .first()
                )

                if not trader:
                    await self._reply(update, f"Trader '{trader_name}' not found.")
                    return

                mirror_id = int(trader.trader_id) if trader.trader_id and trader.trader_id.isdigit() else None
                if not mirror_id or mirror_id <= 0:
                    await self._reply(update, f"Trader '{trader.trader_username}' has no valid mirror ID — cannot allocate.")
                    return

                current_amount = trader.allocated_amount or 0
                await self._reply(update, f"Changing {trader.trader_username} from ${current_amount:.2f} to ${new_amount:.2f}...")

                result = await client.execute_change_mirror_amount(mirror_id, new_amount)

                if result and result.get("error"):
                    detail = result.get("detail", "unknown error")
                    await self._reply(update, f"Failed: {detail[:200]}")
                else:
                    trader.allocated_amount = new_amount
                    db.commit()
                    await self._reply(update, f"Done. {trader.trader_username} now allocated ${new_amount:.2f}")
        except Exception as e:
            logger.error(f"/allocate error: {e}")
            await self._reply(update, f"Allocation failed: {e}")

    async def _cmd_help(self, update: Update, args: list[str]) -> None:
        text = (
            "Available Commands\n\n"
            "/start \u2013 Welcome and main menu\n"
            "/sync \u2013 Force fresh sync with eToro\n"
            "/status \u2013 Quick portfolio snapshot\n"
            "/overview \u2013 Full portfolio summary\n"
            "/active \u2013 List active copied traders\n"
            "/discovery \u2013 New eligible traders\n"
            "/health \u2013 Trader health analysis\n"
            "/alerts \u2013 Recent important alerts\n"
            "/watchlist \u2013 Monitored traders\n"
            "/settings \u2013 Current limits and preferences\n"
            "/news \u2013 Latest market news\n"
            "/allocate &lt;name&gt; &lt;amount&gt; \u2013 Change copy amount\n"
            "/help \u2013 Show this message"
        )
        await self._reply(update, text)

    async def _cmd_sync(self, update: Update, args: list[str]) -> None:
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader
        from backend.services.etoro_service import EToroSyncService

        try:
            await self._reply(update, "\U0001f504 Syncing with eToro...")

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                sync = EToroSyncService()
                if not sync.client.enabled:
                    await self._reply(update, "\u274c eToro API not configured.")
                    return

                ok = await sync.sync_portfolio_data(db, p.id)
                db.refresh(p)

                if ok:
                    active = db.query(CopiedTrader).filter(
                        CopiedTrader.portfolio_id == p.id,
                        CopiedTrader.is_active.is_(True),
                        CopiedTrader.is_paused.is_(False),
                    ).count()
                    s = self._sym(p.currency or "USD")
                    tbl = [
                        f"{'Metric':<12} {'Value':>14}",
                        "\u2500" * 28,
                        f"{'Value':<12} {s}{p.total_value:>14,.2f}",
                        f"{'Cash':<12} {s}{p.available_cash:>14,.2f}",
                        f"{'Traders':<12} {active:>14}",
                    ]
                    text = (
                        f"\u2705 <b>Sync Complete</b>\n\n"
                        f"<code>{chr(10).join(tbl)}</code>\n"
                        f"\U0001f4c5 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                    )
                    await self._reply(update, text)
                else:
                    await self._reply(update, "\u274c Sync failed. Check logs.")
        except Exception as e:
            logger.error(f"/sync error: {e}")
            await self._reply(update, f"\u274c Error: {e}")

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

                tbl = [
                    f"{'Metric':<12} {'Value':>14}",
                    "\u2500" * 28,
                    f"{'Value':<12} {s}{overview['total_value']:>14,.2f}",
                    f"{'Cash':<12} {s}{overview['available_cash']:>14,.2f}",
                    f"{'Return':<12} {ret_icon}{ret:>+14.2f}%",
                    f"{'Health':<12} {health_icon}{health:>14.0f}/100",
                    f"{'Traders':<12} {overview['active_traders']:>14}",
                    f"{'Sentiment':<12} {overview['sentiment']:>14}",
                ]
                text = (
                    f"\U0001f4ca <b>Portfolio Status</b>\n\n"
                    f"<code>{chr(10).join(tbl)}</code>\n"
                    f"\U0001f4c5 {ts} ({label})"
                )
                await self._reply(update, text)
        except Exception as e:
            logger.error(f"/status error: {e}")
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

                def trow(icon, name, ret_s, alloc_s):
                    return f"{icon} {name:<12.12} {ret_s:>6} {alloc_s:>5}"

                lines = [f"\U0001f465 <b>Active Traders ({len(traders)})</b>\n"]
                trows = [trow("", "Name", "Return", "Alloc")]
                trows.append("\u2500" * 28)
                for t in traders:
                    ret = t["total_return_pct"]
                    ret_s = f"{ret:+.1f}%" if ret >= 0 else f"{ret:.1f}%"
                    pnl_icon = "\U0001f7e2" if ret >= 0 else "\U0001f534"
                    trows.append(trow(pnl_icon, t["username"][:12], ret_s, f"{t['allocation_pct']:.1f}%"))
                lines.append(f"<code>{chr(10).join(trows)}</code>")
                lines.append(f"\n\U0001f4c5 {ts} ({label})")
                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/active error: {e}")
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

                lines = [f"\U0001f4ca <b>Portfolio Summary</b> ({label})\n"]

                tbl = [
                    f"{'Metric':<14} {'Value':>16}",
                    "\u2500" * 32,
                    f"{'Value':<14} {s}{overview['total_value']:>16,.2f}",
                    f"{'Cash':<14} {s}{overview['available_cash']:>16,.2f}",
                    f"{'Return':<14} {ret:>16.2f}%",
                    f"{'Health':<14} {health:>16.0f}/100",
                    f"{'Traders':<14} {overview['active_traders']:>16}",
                    f"{'Sentiment':<14} {overview['sentiment']:>16}",
                ]
                lines.append(f"<code>{chr(10).join(tbl)}</code>")

                if overview.get("concentration_risk"):
                    lines.append(f"\n\u26a0\ufe0f Concentration risk detected")

                if traders:
                    lines.append(f"\n\U0001f465 <b>Active Traders ({len(traders)})</b>")
                    t_tbl = [f"{'Name':<12} {'Alloc':>5} {'Return':>6}"]
                    t_tbl.append("\u2500" * 26)
                    for t in traders:
                        ret = t["total_return_pct"]
                        paused = " \u23f8" if t.get("is_paused") else ""
                        name = t["username"][:12] + paused
                        t_tbl.append(f"{name:<12} {t['allocation_pct']:>4.1f}% {ret:>+5.1f}%")
                    lines.append(f"<code>{chr(10).join(t_tbl)}</code>")

                lines.append(f"\n\U0001f4c5 {ts} ({label})")

                await self._reply(update, "\n".join(lines))
        except Exception as e:
            logger.error(f"/overview error: {e}")
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
        try:
            text = await self._generate_health_report(show_reallocation=True)
            await self._reply(update, text)
        except Exception as e:
            logger.exception("Health analysis failed")
            await self._reply(update, f"Health analysis failed: {e}")

    async def _ai_reallocate(self, results: list[dict]) -> str:
        """Ask AI for portfolio reallocation suggestions. Returns formatted block or empty string."""
        from backend.monitoring.ai_health_engine import AI_AVAILABLE

        if not AI_AVAILABLE or not results:
            return ""

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
        if not api_key:
            return ""

        from backend.monitoring.ai_health_engine import PROVIDERS

        provider = "openai"
        for name, cfg in PROVIDERS.items():
            if api_key.startswith(cfg["key_prefix"]):
                provider = name
                break

        extra_headers = {}
        if provider == "groq":
            base_url = PROVIDERS["groq"]["base_url"]
            model = "llama-3.3-70b-versatile"
        elif provider == "openrouter":
            base_url = PROVIDERS["openrouter"]["base_url"]
            model = "openai/gpt-4o-mini"
            extra_headers = {
                "HTTP-Referer": "https://github.com/leoblixt25/SmartEtoro2",
                "X-Title": "SmartEtoro2",
            }
        else:
            base_url = None
            model = "gpt-4o-mini"

        from openai import OpenAI
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

        total_alloc = sum(r.get("allocation_pct") or 0 for r in results)

        lines = ["Analyse this portfolio for reallocation. Recommend how to redistribute allocation % to maximise risk-adjusted returns.", ""]
        for r in results:
            name = r.get("trader") or r.get("name")
            alloc = r.get("allocation_pct") or 0
            ret = r.get("total_return_pct") or 0
            risk = r.get("real_risk") or r.get("risk_score") or "N/A"
            dd = r.get("real_dd")
            peak_dd = r.get("dd_yearly") or dd
            consistency = r.get("profitable_months_pct") or "N/A"
            lines.append(f"- {name}: alloc={alloc:.0f}% return={ret:+.1f}% risk={risk} dd={dd if dd else 'N/A'}% peak_dd={peak_dd if peak_dd else 'N/A'}% consistency={consistency}")
        lines.append("")
        lines.append(f"Total allocation currently: {total_alloc:.0f}%. Keep total at {total_alloc:.0f}% after reallocation.")
        lines.append("Base decisions on multi-month return trends, consistency, drawdown history, and risk score. Ignore single-day movements.")
        lines.append("Return ONLY valid JSON array: [{\"name\":\"...\",\"from\":N,\"to\":N,\"reason\":\"...\"}]")
        lines.append("Set to=from for no change, to>from to increase, to<from to decrease. Max 80 chars per reason.")

        prompt = "\n".join(lines)

        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a portfolio allocation expert for eToro copy trading. Return ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1500,
        }
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        if provider == "groq":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content
            raw = raw.strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) >= 2 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            raw = raw.split("```")[0].strip()

            import json
            data = json.loads(raw)
            if isinstance(data, dict) and "suggestions" in data:
                suggestions = data["suggestions"]
            elif isinstance(data, list):
                suggestions = data
            else:
                logger.error(f"AI reallocation: unexpected JSON format: {raw[:200]}")
                return ""

            NAME_W = max(len(s["name"][:10]) for s in suggestions) if suggestions else 10
            NAME_W = max(NAME_W, 4)

            block = [
                "\n\U0001f4ca <b>Reallocation Suggestion (AI)</b>",
                "\u2500" * 36,
            ]
            for s in suggestions:
                name = s.get("name", "?")
                fr = s.get("from", 0)
                to = s.get("to", 0)
                reason = s.get("reason", "")
                if to > fr:
                    icon = "\u2b06\ufe0f"
                elif to < fr:
                    icon = "\u2b07\ufe0f"
                else:
                    icon = "\u27a1\ufe0f"
                block.append(f"{icon} {name[:10]:<{NAME_W}} {fr:.0f}%\u2192{to:.0f}%  ({reason})")
            return "\n".join(block)

        except Exception as e:
            logger.exception(f"AI reallocation failed: {e}")
            return ""

    async def _generate_health_report(self, show_reallocation: bool = False) -> str:
        """Run full health analysis and return the summary text.

        Shared between /health command and scheduled 12-hour report.
        """
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, CopiedTrader
        from backend.monitoring.trader_health_engine import analyze_trader_health
        from backend.monitoring.ai_health_engine import ai_analyze_traders
        from backend.monitoring.holding_parser import get_trader_holdings, extract_symbols
        from backend.monitoring.news_service import fetch_news_for_symbols
        from backend.services.etoro_service import EToroSyncService

        sync_service = EToroSyncService()
        etoro_client = sync_service.client if sync_service.client.enabled else None

        with db_session() as db:
            p = db.query(Portfolio).first()
            if not p:
                return "No portfolio found."

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
                return "No active traders to analyse."

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
                    "watch_consecutive": t.watch_consecutive or 0,
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

                await asyncio.sleep(0.1)

            # Build portfolio summary for AI
            portfolio_summary = {
                "total_invested_capital": float(p.total_value or 0),
                "total_portfolio_value": float(p.total_value or 0),
                "total_available_cash": float(p.available_cash or 0),
            }

            # Try AI analysis on the full batch
            ai_results = await ai_analyze_traders(enriched, portfolio_summary)

            results = []
            if ai_results:
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
                        "watch_consecutive": td.get("watch_consecutive", 0),
                    })
            else:
                for td in enriched:
                    result = analyze_trader_health(td, td.get("_holdings", []), td.get("_news_by_symbol", {}))
                    results.append(result)

            if not results:
                return "Health analysis complete. No signals to report."

            async def _enrich_trader(r):
                name = r.get("name") or r.get("trader")
                try:
                    m = await etoro_client.get_trader_metrics(name)
                    if m.get("available"):
                        yd = m.get("yearly_dd")
                        if yd is not None:
                            r["real_dd"] = abs(yd)
                            r["dd_source"] = "yearlyDd"
                            r["dd_yearly"] = None
                        else:
                            dd_val = m.get("max_drawdown")
                            dd_field = m.get("dd_field")
                            yearly_peak = m.get("peak_to_valley")
                            if dd_val is not None:
                                r["real_dd"] = abs(dd_val)
                                r["dd_source"] = dd_field or "peakToValley"
                                r["dd_yearly"] = abs(yearly_peak) if yearly_peak is not None and dd_field != "peakToValley" else None
                            elif yearly_peak is not None:
                                r["real_dd"] = abs(yearly_peak)
                                r["dd_source"] = "peakToValley"
                                r["dd_yearly"] = None
                            else:
                                r["dd_source"] = "missing"
                        r["real_risk"] = m.get("risk_score")
                        r["profitable_months_pct"] = m.get("profitable_months_pct")
                        r["win_ratio"] = m.get("win_ratio")
                        r["trades_count"] = m.get("trades_count")
                        r["weeks_since_registration"] = m.get("weeks_since_registration")
                except Exception:
                    pass
            await asyncio.gather(*[_enrich_trader(r) for r in results])

            # Persist scraped stats for each trader
            try:
                from backend.services.scraper_service import upsert_scraped_stats
                for r in results:
                    name = r.get("name") or r.get("trader")
                    yearly_dd = r.get("real_dd")
                    risk_7d = r.get("real_risk") or r.get("risk_score")
                    upsert_scraped_stats(db, name, risk_7d, yearly_dd)
            except Exception:
                logger.exception("Failed to persist scraped stats")

            summary = _build_health_summary(results, live=freshness, source_label=label, ts=ts, ai_used=bool(ai_results))

            for r in results:
                trader_name = r.get("name") or r.get("trader")
                bucket, _, _ = _assess_trader(r, r.get("watch_consecutive", 0))
                ct = next((t for t in traders if t.trader_username == trader_name), None)
                if ct is None:
                    continue
                if bucket == "watch":
                    ct.watch_consecutive = (ct.watch_consecutive or 0) + 1
                    logger.info(f"  WATCH scan ++ {trader_name}: now {ct.watch_consecutive}")
                else:
                    if ct.watch_consecutive:
                        ct.watch_consecutive = 0
            db.commit()
            logger.info(f"Health: watch_consecutive updated for {len(results)} traders")

        if show_reallocation:
            realloc = await self._ai_reallocate(results)
            if realloc:
                summary += realloc

        return summary

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
                alerts = get_alerts(db, p.id, unread_only=True, limit=10)
                if not alerts:
                    await self._reply(update, "\u2705 No unread alerts.")
                    return

                severity_icons = {"critical": "\U0001f534", "warning": "\u26a0\ufe0f", "info": "\U0001f7e1"}
                lines = [f"\U0001f514 <b>Recent Alerts ({len(alerts)})</b>\n"]
                tbl = [f"{'When':<12} {'Severity':<10} {'Alert':<20}"]
                tbl.append("\u2500" * 44)
                for a in alerts:
                    icon = severity_icons.get(a["severity"], "\u2753")
                    when = a["created_at"][:16] if a.get("created_at") else "?"
                    title = a["title"][:20]
                    tbl.append(f"{icon} {when:<10} {a['severity']:<10} {title:<20}")
                lines.append(f"<code>{chr(10).join(tbl)}</code>")
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
                sig_parts = []
                for sig, count in by_signal.items():
                    icon = signal_icons.get(sig, "\u2753")
                    sig_parts.append(f"{icon} {sig} <b>{count}</b>")
                lines.append("  ".join(sig_parts))

                def wrow(icon, name, sig, score):
                    return f"{icon} {name:<14} {sig:>8}  {score:>6}"

                tbl = [wrow("", "Name", "Signal", "Score")]
                tbl.append("\u2500" * 34)
                for r in results:
                    sig = r.get("signal", "watch")
                    sig_icon = signal_icons.get(sig, "\U0001f50d")
                    score = r.get("performance_score", 0)
                    tbl.append(wrow(sig_icon, r["trader"][:14], sig, f"{score:.0f}"))
                lines.append(f"\n<code>{chr(10).join(tbl)}</code>")
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
                s = self._sym(p.currency or "USD")

                tbl = [
                    f"{'Setting':<12} {'Value':>14}",
                    "\u2500" * 28,
                    f"{'ID':<12} {p.id:>14}",
                    f"{'Currency':<12} {p.currency or 'USD':>14}",
                    f"{'Mode':<12} {'Sim' if p.is_simulation else 'Live':>14}",
                    f"{'Value':<12} {s}{p.total_value:>14,.2f}",
                    f"{'Cash':<12} {s}{p.available_cash:>14,.2f}",
                    f"{'Health':<12} {health_icon}{health:>14.0f}/100",
                    f"{'Traders':<12} {active:>14}",
                ]
                text = (
                    f"\u2699\ufe0f <b>Settings</b>\n\n"
                    f"<code>{chr(10).join(tbl)}</code>\n"
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





def _assess_trader(r: dict, watch_consecutive: int = 0) -> tuple:
    """Score-first classification — quantitative metrics drive decisions.

    Decision priority:
      1. Health score (0-100)
      2. Trend deterioration
      3. Consistency
      4. AI sentiment (minor — never overrides score)
      5. Risk concentration

    AI is a soft modifier only. A score >= 60 can NEVER be UNCOPY
    from AI alone. UNCOPY requires score < 50, or score < 60 with
    HIGH confidence AI + deterioration.
    """
    score = r.get("_health_score") or _compute_health_score(r)
    cum_pl = r.get("total_return_pct") or 0.0
    dd_abs = abs(r.get("real_dd") or 0)
    risk = r.get("real_risk") or r.get("risk_score") or 0
    dd_source = r.get("dd_source", "unknown")
    dd_confident = dd_source != "missing"
    dd_yearly = r.get("dd_yearly")
    perf = r.get("performance", {})
    medium = (perf.get("month") or perf.get("week") or 0.0)
    daily = perf.get("day") or 0.0
    ai_status = (r.get("health_status") or r.get("status", "")).lower()
    ai_conf = (r.get("confidence") or "LOW").upper()
    consistency = r.get("consistency_score") or 50

    reasons = []
    trend_declining = medium < -1.0
    severe_decline = medium < -3.0
    trend_positive = medium > 0.5
    ai_negative = ai_status in ("weak", "avoid")
    ai_high = ai_conf == "HIGH"
    high_dd = dd_abs > 25
    excessive_dd = dd_abs > 35
    low_consistency = consistency < 30
    high_risk = risk > 7

    # ── Build measurable reason components ──
    def add_reason(text):
        if text not in reasons:
            reasons.append(text)

    if cum_pl > 0:
        add_reason(f"Return +{cum_pl:.1f}%")
    elif cum_pl < -2:
        add_reason(f"Return {cum_pl:.1f}% declining")

    if trend_declining:
        add_reason(f"Trend {medium:+.1f}% over 30d")
    if excessive_dd:
        add_reason(f"Drawdown {dd_abs:.0f}% severe")
    elif high_dd:
        add_reason(f"Drawdown {dd_abs:.0f}% above threshold")
    elif dd_abs >= 15:
        add_reason(f"Drawdown {dd_abs:.0f}% approaching penalty threshold")
    if dd_abs > 0 and not dd_confident:
        add_reason("DD source unavailable — score may be unreliable")
    if dd_yearly is not None and dd_yearly > dd_abs * 1.5 and dd_yearly > 15:
        add_reason(f"Past 2-year peak {dd_yearly:.0f}% (recovered)")
    if low_consistency:
        add_reason(f"Consistency {consistency}/100 below threshold")
    if high_risk:
        add_reason(f"Risk score {risk} above ideal band")
    if risk < 3 and risk > 0:
        add_reason(f"Risk {risk} signals under-diversification")
    if ai_negative and ai_high:
        add_reason(f"AI negative (HIGH confidence)")
    elif ai_negative:
        add_reason(f"AI negative sentiment")
    if watch_consecutive > 0 and score < 60:
        add_reason(f"Watch scan {watch_consecutive + 1}")

    # ══════════════════════════════════════════════════════════════
    # CLASSIFICATION — score-first, then deterioration
    # ══════════════════════════════════════════════════════════════

    # ── UNCOPY: score < 50, or < 60 with HIGH AI + deterioration ──
    if score < 50:
        bucket = "uncopy"
        confidence = "High"
        add_reason(f"Score {score}/100 — Avoid")

    elif score < 60:
        # Score 50-59: borderline, needs strong evidence
        if ai_negative and ai_high and trend_declining:
            bucket = "uncopy"
            confidence = "Medium"
        elif watch_consecutive >= 2 and (trend_declining or low_consistency):
            bucket = "uncopy"
            confidence = "Medium"
        elif ai_negative and ai_high:
            bucket = "uncopy" if watch_consecutive >= 1 else "watch"
            confidence = "Medium"
            if bucket == "watch":
                add_reason("Borderline score — monitoring before decision")
        elif high_dd or excessive_dd:
            if not dd_confident:
                bucket = "watch"
                confidence = "Low"
                add_reason("DD source uncertain — monitoring before decision")
            else:
                bucket = "uncopy" if watch_consecutive >= 2 else "watch"
                confidence = "Medium"
                if bucket == "watch":
                    add_reason("Elevated drawdown — monitoring")
        else:
            bucket = "watch"
            confidence = "Medium"
        if bucket == "uncopy":
            add_reason(f"Score {score}/100 — Average")

    # ── KEEP: score >= 75, no severe deterioration ──
    elif score >= 75:
        bucket = "keep"
        confidence = "High" if score >= 80 else "Medium"
        if severe_decline:
            bucket = "watch"
            confidence = "Medium"
            add_reason("Score strong but severe trend decline")

    # ── KEEP/WATCH: score 60-74 ──
    elif score >= 60:
        # Negative return + score < 65: uncopy — persistent loss, not just volatility
        if cum_pl < 0 and score < 65:
            bucket = "uncopy"
            confidence = "Medium"
            add_reason(f"Negative return with score {score}/100")
        elif trend_positive or (consistency >= 60 and not trend_declining):
            bucket = "keep"
            confidence = "Medium"
        elif trend_declining and watch_consecutive >= 2:
            bucket = "watch"
            confidence = "Medium"
            add_reason("Weakening trend persists")
        elif excessive_dd:
            bucket = "watch"
            confidence = "Medium"
        elif ai_negative and ai_high:
            bucket = "watch"
            confidence = "Medium"
        elif watch_consecutive >= 1 and trend_declining:
            bucket = "watch"
            confidence = "Medium"
        else:
            bucket = "watch"
            confidence = "Medium"

    # ── WATCH: score < 60 (not yet UNCOPY) ──
    else:
        bucket = "watch"
        confidence = "Medium"

    if not reasons:
        add_reason(f"Score {score}/100")

    return bucket, " \u2022 ".join(reasons), confidence


def _compute_health_score(r: dict) -> int:
    """Weighted score 0-100 prioritizing quality & stability over raw return.

    Components: return 30%, drawdown 30%, risk 20%, consistency 15%, AI 5%.
    """
    cum_pl = r.get("total_return_pct") or 0.0
    dd = abs(r.get("real_dd") or 0)
    risk = r.get("real_risk") or r.get("risk_score") or 0
    prof_months = r.get("profitable_months_pct")
    win_ratio = r.get("win_ratio")
    trades = r.get("trades_count")
    ai_conf = (r.get("confidence") or "LOW").upper()

    # ── Return score (30%) — capped at +5% "good enough" ceiling ──
    ret_score = 0.0
    if cum_pl > 0:
        ret_score = min(cum_pl, 5.0) / 5.0 * 30

    # ── Drawdown score (30%) — reward low DD, accelerate penalty >15% ──
    if dd <= 5:
        dd_score = 30.0
    elif dd <= 15:
        t = (dd - 5) / 10
        dd_score = 30 - t * 10
    elif dd <= 25:
        t = (dd - 15) / 10
        dd_score = 20 - t * 12
    elif dd <= 35:
        t = (dd - 25) / 10
        dd_score = 8 * (1 - t)
    else:
        dd_score = 0

    # ── Risk score (20%) — peaks at 4-5, penalizes both extremes ──
    if not risk or risk == 0:
        risk_score = 10
    elif 4 <= risk <= 5:
        risk_score = 20
    elif 3 <= risk <= 6:
        risk_score = 16
    elif 2 <= risk <= 7:
        risk_score = 12
    elif 1 <= risk <= 8:
        risk_score = 8
    else:
        risk_score = 4

    # High risk (>7) compounding penalty unless top-tier return
    if risk > 7 and cum_pl <= 5.0:
        ret_score *= 0.5
        risk_score *= 0.5

    # ── Consistency score (15%) — stable monthly performance ──
    cons_score = 7.5  # default neutral
    if prof_months is not None and prof_months > 0:
        if prof_months >= 80:
            cons_score = 15
        elif prof_months >= 65:
            cons_score = 12
        elif prof_months >= 50:
            cons_score = 10
        elif prof_months >= 35:
            cons_score = 7
        else:
            cons_score = 4
    if win_ratio is not None and win_ratio > 0:
        win_bonus = win_ratio / 100 * 3
        cons_score = min(15, cons_score + win_bonus)
    if trades is not None and trades >= 50:
        cons_score = min(15, cons_score + 2)

    # ── AI confidence score (5%) ──
    ai_conf_score = {"HIGH": 5, "MEDIUM": 3, "LOW": 1}.get(ai_conf, 2)

    total = int(round(ret_score + dd_score + risk_score + cons_score + ai_conf_score))

    # ── Negative return floor penalty ──
    if cum_pl < 0:
        total -= int(round(min(30, abs(cum_pl) * 10)))

    return max(0, min(100, total))


def _build_health_summary(results: list[dict], live: bool = False, source_label: str = "Cached", ts: str = "", ai_used: bool = False) -> str:
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

    def fmt_alloc(pct):
        return f"{pct:.0f}%"

    def fmt_dd_rs(r):
        dd = r.get("real_dd")
        rs = r.get("real_risk")
        if dd is not None:
            dds = f"{abs(dd):.0f}"
        else:
            dds = "-"
        if rs is not None:
            rss = f"{rs:.0f}"
        else:
            rss = "-"
        return f"{dds}/{rss}"

    def ai_bucket(r):
        s = r.get("status", "") or ""
        status_upper = s.upper()
        if status_upper in ("STRONG", "GOOD", "ELITE"):
            return "keep"
        if status_upper in ("WEAK", "AVOID"):
            return "uncopy"
        if status_upper == "WATCH":
            return "watch"
        return None

    def trader_score(r):
        s = r.get("score") or r.get("health_score")
        if s is not None:
            return int(s)
        return _compute_health_score(r)

    uncopy = []
    keep = []
    watch = []
    for r in results:
        bucket = ai_bucket(r)
        reason = r.get("reason", "")
        if not bucket:
            watch_count = r.get("watch_consecutive", 0)
            bucket, reason, _ = _assess_trader(r, watch_count)
        r["_assessed_reason"] = reason
        sc = trader_score(r)
        r["_health_score"] = sc
        entry = (r.get("trader", "?"), ret_val(r), r.get("allocation_pct") or 0, r.get("risk_score") or 0, r, sc)
        if bucket == "uncopy":
            uncopy.append(entry)
        elif bucket == "keep":
            keep.append(entry)
        else:
            watch.append(entry)

    uncopy.sort(key=lambda x: -x[5])
    keep.sort(key=lambda x: -x[5])
    watch.sort(key=lambda x: -x[5])

    total = len(results)
    source_tag = source_label if source_label else ("Live" if live else "Cached")
    pos = len(keep)
    neg = len(uncopy)
    flat = len(watch)

    logger.info(
        f"HEALTH REPORT: {total} traders ({source_tag}), "
        f"{pos} keep, {neg} uncopy, {flat} watch"
    )

    ai_tag = " \U0001f916" if ai_used else ""
    lines = [f"\U0001f4ca <b>Health \u2014 {total} traders</b> ({source_tag}{ai_tag})"]
    lines.append(f"\u2705 {pos} good  \u274c {neg} bad  \u26aa {flat} flat\n")

    tbl = [f"{'Name':<12} {'Sc':>3} {'Ret':>7} {'Al%':>4} {'D/R':>5}"]
    tbl.append("\u2500" * 34)

    if keep:
        tbl.append(f"\u2705 KEEP")
        for name, ret, alloc, risk, r, sc in keep:
            tbl.append(f"{name[:12]:<12} {sc:>3} {ret_str(ret):>7} {fmt_alloc(alloc):>4} {fmt_dd_rs(r):>5}")

    if watch:
        tbl.append(f"\U0001f50d WATCH")
        for name, ret, alloc, risk, r, sc in watch:
            tbl.append(f"{name[:12]:<12} {sc:>3} {ret_str(ret):>7} {fmt_alloc(alloc):>4} {fmt_dd_rs(r):>5}")

    if uncopy:
        tbl.append(f"\u274c UNCOPY")
        for name, ret, alloc, risk, r, sc in uncopy:
            tbl.append(f"{name[:12]:<12} {sc:>3} {ret_str(ret):>7} {fmt_alloc(alloc):>4} {fmt_dd_rs(r):>5}")

    lines.append(f"<code>{chr(10).join(tbl)}</code>")

    # ── Reasons for WATCH and UNCOPY ──
    watch_reasons = []
    for name, ret, alloc, risk, r, sc in watch:
        reason = r.get("reason") or r.get("_assessed_reason", "")
        if reason:
            watch_reasons.append(f"\U0001f7e1 <b>{name}</b>: {reason}")

    uncopy_reasons = []
    for name, ret, alloc, risk, r, sc in uncopy:
        reason = r.get("reason") or r.get("_assessed_reason", "")
        if reason:
            uncopy_reasons.append(f"\U0001f916 <b>{name}</b>: {reason}")

    if uncopy_reasons:
        lines.append(f"\n\u274c <b>Why UNCOPY</b>")
        lines.extend(uncopy_reasons)

    if watch_reasons:
        lines.append(f"\n\U0001f50d <b>Why WATCH</b>")
        lines.extend(watch_reasons)

    # ── DD source cross-check ──
    dd_warnings = []
    for r in results:
        ds = r.get("dd_source", "unknown")
        dy = r.get("dd_yearly")
        name = r.get("trader", "?")
        if ds == "missing":
            dd_warnings.append(f"\u26a0\ufe0f {name}: DD source unavailable")
        elif ds in ("weeklyDd", "dailyDd") and dy is None:
            dd_warnings.append(f"\U0001f7e1 {name}: DD from {ds} (yearly peak data unavailable)")
        elif ds in ("weeklyDd", "dailyDd") and dy is not None and dy > abs(r.get("real_dd") or 0) * 1.5 and dy > 15:
            dd_warnings.append(f"\U0001f7e1 {name}: Current DD {abs(r.get('real_dd') or 0):.0f}%, yearly peak {dy:.0f}%")
    if dd_warnings:
        lines.append(f"\n\U0001f4cb <b>DD Notes</b>")
        lines.extend(dd_warnings)

    # ── Action ──
    high_conf_uncopy = [e for e in uncopy if e[4].get("_assessed_confidence") == "High"]
    if high_conf_uncopy:
        target = next((e for e in high_conf_uncopy if e[2] >= 1.0), high_conf_uncopy[0])
        lines.append(f"\n\U0001f6a8 <b>Action:</b> UNCOPY <b>{target[0]}</b> ({target[1]:+.1f}% at {target[2]:.1f}%)")
    elif uncopy:
        lines.append(f"\n\u26a0\ufe0f <b>Review needed</b> \u2014 potential UNCOPY candidates flagged")
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
