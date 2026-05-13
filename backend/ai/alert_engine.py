"""
Alert Engine — smart deduplicated notifications.

Only fires when something meaningful changes:
  - New eligible trader discovered
  - A copied trader becomes risky (score drops below 40)
  - Portfolio concentration exceeds 40%
  - A recommended swap becomes available

Stateful: tracks previously sent alerts and suppresses duplicates.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertEngine:
    """Stateful alert deduplication engine.

    Stores a snapshot of the last notified state per portfolio.
    An alert fires only when the current state differs from the snapshot.
    """

    def __init__(self):
        self._previous_state: Dict[int, Dict] = {}

    def evaluate(
        self,
        portfolio_id: int,
        portfolio_analysis: Dict,
        discovery_scored: List[Dict],
        excluded: List[Dict],
        action_plan: Dict,
    ) -> List[Dict]:
        """Compare current state to previous and return new alerts.

        Returns a list of alert dicts with keys:
          - alert_type: str
          - severity: str (info/warning/alert)
          - title: str
          - message: str
          - is_new: bool (True if this is a state change)
        """
        alerts = []
        prev = self._previous_state.get(portfolio_id, {})

        current_state = self._build_state(portfolio_analysis, discovery_scored, excluded, action_plan)

        # 1. New eligible trader discovered
        prev_eligible = set(prev.get("eligible_usernames", []))
        current_eligible = set(current_state.get("eligible_usernames", []))
        new_eligible = current_eligible - prev_eligible
        for username in new_eligible:
            trader_data = next(
                (s for s in discovery_scored if s.get("username") == username),
                None,
            )
            score = (trader_data or {}).get("score", 0)
            explanation = (trader_data or {}).get("explanation", [])
            alerts.append({
                "alert_type": "new_eligible_trader",
                "severity": "info",
                "title": f"New eligible trader: {username}",
                "message": (
                    f"New eligible trader: {username} (score {score}/100)\n"
                    f"Reasons: {'; '.join(str(e) for e in explanation[:3])}"
                ),
                "is_new": True,
            })

        # 2. Copied trader became risky (score dropped below threshold)
        prev_risky = set(prev.get("risky_traders", []))
        current_risky = set(current_state.get("risky_traders", []))
        newly_risky = current_risky - prev_risky
        for username in newly_risky:
            alerts.append({
                "alert_type": "trader_became_risky",
                "severity": "warning",
                "title": f"Risk alert: {username}",
                "message": f"Active trader {username} score dropped below 40 — review suggested",
                "is_new": True,
            })

        # 3. Over-concentration
        prev_concern = prev.get("concentration_risk", False)
        current_concern = current_state.get("concentration_risk", False)
        if current_concern and not prev_concern:
            alerts.append({
                "alert_type": "overconcentration",
                "severity": "warning",
                "title": "Portfolio concentration risk",
                "message": "A single trader exceeds 40% allocation — consider rebalancing",
                "is_new": True,
            })

        # 4. Swap opportunity appeared (recommended swap is new)
        prev_swap = prev.get("recommended_swap")
        current_swap = current_state.get("recommended_swap")
        if current_swap and current_swap != prev_swap:
            alerts.append({
                "alert_type": "swap_opportunity",
                "severity": "info",
                "title": f"Recommended swap: {current_swap}",
                "message": action_plan.get("summary", ""),
                "is_new": True,
            })

        # 5. New exclusion (trader newly blocked/changed status)
        prev_excluded_names = set(prev.get("excluded_usernames", []))
        current_excluded_names = set(current_state.get("excluded_usernames", []))
        newly_excluded = current_excluded_names - prev_excluded_names
        for username in newly_excluded:
            alerts.append({
                "alert_type": "trader_excluded",
                "severity": "info",
                "title": f"Trader excluded: {username}",
                "message": f"{username} is no longer eligible for copying",
                "is_new": True,
            })

        # Update state
        self._previous_state[portfolio_id] = current_state

        if alerts:
            logger.info("AlertEngine: %d new alert(s) for portfolio %d", len(alerts), portfolio_id)

        return alerts

    def _build_state(
        self,
        portfolio_analysis: Dict,
        discovery_scored: List[Dict],
        excluded: List[Dict],
        action_plan: Dict,
    ) -> Dict:
        """Build a hashable snapshot of the current state for comparison."""
        risky_threshold = 40

        return {
            "eligible_usernames": sorted(
                s.get("username", "") for s in discovery_scored if s.get("score", 0) > 0
            ),
            "risky_traders": sorted(
                h.get("username", "")
                for h in portfolio_analysis.get("holdings_detail", [])
                if h.get("final_score", 100) < risky_threshold
            ),
            "concentration_risk": portfolio_analysis.get("concentration_risk", False),
            "recommended_swap": action_plan.get("recommended_swap"),
            "excluded_usernames": sorted(
                e.get("username", "") for e in excluded
            ),
        }

    def reset(self, portfolio_id: Optional[int] = None) -> None:
        """Reset stored state for a portfolio (or all if None)."""
        if portfolio_id is None:
            self._previous_state.clear()
        else:
            self._previous_state.pop(portfolio_id, None)
