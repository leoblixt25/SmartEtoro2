# CopyVault — System Context Document

> **Single source of truth** for all architecture decisions, data formulas, automation flows, and integration contracts. Every engineer must read this before modifying any core logic.

---

## 1. Application Overview & Purpose

**CopyVault** is an intelligence and automation layer built on top of eToro copy-trading accounts. It is **not** a standalone trading platform — it reads portfolio data from the public eToro API and executes actions (close mirrors, change allocations, pause copies) on behalf of the user.

### Primary Goals

- **Accurate Portfolio Tracking** — Sync eToro portfolio data every 5 minutes, compute true Total Value using the defined formula (see §3).
- **Real Allocation Calculation** — Compute per-trader allocation % as a proportion of total portfolio equity.
- **24/7 Automation** — Evaluate risk-management rules (Take-Profit, Rebalance, Drawdown protection) every 10 minutes. Rules can auto-execute or require Telegram approval.
- **AI Market Scout** — Every 6 hours, Gemini Pro cross-references trader holdings against Yahoo Finance news headlines to flag toxic assets and recommend trader swaps. Never auto-executes — only alerts via Telegram with a `/swap` command for manual approval.
- **Telegram Monitoring & Control** — Query portfolio status, approve pending actions, trigger syncs, and emergency-stop all rules via a webhook-based Telegram bot.

### Non-Goals

- No currency conversion — all values use the raw API currency (USD or EUR).
- No user registration — single-user system hardcoded to `portfolio_id=1`.
- No real-time streaming — data is polled on a schedule.

---

## 2. Tech Stack & Architecture

### Backend

| Component | Technology |
|-----------|-----------|
| Framework | **FastAPI** (Python 3.14) |
| ASGI Server | **Uvicorn** |
| HTTP Client | **httpx** (AsyncClient) |
| Database | **SQLite** via **SQLAlchemy 2.0** |
| Scheduler | **APScheduler** (`AsyncIOScheduler`) |
| AI (Analysis) | **Anthropic Claude** (`claude-sonnet-4-20250514`) |
| AI (Scout) | **Google Gemini Pro** (`gemini-1.5-pro`) via `google-generativeai` |
| Telegram | **python-telegram-bot** (raw `Bot` class only — no `Application` due to `__slots__` bug on Python 3.14) |

### Frontend

| Component | Technology |
|-----------|-----------|
| Framework | **React 18** via **Vite 5** |
| Routing | **react-router-dom v6** |
| HTTP | **axios** (plus raw `fetch()` in a few places) |
| Charts | **Recharts** |
| Icons | **lucide-react** |
| CSS | **Tailwind CSS 3.4** (dark-first, `class` mode) |
| Fonts | DM Serif Display (headings), DM Sans (body), JetBrains Mono (code) |
| Dev Port | **3000** (proxies `/api/*` → `localhost:8000`) |
| Prod URL | `https://smart-etoro2.vercel.app` |

### Deployment

| Service | Provider | URL |
|---------|----------|-----|
| Backend | **Render** (free tier) | `https://smartetoro2.onrender.com` |
| Frontend | **Vercel** | `https://smart-etoro2.vercel.app` |
| DB | Render (ephemeral SQLite file) | Not persisted across restarts |

**Render free-tier caveat:** The service spins down after 15 min of inactivity. CopyVault keeps it alive by:
1. A scheduler job that pings `{RENDER_EXTERNAL_URL}/health` every **4 minutes** (§5).
2. (Recommended) An external **UptimeRobot** monitor hitting `/health` every 5 min.

### Frontend → Backend Connection

```js
// api.js — base URL resolution
export const API_URL = import.meta.env.VITE_API_URL ||
  (import.meta.env.MODE === 'production'
    ? 'https://smartetoro2.onrender.com'
    : 'http://localhost:8000')
```

In development, Vite proxies `/api/*` → `localhost:8000`. In production, the frontend calls `https://smartetoro2.onrender.com/api/*` directly.

---

## 3. Core Data & eToro Synchronization Logic

### 3.1 eToro API Endpoint

**Read endpoint:** `GET https://public-api.etoro.com/api/v1/trading/info/{env}/pnl`

- `env = "demo"` when `portfolio.is_simulation == True`
- `env = "real"` when `portfolio.is_simulation == False`

**Execution endpoints** (all `POST`):

| Action | Endpoint | Body |
|--------|----------|------|
| Close mirror | `.../mirrors/{mirrorId}/close` | `{"mirrorId": id}` |
| Change amount | `.../mirrors/{mirrorId}/change-amount` | `{"mirrorId": id, "amount": new_amount}` |
| Pause mirror | `.../mirrors/{mirrorId}/pause` | `{"mirrorId": id}` |
| Unpause mirror | `.../mirrors/{mirrorId}/unpause` | `{"mirrorId": id}` |

**Auth headers** (same for all endpoints):

```
x-api-key:  <ETORO_API_SECRET>    (Public API Key, alphanumeric)
x-user-key: <ETORO_API_KEY>       (JWT token, starts with "eyJ")
x-request-id: <UUID4>
Content-Type: application/json
```

### 3.2 Data Mapping Rules — ⚠️ CRITICAL — DO NOT ALTER

These formulas are the result of extensive debugging against live API responses. Changing them without explicit approval will break all portfolio and trader calculations.

#### Total Value Formula

```python
invested       = sum(positions[].amount) + sum(mirrors[].initialInvestment)
unrealized_pnl = sum(positions[].unrealizedPnL.pnL) + sum(mirrors[].positions[].unrealizedPnL.pnL)
realized_pnl   = sum(mirrors[].closedPositionsNetProfit)
available_cash = clientPortfolio.credit

Total Value = invested + realized_pnl + unrealized_pnl + available_cash
```

**Key insight:** `mirrors[].availableAmount` is **never** used in Total Value. It represents withdrawable cash and would double-count realized PnL if added.

#### Per-Trader Allocation % Formula

```python
mirror_equity = initialInvestment + closedPositionsNetProfit + unrealizedPnL

allocation_pct = (mirror_equity / Total Value) * 100
```

Where `Total Value` is computed exactly as above.

#### Per-Trader PnL % Formula

```python
total_pnl = closedPositionsNetProfit + unrealizedPnL

total_return_pct = (total_pnl / initialInvestment) * 100
```

#### Currency Rule

```python
currency = "EUR" if clientPortfolio.accountCurrencyId == 2 else "USD"
```

- `accountCurrencyId == 1` → USD (`$`)
- `accountCurrencyId == 2` → EUR (`€`)
- No arbitrary EUR/USD conversion is ever applied. The frontend renders `$` or `€` dynamically based on the `portfolio.currency` field.

---

## 4. Database Schema

### Core Tables

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `portfolios` | `id`, `total_value`, `invested_amount`, `available_cash`, `unrealized_pnl`, `realized_pnl`, `daily_pnl`, `weekly_pnl`, `monthly_pnl`, `health_score`, `currency`, `is_simulation` | Single portfolio (id=1) |
| `copied_traders` | `id`, `portfolio_id`, `trader_username`, `allocation_pct`, `total_return_pct`, `risk_score`, `risk_classification`, `is_active`, `is_paused` | Per-trader copy-trade data |
| `positions` | `id`, `portfolio_id`, `instrument`, `amount`, `unrealized_pnl`, `is_open` | Direct stock positions |
| `portfolio_snapshots` | `id`, `portfolio_id`, `total_value`, `daily_pnl`, `health_score`, `recorded_at` | Daily perf snapshot |

### Automation Tables

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `automation_rules` | `id`, `portfolio_id`, `rule_type`, `status` (enabled/disabled/paused), `threshold`, `cooldown_hours`, `last_triggered`, `trigger_count`, `requires_approval`, `config` (JSON) | Rule definitions |
| `automation_logs` | `id`, `rule_id`, `portfolio_id`, `action_type`, `description`, `was_simulated`, `was_approved`, `was_reversed`, `triggered_at` | Audit trail |
| `alerts` | `id`, `portfolio_id`, `alert_type`, `title`, `message`, `severity`, `is_read`, `was_sent_telegram` | User notifications + pending approvals |
| `risk_settings` | `id`, `portfolio_id`, `max_portfolio_drawdown_pct`, `max_allocation_per_trader_pct`, `min_traders_for_diversification`, `emergency_drawdown_trigger_pct`, etc. | Risk thresholds |
| `ai_recommendations` | `id`, `portfolio_id`, `recommendation_type`, `title`, `summary`, `confidence`, `risk_level` | AI-suggested actions |
| `app_settings` | `id`, `key` (unique), `value` (JSON) | Key-value settings store |

### Enums

| Enum | Values |
|------|--------|
| `AutomationStatus` | `enabled`, `disabled`, `paused` |
| `RiskClassification` | `conservative`, `balanced`, `aggressive`, `high_risk` |
| `AlertType` | `drawdown`, `profit_milestone`, `volatility`, `trader_risk`, `imbalance`, `automation`, `weekly_summary`, `ai_scout` |

---

## 5. The Automation & Rule Engine (APScheduler)

### 5.1 Scheduler Lifecycle

The scheduler starts in the FastAPI `lifespan` handler and stops on shutdown. It runs **7 jobs**:

| Job | Trigger | Interval | What It Does |
|-----|---------|----------|-------------|
| `_keep_alive_job` | `IntervalTrigger` | **Every 4 min** | Pings `{RENDER_EXTERNAL_URL}/health` to prevent Render spin-down |
| `_etoro_sync_job` | `IntervalTrigger` | **Every 5 min** | Iterates all portfolios, calls `sync_portfolio_data()` (see §3) |
| `_automation_eval_job` | `IntervalTrigger` | **Every 2 min** | Evaluates all enabled automation rules; auto-executes or creates pending alerts |
| `_risk_check_job` | `IntervalTrigger` | **Every 15 min** | Runs `RiskEngine.check_all()` on all portfolios, creates alerts for violations |
| `_daily_snapshot_job` | `CronTrigger` | **Daily at 00:05** | Creates `PortfolioSnapshot` for historical tracking |
| `_weekly_summary_job` | `CronTrigger` | **Sunday at 08:00** | Calls AI engine `generate_weekly_summary()`, saves as Alert |
| `_market_scout_job` | `CronTrigger` | **Every 6h** (at :15) | Fetches market news + eToro discovery, runs Gemini Scout evaluation, saves Alert + Telegram warning if risk detected |

### 5.2 Supported Rule Types

| Rule Type | Name | Default Threshold | Evaluator Logic |
|-----------|------|-------------------|-----------------|
| `take_profit` | Auto Take-Profit | 20% | `unrealized_pnl / invested_amount >= threshold` → propose closing all mirrors |
| `partial_profit_lock` | Partial Profit Lock | 15% | `unrealized_pnl / invested_amount >= threshold` → lock `config.lock_pct`% of gains |
| `rebalance` | Auto Rebalance | 5% drift | `abs(trader.allocation_pct - config.targets[username])` ≥ threshold → adjust amounts |
| `reduce_on_drawdown` | Reduce on Drawdown | 10% | `(invested - total_value) / invested >= threshold` → reduce each mirror by `config.reduce_by_pct`% |
| `pause_copy_on_loss` | Pause Copy on Loss | -10% | Trader `total_return_pct ≤ min_loss_pct` AND `risk_score ≥ 6.5` → pause |
| `reduce_on_volatility` | Reduce on Volatility | 30% | Trader `volatility ≥ threshold` → reduce allocation |

### 5.3 Execution Flow — ⚠️ CRITICAL BUSINESS LOGIC

```
Scheduler fires (every 10 min)
    │
    ▼
Query all rules WHERE status = 'enabled' AND portfolio_id = X
    │
    ▼
For each rule:
    │
    ├── Is rule in cooldown? (last_triggered + cooldown_hours > now)
    │   └── YES → skip this rule
    │
    ├── Evaluate rule condition (threshold check)
    │   └── NOT triggered → skip
    │
    ▼
    A ProposedAction is created
    │
    ▼
    requires_approval?
    │
    ├── TRUE:
    │   └── create_pending_alert() → DB inserts Alert with alert_type="automation"
    │       User sees via Telegram /pending or UI Alerts page
    │       Approval paths:
    │         • Telegram: /approve {rule_id}
    │         • UI: (mark alert → triggers execute)
    │       When approved → execute_etoro_action() called
    │
    └── FALSE:
        └── execute_etoro_action() called immediately
            │
            ├── FAIL → error logged, no cooldown written (retries next cycle)
            └── SUCCESS → log_execution() writes:
                1. AutomationLog with approved_by="auto", success=True
                2. rule.last_triggered = now (starts cooldown)
                3. rule.trigger_count += 1
```

### 5.4 Cooldown Logic

```python
def _in_cooldown(self, rule: AutomationRule) -> bool:
    if not rule.last_triggered:
        return False
    cooldown_ends = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
    return datetime.utcnow() < cooldown_ends
```

**Important:** `last_triggered` is **only written on successful execution**. If an auto-execution fails (API error), the rule re-evaluates on the next cycle (10 min later).

### 5.5 Emergency Stop

`POST /api/portfolios/{pid}/automation/emergency-stop` sets ALL rules to `paused` status. Individual rules can be re-enabled from the UI. This triggers a critical Alert and an `AutomationLog`.

### 5.6 AI Market Scout (Gemini Pro)

The scout runs every 6 hours as part of the scheduler. It does **not** execute trades — only reports findings.

**Data ingestion pipeline:**
1. `market_data.get_current_holdings(db, portfolio_id)` — reads active `CopiedTrader` records with metrics (allocation, return, drawdown, risk score, positions)
2. `market_data.fetch_market_news()` — async HTTP fetch from Yahoo Finance RSS headlines (falls back to market summary)
3. `market_data.discover_top_traders()` — attempts eToro public discovery API (falls back to 5 static candidates)

**Evaluation:**
4. `GeminiScout.evaluate(holdings, news, candidates)` — sends structured prompt to `gemini-1.5-pro` with system instruction to act as Chief Risk Officer. Returns JSON:
   ```json
   {"action_required": bool, "flagged_trader": "username", "reasoning": "...", "recommended_swap": "username"}
   ```

**Outcome:**
- `action_required=false` → `Alert(severity="info")` saved to DB: "✅ AI Scout: All Clear"
- `action_required=true` → `Alert(severity="warning")` saved + Telegram sent with formatted message and `/swap` command. User must type `/swap` manually — never auto-executed.

---

## 6. Telegram Bot Integration

### 6.1 Architecture

- **Raw `telegram.Bot`** class (NOT `telegram.ext.Application`). The `Application` class uses `__slots__` which triggers a CPython name-mangling bug on Python 3.14.
- **Webhook-based** (not long-polling). The webhook endpoint is registered at startup via `Bot.set_webhook(url)`.
- **FastAPI endpoint:** `POST /api/telegram/webhook` — receives updates, calls `bot.process_update()` to dispatch.
- **Authorization:** Only responds to `TELEGRAM_ALLOWED_USER_ID`. All other users are silently ignored (`process_update` returns early).

### 6.2 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | `""` | Bot token from @BotFather (required to enable) |
| `TELEGRAM_ALLOWED_USER_ID` | `None` | Authorized Telegram user ID (required to enable) |
| `TELEGRAM_CHAT_ID` | `=ALLOWED_USER_ID` | Chat ID for outgoing messages (defaults to allowed user) |

**Bot is DISABLED if** `TELEGRAM_BOT_TOKEN` or `TELEGRAM_ALLOWED_USER_ID` is missing.

### 6.3 Command Reference

| Command | Handler | What It Does |
|---------|---------|-------------|
| `/help` | `_cmd_help` | Lists all available commands |
| `/ping` | `_cmd_ping` | Liveness check — returns "✅ CopyVault Bot is active!" |
| `/status` | `_cmd_status` | Quick snapshot: total value, invested, return (abs + %), unrealized/realized PnL, cash, health score, SIM/LIVE mode |
| `/portfolio` | `_cmd_portfolio` | Full breakdown: same as status plus trader count, daily/weekly/monthly PnL |
| `/traders` | `_cmd_traders` | Per-trader: status icon, return %, allocation %, risk score/color, classification |
| `/risk` | `_cmd_risk` | Runs `RiskEngine.check_all()`, shows active violations with severity icons |
| `/alerts` | `_cmd_alerts` | Shows 5 most recent unread alerts |
| `/pending` | `_cmd_pending` | Shows unread alerts with `alert_type == "automation"` (pending approvals) |
| `/approve <rule_id>` | `_cmd_approve` | Re-evaluates rules, matches by rule_id, calls `execute_etoro_action()`, logs with `approved_by="telegram"` |
| `/sync` | `_cmd_sync` | Triggers `EToroSyncService.sync_portfolio_data()`, returns updated value |
| `/pause` | `_cmd_pause` | Calls `automation_engine.emergency_stop()` — pauses ALL rules |
| `/scout` | `_cmd_scout` | Runs Gemini Scout on demand: fetches news + discovery, evaluates holdings, returns result in chat |
| `/swap <old> <new>` | `_cmd_swap` | Executes a trader swap: closes old mirror via eToro API, marks trader inactive in DB, logs as Alert |

### 6.4 Reply Keyboard

Every response includes a persistent reply keyboard (4×2 grid):

```
/status   /traders
/portfolio /risk
/pending   /alerts
/sync      /scout
```

### 6.5 Status Endpoint (for frontend indicator)

`GET /api/telegram/status` returns:

```json
{
  "enabled": true,
  "has_token": true,
  "has_allowed_user": true,
  "has_chat_id": true,
  "webhook_url": "https://smartetoro2.onrender.com/api/telegram/webhook",
  "uptime": "2h15m",
  "last_error": null
}
```

The Settings page polls this every 30s and shows a green/red indicator dot.

### 6.6 Startup Notification

On server start, the bot sends: "🚀 CopyVault Server Started — eToro sync is active. Use the menu below or tap /help for commands."

### 6.7 Scout Alert Flow

When Gemini Scout detects a risk (either from scheduler or manual `/scout`), the bot sends:

```
⚠️ AI Scout Alert

Risk detected in <trader>'s portfolio.

Reasoning: <Gemini's explanation citing news or metrics>

Recommend swapping to: <recommended_trader>

Reply /swap <trader> <recommended_trader> to execute.
```

The `/swap` handler:
1. Validates the old trader exists and is active in DB
2. Calls `execute_close_mirror(mirror_id)` on eToro to close the position
3. Sets `is_active=False`, `is_paused=True`, `paused_reason` on the DB record
4. Logs an Alert with `alert_type=AI_SCOUT`
5. Informs the user that starting the new copy must be done via eToro UI

**Safety rule:** The scout NEVER auto-executes swaps. Every swap requires the user to type `/swap`. This is a hard architectural guard.

---

## 7. Risk Engine

The `RiskEngine` runs 6 checks on every evaluation cycle (every 15 min):

| Check | Threshold | Severity | Alert Type |
|-------|-----------|----------|------------|
| Portfolio drawdown | `max_portfolio_drawdown_pct` (default 20%) | warning/critical | `drawdown` |
| Per-trader allocation limit | `max_allocation_per_trader_pct` (default 30%) | warning | `trader_risk` |
| Diversification minimum | `min_traders_for_diversification` (default 3) | info | `imbalance` |
| Trader risk score ceiling | score ≥ 7.5 (warning), ≥ 9 (critical) | warning/critical | `trader_risk` |
| Emergency protection mode | drawdown ≥ `emergency_drawdown_trigger_pct` (default 15%) | critical | `drawdown` |
| Cooldown compliance | recent loss events in `cooldown_after_loss_hours` (default 48h) | info | `imbalance` |

Each violation creates an **Alert** in the database, visible on the UI Alerts page and via Telegram `/risk`.

---

## 8. API Routes Summary

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/health` | Health check |
| `GET` | `/api/telegram/status` | Telegram bot status |
| `POST` | `/api/telegram/test` | Send test Telegram message |
| `POST` | `/api/telegram/webhook` | Telegram webhook receiver |
| `GET/POST/PATCH` | `/api/portfolios` (+ /{id}) | Portfolio CRUD |
| `GET` | `/api/portfolios/{id}/health` | Portfolio health analysis |
| `GET` | `/api/portfolios/{id}/performance` | Performance history (30d) |
| `POST` | `/api/portfolios/{id}/sync` | Trigger eToro sync |
| `GET/POST` | `/api/portfolios/{id}/traders` | List/add copied traders |
| `GET/PATCH` | `/api/traders/{id}` | Get/update trader |
| `GET` | `/api/traders/{id}/analytics` | Trader deep-dive analysis |
| `POST` | `/api/ai/analyze` | Run AI analysis |
| `GET` | `/api/portfolios/{id}/recommendations` | AI recommendations |
| `GET/POST` | `/api/portfolios/{id}/automation/rules` | List/create rules |
| `POST` | `/api/portfolios/{id}/automation/rules/{rid}/toggle` | Enable/disable rule |
| `DELETE` | `/api/portfolios/{id}/automation/rules/{rid}` | Delete rule |
| `POST` | `/api/portfolios/{id}/automation/emergency-stop` | Emergency stop |
| `GET` | `/api/portfolios/{id}/automation/logs` | Automation audit log |
| `POST` | `/api/automation/logs/{lid}/reverse` | Reverse action |
| `GET` | `/api/portfolios/{id}/risk/check` | Run risk check |
| `GET/PATCH` | `/api/portfolios/{id}/risk/settings` | Risk settings CRUD |
| `GET` | `/api/portfolios/{id}/alerts` | List alerts |
| `POST` | `/api/alerts/{aid}/read` | Mark alert read |
| `GET/POST` | `/api/settings` | App settings CRUD |
| `WS` | `/ws/{portfolio_id}` | WebSocket live updates |

---

## 9. Environment Variables (Complete)

| Variable | Source | Default | Required | Purpose |
|----------|--------|---------|----------|---------|
| `ALLOWED_ORIGINS` | `main.py` | `http://localhost:3000,https://smart-etoro2.vercel.app` | No | CORS origins |
| `IS_SIMULATION` | `main.py` | `None` | No | Force override simulation mode |
| `ETORO_API_KEY` | `etoro_service.py` | `None` | **Yes** | eToro User Key (JWT) |
| `ETORO_API_SECRET` | `etoro_service.py` | `None` | **Yes** | eToro Public API Key |
| `ETORO_ACCOUNT_ID` | `etoro_service.py` | `""` | No | Account ID |
| `TELEGRAM_BOT_TOKEN` | `telegram_service.py` | `""` | No* | Telegram bot token |
| `TELEGRAM_ALLOWED_USER_ID` | `telegram_service.py` | `None` | No* | Allowed Telegram user |
| `TELEGRAM_CHAT_ID` | `telegram_service.py` | `=ALLOWED_USER_ID` | No | Telegram chat ID |
| `RENDER_EXTERNAL_URL` | `telegram_service.py`, `scheduler.py` | `http://localhost:8000` | No | Base URL for webhook/keep-alive |
| `ANTHROPIC_API_KEY` | `analysis_engine.py` | `None` | No | Claude API key |
| `GEMINI_API_KEY` | `gemini_scout.py` | `None` | No\*\* | Google Gemini API key for AI Market Scout |
| `DATABASE_URL` | `connection.py` | `sqlite:///./etoro_platform.db` | No | SQLAlchemy DB URL |
| `APP_ENV` | `dev_routes.py` | `development` | No | Blocks dev routes in production |

\* Required for Telegram to be enabled.
\*\* Required for AI Market Scout to be enabled.

---

## 10. Key Architectural Decisions (ADRs)

### ADR-001: Render Env Vars for Secrets

**Decision:** All API credentials (`ETORO_API_KEY`, `ETORO_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) are stored as Render environment variables, not in the database via the Settings UI.

**Rationale:** Secrets stored in the DB would be lost on SQLite file reset and would require re-entry on every deploy. Env vars persist across redeploys and are not exposed client-side.

**Frontend consequence:** The Settings page shows credential fields but saving them via `POST /api/settings` writes to the `app_settings` table, **not** env vars. The actual credentials used at runtime are always the env vars.

### ADR-002: No Currency Conversion

**Decision:** All values use the raw API currency (USD or EUR as indicated by `accountCurrencyId`). No arbitrary exchange rate is applied.

**Rationale:** eToro's API returns multi-currency data. Applying a conversion would introduce inaccuracy. The frontend dynamically shows `$` or `€` based on `portfolio.currency`.

### ADR-003: Raw Telegram Bot (No Application)

**Decision:** Use `telegram.Bot` directly instead of `telegram.ext.Application`.

**Rationale:** Python 3.14 introduced a CPython change that breaks `__slots__` name-mangling in `telegram.ext.Application`. Raw `Bot` class is unaffected. Webhook dispatch is handled manually via `Update.de_json()` + `process_update()`.

### ADR-004: Webhook-Based Telegram (Not Polling)

**Decision:** Use webhooks tied to a FastAPI endpoint (`POST /api/telegram/webhook`), not long-polling with `Updater`.

**Rationale:** Long-polling requires a background thread that conflicts with FastAPI's async event loop on Render. Webhooks are purely event-driven.

### ADR-005: Cooldown Only on Success

**Decision:** `rule.last_triggered` is only updated when `execute_etoro_action()` succeeds.

**Rationale:** If an API call fails (network error, eToro downtime), the rule should retry on the next eval cycle rather than waiting out a cooldown.

### ADR-006: Scout Never Auto-Executes

**Decision:** The AI Market Scout (Gemini) is strictly read-only. It evaluates holdings against news and returns a recommendation, but **never** calls any eToro execution endpoint automatically.

**Rationale:** AI models can hallucinate or misinterpret news context. A false-positive swap could crystallize losses. The `/swap` command requires explicit human confirmation via Telegram. This is a hard architectural guard — no code path exists where the scout triggers an eToro mutation.

---

## 11. Frontend Pages & Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/` | `Dashboard` | Main overview: stat cards, growth chart, allocation donut, PnL breakdown, AI recs |
| `/traders` | `Traders` | Trader cards, radar charts, analytics, pause/resume |
| `/performance` | `Performance` | Historical charts (7D/30D/90D), statistics table |
| `/risk` | `RiskPage` | Risk violations, severity counts, slider-based settings editor |
| `/automation` | `Automation` | Rule cards with toggle/delete, add-rule modal, audit log, emergency stop |
| `/alerts` | `Alerts` | Alert list with type/severity filtering, mark-read, mark-all-read |
| `/settings` | `Settings` | eToro API credentials, Telegram bot status indicator + test, simulation toggle |

---

## 12. Recent Bug Fixes & Their Impact

| Fix | File | Impact |
|-----|------|--------|
| Total Value formula: removed `mirrors_available` from `total_invested` | `etoro_service.py:_extract_summary` | Prevented double-counting realized PnL. Total Value now: `invested + realized_pnl + unrealized_pnl + credit` |
| Allocation % formula: `(initialInvestment + closedPositionsNetProfit + unrealizedPnL) / Total Value * 100` | `etoro_service.py:_extract_traders` | Changed from using `equity` to `mirror_equity` for correct per-trader weight |
| `_reply` recursion bug: called `self._reply` instead of `update.message.reply_text` | `telegram_service.py:_reply` | Fixed all Telegram commands — were crashing with infinite recursion |
| Removed local `telegram/` directory shadowing pip package | (directory delete) | Deploy was failing because `import telegram` resolved to local dir instead of installed package |
| Replaced `Application` with raw `Bot` | `telegram_service.py` | Fixed `__slots__` crash on Python 3.14 deployment |
| Moved `formatCurrency` out of JSX | `Dashboard.jsx` | Fixed invalid React (function defined inside JSX expression) |
| Replaced duplicate Monthly PnL with Weekly PnL | `Dashboard.jsx` | Dashboard was showing Monthly PnL twice instead of Weekly |
| Removed Anthropic mock-data fallback | `analysis_engine.py:_call_claude` | API failures now raise exceptions instead of silently returning fake "AI Analysis Unavailable" recommendations |

---

## 13. Glossary

| Term | Definition |
|------|-----------|
| Mirror | A copy-trade relationship on eToro. Each mirror tracks a copied trader's positions. |
| Mirror Equity | `initialInvestment + closedPositionsNetProfit + unrealizedPnL` (per mirror). |
| Total Value | `invested + realized_pnl + unrealized_pnl + credit` (portfolio-wide). |
| Allocation % | `(mirror_equity / total_value) * 100`. |
| Cooldown | Period after a successful automation execution during which the rule won't re-trigger. |
| ENABLED/DISABLED/PAUSED | Automation rule statuses. PAUSED is set by emergency stop and cannot be toggled from the UI toggle (must re-enable manually). |
| Pending Approval | An automation rule that triggered but has `requires_approval=True`. An Alert is created and user must approve via Telegram `/approve {rule_id}`. |
| AI Market Scout | Gemini Pro-powered evaluation that cross-references trader holdings against market news to flag risks. Runs every 6 hours or via `/scout`. Never auto-executes. |
| Scout Alert | An `Alert` with `alert_type=AI_SCOUT` created when Gemini detects a risk. Severity is `warning` if action needed, `info` if all clear. |
| Trader Swap | The act of closing a copy-trade mirror on eToro and starting a new one. In CopyVault, initiated via Telegram `/swap <old> <new>` after a Scout recommendation. |
