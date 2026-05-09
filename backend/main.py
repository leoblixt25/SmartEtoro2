"""
eToro Portfolio Platform — FastAPI Application
────────────────────────────────────────────────────────────────────
Main application entry point with all routes, WebSocket, middleware,
and startup/shutdown lifecycle hooks.
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database.connection import init_db, get_db, SessionLocal
from backend.database.models import (
    Portfolio, CopiedTrader, AutomationRule, AutomationLog,
    Alert, AIRecommendation, RiskSettings, AutomationStatus,
    AppSetting
)
from backend.api.schemas import (
    PortfolioCreate, PortfolioResponse, PortfolioUpdate,
    CopiedTraderCreate, CopiedTraderResponse, CopiedTraderUpdate,
    AutomationRuleCreate, AutomationRuleResponse, AutomationLogResponse,
    AlertResponse, AIRecommendationResponse, AIAnalysisRequest,
    RiskSettingsUpdate, RiskSettingsResponse,
    TraderAnalyticsResult, PortfolioHealthResult as PortfolioHealthSchema,
)
from backend.analytics.trader_analytics import TraderAnalyticsEngine, TraderMetrics
from backend.analytics.portfolio_analytics import PortfolioAnalyticsEngine
from backend.ai.analysis_engine import AIAnalysisEngine
from backend.risk.risk_engine import RiskEngine
from backend.automation.automation_engine import AutomationEngine
from backend.services.data_service import DataService
from backend.services.etoro_service import EToroSyncService
from backend.services.scheduler import SchedulerService

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Global engine instances
# ──────────────────────────────────────────────
trader_analytics = TraderAnalyticsEngine()
portfolio_analytics = PortfolioAnalyticsEngine()
ai_engine = AIAnalysisEngine()
risk_engine = RiskEngine()
automation_engine = AutomationEngine()
data_service = DataService()
scheduler = SchedulerService()

# WebSocket connection manager
ws_connections: list[WebSocket] = []


# ──────────────────────────────────────────────
# App lifecycle
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting eToro Portfolio Platform…")
    init_db()

    # Create default portfolio if none exists
    db = SessionLocal()
    try:
        portfolio_count = db.query(Portfolio).count()
        if portfolio_count == 0:
            logger.info("Creating default portfolio...")
            default_portfolio = Portfolio(
                user_id="default_user",
                total_value=10000.0,
                invested_amount=10000.0,
                available_cash=10000.0,
                is_simulation=True
            )
            db.add(default_portfolio)
            db.commit()
            db.refresh(default_portfolio)

            # Create default risk settings
            settings = RiskSettings(portfolio_id=default_portfolio.id)
            db.add(settings)
            db.commit()

            logger.info(
                f"Default portfolio created with ID: {default_portfolio.id}")
        else:
            logger.info(f"Found {portfolio_count} existing portfolio(s)")
    except Exception as e:
        logger.error(f"Error creating default portfolio: {e}")
    finally:
        db.close()

    scheduler.start()
    yield
    scheduler.stop()
    logger.info("Platform shutdown complete.")


app = FastAPI(
    title="eToro Portfolio Platform",
    description="AI-assisted portfolio management and copy-trading analytics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,https://smart-etoro2.vercel.app").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# WebSocket — live updates
# ──────────────────────────────────────────────

@app.websocket("/ws/{portfolio_id}")
async def websocket_endpoint(websocket: WebSocket, portfolio_id: int):
    await websocket.accept()
    ws_connections.append(websocket)
    logger.info(f"WebSocket connected: portfolio {portfolio_id}")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"event": "pong", "data": {}})
    except WebSocketDisconnect:
        ws_connections.remove(websocket)
        logger.info(f"WebSocket disconnected: portfolio {portfolio_id}")


async def broadcast(event: str, data: dict):
    """Broadcast event to all connected WebSocket clients."""
    dead = []
    for ws in ws_connections:
        try:
            await ws.send_json({"event": event, "data": data, "ts": datetime.utcnow().isoformat()})
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_connections.remove(ws)


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.head("/health")
def health_check_head():
    return Response(status_code=status.HTTP_200_OK)


# ──────────────────────────────────────────────
# Portfolio routes
# ──────────────────────────────────────────────

@app.post("/api/portfolios", response_model=PortfolioResponse, status_code=201)
def create_portfolio(payload: PortfolioCreate, db: Session = Depends(get_db)):
    portfolio = Portfolio(**payload.model_dump())
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    # Create default risk settings
    settings = RiskSettings(portfolio_id=portfolio.id)
    db.add(settings)
    db.commit()

    logger.info(
        f"Portfolio created: {portfolio.id} (user={portfolio.user_id})")
    return portfolio


@app.get("/api/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    
    # Force simulation mode if env var is set (overrides database)
    force_sim = os.getenv("IS_SIMULATION")
    if force_sim is not None:
        portfolio.is_simulation = (force_sim.lower() == 'true')
        
    return portfolio


@app.patch("/api/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def update_portfolio(
    portfolio_id: int,
    payload: PortfolioUpdate,
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(portfolio, field, value)
    portfolio.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(portfolio)
    return portfolio


@app.get("/api/portfolios/{portfolio_id}/health")
def get_portfolio_health(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    settings = db.query(RiskSettings).filter(
        RiskSettings.portfolio_id == portfolio_id).first()
    result = portfolio_analytics.analyze(db, portfolio, settings)
    return result


@app.get("/api/portfolios/{portfolio_id}/performance")
def get_performance_history(
    portfolio_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
):
    from backend.database.models import PortfolioSnapshot
    _get_portfolio_or_404(db, portfolio_id)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(PortfolioSnapshot.recorded_at.asc())
        .limit(days)
        .all()
    )
    return [
        {
            "date": s.recorded_at.strftime("%Y-%m-%d"),
            "value": s.total_value,
            "pnl": s.daily_pnl,
            "health": s.health_score,
        }
        for s in snapshots
    ]


@app.post("/api/portfolios/{portfolio_id}/sync")
async def sync_etoro_data(portfolio_id: int, db: Session = Depends(get_db)):
    """Sync real-time data from eToro account."""
    _get_portfolio_or_404(db, portfolio_id)

    from backend.services.etoro_service import EToroSyncService
    sync_service = EToroSyncService()

    success = await sync_service.sync_portfolio_data(db, portfolio_id)

    if success:
        portfolio = db.query(Portfolio).filter(
            Portfolio.id == portfolio_id).first()
        logger.info(f"Portfolio {portfolio_id} synced successfully")
        return {
            "status": "success",
            "message": "Portfolio data synchronized from eToro",
            "portfolio": {
                "id": portfolio.id,
                "total_value": portfolio.total_value,
                "daily_pnl": portfolio.daily_pnl,
                "weekly_pnl": portfolio.weekly_pnl,
                "monthly_pnl": portfolio.monthly_pnl,
                "unrealized_pnl": portfolio.unrealized_pnl,
                "realized_pnl": portfolio.realized_pnl,
                "last_updated": portfolio.last_updated.isoformat(),
            }
        }
    else:
        logger.warning(f"Failed to sync portfolio {portfolio_id}")
        raise HTTPException(
            status_code=503,
            detail="Failed to sync portfolio data from eToro. Check API credentials and network connection.",
        )


# ──────────────────────────────────────────────
# Copied Trader routes
# ──────────────────────────────────────────────

@app.get("/api/portfolios/{portfolio_id}/traders", response_model=List[CopiedTraderResponse])
def list_traders(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return db.query(CopiedTrader).filter(CopiedTrader.portfolio_id == portfolio_id).all()


@app.post("/api/portfolios/{portfolio_id}/traders", response_model=CopiedTraderResponse, status_code=201)
def add_trader(
    portfolio_id: int,
    payload: CopiedTraderCreate,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    trader = CopiedTrader(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(trader)
    db.commit()
    db.refresh(trader)
    return trader


@app.get("/api/traders/{trader_id}/analytics")
def get_trader_analytics(trader_id: int, db: Session = Depends(get_db)):
    trader = db.query(CopiedTrader).filter(
        CopiedTrader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")

    metrics = data_service.build_trader_metrics(trader)
    result = trader_analytics.analyze(metrics)

    # Persist result back to trader
    trader.risk_score = result.risk_score
    trader.risk_classification = result.risk_classification
    trader.max_drawdown = result.max_drawdown
    trader.sharpe_score = result.sharpe_score
    trader.consistency_score = result.consistency_score
    trader.diversification_score = result.diversification_score
    trader.last_analyzed = datetime.utcnow()
    db.commit()

    return result


@app.patch("/api/traders/{trader_id}", response_model=CopiedTraderResponse)
def update_trader(
    trader_id: int,
    payload: CopiedTraderUpdate,
    db: Session = Depends(get_db),
):
    trader = db.query(CopiedTrader).filter(
        CopiedTrader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(trader, field, value)
    trader.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(trader)
    return trader


# ──────────────────────────────────────────────
# AI Analysis routes
# ──────────────────────────────────────────────

@app.post("/api/ai/analyze")
async def run_ai_analysis(payload: AIAnalysisRequest, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, payload.portfolio_id)
    settings = db.query(RiskSettings).filter(
        RiskSettings.portfolio_id == payload.portfolio_id).first()
    health = portfolio_analytics.analyze(db, portfolio, settings)

    if payload.analysis_type == "trader" and payload.trader_id:
        trader = db.query(CopiedTrader).filter(
            CopiedTrader.id == payload.trader_id).first()
        if not trader:
            raise HTTPException(status_code=404, detail="Trader not found")
        result = await ai_engine.analyze_trader(trader)
    elif payload.analysis_type == "weekly":
        traders = db.query(CopiedTrader).filter(
            CopiedTrader.portfolio_id == portfolio.id).all()
        result = await ai_engine.generate_weekly_summary(portfolio, traders)
    else:
        result = await ai_engine.analyze_portfolio(portfolio, health)

    # Persist recommendations
    for rec in result.get("recommendations", []):
        ai_rec = AIRecommendation(
            portfolio_id=portfolio.id,
            recommendation_type=rec.get("type", "general"),
            title=rec.get("title", ""),
            summary=rec.get("summary", ""),
            confidence={"low": 0.3, "medium": 0.6, "high": 0.9}.get(
                rec.get("confidence", "low"), 0.5),
            risk_level=rec.get("risk_level", "low"),
        )
        db.add(ai_rec)
    db.commit()

    return result


@app.get("/api/portfolios/{portfolio_id}/recommendations", response_model=List[AIRecommendationResponse])
def get_recommendations(
    portfolio_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    return (
        db.query(AIRecommendation)
        .filter(AIRecommendation.portfolio_id == portfolio_id)
        .order_by(AIRecommendation.created_at.desc())
        .limit(limit)
        .all()
    )


# ──────────────────────────────────────────────
# Automation routes
# ──────────────────────────────────────────────

@app.get("/api/portfolios/{portfolio_id}/automation/rules", response_model=List[AutomationRuleResponse])
def list_rules(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return db.query(AutomationRule).filter(AutomationRule.portfolio_id == portfolio_id).all()


@app.post("/api/portfolios/{portfolio_id}/automation/rules", response_model=AutomationRuleResponse, status_code=201)
def create_rule(
    portfolio_id: int,
    payload: AutomationRuleCreate,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    rule = AutomationRule(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@app.post("/api/portfolios/{portfolio_id}/automation/rules/{rule_id}/toggle")
def toggle_rule(portfolio_id: int, rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id,
        AutomationRule.portfolio_id == portfolio_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.status = (
        AutomationStatus.ENABLED
        if rule.status == AutomationStatus.DISABLED
        else AutomationStatus.DISABLED
    )
    rule.updated_at = datetime.utcnow()
    db.commit()
    return {"rule_id": rule_id, "new_status": rule.status}


@app.post("/api/portfolios/{portfolio_id}/automation/emergency-stop")
def emergency_stop(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    count = automation_engine.emergency_stop(db, portfolio_id)
    return {"message": f"Emergency stop activated. {count} rules paused.", "rules_paused": count}


@app.get("/api/portfolios/{portfolio_id}/automation/logs", response_model=List[AutomationLogResponse])
def get_automation_logs(
    portfolio_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    return (
        db.query(AutomationLog)
        .filter(AutomationLog.portfolio_id == portfolio_id)
        .order_by(AutomationLog.triggered_at.desc())
        .limit(limit)
        .all()
    )


@app.post("/api/automation/logs/{log_id}/reverse")
def reverse_action(log_id: int, portfolio_id: int, db: Session = Depends(get_db)):
    success = automation_engine.reverse_action(db, log_id, portfolio_id)
    if not success:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return {"message": "Action reversed successfully", "log_id": log_id}


# ──────────────────────────────────────────────
# Risk routes
# ──────────────────────────────────────────────

@app.get("/api/portfolios/{portfolio_id}/risk/check")
def check_risk(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    settings = db.query(RiskSettings).filter(
        RiskSettings.portfolio_id == portfolio_id).first()
    violations = risk_engine.check_all(db, portfolio, settings)
    risk_engine.violations_to_alerts(db, portfolio_id, violations)
    return {"violations": [v.__dict__ for v in violations], "count": len(violations)}


@app.get("/api/portfolios/{portfolio_id}/risk/settings", response_model=RiskSettingsResponse)
def get_risk_settings(portfolio_id: int, db: Session = Depends(get_db)):
    settings = db.query(RiskSettings).filter(
        RiskSettings.portfolio_id == portfolio_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Risk settings not found")
    return settings


@app.patch("/api/portfolios/{portfolio_id}/risk/settings", response_model=RiskSettingsResponse)
def update_risk_settings(
    portfolio_id: int,
    payload: RiskSettingsUpdate,
    db: Session = Depends(get_db),
):
    settings = db.query(RiskSettings).filter(
        RiskSettings.portfolio_id == portfolio_id).first()
    if not settings:
        settings = RiskSettings(portfolio_id=portfolio_id)
        db.add(settings)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(settings, field, value)
    settings.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(settings)
    return settings


# ──────────────────────────────────────────────
# Alerts routes
# ──────────────────────────────────────────────

@app.get("/api/portfolios/{portfolio_id}/alerts", response_model=List[AlertResponse])
def get_alerts(
    portfolio_id: int,
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    q = db.query(Alert).filter(Alert.portfolio_id == portfolio_id)
    if unread_only:
        q = q.filter(Alert.is_read.is_(False))
    return q.order_by(Alert.created_at.desc()).limit(limit).all()


@app.post("/api/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    db.commit()
    return {"message": "Alert marked as read"}


# ──────────────────────────────────────────────
# Settings routes
# ──────────────────────────────────────────────

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    """Get current application settings."""

    def _load_setting(key: str, default=""):
        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting is not None:
            return setting.value
        return os.getenv(key.upper(), default)

    return {
        "etoro_api_key": _load_setting("etoro_api_key"),
        "etoro_api_secret": _load_setting("etoro_api_secret"),
        "etoro_account_id": _load_setting("etoro_account_id"),
        "telegram_bot_token": _load_setting("telegram_bot_token"),
        "telegram_chat_id": _load_setting("telegram_chat_id"),
        "is_simulation": _load_setting("is_simulation", True) is True,
    }


@app.post("/api/settings")
def update_settings(settings: dict, db: Session = Depends(get_db)):
    """Update application settings stored in the database."""

    # Required fields for eToro integration
    required_fields = ["etoro_api_key", "etoro_api_secret"]
    
    # Telegram settings are optional if you don't use notifications
    optional_fields = ["telegram_bot_token", "telegram_chat_id"]

    for field in required_fields:
        if field not in settings or not isinstance(settings[field], str) or not settings[field].strip():
            raise HTTPException(
                status_code=400, detail=f"Required field missing or empty: {field}")


    for field, value in settings.items():
        setting = db.query(AppSetting).filter(AppSetting.key == field).first()
        if setting is None:
            setting = AppSetting(key=field, value=value)
            db.add(setting)
        else:
            setting.value = value

    # Sync simulation mode with default portfolio
    if "is_simulation" in settings:
        portfolio = db.query(Portfolio).first()
        if portfolio:
            portfolio.is_simulation = settings["is_simulation"]

    db.commit()
    logger.info("Settings updated successfully")

    return {"message": "Settings updated successfully", "settings": settings}


# ──────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────

def _get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio
