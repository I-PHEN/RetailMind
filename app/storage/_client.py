"""Shared Supabase client accessor.

Mirrors the lazy-init pattern in app/retailers.py so storage helpers can be
imported during dev (YAML mode) without instantiating a real client.
"""
from __future__ import annotations

from app.settings import get_settings

_client = None


def get_client():
    """Return a Supabase client, or None if not configured (dev / YAML mode)."""
    global _client
    if _client is not None:
        return _client
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        return None
    from supabase import create_client
    _client = create_client(s.supabase_url, s.supabase_key)
    return _client
