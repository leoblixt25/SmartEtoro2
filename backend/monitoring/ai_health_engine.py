"""
AI-Powered Trader Health Engine — uses OpenAI/OpenRouter GPT to analyze traders.
Falls back to rule-based engine if AI is unavailable.
"""
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AI_AVAILABLE = False
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

try:
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY", "")
    AI_AVAILABLE = bool(key)
except ImportError:
    pass

SYSTEM_PROMPT = """You are an elite copy-trading portfolio analyst specializing in eToro Popular Investors.

Your job: analyze copied traders and return structured JSON. Be conservative and honest.

RULES:
- Never invent missing values
- Never treat missing data as proof a trader is bad
- Missing data lowers confidence, not score
- If day/week/month return all missing and no total_return_pct exists → incomplete
- use UNCOPY only with real negative evidence (high risk, high drawdown, consistent losses)
- If evidence is weak, recommend REVIEW instead

SCORING (out of 100):
85-100 = Elite | 75-84 = Strong | 65-74 = Good | 55-64 = Watch
40-54 = Weak | Below 40 = Avoid | null = Cannot evaluate

CONFIDENCE:
HIGH = most fields present | MEDIUM = some gaps | LOW = limited data | INCOMPLETE = insufficient

ACTIONS:
KEEP = stable & acceptable | REDUCE = good but risk rising | PAUSE = elevated uncertainty
REVIEW = too little data | UNCOPY = clear negative evidence only

NEWS RISK: low | medium | high | unknown

Return ONLY valid JSON — an array of objects (one per trader), each matching this schema:
{
  "name": "username",
  "score": number or null,
  "confidence": "HIGH|MEDIUM|LOW|INCOMPLETE",
  "status": "ELITE|STRONG|GOOD|WATCH|WEAK|AVOID|INCOMPLETE",
  "action": "KEEP|REDUCE|PAUSE|REVIEW|UNCOPY",
  "reason": "short specific reason under 120 chars",
  "news_risk": "low|medium|high|unknown",
  "performance": {"day": null, "week": null, "month": null},
  "risk": {"drawdown": null, "risk_score": null, "leverage": null, "concentration": null}
}"""


def _build_trader_text(traders_data: List[Dict]) -> str:
    """Format trader data for the AI prompt."""
    lines = ["Analyze these copied traders:\n"]
    for td in traders_data:
        lines.append(f"Trader: {td.get('username', '?')}")
        # Performance
        perf_parts = []
        for k in ["return_1d", "return_1w", "return_1m"]:
            v = td.get(k)
            if v is not None:
                perf_parts.append(f"{k}={v:+.2f}%")
        lines.append(f"  Performance: {', '.join(perf_parts) if perf_parts else 'N/A'}")
        lines.append(f"  Total return: {td.get('total_return_pct', 'N/A')}%")
        # Risk
        lines.append(f"  Risk score: {td.get('risk_score', 'N/A')}")
        lines.append(f"  Max drawdown: {td.get('max_drawdown', 'N/A')}%")
        lines.append(f"  Volatility: {td.get('volatility', 'N/A')}")
        lines.append(f"  Consistency: {td.get('consistency_score', 'N/A')}")
        lines.append(f"  Allocation: {td.get('allocation_pct', 'N/A')}%")
        lines.append(f"  Holdings: {len(td.get('_holdings', []))} positions")
        lines.append(f"  News: {td.get('_news_summary', 'N/A')}")
        lines.append("")
    return "\n".join(lines)


def _parse_ai_response(text: str) -> Optional[List[Dict]]:
    """Extract JSON from AI response (handles markdown fences, trailing text, single-object)."""
    text = text.strip()
    # Extract JSON from markdown code block if present
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Also strip any remaining closing fence
    text = text.split("```")[0].strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "traders" in data:
                return data["traders"]
            if "name" in data:
                return [data]
    except json.JSONDecodeError:
        pass
    return None


async def ai_analyze_traders(traders_data: List[Dict]) -> Optional[List[Dict]]:
    """Analyze all traders via OpenAI/OpenRouter. Returns list of result dicts or None on failure."""
    if not AI_AVAILABLE:
        logger.info("AI engine unavailable (no API key)")
        return None

    api_key = os.environ["OPENAI_API_KEY"]
    is_openrouter = api_key.startswith("sk-or-")
    client_kwargs = {"api_key": api_key}
    if is_openrouter:
        client_kwargs["base_url"] = OPENROUTER_BASE
        logger.info("Using OpenRouter API")

    client = OpenAI(**client_kwargs)
    trader_text = _build_trader_text(traders_data)
    model = "openai/gpt-4o-mini" if is_openrouter else "gpt-4o-mini"

    extra_headers = {}
    if is_openrouter:
        extra_headers = {
            "HTTP-Referer": "https://github.com/leoblixt25/SmartEtoro2",
            "X-Title": "SmartEtoro2",
        }

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": trader_text},
            ],
            temperature=0.1,
            max_tokens=2000,
            extra_headers=extra_headers if extra_headers else None,
        )
        raw = response.choices[0].message.content
        results = _parse_ai_response(raw)
        if not results:
            logger.error(f"AI returned unparseable JSON: {raw[:200]}")
            return None

        # Validate: every trader must have required fields
        for r in results:
            r.setdefault("score", None)
            r.setdefault("confidence", "LOW")
            r.setdefault("status", "INCOMPLETE")
            r.setdefault("action", "REVIEW")
            r.setdefault("reason", "AI analysis")
            r.setdefault("news_risk", "unknown")
            r.setdefault("performance", {"day": None, "week": None, "month": None})
            r.setdefault("risk", {"drawdown": None, "risk_score": None, "leverage": None, "concentration": None})

        return results

    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return None
