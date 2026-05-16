"""Validation layer — classify each field as verified, missing, or fallback.

Never pretends missing data is real.  Every field gets a status that
propagates through to scoring and output.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional
from backend.discovery.types import TraderProfile
from backend.discovery.config import (
    MIN_CONFIDENCE_TO_SCORE,
    CONSTRAINT_MAX_DRAWDOWN, CONSTRAINT_MAX_RISK,
    CONSTRAINT_MIN_TRACK_RECORD_DAYS, CONSTRAINT_MIN_WEEKS,
    CONSTRAINT_MIN_CONSISTENCY,
)

logger = logging.getLogger(__name__)

# ── Field status constants ───────────────────────────────────────────

VERIFIED = "verified"
MISSING = "missing"
FALLBACK = "fallback"
FAILED = "failed"


def classify_numeric(value, field_name: str) -> str:
    """Classify a single numeric field.

    Returns:
        'verified' — value is not None, not zero (for metrics where 0 = no data)
        'missing'  — value is None or zero (for metrics where 0 = no data)
    """
    if value is None:
        return MISSING
    v = float(value)
    # risk_score=0 means the API didn't return data
    if v == 0 and field_name in ("risk_score", "riskScore"):
        return MISSING
    if v == 0 and field_name in ("volatility",):
        return MISSING
    if v == 0 and field_name in ("sharpe_score", "sharpe"):
        return MISSING
    return VERIFIED


def classify_return(value) -> str:
    """Classify a return value — 0 means no data."""
    if value is None:
        return MISSING
    try:
        return VERIFIED if float(value) != 0 else MISSING
    except (ValueError, TypeError):
        return MISSING


def classify_int(value) -> str:
    """Classify an integer value — None or 0 means missing."""
    if value is None:
        return MISSING
    try:
        return VERIFIED if int(value) > 0 else MISSING
    except (ValueError, TypeError):
        return MISSING


def build_trader_profile(raw: dict) -> TraderProfile:
    """Build a TraderProfile from a raw API dict, classifying every field."""
    fs: Dict[str, str] = {}

    username = raw.get("username", "?")

    # ── Source / confidence ───────────────────────────────────────
    source = raw.get("source", "unknown")
    confidence = float(raw.get("confidence", 0.0) or 0.0)

    # ── Returns ───────────────────────────────────────────────────
    raw_12m = raw.get("return_12m")
    fs["return_12m"] = classify_return(raw_12m)

    raw_6m = raw.get("return_6m")
    fs["return_6m"] = classify_return(raw_6m)

    raw_3yr = raw.get("return_3yr")
    fs["return_3yr"] = classify_return(raw_3yr)

    raw_ytd = raw.get("return_ytd")
    fs["return_ytd"] = classify_return(raw_ytd)

    raw_tr = raw.get("total_return_pct")
    fs["total_return_pct"] = classify_return(raw_tr)

    raw_avg = raw.get("avg_monthly_return")
    fs["avg_monthly_return"] = classify_return(raw_avg)

    # ── Risk / stability ──────────────────────────────────────────
    raw_risk = raw.get("risk_score")
    fs["risk_score"] = classify_numeric(raw_risk, "risk_score")

    raw_dd = raw.get("max_drawdown")
    fs["max_drawdown"] = VERIFIED if raw_dd is not None else MISSING

    raw_vol = raw.get("volatility")
    fs["volatility"] = classify_numeric(raw_vol, "volatility")

    raw_sharpe = raw.get("sharpe_score")
    fs["sharpe_score"] = classify_numeric(raw_sharpe, "sharpe")

    raw_cons = raw.get("consistency_score")
    fs["consistency_score"] = classify_return(raw_cons)

    # ── Popularity / activity ─────────────────────────────────────
    raw_copiers = raw.get("copiers")
    fs["copiers"] = classify_int(raw_copiers)

    raw_positions = raw.get("positions_count")
    fs["positions_count"] = classify_int(raw_positions)

    # ── Professional analysis fields ──────────────────────────────
    raw_peak = raw.get("peak_to_valley")
    fs["peak_to_valley"] = VERIFIED if raw_peak is not None else MISSING

    raw_prof_months = raw.get("profitable_months_pct")
    fs["profitable_months_pct"] = classify_return(raw_prof_months)

    raw_win = raw.get("win_ratio")
    fs["win_ratio"] = classify_return(raw_win)

    raw_trades = raw.get("trades_count")
    fs["trades_count"] = classify_int(raw_trades)

    raw_weeks = raw.get("weeks_since_registration")
    fs["weeks_since_registration"] = classify_int(raw_weeks)

    # ── Copy info ─────────────────────────────────────────────────
    min_copy = raw.get("min_copy_amount")
    fs["min_copy_amount"] = VERIFIED if min_copy is not None else MISSING

    is_copyable = raw.get("is_copyable", True)

    # ── Missing fields list ───────────────────────────────────────
    missing = [k for k, v in fs.items() if v == MISSING]

    profile = TraderProfile(
        username=username,
        raw_return_12m=float(raw_12m) if raw_12m is not None else None,
        raw_return_6m=float(raw_6m) if raw_6m is not None else None,
        raw_return_3yr=float(raw_3yr) if raw_3yr is not None else None,
        raw_return_ytd=float(raw_ytd) if raw_ytd is not None else None,
        raw_risk_score=float(raw_risk) if raw_risk is not None and raw_risk != 0 else None,
        raw_drawdown=float(raw_dd) if raw_dd is not None else None,
        raw_volatility=float(raw_vol) if raw_vol is not None and raw_vol != 0 else None,
        raw_copiers=int(raw_copiers) if raw_copiers is not None else None,
        raw_positions_count=int(raw_positions) if raw_positions is not None else None,
        raw_consistency_score=float(raw_cons) if raw_cons is not None else None,
        raw_sharpe=float(raw_sharpe) if raw_sharpe is not None and raw_sharpe != 0 else None,
        raw_min_copy_amount=float(min_copy) if min_copy is not None else None,
        raw_total_return_pct=float(raw_tr) if raw_tr is not None else None,
        raw_avg_monthly_return=float(raw_avg) if raw_avg is not None and raw_avg != 0 else None,
        raw_is_copyable=bool(is_copyable),
        raw_peak_to_valley=float(raw_peak) if raw_peak is not None else None,
        raw_profitable_months_pct=float(raw_prof_months) if raw_prof_months is not None else None,
        raw_win_ratio=float(raw_win) if raw_win is not None else None,
        raw_trades_count=int(raw_trades) if raw_trades is not None else None,
        raw_weeks_since_registration=int(raw_weeks) if raw_weeks is not None else None,
        source=source,
        confidence=confidence,
        field_status=fs,
        missing_fields=missing,
        holdings=raw.get("holdings", []),
        assets_under_copy=raw.get("assets_under_copy"),
        track_record_days=raw.get("track_record_days"),
    )
    logger.debug(
        "Validation %s: %d fields (%d verified, %d missing)",
        username,
        len(fs), sum(1 for v in fs.values() if v == VERIFIED),
        len(missing),
    )
    return profile


def validate_data_source(profile: TraderProfile) -> Optional[str]:
    """Validate that the trader's data comes from a reliable source.

    Returns None if valid, or a string reason if unreliable.
    """
    if profile.source == "tradeinfo" or profile.confidence >= 1.0:
        return None

    has_return = (
        profile.raw_return_12m is not None or
        profile.raw_total_return_pct is not None
    )
    if not has_return and profile.confidence < 1.0:
        return f"no return data from {profile.source} (confidence={profile.confidence})"

    if profile.confidence < MIN_CONFIDENCE_TO_SCORE:
        return f"low confidence {profile.confidence} from {profile.source} (min {MIN_CONFIDENCE_TO_SCORE})"

    return None


def check_constraints(profile: TraderProfile) -> Optional[str]:
    """Hard-constraint checks on a single profile. Returns rejection reason or None.

    Quality filters (from professional copy-trading standards):
    - Drawdown > 35%: unacceptable risk of ruin
    - Risk score > 7: too aggressive for copy trading
    - Track record < 90d or weeks < 13: too new, insufficient data
    - Profitable months < 40%: inconsistent, unreliable
    """
    reasons = []

    if profile.raw_drawdown is not None and abs(float(profile.raw_drawdown)) > CONSTRAINT_MAX_DRAWDOWN:
        reasons.append(f"max_drawdown {abs(float(profile.raw_drawdown)):.1f}% > {CONSTRAINT_MAX_DRAWDOWN}%")

    if profile.raw_risk_score is not None and profile.raw_risk_score > CONSTRAINT_MAX_RISK:
        reasons.append(f"risk_score {profile.raw_risk_score:.0f} > {CONSTRAINT_MAX_RISK}")

    if profile.track_record_days is not None and profile.track_record_days > 0:
        if profile.track_record_days < CONSTRAINT_MIN_TRACK_RECORD_DAYS:
            reasons.append(f"track_record {profile.track_record_days}d < {CONSTRAINT_MIN_TRACK_RECORD_DAYS}d")

    if profile.raw_weeks_since_registration is not None and profile.raw_weeks_since_registration > 0:
        if profile.raw_weeks_since_registration < CONSTRAINT_MIN_WEEKS:
            reasons.append(f"active only {profile.raw_weeks_since_registration}w < {CONSTRAINT_MIN_WEEKS}w")

    if profile.raw_profitable_months_pct is not None:
        if profile.raw_profitable_months_pct < CONSTRAINT_MIN_CONSISTENCY:
            reasons.append(f"profitable_months {profile.raw_profitable_months_pct:.0f}% < {CONSTRAINT_MIN_CONSISTENCY}%")

    return "; ".join(reasons) if reasons else None


def apply_constraints(candidates: list[dict]) -> list[dict]:
    """Backward-compatible list-based constraint filter.

    Args:
        candidates: List of raw trader dicts.

    Returns:
        Filtered list with disqualified traders removed.
    """
    import logging
    logger = logging.getLogger(__name__)
    qualified = []
    for c in candidates:
        dd = c.get("max_drawdown")
        risk = c.get("risk_score")
        tr_days = c.get("track_record_days")
        weeks = c.get("weeks_since_registration")
        prof_months = c.get("profitable_months_pct")
        reasons = []
        if dd is not None and float(dd) > CONSTRAINT_MAX_DRAWDOWN:
            reasons.append(f"max_drawdown {float(dd):.1f}% > {CONSTRAINT_MAX_DRAWDOWN}%")
        if risk is not None and float(risk) > CONSTRAINT_MAX_RISK:
            reasons.append(f"risk_score {float(risk):.0f} > {CONSTRAINT_MAX_RISK}")
        if tr_days is not None and int(tr_days) > 0 and int(tr_days) < CONSTRAINT_MIN_TRACK_RECORD_DAYS:
            reasons.append(f"track_record {int(tr_days)}d < {CONSTRAINT_MIN_TRACK_RECORD_DAYS}d")
        if weeks is not None and int(weeks) > 0 and int(weeks) < CONSTRAINT_MIN_WEEKS:
            reasons.append(f"active only {int(weeks)}w < {CONSTRAINT_MIN_WEEKS}w")
        if prof_months is not None and float(prof_months) < CONSTRAINT_MIN_CONSISTENCY:
            reasons.append(f"profitable_months {float(prof_months):.0f}% < {CONSTRAINT_MIN_CONSISTENCY}%")
        if reasons:
            logger.info("Disqualified %s: %s", c.get("username", "?"), "; ".join(reasons))
            continue
        qualified.append(c)
    return qualified
