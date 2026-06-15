# Graph Report - .  (2026-06-13)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1095 nodes · 2181 edges · 66 communities (64 shown, 2 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 282 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `756c3250`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 52|Community 52]]

## God Nodes (most connected - your core abstractions)
1. `TelegramBot` - 49 edges
2. `Portfolio` - 42 edges
3. `TraderProfile` - 38 edges
4. `filter_candidates()` - 35 edges
5. `EToroAPIClient` - 35 edges
6. `Session` - 34 edges
7. `EToroSyncService` - 34 edges
8. `CopiedTrader` - 31 edges
9. `SafeFetcher` - 29 edges
10. `TestEligibilityEngine` - 27 edges

## Surprising Connections (you probably didn't know these)
- `TestActionPlanner` --uses--> `AlertEngine`  [INFERRED]
  tests/test_new_engines.py → backend/ai/alert_engine.py
- `TestDiscoveryEngine` --uses--> `AlertEngine`  [INFERRED]
  tests/test_new_engines.py → backend/ai/alert_engine.py
- `TestEligibilityEngine` --uses--> `AlertEngine`  [INFERRED]
  tests/test_new_engines.py → backend/ai/alert_engine.py
- `TestIsRealTrader` --uses--> `AlertEngine`  [INFERRED]
  tests/test_new_engines.py → backend/ai/alert_engine.py
- `TestOrchestrator` --uses--> `AlertEngine`  [INFERRED]
  tests/test_new_engines.py → backend/ai/alert_engine.py

## Import Cycles
- 1-file cycle: `backend/main.py -> backend/main.py`

## Communities (66 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (41): db_session(), Context manager for use outside FastAPI request cycle (e.g., scheduler)., ai_analyze_traders(), _build_trader_text(), _parse_ai_response(), AI-Powered Trader Health Engine — uses OpenAI/OpenRouter/Groq to analyze traders, Analyze all traders via OpenAI/OpenRouter/Groq. Returns list of result dicts or, Format trader data for the AI prompt with clean metrics. (+33 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (20): filter_candidates(), has_reliable_data(), has_substance(), is_already_copied(), is_copy_available(), passes_budget(), passes_risk(), Eligibility Engine — hard filter layer applied BEFORE scoring.  Rule: A trader i (+12 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (30): Badge(), BADGE_STYLES, Card(), EmptyState(), PageHeader(), PnlDisplay(), Spinner(), ActiveTraders() (+22 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (19): EToroAPIClient, Reject mirror_id=0 before hitting the eToro API.          A mirror ID of 0 mea, Discover traders via the working search/people API endpoint.          Uses GET, Mass discovery with concurrent pagination and lightweight metadata.          F, Fetch portfolio + PnL + positions + mirrors in one call.         Retries up to, Close a copy-trade mirror position on eToro using the retail API.          Use, Client for the official eToro Public API.      Authentication uses two keys fr, Change the allocated amount of a copy-trade mirror on eToro.          eToro AP (+11 more)

### Community 4 - "Community 4"
Cohesion: 0.05
Nodes (38): 10. Environment Variables, 11. eToro Sync (`backend/services/etoro_service.py`), 12. Eligibility Rules Summary, 13. Test Suite, 14. Key Architecture Decisions, 1. What It Is, 2. Architecture Overview, 3. Database Schema (+30 more)

### Community 5 - "Community 5"
Cohesion: 0.10
Nodes (17): Copied Trader Analytics Engine ─────────────────────────────────────────────────, Percentage of positive months. Higher = more consistent., Convert max drawdown % to a 0–100 health score.         0% drawdown → 100; 50%+, Simplified Sharpe-like ratio: mean return / std deviation.         Risk-free rat, Lower volatility → higher score. Clamp at 80%., More unique instrument types = better diversification.         Classify instrume, Ideal: 1–10 trades/week. Very high frequency penalized (HFT risk).         Very, Weighted composite of component scores → 0–100. (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (24): active_traders(), add_trader(), alert_summary(), dashboard(), discovery(), get_portfolio(), get_portfolio_alerts(), _get_portfolio_or_404() (+16 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (24): Base, CopiedTrader, CopiedTrader, Portfolio, PortfolioSnapshot, Position, SQLite / PostgreSQL database models using SQLAlchemy ORM. Set DATABASE_URL to a, Historical analytics snapshot for a trader. (+16 more)

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (28): rank_combined(), Scoring Engine — backward-compatible wrapper around discovery/score.  All core l, TraderProfile, Score discovery candidates using the typed scoring engine.      Returns top_n ca, _score_discovery_candidates(), _available_weights(), _best_return_pct(), calculate_growth_score() (+20 more)

### Community 9 - "Community 9"
Cohesion: 0.10
Nodes (24): mark_alert_read_endpoint(), Session, Session, Session, discover_eligible_traders(), Find new eligible traders not already copied.      Guarded by a lock (prevents o, get_alert_summary(), get_alerts() (+16 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (21): analyze_trader_health(), _assess_data_quality(), _build_reason(), _check_data_flags(), _determine_confidence(), _get_action(), _has_clear_negative_risk(), _has_real_risk_data() (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (27): Adding a real eToro data source, Adding new automation rule types, AI Analysis, Alerts, Analytics Engine, API Reference, Architecture, Automation (+19 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (10): apply_constraints(), generate_scout_report(), rank_candidates(), Backward-compat: filter candidates by hard constraints., scout_holdings(), scout_holdings handles edge cases., TestScoutHoldings, Tests for the 6 new engine modules:   - EligibilityEngine   - PortfolioEngine (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.33
Nodes (25): AlertResponse, CopiedTraderCreate, CopiedTraderResponse, CopiedTraderUpdate, PortfolioBase, PortfolioCreate, PortfolioResponse, PortfolioUpdate (+17 more)

### Community 14 - "Community 14"
Cohesion: 0.11
Nodes (14): Alert, System alerts sent to the user., check_return_thresholds(), Check active traders for return threshold breaches.      Alerts when a trader's, EToroSyncService, Syncs eToro account data with local database.     Pulls real-time portfolio met, Sync portfolio with real eToro data.         Falls back to simulation data when, Parse eToro API portfolio response into flat summary dict.          Total Valu (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (15): Discovery pipeline orchestrator — one job at a time, with cooldown and cache.  T, DiscoveryResult, DiscoveryStats, Typed data structures for the discovery pipeline.  Every trader passes through t, Aggregate statistics from a discovery run., Full result of a discovery pipeline run., Result of scoring a single trader., ScoreResult (+7 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (23): dependencies, axios, clsx, lucide-react, react, react-dom, react-router-dom, recharts (+15 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): calculate_score_from_profile(), _consistency_component(), _drawdown_component(), Get absolute drawdown, default large if missing., Return score 0-100. Nonlinear sqrt curve.      0%→0, 25%→60, 50%→85, 70%→100, 10, Risk-adjusted return 0-100. return / max(dd,5) / risk_penalty, sqrt curve., Consistency score 0-100. Linear from 30% floor.      <30%→0, 50%→30, 60%→45, 70%, Drawdown score 0-100. Linear: -2.5pt per % above 5.      5%→100, 10%→88, 15%→75, (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (21): EToroAPIClient, Daily discovery report — 5-stage mass scan, send top results., _make_progress(), _next_run_id(), Screener Service ───────────────────────────────────────────────────────────────, Remove weak candidates using only lightweight metadata from search API.      The, Enrich filtered candidates with full tradeinfo data., Score all enriched candidates using the weighted engine. (+13 more)

### Community 19 - "Community 19"
Cohesion: 0.12
Nodes (8): NewsCache, News Cache — TTL-based in-memory cache for per-symbol news results.  Prevents re, In-memory cache for news results keyed by symbol.      Each entry stores:, Return cached news for symbol, or None if expired/missing., Store news for symbol with TTL., Clear cache for one symbol, or all if symbol is None., Unit tests for backend/monitoring/news_cache.py., TestNewsCache

### Community 20 - "Community 20"
Cohesion: 0.10
Nodes (8): AlertEngine, Alert Engine — smart deduplicated notifications.  Only fires when something mean, Build a hashable snapshot of the current state for comparison., Reset stored state for a portfolio (or all if None)., Stateful alert deduplication engine.      Stores a snapshot of the last notified, Compare current state to previous and return new alerts.          Returns a list, Unit tests for backend/ai/alert_engine.py., TestAlertEngine

### Community 21 - "Community 21"
Cohesion: 0.14
Nodes (6): Any, GET with browser-like headers (for public/non-API endpoints)., Thread-safe, rate-limited HTTP client for eToro API calls.      Usage:         f, GET request with rate limiting, retry, and optional caching.          Args:, SafeFetcher, TestSafeFetcher

### Community 22 - "Community 22"
Cohesion: 0.17
Nodes (9): TraderProfile, A single trader's full profile after fetch + validation.      All *raw_ fields h, TraderProfile, check_constraints(), Validate that the trader's data comes from a reliable source.      Returns None, Hard-constraint checks on a single profile. Returns rejection reason or None., validate_data_source(), TestCheckConstraints (+1 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (9): Shared fetch layer — rate-limited, cached, safe HTTP client.  All outbound reque, TestSafeLog, Shared safe formatting utilities — never crash on None., Return str(value) or 'missing' if value is None., Return str(int(value)) or 'missing' if value is None., Format a numeric value safely — returns 'missing' if value is None., safe_fmt(), safe_int() (+1 more)

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (8): classify_int(), classify_numeric(), classify_return(), Validation layer — classify each field as verified, missing, or fallback.  Never, Classify a single numeric field.      Returns:         'verified' — value is not, Classify a return value — 0 means no data., Classify an integer value — None or 0 means missing., TestValidateFieldClassification

### Community 25 - "Community 25"
Cohesion: 0.14
Nodes (12): Exception, T, FailureLogger, Utility for logging failures with structured context.      Usage:         logger, Configure root logger with structured format and severity level.      Every log, setup_logging(), async_retry(), Raised when all retry attempts have been exhausted. (+4 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (7): MonitoringState, Monitoring State — tracks previous trader health results for alert dedup.  Only, Reset state for one trader, or all if None., Tracks last-known trader signals to detect meaningful changes., Compare current results to previous state, return new alerts.          Each aler, Tests for backend/monitoring/monitor_state.py., TestMonitoringState

### Community 27 - "Community 27"
Cohesion: 0.17
Nodes (9): aggregate_sentiment(), Aggregate sentiment across all news items.      Returns:         {positive_count, Reset dedup set (useful for testing)., Score a news item as positive, negative, or neutral.      Returns (label, confid, _reset_seen_headlines(), _score_sentiment(), Tests for the Trader Monitoring feature modules:   - NewsCache   - NewsService (, Tests for sentiment scoring and dedup. (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.17
Nodes (16): _extract_xml_tag(), fetch_market_news(), _fetch_news_fallback(), get_market_news(), _hardcoded_news_fallback(), _parse_yahoo_rss(), Market Data Ingestion Pipeline ────────────────────────────────────────────────, Fetch live news headlines for major stocks + indices using yfinance.      Uses (+8 more)

### Community 29 - "Community 29"
Cohesion: 0.17
Nodes (9): format_display(), Format the action plan into a clean, readable display string., get_alert_engine(), Orchestrator — runs the full Decision + Alert pipeline.  Flow:   1. Fetch discov, Run the full Decision + Alert pipeline for a single portfolio.      Args:, run_full_pipeline(), AlertEngine, Unit tests for backend/ai/orchestrator.py. (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.17
Nodes (11): build_discovery_list(), log_discovery_summary(), Discovery Engine — manages new trader candidates.  Ensures ZERO overlap between, Log detailed summary of the discovery run., Build discovery list of genuinely NEW eligible traders.      Enforces strict sep, Widen search when too few eligible traders found.      Removes category filter o, widen_search(), Internal pipeline execution — no lock/cooldown checks.      Separated so it can (+3 more)

### Community 31 - "Community 31"
Cohesion: 0.17
Nodes (11): build_trader_profile(), Build a TraderProfile from a raw API dict, classifying every field., format_trader_block(), _insight(), main(), Fetch raw discovery data from production API, re-score locally with new weights., Re-score a trader dict using local updated scoring weights., rescore_trader() (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.18
Nodes (12): get_news_cache(), _fetch_news_http(), fetch_symbol_news(), _fetch_yfinance_news(), _is_duplicate(), _is_relevant_news(), News Service — fetches per-symbol news via yfinance with caching and sentiment s, Fetch news via direct HTTP to Yahoo Finance API (no yfinance dependency). (+4 more)

### Community 33 - "Community 33"
Cohesion: 0.19
Nodes (7): analyze_portfolio(), get_active_usernames(), Portfolio Engine — analyzes active traders only.  This module has NO discovery l, Extract lowercased usernames from active holdings list., Analyze the active portfolio of copied traders.      Args:         holdings: Lis, Unit tests for backend/ai/portfolio_engine.py., TestPortfolioEngine

### Community 34 - "Community 34"
Cohesion: 0.16
Nodes (6): classify_instrument(), parse_holdings_from_db_positions(), Parse aggregate holdings from the Position table.      Args:         positions:, Classify a symbol as stock, crypto, etf, or other., Tests for backend/monitoring/holding_parser.py., TestHoldingParser

### Community 35 - "Community 35"
Cohesion: 0.18
Nodes (7): explain_exclusion(), explain_recommendation(), Action Planner — builds the dashboard-ready output from all engine results.  Ans, Generate human-readable reasons why a trader was recommended., Format exclusion reasons for display., explain_recommendation and explain_exclusion from action_planner., TestExplainFunctions

### Community 36 - "Community 36"
Cohesion: 0.21
Nodes (6): build_action_plan(), Return a list of constraint warnings for a trader (non-blocking, for display)., Build the complete action plan from all engine outputs.      Args:         portf, summarize_constraints(), Unit tests for backend/ai/action_planner.py., TestActionPlanner

### Community 37 - "Community 37"
Cohesion: 0.26
Nodes (4): is_real_trader(), Pre-filter: verify this is a genuine eToro account with some activity.      This, is_real_trader strict validation tests., TestIsRealTrader

### Community 38 - "Community 38"
Cohesion: 0.21
Nodes (6): calculate_growth_score(), Backward-compat: score a single trader from a raw dict., calculate_growth_score handles missing data without hard-zero., When no return data exists, don't apply hard-zero growth filter., Low return scores low on return but risk adds meaningful points., TestCalculateGrowthScore

### Community 39 - "Community 39"
Cohesion: 0.17
Nodes (11): annualized_return(), consistency_score(), max_drawdown_from_returns(), Shared mathematical utilities for portfolio and trader analytics.  Provides cons, Compute Sharpe-like ratio from a list of periodic returns.      Uses population, Calculate maximum drawdown from a sequence of periodic returns.      Returns the, Calculate consistency of returns. Higher is more consistent.      Uses the ratio, Calculate the percentage of positive returns. (+3 more)

### Community 40 - "Community 40"
Cohesion: 0.18
Nodes (11): Session, get_db(), init_db(), Database session management and FastAPI dependency injection.  Critical: DATABAS, FastAPI dependency: yields a database session., Initialize database tables and verify connectivity.      Calls create_tables (sa, create_tables(), get_engine() (+3 more)

### Community 41 - "Community 41"
Cohesion: 0.26
Nodes (11): Session, EtoroScrapedStats, Scraped stats from eToro trader profile Stats tab — 12-month rolling values., EtoroScrapedStats, get_scraped_stats(), eToro Stats Scraper — ingests live Stats Tab metrics into etoro_scraped_stats. R, Validate yearly max drawdown before DB write.      Rejects values > 99 (lifetime, Insert or update scraped stats for a trader.      Uses SQLAlchemy merge() for cr (+3 more)

### Community 42 - "Community 42"
Cohesion: 0.29
Nodes (4): _compute_confidence(), Backward-compat: compute confidence from raw dict., _compute_confidence measures data completeness., TestComputeConfidence

### Community 43 - "Community 43"
Cohesion: 0.29
Nodes (4): build_watchlist_summary(), Watchlist Summary — produces a portfolio-level summary of all trader health resu, Tests for backend/monitoring/watchlist_summary.py., TestWatchlistSummary

### Community 44 - "Community 44"
Cohesion: 0.22
Nodes (5): Tests for scoring engine, automation engine state, and market data discovery. Co, rank_candidates handles constraint checks., _has_return_data detects actual vs default return values., TestHasReturnData, TestRankCandidates

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (3): _has_return_data(), Backward-compat: check return data from raw dict., TestBackwardCompatScoringEngine

### Community 46 - "Community 46"
Cohesion: 0.38
Nodes (4): discover_top_traders(), Discover eligible trader candidates from the eToro search API.      Pipeline:, discover_top_traders uses multi-source strategy with fallback., TestDiscoverTopTraders

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (6): buildCommand, framework, installCommand, outputDirectory, rewrites, version

### Community 48 - "Community 48"
Cohesion: 0.33
Nodes (5): deduplicate_active(), Discovery pool — rotating seed list of verified real eToro traders.  Since the e, Select a random subset of traders from the seed pool.      Args:         target:, Remove traders that are already in the active portfolio., select_traders()

### Community 49 - "Community 49"
Cohesion: 0.40
Nodes (6): Backend API, Docker Compose Configuration, Frontend, Telegram Bot, Frontend Index, Frontend Main

## Knowledge Gaps
- **87 isolated node(s):** `Session`, `Session`, `T`, `name`, `version` (+82 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Portfolio` connect `Community 7` to `Community 0`, `Community 1`, `Community 33`, `Community 3`, `Community 36`, `Community 37`, `Community 6`, `Community 9`, `Community 12`, `Community 13`, `Community 14`, `Community 15`, `Community 20`, `Community 28`, `Community 29`, `Community 30`?**
  _High betweenness centrality (0.300) - this node is a cross-community bridge._
- **Why does `EToroAPIClient` connect `Community 3` to `Community 18`, `Community 28`, `Community 46`, `Community 7`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `calculate_growth_score()` connect `Community 8` to `Community 38`, `Community 15`, `Community 17`, `Community 18`, `Community 22`, `Community 31`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `TelegramBot` (e.g. with `Session` and `CopiedTraderCreate`) actually correct?**
  _`TelegramBot` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `Portfolio` (e.g. with `AlertEngine` and `Session`) actually correct?**
  _`Portfolio` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `TraderProfile` (e.g. with `TraderProfile` and `TraderProfile`) actually correct?**
  _`TraderProfile` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `EToroAPIClient` (e.g. with `EToroAPIClient` and `CopiedTrader`) actually correct?**
  _`EToroAPIClient` has 5 INFERRED edges - model-reasoned connections that need verification._