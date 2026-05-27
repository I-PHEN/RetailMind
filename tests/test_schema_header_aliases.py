"""Header normalization tests — covers real spreadsheet quirks like 'Unit Price (GHS)'."""
import pandas as pd
import pytest

from app.schema import _build_reverse_map, _normalize_header, normalize


def test_normalize_header_strips_parenthetical_units():
    assert _normalize_header("Unit Price (GHS)") == "unit price"
    assert _normalize_header("Quantity (units)") == "quantity"
    assert _normalize_header("Revenue [USD]") == "revenue"


def test_normalize_header_collapses_punctuation():
    assert _normalize_header("unit_price") == "unit price"
    assert _normalize_header("Unit-Price") == "unit price"
    assert _normalize_header("  UNIT  PRICE  ") == "unit price"


def test_reverse_map_handles_currency_suffix():
    """Real Google-Sheet headers often carry a currency tag."""
    mapping = _build_reverse_map(["Date", "Product", "Quantity", "Unit Price (GHS)"])
    assert mapping["Date"] == "date"
    assert mapping["Product"] == "product"
    assert mapping["Quantity"] == "quantity"
    assert mapping["Unit Price (GHS)"] == "unit_price"


def test_normalize_full_pipeline_with_ghs_header():
    df = pd.DataFrame({
        "Date": ["2026-05-01", "2026-05-02"],
        "Product": ["Case", "Charger"],
        "Quantity": [3, 1],
        "Unit Price (GHS)": [50.0, 120.0],
    })
    out = normalize(df)
    assert list(out.columns) == ["date", "product", "quantity", "unit_price", "revenue"]
    assert out["revenue"].tolist() == [150.0, 120.0]


def test_normalize_rejects_truly_unknown_headers():
    df = pd.DataFrame({
        "ProductID": [1, 2],
        "QuantityInStock": [10, 20],
    })
    with pytest.raises(ValueError, match="Could not map required column"):
        normalize(df)
