"""Data connectors — each returns a canonical-schema DataFrame via app.schema.normalize."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.connectors.csv_loader import load_csv
from app.connectors.google_sheets import load_google_sheet


def load_source(source: dict[str, Any]) -> pd.DataFrame:
    """Dispatch on a source config dict (from pipeline._source_from_retailer)."""
    stype = source.get("type", "csv")
    if stype == "csv":
        return load_csv(source["path"])
    if stype == "google_sheet":
        return load_google_sheet(
            source["spreadsheet_id"],
            source.get("worksheet"),
            source.get("google_token"),
        )
    raise ValueError(f"Unknown source type: {stype!r}")
