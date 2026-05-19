"""
Watchlist Summary — produces a portfolio-level summary of all trader health results.

Output sections:
  - Top traders to keep (signal=increase / recommendation=KEEP)
  - Traders to reduce copy (signal=reduce / recommendation=REDUCE COPY AMOUNT)
  - Traders to pause (signal=watch / recommendation=PAUSE)
  - Traders to uncopy (signal=avoid / recommendation=UNCOPY)
  - Overall portfolio sentiment
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def build_watchlist_summary(results: List[Dict]) -> Dict:
    increase = []
    reduce = []
    watch = []
    avoid_list = []

    for r in results:
        entry = {
            "trader": r["trader"],
            "signal": r["signal"],
            "recommendation": r.get("recommendation", "KEEP"),
            "confidence": r["confidence"],
            "performance_score": r.get("performance_score", 0),
            "reasons": r.get("reasons", []),
        }
        if r["signal"] == "increase":
            increase.append(entry)
        elif r["signal"] == "reduce":
            reduce.append(entry)
        elif r["signal"] == "avoid":
            avoid_list.append(entry)
        else:
            watch.append(entry)

    for lst in (increase, reduce, watch, avoid_list):
        lst.sort(key=lambda x: x["confidence"], reverse=True)

    total = len(results)
    avg_perf = (
        round(sum(r.get("performance_score", 0) for r in results) / total, 1)
        if total else 0.0
    )
    avg_conf = (
        round(sum(r.get("confidence", 0) for r in results) / total, 2)
        if total else 0.0
    )

    weights = {"increase": 1.0, "reduce": -0.5, "avoid": -1.0, "watch": -0.2}
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
        f"  Keep: {len(increase)}",
        f"  Reduce: {len(reduce)}",
        f"  Pause/Watch: {len(watch)}",
        f"  Uncopy: {len(avoid_list)}",
        f"  Avg performance: {avg_perf}/30",
        f"  Sentiment: {sentiment} ({sentiment_score:+.2f})",
    ]

    summary = "\n".join(lines)

    return {
        "increase": increase,
        "reduce": reduce,
        "watch": watch,
        "avoid": avoid_list,
        "summary": summary,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "debug": {
            "total": total,
            "by_signal": {
                "increase": len(increase),
                "reduce": len(reduce),
                "watch": len(watch),
                "avoid": len(avoid_list),
            },
            "avg_performance": avg_perf,
            "avg_confidence": avg_conf,
        },
    }
