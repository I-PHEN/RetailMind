"""Shared pipeline: load → analyze → narrate → (optionally) send."""
from __future__ import annotations

from typing import Any

from app.ai.narrator import narrate
from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.messaging.evolution_client import send_whatsapp


def _source_from_retailer(retailer: dict[str, Any]) -> dict[str, Any]:
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
    df = load_source(_source_from_retailer(retailer))
    return build_bundle(df, {"currency": retailer.get("currency", ""), "retailer": retailer})


def run_digest(retailer: dict[str, Any], mode: str = "digest", send: bool = True) -> dict[str, Any]:
    bundle = build_for(retailer)
    message = narrate(bundle, retailer, mode=mode)
    if send:
        send_whatsapp(retailer["whatsapp"], message)
    return {
        "retailer": retailer["id"],
        "mode": mode,
        "message": message,
        "has_high_severity": bundle["has_high_severity"],
        "insight_count": len(bundle["insights"]),
        "insight_names": [i["name"] for i in bundle["insights"]],
    }
