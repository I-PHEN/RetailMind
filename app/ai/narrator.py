"""Turn an engine-computed insight bundle into a warm WhatsApp message.

Hard rule: Claude narrates ONLY the numbers in the bundle. The system prompt is prompt-cached
(it's static) so repeated digests are cheap and fast.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from anthropic import Anthropic

from app.settings import get_settings

SYSTEM_PROMPT = """You are RetailMind, a sharp, warm business partner texting a shop owner on \
WhatsApp. You are NOT a chatbot reading a report — you are the analyst they never had.

ABSOLUTE RULE: Use ONLY numbers present in the provided insight bundle JSON. Never invent, \
estimate, or extrapolate a figure. If something isn't in the bundle, don't mention it.

Voice & format:
- Open with a short, friendly greeting using the retailer/shop name if given.
- Lead with what matters most (high-severity items first — they are ordered for you).
- Plain language a busy non-analyst understands. Translate stats ("a spike", not "+2.3σ").
- Short. WhatsApp-length. Use line breaks and at most a few tasteful emojis.
- Be concrete and action-first: if something needs reordering or attention, say so plainly.
- Always show money with the currency code from the bundle.
- End with one crisp suggested action or a confident sign-off. No fluff, no markdown headers.
"""


def _client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def narrate(bundle: dict[str, Any], retailer: dict[str, Any] | None = None,
            mode: str = "digest") -> str:
    """mode='digest' → full morning summary. mode='alert' → just the urgent item(s)."""
    retailer = retailer or {}
    instruction = (
        "Write the morning digest." if mode == "digest"
        else "Write a SHORT urgent alert — only the high-severity finding(s), nothing else."
    )
    payload = {
        "shop_name": retailer.get("name", ""),
        "currency": retailer.get("currency", ""),
        "mode": mode,
        "bundle": bundle,
    }
    settings = get_settings()
    resp = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=600,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": f"{instruction}\n\nInsight bundle:\n{json.dumps(payload, default=str)}",
        }],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


if __name__ == "__main__":  # python -m app.ai.narrator <csv>
    from app.analytics.engine import build_bundle
    from app.connectors.csv_loader import load_csv

    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_sales.csv"
    rtl = {"name": "Amina's Mini-Mart", "currency": "KES"}
    b = build_bundle(load_csv(path), {"currency": "KES"})
    print("──── DIGEST ────")
    print(narrate(b, rtl, "digest"))
    print("\n──── ALERT ────")
    print(narrate(b, rtl, "alert"))
