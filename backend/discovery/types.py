"""Typed data structures for the discovery pipeline.

Every trader passes through these stages:
  1. Raw API data → TraderProfile (field_status tracks what's verified vs missing)
  2. TraderProfile → ScoreResult (pure scoring function)
  3. ScoreResult → ranked output list
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TraderProfile:
    """A single trader's full profile after fetch + validation.

    All *raw_ fields hold the API's original value (or None if missing).
    `field_status` tracks what happened per field: 'verified', 'missing',
    or 'fallback'.  `norm_*` fields are computed in scoring.
    """
    username: str

    # ── Raw API values (may be None) ──────────────────────────────
    raw_return_12m: Optional[float] = None
    raw_return_6m: Optional[float] = None
    raw_return_3yr: Optional[float] = None
    raw_return_ytd: Optional[float] = None
    raw_risk_score: Optional[float] = None
    raw_drawdown: Optional[float] = None
    raw_volatility: Optional[float] = None
    raw_copiers: Optional[int] = None
    raw_positions_count: Optional[int] = None
    raw_consistency_score: Optional[float] = None
    raw_sharpe: Optional[float] = None
    raw_min_copy_amount: Optional[float] = None
    raw_total_return_pct: Optional[float] = None
    raw_avg_monthly_return: Optional[float] = None
    raw_is_copyable: bool = True

    # ── Source / confidence ───────────────────────────────────────
    source: str = "unknown"
    confidence: float = 0.0

    # ── Field status ──────────────────────────────────────────────
    field_status: Dict[str, str] = field(default_factory=dict)

    # ── Holdings / extended ───────────────────────────────────────
    holdings: List[str] = field(default_factory=list)
    assets_under_copy: Optional[float] = None
    track_record_days: Optional[int] = None

    # ── Normalised / computed (filled by scoring) ─────────────────
    norm_return_12m: float = 0.0
    norm_return_6m: float = 0.0
    norm_risk: float = 0.0
    norm_drawdown: float = 0.0
    norm_consistency: float = 0.0

    copier_bonus: float = 0.0
    maturity_bonus: float = 0.0

    score: float = 0.0
    final_score: float = 0.0
    confidence_modifier: float = 0.0
    confidence_score: float = 0.0

    missing_fields: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    explanation: List[str] = field(default_factory=list)
    growth_filter: bool = False

    @property
    def verified_fields(self) -> int:
        return sum(1 for s in self.field_status.values() if s == "verified")

    @property
    def total_fields(self) -> int:
        return len(self.field_status) if self.field_status else 0


@dataclass
class ScoreResult:
    """Result of scoring a single trader."""
    username: str
    score: float
    final_score: float
    confidence_score: float
    confidence_modifier: float
    source: str
    source_valid: bool
    source_reason: Optional[str]
    explanation: List[str]
    details: Dict
    penalties: List[str]
    growth_filter: bool
    missing_fields: List[str]
    delta: float = 0.0


@dataclass
class DiscoveryStats:
    """Aggregate statistics from a discovery run."""
    total_scanned: int = 0
    eligible: int = 0
    excluded: int = 0
    active_traders: int = 0
    candidate_pool_size: int = 0
    category: str = "all"
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class DiscoveryResult:
    """Full result of a discovery pipeline run."""
    eligible_scored: List[Dict]
    excluded: List[Dict]
    stats: DiscoveryStats


# ── Excluded-item types ──────────────────────────────────────────────

EXCLUDED_ALREADY_COPIED = "already_copied"
EXCLUDED_SELF = "self"
EXCLUDED_MIN_COPY_TOO_HIGH = "min_copy_too_high"
EXCLUDED_NO_DATA = "no_data"
EXCLUDED_LOW_CONFIDENCE = "low_confidence"
EXCLUDED_FAKE_NAME = "fake_name"
EXCLUDED_DISQUALIFIED = "disqualified"
EXCLUDED_GROWTH_FILTER = "growth_filter"
