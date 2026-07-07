"""
Alert Service — centralized alert access, filtering, and management.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import Alert, AlertType

logger = logging.getLogger(__name__)


LOSS_THRESHOLD = -10.0
PROFIT_MIN = 10.0
PROFIT_MAX = 20.0
DEDUP_HOURS = 24

DEFAULT_PROFIT_TARGET_PCT = float(os.getenv("DEFAULT_PROFIT_TARGET_PCT", "25"))
TAKEPROFIT_DEDUP_HOURS = 48  # don't re-check same trader within 48h


async def _ai_should_take_profit(
    username: str,
    total_return: float,
    target_pct: float,
    allocation_pct: float,
    drawdown: float,
    risk_score,
    return_1w,
    market_data: dict,
) -> dict:
    """Ask AI whether to take profit on a trader that has hit their target.
    
    Returns {"take_profit": bool, "confidence": str, "reason": str}.
    Falls back to {"take_profit": True, "confidence": "LOW", "reason": "AI unavailable"} on failure.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
    if not api_key:
        return {"take_profit": True, "confidence": "LOW", "reason": "AI unavailable, defaulting to take profit"}

    from backend.monitoring.ai_health_engine import PROVIDERS
    provider = "openai"
    for name, cfg in PROVIDERS.items():
        if api_key.startswith(cfg["key_prefix"]):
            provider = name
            break

    extra_headers = {}
    if provider == "groq":
        base_url = PROVIDERS["groq"]["base_url"]
        model = "llama-3.3-70b-versatile"
    elif provider == "openrouter":
        base_url = PROVIDERS["openrouter"]["base_url"]
        model = "openai/gpt-4o-mini"
        extra_headers = {"HTTP-Referer": "https://github.com/leoblixt25/SmartEtoro2", "X-Title": "SmartEtoro2"}
    else:
        base_url = None
        model = "gpt-4o-mini"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, **(base_url and {"base_url": base_url}))

    spy = market_data.get("SPY")
    qqq = market_data.get("QQQ")
    mkt = f"SPY {spy:+.1f}%" if spy is not None else "SPY N/A"
    mkt += f", QQQ {qqq:+.1f}%" if qqq is not None else ", QQQ N/A"
    trend = f"{return_1w:+.1f}% (1w)" if return_1w is not None else "unknown"

    prompt = (
        f"Trader: {username}\n"
        f"Return: {total_return:+.1f}%\n"
        f"Target: {target_pct:.0f}%\n"
        f"Allocation: {allocation_pct:.0f}%\n"
        f"Drawdown: {drawdown:.1f}%\n"
        f"Risk: {risk_score or 'N/A'}\n"
        f"Trend: {trend}\n"
        f"Market: {mkt}\n\n"
        f"Should we take profit on {username} now? Consider:\n"
        f"- Return trajectory (is it still growing or stalling?)\n"
        f"- Market conditions (risk-on or risk-off?)\n"
        f"- Drawdown risk if we wait longer\n"
        f"- Allocation size (bigger allocations need more caution)\n\n"
        f"Answer ONLY valid JSON: {{\"take_profit\": true/false, \"confidence\": \"high/medium/low\", \"reason\": \"10 words max\"}}"
    )

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a cautious portfolio manager. Prefer taking profit when targets are hit in uncertain markets. Answer ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
    }
    if extra_headers:
        kwargs["extra_headers"] = extra_headers
    if provider == "groq":
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[0] if "```" in raw else raw
        data = json.loads(raw)
        return {
            "take_profit": bool(data.get("take_profit", True)),
            "confidence": str(data.get("confidence", "LOW")),
            "reason": str(data.get("reason", "AI analysis"))[:80],
        }
    except Exception as e:
        logger.warning(f"Take-profit AI call failed for {username}: {e}")
        return {"take_profit": True, "confidence": "LOW", "reason": f"AI error, defaulting to take profit"}


async def check_take_profit(db: Session, portfolio_id: int, bot=None, market_data: dict = None) -> List[Dict]:
    """Check active traders that have hit their profit target and ask AI whether to exit.

    Runs silently if no trader is at or above their target.
    Sends Telegram alert if AI recommends taking profit.
    Returns list of triggered take-profit alerts.
    """
    from backend.database.models import CopiedTrader

    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
            CopiedTrader.is_paused.is_(False),
            CopiedTrader.take_profit_triggered.is_(False),
        )
        .all()
    )

    cutoff = datetime.utcnow() - timedelta(hours=TAKEPROFIT_DEDUP_HOURS)
    new_alerts = []

    for t in traders:
        ret = t.total_return_pct
        if ret is None or ret <= 0:
            continue

        target = t.take_profit_target_pct or DEFAULT_PROFIT_TARGET_PCT
        if ret < target:
            continue

        # Deduplicate: skip if already alerted for this trader recently
        title_exists = db.query(Alert).filter(
            Alert.portfolio_id == portfolio_id,
            Alert.title.like(f"%Take Profit: {t.trader_username}%"),
            Alert.created_at > cutoff,
        ).first()
        if title_exists:
            logger.info(f"Take-profit already evaluated for {t.trader_username} in last {TAKEPROFIT_DEDUP_HOURS}h — skipping")
            continue

        logger.info(f"Take-profit candidate: {t.trader_username} at {ret:.1f}% (target {target:.0f}%)")

        decision = await _ai_should_take_profit(
            username=t.trader_username,
            total_return=ret,
            target_pct=target,
            allocation_pct=t.allocation_pct or 0,
            drawdown=t.max_drawdown or 0,
            risk_score=t.risk_score,
            return_1w=getattr(t, "return_1w", None),
            market_data=market_data or {},
        )

        if decision["take_profit"]:
            t.take_profit_triggered = True
            reason = decision["reason"]
            confidence = decision["confidence"]
            title = f"\U0001f534 Take Profit: {t.trader_username}"
            message = (
                f"{t.trader_username} hit {ret:.1f}% profit (target {target:.0f}%) — "
                f"AI recommends exiting. {reason}"
            )
            new_alerts.append({
                "title": title,
                "message": message,
                "severity": "critical",
                "alert_type": AlertType.MONITORING,
            })
        else:
            logger.info(f"Take-profit: AI says hold {t.trader_username} — {decision['reason']}")
            # Still mark so we don't re-ask every 5 min; can revisit after health report
            t.take_profit_triggered = True

    for a in new_alerts:
        db.add(Alert(
            portfolio_id=portfolio_id,
            alert_type=a["alert_type"],
            title=a["title"],
            message=a["message"],
            severity=a["severity"],
        ))
    if new_alerts:
        db.commit()
        if bot and bot.enabled:
            for a in new_alerts:
                await bot.send_message(
                    f"{a['title']}\n{a['message']}\n\nUse /health for full analysis.",
                    show_keyboard=False,
                )

    return new_alerts


async def check_return_thresholds(db: Session, portfolio_id: int, bot=None) -> List[Dict]:
    """Check active traders for return threshold breaches.

    Alerts when a trader's total return:
      - drops to -6% or worse (critical alert)
      - reaches 10-20% profit range (info alert)

    Deduplicates by checking if the same alert title was created in the last DEDUP_HOURS.
    Sends Telegram notification if a bot instance is provided.
    """
    from backend.database.models import CopiedTrader

    traders = (
        db.query(CopiedTrader)
        .filter(
            CopiedTrader.portfolio_id == portfolio_id,
            CopiedTrader.is_active.is_(True),
            CopiedTrader.is_paused.is_(False),
        )
        .all()
    )

    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_HOURS)
    new_alerts = []

    for t in traders:
        ret = t.total_return_pct
        if ret is None:
            continue
        username = t.trader_username

        if ret <= LOSS_THRESHOLD:
            title = f"\U0001f534 Loss Alert: {username}"
            exists = db.query(Alert).filter(
                Alert.portfolio_id == portfolio_id,
                Alert.title == title,
                Alert.created_at > cutoff,
            ).first()
            if not exists:
                new_alerts.append({
                    "title": title,
                    "message": f"{username} has lost <b>{ret:.2f}%</b> \u2014 exceeds {abs(LOSS_THRESHOLD):.0f}% threshold (alloc: {t.allocation_pct:.1f}%)",
                    "severity": "critical",
                    "alert_type": AlertType.MONITORING,
                })

        elif PROFIT_MIN <= ret <= PROFIT_MAX:
            title = f"\U0001f7e2 Profit Alert: {username}"
            exists = db.query(Alert).filter(
                Alert.portfolio_id == portfolio_id,
                Alert.title == title,
                Alert.created_at > cutoff,
            ).first()
            if not exists:
                new_alerts.append({
                    "title": title,
                    "message": f"{username} is up <b>{ret:.2f}%</b> ({PROFIT_MIN:.0f}-{PROFIT_MAX:.0f}% range)",
                    "severity": "info",
                    "alert_type": AlertType.PROFIT_MILESTONE,
                })

    for a in new_alerts:
        db.add(Alert(
            portfolio_id=portfolio_id,
            alert_type=a["alert_type"],
            title=a["title"],
            message=a["message"],
            severity=a["severity"],
        ))
    if new_alerts:
        db.commit()
        if bot and bot.enabled:
            for a in new_alerts:
                await bot.send_message(
                    f"{a['title']}\n{a['message']}\n\U0001f4c5 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                    show_keyboard=False,
                )

    return new_alerts


def get_alerts(
    db: Session,
    portfolio_id: int,
    unread_only: bool = False,
    limit: int = 50,
    alert_types: Optional[List[str]] = None,
) -> List[Dict]:
    """Get alerts for a portfolio with optional filters."""
    q = db.query(Alert).filter(Alert.portfolio_id == portfolio_id)

    if unread_only:
        q = q.filter(Alert.is_read.is_(False))
    if alert_types:
        q = q.filter(Alert.alert_type.in_(alert_types))

    alerts = q.order_by(Alert.created_at.desc()).limit(limit).all()

    return [
        {
            "id": a.id,
            "type": a.alert_type.value if hasattr(a.alert_type, 'value') else str(a.alert_type),
            "title": a.title,
            "message": a.message,
            "severity": a.severity,
            "is_read": a.is_read,
            "was_sent_telegram": a.was_sent_telegram,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


def mark_alert_read(db: Session, alert_id: int) -> bool:
    """Mark a single alert as read. Returns True if found."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return False
    alert.is_read = True
    db.commit()
    return True


def mark_all_read(db: Session, portfolio_id: int) -> int:
    """Mark all alerts as read for a portfolio. Returns count."""
    count = (
        db.query(Alert)
        .filter(Alert.portfolio_id == portfolio_id, Alert.is_read.is_(False))
        .update({"is_read": True})
    )
    db.commit()
    return count


def get_alert_summary(db: Session, portfolio_id: int) -> Dict:
    """Return counts of unread alerts by severity."""
    alerts = (
        db.query(Alert)
        .filter(Alert.portfolio_id == portfolio_id, Alert.is_read.is_(False))
        .all()
    )
    return {
        "total": len(alerts),
        "critical": sum(1 for a in alerts if a.severity == "critical"),
        "warning": sum(1 for a in alerts if a.severity == "warning"),
        "info": sum(1 for a in alerts if a.severity == "info"),
    }
