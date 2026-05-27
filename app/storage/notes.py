"""Long-term facts the agent learns about each shop.

Written by the LLM via the `remember` tool ("shop closed Sundays", "sells
phones and accessories"). Injected into the system prompt on every turn so
the bot recalls them across sessions.
"""
from __future__ import annotations

import logging
from typing import Any

from app.storage._client import get_client

log = logging.getLogger("retailmind.storage.notes")
_TABLE = "retailer_notes"


def add_note(retailer_id: str, fact: str) -> dict[str, Any] | None:
    sb = get_client()
    if sb is None:
        return None
    fact = (fact or "").strip()
    if not fact:
        return None
    try:
        resp = sb.table(_TABLE).insert({
            "retailer_id": retailer_id,
            "fact": fact,
        }).execute()
        return (resp.data or [None])[0]
    except Exception:
        log.exception("note insert failed for %s", retailer_id)
        return None


def get_notes(retailer_id: str, limit: int = 30) -> list[str]:
    sb = get_client()
    if sb is None:
        return []
    resp = (sb.table(_TABLE)
            .select("fact, created_at")
            .eq("retailer_id", retailer_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute())
    return [r["fact"] for r in (resp.data or [])]


def clear_note(retailer_id: str, fact_id: int) -> None:
    sb = get_client()
    if sb is None:
        return
    try:
        sb.table(_TABLE).delete().eq("retailer_id", retailer_id).eq("id", fact_id).execute()
    except Exception:
        log.exception("note delete failed for %s id=%s", retailer_id, fact_id)
