"""Reorder risk from sales velocity.

We don't get live inventory in the MVP, so we model it: assume a weekly restock cycle
(notional on-hand = baseline daily units x RESTOCK_COVER_DAYS) and measure how fast that
cover is being burned through at the *recent* velocity. Products whose recent velocity has
accelerated and whose projected cover is short get flagged for reorder.

When a real stock column exists, swap the notional on-hand for the actual figure here.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from app.analytics.registry import Insight, insight

RESTOCK_COVER_DAYS = 7      # assumed cycle the shop normally stocks for
ACCEL_FACTOR = 1.45         # recent vs baseline velocity that counts as "running hot"
MAX_ITEMS = 3               # only surface the few genuinely urgent ones
URGENT_DAYS = 3             # projected days-to-reorder that escalates to a proactive alert


@insight(name="low_stock", order=50)
def low_stock(df: pd.DataFrame, ctx: dict[str, Any]) -> Insight | None:
    end = df["date"].max().normalize()
    base = df[df["date"] >= end - timedelta(days=29)]
    recent = df[df["date"] >= end - timedelta(days=6)]
    if base.empty or recent.empty:
        return None

    base_daily = base.groupby("product")["quantity"].sum() / 30.0
    recent_daily = recent.groupby("product")["quantity"].sum() / 7.0

    flagged: list[dict[str, Any]] = []
    for product, rv in recent_daily.items():
        bv = float(base_daily.get(product, 0.0))
        if bv <= 0 or rv <= 0:
            continue
        notional_on_hand = bv * RESTOCK_COVER_DAYS
        days_left = notional_on_hand / rv
        if rv >= bv * ACCEL_FACTOR and days_left <= RESTOCK_COVER_DAYS:
            flagged.append(
                {
                    "product": product,
                    "recent_daily_units": round(rv, 1),
                    "baseline_daily_units": round(bv, 1),
                    "days_to_reorder": round(days_left, 1),
                }
            )

    if not flagged:
        return None
    flagged.sort(key=lambda x: x["days_to_reorder"])
    flagged = flagged[:MAX_ITEMS]
    soonest = flagged[0]["days_to_reorder"]
    severity = "high" if soonest <= URGENT_DAYS else "warn"
    lead = flagged[0]
    return Insight(
        title="Reorder soon",
        severity=severity,
        metrics={"items": flagged, "restock_cover_days": RESTOCK_COVER_DAYS},
        finding=(
            f"{lead['product']} is selling fast ({lead['recent_daily_units']}/day vs "
            f"{lead['baseline_daily_units']}/day baseline) — reorder in about "
            f"{lead['days_to_reorder']:.0f} day(s)."
        ),
    )
