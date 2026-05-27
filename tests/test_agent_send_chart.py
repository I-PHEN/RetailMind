"""The send_chart tool: renders the right chart and sends it to the right number."""
from unittest.mock import patch

import pandas as pd

from app.ai.agent import _send_chart


def _df():
    # 30 days of synthetic daily sales — enough for every chart kind.
    dates = pd.date_range("2026-04-28", periods=30, freq="D")
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "product": "iPhone case",
                     "quantity": 4 + i % 3, "unit_price": 30.0,
                     "revenue": (4 + i % 3) * 30.0})
        rows.append({"date": d, "product": "Charger",
                     "quantity": 2, "unit_price": 15.0, "revenue": 30.0})
    # Today's spike for the anomaly chart.
    rows.append({"date": dates[-1], "product": "iPhone case",
                 "quantity": 60, "unit_price": 30.0, "revenue": 1800.0})
    return pd.DataFrame(rows)


def test_send_chart_anomaly_renders_and_sends():
    df = _df()
    with patch("app.ai.agent.send_whatsapp_image") as mock_send:
        out = _send_chart("anomaly", df, "GHS", "+2348012345678")
    assert out == {"status": "sent", "kind": "anomaly"}
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert args[0] == "+2348012345678"
    assert args[1].startswith(b"\x89PNG")  # actual PNG bytes


def test_send_chart_trend_sends_png():
    df = _df()
    with patch("app.ai.agent.send_whatsapp_image") as mock_send:
        out = _send_chart("trend", df, "KES", "+233...")
    assert out["status"] == "sent"
    assert out["kind"] == "trend"
    assert mock_send.call_args[0][1].startswith(b"\x89PNG")


def test_send_chart_unknown_kind_returns_error():
    out = _send_chart("pie_chart", _df(), "GHS", "+1")
    assert out["status"] == "error"
    assert "unknown" in out["error"].lower()


def test_send_chart_no_data_for_insight():
    """When the bundle doesn't contain the requested insight, return no_data — not crash."""
    # Anomaly needs 15+ days of history; give it just 3.
    small = pd.DataFrame([
        {"date": pd.Timestamp("2026-05-25"), "product": "X",
         "quantity": 1, "unit_price": 10.0, "revenue": 10.0},
        {"date": pd.Timestamp("2026-05-26"), "product": "X",
         "quantity": 1, "unit_price": 10.0, "revenue": 10.0},
        {"date": pd.Timestamp("2026-05-27"), "product": "X",
         "quantity": 1, "unit_price": 10.0, "revenue": 10.0},
    ])
    with patch("app.ai.agent.send_whatsapp_image") as mock_send:
        out = _send_chart("anomaly", small, "GHS", "+1")
    assert out["status"] == "no_data"
    mock_send.assert_not_called()
