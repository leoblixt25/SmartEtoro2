"""
Screener Service
────────────────────────────────────────────────────────────────────
5-stage mass discovery engine for scanning 5,000-10,000+ eToro traders.

Stages:
  1. Mass Discovery — lightweight metadata from search API (concurrent)
  2. Hard Filtering  — remove weak candidates before deep analysis
  3. Deep Analysis   — tradeinfo enrichment for filtered candidates
  4. Scoring Engine  — weighted component scoring (return/risk-adjusted/
                       consistency/drawdown/risk/trend)
  5. Final Selection — top N ranked candidates
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from backend.discovery.config import (
    SCAN_PRESETS,
    ESTIMATED_TIMES,
    DISCOVERY_TOP_N,
    MIN_FINAL_SCORE_FOR_RECOMMENDATION,
    CONSTRAINT_MAX_DRAWDOWN,
    CONSTRAINT_MAX_RISK,
    CONSTRAINT_MIN_WEEKS,
)
from backend.discovery.score import calculate_growth_score
from backend.services.etoro_service import EToroAPIClient

logger = logging.getLogger(__name__)

# ── In-memory progress store ──────────────────────────────────────
_screener_jobs: Dict[str, dict] = {}


def _next_run_id() -> str:
    return uuid.uuid4().hex[:12]


def get_job(run_id: str) -> Optional[dict]:
    return _screener_jobs.get(run_id)


# ── Progress helpers ──────────────────────────────────────────────


def _make_progress(
    stage: int,
    stage_name: str,
    pct: float,
    detail: str = "",
    discovered: int = 0,
    after_filter: int = 0,
    enriched: int = 0,
    scored: int = 0,
    final_count: int = 0,
) -> dict:
    return {
        "stage": stage,
        "stage_name": stage_name,
        "pct": pct,
        "detail": detail,
        "discovered": discovered,
        "after_filter": after_filter,
        "enriched": enriched,
        "scored": scored,
        "final_count": final_count,
    }


# ── Stage 1: Mass Discovery ──────────────────────────────────────


async def _stage_mass_discovery(
    client: EToroAPIClient,
    target: int,
    progress_callback: Callable[[dict], None],
) -> List[Dict]:
    """Fetch lightweight metadata for up to `target` traders."""
    logger.info("Stage 1: Mass discovery — target %d traders", target)
    progress_callback(_make_progress(1, "Mass Discovery", 0, f"Scanning {target} traders..."))

    candidates = await client.discover_bulk(target=target, max_concurrent=10)

    progress_callback(_make_progress(
        1, "Mass Discovery", 100,
        f"Found {len(candidates)} candidates",
        discovered=len(candidates),
    ))
    logger.info("Stage 1 complete: %d lightweight candidates", len(candidates))
    return candidates


# ── Stage 2: Hard Filtering ──────────────────────────────────────


def _stage_hard_filter(
    candidates: List[Dict],
    progress_callback: Callable[[dict], None],
) -> List[Dict]:
    """Remove weak candidates using only lightweight metadata.

    Filters on: risk, return range, weeks registered, missing data, drawdown hints.
    """
    logger.info("Stage 2: Hard filtering — %d candidates in", len(candidates))

    passed = []
    rejected_no_data = 0
    rejected_risk = 0
    rejected_return = 0
    rejected_weeks = 0

    for c in candidates:
        username = c.get("username", "?")
        risk = c.get("risk_score")
        ret = c.get("total_return_pct")
        weeks = c.get("weeks_since_registration")

        # No meaningful data at all
        if not risk and not ret:
            rejected_no_data += 1
            continue

        # Risk too high
        if risk is not None and risk > CONSTRAINT_MAX_RISK:
            rejected_risk += 1
            continue

        # Return too low / missing
        if ret is None or ret <= 0:
            rejected_return += 1
            continue

        # Too new
        if weeks is not None and weeks < CONSTRAINT_MIN_WEEKS:
            rejected_weeks += 1
            continue

        passed.append(c)

    progress_callback(_make_progress(
        2, "Hard Filtering", 100,
        f"{len(passed)} passed / {len(candidates)} total "
        f"(risk:{rejected_risk} return:{rejected_return} weeks:{rejected_weeks} nodata:{rejected_no_data})",
        discovered=len(candidates),
        after_filter=len(passed),
    ))

    logger.info(
        "Stage 2 complete: %d/%d passed (risk:%d return:%d weeks:%d nodata:%d)",
        len(passed), len(candidates),
        rejected_risk, rejected_return, rejected_weeks, rejected_no_data,
    )
    return passed


# ── Stage 3: Deep Analysis ───────────────────────────────────────


async def _stage_deep_analysis(
    client: EToroAPIClient,
    candidates: List[Dict],
    progress_callback: Callable[[dict], None],
    max_concurrent: int = 10,
) -> Tuple[List[Dict], List[Dict]]:
    """Enrich filtered candidates with full tradeinfo data."""
    logger.info("Stage 3: Deep analysis — %d candidates", len(candidates))

    usernames = [c["username"] for c in candidates]
    progress_callback(_make_progress(
        3, "Deep Analysis", 0,
        f"Enriching {len(usernames)} traders...",
        after_filter=len(usernames),
    ))

    result = await client.enrich_candidates(usernames, max_concurrent=max_concurrent)

    available = result.get("available", [])
    unavailable = result.get("unavailable", [])
    scanned = result.get("scanned", 0)

    # Merge lightweight metadata into enriched results
    lookup = {c["username"]: c for c in candidates}
    for a in available:
        light = lookup.get(a.get("username", ""), {})
        for k in ("risk_score", "total_return_pct", "copiers", "weeks_since_registration", "country"):
            if a.get(k) is None and light.get(k) is not None:
                a[k] = light[k]

    progress_callback(_make_progress(
        3, "Deep Analysis", 100,
        f"{len(available)} enriched, {len(unavailable)} unavailable",
        after_filter=len(candidates),
        enriched=len(available),
    ))

    logger.info(
        "Stage 3 complete: %d enriched, %d unavailable (scanned: %d)",
        len(available), len(unavailable), scanned,
    )
    return available, unavailable


# ── Stage 4: Scoring Engine ──────────────────────────────────────


def _stage_scoring(
    enriched: List[Dict],
    progress_callback: Callable[[dict], None],
) -> List[Dict]:
    """Score all enriched candidates using the weighted engine."""
    logger.info("Stage 4: Scoring — %d candidates", len(enriched))

    scored = []
    for i, c in enumerate(enriched):
        result = calculate_growth_score(c)
        scored.append({**c, **result})
        if (i + 1) % 50 == 0:
            progress_callback(_make_progress(
                4, "Scoring", round((i + 1) / len(enriched) * 100, 1),
                f"Scored {i + 1}/{len(enriched)} traders",
                enriched=len(enriched),
                scored=len(scored),
            ))

    # Filter
    qualified = [s for s in scored if s.get("final_score", 0) >= MIN_FINAL_SCORE_FOR_RECOMMENDATION]
    qualified.sort(key=lambda x: x["final_score"], reverse=True)

    progress_callback(_make_progress(
        4, "Scoring", 100,
        f"{len(qualified)} qualified above threshold",
        enriched=len(enriched),
        scored=len(qualified),
    ))

    logger.info(
        "Stage 4 complete: %d scored, %d qualified above %.0f",
        len(scored), len(qualified), MIN_FINAL_SCORE_FOR_RECOMMENDATION,
    )
    return qualified


# ── Stage 5: Final Selection ─────────────────────────────────────


def _stage_final_selection(
    qualified: List[Dict],
    top_n: int,
    progress_callback: Callable[[dict], None],
) -> List[Dict]:
    """Select top N traders for final output."""
    top = qualified[:top_n]
    progress_callback(_make_progress(
        5, "Final Selection", 100,
        f"Top {len(top)} of {len(qualified)}",
        discovered=0,
        after_filter=0,
        enriched=len(qualified),
        scored=len(top),
        final_count=len(top),
    ))
    logger.info("Stage 5 complete: %d finalists from %d qualified", len(top), len(qualified))
    return top


# ── Full pipeline ────────────────────────────────────────────────


async def _run_pipeline(
    scan_target: int,
    top_n: int,
    max_concurrent: int,
    progress_callback: Callable[[dict], None],
) -> Tuple[Optional[List[Dict]], Optional[List[Dict]], Optional[dict]]:
    """Run stages 1-5 and return (top, excluded, stats) or (None, None, None) on failure."""
    start_ts = time.time()
    client = EToroAPIClient()

    # Stage 1
    candidates = await _stage_mass_discovery(client, scan_target, progress_callback)
    if not candidates:
        progress_callback(_make_progress(5, "Complete", 100, "No candidates found"))
        return None, None, None

    # Stage 2
    filtered = _stage_hard_filter(candidates, progress_callback)
    if not filtered:
        progress_callback(_make_progress(5, "Complete", 100, "No traders passed filters"))
        return None, None, None

    # Stage 3
    enriched, unavailable = await _stage_deep_analysis(client, filtered, progress_callback, max_concurrent)
    if not enriched:
        progress_callback(_make_progress(5, "Complete", 100, "No traders could be enriched"))
        return None, None, None

    # Stage 4
    qualified = _stage_scoring(enriched, progress_callback)

    # Stage 5
    top = _stage_final_selection(qualified, top_n, progress_callback)

    elapsed = round(time.time() - start_ts, 1)
    stats = {
        "discovered": len(candidates),
        "after_filter": len(filtered),
        "enriched": len(enriched),
        "unavailable": len(unavailable),
        "qualified": len(qualified),
        "final_count": len(top),
        "duration_seconds": elapsed,
    }
    return top, unavailable, stats


async def run_screener(
    portfolio_id: int,
    scan_target: int = 2000,
    top_n: int = DISCOVERY_TOP_N,
    max_concurrent: int = 10,
) -> Tuple[str, dict]:
    """Run the 5-stage screener pipeline in a background task.

    Returns (run_id, initial_progress). Poll GET /api/screener/{run_id}
    for completion.
    """
    run_id = _next_run_id()
    _screener_jobs[run_id] = _make_progress(0, "Starting", 0, "Initializing...")

    def _update(progress: dict) -> None:
        _screener_jobs[run_id] = progress

    async def _run():
        try:
            top, unavailable, stats = await _run_pipeline(scan_target, top_n, max_concurrent, _update)
            if top is None:
                return
            elapsed = stats["duration_seconds"]
            _screener_jobs[run_id] = {
                "stage": 5,
                "stage_name": "Complete",
                "pct": 100,
                "detail": f"Done in {elapsed}s \u2014 {len(top)} finalists",
                "results": top,
                "excluded": unavailable or [],
                "stats": stats,
            }
            logger.info("Screener %s complete: %s", run_id, stats)
        except Exception as e:
            logger.exception("Screener %s failed: %s", run_id, e)
            _screener_jobs[run_id] = {
                "stage": -1, "stage_name": "Error", "pct": 0,
                "detail": str(e), "error": str(e),
            }

    asyncio.create_task(_run())
    return run_id, _screener_jobs[run_id]


async def run_screener_and_wait(
    scan_target: int = 10000,
    top_n: int = DISCOVERY_TOP_N,
    max_concurrent: int = 10,
) -> Tuple[List[Dict], List[Dict], Dict]:
    """Run the 5-stage pipeline synchronously (awaited) and return results.

    Returns (top_candidates, excluded, stats) — same shape as
    the legacy discover_eligible_traders() for backward compatibility.
    """
    progress = {"pct": 0}

    def _update(p: dict) -> None:
        progress.update(p)
        if p.get("pct", 0) % 25 == 0 or p.get("stage_name") in ("Mass Discovery", "Deep Analysis"):
            logger.info("Screener [%s]: %s \u2014 %s", p.get("stage_name", "?"), p.get("detail", ""), p.get("pct", 0))

    top, unavailable, stats = await _run_pipeline(scan_target, top_n, max_concurrent, _update)
    if top is None:
        return [], [], stats or {"error": "No results", "duration_seconds": 0}
    return top, unavailable or [], stats
