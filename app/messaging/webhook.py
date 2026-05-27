"""Wuzapi inbound WhatsApp webhook → route to onboarding or agent.

Wuzapi POSTs application/x-www-form-urlencoded bodies with fields:
    instanceName=<str>
    userID=<str>
    jsonData=<URL-encoded JSON of {event, type}>

For text messages, the inner JSON looks like:
    {"type": "Message",
     "event": {"Info": {"Sender": "<jid>", "Chat": "<jid>",
                         "IsFromMe": false, "IsGroup": false,
                         "SenderAlt": "<phone-jid when Sender is @lid>"},
                "Message": {"conversation": "...",
                            "extendedTextMessage": {"text": "..."}}}}

We skip groups, newsletters, broadcasts, and our own echoes. When Sender is
`@lid` (privacy-mode), we use SenderAlt to recover the phone number.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from datetime import datetime, timezone

from app.ai.agent import answer
from app.messaging.wuzapi_client import send_typing, send_whatsapp
from app.onboarding.fsm import handle as onboarding_handle
from app.retailers import by_whatsapp
from app.scheduler import alert_state as st

log = logging.getLogger("retailmind.webhook")
router = APIRouter()


def _resolve_phone(info: dict) -> str | None:
    """Return E.164 phone (with leading +) from Info, or None if unusable."""
    sender = info.get("Sender", "")
    if "@s.whatsapp.net" in sender:
        return "+" + sender.split("@")[0].split(":")[0]
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

    if info.get("IsFromMe") or info.get("IsGroup"):
        return None

    chat = info.get("Chat", "")
    if "@newsletter" in chat or "@broadcast" in chat or "@g.us" in chat:
        return None

    phone = _resolve_phone(info)
    if phone is None:
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
    """Wuzapi posts form-encoded (and sometimes JSON) — accept both."""
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            payload = await request.json()
        else:
            form = await request.form()
            payload = {k: v for k, v in form.items()}
    except Exception:
        log.exception("inbound: failed to read body")
        return JSONResponse({})

    extracted = _extract(payload)
    if extracted is None:
        return JSONResponse({})

    number, text = extracted
    # Native typing indicator — beats sending a placeholder "On it…" message.
    send_typing(number)

    retailer = by_whatsapp(number)

    if retailer is None:
        try:
            onboarding_handle(number, text)
        except Exception:
            log.exception("onboarding failed for %s", number)
        return JSONResponse({})

    # The retailer messaging us = implicit "I've seen any active alerts".
    # Bumps cooldowns so the next poll doesn't immediately re-fire the same alert.
    try:
        state = st.load_state()
        touched = st.mark_acknowledged(
            state, retailer["id"], datetime.now(timezone.utc).isoformat()
        )
        if touched:
            st.save_state(state)
            log.info("ack'd %d active alert(s) for %s on inbound", touched, retailer["id"])
    except Exception:
        log.exception("failed to ack alerts on inbound for %s", retailer.get("id"))

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
