"""Wuzapi WhatsApp client — send-only HTTP wrapper.

Wuzapi exposes a per-user token (set via the admin panel after pairing a number).
We POST to /chat/send/text with header `Token: <user-token>` and body
`{"Phone": "<digits>@s.whatsapp.net", "Body": "..."}`.

For OAuth links we use our own self-hosted /go/<token> redirect (built in main.py),
not a third-party shortener — that way we control the link entirely.
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.settings import get_settings

log = logging.getLogger("retailmind.wuzapi")

_settings = None


def _s():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def _normalise(number: str) -> str:
    """Return digits-only phone from any reasonable input format."""
    n = number.strip()
    if "@" in n:
        n = n.split("@")[0]
    if n.lower().startswith("whatsapp:"):
        n = n[len("whatsapp:"):]
    n = n.lstrip("+")
    return n


def send_whatsapp(to: str, body: str) -> None:
    s = _s()
    if not s.wuzapi_api_url or not s.wuzapi_token:
        raise RuntimeError("Wuzapi not configured (set WUZAPI_API_URL and WUZAPI_TOKEN)")
    base = s.wuzapi_api_url.rstrip("/")
    headers = {"Token": s.wuzapi_token, "Content-Type": "application/json"}
    payload = {"Phone": f"{_normalise(to)}@s.whatsapp.net", "Body": body}
    resp = httpx.post(f"{base}/chat/send/text", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()


def send_whatsapp_image(to: str, image_bytes: bytes, caption: str = "") -> None:
    """Send a PNG image with optional caption.

    Wuzapi (whatsmeow) expects a base64-encoded data URI in the Image field.
    Endpoint: POST /chat/send/image, body {Phone, Image, Caption}.
    """
    s = _s()
    if not s.wuzapi_api_url or not s.wuzapi_token:
        raise RuntimeError("Wuzapi not configured (set WUZAPI_API_URL and WUZAPI_TOKEN)")
    base = s.wuzapi_api_url.rstrip("/")
    headers = {"Token": s.wuzapi_token, "Content-Type": "application/json"}
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "Phone": f"{_normalise(to)}@s.whatsapp.net",
        "Image": f"data:image/png;base64,{b64}",
        "Caption": caption or "",
    }
    resp = httpx.post(f"{base}/chat/send/image", json=payload, headers=headers, timeout=60)
    resp.raise_for_status()


def send_whatsapp_link(to: str, url: str, title: str, body: str) -> None:
    """Send a message that contains a URL. The caller is responsible for
    using a short URL (e.g. our /go/<token> redirect) if the source URL is long."""
    send_whatsapp(to, f"{body}\n\n👉 {url}")


def send_typing(to: str) -> None:
    """Show 'typing…' in the user's chat. Fire-and-forget: never raises.

    WhatsApp's typing indicator auto-clears after ~15s, and the next outbound
    message clears it immediately, so we don't need to send `paused` separately
    for most flows.
    """
    _set_presence(to, "composing")


def send_paused(to: str) -> None:
    """Explicitly stop the typing indicator. Fire-and-forget: never raises."""
    _set_presence(to, "paused")


def _set_presence(to: str, state: str) -> None:
    s = _s()
    if not s.wuzapi_api_url or not s.wuzapi_token:
        return  # silent — typing is a nicety, not a requirement
    base = s.wuzapi_api_url.rstrip("/")
    headers = {"Token": s.wuzapi_token, "Content-Type": "application/json"}
    payload = {"Phone": _normalise(to), "State": state}
    try:
        httpx.post(f"{base}/chat/presence", json=payload, headers=headers, timeout=5)
    except Exception as e:
        log.warning("set_presence(%s) failed: %s", state, e)
