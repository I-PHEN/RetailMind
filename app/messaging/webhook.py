"""Evolution API inbound WhatsApp webhook → route to onboarding or agent."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.ai.agent import answer
from app.messaging.evolution_client import send_whatsapp
from app.onboarding.fsm import handle as onboarding_handle
from app.retailers import by_whatsapp

log = logging.getLogger("retailmind.webhook")
router = APIRouter()


def _extract(payload: dict) -> tuple[str, str] | None:
    """Return (normalised_number, message_text) or None if not a real inbound message."""
    if payload.get("event") != "messages.upsert":
        return None
    data = payload.get("data", {})
    key = data.get("key", {})
    if key.get("fromMe"):
        return None  # ignore echo of bot's own sends
    jid = key.get("remoteJid", "")
    if not jid:
        return None
    # normalise JID → E.164
    number = "+" + jid.split("@")[0].lstrip("+")
    msg = data.get("message", {})
    text = (
        msg.get("conversation")
        or msg.get("extendedTextMessage", {}).get("text")
        or ""
    ).strip()
    if not text:
        return None
    return number, text


@router.post("/webhook/whatsapp")
async def whatsapp_inbound(request: Request) -> JSONResponse:
    """Evolution posts JSON; we ack immediately and handle out-of-band."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({})

    extracted = _extract(payload)
    if extracted is None:
        return JSONResponse({})

    number, text = extracted
    retailer = by_whatsapp(number)

    if retailer is None:
        try:
            onboarding_handle(number, text)
        except Exception:
            log.exception("onboarding failed for %s", number)
        return JSONResponse({})

    # Known retailer — ack then answer
    try:
        send_whatsapp(number, "📊 On it — pulling your numbers…")
    except Exception:
        log.warning("ack failed for %s", number)

    try:
        reply = answer(retailer, number, text)
        send_whatsapp(number, reply)
    except Exception:
        log.exception("agent failed for %s", retailer.get("id"))
        try:
            send_whatsapp(number, "Sorry, I hit a snag. Try again in a moment?")
        except Exception:
            pass

    return JSONResponse({})
