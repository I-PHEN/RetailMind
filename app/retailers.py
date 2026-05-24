"""Retailer registry — Supabase in production, YAML fallback in dev."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from app.settings import get_settings

# Module-level client — None until first use
_supabase_client = None


def _digits(num: str) -> str:
    return re.sub(r"\D", "", num)


def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        return None
    from supabase import create_client
    _supabase_client = create_client(s.supabase_url, s.supabase_key)
    return _supabase_client


# ---------- YAML fallback (dev / local smoke-tests) ----------

@lru_cache
def _load_yaml() -> list[dict[str, Any]]:
    with open(get_settings().retailmind_config, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("retailers", [])
    # Normalise YAML rows to match the Supabase column names
    normalised = []
    for r in rows:
        row = dict(r)
        # YAML uses whatsapp_to; internal interface uses whatsapp
        if "whatsapp_to" in row and "whatsapp" not in row:
            row["whatsapp"] = row.pop("whatsapp_to")
        # strip whatsapp: prefix
        if row.get("whatsapp", "").startswith("whatsapp:"):
            row["whatsapp"] = row["whatsapp"][len("whatsapp:"):]
        normalised.append(row)
    return normalised


# ---------- Public interface ----------

def all_retailers() -> list[dict[str, Any]]:
    """Return all active retailers. Scheduler calls this."""
    sb = _get_supabase()
    if sb is None:
        return _load_yaml()
    resp = sb.table("retailers").select("*").eq("status", "active").execute()
    return resp.data


def get_retailer(retailer_id: str) -> dict[str, Any] | None:
    sb = _get_supabase()
    if sb is None:
        return next((r for r in _load_yaml() if r.get("id") == retailer_id), None)
    resp = sb.table("retailers").select("*").eq("id", retailer_id).execute()
    return resp.data[0] if resp.data else None


def by_whatsapp(number: str) -> dict[str, Any] | None:
    """Match an inbound number (any format) to a retailer."""
    target = _digits(number)
    sb = _get_supabase()
    if sb is None:
        return next(
            (r for r in _load_yaml() if _digits(r.get("whatsapp", "")) == target),
            None,
        )
    resp = sb.table("retailers").select("*").execute()
    return next(
        (r for r in resp.data if _digits(r.get("whatsapp", "")) == target),
        None,
    )


def create_retailer(data: dict[str, Any]) -> dict[str, Any]:
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured — cannot create retailer in dev mode")
    resp = sb.table("retailers").insert(data).execute()
    return resp.data[0]


def update_retailer(retailer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured — cannot update retailer in dev mode")
    resp = sb.table("retailers").update(data).eq("id", retailer_id).execute()
    return resp.data[0]
