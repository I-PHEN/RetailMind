from unittest.mock import MagicMock, patch
import pytest


def test_normalise_strips_whatsapp_prefix():
    from app.messaging.evolution_client import _normalise
    assert _normalise("whatsapp:+2348012345678") == "+2348012345678"
    assert _normalise("+2348012345678") == "+2348012345678"
    assert _normalise("2348012345678") == "+2348012345678"


def test_normalise_strips_jid_suffix():
    from app.messaging.evolution_client import _normalise
    assert _normalise("2348012345678@s.whatsapp.net") == "+2348012345678"


def test_send_whatsapp_calls_correct_endpoint():
    with patch("app.messaging.evolution_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"key": {"id": "abc"}})
        from app.messaging import evolution_client
        evolution_client._settings = MagicMock(
            evolution_api_url="http://evo",
            evolution_api_key="key123",
            evolution_instance="retailmind",
        )
        evolution_client.send_whatsapp("+2348012345678", "hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "sendText/retailmind" in url
        payload = mock_post.call_args[1]["json"]
        assert payload["number"] == "+2348012345678"
        assert payload["text"] == "hello"


def test_send_whatsapp_raises_on_missing_config():
    from app.messaging import evolution_client
    evolution_client._settings = MagicMock(
        evolution_api_url="",
        evolution_api_key="",
        evolution_instance="retailmind",
    )
    with pytest.raises(RuntimeError, match="EVOLUTION"):
        evolution_client.send_whatsapp("+234...", "hi")
