"""Wuzapi inbound WhatsApp webhook → route to onboarding or agent.

Wuzapi POSTs envelopes shaped like:
    {
      "instanceName": "...",
      "userID": "...",
      "jsonData": "<stringified JSON of {event, type}>"
    }

For text messages, the inner payload is roughly:
    {"type": "Message",
     "event": {"Info": {"Sender": "<jid>", "Chat": "<jid>",
                         "IsFromMe": false, "IsGroup": false,
                         "SenderAlt": "<phone-jid when Sender is @lid>"},
                "Message": {"conversation": "...",
                            "extendedTextMessage": {"text": "..."}}}}

We skip groups, newsletters, broadcasts, and own echoes. When Sender is `@lid`,
we use SenderAlt (Wuzapi populates it for direct messages from privacy-mode users).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.ai.agent import answer
from app.messaging.wuzapi_client import send_whatsapp
from app.onboarding.fsm import handle as onboarding_handle
from app.retailers import by_whatsapp

log = logging.getLogger("retailmind.webhook")
router = APIRouter()


def _resolve_phone(info: dict) -> str | None:
    """Return E.164 phone (with leading +) from Info, or None if unusable."""
    sender = info.get("Sender", "")
    if "@s.whatsapp.net" in sender:
        return "+" + sender.split("@")[0].split(":")[0]
    # Sender is @lid (or something else) — try SenderAlt
    alt = info.get("SenderAlt", "")
    if "@s.whatsapp.net" in alt:
        return "+" + alt.split("@")[0].split(":")[0]
    return None


def _extract(payload: dict) -> tuple[str, str] | None:
    """Return (E.164 phone, text) or None if this isn't a direct text we should handle."""
    raw = payload.get("jsonData")
    if not raw:
        return None
    try:
        inner = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None

    if inner.get("type") != "Message":
        return None

    event = inner.get("event", {})
    info = event.get("Info", {})

    if info.get("IsFromMe"):
        return None  # echo of our own send
    if info.get("IsGroup"):
        return None  # ignore group messages

    chat = info.get("Chat", "")
    if "@newsletter" in chat or "@broadcast" in chat or "@g.us" in chat:
        return None

    phone = _resolve_phone(info)
    if phone is None:
        log.info("dropped inbound: unresolvable sender %r", info.get("Sender"))
        return None

    msg = event.get("Message", {}) or {}
    text = (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or ""
    ).strip()
    if not text:
        return None

    return phone, text


@router.post("/webhook/whatsapp")
async def whatsapp_inbound(request: Request) -> JSONResponse:
    """Wuzapi posts JSON; we ack immediately and handle out-of-band."""
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
