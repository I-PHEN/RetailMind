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
        # Short URLs (< 80 chars) skip the shortener; body is sent as-is.
        body = mock_post.call_args[1]["json"]["Body"]
        assert "body" in body
        assert "https://x/y" in body


def test_send_whatsapp_raises_on_missing_config():
    from app.messaging import wuzapi_client
    wuzapi_client._settings = MagicMock(wuzapi_api_url="", wuzapi_token="")
    with pytest.raises(RuntimeError, match="Wuzapi not configured"):
        wuzapi_client.send_whatsapp("+234...", "hi")


def test_send_typing_posts_chat_presence():
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        wuzapi_client.send_typing("+2348012345678")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "http://wuz:8080/chat/presence"
        payload = mock_post.call_args[1]["json"]
        assert payload["Phone"] == "2348012345678"
        assert payload["State"] == "composing"


def test_send_paused_posts_chat_presence():
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        wuzapi_client.send_paused("+2348012345678")
        payload = mock_post.call_args[1]["json"]
        assert payload["State"] == "paused"


def test_send_typing_swallows_http_errors():
    """Typing indicator failure must NEVER block the actual reply."""
    with patch("app.messaging.wuzapi_client.httpx.post",
               side_effect=RuntimeError("network down")):
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        # Should not raise
        wuzapi_client.send_typing("+2348012345678")


def test_send_whatsapp_image_posts_chat_send_image():
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(
            wuzapi_api_url="http://wuz:8080",
            wuzapi_token="user-token",
        )
        png = b"\x89PNG\r\n\x1a\n_fake_png_bytes_"
        wuzapi_client.send_whatsapp_image("+2348012345678", png, caption="hi there")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url == "http://wuz:8080/chat/send/image"
        payload = mock_post.call_args[1]["json"]
        assert payload["Phone"] == "2348012345678@s.whatsapp.net"
        assert payload["Image"].startswith("data:image/png;base64,")
        assert payload["Caption"] == "hi there"


def test_send_whatsapp_image_raises_on_missing_config():
    from app.messaging import wuzapi_client
    wuzapi_client._settings = MagicMock(wuzapi_api_url="", wuzapi_token="")
    with pytest.raises(RuntimeError, match="Wuzapi not configured"):
        wuzapi_client.send_whatsapp_image("+234...", b"\x89PNG")


def test_send_typing_silent_when_unconfigured():
    """No Wuzapi config? Just do nothing — typing is optional."""
    with patch("app.messaging.wuzapi_client.httpx.post") as mock_post:
        from app.messaging import wuzapi_client
        wuzapi_client._settings = MagicMock(wuzapi_api_url="", wuzapi_token="")
        wuzapi_client.send_typing("+234")
        mock_post.assert_not_called()
