"""
AI-Powered Trader Health Engine — uses OpenAI/OpenRouter/Groq to analyze traders.
Falls back to rule-based engine if AI is unavailable.
"""
import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AI_AVAILABLE = False

# Provider configs
PROVIDERS = {
    "openai": {"base_url": None, "key_prefix": "sk-proj-"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_prefix": "sk-or-"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_prefix": "gsk_"},
}

try:
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
    AI_AVAILABLE = bool(key)
except ImportError:
    pass

SYSTEM_PROMPT = """You are an elite copy-trading portfolio analyst specializing in eToro Popular Investors.

Your job: analyze copied traders and return structured JSON. Be honest and pragmatic.

RULES:
- Never invent missing values, but DO use what IS available
- total_return_pct + allocation_pct are SUFFICIENT to make a call
- Negative returns on big allocations = UNCOPY (real losses)
- Positive returns = KEEP (even if small)
- Near-zero returns with tiny allocations = REVIEW (no action needed)
- UNCOPY only for clear negative evidence (losses on >5% allocation or >3% loss)
- Be decisive — "REVIEW" means "do nothing for now" not "wait for more data"
- A -0.1% return on 1% allocation is NOTHING — call it REVIEW

SCORING (out of 100):
85-100 = Elite | 75-84 = Strong | 65-74 = Good | 55-64 = Watch
40-54 = Weak | Below 40 = Avoid | null = Cannot evaluate

CONFIDENCE:
HIGH = has return + allocation + some risk data
MEDIUM = has return + allocation only
LOW = only return or only allocation
INCOMPLETE = neither

ACTIONS:
KEEP = positive return or strong fundamentals
REDUCE = negative return, moderate allocation (5-15%)
UNCOPY = negative return on >5% allocation, or any >3% loss
REVIEW = everything else (tiny positions, near-zero returns)

NEWS RISK: low | medium | high | unknown

Return ONLY valid JSON — a JSON object with a "traders" key containing an array of objects (one per trader), each matching this schema:
{
  "name": "username",
  "score": number or null,
  "confidence": "HIGH|MEDIUM|LOW|INCOMPLETE",
  "status": "ELITE|STRONG|GOOD|WATCH|WEAK|AVOID|INCOMPLETE",
  "action": "KEEP|REDUCE|UNCOPY|REVIEW",
  "reason": "short specific reason under 120 chars",
  "news_risk": "low|medium|high|unknown",
  "performance": {"day": null, "week": null, "month": null},
  "risk": {"drawdown": null, "risk_score": null, "leverage": null, "concentration": null}
}"""


def _build_trader_text(traders_data: List[Dict], portfolio_summary: Optional[Dict] = None) -> str:
    """Format trader data for the AI prompt with clean metrics."""
    lines = []
    if portfolio_summary:
        lines.append("Portfolio:")
        lines.append(f"  Invested: ${portfolio_summary.get('total_invested_capital', 0):,.2f}")
        lines.append(f"  Value: ${portfolio_summary.get('total_portfolio_value', 0):,.2f}")
        lines.append(f"  Cash: ${portfolio_summary.get('total_available_cash', 0):,.2f}")
        lines.append("")
    lines.append("Traders:")
    for td in traders_data:
        lines.append(f"- {td.get('username', '?')}:")
        lines.append(f"  allocation={td.get('allocation_pct', 'N/A')}%")
        lines.append(f"  return={td.get('total_return_pct', 'N/A')}%")
        lines.append(f"  risk={td.get('risk_score', 'N/A')}")
        lines.append(f"  dd={td.get('max_drawdown', 'N/A')}%")
        lines.append(f"  holdings={len(td.get('_holdings', []))}")
        lines.append(f"  news={td.get('_news_summary', 'N/A')}")
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


async def ai_analyze_traders(traders_data: List[Dict], portfolio_summary: Optional[Dict] = None) -> Optional[List[Dict]]:
    """Analyze all traders via OpenAI/OpenRouter/Groq. Returns list of result dicts or None on failure."""
    if not AI_AVAILABLE:
        logger.info("AI engine unavailable (no API key)")
        return None

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""

    # Detect provider by key prefix
    provider = "openai"
    for name, cfg in PROVIDERS.items():
        if api_key.startswith(cfg["key_prefix"]):
            provider = name
            break

    extra_headers = {}
    if provider == "groq":
        base_url = PROVIDERS["groq"]["base_url"]
        model = "llama-3.3-70b-versatile"
        logger.info("Using Groq API (free)")
    elif provider == "openrouter":
        base_url = PROVIDERS["openrouter"]["base_url"]
        model = "openai/gpt-4o-mini"
        extra_headers = {
            "HTTP-Referer": "https://github.com/leoblixt25/SmartEtoro2",
            "X-Title": "SmartEtoro2",
        }
        logger.info("Using OpenRouter API")
    else:
        base_url = None  # default OpenAI
        model = "gpt-4o-mini"
        logger.info("Using OpenAI API")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    trader_text = _build_trader_text(traders_data, portfolio_summary)

    # Groq supports JSON mode
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": trader_text},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    if extra_headers:
        kwargs["extra_headers"] = extra_headers
    if provider == "groq":
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
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
