"""Top and slow movers over the last 14 days (revenue + units)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight


@insight(name="top_bottom_sellers", order=40)
def top_bottom_sellers(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    end = df["date"].max().normalize()
    recent = df[df["date"] >= end - timedelta(days=13)]
    if recent.empty:
        return None

    by_prod = recent.groupby("product").agg(
        revenue=("revenue", "sum"), units=("quantity", "sum")
    ).sort_values("revenue", ascending=False)
    if by_prod.empty:
        return None

    top = by_prod.head(3)
    slow = by_prod.tail(3).sort_values("revenue")
    cur = ctx.get("currency", "")
    return Insight(
        title="Top & slow movers (14d)",
        severity="info",
        metrics={
            "top": [
                {"product": p, "revenue": round(float(r.revenue), 2), "units": int(r.units)}
                for p, r in top.iterrows()
            ],
            "slow": [
                {"product": p, "revenue": round(float(r.revenue), 2), "units": int(r.units)}
                for p, r in slow.iterrows()
            ],
            "currency": cur,
        },
        finding=(
            f"Top seller (14d): {top.index[0]} at {top.iloc[0].revenue:,.0f} {cur}. "
            f"Slowest: {slow.index[0]} at {slow.iloc[0].revenue:,.0f} {cur}."
        ),
    )
