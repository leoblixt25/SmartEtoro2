"""
Pydantic v2 schemas for request/response validation.
Separates API contract from database models.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from backend.database.models import RiskClassification, AutomationStatus, AlertType


# ──────────────────────────────────────────────
# Portfolio schemas
# ──────────────────────────────────────────────

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
    is_simulation: bool
    last_updated: datetime
    created_at: datetime


# ──────────────────────────────────────────────
# Position schemas
# ──────────────────────────────────────────────

class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument: str
    direction: str
    amount: float
    open_price: float
    current_price: float
    unrealized_pnl: float
    pnl_pct: float
    is_open: bool
    opened_at: datetime
    source: str


# ──────────────────────────────────────────────
# Copied Trader schemas
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# Analytics schemas
# ──────────────────────────────────────────────

class TraderAnalyticsResult(BaseModel):
    trader_id: int
    trader_username: str
    risk_score: float
    risk_classification: RiskClassification
    max_drawdown: float
    avg_monthly_return: float
    sharpe_score: float
    volatility: float
    consistency_score: float
    diversification_score: float
    strengths: List[str]
    weaknesses: List[str]
    warning_signs: List[str]
    sustainability: str
    overall_verdict: str


class PortfolioHealthResult(BaseModel):
    health_score: float
    diversification_score: float
    risk_exposure: str
    concentration_risk: bool
    overexposed_traders: List[str]
    underperforming_traders: List[str]
    recommendations: List[str]
    pnl_breakdown: Dict[str, float]
    allocation_by_trader: List[Dict]


class PerformanceChartPoint(BaseModel):
    date: str
    value: float
    pnl: float


# ──────────────────────────────────────────────
# AI Recommendation schemas
# ──────────────────────────────────────────────

class AIRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_type: str
    title: str
    summary: str
    confidence: float
    risk_level: str
    is_acted_on: bool
    created_at: datetime


class AIAnalysisRequest(BaseModel):
    portfolio_id: int
    analysis_type: str = "general"   # general / trader / weekly / risk
    trader_id: Optional[int] = None
    extra_context: Optional[str] = None


# ──────────────────────────────────────────────
# Automation schemas
# ──────────────────────────────────────────────

class AutomationRuleCreate(BaseModel):
    rule_type: str
    name: str
    description: Optional[str] = None
    config: Dict[str, Any] = {}
    threshold: Optional[float] = None
    cooldown_hours: int = 24
    requires_approval: bool = True


class AutomationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_type: str
    name: str
    description: Optional[str]
    status: AutomationStatus
    config: Dict[str, Any]
    threshold: Optional[float]
    cooldown_hours: int
    last_triggered: Optional[datetime]
    trigger_count: int
    requires_approval: bool
    created_at: datetime


class AutomationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action_type: str
    description: str
    details: Dict[str, Any]
    was_simulated: bool
    was_approved: bool
    was_reversed: bool
    triggered_at: datetime


# ──────────────────────────────────────────────
# Alert schemas
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# Risk Settings schemas
# ──────────────────────────────────────────────

class RiskSettingsUpdate(BaseModel):
    max_portfolio_drawdown_pct: Optional[float] = Field(None, ge=1, le=50)
    max_allocation_per_trader_pct: Optional[float] = Field(None, ge=5, le=80)
    min_traders_for_diversification: Optional[int] = Field(None, ge=1, le=20)
    max_single_asset_exposure_pct: Optional[float] = Field(None, ge=5, le=80)
    volatility_reduction_threshold: Optional[float] = Field(None, ge=5, le=50)
    cooldown_after_loss_hours: Optional[int] = Field(None, ge=0, le=720)
    emergency_protection_enabled: Optional[bool] = None
    emergency_drawdown_trigger_pct: Optional[float] = Field(None, ge=5, le=40)


class RiskSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    max_portfolio_drawdown_pct: float
    max_allocation_per_trader_pct: float
    min_traders_for_diversification: int
    max_single_asset_exposure_pct: float
    volatility_reduction_threshold: float
    cooldown_after_loss_hours: int
    emergency_protection_enabled: bool
    emergency_drawdown_trigger_pct: float


# ──────────────────────────────────────────────
# WebSocket message schemas
# ──────────────────────────────────────────────

class WSMessage(BaseModel):
    event: str
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
