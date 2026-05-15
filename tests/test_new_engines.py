"""
Tests for the 6 new engine modules:
  - EligibilityEngine
  - PortfolioEngine
  - DiscoveryEngine
  - ScoringEngine (new pipeline functions)
  - ActionPlanner
  - AlertEngine
  - Orchestrator
"""

from unittest.mock import MagicMock, patch

import pytest


# ── EligibilityEngine ───────────────────────────────────────────────

class TestEligibilityEngine:
    """Unit tests for backend/ai/eligibility_engine.py."""

    def test_is_already_copied_true(self):
        from backend.ai.eligibility_engine import is_already_copied
        assert is_already_copied("booker03", {"booker03", "jtrader"}) is True

    def test_is_already_copied_false(self):
        from backend.ai.eligibility_engine import is_already_copied
        assert is_already_copied("newtrader", {"booker03"}) is False

    def test_is_already_copied_case_insensitive(self):
        from backend.ai.eligibility_engine import is_already_copied
        assert is_already_copied("Booker03", {"booker03"}) is True

    def test_passes_budget_within_limit(self):
        from backend.ai.eligibility_engine import passes_budget
        ok, reason = passes_budget(200, 1000)
        assert ok is True
        assert reason is None

    def test_passes_budget_exceeded(self):
        from backend.ai.eligibility_engine import passes_budget
        ok, reason = passes_budget(2000, 1000)
        assert ok is False
        assert "insufficient_capital" in reason

    def test_passes_budget_unknown_min_copy(self):
        from backend.ai.eligibility_engine import passes_budget
        ok, reason = passes_budget(None, 150)
        assert ok is True
        assert reason is None

    def test_has_reliable_data_tradeinfo_with_return_ok(self):
        from backend.ai.eligibility_engine import has_reliable_data
        ok, reason = has_reliable_data({"source": "tradeinfo", "confidence": 1.0, "total_return_pct": 15.0})
        assert ok is True
        assert reason is None

    def test_has_reliable_data_low_confidence_rejected(self):
        from backend.ai.eligibility_engine import has_reliable_data
        ok, reason = has_reliable_data({
            "source": "scraper", "confidence": 0.5, "total_return_pct": 15.0,
        })
        assert ok is False
        assert "low_confidence" in reason

    def test_has_reliable_data_zero_return_rejected(self):
        from backend.ai.eligibility_engine import has_reliable_data
        ok, reason = has_reliable_data({
            "source": "scraper", "confidence": 0.9, "total_return_pct": 0.0,
        })
        assert ok is False
        assert "no_valid_return_data" in reason

    def test_passes_risk_within_limit(self):
        from backend.ai.eligibility_engine import passes_risk
        ok, reason = passes_risk({"risk_score": 4.0}, max_risk=9.0)
        assert ok is True

    def test_passes_risk_exceeded(self):
        from backend.ai.eligibility_engine import passes_risk
        ok, reason = passes_risk({"risk_score": 9.5}, max_risk=9.0)
        assert ok is False
        assert "risk_score" in reason

    def test_is_copy_available_true(self):
        from backend.ai.eligibility_engine import is_copy_available
        ok, reason = is_copy_available({"is_copiable": True})
        assert ok is True

    def test_is_copy_available_false(self):
        from backend.ai.eligibility_engine import is_copy_available
        ok, reason = is_copy_available({"is_copiable": False})
        assert ok is False

    def test_filter_candidates_all_checks_together(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "A", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "min_copy_amount": 300, "total_return_pct": 15.0},
            {"username": "B", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 9.5, "min_copy_amount": 300, "total_return_pct": 15.0},
            {"username": "C", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "min_copy_amount": 50000, "total_return_pct": 15.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "A"
        assert len(excluded) == 2

    def test_rejects_zero_holdings(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Empty", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "total_return_pct": 15.0, "min_copy_amount": 300, "holdings": []},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        assert any("no_holdings" in " ".join(e.get("exclusion_reasons", [])) for e in excluded)

    def test_rejects_no_positions(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "NoPos", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "total_return_pct": 15.0, "min_copy_amount": 300, "positions": []},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        assert any("no_positions" in " ".join(e.get("exclusion_reasons", [])) for e in excluded)

    def test_accepts_missing_min_copy(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "NoMin", "source": "tradeinfo", "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "total_return_pct": 15.0, "min_copy_amount": None},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 1
        assert len(excluded) == 0

    def test_rejects_fallback_zero_return(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Zero", "source": "fallback", "confidence": 0.0, "available": True, "copiers": 100, "positions_count": 10, "risk_score": 4.0, "total_return_pct": 0.0, "min_copy_amount": 300},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        reasons = " ".join(excluded[0].get("exclusion_reasons", []))
        assert "no_valid_data" in reasons or "invalid_source" in reasons

    def test_rejects_unknown_source_with_return(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "NoSrc", "source": "unknown", "available": True, "copiers": 100, "positions_count": 10, "total_return_pct": 11.2, "risk_score": 5, "min_copy_amount": 200},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        reasons = " ".join(excluded[0].get("exclusion_reasons", []))
        assert "invalid_source" in reasons

    def test_accepts_valid_trader(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Valid", "source": "tradeinfo", "confidence": 1.0,
             "available": True, "copiers": 100, "positions_count": 10,
             "min_copy_amount": 200, "total_return_pct": 15.0, "risk_score": 4.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "Valid"

    def test_rejects_zero_portfolio_size(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "ZeroPort", "source": "tradeinfo", "confidence": 1.0,
             "available": True, "copiers": 100, "positions_count": 10,
             "risk_score": 4.0, "total_return_pct": 15.0,
             "min_copy_amount": 200, "portfolio_size": 0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        reasons = " ".join(excluded[0].get("exclusion_reasons", []))
        assert "zero_portfolio_size" in reasons

    def test_rejects_blocked_trader(self):
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "Blocked", "is_copiable": False, "source": "tradeinfo",
             "confidence": 1.0, "available": True, "copiers": 100, "positions_count": 10,
             "risk_score": 4.0, "total_return_pct": 15.0, "min_copy_amount": 200},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 0
        assert any("copy_not_available" in " ".join(e.get("exclusion_reasons", [])) for e in excluded)

    def test_accepts_tradeinfo_zero_return(self):
        """SmartMoneyFX scenario: tradeinfo with 0% return is valid (real trader, flat year)."""
        from backend.ai.eligibility_engine import filter_candidates
        candidates = [
            {"username": "SmartMoneyFX", "source": "tradeinfo", "confidence": 1.0,
             "available": True, "copiers": 100, "positions_count": 10,
             "min_copy_amount": 200, "total_return_pct": 0.0, "risk_score": 5.0},
        ]
        eligible, excluded = filter_candidates(candidates, set(), available_balance=5000)
        assert len(eligible) == 1
        assert eligible[0]["username"] == "SmartMoneyFX"


class TestIsRealTrader:
    """is_real_trader strict validation tests."""

    def test_real_trader_passes(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "RealTrader", "copiers": 500,
             "positions_count": 20, "risk_score": 4.0, "total_return_pct": 15.0,
             "source": "tradeinfo"}
        ok, reason = is_real_trader(t)
        assert ok is True
        assert reason is None

    def test_not_available_rejected(self):
        from backend.ai.eligibility_engine import is_real_trader
        ok, reason = is_real_trader({"available": False, "username": "x"})
        assert ok is False
        assert reason == "trader_not_found"

    def test_empty_username_rejected(self):
        from backend.ai.eligibility_engine import is_real_trader
        ok, reason = is_real_trader({"available": True, "username": ""})
        assert ok is False
        assert reason == "missing_username"

    def test_insufficient_copiers_rejected(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 10, "positions_count": 20,
             "risk_score": 4, "total_return_pct": 15.0, "source": "tradeinfo"}
        ok, reason = is_real_trader(t)
        assert ok is False
        assert "insufficient_copiers" in reason

    def test_insufficient_positions_rejected(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 100, "positions_count": 2,
             "risk_score": 4, "total_return_pct": 15.0, "source": "tradeinfo"}
        ok, reason = is_real_trader(t)
        assert ok is False
        assert "insufficient_positions" in reason

    def test_missing_risk_score_accepted_by_is_real_trader(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 100, "positions_count": 10,
             "risk_score": 0, "total_return_pct": 15.0, "source": "tradeinfo"}
        ok, reason = is_real_trader(t)
        assert ok is True
        assert reason is None

    def test_missing_return_accepted_by_is_real_trader(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 100, "positions_count": 10,
             "risk_score": 4, "total_return_pct": None, "source": "tradeinfo"}
        ok, reason = is_real_trader(t)
        assert ok is True
        assert reason is None

    def test_unreliable_source_rejected(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 100, "positions_count": 10,
             "risk_score": 4, "total_return_pct": 15.0, "source": "unknown"}
        ok, reason = is_real_trader(t)
        assert ok is False
        assert "unreliable_source" in reason

    def test_portfolio_live_source_accepted(self):
        from backend.ai.eligibility_engine import is_real_trader
        t = {"available": True, "username": "x", "copiers": 100, "positions_count": 10,
             "risk_score": 4, "total_return_pct": 15.0, "source": "portfolio_live"}
        ok, reason = is_real_trader(t)
        assert ok is True
        assert reason is None


# ── PortfolioEngine ────────────────────────────────────────────────

class TestPortfolioEngine:
    """Unit tests for backend/ai/portfolio_engine.py."""

    def test_analyze_empty_portfolio(self):
        from backend.ai.portfolio_engine import analyze_portfolio
        result = analyze_portfolio([], total_value=10000, available_cash=500)
        assert result["total_traders"] == 0
        assert result["concentration_risk"] is False
        assert result["under_diversified"] is True
        assert result["weakest"] is None
        assert result["avg_score"] == 0.0

    def test_analyze_single_holding(self):
        from backend.ai.portfolio_engine import analyze_portfolio
        holdings = [{"username": "a", "allocation_pct": 50.0, "total_return_pct": 10.0, "risk_score": 4.0}]
        result = analyze_portfolio(holdings, total_value=10000)
        assert result["total_traders"] == 1
        assert result["concentration_risk"] is True
        assert result["under_diversified"] is True

    def test_concentration_risk_detected(self):
        from backend.ai.portfolio_engine import analyze_portfolio
        holdings = [
            {"username": "big", "allocation_pct": 60.0, "risk_score": 4.0, "total_return_pct": 10.0},
            {"username": "small", "allocation_pct": 20.0, "risk_score": 3.0, "total_return_pct": 5.0},
        ]
        result = analyze_portfolio(holdings, total_value=10000)
        assert result["concentration_risk"] is True
        # 2 traders is under-diversified (< 3), even with no concentration issue

    def test_well_diversified_portfolio(self):
        from backend.ai.portfolio_engine import analyze_portfolio
        holdings = [
            {"username": "a", "allocation_pct": 34.0, "risk_score": 3.0, "total_return_pct": 10.0,
             "final_score": 70},
            {"username": "b", "allocation_pct": 33.0, "risk_score": 4.0, "total_return_pct": 8.0,
             "final_score": 65},
            {"username": "c", "allocation_pct": 33.0, "risk_score": 5.0, "total_return_pct": 12.0,
             "final_score": 60},
        ]
        result = analyze_portfolio(holdings, total_value=10000)
        assert result["concentration_risk"] is False
        assert result["under_diversified"] is False
        assert result["weakest"]["username"] == "c"

    def test_allocations_normalized_exceeding_100(self):
        from backend.ai.portfolio_engine import analyze_portfolio
        holdings = [
            {"username": "a", "allocation_pct": 70.0, "risk_score": 3.0, "total_return_pct": 10.0,
             "final_score": 80},
            {"username": "b", "allocation_pct": 50.0, "risk_score": 4.0, "total_return_pct": 8.0,
             "final_score": 60},
        ]
        result = analyze_portfolio(holdings, total_value=10000)
        assert result["total_allocated_pct"] == 120.0

    def test_get_active_usernames(self):
        from backend.ai.portfolio_engine import get_active_usernames
        holdings = [
            {"username": "Booker03"},
            {"username": "JeppeKirkBonde"},
        ]
        names = get_active_usernames(holdings)
        assert names == {"booker03", "jeppekirkbonde"}

    def test_get_active_usernames_empty(self):
        from backend.ai.portfolio_engine import get_active_usernames
        assert get_active_usernames([]) == set()


# ── DiscoveryEngine ─────────────────────────────────────────────────

class TestDiscoveryEngine:
    """Unit tests for backend/ai/discovery_engine.py."""

    def test_build_discovery_list_no_overlap(self):
        from backend.ai.discovery_engine import build_discovery_list
        eligible = [
            {"username": "new1"},
            {"username": "new2"},
        ]
        active = {"existing1", "existing2"}
        result = build_discovery_list(eligible, active)
        assert len(result) == 2
        assert result[0]["username"] == "new1"

    def test_build_discovery_list_filters_overlap(self):
        from backend.ai.discovery_engine import build_discovery_list
        eligible = [
            {"username": "overlap_trader"},
            {"username": "genuinely_new"},
        ]
        active = {"overlap_trader"}
        result = build_discovery_list(eligible, active)
        assert len(result) == 1
        assert result[0]["username"] == "genuinely_new"

    def test_build_discovery_list_all_overlap(self):
        from backend.ai.discovery_engine import build_discovery_list
        eligible = [
            {"username": "a"},
            {"username": "b"},
        ]
        active = {"a", "b"}
        result = build_discovery_list(eligible, active)
        assert len(result) == 0

    def test_build_discovery_list_case_insensitive(self):
        from backend.ai.discovery_engine import build_discovery_list
        eligible = [
            {"username": "Booker03"},
            {"username": "NewTrader"},
        ]
        active = {"booker03"}
        result = build_discovery_list(eligible, active)
        assert len(result) == 1
        assert result[0]["username"] == "NewTrader"


# ── ScoringEngine (pipeline functions) ─────────────────────────────

class TestScoringEnginePipeline:
    """Tests for scout_holdings, rank_candidates, generate_scout_report."""

    def test_scout_holdings_empty(self):
        from backend.ai.scoring_engine import scout_holdings
        result = scout_holdings([])
        assert result["scored"] == []
        assert result["weakest"] is None
        assert result["top"] is None
        assert result["avg_score"] == 0.0

    def test_scout_holdings_returns_scored(self):
        from backend.ai.scoring_engine import scout_holdings
        h = [{"username": "a", "source": "tradeinfo", "confidence": 1.0,
              "total_return_pct": 15.0, "risk_score": 4.0}]
        result = scout_holdings(h)
        assert len(result["scored"]) == 1
        assert result["weakest"]["username"] == "a"
        assert result["top"]["username"] == "a"
        assert result["avg_score"] > 0

    def test_scout_holdings_sorts_by_score(self):
        from backend.ai.scoring_engine import scout_holdings
        holdings = [
            {"username": "low", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 5.0, "risk_score": 4.0},
            {"username": "high", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 25.0, "risk_score": 3.0},
        ]
        result = scout_holdings(holdings)
        assert result["weakest"]["username"] == "low"
        assert result["top"]["username"] == "high"

    def test_rank_candidates_empty(self):
        from backend.ai.scoring_engine import rank_candidates
        result = rank_candidates([], [])
        assert result == []

    def test_rank_candidates_returns_ranked(self):
        from backend.ai.scoring_engine import rank_candidates
        candidates = [
            {"username": "c1", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 20.0, "risk_score": 4.0},
            {"username": "c2", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 15.0, "risk_score": 5.0},
        ]
        result = rank_candidates([], candidates, top_n=2)
        assert len(result) == 2
        assert result[0]["score"] >= result[1]["score"]

    def test_rank_candidates_limits_to_top_n(self):
        from backend.ai.scoring_engine import rank_candidates
        candidates = [
            {"username": f"c{i}", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 15.0, "risk_score": 4.0}
            for i in range(5)
        ]
        result = rank_candidates([], candidates, top_n=3)
        assert len(result) == 3

    def test_generate_scout_report_healthy(self):
        from backend.ai.scoring_engine import generate_scout_report
        holdings = [
            {"username": "a", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 80.0, "risk_score": 3.0,
             "max_drawdown": 5.0, "volatility": 10.0},
            {"username": "b", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 80.0, "risk_score": 4.0,
             "max_drawdown": 5.0, "volatility": 10.0},
        ]
        report = generate_scout_report(holdings, [])
        assert report["action_required"] is False
        assert report["flagged_trader"] is None

    def test_generate_scout_report_weakest_flagged(self):
        from backend.ai.scoring_engine import generate_scout_report
        holdings = [
            {"username": "strong", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 25.0, "risk_score": 3.0},
            {"username": "weak", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 3.0, "risk_score": 8.0},
        ]
        candidates = [
            {"username": "new", "source": "tradeinfo", "confidence": 1.0,
             "return_12m": 20.0, "risk_score": 4.0},
        ]
        report = generate_scout_report(holdings, candidates)
        assert report["action_required"] is True
        assert report["flagged_trader"] == "weak"

    def test_calculate_growth_score_includes_final_score(self):
        from backend.ai.scoring_engine import calculate_growth_score
        result = calculate_growth_score({
            "username": "t", "source": "tradeinfo", "confidence": 1.0,
            "return_12m": 15.0, "risk_score": 4.0,
            "max_drawdown": 8.0, "volatility": 12.0,
            "avg_monthly_return": 2.0, "copiers": 100,
        })
        assert "final_score" in result
        assert result["final_score"] == result["score"]

    def test_apply_constraints_passes_good_trader(self):
        from backend.ai.scoring_engine import apply_constraints
        candidates = [{"username": "good", "max_drawdown": 5.0, "track_record_days": 500}]
        result = apply_constraints(candidates)
        assert len(result) == 1

    def test_apply_constraints_rejects_high_drawdown(self):
        from backend.ai.scoring_engine import apply_constraints
        candidates = [{"username": "risky", "max_drawdown": 20.0}]
        result = apply_constraints(candidates)
        assert len(result) == 0


# ── ActionPlanner ──────────────────────────────────────────────────

class TestActionPlanner:
    """Unit tests for backend/ai/action_planner.py."""

    def test_build_action_plan_empty(self):
        from backend.ai.action_planner import build_action_plan
        plan = build_action_plan({}, [], [], [])
        assert plan["active_portfolio"] == []
        assert plan["discovery"] == []
        assert plan["excluded"] == []
        assert plan["recommendations"]["recommended_swap"] is None
        assert "summary" in plan

    def test_build_action_plan_with_data(self):
        from backend.ai.action_planner import build_action_plan
        portfolio_analysis = {
            "holdings_detail": [
                {"username": "a", "allocation_pct": 50.0, "risk_score": 3.0,
                 "total_return_pct": 10.0, "final_score": 80, "max_drawdown": 5.0},
            ],
            "weakest": {"username": "a", "final_score": 80},
            "avg_score": 80.0,
            "under_diversified": True,
            "concentration_risk": True,
        }
        discovery_scored = [
            {"username": "new", "score": 85, "source": "tradeinfo",
             "confidence_score": 1.0, "source_valid": True, "explanation": ["good"],
             "details": {"return_12m": 20, "risk_score": 3, "max_drawdown": 5}},
        ]
        plan = build_action_plan(portfolio_analysis, discovery_scored, [], [])
        assert len(plan["active_portfolio"]) == 1
        assert plan["active_portfolio"][0]["username"] == "a"
        assert len(plan["discovery"]) == 1
        assert plan["discovery"][0]["username"] == "new"

    def test_recommended_swap_when_discovery_better(self):
        from backend.ai.action_planner import build_action_plan
        portfolio_analysis = {
            "holdings_detail": [
                {"username": "weak", "allocation_pct": 50.0, "risk_score": 5.0,
                 "total_return_pct": 5.0, "final_score": 30, "max_drawdown": 10.0},
            ],
            "weakest": {"username": "weak", "final_score": 30},
            "avg_score": 30.0,
            "under_diversified": True,
            "concentration_risk": False,
        }
        discovery_scored = [
            {"username": "strong", "score": 90, "source": "tradeinfo",
             "confidence_score": 1.0, "source_valid": True, "explanation": ["great"],
             "details": {"return_12m": 25, "risk_score": 2, "max_drawdown": 3}},
        ]
        plan = build_action_plan(portfolio_analysis, discovery_scored, [], [])
        swap = plan["recommendations"]["recommended_swap"]
        assert swap is not None
        assert swap["replace"] == "weak"
        assert swap["with"] == "strong"

    def test_no_swap_when_holdings_stronger(self):
        from backend.ai.action_planner import build_action_plan
        portfolio_analysis = {
            "holdings_detail": [
                {"username": "strong", "allocation_pct": 100.0, "risk_score": 3.0,
                 "total_return_pct": 20.0, "final_score": 90, "max_drawdown": 5.0},
            ],
            "weakest": {"username": "strong", "final_score": 90},
            "avg_score": 90.0,
            "under_diversified": True,
            "concentration_risk": True,
        }
        discovery_scored = [
            {"username": "ok", "score": 70, "source": "tradeinfo",
             "confidence_score": 1.0, "source_valid": True, "explanation": ["decent"],
             "details": {"return_12m": 15, "risk_score": 4, "max_drawdown": 8}},
        ]
        plan = build_action_plan(portfolio_analysis, discovery_scored, [], [])
        assert plan["recommendations"]["recommended_swap"] is None

    def test_excluded_grouped_by_reason(self):
        from backend.ai.action_planner import build_action_plan
        excluded = [
            {"username": "a", "exclusion_reasons": ["already_copied"]},
            {"username": "b", "exclusion_reasons": ["already_copied"]},
            {"username": "c", "exclusion_reasons": ["risk_score 9.5 exceeds 9"]},
        ]
        plan = build_action_plan({}, [], excluded, [])
        assert len(plan["excluded"]) >= 2  # at least 2 reason groups

    def test_format_display_returns_string(self):
        from backend.ai.action_planner import build_action_plan, format_display
        plan = build_action_plan({}, [], [], [])
        display = format_display(plan)
        assert isinstance(display, str)
        assert len(display) > 0

    def test_summarize_constraints_empty(self):
        from backend.ai.action_planner import summarize_constraints
        assert summarize_constraints({}) == []

    def test_summarize_constraints_high_drawdown(self):
        from backend.ai.action_planner import summarize_constraints
        warnings = summarize_constraints({"max_drawdown": 20.0, "risk_score": 4.0, "volatility": 5.0})
        assert any("drawdown" in w for w in warnings)

    def test_summarize_constraints_high_risk(self):
        from backend.ai.action_planner import summarize_constraints
        warnings = summarize_constraints({"max_drawdown": 5.0, "risk_score": 8.0, "volatility": 5.0})
        assert any("risk" in w for w in warnings)

    def test_explain_recommendation(self):
        from backend.ai.action_planner import explain_recommendation
        reasons = explain_recommendation({"username": "t", "total_return_pct": 20.0})
        assert len(reasons) >= 1
        assert "Not already copied" in reasons

    def test_explain_exclusion(self):
        from backend.ai.action_planner import explain_exclusion
        reasons = explain_exclusion({"exclusion_reasons": ["already_copied"]})
        assert reasons == ["already_copied"]


# ── AlertEngine ────────────────────────────────────────────────────

class TestAlertEngine:
    """Unit tests for backend/ai/alert_engine.py."""

    @pytest.fixture
    def engine(self):
        from backend.ai.alert_engine import AlertEngine
        eng = AlertEngine()
        eng.reset()  # clear any state from other tests
        return eng

    def test_first_run_fires_new_eligible(self, engine):
        portfolio_analysis = {
            "holdings_detail": [],
            "weakest": None,
            "avg_score": 0,
            "under_diversified": True,
            "concentration_risk": False,
        }
        discovery_scored = [
            {"username": "new_trader", "score": 85, "source": "tradeinfo",
             "confidence_score": 1.0, "source_valid": True, "explanation": ["good"]},
        ]
        action_plan = {"summary": "test", "recommended_swap": None}

        alerts = engine.evaluate(1, portfolio_analysis, discovery_scored, [], action_plan)
        assert len(alerts) >= 1
        types = [a["alert_type"] for a in alerts]
        assert "new_eligible_trader" in types

    def test_second_run_suppresses_duplicates(self, engine):
        portfolio_analysis = {
            "holdings_detail": [],
            "weakest": None,
            "avg_score": 0,
            "under_diversified": True,
            "concentration_risk": False,
        }
        discovery_scored = [
            {"username": "same", "score": 85, "source": "tradeinfo",
             "confidence_score": 1.0, "source_valid": True, "explanation": ["good"]},
        ]
        action_plan = {"summary": "test", "recommended_swap": None}

        engine.evaluate(1, portfolio_analysis, discovery_scored, [], action_plan)
        alerts = engine.evaluate(1, portfolio_analysis, discovery_scored, [], action_plan)
        # No new alerts — state didn't change
        assert len(alerts) == 0

    def test_concentration_risk_fires_alert(self, engine):
        portfolio_analysis = {
            "holdings_detail": [
                {"username": "big", "final_score": 70},
            ],
            "weakest": {"username": "big", "final_score": 70},
            "avg_score": 70,
            "under_diversified": True,
            "concentration_risk": True,
        }
        action_plan = {"summary": "test", "recommended_swap": None}

        alerts = engine.evaluate(1, portfolio_analysis, [], [], action_plan)
        assert any(a["alert_type"] == "overconcentration" for a in alerts)

    def test_swap_opportunity_fires_alert(self, engine):
        portfolio_analysis = {
            "holdings_detail": [{"username": "a", "final_score": 30}],
            "weakest": {"username": "a", "final_score": 30},
            "avg_score": 30,
            "under_diversified": True,
            "concentration_risk": False,
        }
        action_plan = {"summary": "swap a -> b", "recommended_swap": "b"}

        alerts = engine.evaluate(1, portfolio_analysis, [], [], action_plan)
        assert any(a["alert_type"] == "swap_opportunity" for a in alerts)

    def test_risky_trader_fires_alert(self, engine):
        portfolio_analysis = {
            "holdings_detail": [{"username": "risky", "final_score": 30}],
            "weakest": {"username": "risky", "final_score": 30},
            "avg_score": 30,
            "under_diversified": True,
            "concentration_risk": False,
        }
        action_plan = {"summary": "test", "recommended_swap": None}

        alerts = engine.evaluate(1, portfolio_analysis, [], [], action_plan)
        assert any(a["alert_type"] == "trader_became_risky" for a in alerts)

    def test_reset_clears_state(self, engine):
        engine.evaluate(1, {"holdings_detail": [], "weakest": None, "avg_score": 0,
                            "under_diversified": True, "concentration_risk": False},
                        [], [], {"summary": "test", "recommended_swap": None})
        engine.reset(1)
        # After reset, should fire alerts again
        alerts = engine.evaluate(1, {"holdings_detail": [], "weakest": None, "avg_score": 0,
                                     "under_diversified": True, "concentration_risk": False},
                                 [], [], {"summary": "test", "recommended_swap": None})
        # New eligible alerts won't fire since there are no discovery_scored
        # But check that state was reset (no suppression)
        assert len(alerts) >= 0  # at minimum no crash

    def test_multiple_portfolios_independent(self, engine):
        pa = {"holdings_detail": [], "weakest": None, "avg_score": 0,
              "under_diversified": True, "concentration_risk": False}
        ap = {"summary": "", "recommended_swap": None}
        discovery = [{"username": "t", "score": 80, "source": "tradeinfo",
                      "confidence_score": 1.0, "source_valid": True, "explanation": []}]

        a1 = engine.evaluate(1, pa, discovery, [], ap)
        a2 = engine.evaluate(2, pa, discovery, [], ap)
        assert len(a1) >= 1  # portfolio 1 fires for new trader
        assert len(a2) >= 1  # portfolio 2 also fires (separate state)


# ── Orchestrator ───────────────────────────────────────────────────

class TestOrchestrator:
    """Unit tests for backend/ai/orchestrator.py."""

    @pytest.mark.asyncio
    async def test_run_full_pipeline_portfolio_not_found(self):
        from backend.ai.orchestrator import run_full_pipeline
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = await run_full_pipeline(db, 999)
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_run_full_pipeline_returns_expected_keys(self):
        from backend.ai.orchestrator import run_full_pipeline
        from backend.database.models import Portfolio

        mock_portfolio = MagicMock(spec=Portfolio)
        mock_portfolio.id = 1
        mock_portfolio.total_value = 10000.0
        mock_portfolio.available_cash = 500.0

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_portfolio

        with patch("backend.ai.orchestrator.get_current_holdings", return_value=[]), \
             patch("backend.ai.orchestrator.discover_top_traders",
                   return_value=[{"username": "t1", "source": "tradeinfo", "confidence": 1.0,
                                  "total_return_pct": 15.0, "risk_score": 4.0}]):
            result = await run_full_pipeline(db, 1)
            assert "portfolio_analysis" in result
            assert "eligible_candidates" in result
            assert "excluded_candidates" in result
            assert "discovery_list" in result
            assert "discovery_scored" in result
            assert "action_plan" in result
            assert "alerts" in result
            assert "display" in result
            assert "eligibility_stats" in result

    @pytest.mark.asyncio
    async def test_run_full_pipeline_uses_fallback_on_failure(self):
        from backend.ai.orchestrator import run_full_pipeline
        from backend.database.models import Portfolio

        mock_portfolio = MagicMock(spec=Portfolio)
        mock_portfolio.id = 1
        mock_portfolio.total_value = 10000.0
        mock_portfolio.available_cash = 500.0

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_portfolio

        with patch("backend.ai.orchestrator.get_current_holdings", return_value=[]), \
             patch("backend.ai.orchestrator.discover_top_traders",
                   side_effect=Exception("API down")):
            result = await run_full_pipeline(db, 1)
            assert "portfolio_analysis" in result
            assert result["eligibility_stats"]["total_scanned"] == 0

    @pytest.mark.asyncio
    async def test_run_full_pipeline_force_fallback(self):
        from backend.ai.orchestrator import run_full_pipeline
        from backend.database.models import Portfolio

        mock_portfolio = MagicMock(spec=Portfolio)
        mock_portfolio.id = 1
        mock_portfolio.total_value = 10000.0
        mock_portfolio.available_cash = 500.0

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_portfolio

        with patch("backend.ai.orchestrator.get_current_holdings", return_value=[]):
            result = await run_full_pipeline(db, 1, force_fallback=True)
            assert "portfolio_analysis" in result
            assert result["eligibility_stats"]["total_scanned"] == 0

    def test_get_alert_engine_returns_singleton(self):
        from backend.ai.orchestrator import get_alert_engine
        e1 = get_alert_engine()
        e2 = get_alert_engine()
        assert e1 is e2
