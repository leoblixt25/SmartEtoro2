"""
Groq AI Market Scout
────────────────────────────────────────────────────────────────────
Replaces Gemini Scout with Groq Llama model for faster, rate‑limit‑free operation.
Provides the same evaluate() and evaluate_portfolio() interfaces.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TARGET_KEY = "target_portfolio"

SYSTEM_PROMPT = """You are the Chief Risk Officer for an eToro copy-trading portfolio.

Your job is to:
1. Read the provided market news headlines.
2. Review each copied trader's stock holdings and performance metrics.
3. Flag any trader whose portfolio contains assets that are negatively impacted by current news events.
4. Flag any trader whose drawdown or return metrics are critically underperforming.
5. If a trader is flagged, recommend a specific replacement from the provided top-trader candidates.

Rules:
- Only flag a trader if the evidence is clear (don't cry wolf).
- Your reasoning must cite specific news items or metric thresholds.
- You may only recommend replacements from the provided candidate list.
- If everything looks safe, set action_required to false.

Respond with ONLY valid JSON, no markdown fences, no commentary:

{
  "action_required": true,
  "flagged_trader": "username_of_flagged_trader",
  "reasoning": "Clear explanation citing specific news or metrics",
  "recommended_swap": "username_from_candidates"
}

If no action is needed:
{
  "action_required": false,
  "flagged_trader": null,
  "reasoning": "All traders look healthy relative to current market conditions",
  "recommended_swap": null
}
"""


ALLOCATION_PROMPT = """You are a portfolio allocation optimizer for eToro copy-trading.
Your only job is to construct a 3-trader target portfolio from the data below.

You are a macro-level quantitative evaluator. Detailed stock holdings are intentionally abstracted. DO NOT mention missing or unknown holdings. You must evaluate traders solely based on their Return %, Risk Score, and how their general trading style aligns with current Macro News.

CRITICAL: You MUST select exactly 3 traders for the target_portfolio.
If specific stock holdings are unknown, you must base your decision on their historical return, risk score, and overall market sentiment. Do not allocate 100% to a single trader.

Rules:
- You MUST output exactly 3 traders. No more, no fewer.
- Allocations MUST sum to exactly 100%.
- You may select existing traders, the provided candidates, or a mix of both.
- ONLY select from traders appearing in CURRENT PORTFOLIO or CANDIDATES below.
- If insufficient context is available, choose the top 3 by return and risk.

AVAILABLE CANDIDATES (Choose 3 from this list or the CURRENT PORTFOLIO list):
{available_candidates}

Output your analysis in the following JSON schema:
{
  "target_portfolio": [
    {"username": "trader_1", "allocation_pct": 50, "reasoning": "Performance is resilient."},
    {"username": "trader_2", "allocation_pct": 25, "reasoning": "Low risk hedge."},
    {"username": "trader_3", "allocation_pct": 25, "reasoning": "Diversification."}
  ]
}
"""


class GroqScout:
    """Market scout powered by Groq Llama 3.3 70B model.

    It mirrors the GeminiScout API: ``evaluate`` for risk alerts and
    ``evaluate_portfolio`` for a 3‑trader allocation recommendation.

    The Groq SDK import is deferred to call time so a broken or
    missing groq package never crashes the app at startup.
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            logger.info("GROQ_API_KEY not set — Groq scout disabled")
            self.enabled = False
            self._api_key = None
        else:
            self._api_key = key
            self._client = None       # created lazily by _ensure_client()
            self.enabled = True
            logger.info("Groq scout enabled (client will init on first call)")

    def _ensure_client(self):
        """Import groq and create the client on first use."""
        if self._client is not None:
            return self._client
        try:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
            logger.info("Groq client initialized")
            return self._client
        except ImportError as e:
            logger.error(f"Groq SDK import failed: {e} — falling back")
            self.enabled = False
            raise
        except Exception as e:
            logger.error(f"Groq client init failed: {e}")
            self.enabled = False
            raise

    async def evaluate(
        self,
        holdings_data: list[dict],
        news_data: list[dict],
        top_traders: list[dict],
    ) -> dict:
        """Evaluate portfolio against market news using Groq.

        Returns a dict compatible with the GeminiScout output.
        """
        if not self.enabled:
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": "Groq scout is not configured. Set GROQ_API_KEY.",
                "recommended_swap": None,
            }

        prompt = self._build_prompt(holdings_data, news_data, top_traders)
        try:
            client = self._ensure_client()
            import asyncio

            def _call():
                return client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                )

            response = await asyncio.to_thread(_call)
            # ``response`` is a Groq ChatCompletion object; ``choices[0].message.content`` holds the JSON string
            raw_text = response.choices[0].message.content
            return self._parse_response(raw_text)
        except Exception as e:
            logger.error(f"Groq scout evaluation failed: {e}")
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": f"Scout evaluation error: {e}",
                "recommended_swap": None,
            }

    async def evaluate_portfolio(
        self,
        holdings_data: list[dict],
        news_data: list[dict],
        top_traders: list[dict],
    ) -> dict:
        """Ask Groq to propose a 3‑trader allocation plan.

        Returns a dict containing ``target_portfolio`` and optional metadata.
        """
        if not self.enabled:
            return {TARGET_KEY: [], "total_risk_score": 0, "market_sentiment": "unknown"}

        prompt = self._build_allocation_prompt(holdings_data, news_data, top_traders)
        try:
            client = self._ensure_client()
            import asyncio

            def _call():
                return client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": ALLOCATION_PROMPT}, {"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                )

            response = await asyncio.to_thread(_call)
            raw_text = response.choices[0].message.content
            parsed = self._parse_response(raw_text)
            # Ensure we have exactly 3 allocations; otherwise fallback to equal weight
            allocs = parsed.get(TARGET_KEY, [])
            if len(allocs) != 3:
                logger.warning(
                    f"Groq returned {len(allocs)} allocations (expected 3) — using fallback"
                )
                return self._fallback_allocation(holdings_data)
            # Normalise percentages to sum to 100
            total = sum(a.get("allocation_pct", 0) for a in allocs)
            if total <= 0:
                logger.warning("Groq allocations sum to 0 — using fallback")
                return self._fallback_allocation(holdings_data)
            for a in allocs:
                a["allocation_pct"] = round((a.get("allocation_pct", 0) / total) * 100, 1)
            return {
                TARGET_KEY: allocs,
                "total_risk_score": parsed.get("total_risk_score", 5.0),
                "market_sentiment": parsed.get("market_sentiment", "neutral"),
            }
        except Exception as e:
            logger.error(f"Groq allocation evaluation failed: {e}")
            return self._fallback_allocation(holdings_data)

    def _fallback_allocation(self, holdings: list[dict]) -> dict:
        """Equal‑weight fallback if Groq fails or returns malformed output."""
        top = sorted(holdings, key=lambda h: h.get("total_return_pct", 0) or 0, reverse=True)[:3]
        if not top:
            return {TARGET_KEY: [], "total_risk_score": 0, "market_sentiment": "unknown"}
        pct = round(100 / len(top), 1)
        return {
            "target_portfolio": [
                {"username": t["username"], "allocation_pct": pct, "reasoning": "Fallback — equal weight"}
                for t in top
            ],
            "total_risk_score": 5.0,
            "market_sentiment": "neutral",
        }

    # ---------------------------------------------------------------------
    # Prompt builders – copied verbatim from GeminiScout for consistency.
    # ---------------------------------------------------------------------
    def _build_prompt(
        self,
        holdings: list[dict],
        news: list[dict],
        candidates: list[dict],
    ) -> str:
        sections = ["=== CURRENT PORTFOLIO HOLDINGS ==="]
        for t in holdings:
            sections.append(
                f"Trader: {t.get('username', '?')}\n"
                f"  Allocation: {t.get('allocation_pct', 0):.1f}%\n"
                f"  Return: {t.get('total_return_pct', 0):+.2f}%\n"
                f"  Risk Score: {t.get('risk_score', 5):.1f}/10\n"
                f"  Max Drawdown: {t.get('max_drawdown', 0):.1f}%\n"
                f"  Holdings: {', '.join(t.get('positions', [])) or 'unknown'}\n"
            )
        sections.append("\n=== MARKET NEWS HEADLINES ===")
        for i, n in enumerate(news[:15], 1):
            sections.append(f"{i}. [{n.get('source', '?')}] {n.get('title', '')}")
        sections.append("\n=== RECOMMENDED CANDIDATES (for swaps) ===")
        for c in candidates[:10]:
            sections.append(
                f"- {c.get('username', '?')} "
                f"(Risk: {c.get('risk_score', '?')}/10, "
                f"Return: {c.get('total_return_pct', '?')}%)"
            )
        return "\n".join(sections)

    def _build_allocation_prompt(
        self,
        holdings: list[dict],
        news: list[dict],
        candidates: list[dict],
    ) -> str:
        candidate_lines = []
        for c in candidates[:10]:
            candidate_lines.append(
                f"  - {c.get('username', '?')} "
                f"(Risk: {c.get('risk_score', '?')}/10, "
                f"Return: {c.get('total_return_pct', '?')}%)"
            )
        candidate_block = "\n".join(candidate_lines) if candidate_lines else "  (none available)"
        prompt_header = ALLOCATION_PROMPT.replace("{available_candidates}", candidate_block)
        sections = [prompt_header]
        sections.append("\n=== CURRENT PORTFOLIO HOLDINGS ===")
        for t in holdings:
            sections.append(
                f"Trader: {t.get('username', '?')}\n"
                f"  Allocation: {t.get('allocation_pct', 0):.1f}%\n"
                f"  Return: {t.get('total_return_pct', 0):+.2f}%\n"
                f"  Risk Score: {t.get('risk_score', 5):.1f}/10\n"
                f"  Max Drawdown: {t.get('max_drawdown', 0):.1f}%\n"
            )
        sections.append("\n=== MARKET NEWS HEADLINES ===")
        for i, n in enumerate(news[:15], 1):
            sections.append(f"{i}. [{n.get('source', '?')}] {n.get('title', '')}")
        return "\n".join(sections)

    def _parse_response(self, raw_text: str) -> dict:
        try:
            clean = raw_text.strip().replace('```json', '').replace('```', '')
            data = json.loads(clean)
            # Ensure required keys exist; mimic GeminiScout's output format
            return {
                "action_required": data.get("action_required", False),
                "flagged_trader": data.get("flagged_trader"),
                "recommended_swap": data.get("recommended_swap"),
                "reasoning": data.get("reasoning", ""),
                "target_portfolio": data.get("target_portfolio", []),
            }
        except Exception as e:
            logger.error(f"Failed to parse Groq response: {e}")
            return {"action_required": False, "reasoning": "Parse error", "target_portfolio": []}
