"""
eToro Portfolio Platform — FastAPI Application
Smart portfolio assistant: monitor, analyze, decide.
"""

from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database.connection import init_db, get_db, SessionLocal
from backend.database.models import (
    Portfolio, CopiedTrader, Alert, AppSetting,
)
from backend.api.schemas import (
    PortfolioCreate, PortfolioResponse, PortfolioUpdate,
    CopiedTraderCreate, CopiedTraderResponse, CopiedTraderUpdate,
    AlertResponse,
)
from backend.services.data_service import DataService
from backend.services.etoro_service import EToroSyncService
from backend.services.scheduler import SchedulerService
from backend.services.telegram_service import TelegramBot
from backend.services.portfolio_service import get_portfolio_overview, get_active_traders
from backend.services.discovery_service import discover_eligible_traders
from backend.services.screener_service import run_screener, get_job
from backend.services.alert_service import get_alerts, mark_alert_read, mark_all_read, get_alert_summary
from backend.services.dashboard_service import build_dashboard_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

data_service = DataService()
scheduler = SchedulerService()
telegram_bot = TelegramBot()
ws_connections: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting eToro Portfolio Platform…")
    init_db()

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
                is_simulation=False,
            )
            db.add(default_portfolio)
            db.commit()
            db.refresh(default_portfolio)
            logger.info(f"Default portfolio created with ID: {default_portfolio.id}")
        else:
            logger.info(f"Found {portfolio_count} existing portfolio(s)")
    except Exception as e:
        logger.error(f"Error creating default portfolio: {e}")
    finally:
        db.close()

    scheduler.start()

    if telegram_bot.enabled:
        try:
            telegram_bot._started_at = datetime.utcnow()
            webhook_url = telegram_bot.webhook_url()
            await telegram_bot._bot.set_webhook(url=webhook_url)
            logger.info(f"Telegram webhook set to {webhook_url}")
            await telegram_bot.setup_commands()
            await telegram_bot.send_message(
                "Smart Portfolio Assistant started.\n\n"
                "Monitoring your copied traders with health analysis, "
                "news tracking, and smart alerts.\n"
                "Use the menu below or tap /help for commands.",
                show_keyboard=True,
            )
        except Exception as e:
            logger.error(f"Telegram webhook setup failed: {e}")

    yield

    scheduler.stop()
    logger.info("Platform shutdown complete.")


app = FastAPI(
    title="eToro Portfolio Platform",
    description="Smart portfolio assistant — monitor, analyze, and decide",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,https://smart-etoro2.vercel.app"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket ─────────────────────────────────


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


async def broadcast(event: str, data: dict):
    dead = []
    for ws in ws_connections:
        try:
            await ws.send_json({
                "event": event, "data": data, "ts": datetime.utcnow().isoformat(),
            })
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_connections.remove(ws)


# ── Health ────────────────────────────────────


@app.get("/")
async def root():
    return {"status": "online", "version": "2.0.0", "product": "portfolio-assistant"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.head("/health")
async def health_check_head():
    return Response(status_code=status.HTTP_200_OK)


# ── Telegram ──────────────────────────────────


@app.get("/api/telegram/status")
def telegram_status():
    return telegram_bot.status


@app.post("/api/telegram/test")
async def telegram_test():
    if not telegram_bot.enabled:
        raise HTTPException(status_code=400, detail="Telegram bot is not enabled.")
    try:
        await telegram_bot.send_message(
            "Test message — Smart Portfolio Assistant is connected.",
            show_keyboard=True,
        )
        return {"status": "ok", "message": "Test message sent successfully"}
    except Exception as e:
        telegram_bot.last_error = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to send test message: {e}")


@app.post(telegram_bot.webhook_path())
async def telegram_webhook(request: Request):
    if telegram_bot.enabled:
        try:
            data = await request.json()
            await telegram_bot.process_update(data)
        except Exception as e:
            logger.error(f"Telegram webhook error: {e}")
    return Response(status_code=200)


# ── Portfolio ─────────────────────────────────


@app.post("/api/portfolios", response_model=PortfolioResponse, status_code=201)
def create_portfolio(payload: PortfolioCreate, db: Session = Depends(get_db)):
    portfolio = Portfolio(**payload.model_dump())
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    logger.info(f"Portfolio created: {portfolio.id} (user={portfolio.user_id})")
    return portfolio


@app.get("/api/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    return _get_portfolio_or_404(db, portfolio_id)


@app.patch("/api/portfolios/{portfolio_id}", response_model=PortfolioResponse)
def update_portfolio(portfolio_id: int, payload: PortfolioUpdate, db: Session = Depends(get_db)):
    portfolio = _get_portfolio_or_404(db, portfolio_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(portfolio, field, value)
    portfolio.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(portfolio)
    return portfolio


@app.post("/api/portfolios/{portfolio_id}/sync")
async def sync_etoro_data(portfolio_id: int, db: Session = Depends(get_db)):
    """Sync real-time data from eToro account."""
    _get_portfolio_or_404(db, portfolio_id)
    sync_service = EToroSyncService()
    success = await sync_service.sync_portfolio_data(db, portfolio_id)
    if success:
        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
        logger.info(f"Portfolio {portfolio_id} synced successfully")
        return {
            "status": "success",
            "message": "Portfolio data synchronized from eToro",
            "portfolio": {
                "id": portfolio.id,
                "total_value": portfolio.total_value,
                "daily_pnl": portfolio.daily_pnl,
                "last_updated": portfolio.last_updated.isoformat() if portfolio.last_updated else None,
            },
        }
    else:
        raise HTTPException(status_code=503, detail="Failed to sync portfolio data from eToro.")


# ── Portfolio Overview / Dashboard ────────────


@app.get("/api/portfolios/{portfolio_id}/overview")
def portfolio_overview(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return get_portfolio_overview(db, portfolio_id)


@app.get("/api/portfolios/{portfolio_id}/active-traders")
def active_traders(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return get_active_traders(db, portfolio_id)


@app.get("/api/portfolios/{portfolio_id}/discovery")
async def discovery(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    eligible, excluded, stats = await discover_eligible_traders(db, portfolio_id)
    return {"eligible": eligible, "excluded": excluded, "stats": stats}


@app.post("/api/portfolios/{portfolio_id}/screener")
async def start_screener(
    portfolio_id: int,
    scan_target: int = 2000,
    top_n: int = 10,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    run_id, initial = await run_screener(portfolio_id, scan_target, top_n)
    return {"run_id": run_id, "progress": initial}


@app.get("/api/screener/{run_id}")
async def screener_progress(run_id: str):
    job = get_job(run_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "Run not found"})
    return {"run_id": run_id, "progress": job}


@app.get("/api/portfolios/{portfolio_id}/dashboard")
async def dashboard(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return await build_dashboard_data(db, portfolio_id)


# ── Copied Traders ────────────────────────────


@app.get("/api/portfolios/{portfolio_id}/traders", response_model=List[CopiedTraderResponse])
def list_traders(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return db.query(CopiedTrader).filter(CopiedTrader.portfolio_id == portfolio_id).all()


@app.post("/api/portfolios/{portfolio_id}/traders", response_model=CopiedTraderResponse, status_code=201)
def add_trader(portfolio_id: int, payload: CopiedTraderCreate, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    trader = CopiedTrader(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(trader)
    db.commit()
    db.refresh(trader)
    return trader


@app.patch("/api/traders/{trader_id}", response_model=CopiedTraderResponse)
def update_trader(trader_id: int, payload: CopiedTraderUpdate, db: Session = Depends(get_db)):
    trader = db.query(CopiedTrader).filter(CopiedTrader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(trader, field, value)
    trader.last_updated = datetime.utcnow()
    db.commit()
    db.refresh(trader)
    return trader


# ── Alerts ────────────────────────────────────


@app.get("/api/portfolios/{portfolio_id}/alerts")
def get_portfolio_alerts(
    portfolio_id: int,
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id)
    return get_alerts(db, portfolio_id, unread_only=unread_only, limit=limit)


@app.get("/api/portfolios/{portfolio_id}/alerts/summary")
def alert_summary(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    return get_alert_summary(db, portfolio_id)


@app.post("/api/alerts/{alert_id}/read")
def mark_alert_read_endpoint(alert_id: int, db: Session = Depends(get_db)):
    if not mark_alert_read(db, alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert marked as read"}


@app.post("/api/portfolios/{portfolio_id}/alerts/read-all")
def mark_all_alerts_read(portfolio_id: int, db: Session = Depends(get_db)):
    _get_portfolio_or_404(db, portfolio_id)
    count = mark_all_read(db, portfolio_id)
    return {"message": f"{count} alerts marked as read", "count": count}


# ── Settings ──────────────────────────────────


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    def _load(key: str, default=""):
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        return s.value if s is not None else os.getenv(key.upper(), default)

    return {
        "etoro_api_key": _load("etoro_api_key"),
        "etoro_api_secret": _load("etoro_api_secret"),
        "etoro_account_id": _load("etoro_account_id"),
        "telegram_bot_token": _load("telegram_bot_token"),
        "telegram_chat_id": _load("telegram_chat_id"),
    }


@app.post("/api/settings")
def update_settings(settings: dict, db: Session = Depends(get_db)):
    required = ["etoro_api_key", "etoro_api_secret"]
    for field in required:
        if field not in settings or not isinstance(settings[field], str) or not settings[field].strip():
            raise HTTPException(status_code=400, detail=f"Required field missing: {field}")

    for field, value in settings.items():
        s = db.query(AppSetting).filter(AppSetting.key == field).first()
        if s is None:
            s = AppSetting(key=field, value=value)
            db.add(s)
        else:
            s.value = value
    db.commit()
    return {"message": "Settings updated", "settings": settings}


# ── Helpers ───────────────────────────────────


def _get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio
