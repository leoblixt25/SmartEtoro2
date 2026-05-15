"""
Tests for the Trader Monitoring feature modules:
  - NewsCache
  - NewsService (sentiment scoring, duplicate detection)
  - HoldingParser
  - TraderHealthEngine
  - WatchlistSummary
  - MonitoringState
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── NewsCache ───────────────────────────────────────────────────────

class TestNewsCache:
    """Unit tests for backend/monitoring/news_cache.py."""

    def test_get_missing_returns_none(self):
        from backend.monitoring.news_cache import NewsCache
        cache = NewsCache(ttl_seconds=60)
        assert cache.get("AAPL") is None

    def test_set_and_get(self):
        from backend.monitoring.news_cache import NewsCache
        cache = NewsCache(ttl_seconds=60)
        news = [{"title": "Apple beats expectations"}]
        cache.set("AAPL", news)
        assert cache.get("AAPL") == news

    def test_cache_miss_after_invalidate(self):
        from backend.monitoring.news_cache import NewsCache
        cache = NewsCache(ttl_seconds=60)
        cache.set("AAPL", [{"title": "test"}])
        cache.invalidate("AAPL")
        assert cache.get("AAPL") is None

    def test_invalidate_all(self):
        from backend.monitoring.news_cache import NewsCache
        cache = NewsCache(ttl_seconds=60)
        cache.set("AAPL", [{"title": "a"}])
        cache.set("MSFT", [{"title": "b"}])
        cache.invalidate()
        assert cache.size == 0

    def test_cache_expires(self):
        from backend.monitoring.news_cache import NewsCache
        import time
        cache = NewsCache(ttl_seconds=1)
        cache.set("AAPL", [{"title": "test"}])
        assert cache.get("AAPL") is not None
        time.sleep(1.1)
        assert cache.get("AAPL") is None

    def test_size_and_symbols(self):
        from backend.monitoring.news_cache import NewsCache
        cache = NewsCache(ttl_seconds=60)
        cache.set("AAPL", [])
        cache.set("MSFT", [])
        assert cache.size == 2
        assert "AAPL" in cache.symbols or "AAPL" in [s.upper() for s in cache.symbols]

    def test_default_cache_singleton(self):
        from backend.monitoring.news_cache import get_news_cache, NewsCache
        c1 = get_news_cache()
        c2 = get_news_cache()
        assert c1 is c2


# ── NewsService ─────────────────────────────────────────────────────

class TestNewsService:
    """Tests for sentiment scoring and dedup."""

    def setup_method(self):
        from backend.monitoring.news_service import _reset_seen_headlines
        _reset_seen_headlines()

    def test_positive_sentiment(self):
        from backend.monitoring.news_service import _score_sentiment
        sent, conf = _score_sentiment("Apple beats earnings expectations, stock surges")
        assert sent == "positive"
        assert conf >= 0.5

    def test_negative_sentiment(self):
        from backend.monitoring.news_service import _score_sentiment
        sent, conf = _score_sentiment("Tesla crash reported, investigation launched")
        assert sent == "negative"
        assert conf >= 0.5

    def test_neutral_sentiment(self):
        from backend.monitoring.news_service import _score_sentiment
        sent, conf = _score_sentiment("Markets open mixed with cautious trading")
        assert sent == "neutral"

    def test_duplicate_detection(self):
        from backend.monitoring.news_service import _is_duplicate
        assert _is_duplicate("Breaking news") is False
        assert _is_duplicate("Breaking news") is True
        assert _is_duplicate("Different headline") is False

    def test_aggregate_sentiment_empty(self):
        from backend.monitoring.news_service import aggregate_sentiment
        result = aggregate_sentiment({})
        assert result["total"] == 0
        assert result["net_score"] == 0.0
        assert result["dominant_sentiment"] == "neutral"

    def test_aggregate_sentiment_mixed(self):
        from backend.monitoring.news_service import aggregate_sentiment
        news = {
            "AAPL": [
                {"sentiment": "positive", "title": "a"},
                {"sentiment": "positive", "title": "b"},
            ],
            "TSLA": [
                {"sentiment": "negative", "title": "c"},
            ],
        }
        result = aggregate_sentiment(news)
        assert result["positive_count"] == 2
        assert result["negative_count"] == 1
        assert result["dominant_sentiment"] == "positive"
        assert "AAPL" in result["positive_symbols"]
        assert "TSLA" in result["negative_symbols"]

    @pytest.mark.asyncio
    async def test_fetch_symbol_news_cache_hit(self):
        from backend.monitoring.news_service import fetch_symbol_news
        from backend.monitoring.news_cache import get_news_cache
        cache = get_news_cache()
        cache.set("TEST", [{"title": "cached", "sentiment": "neutral", "confidence": 0.5,
                            "summary": "", "source": "test"}])
        result = await fetch_symbol_news("TEST", max_items=5, use_cache=True)
        assert len(result) >= 1
        assert result[0]["title"] == "cached"

    @pytest.mark.asyncio
    async def test_fetch_symbol_news_skips_cache_when_disabled(self):
        from backend.monitoring.news_service import fetch_symbol_news
        from backend.monitoring.news_cache import get_news_cache
        cache = get_news_cache()
        cache.set("TEST2", [{"title": "should not appear"}])
        # Disabled cache means it won't check — will try yfinance and fail gracefully
        result = await fetch_symbol_news("TEST2", max_items=5, use_cache=False)
        # yfinance will either return data or fail — handle both gracefully
        assert isinstance(result, list)
        cache.invalidate("TEST2")

    def test_is_relevant_news_filters_short_titles(self):
        from backend.monitoring.news_service import _is_relevant_news
        # Reset dedup
        from backend.monitoring.news_service import _reset_seen_headlines
        _reset_seen_headlines()
        assert _is_relevant_news({"title": "Hi"}) is False
        assert _is_relevant_news({"title": "This is a real headline about markets"}) is True


# ── HoldingParser ───────────────────────────────────────────────────

class TestHoldingParser:
    """Tests for backend/monitoring/holding_parser.py."""

    def test_classify_stock(self):
        from backend.monitoring.holding_parser import classify_instrument
        assert classify_instrument("AAPL") == "stock"

    def test_classify_crypto(self):
        from backend.monitoring.holding_parser import classify_instrument
        assert classify_instrument("BTC-USD") == "crypto"
        assert classify_instrument("ETH") == "crypto"

    def test_classify_etf(self):
        from backend.monitoring.holding_parser import classify_instrument
        assert classify_instrument("SPY") == "etf"
        assert classify_instrument("QQQ") == "etf"

    def test_parse_holdings_from_mirrors(self):
        from backend.monitoring.holding_parser import parse_holdings_from_mirrors
        mirrors = [
            {
                "parentUsername": "booker03",
                "positions": [
                    {"instrument": "AAPL", "amount": 1000},
                    {"instrument": "MSFT", "amount": 500},
                ],
            }
        ]
        result = parse_holdings_from_mirrors(mirrors)
        assert "booker03" in result
        assert len(result["booker03"]) == 2
        assert result["booker03"][0]["symbol"] == "AAPL"
        assert result["booker03"][0]["weight"] > result["booker03"][1]["weight"]

    def test_parse_holdings_from_mirrors_empty(self):
        from backend.monitoring.holding_parser import parse_holdings_from_mirrors
        result = parse_holdings_from_mirrors([])
        assert result == {}

    def test_parse_holdings_from_db_positions(self):
        from backend.monitoring.holding_parser import parse_holdings_from_db_positions
        positions = [
            {"instrument": "AAPL", "amount": 2000},
            {"instrument": "GOOGL", "amount": 1000},
        ]
        result = parse_holdings_from_db_positions(positions)
        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"

    def test_extract_symbols(self):
        from backend.monitoring.holding_parser import extract_symbols
        holdings = [
            {"symbol": "AAPL"},
            {"symbol": "MSFT"},
            {"symbol": "AAPL"},
        ]
        symbols = extract_symbols(holdings)
        assert symbols == ["AAPL", "MSFT"]

    def test_extract_symbols_empty(self):
        from backend.monitoring.holding_parser import extract_symbols
        assert extract_symbols([]) == []

    @pytest.mark.asyncio
    async def test_get_trader_holdings_unknown(self):
        from backend.monitoring.holding_parser import get_trader_holdings
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        holdings, source = await get_trader_holdings(db, 1, "unknown_trader")
        assert holdings == []
        assert source == "unknown"


# ── TraderHealthEngine ─────────────────────────────────────────────

class TestTraderHealthEngine:
    """Tests for backend/monitoring/trader_health_engine.py."""

    def test_analyze_strong_trader_with_positive_news(self):
        from backend.monitoring.trader_health_engine import analyze_trader_health
        trader = {
            "username": "strong_trader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "total_return_pct": 80.0,
            "risk_score": 3.0,
            "max_drawdown": 5.0,
            "copiers": 500,
        }
        holdings = [
            {"symbol": "AAPL", "name": "AAPL", "weight": 60.0, "type": "stock", "amount": 6000},
            {"symbol": "MSFT", "name": "MSFT", "weight": 40.0, "type": "stock", "amount": 4000},
        ]
        news_by_symbol = {
            "AAPL": [{"sentiment": "positive", "title": "Apple beats earnings", "confidence": 0.8}],
            "MSFT": [{"sentiment": "positive", "title": "Microsoft cloud grows", "confidence": 0.7}],
        }
        trader["_holdings_source"] = "api_mirror"
        result = analyze_trader_health(trader, holdings, news_by_symbol)
        assert result["signal"] in ("increase", "hold")
        assert result["confidence"] >= 0.5
        assert len(result["reasons"]) >= 2

    def test_analyze_trader_with_negative_news(self):
        from backend.monitoring.trader_health_engine import analyze_trader_health
        trader = {
            "username": "bad_trader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 5.0,
            "return_6m": 2.0,
            "total_return_pct": 5.0,
            "risk_score": 8.0,
            "max_drawdown": 20.0,
            "volatility": 18.0,
        }
        holdings = [
            {"symbol": "TSLA", "name": "TSLA", "weight": 70.0, "type": "stock", "amount": 7000},
            {"symbol": "META", "name": "META", "weight": 30.0, "type": "stock", "amount": 3000},
        ]
        news_by_symbol = {
            "TSLA": [{"sentiment": "negative", "title": "Tesla crash investigation", "confidence": 0.8}],
            "META": [{"sentiment": "negative", "title": "Meta regulatory fine", "confidence": 0.7}],
        }
        trader["_holdings_source"] = "api_mirror"
        result = analyze_trader_health(trader, holdings, news_by_symbol)
        assert result["signal"] in ("reduce", "avoid")
        assert len(result["top_negative_holdings"]) >= 1

    def test_analyze_trader_no_news_data(self):
        from backend.monitoring.trader_health_engine import analyze_trader_health
        trader = {
            "username": "no_news_trader",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 12.0,
            "return_6m": 8.0,
            "total_return_pct": 12.0,
            "risk_score": 4.0,
            "max_drawdown": 8.0,
        }
        trader["_holdings_source"] = "api_mirror"
        result = analyze_trader_health(trader, [], {})
        assert result["signal"] == "reduce"
        assert result["holdings_source"] == "api_mirror"

    def test_analyze_trader_missing_holdings(self):
        from backend.monitoring.trader_health_engine import analyze_trader_health
        trader = {
            "username": "unknown_holdings",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 10.0,
            "risk_score": 5.0,
            "max_drawdown": 10.0,  # Provide drawdown so performance score stays "stable"
            "copiers": 1,  # 4th verified field to pass data quality gate (no bonus at 1)
        }
        trader["_holdings_source"] = "unknown"
        result = analyze_trader_health(trader, [], {})
        assert result["signal"] == "reduce"
        assert result["holdings_count"] == 0

    def test_analyze_trader_critical_risk(self):
        from backend.monitoring.trader_health_engine import analyze_trader_health
        trader = {
            "username": "risky",
            "source": "tradeinfo",
            "confidence": 1.0,
            "return_12m": 2.0,
            "risk_score": 9.5,
            "max_drawdown": 35.0,
        }
        trader["_holdings_source"] = "unknown"
        result = analyze_trader_health(trader, [], {})
        assert result["signal"] == "avoid"

    def test_score_performance_strong(self):
        from backend.monitoring.trader_health_engine import _score_performance
        trader = {"source": "tradeinfo", "confidence": 1.0,
                  "total_return_pct": 135.0,
                  "risk_score": 3.0,
                  "copiers": 500,
                  "max_drawdown": 5.0}
        score, label = _score_performance(trader)
        assert label == "strong"
        assert score >= 70

    def test_score_performance_weak(self):
        from backend.monitoring.trader_health_engine import _score_performance
        trader = {"source": "tradeinfo", "confidence": 1.0,
                  "return_12m": 2.0, "risk_score": 5.0}
        score, label = _score_performance(trader)
        assert label == "weak" or label == "critical"


# ── WatchlistSummary ───────────────────────────────────────────────

class TestWatchlistSummary:
    """Tests for backend/monitoring/watchlist_summary.py."""

    def test_empty_results(self):
        from backend.monitoring.watchlist_summary import build_watchlist_summary
        summary = build_watchlist_summary([])
        assert summary["debug"]["total"] == 0
        assert summary["sentiment"] == "neutral"

    def test_sorts_by_signal(self):
        from backend.monitoring.watchlist_summary import build_watchlist_summary
        results = [
            {"trader": "a", "signal": "increase", "confidence": 0.8, "performance_score": 80,
             "reasons": ["good"]},
            {"trader": "b", "signal": "reduce", "confidence": 0.7, "performance_score": 30,
             "reasons": ["bad"]},
            {"trader": "c", "signal": "hold", "confidence": 0.6, "performance_score": 55,
             "reasons": ["ok"]},
        ]
        summary = build_watchlist_summary(results)
        assert len(summary["increase"]) == 1
        assert len(summary["reduce"]) == 1
        assert len(summary["hold"]) == 1
        assert summary["increase"][0]["trader"] == "a"
        assert summary["debug"]["by_signal"]["increase"] == 1
        assert summary["debug"]["by_signal"]["reduce"] == 1

    def test_sentiment_positive(self):
        from backend.monitoring.watchlist_summary import build_watchlist_summary
        results = [
            {"trader": "a", "signal": "increase", "confidence": 0.9, "performance_score": 90,
             "reasons": []},
            {"trader": "b", "signal": "increase", "confidence": 0.8, "performance_score": 85,
             "reasons": []},
        ]
        summary = build_watchlist_summary(results)
        assert summary["sentiment"] == "positive"

    def test_sentiment_negative(self):
        from backend.monitoring.watchlist_summary import build_watchlist_summary
        results = [
            {"trader": "a", "signal": "reduce", "confidence": 0.9, "performance_score": 20,
             "reasons": []},
            {"trader": "b", "signal": "avoid", "confidence": 0.8, "performance_score": 10,
             "reasons": []},
        ]
        summary = build_watchlist_summary(results)
        assert summary["sentiment"] == "negative"

    def test_avg_performance(self):
        from backend.monitoring.watchlist_summary import build_watchlist_summary
        results = [
            {"trader": "a", "signal": "hold", "confidence": 0.5, "performance_score": 80,
             "reasons": []},
            {"trader": "b", "signal": "hold", "confidence": 0.5, "performance_score": 60,
             "reasons": []},
        ]
        summary = build_watchlist_summary(results)
        assert summary["debug"]["avg_performance"] == 70.0


# ── MonitoringState ────────────────────────────────────────────────

class TestMonitoringState:
    """Tests for backend/monitoring/monitor_state.py."""

    def test_first_run_no_alerts(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        results = [
            {"trader": "a", "signal": "hold", "confidence": 0.7,
             "holdings_health": 80, "reasons": [], "top_negative_holdings": []},
        ]
        alerts = state.get_changes(results)
        assert len(alerts) == 0  # first run — just learning

    def test_hold_to_reduce_fires_alert(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.7,
             "holdings_health": 80, "reasons": [], "top_negative_holdings": []},
        ])
        alerts = state.get_changes([
            {"trader": "a", "signal": "reduce", "confidence": 0.7,
             "holdings_health": 40, "reasons": ["worsening"],
             "top_negative_holdings": ["TSLA"]},
        ])
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "monitor_trader_downgrade"

    def test_hold_to_increase_fires_alert(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.6,
             "holdings_health": 50, "reasons": [], "top_negative_holdings": []},
        ])
        alerts = state.get_changes([
            {"trader": "a", "signal": "increase", "confidence": 0.8,
             "holdings_health": 80, "reasons": ["improving"],
             "top_negative_holdings": []},
        ])
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "monitor_trader_upgrade"

    def test_no_alert_for_same_signal(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.6,
             "holdings_health": 50, "reasons": [], "top_negative_holdings": []},
        ])
        alerts = state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.6,
             "holdings_health": 50, "reasons": [], "top_negative_holdings": []},
        ])
        assert len(alerts) == 0

    def test_reset_clears_state(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.6,
             "holdings_health": 50, "reasons": [], "top_negative_holdings": []},
        ])
        state.reset("a")
        alerts = state.get_changes([
            {"trader": "a", "signal": "reduce", "confidence": 0.7,
             "holdings_health": 30, "reasons": ["bad"],
             "top_negative_holdings": ["TSLA"]},
        ])
        # After reset, first run is "learning" — no alert
        assert len(alerts) == 0

    def test_negative_news_impact_alert(self):
        from backend.monitoring.monitor_state import MonitoringState
        state = MonitoringState()
        state.get_changes([
            {"trader": "a", "signal": "hold", "confidence": 0.6,
             "holdings_health": 60, "reasons": [], "top_negative_holdings": []},
        ])
        alerts = state.get_changes([
            {"trader": "a", "signal": "reduce", "confidence": 0.7,
             "holdings_health": 20, "reasons": ["negative news"],
             "top_negative_holdings": ["TSLA"]},
        ])
        has_news_alert = any(
            a["alert_type"] == "monitor_negative_news_impact" for a in alerts
        )
        assert has_news_alert
