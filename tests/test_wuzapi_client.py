from unittest.mock import MagicMock, patch
import pytest


def test_normalise_strips_whatsapp_prefix():
    from app.messaging.wuzapi_client import _normalise
    assert _normalise("whatsapp:+2348012345678") == "2348012345678"
    assert _normalise("+2348012345678") == "2348012345678"
    assert _normalise("2348012345678") == "2348012345678"


def test_normalise_strips_jid_suffix():
    from app.messaging.wuzapi_client import _normalise
    assert _normalise("2348012345678@s.whatsapp.net") == "2348012345678"


def test_send_whatsapp_calls_correct_endpoint():
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        wuzapi_client.send_whatsapp("+2348012345678", "hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "http://wuz:8080/chat/send/text"
        headers = mock_post.call_args[1]["headers"]
        assert headers["Token"] == "user-token"
        payload = mock_post.call_args[1]["json"]
        assert payload["Phone"] == "2348012345678@s.whatsapp.net"
        assert payload["Body"] == "hello"


def test_send_whatsapp_link_inlines_url():
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        wuzapi_client.send_whatsapp_link("+234...", "https://x/y", "Title", "body")
        body = mock_post.call_args[1]["json"]["Body"]
        assert "*Title*" in body
        assert "body" in body
        assert "https://x/y" in body


def test_send_whatsapp_raises_on_missing_config():
    from app.messaging import wuzapi_client
    wuzapi_client._settings = MagicMock(wuzapi_api_url="", wuzapi_token="")
    with pytest.raises(RuntimeError, match="Wuzapi not configured"):
        wuzapi_client.send_whatsapp("+234...", "hi")
