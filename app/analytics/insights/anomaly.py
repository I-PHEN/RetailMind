"""Daily-revenue anomaly via rolling-mean z-score.

Flags the latest day if it deviates sharply from the trailing 14-day window. This is the
insight the anomaly poll escalates into an unsolicited 'RetailMind noticed something' alert.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight

WINDOW = 14
Z_WARN = 2.0
Z_HIGH = 3.0


@insight(name="anomaly", order=60)
def anomaly(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    daily = df.groupby(df["date"].dt.date)["revenue"].sum().sort_index()
    if len(daily) < WINDOW + 1:
        return None

    window = daily.iloc[-(WINDOW + 1):-1]
    mean, std = float(window.mean()), float(window.std(ddof=0))
    if std == 0:
        return None

    last_day = daily.index[-1]
    last_rev = float(daily.iloc[-1])
    z = (last_rev - mean) / std
    if abs(z) < Z_WARN:
        return None

    severity = "high" if abs(z) >= Z_HIGH else "warn"
    direction = "spike" if z > 0 else "drop"
    cur = ctx.get("currency", "")
    # Carry the trailing window (+ spike day) so the chart renderer can plot the line.
    series_tail = daily.iloc[-(WINDOW + 1):]
    daily_series = [
        {"date": str(d), "revenue": round(float(v), 2)}
        for d, v in series_tail.items()
    ]
    return Insight(
        title=f"Revenue {direction} detected",
        severity=severity,
        metrics={
            "date": str(last_day),
            "revenue": round(last_rev, 2),
            "expected_avg": round(mean, 2),
            "z_score": round(z, 2),
            "currency": cur,
            "daily_series": daily_series,
        },
        finding=(
            f"{last_day} revenue {last_rev:,.0f} {cur} is a {direction} "
            f"({z:+.1f}σ) vs the expected ~{mean:,.0f} {cur}."
        ),
    )
