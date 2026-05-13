"""Scout orchestrator — ties together data fetching, scoring, and reporting.

This is the single entry point for both the Telegram /scout command
and the scheduled market scout job. Duplicate display logic that was
spread across telegram_service.py and scheduler.py is now consolidated here.
"""

import logging
from typing import Dict, List, Optional, Tuple

from backend.scout.scoring_engine import generate_scout_report, rank_traders
from backend.scout.trader_filter import filter_traders, deduplicate_traders, summarize_constraints
from backend.utils.constants import TARGET_COUNT

logger = logging.getLogger(__name__)


class ScoutRunner:
    """Orchestrates a full scout run.

    Flow:
        1. Load current holdings from DB
        2. Fetch market news (for context / AI narrator)
        3. Discover top trader candidates from API or fallback
        4. Filter candidates with hard constraints
        5. Score and rank both holdings and candidates
        6. Generate report with weakest holding, top swaps, avg score
        7. (Optional) Attach AI narrator summary
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
    ) -> Dict:
        """Execute a full scout run with the given data.

        Args:
            holdings: Current copied traders from DB.
            candidates: Discovered trader candidates.

        Returns:
            Dict with full scout report, always includes 'holdings_ranked',
            'candidates_ranked', and 'display' for Telegram/UI output.
        """
        if not holdings and not candidates:
            return self._empty_report("No trader data available to scout.")

        # Deduplicate and filter candidates
        candidates = deduplicate_traders(candidates)
        candidates_filtered = filter_traders(candidates)

        # Generate report
        report = generate_scout_report(holdings, candidates_filtered)

        # Build display text
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
            "total_holdings": 0,
            "total_candidates": 0,
            "display": f"⚠️ {reason}",
        }
        self._last_report = report
        return report

    def _format_report(self, report: Dict) -> List[str]:
        """Format the scout report into display-ready lines."""
        lines = []
        lines.append("📊 **Growth Scout Report**")
        lines.append("")

        # ── Holdings section ──
        holdings = report.get("holdings_ranked", [])
        lines.append(f"**Active Traders ({report['total_holdings']}):**")
        if holdings:
            for h in holdings:
                warnings = summarize_constraints(h)
                warn_str = f" ⚠️ {'; '.join(warnings)}" if warnings else ""
                lines.append(
                    f"  {h['username']} — **{h['final_score']}/100**"
                    f" (P:{h['performance_score']} R:{h['risk_score_category']}"
                    f" S:{h['stability_score']}){warn_str}"
                )
        else:
            lines.append("  No active copied traders found.")
        lines.append("")

        # ── Top swaps section ──
        swaps = report.get("top_swaps", [])
        lines.append(f"**Top Discovery Candidates ({report['total_candidates']} scanned):**")
        if swaps:
            for i, s in enumerate(swaps, 1):
                lines.append(
                    f"  {i}. {s['username']} — **{s['final_score']}/100**"
                    f" (return {s['total_return_pct']:.1f}%, risk {s['risk_score']:.1f})"
                )
        else:
            lines.append("  No viable candidates found.")
        lines.append("")

        # ── Summary ──
        weakest = report.get("weakest")
        if weakest:
            lines.append(
                f"🔻 **Weakest holding:** {weakest['username']}"
                f" ({weakest['final_score']}/100)"
            )
        lines.append(f"📈 **Portfolio avg score:** {report['avg_score']}/100")
        lines.append(f"🏆 **Recommendation:** {swaps[0]['username']} ({swaps[0]['final_score']}/100)"
                      if swaps else "")

        return lines


# ── Module-level convenience ────────────────────────────────────────

_runner: Optional[ScoutRunner] = None


def get_scout_runner() -> ScoutRunner:
    global _runner
    if _runner is None:
        _runner = ScoutRunner()
    return _runner
