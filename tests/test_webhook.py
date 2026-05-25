import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _make_app():
    from app.messaging.webhook import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


def _evolution_payload(jid: str, text: str) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": jid, "fromMe": False},
            "message": {"conversation": text},
        },
    }


def test_unknown_number_routes_to_onboarding():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None) as mock_lookup, \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json=_evolution_payload("2348012345678@s.whatsapp.net", "Hi"),
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+2348012345678", "Hi")


def test_known_number_routes_to_agent():
    client = TestClient(_make_app())
    retailer = {"id": "demo", "whatsapp": "+2348012345678"}
    with patch("app.messaging.webhook.by_whatsapp", return_value=retailer), \
         patch("app.messaging.webhook.answer", return_value="reply text") as mock_answer, \
         patch("app.messaging.webhook.send_whatsapp") as mock_send:
        resp = client.post(
            "/webhook/whatsapp",
            json=_evolution_payload("2348012345678@s.whatsapp.net", "How were sales?"),
        )
        assert resp.status_code == 200
        mock_answer.assert_called_once()
        mock_send.assert_called()


def test_ignores_own_messages():
    """Messages with fromMe=True (bot's own sends) must not loop."""
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post(
            "/webhook/whatsapp",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {"remoteJid": "234@s.whatsapp.net", "fromMe": True},
                    "message": {"conversation": "bot echo"},
                },
            },
        )
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_ignores_non_message_events():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post(
            "/webhook/whatsapp",
            json={"event": "connection.update", "data": {}},
        )
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_extended_text_message_extracted():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {"remoteJid": "234@s.whatsapp.net", "fromMe": False},
                    "message": {
                        "extendedTextMessage": {"text": "quoted reply text"}
                    },
                },
            },
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+234", "quoted reply text")
