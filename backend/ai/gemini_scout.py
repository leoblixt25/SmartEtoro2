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
                model_name="gemini-2.5-flash",
                system_instruction=SYSTEM_PROMPT,
            )
            self.enabled = True
            logger.info("Gemini scout initialized with gemini-2.5-flash")

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

    async def _call_gemini(self, prompt: str) -> str:
        """Call Gemini API and return raw text response."""
        from google.api_core.exceptions import NotFound, ServiceUnavailable
        try:
            response = await self._model.generate_content_async(prompt)
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
