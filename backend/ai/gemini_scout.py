"""
Gemini AI Market Scout
────────────────────────────────────────────────────────────────────
Proactive risk detection engine using Google Gemini Pro.
Evaluates portfolio holdings against market news to flag toxic
assets and recommend trader swaps.

Usage:
    scout = GeminiScout()
    result = await scout.evaluate(holdings, news, candidates)
"""

from __future__ import annotations
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


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

Your response MUST be valid JSON matching this exact structure:
```json
{
  "action_required": true,
  "reasoning": "Since the tech sector is rallying, I am allocating 50% to high-return trader X, and hedging 25% each into low-risk traders Y and Z.",
  "allocations": [
    {"username": "trader_1", "allocation_pct": 50, "reasoning": "Performance is resilient."},
    {"username": "trader_2", "allocation_pct": 25, "reasoning": "Low risk hedge."},
    {"username": "trader_3", "allocation_pct": 25, "reasoning": "Diversification."}
  ]
}
```
Do not include any preamble, conversational text, or markdown formatting outside of the JSON block. Your entire response must be valid, parseable JSON.
"""


class GeminiScout:
    """Proactive market-risk scout powered by Google Gemini Pro."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not GEMINI_AVAILABLE:
            logger.warning("google-generativeai not installed — Gemini scout disabled")
            self.enabled = False
        elif not key:
            logger.warning("GEMINI_API_KEY not set — Gemini scout disabled")
            self.enabled = False
        else:
            genai.configure(api_key=key)
            self._model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                system_instruction=SYSTEM_PROMPT,
            )
            self._allocation_model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                system_instruction=ALLOCATION_PROMPT,
            )
            self.enabled = True
            logger.info("Gemini scout initialized with gemini-2.0-flash")

    async def evaluate(
        self,
        holdings_data: list[dict],
        news_data: list[dict],
        top_traders: list[dict],
    ) -> dict:
        """Evaluate portfolio against market news using Gemini Pro.

        Args:
            holdings_data: List of current copied traders with metrics.
            news_data: List of recent market news headlines.
            top_traders: List of recommended alternative traders.

        Returns:
            Dict with keys: action_required, flagged_trader, reasoning, recommended_swap
        """
        if not self.enabled:
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": "Gemini scout is not configured. Set GEMINI_API_KEY.",
                "recommended_swap": None,
            }

        prompt = self._build_prompt(holdings_data, news_data, top_traders)

        try:
            response = await self._call_gemini(prompt)
            parsed = self._parse_response(response)
            if parsed["action_required"]:
                logger.warning(
                    f"Scout flagged {parsed['flagged_trader']}: "
                    f"{parsed['reasoning'][:120]}..."
                )
            else:
                logger.info("Scout: all clear")
            return parsed
        except Exception as e:
            logger.error(f"Gemini scout evaluation failed: {e}")
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": f"Scout evaluation error: {e}",
                "recommended_swap": None,
            }

    async def evaluate_portfolio_with_gemini(
        self,
        holdings_data: list[dict],
        news_data: list[dict],
        top_traders: list[dict],
    ) -> dict:
        """Ask Gemini to propose a 3-trader allocation plan."""
        if not self.enabled:
            return {"allocations": [], "total_risk_score": 0, "market_sentiment": "unknown"}

        if not self._allocation_model:
            self._allocation_model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                system_instruction=ALLOCATION_PROMPT,
            )

        prompt = self._build_allocation_prompt(holdings_data, news_data, top_traders)

        try:
            response = await self._call_gemini(prompt, model=self._allocation_model)
            parsed = self._parse_response(response)

            # Strict 3-trader enforcement
            allocs = parsed.get("allocations", [])
            if len(allocs) != 3:
                logger.warning(f"Gemini returned {len(allocs)} allocations, need 3 — using fallback")
                return self._fallback_allocation(holdings_data)

            # Normalize to 100%
            total = sum(a.get("allocation_pct", 0) for a in allocs)
            if total <= 0:
                logger.warning("Gemini allocations sum to 0 — using fallback")
                return self._fallback_allocation(holdings_data)
            
            for a in allocs:
                a["allocation_pct"] = round((a["allocation_pct"] / total) * 100, 1)

            logger.info(f"Gemini allocation: {[a['username'] for a in allocs]}")

            return {
                "allocations": allocs,
                "total_risk_score": parsed.get("total_risk_score", 5.0),
                "market_sentiment": parsed.get("market_sentiment", "neutral"),
            }

        except Exception as e:
            logger.error(f"Gemini allocation evaluation failed: {e}")
            return self._fallback_allocation(holdings_data)

    def _fallback_allocation(self, holdings: list[dict]) -> dict:
        """Equal-weight fallback if Gemini fails."""
        top = sorted(holdings, key=lambda h: h.get("total_return_pct", 0) or 0, reverse=True)[:3]
        if not top:
            return {"allocations": [], "total_risk_score": 0, "market_sentiment": "unknown"}
        pct = round(100 / len(top), 1)
        return {
            "allocations": [
                {"username": t["username"], "allocation_pct": pct, "reasoning": "Fallback — equal weight"}
                for t in top
            ],
            "total_risk_score": 5.0,
            "market_sentiment": "neutral",
        }

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
        """Build prompt for 3-trader allocation, injecting candidates explicitly."""
        # Format candidate list for insertion into ALLOCATION_PROMPT template
        candidate_lines = []
        for c in candidates[:10]:
            candidate_lines.append(
                f"  - {c.get('username', '?')} "
                f"(Risk: {c.get('risk_score', '?')}/10, "
                f"Return: {c.get('total_return_pct', '?')}%)"
            )
        candidate_block = "\n".join(candidate_lines) if candidate_lines else "  (none available)"

        # Fill the template
        prompt_header = ALLOCATION_PROMPT.format(available_candidates=candidate_block)
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

    async def _call_gemini(self, prompt: str, model=None) -> str:
        """Call Gemini API and return raw text response."""
        from google.api_core.exceptions import NotFound, ServiceUnavailable
        m = model or self._model
        try:
            response = await m.generate_content_async(prompt)
            return response.text
        except NotFound as e:
            logger.error(f"Gemini API model not found (404): {e}")
            raise RuntimeError("Gemini model not found — check model name and API version")
        except ServiceUnavailable as e:
            logger.error(f"Gemini API service unavailable (503): {e}")
            raise RuntimeError("Gemini API service unavailable — try again later")
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise RuntimeError(f"Gemini API error: {e}")

    def _parse_response(self, raw: str) -> dict:
        """Parse Gemini JSON response with safety net."""
        import re
        # Find the first { and last } — strips any preamble or markdown fences
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start == -1 or brace_end == -1:
            logger.error(f"Gemini returned no JSON object: {raw[:300]}")
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": "Failed to parse Gemini response",
                "recommended_swap": None,
            }
        cleaned = raw[brace_start : brace_end + 1].strip()

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Gemini returned non-JSON: {raw[:300]}")
            return {
                "action_required": False,
                "flagged_trader": None,
                "reasoning": "Failed to parse Gemini response",
                "recommended_swap": None,
            }

        return {
            "action_required": str(result.get("action_required", "")).lower() == "true",
            "flagged_trader": result.get("flagged_trader"),
            "reasoning": result.get("reasoning", "No reasoning provided"),
            "recommended_swap": result.get("recommended_swap"),
        }
