"""Shared constants for the platform backend."""

# ── Trader Discovery ────────────────────────────────────────────────
# CANDIDATE_TRADERS env var adds usernames to the merged discovery pool.
# Set it to a comma-separated list of eToro usernames, e.g.
#   CANDIDATE_TRADERS="user1,user2,user3"
# The seed list (trader_seed_data.py) provides the base candidate universe
# of ~45 traders across 8 categories. Set CANDIDATE_TRADERS to extend it.
CANDIDATE_TRADERS_ENV = "CANDIDATE_TRADERS"

# Legacy fallback — only used when seed data + API enrichment both fail.
FALLBACK_TRADERS = [
    "JeppeKirkBonde",
    "CPHequities",
    "Jaynemesis",
    "booker03",
    "ConsistentCapital",
    "GrowthEngine",
    "AlphaPulse",
    "SmartMoneyFX",
]

# Discovery categories from trader_seed_data.py
AVAILABLE_CATEGORIES = [
    "balanced", "aggressive_growth", "etf_focused", "dividend",
    "low_risk", "tech_focused", "crypto_light", "diversified",
]

# ── Scoring Weights ─────────────────────────────────────────────────
WEIGHT_PERFORMANCE = 0.30
WEIGHT_RISK = 0.25
WEIGHT_STABILITY = 0.20
WEIGHT_MARKET_BEHAVIOR = 0.15
WEIGHT_COPY_SUITABILITY = 0.10

# ── Scoring Thresholds ──────────────────────────────────────────────
GROWTH_FILTER_MIN_12M = 10.0
PENALTY_RISK_HIGH = 30
PENALTY_DRAWDOWN_HIGH = 20
CONSTRAINT_MAX_DRAWDOWN = 25.0
CONSTRAINT_MAX_RISK = 9.0

# ── Allocation ──────────────────────────────────────────────────────
TARGET_COUNT = 3
TARGET_ALLOCATION_PCT = 33.3
MIN_POSITION_SIZE = 200.0

# ── Telegram ────────────────────────────────────────────────────────
TELEGRAM_WEBHOOK_PATH = "/api/telegram/webhook"

# ── Scheduler ───────────────────────────────────────────────────────
KEEP_ALIVE_INTERVAL_MINUTES = 4
ETORO_SYNC_INTERVAL_MINUTES = 5

# ── eToro API ───────────────────────────────────────────────────────
ETORO_PUBLIC_API_BASE = "https://public-api.etoro.com/api/v1"
