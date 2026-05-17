"""Twilio inbound WhatsApp webhook → conversational agent → reply."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse

from app.ai.agent import answer
from app.messaging.twilio_client import send_whatsapp
from app.retailers import by_whatsapp

log = logging.getLogger("retailmind.webhook")
router = APIRouter()


@router.post("/webhook/whatsapp", response_class=PlainTextResponse)
async def whatsapp_inbound(From: str = Form(""), Body: str = Form("")) -> str:
    """Twilio posts form-encoded; we reply out-of-band via the REST API and 200 fast."""
    sender, text = From.strip(), Body.strip()
    retailer = by_whatsapp(sender)
    if not retailer:
        log.warning("inbound from unknown number %s", sender)
        return ""  # silently ignore numbers not in the registry

    try:
        reply = answer(retailer, sender, text)
    except Exception:
        log.exception("agent failed for %s", retailer["id"])
        reply = "Sorry, I hit a snag pulling that up. Try again in a moment?"

    try:
        send_whatsapp(sender, reply)
    except Exception:
        log.exception("failed sending reply to %s", sender)
    return ""
