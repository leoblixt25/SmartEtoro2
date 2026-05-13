"""
Minimal seed list of known eToro popular investors.

Only includes usernames that have been verified as real eToro profiles.
Seeds are used ONLY as a backup discovery source when the eToro social
API returns no results. The primary discovery flow is:
  eToro discovery API → validate → enrich → filter → score → recommend
"""

from typing import Dict, List

SEED_REGISTRY: Dict[str, List[dict]] = {
    "balanced": [
        {"username": "JeppeKirkBonde", "risk_estimate": 4},
        {"username": "booker03", "risk_estimate": 5},
        {"username": "ConsistentCapital", "risk_estimate": 3},
        {"username": "AlphaPulse", "risk_estimate": 4},
        {"username": "SmartMoneyFX", "risk_estimate": 5},
    ],
    "aggressive_growth": [
        {"username": "Jaynemesis", "risk_estimate": 6},
        {"username": "GrowthEngine", "risk_estimate": 7},
    ],
    "tech_focused": [
        {"username": "CPHequities", "risk_estimate": 5},
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


ALL_CATEGORIES = list(SEED_REGISTRY.keys())


def get_total_seed_count() -> int:
    """Return the number of unique seed traders."""
    return len(get_all_seeds())
