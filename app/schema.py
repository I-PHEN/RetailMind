"""Canonical sales schema + fuzzy header auto-mapping.

Every connector funnels raw rows through `normalize()` so the rest of the system only ever
sees these columns:

    date (datetime64), product (str), quantity (float), unit_price (float),
    revenue (float), category (str, optional), unit_cost (float, optional)

Add new header spellings to ALIASES here — never special-case columns in connectors.
Headers are normalized before matching: lowercased, stripped, parenthetical/unit
suffixes removed, non-alphanum collapsed to single spaces — so "Unit Price (GHS)",
"unit_price", "Unit-Price [USD]" all match the same alias.
"""
from __future__ import annotations

import re

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


_PAREN_OR_BRACKET = re.compile(r"[\(\[\{].*?[\)\]\}]")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _normalize_header(h: str) -> str:
    """Lowercase, drop parenthetical/bracketed units (e.g. '(GHS)'), collapse
    punctuation to single spaces so 'Unit Price (GHS)' -> 'unit price'."""
    s = _PAREN_OR_BRACKET.sub(" ", str(h)).lower()
    s = _NON_WORD.sub(" ", s).strip()
    return s


def _build_reverse_map(columns: list[str]) -> dict[str, str]:
    """Map each raw column to a canonical name where we can."""
    norm = {c: _normalize_header(c) for c in columns}
    # Pre-normalize the alias table once per call so comparison is symmetric.
    alias_norm = {
        canon: {_normalize_header(a) for a in names}
        for canon, names in ALIASES.items()
    }
    mapping: dict[str, str] = {}
    for canonical, names in alias_norm.items():
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

    src = df.rename(columns=_build_reverse_map(list(df.columns)))
    cols = set(src.columns)

    def _num(name: str) -> pd.Series | None:
        return pd.to_numeric(src[name], errors="coerce") if name in cols else None

    quantity = _num("quantity")
    unit_price = _num("unit_price")
    revenue = _num("revenue")
    # Derive whichever of revenue / unit_price is missing but inferable.
    if revenue is None and quantity is not None and unit_price is not None:
        revenue = quantity * unit_price
    if unit_price is None and quantity is not None and revenue is not None:
        unit_price = revenue / quantity.replace(0, pd.NA)

    missing = []
    if "date" not in cols:
        missing.append("date")
    if "product" not in cols:
        missing.append("product")
    if quantity is None:
        missing.append("quantity")
    if unit_price is None:
        missing.append("unit_price")
    if revenue is None:
        missing.append("revenue")
    if missing:
        raise ValueError(
            f"Could not map required column(s) {missing} from headers "
            f"{list(df.columns)}. Add an alias in app/schema.py."
        )

    # Build a fresh frame column-by-column: correct dtypes, no chained-assignment.
    norm = pd.DataFrame()
    norm["date"] = pd.to_datetime(
        src["date"].apply(lambda v: dateparser.parse(str(v)) if pd.notna(v) else pd.NaT),
        errors="coerce",
    )
    norm["product"] = src["product"].astype(str).str.strip()
    norm["quantity"] = quantity
    norm["unit_price"] = unit_price
    norm["revenue"] = revenue
    if "category" in cols:
        norm["category"] = src["category"].astype(str).str.strip()
    if "unit_cost" in cols:
        norm["unit_cost"] = _num("unit_cost")

    norm = norm.dropna(subset=["date", "product"])
    norm = norm[norm["quantity"].fillna(0) >= 0].sort_values("date").reset_index(drop=True)
    if norm.empty:
        raise ValueError("No valid rows after normalization (check date/quantity columns).")
    return norm
