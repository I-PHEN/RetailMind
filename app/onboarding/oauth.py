"""Google OAuth helpers for the Sheets connection step of onboarding."""
from __future__ import annotations

import secrets
from typing import Any

from google_auth_oauthlib.flow import Flow

from app.settings import get_settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def build_oauth_url(whatsapp: str) -> tuple[str, str]:
    """Return (authorization_url, state_token).

    state_token is a 32-char hex string the caller must store in onboarding_state.data
    so the redirect handler can recover which WhatsApp number is completing OAuth.
    """
    s = get_settings()
    state_token = secrets.token_hex(16)  # 32 hex chars

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_oauth_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=s.google_oauth_redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state_token,
        prompt="consent",  # force refresh_token to be returned
    )
    return auth_url, state_token


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Returns a dict with token data."""
    s = get_settings()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_oauth_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=s.google_oauth_redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "client_id": s.google_oauth_client_id,
        "client_secret": s.google_oauth_client_secret,
    }


import re as _re
import logging as _logging

_log = _logging.getLogger("retailmind.onboarding.oauth")

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


def complete_onboarding(code: str, state_token: str) -> str:
    """Exchange OAuth code, create retailer, send confirmation + first digest.

    Returns the retailer's WhatsApp number (for the HTTP response).
    Raises ValueError if the state_token is not found.
    """
    from app.retailers import create_retailer
    from app.messaging.evolution_client import send_whatsapp
    from app.pipeline import run_digest

    tokens = exchange_code(code)

    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured")

    # Recover the WhatsApp number from the state token
    resp = (
        sb.table("onboarding_state")
        .select("*")
        .filter("data->>oauth_state_token", "eq", state_token)
        .execute()
    )
    if not resp.data:
        raise ValueError(f"Unknown state token: {state_token}")

    row = resp.data[0]
    whatsapp = row["whatsapp"]
    data = row["data"]
    name = data.get("name", "")
    shop_name = data.get("shop_name", f"{name}'s Shop")
    timezone = data.get("timezone", "Africa/Lagos")

    # Build retailer id from shop name
    retailer_id = _re.sub(r"[^\w]", "_", shop_name.lower()).strip("_")[:30]

    retailer = create_retailer({
        "id": retailer_id,
        "name": shop_name,
        "whatsapp": whatsapp,
        "currency": "USD",
        "timezone": timezone,
        "digest_time": "08:00",
        "google_token": tokens,
        "status": "active",
    })

    # Clean up onboarding state
    sb.table("onboarding_state").delete().eq("whatsapp", whatsapp).execute()

    send_whatsapp(
        whatsapp,
        f"Perfect! You're all set {name} 🎉\n"
        f"I'll send you a summary every morning at 8am ⏰\n"
        f"First one coming now 👇",
    )

    try:
        run_digest(retailer, mode="digest", send=True)
    except Exception:
        _log.exception("first digest failed for %s", retailer_id)

    return whatsapp
