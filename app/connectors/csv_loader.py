"""CSV connector. Zero external auth — the reliable fallback path."""
from __future__ import annotations

import sys

import pandas as pd

from app.schema import normalize


def load_csv(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    return normalize(raw)


if __name__ == "__main__":  # smoke-test: python -m app.connectors.csv_loader <path>
    p = sys.argv[1] if len(sys.argv) > 1 else "data/sample_sales.csv"
    df = load_csv(p)
    print(df.head(10).to_string())
    print(f"\n{len(df)} rows | {df['date'].min().date()} → {df['date'].max().date()} | "
          f"{df['product'].nunique()} products | columns={list(df.columns)}")
