"""Shared pipeline: load → analyze → narrate → (optionally) send."""
from __future__ import annotations

import logging
from typing import Any

from app.ai.narrator import narrate
from app.analytics.engine import build_bundle
from app.charts.policy import pick_chart_for_message
from app.connectors import load_source
from app.messaging.wuzapi_client import send_whatsapp, send_whatsapp_image

log = logging.getLogger("retailmind.pipeline")


def source_from_retailer(retailer: dict[str, Any]) -> dict[str, Any]:
    """Build a source config dict from either a YAML retailer or a Supabase retailer."""
    if "source" in retailer:
        return retailer["source"]  # YAML shape — already a source dict
    # Supabase shape — flat fields
    return {
        "type": "google_sheet",
        "spreadsheet_id": retailer["spreadsheet_id"],
        "google_token": retailer.get("google_token"),
    }


def build_for(retailer: dict[str, Any]) -> dict[str, Any]:
    df = load_source(source_from_retailer(retailer))
    return build_bundle(df, {"currency": retailer.get("currency", ""), "retailer": retailer})


def run_digest(retailer: dict[str, Any], mode: str = "digest", send: bool = True) -> dict[str, Any]:
    bundle = build_for(retailer)
    pick = pick_chart_for_message(bundle.get("insights", []))
    has_chart = pick is not None
    message = narrate(bundle, retailer, mode=mode, has_chart=has_chart)
    if send:
        _send(retailer["whatsapp"], message, pick)
    return {
        "retailer": retailer["id"],
        "mode": mode,
        "message": message,
        "has_chart": has_chart,
        "chart_insight": pick[0]["name"] if pick else None,
        "has_high_severity": bundle["has_high_severity"],
        "insight_count": len(bundle["insights"]),
        "insight_names": [i["name"] for i in bundle["insights"]],
    }


def _send(to: str, message: str, pick: tuple[dict, bytes] | None) -> None:
    """Send chart-with-caption when we have one; fall back to text on any image failure."""
    if pick is None:
        send_whatsapp(to, message)
        return
    _, png = pick
    try:
        send_whatsapp_image(to, png, caption=message)
    except Exception:
        log.exception("image send failed, falling back to text-only")
        send_whatsapp(to, message)
