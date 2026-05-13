"""
Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from backend.database.models import RiskClassification, AlertType


class PortfolioBase(BaseModel):
    user_id: str
    is_simulation: bool = False


class PortfolioCreate(PortfolioBase):
    total_value: float = 0.0
    invested_amount: float = 0.0
    available_cash: float = 0.0


class PortfolioUpdate(BaseModel):
    total_value: Optional[float] = None
    invested_amount: Optional[float] = None
    available_cash: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    daily_pnl: Optional[float] = None
    weekly_pnl: Optional[float] = None
    monthly_pnl: Optional[float] = None
    health_score: Optional[float] = None


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: str
    total_value: float
    invested_amount: float
    available_cash: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    health_score: float
    currency: str
    is_simulation: bool
    last_updated: datetime
    created_at: datetime


class CopiedTraderCreate(BaseModel):
    trader_username: str
    trader_id: str
    allocated_amount: float = Field(gt=0)
    allocation_pct: float = Field(ge=0, le=100)


class CopiedTraderUpdate(BaseModel):
    allocated_amount: Optional[float] = None
    allocation_pct: Optional[float] = None
    risk_score: Optional[float] = None
    is_paused: Optional[bool] = None
    paused_reason: Optional[str] = None


class CopiedTraderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trader_username: str
    trader_id: str
    allocated_amount: float
    allocation_pct: float
    current_value: float
    unrealized_pnl: float
    total_return_pct: float
    risk_score: float
    risk_classification: RiskClassification
    max_drawdown: float
    avg_monthly_return: float
    sharpe_score: float
    volatility: float
    trade_frequency: float
    diversification_score: float
    consistency_score: float
    is_active: bool
    is_paused: bool
    paused_reason: Optional[str]
    ai_summary: Optional[str]
    copy_started: datetime
    last_updated: datetime


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alert_type: AlertType
    title: str
    message: str
    severity: str
    is_read: bool
    was_sent_telegram: bool
    created_at: datetime
