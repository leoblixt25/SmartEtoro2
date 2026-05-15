"""
Scoring Engine — backward-compatible wrapper around discovery/score.

All core logic has moved to backend/discovery/score.py (typed, testable).
This module keeps the same function signatures so callers don't break.
Also provides backward-compat versions of private functions that
tests import directly.
"""

import logging
from typing import Dict, List, Optional
from backend.discovery.score import (
    calculate_growth_score as _calc_growth_score,
    rank_candidates as _rank_candidates,
    scout_holdings as _scout_holdings,
    rank_combined as _rank_combined,
    generate_scout_report as _gen_scout_report,
    _compute_confidence_score,
    _has_return_data as _has_ret_data,
)
from backend.discovery.validate import (
    validate_data_source,
    apply_constraints as _apply_constraints_list,
    build_trader_profile,
)
from backend.discovery.types import TraderProfile, ScoreResult
from backend.discovery.config import (
    W_12M, W_6M, W_RISK, W_MAX_DRAWDOWN, W_CONSISTENCY,
    PENALTY_RISK_HIGH, PENALTY_DRAWDOWN_HIGH,
    GROWTH_FILTER_MIN_12M,
    MIN_CONFIDENCE_TO_SCORE,
    CONSTRAINT_MAX_DRAWDOWN,
    CONSTRAINT_MIN_TRACK_RECORD_DAYS,
)

logger = logging.getLogger(__name__)


# ── Backward-compat private functions (used by tests) ────────────────


def _compute_confidence(trader: dict) -> float:
    """Backward-compat: compute confidence from raw dict."""
    profile = build_trader_profile(trader)
    return _compute_confidence_score(profile)


def _has_return_data(trader: dict) -> bool:
    """Backward-compat: check return data from raw dict."""
    profile = build_trader_profile(trader)
    return _has_ret_data(profile)


# ── Main scoring functions (pure delegation) ─────────────────────────


def calculate_growth_score(trader: dict) -> dict:
    """Backward-compat: score a single trader from a raw dict."""
    return _calc_growth_score(trader)


def rank_candidates(holdings: list[dict], candidates: list[dict], top_n: int = 10) -> list[dict]:
    return _rank_candidates(holdings, candidates, top_n=top_n)


def scout_holdings(holdings: list[dict]) -> dict:
    return _scout_holdings(holdings)


def rank_combined(holdings: list[dict], candidates: list[dict], top_n: int = 3) -> list[dict]:
    return _rank_combined(holdings, candidates, top_n=top_n)


def generate_scout_report(holdings: list[dict], candidates: list[dict]) -> dict:
    return _gen_scout_report(holdings, candidates)


def apply_constraints(candidates: list[dict]) -> list[dict]:
    """Backward-compat: filter candidates by hard constraints."""
    return _apply_constraints_list(candidates)


# Re-export constants
W_12M = W_12M
W_6M = W_6M
W_RISK = W_RISK
W_MAX_DRAWDOWN = W_MAX_DRAWDOWN
W_CONSISTENCY = W_CONSISTENCY
PENALTY_RISK_HIGH = PENALTY_RISK_HIGH
PENALTY_DRAWDOWN_HIGH = PENALTY_DRAWDOWN_HIGH
GROWTH_FILTER_MIN_12M = GROWTH_FILTER_MIN_12M
MIN_CONFIDENCE_TO_SCORE = MIN_CONFIDENCE_TO_SCORE
CONSTRAINT_MAX_DRAWDOWN = CONSTRAINT_MAX_DRAWDOWN
CONSTRAINT_MIN_TRACK_RECORD_DAYS = CONSTRAINT_MIN_TRACK_RECORD_DAYS


__all__ = [
    "calculate_growth_score",
    "rank_candidates",
    "scout_holdings",
    "rank_combined",
    "generate_scout_report",
    "validate_data_source",
    "apply_constraints",
    "_compute_confidence",
    "_has_return_data",
    "TraderProfile",
    "ScoreResult",
]
