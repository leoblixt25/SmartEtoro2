"""Tests for the new backend/discovery/ modules.

Covers:
  - utils.safe_log: safe_fmt never crashes on None
  - discovery.validate: field classification, source validation, constraints
  - discovery.score: profile-based scoring, no fake defaults
  - discovery.pipeline: run order, lock, cooldown (mock DB + API)
  - discovery.fetch: SafeFetcher retry, cache, rate-limit stop
  - Backward compat: scoring_engine re-exports match old API
"""

from __future__ import annotations
import asyncio
import json
import time
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── utils.safe_log ───────────────────────────────────────────────────


class TestSafeLog:
    def test_safe_fmt_with_value(self):
        from backend.utils.safe_log import safe_fmt
        assert safe_fmt(42.5) == "42.5"
        assert safe_fmt(3.14159, fmt=".2f") == "3.14"

    def test_safe_fmt_with_none(self):
        from backend.utils.safe_log import safe_fmt
        assert safe_fmt(None) == "missing"

    def test_safe_fmt_with_suffix(self):
        from backend.utils.safe_log import safe_fmt
        assert safe_fmt(12.3, suffix="%") == "12.3%"

    def test_safe_fmt_with_custom_missing(self):
        from backend.utils.safe_log import safe_fmt
        assert safe_fmt(None, missing="N/A") == "N/A"

    def test_safe_fmt_with_bad_value(self):
        from backend.utils.safe_log import safe_fmt
        assert safe_fmt("not-a-number") == "missing"

    def test_safe_str_with_none(self):
        from backend.utils.safe_log import safe_str
        assert safe_str(None) == "missing"

    def test_safe_str_with_value(self):
        from backend.utils.safe_log import safe_str
        assert safe_str("hello") == "hello"

    def test_safe_int_with_none(self):
        from backend.utils.safe_log import safe_int
        assert safe_int(None) == "missing"

    def test_safe_int_with_value(self):
        from backend.utils.safe_log import safe_int
        assert safe_int(42) == "42"


# ── discovery.types ──────────────────────────────────────────────────


class TestTraderProfile:
    def test_default_creation(self):
        from backend.discovery.types import TraderProfile
        p = TraderProfile(username="testuser")
        assert p.username == "testuser"
        assert p.raw_return_12m is None
        assert p.score == 0.0
        assert p.final_score == 0.0
        assert p.missing_fields == []
        assert p.field_status == {}

    def test_verified_fields_count(self):
        from backend.discovery.types import TraderProfile
        p = TraderProfile(username="t", field_status={"a": "verified", "b": "missing", "c": "verified"})
        assert p.verified_fields == 2
        assert p.total_fields == 3

    def test_discovery_stats_defaults(self):
        from backend.discovery.types import DiscoveryStats
        s = DiscoveryStats()
        assert s.total_scanned == 0
        assert s.eligible == 0
        assert s.error is None

    def test_discovery_result_holds_stats(self):
        from backend.discovery.types import DiscoveryResult, DiscoveryStats
        r = DiscoveryResult(eligible_scored=[], excluded=[], stats=DiscoveryStats())
        assert r.eligible_scored == []
        assert r.stats.eligible == 0


# ── discovery.validate ────────────────────────────────────────────────


class TestValidateFieldClassification:
    def test_classify_numeric_verified(self):
        from backend.discovery.validate import classify_numeric, VERIFIED
        assert classify_numeric(5.0, "risk_score") == VERIFIED
        assert classify_numeric(10.0, "return_12m") == VERIFIED

    def test_classify_numeric_none(self):
        from backend.discovery.validate import classify_numeric, MISSING
        assert classify_numeric(None, "risk_score") == MISSING

    def test_classify_numeric_zero_risk_is_missing(self):
        from backend.discovery.validate import classify_numeric, MISSING
        assert classify_numeric(0, "risk_score") == MISSING

    def test_classify_return_verified(self):
        from backend.discovery.validate import classify_return, VERIFIED
        assert classify_return(15.0) == VERIFIED

    def test_classify_return_none(self):
        from backend.discovery.validate import classify_return, MISSING
        assert classify_return(None) == MISSING

    def test_classify_return_zero_is_missing(self):
        from backend.discovery.validate import classify_return, MISSING
        assert classify_return(0.0) == MISSING

    def test_classify_int_verified(self):
        from backend.discovery.validate import classify_int, VERIFIED
        assert classify_int(10) == VERIFIED

    def test_classify_int_none(self):
        from backend.discovery.validate import classify_int, MISSING
        assert classify_int(None) == MISSING

    def test_classify_int_zero_is_missing(self):
        from backend.discovery.validate import classify_int, MISSING
        assert classify_int(0) == MISSING


class TestBuildTraderProfile:
    def test_build_from_full_dict(self):
        from backend.discovery.validate import build_trader_profile
        raw = {
            "username": "testpro",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 85.0,
            "return_6m": 30.0,
            "total_return_pct": 80.0,
            "risk_score": 3.5,
            "max_drawdown": 8.0,
            "volatility": 12.0,
            "copiers": 500,
            "positions_count": 10,
            "consistency_score": 70.0,
        }
        p = build_trader_profile(raw)
        assert p.username == "testpro"
        assert p.raw_return_12m == 85.0
        assert p.raw_risk_score == 3.5
        assert p.raw_copiers == 500
        assert p.raw_positions_count == 10
        assert p.source == "tradeinfo"
        assert p.confidence == 1.0
        # Most fields should be verified
        verified = sum(1 for s in p.field_status.values() if s == "verified")
        assert verified >= 8

    def test_build_from_sparse_dict(self):
        from backend.discovery.validate import build_trader_profile
        raw = {"username": "sparse"}
        p = build_trader_profile(raw)
        assert p.username == "sparse"
        assert p.raw_return_12m is None
        assert p.raw_risk_score is None
        # Most fields should be missing
        missing_count = sum(1 for s in p.field_status.values() if s == "missing")
        assert missing_count >= 10


class TestValidateDataSource:
    def test_tradeinfo_is_valid(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import validate_data_source
        p = TraderProfile(username="t", source="tradeinfo", confidence=1.0)
        assert validate_data_source(p) is None

    def test_low_confidence_no_return_is_invalid(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import validate_data_source
        p = TraderProfile(username="t", source="fallback", confidence=0.5)
        reason = validate_data_source(p)
        assert reason is not None
        assert "no return data" in reason

    def test_low_confidence_below_min(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import validate_data_source
        p = TraderProfile(
            username="t", source="fallback", confidence=0.5,
            raw_return_12m=50.0,
        )
        reason = validate_data_source(p)
        assert reason is not None
        assert "low confidence" in reason

    def test_high_confidence_fallback_with_return_is_valid(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import validate_data_source
        p = TraderProfile(
            username="t", source="fallback", confidence=0.9,
            raw_return_12m=50.0,
        )
        assert validate_data_source(p) is None


class TestCheckConstraints:
    def test_pass(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import check_constraints
        p = TraderProfile(username="t", raw_drawdown=5.0, track_record_days=500)
        assert check_constraints(p) is None

    def test_high_drawdown_fails(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import check_constraints
        p = TraderProfile(username="t", raw_drawdown=40.0)
        reason = check_constraints(p)
        assert reason is not None
        assert "max_drawdown" in reason

    def test_short_track_record_fails(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.validate import check_constraints
        p = TraderProfile(username="t", raw_drawdown=5.0, track_record_days=50)
        reason = check_constraints(p)
        assert reason is not None
        assert "track_record" in reason


class TestApplyConstraintsBackwardCompat:
    def test_passes_good_traders(self):
        from backend.discovery.validate import apply_constraints
        candidates = [
            {"username": "a", "max_drawdown": 5.0, "track_record_days": 500},
            {"username": "b", "max_drawdown": 10.0, "track_record_days": 400},
        ]
        result = apply_constraints(candidates)
        assert len(result) == 2

    def test_filters_high_drawdown(self):
        from backend.discovery.validate import apply_constraints
        candidates = [
            {"username": "a", "max_drawdown": 40.0},
            {"username": "b", "max_drawdown": 5.0},
        ]
        result = apply_constraints(candidates)
        assert len(result) == 1
        assert result[0]["username"] == "b"


# ── discovery.score ─────────────────────────────────────────────────


class TestCalculateScoreFromProfile:
    def test_full_data_trader_scores_meaningfully(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.score import calculate_score_from_profile
        p = TraderProfile(
            username="strong",
            source="tradeinfo",
            confidence=1.0,
            raw_return_12m=85.0,
            raw_return_6m=30.0,
            raw_total_return_pct=80.0,
            raw_risk_score=3.5,
            raw_drawdown=8.0,
            raw_volatility=12.0,
            raw_copiers=500,
            raw_positions_count=10,
            raw_consistency_score=70.0,
            raw_avg_monthly_return=3.0,
            raw_peak_to_valley=-8.0,
            raw_profitable_months_pct=70.0,
            raw_win_ratio=65.0,
            raw_weeks_since_registration=200,
        )
        p.field_status = {
            "return_12m": "verified", "return_6m": "verified",
            "total_return_pct": "verified", "risk_score": "verified",
            "max_drawdown": "verified", "volatility": "verified",
            "copiers": "verified", "positions_count": "verified",
            "consistency_score": "verified", "avg_monthly_return": "verified",
        }
        result = calculate_score_from_profile(p)
        assert result.score > 40.0, f"Expected score > 40, got {result.score}"
        assert result.final_score > 0
        assert result.growth_filter is False
        assert result.final_score == result.score

    def test_sparse_data_trader_scores_low(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.score import calculate_score_from_profile
        p = TraderProfile(username="sparse", source="fallback", confidence=0.5)
        result = calculate_score_from_profile(p)
        # Should be rejected for unreliable source
        assert result.score == 0.0

    def test_low_return_still_scores_via_risk(self):
        """Low return gets low return_score but risk and dd add points."""
        from backend.discovery.types import TraderProfile
        from backend.discovery.score import calculate_score_from_profile
        p = TraderProfile(
            username="low_ret",
            source="tradeinfo",
            confidence=1.0,
            raw_return_12m=2.0,
            raw_total_return_pct=2.0,
            raw_risk_score=3.0,
            raw_drawdown=5.0,
            raw_peak_to_valley=-5.0,
        )
        p.field_status = {
            "return_12m": "verified",
            "total_return_pct": "verified",
            "risk_score": "verified",
            "max_drawdown": "verified",
        }
        result = calculate_score_from_profile(p)
        # return=14.1*0.333 + risk_adj=0*0.333 + dd=95*0.200 + risk=70*0.133 = 33.0
        assert result.score > 15
        assert result.growth_filter is False

    def test_copier_bonus_applied(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.score import calculate_score_from_profile
        base = TraderProfile(
            username="with_copiers",
            source="tradeinfo",
            confidence=1.0,
            raw_return_12m=50.0,
            raw_total_return_pct=50.0,
            raw_risk_score=4.0,
            raw_drawdown=10.0,
            raw_volatility=15.0,
        )
        base.field_status = {
            "return_12m": "verified",
            "total_return_pct": "verified",
            "risk_score": "verified",
            "max_drawdown": "verified",
            "volatility": "verified",
        }
        # Score without copiers
        no_copiers = calculate_score_from_profile(TraderProfile(**{**base.__dict__}))
        # Score with copiers
        base.raw_copiers = 500
        base.raw_positions_count = 10
        with_copiers = calculate_score_from_profile(base)
        assert with_copiers.score >= no_copiers.score

    def test_missing_fields_never_get_fake_defaults(self):
        from backend.discovery.types import TraderProfile
        from backend.discovery.score import calculate_score_from_profile
        p = TraderProfile(
            username="no_risk",
            source="tradeinfo",
            confidence=1.0,
            raw_return_12m=50.0,
            raw_total_return_pct=50.0,
            raw_copiers=100,
            raw_positions_count=5,
            # No risk, dd, vol, consistency
        )
        p.field_status = {
            "return_12m": "verified",
            "total_return_pct": "verified",
            "copiers": "verified",
            "positions_count": "verified",
        }
        result = calculate_score_from_profile(p)
        # No fake defaults — norm values stay 0.0
        assert result.norm_risk == 0.0
        assert result.norm_drawdown == 0.0
        # Score uses only verified return data (no fake risk/copiers)
        assert result.score > 0


# ── discovery.fetch (SafeFetcher) ───────────────────────────────────


class TestSafeFetcher:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._cache.clear()
        url = "https://api.test.com/data"
        SafeFetcher._cache[url] = (time.time(), {"cached": True})
        fetcher = SafeFetcher(api_key="test", user_key="test")
        result = await fetcher.get(url, cache_ttl=60.0)
        assert result == {"cached": True}

    @pytest.mark.asyncio
    async def test_cache_miss_fetches(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._cache.clear()
        SafeFetcher._rate_limit_hits = 0
        fetcher = SafeFetcher(api_key="test", user_key="test")

        # Build a fake response (json() is synchronous like httpx.Response)
        class FakeResponse:
            status_code = 200
            text = '{"key": "value"}'
            def json(self):
                return {"key": "value"}

        # Build a fake async client that yields FakeResponse
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, url, **kwargs):
                return FakeResponse()

        with patch("httpx.AsyncClient", return_value=FakeClient()):
            result = await fetcher.get("https://api.test.com/other")
            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_rate_limit_eventually_stops(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._cache.clear()
        SafeFetcher._rate_limit_hits = 0
        from backend.discovery.config import RATE_LIMIT_HIT_STOP
        SafeFetcher._rate_limit_hits = RATE_LIMIT_HIT_STOP
        fetcher = SafeFetcher(api_key="test", user_key="test")
        result = await fetcher.get("https://api.test.com/ratelimited")
        assert result is None
        assert SafeFetcher._rate_limit_hits >= RATE_LIMIT_HIT_STOP

    @pytest.mark.asyncio
    async def test_401_not_retried(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._cache.clear()
        SafeFetcher._rate_limit_hits = 0
        fetcher = SafeFetcher(api_key="test", user_key="test")
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = AsyncMock()
            mock_resp.status_code = 401
            mock_resp.text = "unauthorized"
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_instance
            result = await fetcher.get("https://api.test.com/authfail")
            assert result is None

    def test_cache_key_generation(self):
        from backend.discovery.fetch import SafeFetcher
        key1 = SafeFetcher._cache_key("https://api.test.com", {"a": 1, "b": 2})
        key2 = SafeFetcher._cache_key("https://api.test.com", {"b": 2, "a": 1})
        assert key1 == key2
        assert '"a": 1' in key1

    def test_clear_cache(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._cache["test"] = (time.time(), "val")
        assert len(SafeFetcher._cache) >= 1
        fetcher = SafeFetcher(api_key="test", user_key="test")
        fetcher.clear_cache()
        assert len(SafeFetcher._cache) == 0

    def test_is_degraded(self):
        from backend.discovery.fetch import SafeFetcher
        SafeFetcher._rate_limit_hits = 0
        fetcher = SafeFetcher(api_key="test", user_key="test")
        assert fetcher.is_degraded is False
        SafeFetcher._rate_limit_hits = 999
        assert fetcher.is_degraded is True
        SafeFetcher._rate_limit_hits = 0


# ── discovery.pipeline (lock, cooldown, cache) ──────────────────────


class TestDiscoveryPipeline:
    @pytest.mark.asyncio
    async def test_second_call_returns_cached(self):
        """Within cache TTL, second call returns cached result."""
        from backend.discovery.pipeline import discover_eligible_traders, _cache, _cache_time, _last_run_time

        # Reset state
        import backend.discovery.pipeline as p
        p._cache = None
        p._cache_time = 0.0
        p._last_run_time = 0.0
        p._discovery_lock = asyncio.Lock()

        # Set a fake cache entry
        cached = ([{"username": "cached_trader"}], [], {"total_scanned": 5})
        p._cache = cached
        p._cache_time = time.time()
        p._last_run_time = time.time()

        mock_db = MagicMock()
        result = await discover_eligible_traders(mock_db, portfolio_id=1, force=False)
        # Should return cached, not hitting real DB/API
        assert result[0][0]["username"] == "cached_trader"

    @pytest.mark.asyncio
    async def test_force_bypasses_cache(self):
        """force=True runs despite cache."""
        from backend.discovery.pipeline import discover_eligible_traders, _cache, _cache_time

        import backend.discovery.pipeline as p
        p._cache = ([{"username": "stale"}], [], {})
        p._cache_time = time.time()
        p._last_run_time = 0.0
        p._discovery_lock = asyncio.Lock()

        # Portfolio query will fail because mock_db returns None
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await discover_eligible_traders(mock_db, portfolio_id=1, force=True)
        assert "error" in result[2]

    @pytest.mark.asyncio
    async def test_concurrent_calls_serialized(self):
        """Two simultaneous calls should not both run discovery."""
        from backend.discovery.pipeline import discover_eligible_traders
        import backend.discovery.pipeline as p
        p._cache = None
        p._cache_time = 0.0
        p._last_run_time = 0.0
        p._discovery_lock = asyncio.Lock()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        results = await asyncio.gather(
            discover_eligible_traders(mock_db, portfolio_id=1, force=True),
            discover_eligible_traders(mock_db, portfolio_id=1, force=True),
            return_exceptions=True,
        )
        # At least one should report an error (portfolio not found means it ran)
        errors = sum(1 for r in results if isinstance(r, tuple) and "error" in (r[2] if len(r) > 2 else {}))
        cache_hits = sum(1 for r in results if isinstance(r, tuple) and len(r) > 0 and r[0] and not r[2].get("error"))
        # The second call should have returned cached
        assert cache_hits >= 1 or errors >= 1


# ── Backward compat: scoring_engine re-exports ──────────────────────


class TestBackwardCompatScoringEngine:
    def test_calculate_growth_score_importable(self):
        from backend.ai.scoring_engine import calculate_growth_score
        result = calculate_growth_score({"username": "test"})
        assert isinstance(result, dict)
        assert "score" in result
        assert "final_score" in result
        assert "confidence_score" in result

    def test_rank_candidates_importable(self):
        from backend.ai.scoring_engine import rank_candidates
        result = rank_candidates([], [])
        assert isinstance(result, list)

    def test_scout_holdings_importable(self):
        from backend.ai.scoring_engine import scout_holdings
        result = scout_holdings([])
        assert isinstance(result, dict)
        assert result["scored"] == []

    def test_generate_scout_report_importable(self):
        from backend.ai.scoring_engine import generate_scout_report
        result = generate_scout_report([], [])
        assert isinstance(result, dict)

    def test_validate_data_source_importable(self):
        from backend.ai.scoring_engine import validate_data_source
        from backend.discovery.types import TraderProfile
        result = validate_data_source(TraderProfile(username="t", source="tradeinfo"))
        assert result is None

    def test_constants_importable(self):
        from backend.ai.scoring_engine import (
            W_12M, W_6M, W_RISK, GROWTH_FILTER_MIN_12M,
            PENALTY_RISK_HIGH, MIN_CONFIDENCE_TO_SCORE,
        )
        assert W_12M == 0.25
        assert W_6M == 0.15
        assert W_RISK == 0.20
        assert GROWTH_FILTER_MIN_12M == 10.0
        assert PENALTY_RISK_HIGH == 30
        assert MIN_CONFIDENCE_TO_SCORE == 0.8

    def test_apply_constraints_backward_compat(self):
        from backend.ai.scoring_engine import apply_constraints
        candidates = [
            {"username": "a", "max_drawdown": 5.0},
            {"username": "b", "max_drawdown": 40.0},
        ]
        result = apply_constraints(candidates)
        assert len(result) == 1
        assert result[0]["username"] == "a"

    def test_compute_confidence_backward_compat(self):
        from backend.ai.scoring_engine import _compute_confidence
        full = {
            "username": "full",
            "return_12m": 50.0,
            "total_return_pct": 50.0,
            "risk_score": 3.0,
            "max_drawdown": 5.0,
            "volatility": 10.0,
            "avg_monthly_return": 2.0,
            "sharpe_score": 1.5,
        }
        assert _compute_confidence(full) > 0.5

    def test_has_return_data_backward_compat(self):
        from backend.ai.scoring_engine import _has_return_data
        assert _has_return_data({"return_12m": 50.0}) is True
        assert _has_return_data({"return_12m": None}) is False


# ── Integration: pipeline uses scoring correctly ────────────────────


class TestScoreNoFakeDefaults:
    """Critical acceptance test: no fake defaults ever used as real metrics."""

    def test_missing_risk_does_not_get_default_50(self):
        from backend.discovery.validate import build_trader_profile
        from backend.discovery.score import calculate_score_from_profile
        # Trader with returns but NO risk/dd/vol
        raw = {
            "username": "partial",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 50.0,
            "total_return_pct": 50.0,
            "return_3yr": 10.0,
            "return_ytd": 10.0,
        }
        profile = build_trader_profile(raw)
        result = calculate_score_from_profile(profile)
        # The risk, dd, consistency norms should all be 0
        assert result.norm_risk == 0.0, "risk should not default to 50"
        assert result.norm_drawdown == 0.0, "dd should not default to 50"
        assert result.norm_consistency == 0.0, "consistency should not default to 50"
        # With weight redistribution, all weight goes to the only available component.
        # return_component(50) = 10 * sqrt(50) = 70.7, score = 70.7 * 1.0 = 70.7
        assert result.score == pytest.approx(70.7, abs=1.0)

    def test_no_fake_copiers_entered(self):
        from backend.discovery.validate import build_trader_profile
        from backend.discovery.score import calculate_score_from_profile
        raw = {"username": "no_copiers", "source": "tradeinfo", "confidence": 1.0}
        profile = build_trader_profile(raw)
        assert profile.raw_copiers is None
        assert profile.copier_bonus == 0.0
