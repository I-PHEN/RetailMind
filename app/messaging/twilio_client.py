"""Twilio WhatsApp send. Sandbox-friendly; one function the rest of the app calls."""
from __future__ import annotations

from twilio.rest import Client

from app.settings import get_settings

# WhatsApp bodies over ~1600 chars are rejected by Twilio — keep digests tight.
MAX_LEN = 1500


def send_whatsapp(to: str, body: str) -> str:
    """Send `body` to `to` (format: 'whatsapp:+2547...'). Returns the message SID."""
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token):
        raise RuntimeError("Twilio credentials missing — set TWILIO_* in .env")

    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    if len(body) > MAX_LEN:
        body = body[: MAX_LEN - 1] + "…"

    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    msg = client.messages.create(from_=s.twilio_whatsapp_from, to=to, body=body)
    return msg.sid
