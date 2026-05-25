"""Onboarding conversation state machine.

States: greeting → awaiting_name → awaiting_oauth → (done, handled by oauth callback)
Reads/writes onboarding_state table in Supabase.
"""
from __future__ import annotations

import logging
from typing import Any

from app.messaging.wuzapi_client import send_whatsapp, send_whatsapp_link
from app.onboarding.name_parser import parse_name
from app.onboarding.oauth import build_oauth_url
from app.settings import get_settings

log = logging.getLogger("retailmind.onboarding")

_TIMEZONE_MAP = {
    "+234": "Africa/Lagos",
    "+254": "Africa/Nairobi",
    "+233": "Africa/Accra",
    "+256": "Africa/Kampala",
    "+255": "Africa/Dar_es_Salaam",
    "+27":  "Africa/Johannesburg",
    "+260": "Africa/Lusaka",
    "+263": "Africa/Harare",
    "+225": "Africa/Abidjan",
    "+221": "Africa/Dakar",
}

_DEFAULT_TZ = "Africa/Lagos"

_CURRENCY_MAP = {
    "+234": "NGN",
    "+254": "KES",
    "+233": "GHS",
    "+256": "UGX",
    "+255": "TZS",
    "+27":  "ZAR",
    "+260": "ZMW",
    "+263": "ZWL",
    "+225": "XOF",
    "+221": "XOF",
}

_DEFAULT_CURRENCY = "USD"


def _detect_timezone(whatsapp: str) -> str:
    for prefix, tz in _TIMEZONE_MAP.items():
        if whatsapp.startswith(prefix):
            return tz
    return _DEFAULT_TZ


def _detect_currency(whatsapp: str) -> str:
    for prefix, cur in _CURRENCY_MAP.items():
        if whatsapp.startswith(prefix):
            return cur
    return _DEFAULT_CURRENCY


# --- Supabase access (module-level so tests can patch) ---

_supabase_client = None


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


def _get_state(whatsapp: str) -> dict[str, Any] | None:
    sb = _get_supabase()
    if sb is None:
        return None
    resp = sb.table("onboarding_state").select("*").eq("whatsapp", whatsapp).execute()
    return resp.data[0] if resp.data else None


def _set_state(whatsapp: str, step: str, data: dict[str, Any]) -> None:
    sb = _get_supabase()
    if sb is None:
        return
    sb.table("onboarding_state").upsert({
        "whatsapp": whatsapp,
        "step": step,
        "data": data,
    }).execute()


def handle(whatsapp: str, text: str) -> None:
    """Process one inbound message from an unknown (onboarding) number."""
    state = _get_state(whatsapp)

    if state is None:
        # First contact — send greeting and record state
        _set_state(whatsapp, "awaiting_name", {})
        send_whatsapp(
            whatsapp,
            "Hi 👋 I'm RetailMind, your AI business partner.\n\n"
            "What's your name and what do you call your shop?",
        )
        return

    step = state.get("step", "greeting")
    data = state.get("data", {})

    if step == "awaiting_name":
        owner, shop = parse_name(text)
        auth_url, state_token = build_oauth_url(whatsapp)
        _set_state(whatsapp, "awaiting_oauth", {
            **data,
            "name": owner,
            "shop_name": shop,
            "oauth_state_token": state_token,
            "timezone": _detect_timezone(whatsapp),
            "currency": _detect_currency(whatsapp),
        })
        send_whatsapp(whatsapp, f"Nice to meet you {owner}! 🛒\n\nNow I need to see your sales data. Tap below to connect your Google Sheet:")
        send_whatsapp_link(
            whatsapp,
            auth_url,
            "Connect Google Sheet",
            "Tap to authorise RetailMind to read your sales sheet",
        )
        return

    if step == "awaiting_oauth":
        # They messaged again before completing OAuth — remind them
        send_whatsapp(
            whatsapp,
            "Still waiting for you to connect your Google Sheet 👆\n"
            "Tap the link above when you're ready!",
        )
        return

    log.warning("onboarding handle called for %s in unknown step %s", whatsapp, step)
