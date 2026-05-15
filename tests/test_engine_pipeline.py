"""
Tests for scoring engine, automation engine state, and market data discovery.
Covers confidence scoring, recovery mode, cooldown bypass, and fallback logic.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# ── Scoring Engine Tests ────────────────────────────────────────────


class TestComputeConfidence:
    """_compute_confidence measures data completeness."""

    def test_complete_data_returns_1_0(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {
            "return_12m": 18.5,
            "total_return_pct": 18.5,
            "risk_score": 4.0,
            "max_drawdown": 8.0,
            "volatility": 15.0,
            "avg_monthly_return": 1.5,
            "sharpe_score": 1.8,
        }
        assert _compute_confidence(trader) == 1.0

    def test_minimal_data_returns_0_3(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {}
        assert _compute_confidence(trader) == 0.3

    def test_partial_data_scales_correctly(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {
            "return_12m": 18.5,
            "risk_score": 4.0,
        }
        score = _compute_confidence(trader)
        # 2 of 7 checks pass: ratio = 2/7 ≈ 0.286 → 0.3 + 0.286*0.7 ≈ 0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_default_risk_score_does_not_count(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {
            "risk_score": None,  # None = missing from API — should not count
        }
        assert _compute_confidence(trader) == 0.3

    def test_zero_values_do_not_count(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {
            "return_12m": 0.0,
            "total_return_pct": 0.0,
            "risk_score": None,
        }
        assert _compute_confidence(trader) == 0.3


class TestHasReturnData:
    """_has_return_data detects actual vs default return values."""

    def test_with_actual_data_returns_true(self):
        from backend.ai.scoring_engine import _has_return_data
        assert _has_return_data({"total_return_pct": 15.0}) is True
        assert _has_return_data({"return_12m": 12.0}) is True
        assert _has_return_data({"avg_monthly_return": 1.5}) is True

    def test_with_defaults_returns_false(self):
        from backend.ai.scoring_engine import _has_return_data
        assert _has_return_data({}) is False
        assert _has_return_data({"total_return_pct": 0.0}) is False
        assert _has_return_data({"return_12m": None}) is False


class TestCalculateGrowthScore:
    """calculate_growth_score handles missing data without hard-zero."""

    def test_missing_return_data_skips_growth_filter(self):
        """When no return data exists, don't apply hard-zero growth filter."""
        from backend.ai.scoring_engine import calculate_growth_score
        trader = {
            "username": "test_trader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "risk_score": None,  # No risk data from API
            "max_drawdown": None,  # No drawdown data from API
        }
        result = calculate_growth_score(trader)
        assert result["growth_filter"] is False
        assert result["confidence_score"] == 0.3
        assert result["score"] == 0  # No data to score — correctly zero

    def test_actual_low_return_triggers_growth_filter(self):
        """When data shows 12M return < 10%, score = 0."""
        from backend.ai.scoring_engine import calculate_growth_score
        trader = {
            "username": "low_return",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 3.0,
            "risk_score": 4.0,
            "max_drawdown": 5.0,
            "volatility": 10.0,
        }
        result = calculate_growth_score(trader)
        assert result["growth_filter"] is True
        assert result["score"] == 0.0

    def test_confidence_included_in_result(self):
        from backend.ai.scoring_engine import calculate_growth_score
        trader = {
            "username": "full_data",
            "return_12m": 20.0,
            "return_6m": 12.0,
            "total_return_pct": 20.0,
            "risk_score": 4.0,
            "max_drawdown": 8.0,
            "volatility": 15.0,
            "avg_monthly_return": 1.5,
            "sharpe_score": 1.8,
        }
        result = calculate_growth_score(trader)
        assert "confidence_score" in result
        assert result["confidence_score"] >= 0.9

    def test_good_data_returns_positive_score(self):
        from backend.ai.scoring_engine import calculate_growth_score
        trader = {
            "username": "good_trader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 22.0,
            "return_6m": 14.0,
            "total_return_pct": 22.0,
            "risk_score": 3.0,
            "max_drawdown": 5.0,
            "volatility": 12.0,
            "avg_monthly_return": 1.8,
            "sharpe_score": 2.0,
        }
        result = calculate_growth_score(trader)
        assert result["score"] > 40
        assert result["growth_filter"] is False
        assert result["confidence_score"] == 1.0


class TestScoutHoldings:
    """scout_holdings handles edge cases."""

    def test_empty_holdings(self):
        from backend.ai.scoring_engine import scout_holdings
        result = scout_holdings([])
        assert result["scored"] == []
        assert result["weakest"] is None
        assert result["top"] is None
        assert result["avg_score"] == 0.0

    def test_single_holding(self):
        from backend.ai.scoring_engine import scout_holdings
        h = [{"username": "a", "total_return_pct": 15.0, "risk_score": 4.0,
              "return_12m": 15.0, "max_drawdown": 5.0}]
        result = scout_holdings(h)
        assert len(result["scored"]) == 1
        assert result["weakest"]["username"] == "a"
        assert result["top"]["username"] == "a"


class TestRankCandidates:
    """rank_candidates handles constraint checks."""

    def test_apply_constraints_filters_high_drawdown(self):
        from backend.ai.scoring_engine import apply_constraints
        candidates = [
            {"username": "a", "max_drawdown": 5.0},
            {"username": "b", "max_drawdown": 20.0},
        ]
        result = apply_constraints(candidates)
        assert len(result) == 1
        assert result[0]["username"] == "a"


# ── Market Data Discovery Tests ──────────────────────────────────────


class TestDiscoverTopTraders:
    """discover_top_traders uses multi-source strategy with fallback."""

    @pytest.mark.asyncio
    async def test_enrich_candidates_returns_available(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.enabled = True
            traders_100 = [f"trader{i}" for i in range(100)]
            available = [{"username": f"trader{i}"} for i in range(100)]
            client.discover_social_top = AsyncMock(return_value=traders_100)
            client.enrich_candidates = AsyncMock(return_value={
                "available": available,
                "unavailable": [],
                "scanned": 100,
                "valid_count": 100,
                "rejected": 0,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) == 100
            assert result[0]["username"] == "trader0"

    @pytest.mark.asyncio
    async def test_empty_enrichment_returns_empty_list(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.enabled = True
            client.discover_social_top = AsyncMock(return_value=[])
            client.enrich_candidates = AsyncMock(return_value={
                "available": [],
                "unavailable": [
                    {"username": "bad1", "reason": "all_endpoints_failed"},
                    {"username": "bad2", "reason": "all_endpoints_failed"},
                ],
                "scanned": 2,
                "valid_count": 0,
                "rejected": 2,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.enabled = True
            client.discover_social_top = AsyncMock(side_effect=Exception("API down"))
            client.enrich_candidates = AsyncMock(return_value={
                "available": [],
                "unavailable": [{"username": "x", "reason": "error"}],
                "scanned": 45,
                "valid_count": 0,
                "rejected": 45,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) == 0


# ── Eligibility Engine Tests ────────────────────────────────────────


class TestFilterCandidates:
    """filter_candidates applies all pre-scoring checks via EligibilityEngine."""

    def test_eligible_trader_passes(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [{
            "username": "GoodTrader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "risk_score": 4.0,
            "total_return_pct": 15.0,
            "min_copy_amount": 200,
            "available": True,
            "copiers": 100,
            "positions_count": 10,
        }]
        eligible, excluded = filter_candidates(candidates, set(), 5000)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "GoodTrader"
        assert len(excluded) == 0

    def test_already_copied_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [{
            "username": "CopiedTrader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "risk_score": 4.0,
            "total_return_pct": 10.0,
            "available": True,
            "copiers": 100,
            "positions_count": 10,
        }]
        eligible, excluded = filter_candidates(candidates, {"copiedtrader"}, 5000)
        assert len(eligible) == 0
        assert "already_copied" in excluded[0]["exclusion_reasons"]

    def test_case_insensitive_matching(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Booker03", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 200, "total_return_pct": 15.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
            {"username": "OTHER", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 200, "total_return_pct": 15.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
        ]
        eligible, excluded = filter_candidates(candidates, {"booker03"}, 5000)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "OTHER"
        assert excluded[0]["username"] == "Booker03"

    def test_no_holdings_nothing_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "a", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 200, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
            {"username": "b", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 200, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), 5000)
        assert len(eligible) == 2
        assert len(excluded) == 0

    def test_min_copy_too_high_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "cheap", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 100, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
            {"username": "expensive", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 20000, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), 1500)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "cheap"
        assert len(excluded) == 1
        assert excluded[0]["username"] == "expensive"
        assert any("insufficient_capital" in r for r in excluded[0]["exclusion_reasons"])

    def test_all_affordable_none_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "a", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 100, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
            {"username": "b", "source": "tradeinfo", "confidence": 1.0, "min_copy_amount": 200, "total_return_pct": 10.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), 1000)
        assert len(eligible) == 2
        assert len(excluded) == 0

    def test_missing_min_copy_accepted(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [{"username": "no_min_field", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "total_return_pct": 15.0}]
        eligible, excluded = filter_candidates(candidates, set(), 150)
        assert len(eligible) == 1

    def test_risk_too_high_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [{
            "username": "Risky",
            "source": "tradeinfo",
            "confidence": 1.0,
            "risk_score": 9.5,
            "total_return_pct": 20.0,
            "min_copy_amount": 200,
            "available": True,
            "copiers": 100,
            "positions_count": 10,
        }]
        eligible, excluded = filter_candidates(candidates, set(), 5000, max_risk=9.0)
        assert len(eligible) == 0
        assert any("risk_score" in r for r in excluded[0]["exclusion_reasons"])

    def test_no_reliable_data_excluded(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [{
            "username": "NoData",
            "risk_score": 4.0,
            "total_return_pct": 0.0,
            "avg_monthly_return": 0.0,
            "min_copy_amount": 200,
            "source": "scraper",
            "confidence": 0.5,
            "available": True,
            "copiers": 100,
            "positions_count": 10,
        }]
        eligible, excluded = filter_candidates(candidates, set(), 5000)
        assert len(eligible) == 0
        reasons = ",".join(excluded[0].get("exclusion_reasons", []))
        assert "no_valid" in reasons or "no_return" in reasons

    def test_no_affordable_traders_returns_empty(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Expensive1", "source": "tradeinfo", "confidence": 1.0, "risk_score": 4.0, "total_return_pct": 15.0, "min_copy_amount": 50000, "available": True, "copiers": 100, "positions_count": 10},
            {"username": "Expensive2", "source": "tradeinfo", "confidence": 1.0, "risk_score": 3.0, "total_return_pct": 20.0, "min_copy_amount": 30000, "available": True, "copiers": 100, "positions_count": 10},
        ]
        eligible, excluded = filter_candidates(candidates, set(), 2000)
        assert len(eligible) == 0
        assert len(excluded) == 2


class TestExplainFunctions:
    """explain_recommendation and explain_exclusion from action_planner."""

    def test_good_trader_gets_positive_reasons(self):
        from backend.ai.action_planner import explain_recommendation
        trader = {
            "username": "GoodTrader",
            "total_return_pct": 18.5,
            "risk_score": 4.0,
            "max_drawdown": 8.0,
            "volatility": 12.0,
            "avg_monthly_return": 1.5,
            "min_copy_amount": 200,
            "sharpe_score": 1.8,
            "copiers": 2500,
            "trade_frequency": 3,
            "performance_score": 75.0,
            "risk_score_category": 65.0,
        }
        reasons = explain_recommendation(trader)
        assert len(reasons) >= 3
        assert any("Strong" in r for r in reasons)
        assert any("Low drawdown" in r for r in reasons)
        assert any("Not already copied" in r for r in reasons)

    def test_minimal_trader_still_gets_reasons(self):
        from backend.ai.action_planner import explain_recommendation
        trader = {"username": "Minimal", "total_return_pct": 5.0}
        reasons = explain_recommendation(trader)
        assert len(reasons) >= 1
        assert "Not already copied" in reasons

    def test_explain_exclusion_formats_reasons(self):
        from backend.ai.action_planner import explain_exclusion
        excluded = {
            "username": "Bad",
            "exclusion_reasons": ["already_copied", "insufficient_capital (min=$20000, available=$1500)"],
        }
        reasons = explain_exclusion(excluded)
        assert len(reasons) == 2
        assert "already_copied" in reasons[0]

    def test_explain_exclusion_fallback_for_old_format(self):
        from backend.ai.action_planner import explain_exclusion
        excluded = {"username": "Old", "exclusion_reason": "already_copied"}
        reasons = explain_exclusion(excluded)
        assert reasons == ["already_copied"]
