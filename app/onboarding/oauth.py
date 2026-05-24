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
