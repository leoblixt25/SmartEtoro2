"""Centralized configuration for CopyVault backend.

All environment variable access lives here. No other module should
call os.environ directly — import from this module instead.
"""

import os
from typing import Optional


# ── eToro API ───────────────────────────────────────────────────────
ETORO_API_KEY: Optional[str] = os.environ.get("ETORO_API_KEY")
ETORO_API_SECRET: Optional[str] = os.environ.get("ETORO_API_SECRET")
ETORO_ACCOUNT_ID: str = os.environ.get("ETORO_ACCOUNT_ID", "")

# ── Telegram ────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USER_ID: Optional[str] = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
TELEGRAM_CHAT_ID: Optional[str] = os.environ.get("TELEGRAM_CHAT_ID")

# ── AI Providers ────────────────────────────────────────────────────
ANTHROPIC_API_KEY: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_API_KEY: Optional[str] = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY: Optional[str] = os.environ.get("GROQ_API_KEY")

# ── Deployment ──────────────────────────────────────────────────────
APP_ENV: str = os.environ.get("APP_ENV", "development")
RENDER_EXTERNAL_URL: str = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./etoro_platform.db")
ALLOWED_ORIGINS: str = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,https://smart-etoro2.vercel.app",
)
IS_SIMULATION: Optional[str] = os.environ.get("IS_SIMULATION")

# ── Derived ─────────────────────────────────────────────────────────
def is_production() -> bool:
    return APP_ENV == "production"

def is_simulation_mode() -> bool:
    """Determine simulation mode from env var. Returns True by default."""
    val = os.environ.get("IS_SIMULATION", "true")
    return val.lower() == "true"
