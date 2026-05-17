"""Last 7 days vs the prior 7 days — the headline 'is this week good or bad' number."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight


@insight(name="wow_change", order=20)
def wow_change(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    end = df["date"].max().normalize()
    this_start = end - timedelta(days=6)
    prev_start = end - timedelta(days=13)
    prev_end = end - timedelta(days=7)

    this_week = df[(df["date"] >= this_start) & (df["date"] <= end)]["revenue"].sum()
    prev_week = df[(df["date"] >= prev_start) & (df["date"] <= prev_end)]["revenue"].sum()
    if prev_week == 0:
        return None

    delta_pct = (this_week - prev_week) / prev_week * 100.0
    severity = "high" if abs(delta_pct) >= 25 else ("warn" if abs(delta_pct) >= 12 else "info")
    word = "up" if delta_pct >= 0 else "down"
    return Insight(
        title="Week over week",
        severity=severity,
        metrics={
            "this_week_revenue": round(float(this_week), 2),
            "prev_week_revenue": round(float(prev_week), 2),
            "delta_pct": round(float(delta_pct), 1),
            "currency": ctx.get("currency", ""),
        },
        finding=(
            f"This week's revenue ({this_week:,.0f}) is {word} {abs(delta_pct):.0f}% "
            f"vs last week ({prev_week:,.0f} {ctx.get('currency','')})."
        ),
    )
