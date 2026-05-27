"""Yesterday's revenue and how it compares to the trailing daily average."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight


@insight(name="revenue_trend", order=10)
def revenue_trend(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    daily = df.groupby(df["date"].dt.date)["revenue"].sum().sort_index()
    if daily.empty:
        return None

    last_day = daily.index[-1]
    last_rev = float(daily.iloc[-1])
    baseline = float(daily.iloc[-30:-1].mean()) if len(daily) > 1 else last_rev
    delta_pct = ((last_rev - baseline) / baseline * 100.0) if baseline else 0.0

    direction = "above" if delta_pct >= 0 else "below"
    # Last 30 days for the chart renderer (line + mean overlay).
    series_tail = daily.iloc[-30:]
    daily_series = [
        {"date": str(d), "revenue": round(float(v), 2)}
        for d, v in series_tail.items()
    ]
    return Insight(
        title="Latest day revenue",
        severity="info",
        metrics={
            "date": str(last_day),
            "revenue": round(last_rev, 2),
            "trailing_avg_30d": round(baseline, 2),
            "delta_pct": round(delta_pct, 1),
            "currency": ctx.get("currency", ""),
            "daily_series": daily_series,
        },
        finding=(
            f"On {last_day}, revenue was {last_rev:,.0f} {ctx.get('currency','')}, "
            f"{abs(delta_pct):.0f}% {direction} the 30-day average."
        ),
    )
