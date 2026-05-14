"""
Tests for the Daily eToro Trader-Selection Engine.
"""

import pytest
from typing import Dict, List, Optional

from backend.services.daily_selection_engine import (
    _passes_3yr_history,
    _passes_3yr_return,
    _passes_ytd_return,
    _passes_risk,
    _passes_concentration,
    _passes_activity,
    _passes_aum,
    _apply_hard_filters,
    _compute_consistency_score,
    _score_trader_first_pass,
    _score_all,
    _enrich_all,
    _news_to_score,
    _risk_to_score,
    _re_score_top10,
    _apply_safeguards,
    _build_selection_reason,
    format_selection_output,
    _build_selected_list,
    SelectedTrader,
    DailySelectionResult,
)


def make_trader(overrides: Optional[Dict] = None) -> Dict:
    base = {
        "username": "TestTrader",
        "available": True,
        "source": "tradeinfo",
        "confidence": 1.0,
        "risk_score": 4.0,
        "total_return_pct": 25.0,
        "return_3yr": 35.0,
        "return_ytd": 12.0,
        "max_drawdown": 8.0,
        "volatility": 12.0,
        "copiers": 200,
        "positions_count": 15,
        "assets_under_copy": 500000.0,
        "holdings": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        "track_record_days": 1100,
        "is_copiable": True,
        "min_copy_amount": 500.0,
    }
    if overrides:
        base.update(overrides)
    return base


class TestHardFilters:

    def test_3yr_history_passes_with_return_data(self):
        ok, _ = _passes_3yr_history(make_trader({"return_3yr": 15.0}))
        assert ok is True

    def test_3yr_history_passes_with_track_days(self):
        ok, _ = _passes_3yr_history(make_trader({"return_3yr": None, "track_record_days": 1095}))
        assert ok is True

    def test_3yr_history_fails_no_data(self):
        ok, reason = _passes_3yr_history(make_trader({"return_3yr": None, "track_record_days": 0}))
        assert ok is False
        assert "insufficient_history" in reason

    def test_3yr_return_passes_positive(self):
        ok, _ = _passes_3yr_return(make_trader({"return_3yr": 10.0}))
        assert ok is True

    def test_3yr_return_fails_negative(self):
        ok, reason = _passes_3yr_return(make_trader({"return_3yr": -5.0}))
        assert ok is False
        assert "3yr_return_not_positive" in reason

    def test_3yr_return_fails_none(self):
        ok, reason = _passes_3yr_return(make_trader({"return_3yr": None}))
        assert ok is False

    def test_ytd_return_passes_positive(self):
        ok, _ = _passes_ytd_return(make_trader({"return_ytd": 5.0}))
        assert ok is True

    def test_ytd_return_fails_negative(self):
        ok, reason = _passes_ytd_return(make_trader({"return_ytd": -2.0}))
        assert ok is False
        assert "ytd_return_not_positive" in reason

    def test_risk_passes_within_limit(self):
        ok, _ = _passes_risk(make_trader({"risk_score": 6.0}))
        assert ok is True

    def test_risk_fails_exceeds_limit(self):
        ok, reason = _passes_risk(make_trader({"risk_score": 9.0}))
        assert ok is False
        assert "risk_too_high" in reason

    def test_concentration_passes_diverse(self):
        ok, _ = _passes_concentration(make_trader({"holdings": ["A", "B", "C"]}))
        assert ok is True

    def test_concentration_passes_no_holdings(self):
        ok, _ = _passes_concentration(make_trader({"holdings": []}))
        assert ok is True

    def test_activity_passes(self):
        ok, _ = _passes_activity(make_trader({"copiers": 100, "positions_count": 10}))
        assert ok is True

    def test_activity_fails_low_copiers(self):
        ok, reason = _passes_activity(make_trader({"copiers": 10, "positions_count": 10}))
        assert ok is False
        assert "insufficient_copiers" in reason

    def test_activity_fails_low_positions(self):
        ok, reason = _passes_activity(make_trader({"copiers": 100, "positions_count": 2}))
        assert ok is False
        assert "insufficient_positions" in reason

    def test_activity_skips_when_missing(self):
        ok, _ = _passes_activity(make_trader({"copiers": None, "positions_count": None}))
        assert ok is True

    def test_aum_passes_positive(self):
        ok, _ = _passes_aum(make_trader({"assets_under_copy": 100000.0}))
        assert ok is True

    def test_aum_passes_none(self):
        ok, _ = _passes_aum(make_trader({"assets_under_copy": None}))
        assert ok is True

    def test_aum_fails_zero(self):
        ok, reason = _passes_aum(make_trader({"assets_under_copy": 0.0}))
        assert ok is False
        assert "zero_assets_under_copy" in reason

    def test_apply_hard_filters_all_pass(self):
        traders = [make_trader(), make_trader({"username": "Trader2"})]
        passed, excluded = _apply_hard_filters(traders)
        assert len(passed) == 2
        assert len(excluded) == 0

    def test_apply_hard_filters_some_excluded(self):
        traders = [
            make_trader(),
            make_trader({"username": "BadRisk", "risk_score": 9.0}),
            make_trader({"username": "BadReturn", "return_3yr": -5.0}),
        ]
        passed, excluded = _apply_hard_filters(traders)
        assert len(passed) == 1
        assert len(excluded) == 2
        assert len(excluded[0].get("exclusion_reasons", [])) >= 1


class TestScoring:

    def test_consistency_score_high_quality(self):
        score = _compute_consistency_score(make_trader({"max_drawdown": 3.0, "volatility": 8.0}))
        assert score >= 70.0

    def test_consistency_score_poor(self):
        score = _compute_consistency_score(make_trader({"max_drawdown": 20.0, "volatility": 30.0}))
        assert score < 50.0

    def test_consistency_score_uses_sharpe(self):
        score = _compute_consistency_score(make_trader({"sharpe_score": 2.0}))
        assert score >= 50.0

    def test_first_pass_scoring(self):
        trader = make_trader()
        result = _score_trader_first_pass(trader)
        assert "first_pass_score" in result
        assert "components" in result
        assert result["first_pass_score"] > 0
        assert result["first_pass_score"] <= 100

    def test_first_pass_zero_return(self):
        trader = make_trader({"return_3yr": 0.0, "return_ytd": 0.0})
        result = _score_trader_first_pass(trader)
        assert result["first_pass_score"] >= 0

    def test_score_all_returns_sorted(self):
        traders = [
            make_trader({"username": "A", "return_3yr": 10.0}),
            make_trader({"username": "B", "return_3yr": 50.0}),
            make_trader({"username": "C", "return_3yr": 30.0}),
        ]
        scored = _score_all(traders)
        by_score = sorted(scored, key=lambda x: x["first_pass_score"], reverse=True)
        assert by_score[0]["username"] == "B"
        assert by_score[2]["username"] == "A"

    def test_news_to_score_positive(self):
        score = _news_to_score({"net_score": 0.8})
        assert score > 50.0

    def test_news_to_score_negative(self):
        score = _news_to_score({"net_score": -0.8})
        assert score < 50.0

    def test_news_to_score_neutral(self):
        score = _news_to_score({"net_score": 0.0})
        assert score == 50.0

    def test_risk_to_score_low_risk(self):
        score = _risk_to_score(make_trader({"risk_score": 2.0}))
        assert score > 70.0

    def test_risk_to_score_high_risk(self):
        score = _risk_to_score(make_trader({"risk_score": 8.0}))
        assert score == 0.0

    def test_re_score_top10(self):
        traders = []
        for i in range(10):
            t = make_trader({
                "username": f"Trader{i}",
                "first_pass_score": float(90 - i * 5),
                "news": {"net_score": 0.5, "dominant_sentiment": "positive", "total": 3},
            })
            traders.append(t)

        re_scored = _re_score_top10(traders)
        assert len(re_scored) == 10
        for t in re_scored:
            assert "final_score" in t
            assert "second_pass_components" in t
            assert "selection_reason" in t
            assert t["final_score"] > 0


class TestSafeguards:

    def test_safeguard_passes_good_trader(self):
        trader = make_trader({
            "risk_score": 4.0,
            "news": {"net_score": 0.3, "dominant_sentiment": "positive"},
        })
        safe = _apply_safeguards([trader])
        assert len(safe) == 1

    def test_safeguard_removes_high_risk(self):
        trader = make_trader({
            "risk_score": 9.0,
            "news": {"net_score": 0.0, "dominant_sentiment": "neutral"},
        })
        safe = _apply_safeguards([trader])
        assert len(safe) == 0

    def test_safeguard_removes_strongly_negative_news(self):
        trader = make_trader({
            "risk_score": 4.0,
            "news": {"net_score": -0.8, "dominant_sentiment": "negative"},
        })
        safe = _apply_safeguards([trader])
        assert len(safe) == 0

    def test_safeguard_keeps_mildly_negative(self):
        trader = make_trader({
            "risk_score": 4.0,
            "news": {"net_score": -0.3, "dominant_sentiment": "negative"},
        })
        safe = _apply_safeguards([trader])
        assert len(safe) == 1


class TestOutput:

    def test_build_selection_reason_strong_trader(self):
        trader = make_trader({"return_3yr": 40.0, "return_ytd": 20.0, "news": {"dominant_sentiment": "positive"}})
        reason = _build_selection_reason(trader)
        assert isinstance(reason, str)
        assert len(reason) > 0
        assert "Strong 3yr" in reason

    def test_build_selected_list(self):
        traders = [
            make_trader({"username": "A", "final_score": 85.0, "selection_reason": "Good performer",
                         "news": {"dominant_sentiment": "positive", "net_score": 0.5}}),
            make_trader({"username": "B", "final_score": 75.0, "selection_reason": "Solid returns",
                         "news": {"dominant_sentiment": "neutral", "net_score": 0.0}}),
            make_trader({"username": "C", "final_score": 65.0, "selection_reason": "Passed filters",
                         "news": {"dominant_sentiment": "positive", "net_score": 0.2}}),
        ]
        selected = _build_selected_list(traders)
        assert len(selected) == 3
        for s in selected:
            assert isinstance(s, SelectedTrader)
            assert s.final_score > 0
            assert len(s.selection_reason) > 0

    def test_format_selection_output_with_results(self):
        selected = [
            SelectedTrader(
                username="TraderA", performance_3yr=35.0, performance_ytd=12.0,
                copiers=200, assets_under_copy=500000.0,
                main_holdings=["AAPL", "MSFT"],
                news_sentiment={"dominant_sentiment": "positive", "net_score": 0.5},
                final_score=85.0, selection_reason="Strong performance",
            )
        ]
        result = DailySelectionResult(
            top_3=selected, all_scored=[], excluded=[],
            scanned_count=100,
            stats={"status": "success", "passed_filters": 10, "top_10_scored": 10},
        )
        output = format_selection_output(result)
        assert "DAILY TRADER SELECTION REPORT" in output
        assert "TraderA" in output
        assert "85.0" in output

    def test_format_selection_output_empty(self):
        result = DailySelectionResult(
            top_3=[], all_scored=[], excluded=[], scanned_count=0,
            stats={"status": "empty", "reason": "No traders found"},
        )
        output = format_selection_output(result)
        assert "DAILY TRADER SELECTION REPORT" in output
        assert "No high-confidence traders found today" in output


class TestIntegration:

    def test_enrich_all_with_mock_client(self):
        class MockClient:
            async def get_trader_extended_metrics(self, username):
                return make_trader({"username": username})

        candidates = [make_trader({"username": "A"}), make_trader({"username": "B"})]
        import asyncio
        enriched = asyncio.run(_enrich_all(candidates, MockClient()))
        assert len(enriched) == 2
        assert enriched[0]["username"] == "A"

    def test_enrich_all_filters_unavailable(self):
        class MockClient:
            async def get_trader_extended_metrics(self, username):
                if username == "Bad":
                    return {"available": False, "username": "Bad"}
                return make_trader({"username": username})

        candidates = [
            make_trader({"username": "Good"}),
            make_trader({"username": "Bad"}),
        ]
        import asyncio
        enriched = asyncio.run(_enrich_all(candidates, MockClient()))
        assert len(enriched) == 1
        assert enriched[0]["username"] == "Good"

    def test_full_pipeline_happy_path(self):
        all_scored = [{
            "username": f"T{i}",
            "first_pass_score": float(80 - i * 5),
            "return_3yr": 20.0,
            "return_ytd": 10.0,
            "risk_score": 4.0,
            "max_drawdown": 8.0,
            "volatility": 12.0,
            "copiers": 200,
            "positions_count": 15,
            "assets_under_copy": 500000.0,
            "holdings": ["AAPL", "MSFT"],
            "available": True,
            "source": "tradeinfo",
            "confidence": 1.0,
            "track_record_days": 1100,
            "news": {"net_score": 0.0, "dominant_sentiment": "neutral", "total": 0},
        } for i in range(15)]

        top_10 = all_scored[:10]
        re_scored = _re_score_top10(top_10)
        top_3 = re_scored[:3]
        top_3 = _apply_safeguards(top_3)

        assert len(top_3) == 3
        assert all(t.get("final_score", 0) > 0 for t in top_3)
        assert top_3[0]["first_pass_score"] >= top_3[1]["first_pass_score"]
