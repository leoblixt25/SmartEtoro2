"""
AI Analysis Module — Claude Integration
────────────────────────────────────────────────────────────────────
Wraps the Anthropic API to generate safe, explainable investment
analysis. Every response includes a confidence score and avoids
emotional or hyped language.

Design principles:
- NEVER recommend actions without confidence scores
- ALWAYS explain reasoning in plain language
- NEVER encourage high-risk or leveraged positions
- Always prioritize capital preservation language
"""

from __future__ import annotations
import json
import logging
from typing import Optional
import anthropic
from backend.database.models import Portfolio, CopiedTrader
from backend.analytics.portfolio_analytics import PortfolioHealthResult

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a conservative, long-term investment analysis assistant for an eToro portfolio management platform.

Your role is to:
- Analyze portfolio data and provide clear, factual assessments
- Recommend risk-reducing actions when appropriate
- Explain your reasoning in plain, jargon-free language
- Always include a confidence level (Low / Medium / High) for each recommendation
- Flag overexposure, high-risk traders, and concentration risks

Your tone must be:
- Calm and analytical — never excited or alarmist
- Conservative — prioritize capital preservation over growth
- Transparent — explain WHY, not just WHAT
- Concise — 3-5 sentences per recommendation maximum

You must NEVER:
- Suggest leveraged positions or high-frequency trading
- Encourage chasing returns or revenge trading
- Make guarantees about future performance
- Recommend panic selling or emotional decisions

Format your responses as structured JSON with these fields:
{
  "recommendations": [
    {
      "type": "allocation | risk | trader | general",
      "title": "Short action title",
      "summary": "2-4 sentence explanation",
      "confidence": "low | medium | high",
      "risk_level": "low | medium | high"
    }
  ],
  "weekly_summary": "Optional: 2-3 sentence portfolio overview",
  "overall_risk_assessment": "low | medium | high | critical"
}
"""


class AIAnalysisEngine:
    """
    Wraps Claude API for portfolio and trader analysis.
    All outputs are structured and confidence-scored.
    """

    def __init__(self, api_key: Optional[str] = None):
        import os
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            logger.warning("ANTHROPIC_API_KEY not set — AI analysis will return mock data")
            self._client = None
        else:
            self._client = anthropic.AsyncAnthropic(api_key=key)

    # ── Public analysis methods ──────────────────

    async def analyze_portfolio(
        self,
        portfolio: Portfolio,
        health_result: PortfolioHealthResult,
    ) -> dict:
        """Full portfolio health analysis with recommendations."""
        prompt = self._build_portfolio_prompt(portfolio, health_result)
        return await self._call_claude(prompt, context="portfolio_analysis")

    async def analyze_trader(self, trader: CopiedTrader) -> dict:
        """Deep-dive analysis of a single copied trader."""
        prompt = self._build_trader_prompt(trader)
        return await self._call_claude(prompt, context="trader_analysis")

    async def generate_weekly_summary(
        self,
        portfolio: Portfolio,
        traders: list[CopiedTrader],
    ) -> dict:
        """Weekly performance summary for Telegram/dashboard."""
        prompt = self._build_weekly_prompt(portfolio, traders)
        return await self._call_claude(prompt, context="weekly_summary")

    async def check_risk_alerts(
        self,
        portfolio: Portfolio,
        health_result: PortfolioHealthResult,
    ) -> dict:
        """Focused risk check — returns only alerts, not full analysis."""
        prompt = self._build_risk_check_prompt(portfolio, health_result)
        return await self._call_claude(prompt, context="risk_check")

    # ── Prompt builders ──────────────────────────

    def _build_portfolio_prompt(
        self,
        portfolio: Portfolio,
        health: PortfolioHealthResult,
    ) -> str:
        return f"""Analyze this eToro portfolio and provide actionable recommendations.

PORTFOLIO DATA:
- Total Value: ${portfolio.total_value:,.2f}
- Available Cash: ${portfolio.available_cash:,.2f}
- Daily PnL: ${portfolio.daily_pnl:+,.2f}
- Weekly PnL: ${portfolio.weekly_pnl:+,.2f}
- Monthly PnL: ${portfolio.monthly_pnl:+,.2f}
- Unrealized PnL: ${portfolio.unrealized_pnl:+,.2f}
- Health Score: {portfolio.health_score:.1f}/100
- Simulation Mode: {portfolio.is_simulation}

HEALTH ANALYSIS:
- Diversification Score: {health.diversification_score:.1f}/100
- Risk Exposure: {health.risk_exposure.upper()}
- Concentration Risk: {health.concentration_risk}
- Overexposed Traders: {', '.join(health.overexposed_traders) or 'None'}
- Underperforming Traders: {', '.join(health.underperforming_traders) or 'None'}

TRADER ALLOCATIONS:
{json.dumps(health.allocation_by_trader, indent=2)}

EXISTING RECOMMENDATIONS FROM RULES ENGINE:
{chr(10).join(f'- {r}' for r in health.recommendations)}

Based on this data, provide your analysis and recommendations. Focus on risk management and long-term portfolio stability."""

    def _build_trader_prompt(self, trader: CopiedTrader) -> str:
        return f"""Analyze this copied trader's performance and risk profile for an eToro investor.

TRADER: {trader.trader_username}
- Allocation: ${trader.allocated_amount:,.2f} ({trader.allocation_pct:.1f}% of portfolio)
- Current Value: ${trader.current_value:,.2f}
- Total Return: {trader.total_return_pct:+.2f}%
- Risk Score: {trader.risk_score:.1f}/10
- Risk Classification: {trader.risk_classification}
- Max Drawdown: {trader.max_drawdown:.1f}%
- Avg Monthly Return: {trader.avg_monthly_return:.2f}%
- Sharpe Score: {trader.sharpe_score:.2f}
- Volatility: {trader.volatility:.1f}%
- Trade Frequency: {trader.trade_frequency:.1f} trades/week
- Diversification Score: {trader.diversification_score:.1f}/100
- Consistency Score: {trader.consistency_score:.1f}%

Provide an honest assessment of whether to continue copying this trader, adjust allocation, or stop copying. Prioritize risk-adjusted returns over raw performance."""

    def _build_weekly_prompt(
        self,
        portfolio: Portfolio,
        traders: list[CopiedTrader],
    ) -> str:
        trader_summary = "\n".join([
            f"  - {t.trader_username}: {t.total_return_pct:+.1f}% return, "
            f"Risk {t.risk_score:.1f}/10, {'⚠ Paused' if t.is_paused else 'Active'}"
            for t in traders
        ])
        return f"""Generate a weekly portfolio performance summary.

WEEKLY PERFORMANCE:
- Portfolio Value: ${portfolio.total_value:,.2f}
- Weekly PnL: ${portfolio.weekly_pnl:+,.2f}
- Health Score: {portfolio.health_score:.1f}/100

COPIED TRADERS:
{trader_summary}

Provide a concise weekly summary suitable for a Telegram notification. Keep it under 200 words, focus on what changed and what to watch next week."""

    def _build_risk_check_prompt(
        self,
        portfolio: Portfolio,
        health: PortfolioHealthResult,
    ) -> str:
        return f"""Quick risk check for this portfolio. Flag only genuine concerns.

- Health Score: {portfolio.health_score:.1f}/100
- Risk Exposure: {health.risk_exposure}
- Overexposed: {health.overexposed_traders}
- Underperforming: {health.underperforming_traders}
- Monthly PnL: ${portfolio.monthly_pnl:+,.2f}

Only return recommendations if there are real risk concerns. If everything looks acceptable, say so clearly."""

    # ── Claude API call ──────────────────────────

    async def _call_claude(self, prompt: str, context: str = "analysis") -> dict:
        """
        Call Claude API and return structured JSON response.
        Raises an exception if API is unavailable.
        """
        if self._client is None:
            raise RuntimeError("ANTHROPIC_API_KEY not configured — Claude unavailable")

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text

            # Strip markdown code fences if present
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]

            return json.loads(cleaned.strip())

        except json.JSONDecodeError as e:
            logger.error(f"AI response JSON parse error ({context}): {e}")
            raise
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error ({context}): {e}")
            raise
