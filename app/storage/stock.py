"""Per-retailer stock snapshots — owner tells us, we remember.

Latest snapshot per (retailer_id, product); upserted on each `set_stock`. The
agent calls these from `set_stock` / `get_stock` tools so reorder estimates
can use real counts instead of pure sales-velocity guesses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.storage._client import get_client

log = logging.getLogger("retailmind.storage.stock")
_TABLE = "stock_snapshots"


def set_stock(retailer_id: str, product: str, units: float) -> dict[str, Any]:
    """Upsert one stock snapshot. Returns the saved row."""
    sb = get_client()
    payload = {
        "retailer_id": retailer_id,
        "product": product,
        "units": float(units),
        "set_at": datetime.now(timezone.utc).isoformat(),
    }
    if sb is None:
        log.info("set_stock: Supabase unconfigured, returning payload only")
        return payload
    resp = sb.table(_TABLE).upsert(payload, on_conflict="retailer_id,product").execute()
    return (resp.data or [payload])[0]


def get_stock(retailer_id: str) -> list[dict[str, Any]]:
    """All current snapshots for a retailer, newest set_at first."""
    sb = get_client()
    if sb is None:
        return []
    resp = (sb.table(_TABLE)
            .select("product, units, set_at")
            .eq("retailer_id", retailer_id)
            .order("set_at", desc=True)
            .execute())
    return resp.data or []


def get_stock_for(retailer_id: str, product: str) -> dict[str, Any] | None:
    """One snapshot, or None if the owner hasn't reported this product yet."""
    sb = get_client()
    if sb is None:
        return None
    resp = (sb.table(_TABLE)
            .select("product, units, set_at")
            .eq("retailer_id", retailer_id)
            .eq("product", product)
            .execute())
    return (resp.data or [None])[0]
