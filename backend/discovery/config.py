"""Shared configuration for the discovery pipeline."""

# ── Scoring Weights ──────────────────────────────────────────────────
W_12M = 0.25
W_6M = 0.15
W_RISK = 0.20
W_MAX_DRAWDOWN = 0.20
W_CONSISTENCY = 0.20

# ── Penalties ────────────────────────────────────────────────────────
PENALTY_RISK_HIGH = 30
PENALTY_DRAWDOWN_HIGH = 20
GROWTH_FILTER_MIN_12M = 10.0

# ── Bonuses ──────────────────────────────────────────────────────────
COPIER_BONUS_MAX = 25.0
COPIER_BONUS_LOG_BASE = 10
COPIER_BONUS_SCALE = 12.5
MATURITY_BONUS = 10.0
MATURITY_MIN_POSITIONS = 5

# ── Confidence ───────────────────────────────────────────────────────
MIN_CONFIDENCE_TO_SCORE = 0.8
CONFIDENCE_FLOOR = 0.3
MISSING_RISK_PENALTY = 0.15
MISSING_COPIERS_PENALTY = 0.10
MISSING_RETURN_PENALTY = 0.20
MISSING_DD_PENALTY = 0.15
MISSING_VOL_PENALTY = 0.10

# ── Constraints ──────────────────────────────────────────────────────
CONSTRAINT_MAX_DRAWDOWN = 15.0
CONSTRAINT_MIN_TRACK_RECORD_DAYS = 365

# ── Data Quality Gates ───────────────────────────────────────────────
# Minimum verified fields (%s) required for a trader to be scored at all.
# If a trader has fewer verified fields than this, score = 0 ("insufficient data").
MIN_VERIFIED_FIELDS = 0
# Minimum final_score for a trader to appear in recommendations.
MIN_FINAL_SCORE_FOR_RECOMMENDATION = 10.0

# ── Discovery Scan Targets ──────────────────────────────────────────
DISCOVERY_SCAN_TARGET = 500
DISCOVERY_MIN = 200
DISCOVERY_MAX = 500

# ── Fetch Layer ──────────────────────────────────────────────────────
API_SEMAPHORE_MAX = 8
RATE_LIMIT_HIT_STOP = 10
REQUEST_TIMEOUT = 15.0
BROWSER_TIMEOUT = 10.0
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0

# ── Discovery Pipeline ───────────────────────────────────────────────
COOLDOWN_SECONDS = 60.0
CACHE_TTL_SECONDS = 300.0
MIN_TRADERS_TARGET = 30
DISCOVERY_TOP_N = 10
DISCOVERY_SEMAPHORE_MAX = 5
ENRICH_CONCURRENCY = 10
