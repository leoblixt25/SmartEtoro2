# Smart eToro Platform — System Context

> Single source of truth for architecture, data flow, eligibility rules, and integration contracts.
> Read this before modifying core logic.

---

## 1. What It Is

A **smart portfolio assistant** for eToro copy-trading accounts. It monitors your portfolio, analyzes trader health, discovers new eligible traders, and sends alerts via Telegram and a web dashboard. It is **decision support** — it never auto-executes trades.

### What It Is NOT
- Not an auto-copier (no automation engine)
- Not a risk executor (no automated risk actions)
- Not an AI trading bot (no LLM-based analysis)
- Not a trading platform

---

## 2. Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │           Telegram Bot               │
                    │   10 commands, webhook-based         │
                    └──────────┬──────────────────────────┘
                               │
┌──────────┐     ┌─────────────▼─────────────┐     ┌──────────────┐
│ Frontend │────▶│     FastAPI Backend       │────▶│  eToro API   │
│ React 18 │     │  18 routes, WebSocket     │     │  public-api  │
│ Vite 5   │     │  SQLAlchemy, APScheduler  │     │              │
│ Tailwind │     │  httpx async client       │     └──────────────┘
└──────────┘     └──────┬──────────┬─────────┘
                        │          │
               ┌────────▼──┐  ┌───▼──────────┐
               │ PostgreSQL │  │  yfinance    │
               │ (Render)   │  │  (news data) │
               │ SQLite dev │  └──────────────┘
               └────────────┘
```

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (Python 3.12) |
| Database | PostgreSQL (Render) / SQLite (dev) via SQLAlchemy 2.0 |
| Scheduler | APScheduler (AsyncIOScheduler) — 3 jobs |
| Telegram | python-telegram-bot (raw `Bot` class, webhook-based) |
| Frontend | React 18 + Vite 5 + Tailwind CSS 3.4 + Recharts |
| HTTP | httpx (async), yfinance (market news) |

### Deployment

| Service | Provider | URL |
|---------|----------|-----|
| Backend | Render | `https://smartetoro2.onrender.com` |
| Frontend | Vercel | `https://smart-etoro2.vercel.app` |
| Database | Render PostgreSQL | Persisted |

Render spins down after 15 min idle. A scheduler keep-alive pings `/health` every 4 min.

---

## 3. Database Schema

### Tables (7)

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `portfolios` | id, total_value, invested_amount, available_cash, unrealized/realized/daily/weekly/monthly pnl, health_score, currency, is_simulation | Single portfolio (id=1) |
| `copied_traders` | id, portfolio_id, trader_username, trader_id, allocated_amount, allocation_pct, total_return_pct, risk_score, risk_classification, max_drawdown, volatility, sharpe_score, consistency_score, is_active, is_paused | Per-trader copy data |
| `positions` | id, portfolio_id, instrument, direction, amount, open_price, unrealized_pnl, is_open, source (manual/copy) | Direct stock positions |
| `trader_analytics_snapshots` | id, trader_id, risk_score, max_drawdown, monthly_return, sharpe, volatility, recorded_at | Historical snapshots |
| `portfolio_snapshots` | id, portfolio_id, total_value, daily_pnl, health_score, recorded_at | Daily value history |
| `alerts` | id, portfolio_id, alert_type (enum), title, message, severity, is_read, was_sent_telegram | System alerts |
| `app_settings` | id, key (unique), value (JSON), updated_at | Key-value settings |

### Enums

| Enum | Values |
|------|--------|
| `RiskClassification` | conservative, balanced, aggressive, high_risk |
| `AlertType` | drawdown, profit_milestone, volatility, trader_risk, imbalance, automation, weekly_summary, ai_scout, MONITORING |

### Removed Tables (no longer exist)
- `automation_rules` — deleted (no automation engine)
- `automation_logs` — deleted
- `risk_settings` — deleted
- `ai_recommendations` — deleted

---

## 4. Scheduler Jobs (3)

| Job | Interval | What It Does |
|-----|----------|-------------|
| `keep_alive` | Every 4 min | Pings `/health` to prevent Render spin-down |
| `etoro_sync` | Every 5 min | Syncs portfolio data from eToro API, updates DB |
| `trader_monitor` | Every 4 hours | Runs trader health pipeline (news + holdings → signals) |

### Removed Jobs
- `automation_eval` (was every 2 min) — no automation engine
- `risk_check` (was every 15 min) — no risk engine
- `daily_snapshot` (was daily) — removed as unused
- `weekly_summary` (was weekly) — removed
- `market_scout` (was every 6h) — removed with AI scout

---

## 5. AI Decision Pipeline

The deterministic pipeline runs on demand (Telegram `/overview`, frontend Dashboard, /discovery). It NEVER uses LLMs — all scoring is formulaic.

```
discover_top_traders()
    │
    ▼
filter_candidates() ←── eligibility_engine.py
    │
    ├── eligible → build_discovery_list() → rank_candidates() → scored
    │
    └── excluded → grouped by reason
```

### 5.1 Data Sources

Candidates come from:
1. **Primary**: `EToroAPIClient.discover_candidates()` — fetches each candidate from:
   - `tradeinfo` endpoint (confidence=1.0) — authoritative
   - Fallback: `portfolio/live` (confidence=0.7)
   - Fallback: `gain` (confidence=0.5)
   - Fallback: `daily-gain` (confidence=0.3)
2. **Static fallback** (`_default_trader_candidates()`) — 8 hardcoded traders, used when ALL API endpoints fail. These have no `source` field and are rejected by eligibility.

### 5.2 Eligibility Engine (`backend/ai/eligibility_engine.py`)

A trader is eligible ONLY if ALL checks pass:

| Step | Check | Function | Rejection Reason |
|------|-------|----------|-----------------|
| 1 | Not already copied | `is_already_copied()` | already_copied |
| 2 | Copy available | `is_copy_available()` | copy_not_available, trader_blocked, trader_paused, trader_restricted |
| 3 | Budget | `passes_budget()` | missing_min_copy, insufficient_capital |
| 4 | Risk score ≤ 9 | `passes_risk()` | risk_score N exceeds 9 |
| 5 | Has substance | `has_substance()` | no_holdings, no_positions, zero_portfolio_size, no_valid_data, invalid_source |
| 6 | Reliable data | `has_reliable_data()` | no_valid_return_data, no_return_data, low_confidence, no_return_metrics |

**Key rules:**
- `min_copy_amount` must be known (no default to $200) — if missing, reject with `missing_min_copy`
- Traders with ALL zero return are rejected regardless of source (even tradeinfo)
- Unknown/fallback/default sources (`source` missing or set to `fallback`/`default`/`unknown`) are always rejected
- Sources from API fallback endpoints (`portfolio_live` conf=0.7, `gain` conf=0.5, `daily_gain` conf=0.3) are rejected by `has_reliable_data` (confidence < 0.8)

### 5.3 Scoring Engine (`backend/ai/scoring_engine.py`)

Growth Score (0–100) formula:

| Component | Weight | Normalization |
|-----------|--------|-------------|
| 12M Return | 35% | `min(100, r12 × 5)` |
| 6M Return | 25% | `min(100, r6 × 8)` |
| Risk (inverted) | 15% | `min(100, (10 - risk) × 12.5)` |
| Max Drawdown (inverted) | 15% | `min(100, 100 - dd × 4)` |
| Consistency | 10% | from consistency_score, sharpe, or volatility |

Penalties:
- Risk > 7 → -30 pts
- Max Drawdown > 25% → -20 pts
- 12M return < 10% AND has return data → score = 0 (growth filter)

Delta scoring: candidates are ranked by `score - weakest_holding_score` to show swap value.

### 5.4 Action Planner (`backend/ai/action_planner.py`)

Builds a structured plan with:
- **Active portfolio** — scored current holdings
- **Discovery** — ranked eligible candidates (score > 0 only)
- **Excluded** — grouped by reason
- **Recommendations** — recommended swap (weakest → best discovery if better), equal-weight plan
- **Summary** — formatted display string for Telegram

### 5.5 Alert Engine (`backend/ai/alert_engine.py`)

Stateful singleton that tracks previous pipeline results per portfolio. Fires alerts only on state changes:

| Alert Type | Fires When |
|-----------|-----------|
| `new_eligible_trader` | A new trader appears in eligible candidates |
| `trader_became_risky` | A holding's score drops significantly |
| `overconcentration` | Single trader allocation exceeds threshold |
| `swap_opportunity` | A discovery candidate scores higher than weakest holding |
| `trader_excluded` | A previously eligible trader is now excluded |

---

## 6. Monitoring Pipeline (`backend/monitoring/`)

Runs every 4 hours via `trader_monitor` scheduler job. Completely separate from the AI Decision Pipeline.

### Flow
```
trader_health_engine.analyze_trader()
    │
    ├── 1. Fetch holdings via EToroAPI (mirrors) or DB (Position table)
    ├── 2. Parse symbols from holdings
    ├── 3. Fetch news for symbols (yfinance)
    ├── 4. Compute health signals (holdings_health, news_sentiment, performance, risk)
    └── 5. Return HealthReport with overall_score, signals, recommendations
```

### Components

| Module | Responsibility |
|--------|---------------|
| `holding_parser.py` | Parse trader holdings from eToro mirrors or DB positions |
| `news_service.py` | Fetch + aggregate news sentiment per symbol via yfinance |
| `news_cache.py` | LRU cache for news results (avoids repeated API calls) |
| `trader_health_engine.py` | Core analysis: score performance, risk, holdings health, news sentiment |
| `monitor_state.py` | Tracks previous health signals per trader, fires alerts on change |
| `watchlist_summary.py` | Aggregates all trader results, sorts by signal, generates summary |
| `orchestrator.py` | Runs the full pipeline: iterate active traders → analyze → summarize → alert |

### Health Signals

- `positive` / `neutral` / `negative` based on composite analysis
- Alerts only fire when signal CHANGES (e.g., `hold_to_reduce` or `hold_to_increase`)

---

## 7. Telegram Bot

### Architecture
- Raw `telegram.Bot` class (NOT `telegram.ext.Application`)
- Webhook-based: `POST /api/telegram/webhook`
- Registered at startup in FastAPI `lifespan`
- Only responds to `TELEGRAM_ALLOWED_USER_ID`

### Commands (10)

| Command | What It Does |
|---------|-------------|
| `/start` | Welcome message with menu keyboard |
| `/status` | Quick portfolio snapshot: value, PnL, health |
| `/overview` | Full dashboard: value, traders, alerts summary |
| `/active` | Active traders: allocation, return, risk |
| `/discovery` | New eligible traders from the AI pipeline |
| `/health` | Per-trader health analysis |
| `/alerts` | Latest unread alerts |
| `/watchlist` | Watchlist summary from monitoring pipeline |
| `/settings` | Bot configuration status |
| `/help` | List all commands |

---

## 8. API Routes (18)

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/health` | Health check |
| `GET` | `/api/telegram/status` | Telegram bot status |
| `POST` | `/api/telegram/test` | Send test message |
| `POST` | `/api/telegram/webhook` | Telegram webhook |
| `GET` | `/api/portfolios` | List portfolios |
| `POST` | `/api/portfolios` | Create portfolio |
| `GET` | `/api/portfolios/{id}` | Get portfolio |
| `PATCH` | `/api/portfolios/{id}` | Update portfolio |
| `GET` | `/api/portfolios/{id}/overview` | Portfolio overview (aggregated) |
| `GET` | `/api/portfolios/{id}/active-traders` | Active traders list |
| `GET` | `/api/portfolios/{id}/discovery` | Eligible new traders |
| `GET` | `/api/portfolios/{id}/dashboard` | Full dashboard data |
| `GET` | `/api/portfolios/{id}/alerts` | List alerts |
| `GET` | `/api/portfolios/{id}/alerts/summary` | Alert counts by severity |
| `POST` | `/api/alerts/{id}/read` | Mark alert read |
| `POST` | `/api/alerts/read-all` | Mark all alerts read |
| `GET` | `/api/portfolios/{id}/traders` | List copied traders |
| `POST` | `/api/portfolios/{id}/traders` | Add copied trader |
| `GET` | `/api/traders/{id}` | Get trader |
| `PATCH` | `/api/traders/{id}` | Update trader |
| `GET/POST` | `/api/settings` | App settings CRUD |
| `WS` | `/ws/{portfolio_id}` | WebSocket live updates |

### Removed Routes
- All automation routes (rules CRUD, toggle, emergency-stop, logs, reverse)
- All risk routes (check, settings)
- AI analysis and recommendations
- Performance history, trader analytics
- Portfolio health (merged into dashboard)
- Dev seed routes
- Reverse log

---

## 9. Frontend Pages (6)

| Route | Page | What It Shows |
|-------|------|-------------|
| `/` | Overview | Portfolio dashboard: stat cards, health score, active traders summary, discovery preview, recent alerts |
| `/active` | ActiveTraders | Full trader list with allocation %, return %, risk score/color |
| `/discovery` | Discovery | Eligible trader scan results with scores and deltas |
| `/health` | Health | Per-trader health cards with performance/risk/drawdown |
| `/alerts` | Alerts | Filterable alert list (severity, type), mark-read, mark-all-read |
| `/settings` | Settings | Minimal settings view |

### Removed Pages
- Dashboard (merged into Overview), Traders, Performance, RiskPage, Automation

---

## 10. Environment Variables

| Variable | Required | Used By | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Yes | `connection.py` | PostgreSQL or SQLite URL |
| `ETORO_API_KEY` | Yes | `etoro_service.py` | eToro User Key (JWT) |
| `ETORO_API_SECRET` | Yes | `etoro_service.py` | eToro Public API Key |
| `ETORO_ACCOUNT_ID` | No | `etoro_service.py` | Account ID override |
| `TELEGRAM_BOT_TOKEN` | No* | `telegram_service.py` | Telegram bot token |
| `TELEGRAM_ALLOWED_USER_ID` | No* | `telegram_service.py` | Authorized Telegram user |
| `TELEGRAM_CHAT_ID` | No | `telegram_service.py` | Chat ID for outbound msgs |
| `RENDER_EXTERNAL_URL` | No | telegram, scheduler | Base URL for webhook |
| `APP_ENV` | No | `main.py` | "production" or "development" |
| `ALLOWED_ORIGINS` | No | `main.py` | CORS origins |
| `CANDIDATE_TRADERS` | No | `market_data.py` | Comma-separated override list |

\* Required for Telegram to be enabled.

### Removed Variables
- `ANTHROPIC_API_KEY` — no Claude integration
- `GEMINI_API_KEY` — no Gemini integration  
- `GROQ_API_KEY` — no Groq integration
- `IS_SIMULATION` — no longer read

---

## 11. eToro Sync (`backend/services/etoro_service.py`)

### Data Mapping

```
Total Value = invested + realized_pnl + unrealized_pnl + available_cash

Where:
  invested       = sum(positions[].amount) + sum(mirrors[].initialInvestment)
  unrealized_pnl = sum(positions[].unrealizedPnL) + sum(mirrors[].positions[].unrealizedPnL)
  realized_pnl   = sum(mirrors[].closedPositionsNetProfit)
  available_cash = clientPortfolio.credit
```

### Per-Trader Metrics

```
mirror_equity = initialInvestment + closedPositionsNetProfit + unrealizedPnL
allocation_pct = (mirror_equity / Total Value) * 100
total_return_pct = ((closedPositionsNetProfit + unrealizedPnL) / initialInvestment) * 100
```

### Auth Headers
```
x-api-key:  <ETORO_API_SECRET>
x-user-key: <ETORO_API_KEY>
x-request-id: <UUID4>
Content-Type: application/json
```

---

## 12. Eligibility Rules Summary

A trader is **eligible for Discovery** if and only if:

1. **Not already copied** — username not in active portfolio (case-insensitive)
2. **Copy available** — `is_copiable` is True, not blocked/paused/restricted
3. **Budget OK** — `min_copy_amount` is known (> 0) and ≤ available balance
4. **Risk OK** — `risk_score` ≤ 9.0
5. **Has substance** — has non-zero return data, valid source (not fallback/default/unknown), and any available holdings/positions/portfolio_size are not empty
6. **Reliable data** — source confidence ≥ 0.8 (or tradeinfo=1.0), non-zero return

### Rejection Examples

| Scenario | Reasons |
|----------|---------|
| SmartMoneyFX (fallback, no source) | `no_valid_data, invalid_source=unknown` |
| SmartMoneyFX (tradeinfo, 0% return) | `no_valid_data` |
| SmartMoneyFX (API, low confidence) | `no_valid_return_data` |
| Copied trader in active portfolio | `already_copied` |
| Trader with unknown min_copy | `missing_min_copy` |
| Blocked/paused trader | `copy_not_available`, `trader_blocked`, etc. |
| Risk > 9 | `risk_score 9.5 exceeds 9` |

---

## 13. Test Suite

144 tests across 3 files:

| File | Tests | Area |
|------|-------|------|
| `tests/test_new_engines.py` | ~75 | Eligibility, Portfolio, Discovery, Scoring, ActionPlanner, AlertEngine, Orchestrator |
| `tests/test_engine_pipeline.py` | ~33 | Confidence, growth filter, source validation, default traders, filter_candidates |
| `tests/test_monitoring.py` | ~36 | News cache, news service, holding parser, health engine, watchlist summary, monitoring state |

Run: `python -m pytest tests/`

---

## 14. Key Architecture Decisions

- **No auto-execution**: The bot is a decision assistant. It neither executes copy-trades nor modifies allocations.
- **No AI/LLM**: All analysis is deterministic (formulaic scoring). No Claude, Gemini, or Groq integration.
- **Fail closed**: Unknown `min_copy_amount` → rejected. Unknown source → rejected. Zero return → rejected.
- **Strict eligibility**: All 6 checks must pass. A single failure excludes the trader from Discovery.
- **Telegram is monitoring-only**: 10 commands, all read-only. No approval or execution commands.
- **Scheduler is lean**: 3 jobs instead of 8. No automation eval, risk check, daily/weekly snapshots, or market scout.
- **Confidence-gated sources**: tradeinfo=1.0 (authoritative), portfolio_live=0.7, gain=0.5, daily_gain=0.3. Sources below 0.8 confidence are rejected.
- **Stateful alerts**: AlertEngine and MonitoringState both use in-memory singletons to suppress duplicate alerts.
