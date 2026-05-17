"""Turn an engine-computed insight bundle into a warm WhatsApp message.

Hard rule: the model narrates ONLY the numbers in the bundle.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from app.ai.llm import chat

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
    resp = chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"{instruction}\n\nInsight bundle:\n{json.dumps(payload, default=str)}"},
        ],
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip()


if __name__ == "__main__":  # python -m app.ai.narrator <csv>
    sys.stdout.reconfigure(encoding="utf-8")  # WhatsApp text has emojis; Windows console is cp1252
    from app.analytics.engine import build_bundle
    from app.connectors.csv_loader import load_csv

    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_sales.csv"
    rtl = {"name": "Amina's Mini-Mart", "currency": "KES"}
    b = build_bundle(load_csv(path), {"currency": "KES"})
    print("──── DIGEST ────")
    print(narrate(b, rtl, "digest"))
    print("\n──── ALERT ────")
    print(narrate(b, rtl, "alert"))
