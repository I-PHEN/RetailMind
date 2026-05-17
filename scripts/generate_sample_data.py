"""Generate a realistic sample sales CSV for an African mini-mart.

Bakes in patterns the demo relies on:
  - weekly seasonality (weekends busier)
  - a gentle upward revenue trend
  - one product ("Sugar 1kg") selling fast -> low-stock/reorder insight
  - a clear revenue spike in the last few days -> anomaly insight

Run once; commit the output. Deterministic via fixed seed.

    python scripts/generate_sample_data.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

OUT = Path(__file__).resolve().parents[1] / "data" / "sample_sales.csv"
DAYS = 75

# product -> (category, unit_price KES, unit_cost KES, base daily units)
PRODUCTS = {
    "Cooking Oil 1L":   ("Groceries",   320, 250, 14),
    "Sugar 1kg":        ("Groceries",   160, 120, 26),   # fast mover -> low stock
    "Maize Flour 2kg":  ("Groceries",   190, 150, 18),
    "Rice 2kg":         ("Groceries",   280, 220, 10),
    "Bread":            ("Bakery",       60,  42, 30),
    "Milk 500ml":       ("Dairy",        55,  40, 28),
    "Soda 500ml":       ("Beverages",    70,  48, 22),
    "Bottled Water 1L": ("Beverages",    45,  28, 16),
    "Tea Leaves 250g":  ("Groceries",   140, 105,  7),
    "Soap Bar":         ("Household",    45,  30, 12),
    "Detergent 500g":   ("Household",   180, 135,  6),
    "Matchbox":         ("Household",    10,   6, 20),
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    start = date.today() - timedelta(days=DAYS - 1)
    rows: list[dict] = []

    for d in range(DAYS):
        day = start + timedelta(days=d)
        weekday = day.weekday()  # 0 Mon .. 6 Sun
        weekend_boost = 1.35 if weekday >= 5 else 1.0
        trend = 1.0 + (d / DAYS) * 0.25                 # +25% over the window
        spike = 1.9 if d >= DAYS - 3 else 1.0           # last 3 days anomaly

        for product, (cat, price, cost, base) in PRODUCTS.items():
            # Sugar accelerates late -> triggers low-stock/velocity insight
            sugar_accel = 1.0
            if product == "Sugar 1kg" and d >= DAYS - 14:
                sugar_accel = 1.5

            mean = base * weekend_boost * trend * spike * sugar_accel
            qty = max(0, int(random.gauss(mean, mean * 0.18)))
            if qty == 0:
                continue
            rows.append(
                {
                    "Date": day.isoformat(),
                    "Item": product,
                    "Category": cat,
                    "Qty": qty,
                    "Unit Price": price,
                    "Unit Cost": cost,
                    "Total": qty * price,
                }
            )

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Date", "Item", "Category", "Qty", "Unit Price", "Unit Cost", "Total"],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
