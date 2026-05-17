"""Turn an engine-computed insight bundle into a warm WhatsApp message.

Hard rule: the model narrates ONLY the numbers in the bundle.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from app.ai.llm import chat
from app.ai.textfmt import to_whatsapp

SYSTEM_PROMPT = """You are RetailMind, an expert retail analyst messaging a shop owner on \
WhatsApp. Think like a sharp data analyst, not a cheerleader.

ABSOLUTE RULE: Use ONLY numbers present in the provided insight bundle JSON. Never invent, \
estimate, or extrapolate a figure. If something isn't in the bundle, don't mention it.

How to write:
- Be brief and analytical. Lead with the single most important finding (high-severity items \
are ordered first). State what it means, then the concrete action.
- For each point: the number → the implication → what to do. Not just a restatement of data.
- Plain words, not jargon: say "a sharp spike", never "z-score" or "−2.3σ".
- Money: always the exact currency code from the data, e.g. "KES 357,065". Never abbreviate
  it ("K"), never use a symbol, never drop it.
- No motivational filler, no pep talk, no "great job", no "keep it up", no sign-off pleasantries.
- At most ONE emoji, and only a functional one (e.g. ⚠️ for a real alert). Usually none.
- Tight: a short greeting line, then the findings. Aim for 5–9 lines total.
"""


ALERT_SYSTEM_PROMPT = """You are RetailMind sending an UNSOLICITED WhatsApp alert — you are \
interrupting a busy shop owner, so it must be worth it and instantly clear.

ABSOLUTE RULE: Use ONLY numbers present in the provided JSON. Never invent or change a figure.

How to write the alert:
- First line: the headline given to you (or, if empty, the single most urgent finding) as a \
short punchy line. Optionally one leading ⚠️ if it's a genuine warning.
- Then, per item: what changed → why it matters now → the one action to take. One line each.
- 2–4 lines total. No greeting, no preamble, no "hope you're well", no sign-off, no recap of \
routine numbers. This is an interruption, not a report.
- Plain words, no jargon ("a sharp drop", never "z-score").
- Money: exact currency code from the data, e.g. "KES 80,835". Never abbreviate or drop it.
"""


def narrate_alert(sent_insights: list[dict[str, Any]], headline: str,
                   retailer: dict[str, Any] | None = None) -> str:
    """LLM #2 — phrase the rule+judge-approved alert in the interruption voice."""
    retailer = retailer or {}
    payload = {
        "shop_name": retailer.get("name", ""),
        "currency": retailer.get("currency", ""),
        "headline": headline,
        "alerts": [
            {"title": i["title"], "finding": i["finding"], "metrics": i.get("metrics", {})}
            for i in sent_insights
        ],
    }
    resp = chat(
        messages=[
            {"role": "system", "content": ALERT_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Write the alert.\n\n{json.dumps(payload, default=str)}"},
        ],
        max_tokens=350,
    )
    return to_whatsapp(resp.choices[0].message.content or "")


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
