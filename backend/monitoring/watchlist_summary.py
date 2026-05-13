"""
Watchlist Summary — produces a portfolio-level summary of all trader health results.

Output sections:
  - Top traders to increase (confidence >= 0.7, signal=increase)
  - Traders to hold (signal=hold)
  - Traders to reduce (signal=reduce)
  - Traders to watch (signal=watch/avoid)
  - Overall portfolio sentiment
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def build_watchlist_summary(results: List[Dict]) -> Dict:
    """Build a portfolio-level summary from individual trader health results.

    Args:
        results: List of trader health dicts from analyze_trader_health().

    Returns:
        Dict with sections:
          - increase: traders to add to
          - hold: traders to maintain
          - reduce: traders to reduce allocation
          - watch: traders needing attention
          - summary: one-line portfolio sentiment
          - debug: { total, by_signal, avg_performance, avg_confidence }
    """
    increase = []
    hold = []
    reduce = []
    watch = []

    for r in results:
        entry = {
            "trader": r["trader"],
            "signal": r["signal"],
            "confidence": r["confidence"],
            "performance_score": r.get("performance_score", 0),
            "reasons": r.get("reasons", []),
        }
        if r["signal"] == "increase":
            increase.append(entry)
        elif r["signal"] == "hold":
            hold.append(entry)
        elif r["signal"] in ("reduce", "avoid"):
            reduce.append(entry)
        else:
            watch.append(entry)

    # Sort each section by confidence descending
    for lst in (increase, hold, reduce, watch):
        lst.sort(key=lambda x: x["confidence"], reverse=True)

    # Summary
    total = len(results)
    avg_perf = (
        round(sum(r.get("performance_score", 0) for r in results) / total, 1)
        if total else 0.0
    )
    avg_conf = (
        round(sum(r.get("confidence", 0) for r in results) / total, 2)
        if total else 0.0
    )

    # Overall sentiment
    weights = {"increase": 1.0, "hold": 0.0, "reduce": -0.5, "avoid": -1.0, "watch": -0.2}
    sentiment_score = sum(
        weights.get(r["signal"], 0) * r.get("confidence", 0.5)
        for r in results
    ) / max(total, 1)
    sentiment_score = round(max(-1, min(1, sentiment_score)), 2)

    if sentiment_score >= 0.3:
        sentiment = "positive"
    elif sentiment_score <= -0.3:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    lines = [
        f"Portfolio: {total} traders monitored",
        f"  Increase: {len(increase)}",
        f"  Hold: {len(hold)}",
        f"  Reduce/Avoid: {len(reduce)}",
        f"  Watch: {len(watch)}",
        f"  Avg performance: {avg_perf}/100",
        f"  Sentiment: {sentiment} ({sentiment_score:+.2f})",
    ]

    summary = "\n".join(lines)

    return {
        "increase": increase,
        "hold": hold,
        "reduce": reduce,
        "watch": watch,
        "summary": summary,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "debug": {
            "total": total,
            "by_signal": {
                "increase": len(increase),
                "hold": len(hold),
                "reduce": len(reduce),
                "watch": len(watch),
            },
            "avg_performance": avg_perf,
            "avg_confidence": avg_conf,
        },
    }
