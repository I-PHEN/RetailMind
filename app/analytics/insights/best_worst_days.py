"""Best and worst trading day-of-week over the last 4 weeks."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight


@insight(name="best_worst_days", order=30)
def best_worst_days(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    end = df["date"].max().normalize()
    recent = df[df["date"] >= end - timedelta(days=27)]
    if recent.empty:
        return None

    by_dow = recent.groupby(recent["date"].dt.day_name())["revenue"].mean()
    if by_dow.empty:
        return None
    best = by_dow.idxmax()
    worst = by_dow.idxmin()
    return Insight(
        title="Best & worst days",
        severity="info",
        metrics={
            "best_day": best,
            "best_day_avg": round(float(by_dow.max()), 2),
            "worst_day": worst,
            "worst_day_avg": round(float(by_dow.min()), 2),
            "currency": ctx.get("currency", ""),
        },
        finding=(
            f"Over the last 4 weeks, {best} is the strongest day "
            f"(avg {by_dow.max():,.0f}) and {worst} the weakest "
            f"(avg {by_dow.min():,.0f} {ctx.get('currency','')})."
        ),
    )
