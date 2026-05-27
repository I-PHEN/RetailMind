"""Pipeline picks a chart → sends image (not text). Falls back to text when no chart."""
from unittest.mock import patch


RETAILER = {"id": "shop1", "name": "Shop", "whatsapp": "+2348012345678",
            "currency": "GHS", "spreadsheet_id": "X"}


def test_run_digest_sends_image_when_chart_picked():
    fake_bundle = {"insights": [{"name": "anomaly", "severity": "high"}],
                   "has_high_severity": True}
    fake_pick = ({"name": "anomaly"}, b"\x89PNGchart")

    with patch("app.pipeline.build_for", return_value=fake_bundle), \
         patch("app.pipeline.pick_chart_for_message", return_value=fake_pick), \
         patch("app.pipeline.narrate", return_value="caption text"), \
         patch("app.pipeline.send_whatsapp_image") as mock_img, \
         patch("app.pipeline.send_whatsapp") as mock_text:

        from app.pipeline import run_digest
        res = run_digest(RETAILER, mode="digest", send=True)

        mock_img.assert_called_once()
        args, kwargs = mock_img.call_args
        assert args[0] == "+2348012345678"
        assert args[1] == b"\x89PNGchart"
        assert kwargs.get("caption") == "caption text"
        mock_text.assert_not_called()
        assert res["has_chart"] is True
        assert res["chart_insight"] == "anomaly"


def test_run_digest_sends_text_when_no_chart():
    fake_bundle = {"insights": [{"name": "low_stock", "severity": "high"}],
                   "has_high_severity": True}

    with patch("app.pipeline.build_for", return_value=fake_bundle), \
         patch("app.pipeline.pick_chart_for_message", return_value=None), \
         patch("app.pipeline.narrate", return_value="text-only message"), \
         patch("app.pipeline.send_whatsapp_image") as mock_img, \
         patch("app.pipeline.send_whatsapp") as mock_text:

        from app.pipeline import run_digest
        res = run_digest(RETAILER, mode="digest", send=True)

        mock_text.assert_called_once_with("+2348012345678", "text-only message")
        mock_img.assert_not_called()
        assert res["has_chart"] is False


def test_run_digest_falls_back_to_text_when_image_send_fails():
    fake_bundle = {"insights": [{"name": "anomaly", "severity": "high"}],
                   "has_high_severity": True}
    fake_pick = ({"name": "anomaly"}, b"\x89PNG")

    with patch("app.pipeline.build_for", return_value=fake_bundle), \
         patch("app.pipeline.pick_chart_for_message", return_value=fake_pick), \
         patch("app.pipeline.narrate", return_value="caption"), \
         patch("app.pipeline.send_whatsapp_image",
               side_effect=RuntimeError("Wuzapi 500")), \
         patch("app.pipeline.send_whatsapp") as mock_text:

        from app.pipeline import run_digest
        run_digest(RETAILER, mode="digest", send=True)

        # Image attempted, failed, then text fallback used.
        mock_text.assert_called_once_with("+2348012345678", "caption")
