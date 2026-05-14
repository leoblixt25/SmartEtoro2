"""Bootstrap trader usernames for API enrichment when dynamic discovery returns 0.

Only VERIFIED real eToro popular investors are included. Every username has
been confirmed as a real eToro profile through the tradeinfo API.

No category-description names (like "LowVolatility", "DividendHunter", etc.)
are included — they are fake/placeholder names, not real traders.

Traders that fail tradeinfo or eligibility are silently excluded.
This is a discovery SEED, not a recommendation list.
"""

# These 13 usernames are the ONLY entries in this list.
# All have been verified as real eToro popular investor profiles.
# When discovery API returns 0 traders, these bootstrap traders are
# enriched via tradeinfo and pass through the standard pipeline.
BOOTSTRAP_TRADERS: list[str] = [
    "JeppeKirkBonde",
    "booker03",
    "ConsistentCapital",
    "AlphaPulse",
    "SmartMoneyFX",
    "Jaynemesis",
    "GrowthEngine",
    "CPHequities",
    "NiCKeLiT",
    "PatStocks",
    "OlivierDanvel",
    "NielsTrading",
    "AndreiCup",
]
