"""Deterministic chart-selection policy.

When does an insight earn a chart? Only when the chart genuinely adds clarity over prose.
Rules live HERE — one place to tune. The narrator never decides; the LLM never picks.

Per insight (matches the names in app/analytics/insights/):
  anomaly:        always chart (the spike IS the story).
  wow_change:     chart only if |delta_pct| >= 15.
  revenue_trend:  chart only if |delta_pct| >= 25 (else it's a flat line).
  top_bottom:     chart only if top revenue >= 2x median (a real outlier worth showing).
  low_stock:      never — it's a list, prose is clearer.
  other names:    no chart.
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Any

from app.charts import renderer

log = logging.getLogger("retailmind.charts")

_SEV_RANK = {"high": 0, "warn": 1, "info": 2}

WOW_MIN_DELTA = 15.0
TREND_MIN_DELTA = 25.0
TOPSEL_OUTLIER_RATIO = 2.0


def _should_chart(insight: dict[str, Any]) -> bool:
    name = insight.get("name")
    m = insight.get("metrics", {}) or {}

    if name == "anomaly":
        return True
    if name == "wow_change":
        return abs(float(m.get("delta_pct", 0))) >= WOW_MIN_DELTA
    if name == "revenue_trend":
        return abs(float(m.get("delta_pct", 0))) >= TREND_MIN_DELTA
    if name in ("top_bottom_sellers", "top_bottom"):
        top = m.get("top") or []
        slow = m.get("slow") or []
        all_revs = [float(p.get("revenue", 0)) for p in top + slow if "revenue" in p]
        if len(all_revs) < 2 or not top:
            return False
        med = median(all_revs)
        if med <= 0:
            return False
        return float(top[0].get("revenue", 0)) >= TOPSEL_OUTLIER_RATIO * med
    return False


def _render(insight: dict[str, Any]) -> bytes | None:
    name = insight.get("name")
    m = insight.get("metrics", {}) or {}
    try:
        if name == "anomaly":
            return renderer.anomaly_spike(m)
        if name == "wow_change":
            return renderer.wow_bars(m)
        if name == "revenue_trend":
            return renderer.revenue_trend_line(m)
        if name in ("top_bottom_sellers", "top_bottom"):
            return renderer.top_movers_bar(m)
    except Exception:
        log.exception("chart render failed for insight=%s", name)
        return None
    return None


def chart_for(insight: dict[str, Any]) -> bytes | None:
    """Return a PNG chart for this insight, or None if a chart wouldn't add clarity."""
    if not _should_chart(insight):
        return None
    return _render(insight)


def pick_chart_for_message(insights: list[dict[str, Any]]) -> tuple[dict, bytes] | None:
    """Pick the ONE chart to attach. Prefer high severity, then bundle order.

    Returns (insight, png_bytes) or None when nothing qualifies. One chart per
    message — never spam the chat with images.
    """
    if not insights:
        return None
    # Stable sort: severity first, then preserve original order via enumerate.
    ranked = sorted(
        enumerate(insights),
        key=lambda pair: (_SEV_RANK.get(pair[1].get("severity"), 3), pair[0]),
    )
    for _, ins in ranked:
        png = chart_for(ins)
        if png:
            return ins, png
    return None
