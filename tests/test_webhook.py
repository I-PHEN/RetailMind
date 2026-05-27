"""Tests for the Wuzapi inbound webhook parser + routing."""
import json
from fastapi.testclient import TestClient
from unittest.mock import patch


def _make_app():
    from app.messaging.webhook import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


def _wuzapi_envelope(inner: dict) -> dict:
    """Wrap an event dict in Wuzapi's outer envelope (jsonData is a JSON string)."""
    return {
        "instanceName": "retailmind",
        "userID": "user123",
        "jsonData": json.dumps(inner),
    }


def _direct_text(phone: str, text: str, *, key: str = "conversation") -> dict:
    return {
        "type": "Message",
        "event": {
            "Info": {
                "Chat": f"{phone}@s.whatsapp.net",
                "Sender": f"{phone}@s.whatsapp.net",
                "IsFromMe": False,
                "IsGroup": False,
            },
            "Message": {key: text} if key == "conversation"
                       else {"extendedTextMessage": {"text": text}},
        },
    }


def test_unknown_number_routes_to_onboarding():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.send_typing") as mock_typing, \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json=_wuzapi_envelope(_direct_text("2348012345678", "Hi")),
        )
        assert resp.status_code == 200
        mock_typing.assert_called_once_with("+2348012345678")
        mock_onboard.assert_called_once_with("+2348012345678", "Hi")


def test_known_number_routes_to_agent_with_single_reply():
    client = TestClient(_make_app())
    retailer = {"id": "demo", "whatsapp": "+2348012345678"}
    with patch("app.messaging.webhook.by_whatsapp", return_value=retailer), \
         patch("app.messaging.webhook.send_typing") as mock_typing, \
         patch("app.messaging.webhook.answer", return_value="reply text") as mock_answer, \
         patch("app.messaging.webhook.send_whatsapp") as mock_send:
        resp = client.post(
            "/webhook/whatsapp",
            json=_wuzapi_envelope(_direct_text("2348012345678", "How were sales?")),
        )
        assert resp.status_code == 200
        mock_typing.assert_called_once_with("+2348012345678")
        mock_answer.assert_called_once()
        # No more "On it..." ack — just the one real reply.
        mock_send.assert_called_once_with("+2348012345678", "reply text")


def test_ignores_own_echoes():
    client = TestClient(_make_app())
    inner = _direct_text("2348012345678", "bot echo")
    inner["event"]["Info"]["IsFromMe"] = True
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_ignores_group_messages():
    client = TestClient(_make_app())
    inner = {
        "type": "Message",
        "event": {
            "Info": {"Chat": "123@g.us", "Sender": "111@lid",
                     "IsFromMe": False, "IsGroup": True},
            "Message": {"conversation": "group chat"},
        },
    }
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_ignores_non_message_events():
    client = TestClient(_make_app())
    inner = {"type": "ChatPresence", "event": {"State": "composing"}}
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_extended_text_message_extracted():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json=_wuzapi_envelope(_direct_text("234", "quoted reply", key="extended")),
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+234", "quoted reply")


def test_lid_sender_falls_back_to_senderalt():
    """When Sender is @lid (privacy mode), SenderAlt carries the phone JID."""
    client = TestClient(_make_app())
    inner = {
        "type": "Message",
        "event": {
            "Info": {
                "Chat": "111@lid",
                "Sender": "111@lid",
                "SenderAlt": "2348012345678@s.whatsapp.net",
                "IsFromMe": False,
                "IsGroup": False,
            },
            "Message": {"conversation": "hi from lid user"},
        },
    }
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+2348012345678", "hi from lid user")


def test_lid_with_no_senderalt_is_dropped():
    client = TestClient(_make_app())
    inner = {
        "type": "Message",
        "event": {
            "Info": {"Chat": "111@lid", "Sender": "111@lid", "SenderAlt": "",
                     "IsFromMe": False, "IsGroup": False},
            "Message": {"conversation": "anonymous"},
        },
    }
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_device_suffix_stripped_from_jid():
    """Senders sometimes include a device suffix like '...:12@s.whatsapp.net'."""
    client = TestClient(_make_app())
    inner = {
        "type": "Message",
        "event": {
            "Info": {
                "Chat": "5491155551122@s.whatsapp.net",
                "Sender": "5491155551122:12@s.whatsapp.net",
                "IsFromMe": False,
                "IsGroup": False,
            },
            "Message": {"conversation": "hi"},
        },
    }
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post("/webhook/whatsapp", json=_wuzapi_envelope(inner))
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+5491155551122", "hi")


def test_form_encoded_payload_works():
    """Real Wuzapi sends application/x-www-form-urlencoded, not JSON."""
    client = TestClient(_make_app())
    inner = _direct_text("2348012345678", "from form")
    form_data = {
        "instanceName": "retailmind",
        "userID": "user123",
        "jsonData": json.dumps(inner),
    }
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+2348012345678", "from form")
