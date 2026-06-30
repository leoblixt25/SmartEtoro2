"""
Telegram Bot Service
Smart portfolio assistant commands: monitor, analyze, decide.
"""

from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Hardcoded 12-month max drawdown values confirmed from eToro UI.
# Used when the tradeinfo API does not expose yearlyDd/maxMonthlyDrawdown.
HARDCODED_12M_DD = {
    "ai-revolution": 18.95,
    "edu-inversor": 10.40,
    "onk342": 14.20,
    "cphequities": 19.00,
}

try:
    import telegram
    from telegram import Bot, Update, BotCommand
    from telegram.constants import ParseMode
    from telegram.request import HTTPXRequest
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

# ── Score history helpers ───────────────────────────────────────────
SCORE_HISTORY_PATH = "score_history.json"

def _load_score_history():
    """Load score history dict {username: [(timestamp_iso, score), ...]}."""
    import json
    try:
        with open(SCORE_HISTORY_PATH) as f:
            data = json.load(f)
            # Prune entries older than 30 days
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            pruned = {}
            for user, entries in data.items():
                fresh = [(ts, s) for ts, s in entries if ts >= cutoff]
                if fresh:
                    pruned[user] = fresh
            return pruned
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_score_history(user_scores: dict):
    """Save score history dict, keyed by username, each with [(timestamp_iso, score)]."""
    import json
    history = _load_score_history()
    now_iso = datetime.utcnow().isoformat()
    for username, score in user_scores.items():
        if username not in history:
            history[username] = []
        history[username].append((now_iso, score))
    with open(SCORE_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)

def _score_trend(username: str, current_score: int) -> str:
    """Return trend indicator: ↑ ↓ → based on 7-day score change."""
    history = _load_score_history()
    entries = history.get(username, [])
    now = datetime.utcnow()
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    old_entries = [(ts, s) for ts, s in entries if ts >= cutoff_7d]
    if len(old_entries) < 2:
        return "\u2192"  # insufficient history → flat
    oldest_score = old_entries[0][1]
    diff = current_score - oldest_score
    if diff >= 3:
        return "\u2191"
    if diff <= -3:
        return "\u2193"
    return "\u2192"

# ── Market context helper ───────────────────────────────────────────
async def _fetch_market_data() -> dict:
    """Fetch 1-day % change for SPY, QQQ, BTC-USD via yfinance. Returns {symbol: pct_change}."""
    result = {}
    try:
        import yfinance as yf
        for sym in ("SPY", "QQQ", "BTC-USD"):
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="2d")
                if len(hist) >= 2:
                    ct = hist["Close"].iloc[-1]
                    cy = hist["Close"].iloc[-2]
                    result[sym] = round((ct - cy) / cy * 100, 1)
            except Exception:
                pass
    except Exception:
        pass
    return result

def _format_market_line(market_data: dict) -> str:
    """Format market data dict into a one-line string."""
    parts = []
    for sym in ("SPY", "QQQ", "BTC-USD"):
        val = market_data.get(sym)
        if val is not None:
            sign = "+" if val >= 0 else ""
            label = "BTC" if sym == "BTC-USD" else sym
            parts.append(f"{label} {sign}{val:.1f}%")
    return f"\U0001f30d Market: {' | '.join(parts)}" if parts else ""

# ── Watchlist helper ────────────────────────────────────────────────

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
            "/chart": self._cmd_chart,
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
            "/chart [days] \u2013 Equity curve & P&L chart (default 30d)\n"
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
                    total_pnl = float(p.total_value or 0) - float(p.invested_amount or 0)  # CHANGED: P&L = value - invested
                    pnl_sign = "+" if total_pnl >= 0 else ""
                    tbl = [
                        f"{'Metric':<12} {'Value':>14}",
                        "\u2500" * 28,
                        f"{'Value':<12} {s}{p.total_value:>14,.2f}",
                        f"{'Invested':<12} {s}{p.invested_amount:>14,.2f}",
                        f"{'P&L':<12} {s}{pnl_sign}{total_pnl:>13,.2f}",
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

    async def _ai_reallocate(self, results: list[dict], total_value: float = 0) -> tuple[str, list]:
        """Ask AI for portfolio reallocation suggestions. Returns (html_block, raw_suggestions)."""
        from backend.monitoring.ai_health_engine import AI_AVAILABLE

        if not AI_AVAILABLE or not results:
            return "", []

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
        if not api_key:
            return "", []

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
            consistency = r.get("profitable_months_pct") or "N/A"
            lines.append(f"- {name}: alloc={alloc:.0f}% return={ret:+.1f}% risk={risk} dd={dd if dd else 'N/A'}% consistency={consistency}")
        lines.append("")
        lines.append(f"Total allocation currently: {total_alloc:.0f}%. Keep total at {total_alloc:.0f}% after reallocation.")
        lines.append("Base decisions on multi-month return trends, consistency, drawdown history, and risk score. Ignore single-day movements.")
        lines.append("Return ONLY valid JSON object: {\"reallocations\": [{\"name\":\"...\",\"from\":N,\"to\":N,\"reason\":\"...\"}]}")
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
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
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
            if isinstance(data, dict):
                for key in ("suggestions", "reallocations", "allocations", "items"):
                    if key in data:
                        suggestions = data[key]
                        break
                else:
                    logger.error(f"AI reallocation: unexpected JSON format: {raw[:200]}")
                    return "", []
            elif isinstance(data, list):
                suggestions = data
            else:
                logger.error(f"AI reallocation: unexpected JSON format: {raw[:200]}")
                return "", []

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
                fr_amt = fr / 100 * total_value if total_value else 0
                to_amt = to / 100 * total_value if total_value else 0
                if total_value:
                    amt_str = f" (${fr_amt:,.0f}\u2192${to_amt:,.0f})"
                else:
                    amt_str = ""
                if to > fr:
                    icon = "\u2b06\ufe0f"
                elif to < fr:
                    icon = "\u2b07\ufe0f"
                else:
                    icon = "\u27a1\ufe0f"
                block.append(f"{icon} {name[:10]:<{NAME_W}} {fr:.0f}%\u2192{to:.0f}%{amt_str}  ({reason})")
            sum_from = sum(s.get("from", 0) for s in suggestions)
            sum_to = sum(s.get("to", 0) for s in suggestions)
            if abs(sum_to - sum_from) > 1:
                diff = sum_from - sum_to
                if diff > 0:
                    cash_amt = diff / 100 * total_value if total_value else 0
                    cash_str = f" (${cash_amt:,.0f})" if total_value else ""
                    block.append(f"\U0001f4b0 Cash remainder: {diff:.0f}%{cash_str}")
                else:
                    block.append(f"\u26a0\ufe0f Over-allocated by {abs(diff):.0f}%")
            return "\n".join(block), suggestions

        except Exception as e:
            logger.exception(f"AI reallocation failed: {e}")
            return "", []

    async def _cmd_chart(self, update: Update, args: list[str]) -> None:
        """Equity curve + daily P&L chart."""
        from backend.database.connection import db_session
        from backend.database.models import Portfolio, PortfolioSnapshot
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from io import BytesIO

        try:
            days = 30
            if args and args[0].isdigit():
                days = min(int(args[0]), 365)

            with db_session() as db:
                p = db.query(Portfolio).first()
                if not p:
                    await self._reply(update, "No portfolio found.")
                    return

                since = datetime.utcnow() - timedelta(days=days)
                snaps = (
                    db.query(PortfolioSnapshot)
                    .filter(
                        PortfolioSnapshot.portfolio_id == p.id,
                        PortfolioSnapshot.recorded_at >= since,
                    )
                    .order_by(PortfolioSnapshot.recorded_at.asc())
                    .all()
                )

                if len(snaps) < 2:
                    await self._reply(update, f"Not enough data ({len(snaps)} snapshots). Sync more days first.")
                    return

                dates = [s.recorded_at for s in snaps]
                values = [s.total_value for s in snaps]
                pnl = [0.0]
                for i in range(1, len(values)):
                    pnl.append(values[i] - values[i - 1])
                currency = p.currency or "USD"

            plt.style.use("dark_background")
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), gridspec_kw={"height_ratios": [3, 1]})
            fig.patch.set_facecolor("#1a1a2e")

            for ax in (ax1, ax2):
                ax.set_facecolor("#1a1a2e")
                ax.tick_params(colors="#888888")
                ax.spines["bottom"].set_color("#333333")
                ax.spines["left"].set_color("#333333")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)

            ax1.plot(dates, values, color="#00d4aa", linewidth=2, label="Equity")
            ax1.fill_between(dates, values[0], values, alpha=0.1, color="#00d4aa")
            start_val = values[0] if values else 0
            end_val = values[-1] if values else 0
            pnl_total = end_val - start_val
            color = "#00d4aa" if pnl_total >= 0 else "#ff6b6b"
            s = self._sym(currency)
            ax1.set_title(f"Portfolio ({days}d)", color="#ffffff", fontsize=14, fontweight="bold")
            ax1.set_ylabel(f"Value ({s})", color="#888888")
            ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{s}{x:,.0f}"))
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax1.legend([f"Equity  ({pnl_total:+.2f}{s})"], loc="upper left", facecolor="#1a1a2e", labelcolor="#cccccc")

            colors = ["#00d4aa" if v >= 0 else "#ff6b6b" for v in pnl]
            ax2.bar(dates, pnl, color=colors, width=max(0.5, days * 0.02))
            ax2.axhline(y=0, color="#555555", linewidth=0.5)
            ax2.set_ylabel(f"Daily P&L ({s})", color="#888888")
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{s}{x:+,.0f}"))
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

            plt.tight_layout()
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)

            caption = (
                f"\U0001f4c8 <b>Portfolio Equity</b>  |  {days}d\n"
                f"{s}{start_val:,.2f} \u2192 {s}{end_val:,.2f}  ({pnl_total:+.2f}{s})"
            )
            await update.message.reply_photo(photo=buf, caption=caption, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Chart generation failed")
            await self._reply(update, f"\u274c Chart error: {e}")

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

            # Build portfolio summary
            val = float(p.total_value or 0)
            inv = float(p.invested_amount or 0)
            old_pnl = float((p.unrealized_pnl or 0) + (p.realized_pnl or 0))
            new_pnl = val - inv
            logger.info(f"P&L DEBUG: value={val:.2f} invested={inv:.2f} old_pnl(unrealized+realized)={old_pnl:.2f} new_pnl(value-invested)={new_pnl:.2f}")
            total_pnl = new_pnl  # CHANGED: P&L = value - invested (was unrealized+realized)
            portfolio_summary = {
                "total_value": val,
                "invested": inv,
                "cash": float(p.available_cash or 0),
                "pnl": total_pnl,
                "traders": len(enriched),
            }

            # AI portfolio summary (separate — AI expects different field names)
            ai_portfolio_summary = {
                "total_invested_capital": float(p.invested_amount or 0),
                "total_portfolio_value": float(p.total_value or 0),
                "total_available_cash": float(p.available_cash or 0),
            }

            # Try AI analysis on the full batch
            ai_results = await ai_analyze_traders(enriched, ai_portfolio_summary)

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
                        "return_1m": td.get("return_1m"),
                        "this_week_gain": td.get("return_1w"),  # CHANGED: populate weekly return from trader data
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

            # Enrich with DD/risk from tradeinfo API (limited to 3 concurrent to avoid OOM)
            sem = asyncio.Semaphore(3)

            async def _enrich_trader(r):
                async with sem:
                    name = r.get("name") or r.get("trader")
                    # First, check hardcoded 12M DD values (confirmed from eToro UI)
                    hardcoded_dd = HARDCODED_12M_DD.get(name.lower().strip())
                    if hardcoded_dd is not None:
                        r["real_dd"] = abs(hardcoded_dd)
                        r["dd_source"] = "yearlyDd"
                    else:
                        r["dd_source"] = "unverified"
                    try:
                        m = await etoro_client.get_trader_metrics(name)
                        if m.get("available"):
                            if hardcoded_dd is None:
                                yd = m.get("yearly_dd")
                                if yd is not None:
                                    r["real_dd"] = abs(yd)
                                    r["dd_source"] = "yearlyDd"
                                else:
                                    dd_val = m.get("max_drawdown")
                                    dd_field = m.get("dd_field")
                                    if dd_val is not None:
                                        r["real_dd"] = abs(dd_val)
                                        r["dd_source"] = dd_field or "yearlyDd"
                            r["real_risk"] = m.get("risk_score")
                            r["profitable_months_pct"] = m.get("profitable_months_pct")
                            r["win_ratio"] = m.get("win_ratio")
                            r["trades_count"] = m.get("trades_count")
                            r["weeks_since_registration"] = m.get("weeks_since_registration")
                            r["this_week_gain"] = m.get("this_week_gain")  # CHANGED: populate weekly return from tradeinfo API
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

            # Fetch market data first (used in both health summary and market line)
            market_data = await _fetch_market_data()
            market_line = _format_market_line(market_data) if market_data else ""

            # Get AI reallocation suggestions (used in Rebalancing Decision)
            realloc_suggestions = []
            if show_reallocation:
                _, realloc_suggestions = await self._ai_reallocate(results, portfolio_summary.get("total_value", 0))

            summary = _build_health_summary(results, live=freshness, source_label=label, ts=ts, ai_used=bool(ai_results), realloc_suggestions=realloc_suggestions, market_data=market_data)

            # Build portfolio preamble
            val = portfolio_summary["total_value"]
            inv = portfolio_summary["invested"]
            cash = portfolio_summary["cash"]
            pnl = portfolio_summary["pnl"]
            pnl_icon = "\u2705" if pnl >= 0 else "\u274c"
            pnl_sign = "+" if pnl >= 0 else ""
            tc = portfolio_summary["traders"]
            preamble = (
                f"Value: ${val:,.2f} | Invested: ${inv:,.2f}\n"
                f"P&L: {pnl_sign}${pnl:,.2f} {pnl_icon} | Cash: ${cash:,.2f} | {tc} Traders"
            )
            summary = preamble + "\n\n" + summary
            if market_line:
                summary = market_line + "\n\n" + summary
            # Save each trader's health score to rolling history
            try:
                scores = {}
                for r in results:
                    name = r.get("name") or r.get("trader")
                    sc = r.get("_health_score")
                    if name and sc is not None:
                        scores[name] = sc
                if scores:
                    _save_score_history(scores)
            except Exception:
                logger.exception("Failed to save score history")

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
    ret_1m = r.get("return_1m")
    blended_pl = 0.50 * cum_pl + 0.50 * ret_1m if ret_1m is not None else cum_pl
    dd_abs = abs(r.get("real_dd") or 0)
    risk = r.get("real_risk") or r.get("risk_score") or 0
    dd_source = r.get("dd_source", "unknown")
    dd_confident = dd_source == "yearlyDd"
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

    if cum_pl < -2:
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

    # ── UNCOPY override: DD > 35% (confirmed threshold) ──
    if excessive_dd and dd_confident:
        bucket = "uncopy"
        confidence = "High"
        add_reason(f"Drawdown {dd_abs:.0f}% exceeds UNCOPY threshold")
    elif score < 50:
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
        if cum_pl > 0:
            add_reason(f"Return +{cum_pl:.1f}%")
        if severe_decline:
            bucket = "watch"
            confidence = "Medium"
            add_reason("Score strong but severe trend decline")

    # ── KEEP/WATCH: score 60-74 ──
    elif score >= 60:
        # Negative return on significant loss with borderline score: uncopy
        if blended_pl < -5 and score < 65:
            bucket = "uncopy"
            confidence = "Medium"
            add_reason(f"Negative return with score {score}/100")
        elif trend_positive or (consistency >= 60 and not trend_declining):
            bucket = "keep"
            confidence = "Medium"
            if cum_pl > 0:
                add_reason(f"Return +{cum_pl:.1f}%")
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

    # ── Holdings override: without transparency, CORE HOLD is prohibited ──
    ds = r.get("_dim_scores") or _compute_dimension_scores(r)
    if not ds.get("has_holdings", False):
        if bucket == "keep":
            bucket = "watch"
            confidence = "Low"
            add_reason("CORE HOLD requires holdings visibility")
        elif bucket == "uncopy":
            # Only justify EXIT without holdings for extreme confirmed drawdown
            if not (excessive_dd and dd_confident):
                bucket = "watch"
                confidence = "Low"
                add_reason("Holdings unavailable \u2014 cannot justify EXIT")

    if not reasons:
        add_reason(f"Score {score}/100")

    return bucket, " \u2022 ".join(reasons), confidence


def _compute_dimension_scores(r: dict) -> dict:
    """Three-dimension score: Risk Management (25), Consistency (25), Drawdown Control (20).

    Transparency is a data-access limitation, not a trader quality — excluded from score.
    Market Alignment is derived as a text label, not a numeric sub-score.
    Returns {risk_mgmt, consistency, drawdown_ctrl, total, has_holdings, has_news, confidence}.
    """
    holdings = r.get("_holdings") or []
    dd = abs(r.get("real_dd") or 0)
    rs = r.get("real_risk") or r.get("risk_score") or 0
    pm = r.get("profitable_months_pct")
    ret = r.get("total_return_pct") or 0
    has_holdings = bool(holdings)
    news = r.get("_news_by_symbol") or {}
    has_news = bool(news)

    # ── Risk Management (25) — drawdown magnitude + risk score ──
    dd_p = 14 if dd < 10 else (12 if dd < 15 else (10 if dd < 20 else (8 if dd < 25 else 5)))
    rs_p = 11 if 4 <= rs <= 5 else (9 if 3 <= rs <= 6 else (7 if 2 <= rs <= 7 else 4))
    risk_mgmt = min(25, max(5, dd_p + rs_p))

    # ── Consistency (25) — profitable months + return behavior ──
    cs = 10
    if pm is not None:
        cs += (10 if pm >= 70 else (7 if pm >= 55 else (5 if pm >= 40 else 2)))
    else:
        cs += 5
    cs += 3 if -3 < ret < 3 else (5 if ret >= 3 else 0)
    consistency = min(25, max(5, cs))

    # ── Drawdown Control (20) — peak-to-trough magnitude ──
    dc = 18 if dd < 10 else (15 if dd < 15 else (12 if dd < 20 else (8 if dd < 25 else 4)))
    drawdown_ctrl = min(20, max(4, dc))

    # ── Total — rescale to /100 (max available is 70) ──
    raw = risk_mgmt + consistency + drawdown_ctrl
    total_score = int(round(raw / 70 * 100))

    # ── Confidence: based on signal quality, not data completeness ──
    has_dd = bool(abs(r.get("real_dd") or 0))
    has_pm = r.get("profitable_months_pct") is not None
    if has_dd and has_pm and pm is not None and pm > 0:
        confidence = "High"
    elif has_dd:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "risk_mgmt": risk_mgmt,
        "consistency": consistency,
        "drawdown_ctrl": drawdown_ctrl,
        "total": min(100, max(0, int(round(total_score)))),
        "has_holdings": has_holdings,
        "has_news": has_news,
        "confidence": confidence,
    }


def _compute_health_score(r: dict) -> int:
    """Weighted score 0-100. Delegates to dimension scores for total."""
    return _compute_dimension_scores(r)["total"]


def _derive_market_context(trader_return: float, md: dict) -> str:
    """Derive market context label from trader return vs SPY/QQQ/BTC.
    Never returns 'N/A' or 'Unknown' — always a specific reason.
    """
    if trader_return is None:
        return "trader return unavailable"
    if not md or not any(v is not None for v in md.values()):
        return "benchmark data unavailable"
    spy = md.get("SPY")
    qqq = md.get("QQQ")
    btc = md.get("BTC-USD")
    spy_or_qqq_up = (spy is not None and spy > 0) or (qqq is not None and qqq > 0)
    if spy_or_qqq_up and trader_return > 0:
        return "Aligned"
    if spy_or_qqq_up and trader_return <= 0:
        return "Lagging"
    # Check if trader tracks BTC more than equities
    if btc is not None:
        btc_up = btc > 0
        trader_up = trader_return > 0
        if btc_up == trader_up:
            return "Crypto-correlated"
    return "Uncorrelated"


def _build_health_summary(results: list[dict], live: bool = False, source_label: str = "Cached", ts: str = "", ai_used: bool = False, realloc_suggestions: list | None = None, market_data: dict | None = None) -> str:
    total = len(results)
    source_tag = source_label if source_label else ("Live" if live else "Cached")

    # Compute and cache dimension scores + health score per trader
    for r in results:
        if "_dim_scores" not in r:
            r["_dim_scores"] = _compute_dimension_scores(r)
        if "_health_score" not in r:
            r["_health_score"] = r["_dim_scores"]["total"]
    for r in results:
        watch_count = r.get("watch_consecutive", 0)
        bucket, reason, confidence = _assess_trader(r, watch_count)
        r["_assessed_reason"] = reason
        r["_assessed_confidence"] = confidence

    logger.info(
        f"HEALTH REPORT: {total} traders ({source_tag}), "
        f"{sum(1 for r in results if _assess_trader(r, r.get('watch_consecutive', 0))[0]=='keep')} core, "
        f"{sum(1 for r in results if _assess_trader(r, r.get('watch_consecutive', 0))[0]=='uncopy')} exit"
    )

    def _is_declining(r: dict) -> bool:
        """Trader is declining if assess reason says 'declining' OR score trend is down."""
        if r.get("_assessed_reason", "").find("declining") >= 0:
            return True
        if _score_trend(r.get("trader", "?"), r["_health_score"]) == "\u2193":
            return True
        return False

    # ── Overall Portfolio Health Score ──
    total_alloc = sum(r.get("allocation_pct") or 0 for r in results) or 1
    weighted_score = sum(
        r["_health_score"] * (r.get("allocation_pct") or 0) / total_alloc for r in results
    )
    overall_score = int(round(weighted_score))

    if overall_score >= 75:
        status = "\U0001f7e2 Strong"
    elif overall_score >= 60:
        status = "\U0001f7e1 Stable"
    elif overall_score >= 40:
        status = "\U0001f7e0 Caution"
    else:
        status = "\U0001f534 Review Required"

    # Overall confidence based on signal quality, not data completeness
    confs = [r["_dim_scores"]["confidence"] for r in results]
    if "Low" in confs:
        overall_confidence = "Low"
    elif "Medium" in confs:
        overall_confidence = "Medium"
    else:
        overall_confidence = "High"

    has_any_holdings = any(r["_dim_scores"]["has_holdings"] for r in results)

    lines = [f"\U0001f4ca <b>PORTFOLIO HEALTH REPORT</b>"]
    lines.append(f"\n<b>Overall Health Score: {overall_score}/100</b>")
    lines.append(f"Status: {status}  |  Confidence: {overall_confidence}")
    # One-line data limitation note at the top (not repeated per trader)
    if not has_any_holdings:
        lines.append("\U0001f6a7 Holdings data unavailable \u2014 analysis based on performance metrics only.")

    # ── Portfolio Summary ──
    core_count = sum(1 for r in results if _assess_trader(r, r.get("watch_consecutive", 0))[0] == "keep")
    exit_count = sum(1 for r in results if _assess_trader(r, r.get("watch_consecutive", 0))[0] == "uncopy")
    avg_dd = sum(abs(r.get("real_dd") or 0) for r in results) / max(total, 1)
    avg_ret = sum(r.get("total_return_pct") or 0 for r in results) / max(total, 1)
    declining_count = sum(1 for r in results if _is_declining(r))

    sector_map = {}
    all_symbols = set()
    for r in results:
        for h in (r.get("_holdings") or []):
            t = h.get("type", "other")
            sector_map[t] = sector_map.get(t, 0) + h.get("weight", 0)
            all_symbols.add(h.get("symbol", "").upper())
    top_sector = max(sector_map.items(), key=lambda x: x[1]) if sector_map else ("unknown", 0)

    spts = []
    lpts = []
    if avg_ret > 0:
        spts.append("Portfolio profitable")
    if avg_dd < 15:
        spts.append(f"Drawdown controlled ({avg_dd:.1f}%)")
    if declining_count == 0:
        spts.append("No traders in decline")
    if exit_count == 0:
        spts.append("No EXIT candidates")
    if core_count >= total * 0.5 and has_any_holdings:
        spts.append(f"{core_count}/{total} CORE HOLD")

    if not has_any_holdings:
        lpts.append("Holdings transparency unavailable")
        lpts.append("Sector exposure unknown")
    else:
        if len(all_symbols) >= 8:
            spts.append(f"{len(all_symbols)} unique holdings")
        if top_sector[1] > 50:
            lpts.append(f"Concentrated in {top_sector[0]} ({top_sector[1]:.0f}%)")
        if len(all_symbols) < 5:
            lpts.append("Highly concentrated holdings")
    if exit_count > 0:
        lpts.append(f"{exit_count} trader(s) flagged for EXIT")
    if avg_dd > 20:
        lpts.append(f"Elevated drawdown {avg_dd:.1f}%")
    if total < 5:
        lpts.append(f"Only {total} traders \u2014 limited diversification")

    lines.append(f"\n<b>Portfolio Summary</b>")
    if spts:
        lines.append("\U0001f7e2 " + " | ".join(spts))
    if lpts:
        lines.append("\U0001f7e1 " + " | ".join(lpts))
    if not spts and not lpts:
        lines.append("Neutral \u2014 no strong directional signals")

    # ── Trader Analysis ──
    lines.append("\n" + "\u2500" * 35)
    lines.append("<b>TRADER ANALYSIS</b>")

    def _classify(r: dict) -> str:
        ds, sc, bucket = r["_dim_scores"], r["_health_score"], _assess_trader(r, r.get("watch_consecutive", 0))[0]
        if not ds["has_holdings"]:
            return "\U0001f534 EXIT" if bucket == "uncopy" else "\U0001f7e1 MONITOR"
        if bucket == "keep" and sc >= 75:
            return "\U0001f7e2 CORE HOLD"
        if bucket == "keep":
            return "\U0001f7e1 MONITOR"
        if bucket == "uncopy":
            return "\U0001f534 EXIT"
        return "\U0001f7e1 MONITOR" if sc >= 45 else "\U0001f7e0 REDUCE"

    for r in results:
        ds = r["_dim_scores"]
        sc = r["_health_score"]
        name = r.get("trader") or r.get("name", "?")
        alloc = r.get("allocation_pct") or 0
        sig = _classify(r)
        ret = r.get("total_return_pct")  # keep None for mkt ctx fallback
        dd = abs(r.get("real_dd") or 0)
        rs = r.get("real_risk") or r.get("risk_score") or 0
        pm = r.get("profitable_months_pct")
        mkt_ctx = _derive_market_context(ret, market_data or {})

        lines.append(f"\n<b>{name}</b> \u2014 {sig}")
        lines.append(f"Score: {sc}/100 | Alloc: {alloc:.0f}%")
        lines.append(f"Risk:{ds['risk_mgmt']}/25  Cons:{ds['consistency']}/25  DD:{ds['drawdown_ctrl']}/20 | Mkt: {mkt_ctx}")
        perf_parts = []
        if ret is not None and abs(ret) >= 1:
            perf_parts.append(f"Ret: {ret:+.1f}%")
        if dd > 0:
            perf_parts.append(f"DD: {dd:.0f}%")
        if rs:
            perf_parts.append(f"Risk: {rs:.0f}/10")
        if pm is not None:
            perf_parts.append(f"Profitable: {pm:.0f}% months")
        if perf_parts:
            lines.append(" | ".join(perf_parts))
        assessed = r.get("_assessed_reason") or ""
        if assessed:
            # Strip internal tracking labels (Rule 6)
            clean = assessed
            for token in ("Watch scan", "cycle", "iteration"):
                idx = clean.lower().find(token.lower())
                if idx >= 0:
                    end = clean.find("\u2022", idx)
                    if end >= 0:
                        clean = clean[:idx] + clean[end + 1:]
                    else:
                        clean = clean[:idx].rstrip()
            clean = clean.strip(" \u2022")
            if clean:
                brief = clean[:100] if len(clean) > 100 else clean
                lines.append(f"\U0001f4ac {brief}")

    # ── Market Intelligence ──
    lines.append("\n" + "\u2500" * 35)
    lines.append("\U0001f30d <b>MARKET INTELLIGENCE</b>")

    if not has_any_holdings:
        lines.append("Market intelligence limited because underlying holdings are unavailable.")
        lines.append("Cannot evaluate sector exposure, company risks, or valuation concerns.")
    else:
        pos_syms, neg_syms = set(), set()
        for r in results:
            for sym, articles in (r.get("_news_by_symbol") or {}).items():
                for a in articles:
                    sent = a.get("sentiment", "neutral")
                    if sent == "positive":
                        pos_syms.add(sym)
                    elif sent == "negative":
                        neg_syms.add(sym)

        news_parts = []
        if pos_syms:
            news_parts.append(f"Positive: {', '.join(sorted(pos_syms)[:5])}")
        if neg_syms:
            news_parts.append(f"Negative: {', '.join(sorted(neg_syms)[:5])}")
        if news_parts:
            lines.append(" | ".join(news_parts))
        else:
            lines.append("No significant news signals across holdings")

        if sector_map:
            top_sectors = sorted(sector_map.items(), key=lambda x: -x[1])[:3]
            lines.append("Sector: " + " | ".join(f"{k} {v:.0f}%" for k, v in top_sectors))
        else:
            lines.append("Holdings data: UNAVAILABLE \u2014 cannot evaluate sector exposure or concentration risk")

    # ── Rebalancing Decision ──
    lines.append("\n" + "\u2500" * 35)
    lines.append("\U0001f504 <b>REBALANCING DECISION</b>")

    # Conditional recommendations based on available metrics
    rebal_lines = []
    for r in results:
        ret = r.get("total_return_pct") or 0
        dd = abs(r.get("real_dd") or 0)
        pm = r.get("profitable_months_pct")
        name = r.get("trader") or r.get("name", "?")
        declining = _is_declining(r)
        if ret < 0 and declining:
            rebal_lines.append(f"\u2b07\ufe0f <b>Reduce {name}</b> \u2014 negative return, declining trend")
        elif dd >= 18 and ret < 2:
            rebal_lines.append(f"\u26a0\ufe0f <b>Trim {name}</b> \u2014 drawdown {dd:.0f}%, consider if worsens")
        elif dd < 10 and ret > 0 and pm is not None and pm > 70:
            rebal_lines.append(f"\u2b06\ufe0f <b>Increase {name}</b> \u2014 low DD, profitable >70% months")
    if rebal_lines:
        lines.extend(rebal_lines)
    else:
        lines.append("\U0001f7e1 <b>MAINTAIN CURRENT ALLOCATION</b> \u2014 no strong directional signals from available data")

    # ── Bottom Summary — 3 bullets: risk, opportunity, action ──
    lines.append("\n" + "\u2500" * 35)
    lines.append("\U0001f4dc <b>SUMMARY</b>")

    improving_ct = sum(1 for r in results if _score_trend(r.get("trader", "?"), r["_health_score"]) == "\u2191")
    declining_ct = sum(1 for r in results if _is_declining(r))
    total_pl = sum(r.get("total_return_pct") or 0 for r in results)

    risk_bullet = f"\U0001f6a9 <b>Risk:</b> Drawdown avg {avg_dd:.1f}%" if avg_dd > 0 else ""
    if declining_ct > improving_ct:
        risk_bullet += f", {declining_ct}/{total} traders declining"
    if not risk_bullet:
        risk_bullet = "\U0001f6a9 <b>Risk:</b> No material deterioration detected"

    if total_pl > 0:
        opp_bullet = f"\U0001f7e2 <b>Opportunity:</b> Portfolio profitable; {'increase' if avg_dd < 15 else 'maintain'} allocation"
    else:
        opp_bullet = f"\U0001f7e2 <b>Opportunity:</b> Market conditions may present entry points"

    action_bullet = f"\U0001f4a1 <b>Action:</b> Maintain allocation, monitor {declining_ct} declining trader(s)" if declining_ct > 0 else "\U0001f4a1 <b>Action:</b> Maintain current allocation"

    lines.append(risk_bullet)
    lines.append(opp_bullet)
    lines.append(action_bullet)

    if ts:
        lines.append(f"\n\U0001f4c5 {ts} ({source_tag})")

    return "\n".join(lines)

