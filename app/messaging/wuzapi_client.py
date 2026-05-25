"""Wuzapi WhatsApp client — send-only HTTP wrapper.

Wuzapi exposes a per-user token (set via the admin panel after pairing a number).
We POST to /chat/send/text with header `Token: <user-token>` and body
`{"Phone": "<digits>@s.whatsapp.net", "Body": "..."}`.

Link messages get sent as plain text with the URL inlined — WhatsApp auto-previews.
"""
from __future__ import annotations

import httpx

from app.settings import get_settings

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


def send_whatsapp_link(to: str, url: str, title: str, body: str) -> None:
    send_whatsapp(to, f"*{title}*\n{body}\n\n{url}")
