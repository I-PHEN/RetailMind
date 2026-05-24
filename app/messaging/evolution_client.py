"""Evolution API WhatsApp client. Replaces twilio_client.py."""
from __future__ import annotations

import httpx

from app.settings import get_settings

# Module-level settings ref — tests can swap this out
_settings = None


def _s():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def _normalise(number: str) -> str:
    """Return E.164 (+digits) from any reasonable input format."""
    n = number.strip()
    # strip JID suffix
    if "@" in n:
        n = n.split("@")[0]
    # strip whatsapp: prefix
    if n.lower().startswith("whatsapp:"):
        n = n[len("whatsapp:"):]
    # ensure leading +
    if not n.startswith("+"):
        n = "+" + n
    return n


def send_whatsapp(to: str, body: str) -> None:
    """Send a text message to `to` via Evolution API."""
    s = _s()
    if not s.evolution_api_url or not s.evolution_api_key:
        raise RuntimeError("EVOLUTION_API_URL / EVOLUTION_API_KEY not set in env")

    url = f"{s.evolution_api_url.rstrip('/')}/message/sendText/{s.evolution_instance}"
    headers = {"apikey": s.evolution_api_key, "Content-Type": "application/json"}
    payload = {"number": _normalise(to), "text": body}
    resp = httpx.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()


def send_whatsapp_link(to: str, url: str, title: str, body: str) -> None:
    """Send a link preview card — used for the Google OAuth URL during onboarding."""
    s = _s()
    if not s.evolution_api_url or not s.evolution_api_key:
        raise RuntimeError("EVOLUTION_API_URL / EVOLUTION_API_KEY not set in env")

    endpoint = f"{s.evolution_api_url.rstrip('/')}/message/sendLink/{s.evolution_instance}"
    headers = {"apikey": s.evolution_api_key, "Content-Type": "application/json"}
    payload = {
        "number": _normalise(to),
        "linkPreview": {
            "url": url,
            "title": title,
            "description": body,
        },
    }
    resp = httpx.post(endpoint, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
