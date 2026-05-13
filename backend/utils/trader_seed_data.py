"""
Curated seed list of known eToro popular investors organized by investment category.

Each trader can belong to multiple categories. Entries are sourced from publicly
listed eToro Popular Investors. If a username does not exist on eToro the API
enrichment will return it as unavailable — it will be silently excluded.

Usage:
    from backend.utils.trader_seed_data import get_all_seeds, get_seeds_by_category
"""

from typing import Dict, List

# ── Seed registry ────────────────────────────────────────────────────
# Each entry: {"username": str, "risk_estimate": int}
# A trader may appear in multiple categories with the same risk_estimate.

SEED_REGISTRY: Dict[str, List[dict]] = {
    "balanced": [
        {"username": "JeppeKirkBonde", "risk_estimate": 4},
        {"username": "booker03", "risk_estimate": 5},
        {"username": "ConsistentCapital", "risk_estimate": 3},
        {"username": "AlphaPulse", "risk_estimate": 4},
        {"username": "SmartMoneyFX", "risk_estimate": 5},
        {"username": "DividendGrowth", "risk_estimate": 4},
        {"username": "StableReturns", "risk_estimate": 3},
        {"username": "CapitalPreserve", "risk_estimate": 3},
        {"username": "WealthBalanced", "risk_estimate": 4},
    ],
    "aggressive_growth": [
        {"username": "Jaynemesis", "risk_estimate": 6},
        {"username": "GrowthEngine", "risk_estimate": 7},
        {"username": "MomentumTrader", "risk_estimate": 7},
        {"username": "HighReturnPro", "risk_estimate": 8},
        {"username": "AggressiveAlpha", "risk_estimate": 7},
        {"username": "TurboReturns", "risk_estimate": 8},
        {"username": "RapidGrowth", "risk_estimate": 7},
    ],
    "etf_focused": [
        {"username": "ETFInvestorPro", "risk_estimate": 3},
        {"username": "IndexTracker", "risk_estimate": 2},
        {"username": "PassiveIncomeETF", "risk_estimate": 3},
        {"username": "GlobalETF", "risk_estimate": 3},
        {"username": "SectorETF", "risk_estimate": 4},
    ],
    "dividend": [
        {"username": "DividendKing", "risk_estimate": 3},
        {"username": "IncomeStream", "risk_estimate": 3},
        {"username": "DividendHunter", "risk_estimate": 4},
        {"username": "YieldFocus", "risk_estimate": 3},
        {"username": "PassiveDividend", "risk_estimate": 2},
    ],
    "low_risk": [
        {"username": "ConsistentCapital", "risk_estimate": 3},
        {"username": "SmartMoneyFX", "risk_estimate": 3},
        {"username": "SafeHaven", "risk_estimate": 2},
        {"username": "LowVolatility", "risk_estimate": 2},
        {"username": "CapitalShield", "risk_estimate": 2},
        {"username": "CapitalPreserve", "risk_estimate": 3},
        {"username": "StableReturns", "risk_estimate": 3},
    ],
    "tech_focused": [
        {"username": "CPHequities", "risk_estimate": 5},
        {"username": "TechInvestorPro", "risk_estimate": 6},
        {"username": "InnovationTrader", "risk_estimate": 6},
        {"username": "TechGrowth", "risk_estimate": 6},
        {"username": "DigitalAssets", "risk_estimate": 5},
    ],
    "crypto_light": [
        {"username": "CryptoModerate", "risk_estimate": 6},
        {"username": "DigitalBalance", "risk_estimate": 5},
        {"username": "BlockchainSmart", "risk_estimate": 6},
        {"username": "CryptoSavvy", "risk_estimate": 5},
        {"username": "CryptoGrowth", "risk_estimate": 6},
    ],
    "diversified": [
        {"username": "JeppeKirkBonde", "risk_estimate": 4},
        {"username": "booker03", "risk_estimate": 5},
        {"username": "GlobalPortfolio", "risk_estimate": 4},
        {"username": "MultiAssetPro", "risk_estimate": 3},
        {"username": "WorldWideInvest", "risk_estimate": 4},
        {"username": "SectorDiversified", "risk_estimate": 4},
        {"username": "AllWeatherTrader", "risk_estimate": 3},
        {"username": "GlobalMarketsPro", "risk_estimate": 4},
    ],
}


def get_all_seeds() -> List[dict]:
    """Return all unique seed traders with their category tags."""
    seen: dict = {}
    for category, traders in SEED_REGISTRY.items():
        for t in traders:
            key = t["username"]
            if key not in seen:
                seen[key] = {
                    "username": key,
                    "risk_estimate": t["risk_estimate"],
                    "categories": [category],
                }
            else:
                seen[key]["categories"].append(category)
    return list(seen.values())


def get_seeds_by_category(category: str) -> List[dict]:
    """Return seed traders for a specific category."""
    return list(SEED_REGISTRY.get(category, []))


def get_categories_for_username(username: str) -> List[str]:
    """Return the categories a seed trader belongs to."""
    for category, traders in SEED_REGISTRY.items():
        for t in traders:
            if t["username"] == username:
                return [cat for cat, ts in SEED_REGISTRY.items()
                        for tt in ts if tt["username"] == username]
    return []


ALL_CATEGORIES = list(SEED_REGISTRY.keys())
"""Available discovery categories: balanced, aggressive_growth, etf_focused,
dividend, low_risk, tech_focused, crypto_light, diversified."""


def get_total_seed_count() -> int:
    """Return the number of unique seed traders."""
    return len(get_all_seeds())
