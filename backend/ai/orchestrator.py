"""
Orchestrator — runs the full Decision + Alert pipeline.

Flow:
  1. Fetch discovery candidates + active holdings
  2. eligibility_engine.filter_candidates() → eligible + excluded
  3. portfolio_engine.analyze_portfolio() → portfolio analysis
  4. discovery_engine.build_discovery_list() → new-only candidates
  5. scoring_engine.rank_candidates() → scored discovery
  6. action_planner.build_action_plan() → full plan
  7. alert_engine.evaluate() → smart alerts

Output: a single dict with every section the dashboard needs.
"""

import logging
from typing import Dict, List, Optional

from backend.services.market_data import get_current_holdings
from backend.services.market_data import discover_top_traders, _default_trader_candidates
from backend.ai.eligibility_engine import filter_candidates
from backend.ai.portfolio_engine import analyze_portfolio, get_active_usernames
from backend.ai.discovery_engine import build_discovery_list
from backend.ai.scoring_engine import rank_candidates
from backend.ai.action_planner import build_action_plan, format_display
from backend.ai.alert_engine import AlertEngine

logger = logging.getLogger(__name__)

# Singleton alert engine (keeps state across runs)
_alert_engine = AlertEngine()


def get_alert_engine() -> AlertEngine:
    return _alert_engine


async def run_full_pipeline(
    db,
    portfolio_id: int,
    force_fallback: bool = False,
) -> Dict:
    """Run the full Decision + Alert pipeline for a single portfolio.

    Args:
        db: Database session.
        portfolio_id: Portfolio ID to analyze.
        force_fallback: If True, skip API and use static fallback data.

    Returns:
        Dict with keys:
          - portfolio_analysis
          - eligible_candidates
          - excluded_candidates
          - discovery_list
          - discovery_scored
          - action_plan
          - alerts
          - display (ready-to-render string)
          - eligibility_stats
    """
    from backend.database.models import Portfolio

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        logger.error("Pipeline: portfolio %d not found", portfolio_id)
        return {"error": f"Portfolio {portfolio_id} not found"}

    # ── 1. Fetch data ──
    holdings = get_current_holdings(db, portfolio_id)
    candidates = []

    if force_fallback:
        candidates = _default_trader_candidates()
    else:
        try:
            candidates = await discover_top_traders()
        except Exception as e:
            logger.warning("Pipeline: discovery failed (%s) — using fallback", e)
            candidates = _default_trader_candidates()

    # ── 2. Eligibility filter ──
    active_usernames = get_active_usernames(holdings)
    available_balance = portfolio.available_cash or (portfolio.total_value or 0) * 0.1

    eligible, excluded = filter_candidates(candidates, active_usernames, available_balance)

    eligibility_stats = {
        "total_scanned": len(candidates),
        "eligible": len(eligible),
        "excluded": len(excluded),
        "active_traders": len(holdings),
    }

    # ── 3. Portfolio analysis ──
    portfolio_analysis = analyze_portfolio(
        holdings,
        total_value=portfolio.total_value or 0,
        available_cash=portfolio.available_cash or 0,
    )

    # ── 4. Build discovery list (no overlap) ──
    discovery_list = build_discovery_list(eligible, active_usernames)

    # ── 5. Score discovery candidates ──
    discovery_scored = rank_candidates(holdings, discovery_list)

    # ── 6. Build action plan ──
    action_plan = build_action_plan(portfolio_analysis, discovery_scored, excluded, holdings)

    # ── 7. Evaluate alerts ──
    alerts = _alert_engine.evaluate(
        portfolio_id, portfolio_analysis, discovery_scored, excluded, action_plan,
    )

    # ── 8. Build display ──
    display = format_display(action_plan)

    # ── 9. Consolidated debug log ──
    logger.info(
        "PIPELINE portfolio=%d: scanned=%d, active=%d, "
        "eligible=%d, excluded=%d, alerts=%d, "
        "diversified=%s, concentration=%s",
        portfolio_id,
        eligibility_stats["total_scanned"],
        eligibility_stats["active_traders"],
        eligibility_stats["eligible"],
        eligibility_stats["excluded"],
        len(alerts),
        not portfolio_analysis.get("under_diversified", True),
        portfolio_analysis.get("concentration_risk", False),
    )

    return {
        "portfolio_analysis": portfolio_analysis,
        "eligible_candidates": eligible,
        "excluded_candidates": excluded,
        "discovery_list": discovery_list,
        "discovery_scored": discovery_scored,
        "action_plan": action_plan,
        "alerts": alerts,
        "display": display,
        "eligibility_stats": eligibility_stats,
    }
