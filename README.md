# CopyVault — eToro Portfolio Intelligence Platform

> AI-assisted portfolio management and copy-trading analytics.  
> Built for long-term investors who want transparency, risk control, and intelligent insights.

---

## What This Is

CopyVault is a **conservative, explainable** portfolio management platform for eToro copy-traders. It is **not** a trading bot. It does not execute trades. Every automated action is proposed, logged, and requires your approval.

**Core philosophy:**
- Capital preservation over speculation
- Every recommendation is explained, not just stated
- All automation is reversible and fully audited
- Risk controls cannot be bypassed

---

## Architecture

```
project/
├── backend/               # FastAPI Python backend
│   ├── api/               # Pydantic schemas + validators
│   ├── analytics/         # Trader & portfolio analytics engines
│   ├── ai/                # Claude AI integration
│   ├── automation/        # Rule engine with safeguards
│   ├── risk/              # Mandatory risk enforcement
│   ├── services/          # Data service + background scheduler
│   └── database/          # SQLAlchemy models + connection
│
├── frontend/              # React + Tailwind UI
│   └── src/
│       ├── pages/         # Dashboard, Traders, Performance, Risk, Automation, Alerts
│       ├── components/    # Reusable UI components
│       └── services/      # API client layer
│
├── telegram/              # Telegram bot (monitoring + commands)
├── config/                # Environment configuration
├── docker/                # Dockerfile + docker-compose + nginx
└── tests/                 # Test suite
```

---

## Quick Start

### Option A: Docker (Recommended)

```bash
# 1. Clone and configure
git clone <repo>
cd etoro-platform
cp config/.env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN

# 2. Start all services
cd docker
docker-compose up -d

# 3. Open the dashboard
open http://localhost:3000
```

### Option B: Local Development

**Backend:**
```bash
# Python 3.12+
cd etoro-platform
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp config/.env.example .env      # Edit with your keys

uvicorn backend.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev                       # http://localhost:3000
```

**Telegram Bot (optional):**
```bash
python -m telegram.bot
```

---

## Seed Demo Data

After starting the backend, seed a portfolio with realistic simulation data:

```bash
curl -X POST http://localhost:8000/api/portfolios \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo_user", "is_simulation": true, "total_value": 10000}'

# Returns portfolio ID (e.g. 1), then seed it:
curl -X POST "http://localhost:8000/api/dev/seed/1"
```

---

## API Reference

### Portfolio
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/portfolios`            | Create portfolio |
| GET    | `/api/portfolios/{id}`       | Get portfolio    |
| PATCH  | `/api/portfolios/{id}`       | Update values    |
| GET    | `/api/portfolios/{id}/health` | Health analysis |
| GET    | `/api/portfolios/{id}/performance` | Growth history |

### Traders
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/portfolios/{id}/traders`    | List all traders |
| POST   | `/api/portfolios/{id}/traders`    | Add a trader     |
| GET    | `/api/traders/{id}/analytics`     | Full analysis    |
| PATCH  | `/api/traders/{id}`               | Update trader    |

### AI Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/ai/analyze`                    | Run AI analysis     |
| GET    | `/api/portfolios/{id}/recommendations` | Get recommendations |

### Risk
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/portfolios/{id}/risk/check`    | Run risk check    |
| GET    | `/api/portfolios/{id}/risk/settings` | Get thresholds    |
| PATCH  | `/api/portfolios/{id}/risk/settings` | Update thresholds |

### Automation
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/portfolios/{id}/automation/rules`         | List rules    |
| POST   | `/api/portfolios/{id}/automation/rules`         | Create rule   |
| POST   | `/api/portfolios/{id}/automation/rules/{rid}/toggle` | Enable/disable |
| POST   | `/api/portfolios/{id}/automation/emergency-stop` | Stop all     |
| GET    | `/api/portfolios/{id}/automation/logs`          | Audit trail   |

### Alerts
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/portfolios/{id}/alerts`   | List alerts       |
| POST   | `/api/alerts/{id}/read`         | Mark as read      |

---

## Telegram Commands

Once the bot is running and you've messaged it `/start`:

| Command       | Description                          |
|---------------|--------------------------------------|
| `/status`     | Quick portfolio snapshot             |
| `/portfolio`  | Full portfolio details               |
| `/risk`       | Active risk violations               |
| `/traders`    | Copied traders overview              |
| `/performance`| PnL summary (daily/weekly/monthly)   |
| `/alerts`     | Recent unread alerts                 |
| `/pause`      | Emergency pause all automation       |
| `/resume`     | Instructions to resume (via dashboard)|
| `/help`       | Show command list                    |

---

## Analytics Engine

### Trader Scoring

Each copied trader is scored across 6 dimensions:

| Metric | Weight | Description |
|--------|--------|-------------|
| Consistency | 25% | % of positive return months |
| Max Drawdown | 25% | Lower = better |
| Sharpe-like Score | 20% | Return / volatility ratio |
| Volatility | 15% | Annualized price swings |
| Diversification | 10% | Asset class breadth |
| Trade Frequency | 5% | Penalises HFT-like patterns |

**Risk Classifications:**
- 🟢 **Conservative** — Risk ≤4, Drawdown <10%, Volatility <15%
- 🔵 **Balanced** — Risk ≤6, Drawdown <20%
- 🟡 **Aggressive** — Risk ≤7.5
- 🔴 **High Risk** — Risk >7.5

### Portfolio Health Score

Composite score (0–100) based on:
- Diversification across traders and asset classes
- Concentration risk (HHI-based)
- Current risk exposure level
- Number of active violations

---

## Automation Rules

All rules are **proposals** by default (`requires_approval: true`). They flag conditions but wait for your action.

| Rule | Trigger | Action Proposed |
|------|---------|-----------------|
| Take Profit | Return % ≥ threshold | Close/reduce positions |
| Partial Profit Lock | Return % ≥ threshold | Lock X% of gains |
| Reduce on Drawdown | Drawdown % ≥ threshold | Reduce high-risk exposure |
| Pause Copy on Loss | Return ≤ threshold + high risk | Pause copy relationship |
| Rebalance | Drift from target > threshold | Adjust allocations |
| Reduce on Volatility | Trader volatility ≥ threshold | Reduce allocation |

**Every rule has:**
- Enable / disable toggle
- Configurable threshold
- Cooldown period (default 24h)
- Full audit log entry
- Reverse button (undo)

---

## Risk Safeguards

These run every 15 minutes via the background scheduler:

1. **Portfolio drawdown limit** — Warns at 75%, critical at 100% of threshold
2. **Per-trader max allocation** — Flags over-concentrated positions
3. **Diversification minimum** — Ensures adequate trader spread
4. **Trader risk score monitoring** — Flags scores ≥7.5 (warning) or ≥9 (critical)
5. **Emergency protection** — Auto-pauses all automation at a configurable drawdown level
6. **Loss cooldown** — Prevents reactive actions too soon after a loss

---

## Extending This Platform

### Adding a real eToro data source

When eToro makes their API available, replace `DataService.build_trader_metrics()` in `backend/services/data_service.py` with real API calls. The rest of the system is already structured to receive live data.

### Switching to PostgreSQL

Change `DATABASE_URL` in `.env`:
```
DATABASE_URL=postgresql://user:password@localhost:5432/copyvault
```
No code changes required — SQLAlchemy handles the rest.

### Adding new automation rule types

1. Add rule definition to `RULE_TYPES` in `Automation.jsx`
2. Add evaluator method `_eval_<type>()` in `AutomationEngine`
3. Register it in the `evaluators` dict in `evaluate_rules()`

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (for AI) | Claude API key |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Optional | Your Telegram chat ID |
| `DATABASE_URL` | Optional | Defaults to SQLite |
| `ALLOWED_ORIGINS` | Optional | CORS origins (default: localhost:3000) |
| `DEFAULT_PORTFOLIO_ID` | Optional | Portfolio for Telegram commands |

---

## What This Doesn't Do

By design, CopyVault **never**:
- Executes trades without your explicit approval
- Recommends leverage or margin positions
- Encourages panic selling or revenge trading
- Hides automated actions (full audit trail always)
- Guarantee returns or make price predictions

---

## License

MIT — see LICENSE file.

---

*Built as an MVP. Contributions welcome. Always paper-trade before live use.*
