"""Fetch raw discovery data from production API, re-score locally with new weights."""
import asyncio
import json
import httpx
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Local scoring with updated weights
from backend.discovery.validate import build_trader_profile
from backend.discovery.score import calculate_score_from_profile


def _insight(t) -> str:
    ret = t.get("total_return_pct")
    risk = t.get("risk_score")
    dd = t.get("peak_to_valley") or t.get("max_drawdown")
    dd_abs = abs(dd) if dd is not None else None
    prof_months = t.get("profitable_months_pct")
    weeks = t.get("weeks_since_registration")

    is_high_ret = ret is not None and ret > 100
    is_mod_ret = ret is not None and 50 < ret <= 100
    is_low_ret = ret is not None and ret <= 50
    is_low_risk = risk is not None and risk <= 3
    is_mod_risk = risk is not None and 4 <= risk <= 5
    is_low_dd = dd_abs is not None and dd_abs < 10
    is_mod_dd = dd_abs is not None and 10 <= dd_abs < 18
    is_high_dd = dd_abs is not None and dd_abs >= 18
    is_high_cons = prof_months is not None and prof_months > 70
    is_long_exp = weeks is not None and weeks >= 156

    if is_high_ret and is_low_risk and is_low_dd:
        return "Elite risk-adjusted returns."
    if is_high_ret and is_mod_risk and is_low_dd:
        return "Strong return with controlled risk."
    if is_high_ret and is_mod_risk and is_mod_dd and is_high_cons:
        return "High returns with reliable consistency."
    if is_high_ret and is_mod_risk and is_mod_dd:
        return "Good return with manageable drawdown."
    if is_high_ret and is_mod_risk and is_high_dd:
        return "Strong returns but elevated drawdown."
    if is_high_ret and (risk is not None and risk > 5):
        return "Aggressive profile with high upside."
    if is_high_cons and is_mod_ret:
        return "Remarkable consistency."
    if is_high_cons and is_low_dd and is_mod_ret:
        return "Consistency plus capital preservation."
    if is_low_risk and is_low_dd and is_high_cons:
        return "Textbook capital preservation."
    if is_low_risk and is_low_dd:
        return "Very stable with low drawdown."
    if is_low_risk and is_mod_ret:
        return "Solid and disciplined risk taker."
    if is_mod_ret and is_mod_risk and is_low_dd:
        return "Solid returns with capital preservation."
    if is_mod_ret and is_mod_risk and is_mod_dd:
        return "Consistent long-term performer."
    if is_long_exp and is_low_dd:
        return "Proven stability over years."
    if is_long_exp and is_mod_ret:
        return "Reliable veteran performer."
    if is_high_cons and is_high_ret:
        return "Rare combo of consistency and returns."
    if is_low_ret:
        return "Low return profile, limited upside."
    return "Balanced across key metrics."


def format_trader_block(t, rank: int) -> str:
    medals = ["\U0001f947", "\U0001f948", "\U0001f949", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    medal = medals[rank] if rank < len(medals) else f"{rank+1}."

    username = t.get("username", "?")
    score = t.get("final_score", t.get("score", 0))
    ret = t.get("total_return_pct")
    risk = t.get("risk_score")
    dd = t.get("peak_to_valley") or t.get("max_drawdown")
    dd_abs = abs(dd) if dd is not None else None
    prof_months = t.get("profitable_months_pct")
    weeks = t.get("weeks_since_registration")
    positions = t.get("positions_count")

    ret_str = f"+{ret:.1f}%" if ret is not None else "N/A"
    risk_str = f"{int(risk)}/10" if risk is not None else "N/A"
    dd_str = f"{dd_abs:.1f}%" if dd_abs is not None else "N/A"

    present = sum(1 for f in [ret, risk, dd, positions, prof_months, weeks] if f is not None)
    conf = "HIGH" if present >= 5 else "MEDIUM" if present >= 3 else "LOW"

    if risk is not None:
        if risk <= 3:
            style = "\U0001f7e2 Conservative Growth"
        elif risk <= 5:
            style = "\U0001f7e1 Balanced Growth"
        elif risk <= 7:
            style = "\U0001f7e0 Aggressive Growth"
        else:
            style = "\U0001f534 High Risk"
    else:
        style = "\u26aa Unknown"

    lines = [
        f'{medal} <b>{username}</b> \u2b50 <b>{score:.0f}/100</b> \U0001f512 {conf}',
        f'\U0001f4c8 <b>{ret_str}</b> \u2022 \u26a0\ufe0f Risk <b>{risk_str}</b> \u2022 \U0001f4c9 DD <b>{dd_str}</b>',
        style,
        f'\U0001f4a1 {_insight(t)}',
        '\u2501' * 16,
    ]
    return "\n".join(lines)


def rescore_trader(t: dict) -> dict:
    """Re-score a trader dict using local updated scoring weights."""
    # Map API field names to what build_trader_profile expects
    raw = {
        "username": t.get("username", "?"),
        "source": t.get("source", "tradeinfo"),
        "confidence": t.get("confidence_mod", t.get("confidence", 1.0)),
        "total_return_pct": t.get("total_return_pct"),
        "return_12m": t.get("total_return_pct"),  # use total as 12m
        "risk_score": t.get("risk_score"),
        "peak_to_valley": t.get("peak_to_valley"),
        "profitable_months_pct": t.get("profitable_months_pct"),
        "positions_count": t.get("positions_count"),
        "weeks_since_registration": t.get("weeks_since_registration"),
    }
    profile = build_trader_profile(raw)
    scored = calculate_score_from_profile(profile)

    return {
        **t,
        "score": scored.score,
        "final_score": scored.final_score,
        "explanation": scored.explanation,
        "_rescored": True,
    }


async def main():
    url = "https://smartetoro2.onrender.com/api/portfolios/1/discovery"
    print(f"Fetching raw data from {url} ...")
    print("(This may take 2-3 minutes)\n")

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        print(f"API returned {resp.status_code}: {resp.text[:500]}")
        return

    data = resp.json()
    eligible = data.get("eligible", [])
    stats = data.get("stats", {})

    if not eligible:
        print("No eligible traders found.")
        return

    # Re-score all eligible traders with new local weights
    rescored = [rescore_trader(t) for t in eligible]
    rescored.sort(key=lambda x: x["final_score"], reverse=True)

    scanned = stats.get("total_scanned", 0)
    eligible_count = len(rescored)

    now = datetime.now().strftime("%b %d, %H:%M UTC")
    print("\U0001f3c6 <b>TOP COPY TRADERS</b>")
    print(f"\U0001f4c5 <b>{now}</b>")
    print(f"\U0001f4ca <b>{scanned} Scanned</b> \u2022 \u2705 <b>Real Data Only</b>")
    print("")

    for i, t in enumerate(rescored[:5]):
        print(format_trader_block(t, i))

    top = rescored[0]
    top_user = top.get("username", "?")
    top_ret = top.get("total_return_pct")
    top_risk = top.get("risk_score")
    top_dd = top.get("peak_to_valley") or top.get("max_drawdown")

    if top_ret is not None and top_ret > 100 and top_risk is not None and top_risk <= 4:
        best_reason = "Best mix of return, safety, and consistency."
    elif top_dd is not None and abs(top_dd) < 12:
        best_reason = "Strongest capital preservation."
    elif top_ret is not None and top_ret > 80:
        best_reason = "Top return with acceptable risk."
    else:
        best_reason = "Most well-rounded performer."

    print("")
    print(f"\U0001f3af <b>BEST PICK</b>")
    print(f"<b>{top_user}</b> \u2192 {best_reason}")
    print(f"\U0001f4cc <b>{eligible_count} eligible traders</b> from <b>{scanned} scanned</b>")

    # Show ALL with breakdown
    print("\n\n--- FULL RANKING WITH BREAKDOWN ---")
    for i, t in enumerate(rescored):
        exp = t.get("explanation", [])
        print(f"  {i+1:2d}. {t['username']:20s} {t['final_score']:5.1f}/100  |  {' | '.join(exp)}")


if __name__ == "__main__":
    asyncio.run(main())
