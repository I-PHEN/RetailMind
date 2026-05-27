"""Chart renderer smoke tests — each function returns a valid PNG.

We don't pixel-snapshot (too brittle); we assert the magic bytes and that the
output is non-empty. Visual quality is verified by eye via the verification
step in the plan.
"""
from app.charts import renderer

PNG_MAGIC = b"\x89PNG"


def test_anomaly_spike_returns_png():
    metrics = {
        "date": "2026-05-27",
        "revenue": 1500.0,
        "expected_avg": 400.0,
        "z_score": 5.0,
        "currency": "GHS",
        "daily_series": [
            {"date": f"2026-05-{d:02d}", "revenue": 400.0 + (d * 3)}
            for d in range(13, 27)
        ] + [{"date": "2026-05-27", "revenue": 1500.0}],
    }
    out = renderer.anomaly_spike(metrics)
    assert isinstance(out, bytes)
    assert out.startswith(PNG_MAGIC)
    assert len(out) > 1000  # a real PNG of this size is at least a few KB


def test_anomaly_spike_handles_empty_series():
    out = renderer.anomaly_spike({"date": None, "currency": "GHS"})
    assert out.startswith(PNG_MAGIC)


def test_revenue_trend_line_returns_png():
    metrics = {
        "currency": "KES",
        "delta_pct": 32.0,
        "daily_series": [
            {"date": f"2026-04-{d:02d}", "revenue": 300.0 + d * 10}
            for d in range(1, 30)
        ],
    }
    out = renderer.revenue_trend_line(metrics)
    assert out.startswith(PNG_MAGIC)


def test_wow_bars_returns_png():
    metrics = {
        "this_week_revenue": 5400.0,
        "prev_week_revenue": 4100.0,
        "delta_pct": 31.7,
        "currency": "NGN",
    }
    out = renderer.wow_bars(metrics)
    assert out.startswith(PNG_MAGIC)


def test_top_movers_bar_returns_png():
    metrics = {
        "top": [
            {"product": "iPhone case", "revenue": 980.0, "units": 32},
            {"product": "Charger", "revenue": 540.0, "units": 18},
            {"product": "Earphones", "revenue": 410.0, "units": 12},
        ],
        "slow": [
            {"product": "Lightning cable", "revenue": 60.0, "units": 2},
            {"product": "Old screen protector", "revenue": 80.0, "units": 3},
            {"product": "Adapter", "revenue": 90.0, "units": 3},
        ],
        "currency": "GHS",
    }
    out = renderer.top_movers_bar(metrics)
    assert out.startswith(PNG_MAGIC)
