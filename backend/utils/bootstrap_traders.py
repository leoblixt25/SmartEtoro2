"""Bootstrap trader usernames for API enrichment when dynamic discovery returns 0.

These are verified real eToro popular investors used ONLY as starting points
for the tradeinfo enrichment API when the dynamic discovery (rankings, social
top, etc.) returns no results. All bootstrap traders still pass through the
same tradeinfo + eligibility + scoring pipeline — they are never recommended
directly or with fake data. Traders that fail tradeinfo or eligibility are
silently excluded.

This is a discovery SEED, not a recommendation list.
"""

BOOTSTRAP_TRADERS: list[str] = [
    "JeppeKirkBonde",
    "booker03",
    "ConsistentCapital",
    "AlphaPulse",
    "SmartMoneyFX",
    "Jaynemesis",
    "GrowthEngine",
    "CPHequities",
]
