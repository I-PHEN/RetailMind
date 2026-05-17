"""Turn an engine-computed insight bundle into a warm WhatsApp message.

Hard rule: the model narrates ONLY the numbers in the bundle.
"""
from __future__ import annotations

import json
import re
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
- End with one crisp suggested action or a confident sign-off. No fluff.

WhatsApp formatting (STRICT — this is sent to WhatsApp, not Markdown):
- Bold uses a SINGLE asterisk: *like this*. NEVER use ** or __ or # headers.
- No Markdown headings, no tables, no horizontal rules. Plain text with line breaks only.
- Use simple "•" or "-" bullets at most; keep it skimmable on a phone.
"""


def to_whatsapp(text: str) -> str:
    """Force LLM output into valid WhatsApp formatting (free models ignore the prompt)."""
    # **bold** / __bold__  ->  *bold*  (WhatsApp uses a single asterisk)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.S)
    # Markdown headings "### Title" -> "*Title*"
    text = re.sub(r"(?m)^\s*#{1,6}\s*(.+?)\s*$", r"*\1*", text)
    # Horizontal rules / stray table pipes
    text = re.sub(r"(?m)^\s*([-*_]\s*){3,}$", "", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", "", text)
    # Tidy trailing spaces and collapse 3+ blank lines
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    return to_whatsapp(resp.choices[0].message.content or "")


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
