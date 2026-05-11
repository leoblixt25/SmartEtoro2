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

# Attempt to import Groq SDK
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# Re‑use prompts from Gemini Scout for consistency
from backend.ai.gemini_scout import SYSTEM_PROMPT, ALLOCATION_PROMPT


class GroqScout:
    """Market scout powered by Groq Llama 3.3 70B model.

    It mirrors the GeminiScout API: ``evaluate`` for risk alerts and
    ``evaluate_portfolio`` for a 3‑trader allocation recommendation.
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("GROQ_API_KEY")
        if not GROQ_AVAILABLE:
            logger.warning("groq package not installed — Groq scout disabled")
            self.enabled = False
        elif not key:
            logger.warning("GROQ_API_KEY not set — Groq scout disabled")
            self.enabled = False
        else:
            self.client = Groq(api_key=key)
            self.enabled = True
            logger.info("Groq scout initialized with llama-3.3-70b-versatile")

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
            # Groq SDK is synchronous; run in a thread to avoid blocking the event loop
            import asyncio

            def _call():
                return self.client.chat.completions.create(
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
            import asyncio

            def _call():
                return self.client.chat.completions.create(
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
