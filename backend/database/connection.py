"""
Database session management and FastAPI dependency injection.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy.orm import Session
from backend.database.models import get_engine, get_session_factory, create_tables
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./etoro_platform.db")

engine = get_engine(DATABASE_URL)
SessionLocal = get_session_factory(engine)


def init_db():
    """Initialize database tables on startup."""
    create_tables(engine)
    # Enable WAL mode for SQLite (PostgreSQL handles this natively)
    if DATABASE_URL.startswith("sqlite"):
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.commit()


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
