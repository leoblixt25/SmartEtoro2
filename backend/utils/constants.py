"""
Shared constants for the CopyVault backend.

Centralized to eliminate duplicate definitions across modules
(e.g. FALLBACK_TRADERS defined in both market_data.py and automation_engine.py).
"""

# ── Trader Discovery ────────────────────────────────────────────────
FALLBACK_TRADERS = [
    "JeppeKirkBonde",
    "CPHequities",
    "Jaynemesis",
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
AUTOMATION_EVAL_INTERVAL_MINUTES = 2
RISK_CHECK_INTERVAL_MINUTES = 15

# ── eToro API ───────────────────────────────────────────────────────
ETORO_PUBLIC_API_BASE = "https://public-api.etoro.com/api/v1"
