"""
Discovery Service — thin wrapper around discovery.pipeline.

All business logic is in backend/discovery/ (pipeline, score, validate, fetch).
This module exists solely for backward-compatible imports.
"""

from backend.discovery.pipeline import discover_eligible_traders

__all__ = ["discover_eligible_traders"]
