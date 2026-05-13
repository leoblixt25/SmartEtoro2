"""
Holding Parser — extracts per-trader holdings from available data sources.

Sources (in priority order):
  1. Live API data — mirror positions from get_portfolio_data()
  2. Database — Position records with source="copy"
  3. Fallback — returns empty holdings with unknown status

For each trader, returns a list of held instruments with weight and type.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Instrument classification ───────────────────────────────────────

CRYPTO_KEYWORDS = ["BTC", "ETH", "XRP", "ADA", "SOL", "DOT", "DOGE", "LINK",
                   "MATIC", "AVAX", "UNI", "ATOM", "LTC", "BCH", "XLM"]
ETF_KEYWORDS = ["SPY", "QQQ", "IWM", "EFA", "VTI", "VOO", "BND", "GLD",
                "ARKK", "ARKW", "XLE", "XLF", "XLK", "XLV"]


def classify_instrument(symbol: str) -> str:
    """Classify a symbol as stock, crypto, etf, or other."""
    sym = symbol.upper().replace("-USD", "").replace("-USDT", "")
    if any(kw in sym for kw in CRYPTO_KEYWORDS):
        return "crypto"
    if sym in ETF_KEYWORDS or sym.endswith("^") or "/" in symbol:
        return "etf"
    return "stock"


def parse_holdings_from_mirrors(mirrors: List[Dict]) -> Dict[str, List[Dict]]:
    """Extract per-trader holdings from eToro API mirror data.

    Args:
        mirrors: List of mirror dicts from get_portfolio_data()['clientPortfolio']['mirrors']

    Each mirror has: parentUsername, positions[{instrument, amount, ...}]

    Returns:
        {username: [{symbol, name, weight, type, amount}, ...]}
    """
    result: Dict[str, List[Dict]] = {}

    for mirror in mirrors:
        username = mirror.get("parentUsername", "unknown")
        positions = mirror.get("positions", [])

        holdings = []
        total_amount = sum(
            abs(p.get("amount", 0) or 0) for p in positions
        )

        for pos in positions:
            instrument = pos.get("instrument", "")
            if not instrument:
                continue

            amount = abs(pos.get("amount", 0) or 0)
            weight = round(amount / max(total_amount, 1) * 100, 1) if total_amount > 0 else 0.0

            holdings.append({
                "symbol": instrument.upper(),
                "name": instrument,
                "weight": weight,
                "type": classify_instrument(instrument),
                "amount": amount,
            })

        # Sort by weight descending
        holdings.sort(key=lambda h: h["weight"], reverse=True)
        result[username] = holdings

    return result


def parse_holdings_from_db_positions(
    positions: List[Dict],
) -> List[Dict]:
    """Parse aggregate holdings from the Position table.

    Args:
        positions: List of Position dicts with instrument, amount, etc.

    Returns:
        List of holding dicts (no per-trader mapping).
    """
    holdings = []
    total_amount = sum(abs(p.get("amount", 0) or 0) for p in positions)

    for pos in positions:
        instrument = pos.get("instrument", "")
        if not instrument:
            continue

        amount = abs(pos.get("amount", 0) or 0)
        weight = round(amount / max(total_amount, 1) * 100, 1) if total_amount > 0 else 0.0

        holdings.append({
            "symbol": instrument.upper(),
            "name": instrument,
            "weight": weight,
            "type": classify_instrument(instrument),
            "amount": amount,
        })

    holdings.sort(key=lambda h: h["weight"], reverse=True)
    return holdings


def extract_symbols(holdings_list: List[Dict]) -> List[str]:
    """Extract unique symbols from a list of holdings."""
    seen: set = set()
    symbols = []
    for h in holdings_list:
        sym = h.get("symbol", "").upper()
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    return symbols


async def get_trader_holdings(
    db,
    portfolio_id: int,
    trader_username: str,
    etoro_client=None,
) -> Tuple[List[Dict], str]:
    """Get holdings for a specific trader.

    Returns:
        (holdings_list, source) where source is one of:
        "api_mirror", "db_positions", "unknown"
    """
    # Priority 1: Live API mirror data
    if etoro_client and etoro_client.enabled:
        try:
            raw = await etoro_client.get_portfolio_data()
            if raw:
                mirrors = raw.get("clientPortfolio", {}).get("mirrors", [])
                by_user = parse_holdings_from_mirrors(mirrors)
                holdings = by_user.get(trader_username, [])
                if holdings:
                    logger.info(
                        "Holdings for %s: %d positions via API",
                        trader_username, len(holdings),
                    )
                    return holdings, "api_mirror"
        except Exception as e:
            logger.warning("Failed to fetch API holdings for %s: %s", trader_username, e)

    # Priority 2: Database Position records with source="copy"
    try:
        from backend.database.models import Position
        positions = (
            db.query(Position)
            .filter(
                Position.portfolio_id == portfolio_id,
                Position.is_open.is_(True),
                Position.source == "copy",
            )
            .all()
        )
        if positions:
            pos_dicts = [
                {"instrument": p.instrument, "amount": p.amount}
                for p in positions
            ]
            holdings = parse_holdings_from_db_positions(pos_dicts)
            logger.info(
                "Holdings for %s: %d positions via DB",
                trader_username, len(holdings),
            )
            return holdings, "db_positions"
    except Exception as e:
        logger.warning("Failed to read DB positions for %s: %s", trader_username, e)

    # Fallback: no holdings data
    logger.info("No holdings data for %s — marking unknown", trader_username)
    return [], "unknown"
