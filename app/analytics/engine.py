"""Analytics engine — runs the insight registry, returns an ordered insight bundle.

The bundle is the ONLY thing the AI layer is allowed to turn into prose. Every number in it
was computed here with pandas.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

import pandas as pd

import app.analytics.insights  # noqa: F401  (triggers @insight registration)
from app.analytics.registry import registered

SEVERITY_RANK = {"high": 0, "warn": 1, "info": 2}


def run_insights(df: pd.DataFrame, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ctx = {"currency": "", "now": datetime.now(timezone.utc), **(ctx or {})}
    bundle: list[dict[str, Any]] = []
    for order, name, fn in registered():
        try:
            result = fn(df, ctx)
        except Exception as exc:  # one bad insight must not sink the digest
            print(f"[engine] insight {name!r} failed: {exc}", file=sys.stderr)
            continue
        if result is None:
            continue
        result.name = name
        result.order = order
        bundle.append(result.to_dict())
    return bundle


def build_bundle(df: pd.DataFrame, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    insights = run_insights(df, ctx)
    insights_sorted = sorted(
        insights, key=lambda i: (SEVERITY_RANK.get(i["severity"], 3), i["order"])
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(df)),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "has_high_severity": any(i["severity"] == "high" for i in insights_sorted),
        "insights": insights_sorted,
    }


if __name__ == "__main__":  # python -m app.analytics.engine <csv>
    from app.connectors.csv_loader import load_csv

    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_sales.csv"
    bundle = build_bundle(load_csv(path), {"currency": "KES"})
    print(json.dumps(bundle, indent=2, default=str))
