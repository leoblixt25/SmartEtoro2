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
            "risk_score": 5.0,  # default — should not count
        }
        assert _compute_confidence(trader) == 0.3

    def test_zero_values_do_not_count(self):
        from backend.ai.scoring_engine import _compute_confidence
        trader = {
            "return_12m": 0.0,
            "total_return_pct": 0.0,
            "risk_score": 5.0,
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
            "risk_score": 5.0,
            "max_drawdown": 0.0,
        }
        result = calculate_growth_score(trader)
        assert result["growth_filter"] is False
        assert result["confidence_score"] == 0.3
        assert result["score"] > 0  # Not zeroed by growth filter

    def test_actual_low_return_triggers_growth_filter(self):
        """When data shows 12M return < 10%, score = 0."""
        from backend.ai.scoring_engine import calculate_growth_score
        trader = {
            "username": "low_return",
            "return_12m": 3.0,
            "risk_score": 4.0,
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
        assert result["score"] > 50
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
        h = [{"username": "a", "total_return_pct": 15.0, "risk_score": 4.0}]
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


# ── Automation Engine State Tests ────────────────────────────────────


class TestPortfolioState:
    """_determine_portfolio_state maps trader count to state."""

    @pytest.fixture
    def engine(self):
        from backend.automation.automation_engine import AutomationEngine
        return AutomationEngine()

    def test_zero_traders_is_recovery(self, engine):
        state = engine._determine_portfolio_state(None, [])
        assert state.value == "recovery"

    def test_one_trader_is_recovery(self, engine):
        state = engine._determine_portfolio_state(None, ["t1"])
        assert state.value == "recovery"

    def test_two_traders_is_degraded(self, engine):
        state = engine._determine_portfolio_state(None, ["t1", "t2"])
        assert state.value == "degraded"

    def test_three_traders_is_healthy(self, engine):
        state = engine._determine_portfolio_state(None, ["t1", "t2", "t3"])
        assert state.value == "healthy"

    def test_many_traders_is_healthy(self, engine):
        state = engine._determine_portfolio_state(None, ["t1", "t2", "t3", "t4", "t5"])
        assert state.value == "healthy"


class TestIsRecoveryMode:
    """is_recovery_mode returns True for critically under-diversified states."""

    @pytest.fixture
    def engine(self):
        from backend.automation.automation_engine import AutomationEngine
        return AutomationEngine()

    def test_one_trader_returns_true(self, engine):
        assert engine.is_recovery_mode(None, ["t1"]) is True

    def test_two_traders_returns_false(self, engine):
        assert engine.is_recovery_mode(None, ["t1", "t2"]) is False

    def test_three_traders_returns_false(self, engine):
        assert engine.is_recovery_mode(None, ["t1", "t2", "t3"]) is False


class TestInCooldown:
    """_in_cooldown respects portfolio state for bypass."""

    @pytest.fixture
    def engine(self):
        from backend.automation.automation_engine import AutomationEngine
        return AutomationEngine()

    @pytest.fixture
    def recent_rule(self):
        from backend.database.models import AutomationRule
        rule = MagicMock(spec=AutomationRule)
        rule.last_triggered = datetime.utcnow() - timedelta(minutes=5)
        rule.cooldown_hours = 1
        rule.name = "test_rule"
        rule.rule_type = "take_profit"
        return rule

    @pytest.fixture
    def old_rule(self):
        from backend.database.models import AutomationRule
        rule = MagicMock(spec=AutomationRule)
        rule.last_triggered = datetime.utcnow() - timedelta(minutes=35)
        rule.cooldown_hours = 1
        rule.name = "test_rule"
        rule.rule_type = "take_profit"
        return rule

    def test_cooldown_active_normal(self, engine, recent_rule):
        from backend.automation.automation_engine import PortfolioState
        assert engine._in_cooldown(recent_rule, PortfolioState.HEALTHY) is True

    def test_cooldown_bypassed_in_recovery(self, engine, old_rule):
        from backend.automation.automation_engine import PortfolioState
        assert engine._in_cooldown(old_rule, PortfolioState.RECOVERY) is False

    def test_recovery_throttle_30_min(self, engine, recent_rule):
        from backend.automation.automation_engine import PortfolioState
        assert engine._in_cooldown(recent_rule, PortfolioState.RECOVERY) is True

    def test_no_last_triggered_no_cooldown(self, engine):
        from backend.automation.automation_engine import PortfolioState
        rule = MagicMock()
        rule.last_triggered = None
        assert engine._in_cooldown(rule, PortfolioState.HEALTHY) is False

    def test_degraded_still_enforces_cooldown(self, engine, recent_rule):
        from backend.automation.automation_engine import PortfolioState
        assert engine._in_cooldown(recent_rule, PortfolioState.DEGRADED) is True


# ── Market Data Discovery Tests ──────────────────────────────────────


class TestDiscoverTopTraders:
    """discover_top_traders handles new Dict response and fallback."""

    @pytest.mark.asyncio
    async def test_dict_with_available_returns_list(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.discover_candidates = AsyncMock(return_value={
                "available": [{"username": "trader1"}, {"username": "trader2"}],
                "unavailable": [],
                "scanned": 2,
                "valid_count": 2,
                "rejected": 0,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) == 2
            assert result[0]["username"] == "trader1"

    @pytest.mark.asyncio
    async def test_dict_with_empty_available_triggers_fallback(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.discover_candidates = AsyncMock(return_value={
                "available": [],
                "unavailable": [
                    {"username": "bad1", "reason": "tradeinfo_not_found"},
                    {"username": "bad2", "reason": "tradeinfo_not_found"},
                ],
                "scanned": 3,
                "valid_count": 0,
                "rejected": 2,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            # Should fall back to _default_trader_candidates
            assert len(result) > 0
            assert result[0]["username"] in [
                "JeppeKirkBonde", "CPHequities", "Jaynemesis",
                "booker03", "ConsistentCapital", "GrowthEngine",
                "AlphaPulse", "SmartMoneyFX",
            ]

    @pytest.mark.asyncio
    async def test_exception_triggers_fallback(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.discover_candidates = AsyncMock(side_effect=Exception("API down"))
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_partial_unavailable_logged_not_included(self):
        with patch("backend.services.etoro_service.EToroAPIClient") as MockClient:
            client = AsyncMock()
            client.discover_candidates = AsyncMock(return_value={
                "available": [{"username": "good"}],
                "unavailable": [{"username": "bad", "reason": "tradeinfo_not_found"}],
                "scanned": 2,
                "valid_count": 1,
                "rejected": 1,
            })
            MockClient.return_value = client

            from backend.services.market_data import discover_top_traders
            result = await discover_top_traders()
            assert len(result) == 1
            assert result[0]["username"] == "good"


class TestDefaultTraderCandidates:
    """_default_trader_candidates returns expected static list."""

    def test_returns_known_traders(self):
        from backend.services.market_data import _default_trader_candidates
        result = _default_trader_candidates()
        assert len(result) == 8
        usernames = [t["username"] for t in result]
        assert "JeppeKirkBonde" in usernames
        assert "booker03" in usernames
        assert all(t["is_copiable"] for t in result)
        assert all(t["min_copy_amount"] == 200 for t in result)
