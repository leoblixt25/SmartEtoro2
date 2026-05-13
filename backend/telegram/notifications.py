"""Telegram notification helpers — formatting and sending.

Decoupled from command handling so it can be used by the scheduler
and other services without importing the full command set.
"""

import html
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SYM_MAP = {"USD": "$", "EUR": "€"}


def currency_symbol(currency: str) -> str:
    return SYM_MAP.get(currency, "$")


def escape_html(text: str) -> str:
    """Escape text for Telegram HTML parse_mode."""
    return html.escape(str(text), quote=False)


def format_status(portfolio) -> str:
    sym = currency_symbol(portfolio.currency or "USD")
    tv = portfolio.total_value or 0
    invested = portfolio.invested_amount or 0
    realized = portfolio.realized_pnl or 0
    unrealized = portfolio.unrealized_pnl or 0
    cash = portfolio.available_cash or 0
    health = portfolio.health_score or 0
    mode = "LIVE"
    total_return = tv - invested
    return_pct = (total_return / invested * 100) if invested else 0

    lines = [
        f"📊 **Portfolio Status** ({mode})",
        "",
        f"Total Value:   {sym}{tv:,.2f}",
        f"Invested:      {sym}{invested:,.2f}",
        f"Return:        {sym}{total_return:+,.2f} ({return_pct:+.2f}%)",
        f"Realized PnL:  {sym}{realized:+,.2f}",
        f"Unrealized PnL:{sym}{unrealized:+,.2f}",
        f"Available:     {sym}{cash:,.2f}",
        f"Health Score:  {health:.0f}/100",
    ]
    return "\n".join(lines)


def format_traders(traders: List) -> str:
    if not traders:
        return "No traders found."

    lines = ["👥 **Copied Traders**", ""]
    for t in traders:
        status = "▶️" if t.is_active and not t.is_paused else "⏸️" if t.is_paused else "⏹️"
        ret = t.total_return_pct or 0
        alloc = t.allocation_pct or 0
        risk = t.risk_score or 5
        cls_icon = "🟢" if risk < 4 else "🟡" if risk < 7 else "🔴"
        lines.append(
            f"{status} **{t.trader_username}** — {ret:+.2f}% | alloc {alloc:.1f}%"
            f" | {cls_icon} risk {risk:.1f}"
        )
    return "\n".join(lines)


def format_risk_violations(violations: List) -> str:
    if not violations:
        return "✅ No risk violations detected."

    lines = ["⚠️ **Risk Violations**", ""]
    for v in violations:
        icon = "🔴" if v.severity == "critical" else "🟡" if v.severity == "warning" else "🔵"
        lines.append(f"{icon} **{v.type}** ({v.severity})")
        if v.message:
            lines.append(f"   {v.message}")
    return "\n".join(lines)


def format_alerts(alerts: List) -> str:
    if not alerts:
        return "No alerts."

    lines = ["🔔 **Recent Alerts**", ""]
    for a in alerts[:5]:
        t = a.alert_type or "general"
        sev_icon = "🔴" if a.severity == "critical" else "🟡" if a.severity == "warning" else "🔵"
        lines.append(f"{sev_icon} **[{t}]** {a.title}")
        if a.message:
            lines.append(f"   {a.message[:200]}")
    return "\n".join(lines)


def format_pending_approvals(alerts: List) -> str:
    if not alerts:
        return "No pending approvals."

    lines = ["⏳ **Pending Approvals**", ""]
    for a in alerts:
        # rule_id is stored in the title or we link by alert id
        lines.append(f"🔹 **#{a.id}** — {a.message or a.title}")
    lines.append("")
    lines.append("Use `/approve <rule_id>` to approve.")
    return "\n".join(lines)


def format_scout_alert(report: Dict) -> str:
    """Format a scout alert for scheduled notifications."""
    weakest = report.get("weakest")
    swaps = report.get("top_swaps", [])
    avg = report.get("avg_score", 0)

    lines = ["🔍 **Market Scout — Scheduled Check**", ""]
    lines.append(f"📈 **Portfolio avg score:** {avg}/100")

    if weakest:
        lines.append(f"🔻 **Weakest:** {weakest['username']} ({weakest['final_score']}/100)")

    if swaps:
        lines.append("")
        lines.append("**Top picks to watch:**")
        for s in swaps[:3]:
            lines.append(f"  • {s['username']} ({s['final_score']}/100)")

    return "\n".join(lines)
