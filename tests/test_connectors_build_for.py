from unittest.mock import patch, MagicMock
import pandas as pd


def _fake_df():
    return pd.DataFrame({
        "date": ["2024-01-01"],
        "product": ["Rice"],
        "quantity": [10],
        "unit_price": [5.0],
        "revenue": [50.0],
    })


def test_build_for_yaml_shape():
    """YAML retailer: has nested source dict → uses service account path."""
    retailer = {
        "id": "demo",
        "currency": "KES",
        "source": {"type": "csv", "path": "data/sample_sales.csv"},
    }
    with patch("app.pipeline.load_source", return_value=_fake_df()) as mock_load, \
         patch("app.pipeline.build_bundle", return_value={"insights": [], "has_high_severity": False}):
        from app.pipeline import build_for
        build_for(retailer)
        mock_load.assert_called_once_with({"type": "csv", "path": "data/sample_sales.csv"})


def test_build_for_supabase_shape():
    """Supabase retailer: flat spreadsheet_id + google_token → constructs source dict."""
    retailer = {
        "id": "amina",
        "currency": "NGN",
        "spreadsheet_id": "SHEET_ID_123",
        "google_token": {"access_token": "tok", "refresh_token": "ref"},
        # no 'source' key
    }
    with patch("app.pipeline.load_source", return_value=_fake_df()) as mock_load, \
         patch("app.pipeline.build_bundle", return_value={"insights": [], "has_high_severity": False}):
        from app.pipeline import build_for
        build_for(retailer)
        call_arg = mock_load.call_args[0][0]
        assert call_arg["type"] == "google_sheet"
        assert call_arg["spreadsheet_id"] == "SHEET_ID_123"
        assert call_arg["google_token"] == {"access_token": "tok", "refresh_token": "ref"}
