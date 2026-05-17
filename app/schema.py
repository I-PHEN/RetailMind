"""Canonical sales schema + fuzzy header auto-mapping.

Every connector funnels raw rows through `normalize()` so the rest of the system only ever
sees these columns:

    date (datetime64), product (str), quantity (float), unit_price (float),
    revenue (float), category (str, optional), unit_cost (float, optional)

Add new header spellings to ALIASES here — never special-case columns in connectors.
"""
from __future__ import annotations

import pandas as pd
from dateutil import parser as dateparser

REQUIRED = ["date", "product", "quantity", "unit_price", "revenue"]
OPTIONAL = ["category", "unit_cost"]

# canonical -> accepted raw header spellings (lowercased, stripped before match)
ALIASES: dict[str, list[str]] = {
    "date": ["date", "day", "datetime", "timestamp", "sale date", "order date"],
    "product": ["product", "item", "item name", "sku", "name", "description", "goods"],
    "quantity": ["quantity", "qty", "units", "count", "qty sold", "units sold", "volume"],
    "unit_price": ["unit price", "price", "unit_price", "selling price", "rate", "price each"],
    "revenue": ["revenue", "total", "amount", "sales", "total amount", "line total",
                "gross", "value", "total sales"],
    "category": ["category", "cat", "department", "type", "group", "class"],
    "unit_cost": ["unit cost", "cost", "unit_cost", "buying price", "cost price", "cogs"],
}


def _build_reverse_map(columns: list[str]) -> dict[str, str]:
    """Map each raw column to a canonical name where we can."""
    norm = {c: c.strip().lower() for c in columns}
    mapping: dict[str, str] = {}
    for canonical, names in ALIASES.items():
        for raw, low in norm.items():
            if raw in mapping:
                continue
            if low in names:
                mapping[raw] = canonical
                break
    return mapping


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a canonical-schema DataFrame from arbitrary sales rows.

    Raises ValueError if a required column cannot be located, listing what's missing
    so a misconfigured sheet fails loudly rather than silently mis-analyzing.
    """
    if df.empty:
        raise ValueError("Source has no rows.")

    rename = _build_reverse_map(list(df.columns))
    out = df.rename(columns=rename).copy()

    # Derive revenue if absent but price & qty present.
    if "revenue" not in out.columns and {"quantity", "unit_price"} <= set(out.columns):
        out["revenue"] = pd.to_numeric(out["quantity"], errors="coerce") * pd.to_numeric(
            out["unit_price"], errors="coerce"
        )
    # Derive unit_price if absent but revenue & qty present.
    if "unit_price" not in out.columns and {"quantity", "revenue"} <= set(out.columns):
        q = pd.to_numeric(out["quantity"], errors="coerce")
        out["unit_price"] = pd.to_numeric(out["revenue"], errors="coerce") / q.replace(0, pd.NA)

    missing = [c for c in REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(
            f"Could not map required column(s) {missing} from headers "
            f"{list(df.columns)}. Add an alias in app/schema.py."
        )

    out["date"] = out["date"].apply(
        lambda v: dateparser.parse(str(v)) if pd.notna(v) else pd.NaT
    )
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["product"] = out["product"].astype(str).str.strip()
    for col in ("quantity", "unit_price", "revenue", "unit_cost"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    keep = REQUIRED + [c for c in OPTIONAL if c in out.columns]
    out = out[keep].dropna(subset=["date", "product"])
    out = out[out["quantity"].fillna(0) >= 0].sort_values("date").reset_index(drop=True)
    if out.empty:
        raise ValueError("No valid rows after normalization (check date/quantity columns).")
    return out
