"""Shared pipeline: load → analyze → narrate → (optionally) send.

Used by the /trigger endpoint and the scheduler so both behave identically.
"""
from __future__ import annotations

from typing import Any

from app.ai.narrator import narrate
from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.messaging.twilio_client import send_whatsapp


def build_for(retailer: dict[str, Any]) -> dict[str, Any]:
    df = load_source(retailer["source"])
    return build_bundle(df, {"currency": retailer.get("currency", ""), "retailer": retailer})


def run_digest(retailer: dict[str, Any], mode: str = "digest", send: bool = True) -> dict[str, Any]:
    bundle = build_for(retailer)
    message = narrate(bundle, retailer, mode=mode)
    sid = None
    if send:
        sid = send_whatsapp(retailer["whatsapp_to"], message)
    return {
        "retailer": retailer["id"],
        "mode": mode,
        "message": message,
        "twilio_sid": sid,
        "has_high_severity": bundle["has_high_severity"],
        "insight_count": len(bundle["insights"]),
    }
