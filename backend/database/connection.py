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
if not DATABASE_URL:
    msg = (
        "\n╔══════════════════════════════════════════════════════════════╗\n"
        "║  FATAL: DATABASE_URL environment variable is not set.        ║\n"
        "║                                                              ║\n"
        "║  The application requires a database connection string.      ║\n"
        "║  Set DATABASE_URL in your environment or Render Dashboard.   ║\n"
        "║                                                              ║\n"
        "║  Example (Postgres on Render):                               ║\n"
        "║    postgresql://user:pass@host:5432/etoro_platform           ║\n"
        "║                                                              ║\n"
        "║  Example (local SQLite):                                     ║\n"
        "║    sqlite:///./etoro_platform.db                             ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
    )
    logger.critical(msg)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# 2. Build engine
# ─────────────────────────────────────────────────────────────────────
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

    # Migrate PostgreSQL enums (safe to re-run)
    if DATABASE_URL.startswith("postgresql"):
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("ALTER TYPE alerttype ADD VALUE IF NOT EXISTS 'MONITORING'"))
        logger.info("PostgreSQL enums migrated")

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
