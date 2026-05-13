"""Scout orchestrator — ties together data fetching, scoring, and reporting.

This is the single entry point for both the Telegram /scout command
and the scheduled market scout job. Duplicate display logic that was
spread across telegram_service.py and scheduler.py is now consolidated here.
"""

import logging
from typing import Dict, List, Optional

from backend.scout.scoring_engine import (
    generate_scout_report,
    rank_traders,
    explain_recommendation,
    explain_exclusion,
)
from backend.scout.trader_filter import (
    filter_traders,
    deduplicate_traders,
    summarize_constraints,
    eligibility_filter,
)
from backend.utils.constants import TARGET_COUNT

logger = logging.getLogger(__name__)


class ScoutRunner:
    """Orchestrates a full scout run.

    Flow:
        1. Load current holdings from DB
        2. Fetch market news (for context / AI narrator)
        3. Discover top trader candidates from API or fallback
        4. Deduplicate candidates
        5. Apply eligibility filter (already-copied, capital, risk, activity)
        6. Apply hard constraint filters (drawdown, risk ceiling, return floor)
        7. Score and rank both holdings and candidates
        8. Generate report with weakest holding, top swaps, avg score
        9. (Optional) Attach AI narrator summary
    """

    def __init__(self):
        self._last_report: Optional[Dict] = None

    @property
    def last_report(self) -> Optional[Dict]:
        return self._last_report

    async def run(
        self,
        holdings: List[Dict],
        candidates: List[Dict],
        available_balance: float = 0.0,
    ) -> Dict:
        """Execute a full scout run with the given data.

        Args:
            holdings: Current copied traders from DB.
            candidates: Discovered trader candidates.
            available_balance: Available cash/capital for new copies.

        Returns:
            Dict with full scout report, always includes 'holdings_ranked',
            'candidates_ranked', 'excluded_candidates', and 'display'.
        """
        if not holdings and not candidates:
            return self._empty_report("No trader data available to scout.")

        total_discovered = len(candidates)

        # ── 1. Deduplicate ──
        candidates = deduplicate_traders(candidates)

        # ── 2. Build holdings username set (case-insensitive) ──
        holdings_usernames = {
            h.get("username", "").lower()
            for h in holdings
            if h.get("username")
        }

        # ── 3. Eligibility filter (pre-scoring) ──
        eligible, excluded = eligibility_filter(
            candidates,
            holdings_usernames,
            available_balance,
        )

        already_copied_count = sum(
            1 for e in excluded
            if "already_copied" in (e.get("exclusion_reasons") or [])
        )
        capital_excluded = sum(
            1 for e in excluded
            if any("insufficient_capital" in r for r in (e.get("exclusion_reasons") or []))
        )
        other_excluded = len(excluded) - already_copied_count - capital_excluded

        # ── 4. Hard constraints filter (on eligible only) ──
        eligible_filtered = filter_traders(eligible)
        hard_rejected = len(eligible) - len(eligible_filtered)

        # ── 5. Logging ──
        logger.info(
            f"Found {total_discovered} traders | "
            f"already_copied={already_copied_count}, "
            f"capital_excluded={capital_excluded}, "
            f"hard_rejected={hard_rejected}, "
            f"other_excluded={other_excluded}, "
            f"eligible={len(eligible_filtered)}"
        )

        # ── 6. Generate report ──
        report = generate_scout_report(holdings, eligible_filtered)

        # ── 7. Attach eligibility info ──
        report["excluded_candidates"] = excluded
        report["eligible_count"] = len(eligible_filtered)
        report["excluded_counts"] = {
            "already_copied": already_copied_count,
            "insufficient_capital": capital_excluded,
            "hard_constraints": hard_rejected,
            "other": other_excluded,
            "total": len(excluded) + hard_rejected,
        }

        # ── 8. Add explanations to top swaps (if any) ──
        top_swaps = report.get("top_swaps", [])
        for s in top_swaps:
            s["why"] = explain_recommendation(s)

        # ── 9. Build display text ──
        display_lines = self._format_report(report)
        report["display"] = "\n".join(display_lines)

        self._last_report = report
        return report

    def _empty_report(self, reason: str) -> Dict:
        report = {
            "weakest": None,
            "top_swaps": [],
            "avg_score": 0.0,
            "holdings_ranked": [],
            "candidates_ranked": [],
            "eligible_count": 0,
            "excluded_candidates": [],
            "excluded_counts": {
                "already_copied": 0,
                "insufficient_capital": 0,
                "hard_constraints": 0,
                "other": 0,
                "total": 0,
            },
            "total_holdings": 0,
            "total_candidates": 0,
            "display": f"\u26a0\ufe0f {reason}",
        }
        self._last_report = report
        return report

    def _format_report(self, report: Dict) -> List[str]:
        """Format the scout report into display-ready lines."""
        lines = []
        lines.append("\U0001f4ca **Growth Scout Report**")
        lines.append("")

        exc_counts = report.get("excluded_counts", {})

        # ── Holdings section ──
        holdings = report.get("holdings_ranked", [])
        lines.append(f"**Active Traders ({report['total_holdings']}):**")
        if holdings:
            for h in holdings:
                warnings = summarize_constraints(h)
                warn_str = f" \u26a0\ufe0f {'; '.join(warnings)}" if warnings else ""
                lines.append(
                    f"  {h['username']} \u2014 **{h['final_score']}/100**"
                    f" (P:{h['performance_score']} R:{h['risk_score_category']}"
                    f" S:{h['stability_score']}){warn_str}"
                )
        else:
            lines.append("  No active copied traders found.")
        lines.append("")

        # ── Candidates section ──
        swaps = report.get("top_swaps", [])
        total_eligible = report.get("eligible_count", 0)
        total_excluded = exc_counts.get("total", 0)
        total_scanned = total_eligible + total_excluded

        lines.append(
            f"**Top Discovery Candidates** "
            f"({total_eligible} eligible / {total_excluded} excluded / {total_scanned} scanned):"
        )

        if swaps:
            for i, s in enumerate(swaps, 1):
                why = s.get("why", [])
                why_str = ""
                if why:
                    bullet_reasons = "\n      ".join(why)
                    why_str = f"\n      Why: {bullet_reasons}"
                lines.append(
                    f"  {i}. {s['username']} \u2014 **{s['final_score']}/100**"
                    f" (return {s['total_return_pct']:.1f}%, risk {s['risk_score']:.1f}){why_str}"
                )
        else:
            if total_eligible == 0:
                lines.append("  \u26a0\ufe0f No eligible traders found for your balance/risk profile.")
            else:
                lines.append("  No viable candidates found.")

        # ── Excluded summary ──
        excluded = report.get("excluded_candidates", [])
        if excluded:
            lines.append("")
            lines.append(f"**Excluded ({len(excluded)}):**")
            for ex in excluded[:5]:  # show top 5
                reasons = explain_exclusion(ex)
                short = "; ".join(reasons)
                lines.append(f"  \u274c {ex.get('username', '?')} \u2014 {short}")
            if len(excluded) > 5:
                lines.append(f"  ... and {len(excluded) - 5} more excluded")
        lines.append("")

        # ── Summary ──
        weakest = report.get("weakest")
        if weakest:
            lines.append(
                f"\U0001f53b **Weakest holding:** {weakest['username']}"
                f" ({weakest['final_score']}/100)"
            )
        lines.append(f"\U0001f4c8 **Portfolio avg score:** {report['avg_score']}/100")
        if swaps:
            lines.append(
                f"\U0001f3c6 **Recommendation:** {swaps[0]['username']} ({swaps[0]['final_score']}/100)"
            )

        return lines


# ── Module-level convenience ────────────────────────────────────────

_runner: Optional[ScoutRunner] = None


def get_scout_runner() -> ScoutRunner:
    global _runner
    if _runner is None:
        _runner = ScoutRunner()
    return _runner
