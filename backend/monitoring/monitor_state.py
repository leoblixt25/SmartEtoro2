"""
Monitoring State — tracks previous trader health results for alert dedup.

Only fires alerts when:
  - A trader changes from hold to reduce
  - A trader changes from hold to increase
  - A trader becomes risky due to news
  - A copied trader has a major negative event on top holdings
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MonitoringState:
    """Tracks last-known trader signals to detect meaningful changes."""

    def __init__(self):
        self._state: Dict[str, dict] = {}

    def get_changes(self, results: List[Dict]) -> List[Dict]:
        """Compare current results to previous state, return new alerts.

        Each alert dict: {alert_type, severity, title, message, is_new}
        """
        alerts = []

        for r in results:
            username = r["trader"]
            current_signal = r["signal"]
            prev = self._state.get(username)

            if prev is None:
                self._state[username] = {
                    "signal": current_signal,
                    "confidence": r.get("confidence", 0),
                    "holdings_health": r.get("holdings_health", 50),
                }
                continue

            prev_signal = prev.get("signal")

            # 1. hold → reduce
            if prev_signal == "hold" and current_signal == "reduce":
                alerts.append({
                    "alert_type": "monitor_trader_downgrade",
                    "severity": "warning",
                    "title": f"⚠️ Trader downgraded: {username}",
                    "message": (
                        f"{username} changed from hold to reduce. "
                        f"Reasons: {'; '.join(r.get('reasons', [])[:2])}"
                    ),
                    "is_new": True,
                    "trader": username,
                })
                logger.info("MONITOR ALERT: %s hold → reduce", username)

            # 2. hold → increase
            elif prev_signal == "hold" and current_signal == "increase":
                alerts.append({
                    "alert_type": "monitor_trader_upgrade",
                    "severity": "info",
                    "title": f"✅ Trader upgraded: {username}",
                    "message": (
                        f"{username} changed from hold to increase. "
                        f"Reasons: {'; '.join(r.get('reasons', [])[:2])}"
                    ),
                    "is_new": True,
                    "trader": username,
                })
                logger.info("MONITOR ALERT: %s hold → increase", username)

            # 3. Major negative event on top holdings
            current_health = r.get("holdings_health", 50)
            prev_health = prev.get("holdings_health", 50)
            if prev_health >= 40 and current_health < 30 and current_signal in ("reduce", "avoid"):
                alerts.append({
                    "alert_type": "monitor_negative_news_impact",
                    "severity": "warning",
                    "title": f"🔴 Negative news impact: {username}",
                    "message": (
                        f"{username} holdings health dropped from "
                        f"{prev_health:.0f} to {current_health:.0f}. "
                        f"Negative holdings: {', '.join(r.get('top_negative_holdings', [])[:3])}"
                    ),
                    "is_new": True,
                    "trader": username,
                })
                logger.info("MONITOR ALERT: %s news impact (%.0f→%.0f)",
                            username, prev_health, current_health)

            # 4. New risky trader (risky signal for the first time)
            if prev.get("signal") not in ("reduce", "avoid") and current_signal in ("avoid",) and r.get("confidence", 0) >= 0.6:
                alerts.append({
                    "alert_type": "monitor_trader_risky",
                    "severity": "critical",
                    "title": f"🚨 Trader at risk: {username}",
                    "message": (
                        f"{username} is now flagged as avoid. "
                        f"Reasons: {'; '.join(r.get('reasons', [])[:2])}"
                    ),
                    "is_new": True,
                    "trader": username,
                })
                logger.info("MONITOR ALERT: %s became risky", username)

            # Update state
            self._state[username] = {
                "signal": current_signal,
                "confidence": r.get("confidence", 0),
                "holdings_health": current_health,
            }

        return alerts

    def reset(self, username: Optional[str] = None) -> None:
        """Reset state for one trader, or all if None."""
        if username:
            self._state.pop(username, None)
        else:
            self._state.clear()


_monitor_state = MonitoringState()


def get_monitor_state() -> MonitoringState:
    return _monitor_state
