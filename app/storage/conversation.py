"""Persisted conversation memory — last N messages per retailer.

The Q&A agent loads `recent_messages` at the start of every turn and appends
both the user message and its reply at the end. Surviving uvicorn restart is
the whole point — without this the bot has the goldfish problem.
"""
from __future__ import annotations

import logging
from typing import Literal

from app.storage._client import get_client

log = logging.getLogger("retailmind.storage.conversation")
_TABLE = "conversation_messages"
Role = Literal["user", "assistant"]


def recent_messages(retailer_id: str, limit: int = 16) -> list[dict[str, str]]:
    """Return the last `limit` messages, ordered oldest → newest (chat-ready)."""
    sb = get_client()
    if sb is None:
        return []
    resp = (sb.table(_TABLE)
            .select("role, content, created_at")
            .eq("retailer_id", retailer_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute())
    rows = resp.data or []
    rows.reverse()  # oldest first for the LLM
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def append_message(retailer_id: str, role: Role, content: str) -> None:
    """Append one turn. Fire-and-forget — never raise."""
    sb = get_client()
    if sb is None:
        return
    try:
        sb.table(_TABLE).insert({
            "retailer_id": retailer_id,
            "role": role,
            "content": content,
        }).execute()
    except Exception:
        log.exception("conversation append failed for %s", retailer_id)
