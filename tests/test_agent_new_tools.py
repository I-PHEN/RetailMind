"""The four new agent tools: set_stock, get_stock, compare_periods, pause_alerts, remember."""
from unittest.mock import patch

import pandas as pd

from app.ai.agent import _run_tool


RETAILER = {"id": "shop1", "name": "Shop", "whatsapp": "+1", "currency": "GHS"}


def _df():
    dates = pd.date_range("2026-05-01", periods=27, freq="D")
    rows = []
    for d in dates:
        rows.append({"date": d, "product": "case", "quantity": 4, "unit_price": 30.0,
                     "revenue": 120.0})
    return pd.DataFrame(rows)


def test_set_stock_calls_storage_helper():
    with patch("app.ai.agent.stock_store.set_stock",
               return_value={"set_at": "2026-05-27T12:00:00+00:00"}) as mock:
        out = _run_tool("set_stock",
                        {"product": "iPhone case", "units": 50},
                        _df(), "GHS", RETAILER, "+1")
    mock.assert_called_once_with("shop1", "iPhone case", 50.0)
    assert out["status"] == "saved"
    assert out["product"] == "iPhone case"
    assert out["units"] == 50.0


def test_get_stock_no_product_returns_all():
    rows = [{"product": "case", "units": 50, "set_at": "2026-05-27T12:00:00+00:00"}]
    with patch("app.ai.agent.stock_store.get_stock", return_value=rows) as mock:
        out = _run_tool("get_stock", {"product": None}, _df(), "GHS", RETAILER, "+1")
    mock.assert_called_once_with("shop1")
    assert out["items"] == rows


def test_get_stock_with_product_returns_one():
    row = {"product": "case", "units": 50, "set_at": "..."}
    with patch("app.ai.agent.stock_store.get_stock_for", return_value=row) as mock:
        out = _run_tool("get_stock", {"product": "case"}, _df(), "GHS", RETAILER, "+1")
    mock.assert_called_once_with("shop1", "case")
    assert out["items"] == [row]


def test_compare_periods_sums_correctly():
    df = _df()
    out = _run_tool("compare_periods",
                    {"start_a": "2026-05-20", "end_a": "2026-05-26",
                     "start_b": "2026-05-13", "end_b": "2026-05-19",
                     "label_a": "this week", "label_b": "last week"},
                    df, "GHS", RETAILER, "+1")
    # Both windows are 7 days of identical synthetic data → equal revenue, 0% delta.
    assert out["a"]["label"] == "this week"
    assert out["b"]["label"] == "last week"
    assert out["a"]["revenue"] == out["b"]["revenue"]
    assert out["delta_pct"] == 0.0


def test_pause_alerts_writes_state():
    with patch("app.ai.agent.st.load_state", return_value={}), \
         patch("app.ai.agent.st.save_state") as mock_save, \
         patch("app.ai.agent.st.set_pause") as mock_set:
        out = _run_tool("pause_alerts", {"hours": 2, "reason": "meeting"},
                        _df(), "GHS", RETAILER, "+1")
    mock_set.assert_called_once()
    rid_arg, until_arg, reason_arg = mock_set.call_args[0][1:]
    assert rid_arg == "shop1"
    assert reason_arg == "meeting"
    assert "T" in until_arg  # ISO timestamp
    mock_save.assert_called_once()
    assert out["status"] == "paused"
    assert out["hours"] == 2.0


def test_pause_alerts_caps_at_24h():
    with patch("app.ai.agent.st.load_state", return_value={}), \
         patch("app.ai.agent.st.save_state"), \
         patch("app.ai.agent.st.set_pause"):
        out = _run_tool("pause_alerts", {"hours": 999}, _df(), "GHS", RETAILER, "+1")
    assert out["hours"] == 24.0


def test_remember_calls_notes_store():
    with patch("app.ai.agent.notes_store.add_note") as mock:
        out = _run_tool("remember", {"fact": "closed on Sundays"},
                        _df(), "GHS", RETAILER, "+1")
    mock.assert_called_once_with("shop1", "closed on Sundays")
    assert out["status"] == "remembered"
    assert out["fact"] == "closed on Sundays"


def test_remember_rejects_empty_fact():
    with patch("app.ai.agent.notes_store.add_note") as mock:
        out = _run_tool("remember", {"fact": "   "}, _df(), "GHS", RETAILER, "+1")
    mock.assert_not_called()
    assert out["status"] == "error"
