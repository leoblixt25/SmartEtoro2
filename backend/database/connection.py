"""
Database session management and FastAPI dependency injection.

Critical: DATABASE_URL must be set in the environment.
- On Render: set to your Postgres connection string.
- Locally: set to a SQLite file path (e.g. sqlite:///./etoro_platform.db).

If DATABASE_URL is missing, the application CRASHES immediately with
a clear error message — no silent fallback to an in-memory database.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.models import get_engine, get_session_factory, create_tables
import os
import sys
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# 1. Require DATABASE_URL – crash immediately if missing
# ─────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
# Hard fallback: if Neon URL persists in dashboard despite render.yaml, swap to Supabase
SUPABASE_URL = "postgresql://postgres:Woodgoat22.3@aws-0-us-east-2.pooler.supabase.com:5432/postgres"
if not DATABASE_URL:
    logger.warning("DATABASE_URL not set — using Supabase fallback")
    DATABASE_URL = SUPABASE_URL
elif "neon.tech" in DATABASE_URL:
    logger.warning("DATABASE_URL points to Neon (quota exceeded) — overriding to Supabase")
    DATABASE_URL = SUPABASE_URL

# ─────────────────────────────────────────────────────────────────────
# 2. Build engine
# ─────────────────────────────────────────────────────────────────────
# Append SSL requirement for Supabase
if DATABASE_URL.startswith("postgresql"):
    DATABASE_URL += "&sslmode=require" if "?" in DATABASE_URL else "?sslmode=require"

# Log the database host (without credentials) for debugging
db_host = DATABASE_URL.split("@")[1].split("?")[0] if DATABASE_URL.startswith("postgresql") else DATABASE_URL
logger.info(f"Database: {db_host}")
logger.info(f"Database backend: {'PostgreSQL' if DATABASE_URL.startswith('postgresql') else 'SQLite' if DATABASE_URL.startswith('sqlite') else 'other'}")

engine = get_engine(DATABASE_URL)
SessionLocal = get_session_factory(engine)


# ─────────────────────────────────────────────────────────────────────
# 3. Initialise tables
# ─────────────────────────────────────────────────────────────────────

def init_db():
    """Initialize database tables and verify connectivity.

    Calls create_tables (safe — never drops existing data).
    If the connection fails, the application crashes immediately.
    """
    logger.info("Verifying database connection…")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.scalar()
            logger.info("Database connection OK")
    except Exception as e:
        logger.critical(f"Database connection FAILED: {e}")
        sys.exit(1)

    create_tables(engine)

    # Migrate PostgreSQL schemas (safe to re-run)
    if DATABASE_URL.startswith("postgresql"):
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("ALTER TYPE alerttype ADD VALUE IF NOT EXISTS 'MONITORING'"))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS health_status VARCHAR"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS watch_consecutive INTEGER DEFAULT 0"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS take_profit_target_pct FLOAT"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS take_profit_triggered BOOLEAN DEFAULT FALSE"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS exit_return_pct FLOAT"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS watch_for_reentry BOOLEAN DEFAULT FALSE"
                ))
                conn.execute(text(
                    "ALTER TABLE copied_traders ADD COLUMN IF NOT EXISTS reentry_triggered BOOLEAN DEFAULT FALSE"
                ))
        logger.info("PostgreSQL schemas & enums migrated")

    # Enable WAL mode for SQLite (PostgreSQL handles this natively)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.commit()
        logger.info("SQLite WAL mode enabled")


# ─────────────────────────────────────────────────────────────────────
# 4. Session helpers
# ─────────────────────────────────────────────────────────────────────


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    """Context manager for use outside FastAPI request cycle (e.g., scheduler)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
