"""Google Sheets connector (gspread + service account).

Setup: create a service account, download its JSON, point GOOGLE_SERVICE_ACCOUNT_JSON at it,
and share the target sheet with the service account's client_email (Viewer is enough).
"""
from __future__ import annotations

import pandas as pd

from app.schema import normalize
from app.settings import get_settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def load_google_sheet(spreadsheet_id: str, worksheet: str | None = None) -> pd.DataFrame:
    # Imported lazily so CSV-only runs never need Google libs configured.
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        get_settings().google_service_account_json, scopes=_SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet) if worksheet else sh.sheet1
    raw = pd.DataFrame(ws.get_all_records())
    return normalize(raw)
