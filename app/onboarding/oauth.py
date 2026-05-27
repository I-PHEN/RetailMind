"""Google OAuth helpers for the Sheets connection step of onboarding.

Two-step flow:
  1. handle_oauth_callback(code, state_token)
       Exchange code -> store tokens in onboarding_state, advance to
       'awaiting_sheet_pick'. Return (whatsapp, tokens) so the HTTP handler
       can render the picker page with the user's access_token.
  2. finalize_with_sheet(state_token, spreadsheet_id)
       Pulled from picker: create the retailer, send confirmation + first digest.

We use scope `drive.file` so the user only grants access to the single sheet
they pick via the Google Picker widget (not their whole Drive).
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from google_auth_oauthlib.flow import Flow

from app.settings import get_settings

log = logging.getLogger("retailmind.onboarding.oauth")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


def _flow() -> Flow:
    s = get_settings()
    return Flow.from_client_config(
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


def build_oauth_url(whatsapp: str) -> tuple[str, str, str]:
    """Return (authorization_url, state_token, code_verifier).

    state_token is a 32-char hex string the caller must store in onboarding_state.data
    so the redirect handler can recover which WhatsApp number is completing OAuth.

    code_verifier is the PKCE secret. Google's OAuth requires PKCE for this client,
    so the same verifier must be passed back to `exchange_code` after the redirect.
    """
    state_token = secrets.token_hex(16)
    # PKCE: generate our own verifier so we can persist it across the redirect.
    # 43–128 url-safe chars per RFC 7636; 64 bytes -> ~86 chars.
    code_verifier = secrets.token_urlsafe(64)
    flow = _flow()
    flow.code_verifier = code_verifier  # makes authorization_url emit a code_challenge
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state_token,
        prompt="consent",
    )
    return auth_url, state_token, code_verifier


def exchange_code(code: str, code_verifier: str | None = None) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Returns a dict with token data.

    `code_verifier` must match the value used when the auth URL was built
    (Google rejects the exchange with InvalidGrantError otherwise).
    """
    s = get_settings()
    flow = _flow()
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "client_id": s.google_oauth_client_id,
        "client_secret": s.google_oauth_client_secret,
    }


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


def _row_by_token(state_token: str) -> dict[str, Any]:
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured")
    resp = (
        sb.table("onboarding_state")
        .select("*")
        .filter("data->>oauth_state_token", "eq", state_token)
        .execute()
    )
    if not resp.data:
        raise ValueError(f"Unknown state token: {state_token}")
    return resp.data[0]


def handle_oauth_callback(code: str, state_token: str) -> tuple[str, str]:
    """Step 1: exchange code, persist tokens, advance state to awaiting_sheet_pick.

    Returns (whatsapp, access_token) — the access_token is handed to the picker
    page's JS so the Google Picker widget can authenticate as the user.
    """
    row = _row_by_token(state_token)
    whatsapp = row["whatsapp"]
    verifier = (row.get("data") or {}).get("oauth_code_verifier")
    tokens = exchange_code(code, code_verifier=verifier)
    data = {**row["data"], "google_token": tokens}

    sb = _get_supabase()
    sb.table("onboarding_state").upsert({
        "whatsapp": whatsapp,
        "step": "awaiting_sheet_pick",
        "data": data,
    }).execute()
    return whatsapp, tokens["access_token"]


def finalize_with_sheet(state_token: str, spreadsheet_id: str) -> dict[str, Any]:
    """Step 2: user picked a sheet — create retailer, send confirmation + first digest."""
    from app.retailers import create_retailer
    from app.messaging.wuzapi_client import send_whatsapp
    from app.pipeline import run_digest

    row = _row_by_token(state_token)
    whatsapp = row["whatsapp"]
    data = row["data"]
    tokens = data.get("google_token")
    if not tokens:
        raise ValueError("OAuth tokens missing — finish step 1 first")

    name = data.get("name", "")
    shop_name = data.get("shop_name", f"{name}'s Shop")
    timezone = data.get("timezone", "Africa/Lagos")
    currency = data.get("currency", "USD")

    retailer_id = re.sub(r"[^\w]", "_", shop_name.lower()).strip("_")[:30]

    retailer = create_retailer({
        "id": retailer_id,
        "name": shop_name,
        "owner_name": name,
        "whatsapp": whatsapp,
        "currency": currency,
        "timezone": timezone,
        "digest_time": "08:00",
        "google_token": tokens,
        "spreadsheet_id": spreadsheet_id,
        "status": "active",
    })

    sb = _get_supabase()
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
        log.exception("first digest failed for %s", retailer_id)

    return retailer
