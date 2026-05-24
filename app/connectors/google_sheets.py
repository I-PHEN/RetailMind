"""Google Sheets connector — service account (dev) or OAuth token (production)."""
from __future__ import annotations

import pandas as pd

from app.schema import normalize
from app.settings import get_settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def load_google_sheet(
    spreadsheet_id: str,
    worksheet: str | None = None,
    google_token: dict | None = None,
) -> pd.DataFrame:
    import gspread

    if google_token and google_token.get("access_token"):
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=google_token["access_token"],
            refresh_token=google_token.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=google_token.get("client_id"),
            client_secret=google_token.get("client_secret"),
        )
    else:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            get_settings().google_service_account_json, scopes=_SCOPES
        )

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet) if worksheet else sh.sheet1
    raw = pd.DataFrame(ws.get_all_records())
    return normalize(raw)
