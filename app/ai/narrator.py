"""Turn an engine-computed insight bundle into a warm WhatsApp message.

Hard rule: the model narrates ONLY the numbers in the bundle.

Two modes, two voices, and a `has_chart` switch that shrinks prose when a chart
will carry the data:
  - digest:   daily morning summary (3 lines text-only, 2 lines with chart)
  - alert:    unsolicited interruption (2 lines text-only, 1 line with chart)
"""
from __future__ import annotations

import json
import sys
from typing import Any

from app.ai.llm import chat
from app.ai.textfmt import to_whatsapp

SYSTEM_PROMPT_TEXT = """You are RetailMind — an AI Chief Operating Officer messaging an African \
shop owner on WhatsApp. Be sharp, useful, and SHORT. WhatsApp screens are small and shop \
owners are busy.

ABSOLUTE RULE: Use ONLY numbers from the provided insight bundle JSON. Never invent, \
estimate, or extrapolate. If it's not in the bundle, don't say it.

HOW TO WRITE THE DIGEST:
- Total length: 2 to 3 short lines. NEVER more.
- ONE finding per line. Format: <what happened> → <one concrete action>.
- Lead with the most urgent finding (high-severity first in the bundle).
- Plain words. NEVER say "z-score", "delta", "standard deviation", "trailing average". \
Say "shot up", "dropped", "running low", "your usual".
- Money: always the currency code from the data (e.g. "GHS 1,240"). No symbols, no abbreviations.
- NO greeting, NO pep talk, NO "great job", NO sign-off.
- At most ONE functional emoji (👋, ⚠️, 🔥). Usually zero.

GOOD EXAMPLE:
Yesterday: GHS 1,240 — up 18% vs your usual.
iPhone case sold 32 units. Restock if you have under 40 left.

BAD EXAMPLE (don't do this):
"Good morning! I hope you're having a wonderful day. Here's your detailed sales summary..."
"""


SYSTEM_PROMPT_WITH_CHART = """You are RetailMind — an AI Chief Operating Officer messaging an \
African shop owner on WhatsApp. A CHART IS ATTACHED to this message. The chart already shows \
the numbers visually. Your caption must NOT restate them.

ABSOLUTE RULE: Use ONLY information from the provided JSON. Never invent or estimate.

HOW TO WRITE THE CAPTION (chart-attached digest):
- Exactly 2 short lines. NEVER more.
- Line 1: ONE-sentence headline of what the chart shows (no numbers).
- Line 2: the single action to take.
- Plain words. NEVER "z-score", "delta", "trailing average".
- NO greeting, NO sign-off, NO emoji unless ⚠️ for a real warning.

GOOD EXAMPLE (chart-attached):
Yesterday was your best day in 3 weeks.
Keep iPhone cases well stocked this week.

BAD EXAMPLE:
"Good morning! As you can see in the chart, yesterday's revenue of GHS 1,240..."
"""


ALERT_SYSTEM_PROMPT_TEXT = """You are RetailMind sending an UNSOLICITED WhatsApp alert to an \
African shop owner. You are INTERRUPTING them — make it worth it and instantly clear.

ABSOLUTE RULE: Use ONLY numbers from the provided JSON. Never invent, change, or extrapolate.

HOW TO WRITE THE ALERT:
- Exactly 2 short lines. NEVER more.
- Line 1: the headline — what happened, punchy, no greeting.
- Line 2: the one action to take.
- Plain words. NEVER "z-score", "anomaly", "deviation". Say "shot up", "dropped sharply", \
"running low".
- Money: currency code + number (e.g. "GHS 480"). Never abbreviate.
- NO greeting, NO preamble, NO sign-off.
- One leading ⚠️ if it's a real warning, otherwise no emoji.

GOOD EXAMPLE:
⚠️ iPhone case sales shot up 4× normal today.
Reorder today — stock likely runs out in 2 days.

BAD EXAMPLE:
"Hi Michael, hope your day is going well. I noticed something interesting..."
"""


ALERT_SYSTEM_PROMPT_WITH_CHART = """You are RetailMind sending an UNSOLICITED WhatsApp alert. \
A CHART IS ATTACHED — it already shows the spike or drop. The caption must NOT restate the \
numbers in the chart.

ABSOLUTE RULE: Use ONLY information from the provided JSON.

HOW TO WRITE THE CAPTION (chart-attached alert):
- Exactly 1 short line. NEVER more.
- Format: <what changed> — <action>. No numbers.
- One leading ⚠️ if it's a real warning, otherwise no emoji.
- NO greeting, NO sign-off, NO preamble.

GOOD EXAMPLE (chart-attached):
⚠️ iPhone case sales just spiked — reorder today.

BAD EXAMPLE:
"As shown in the chart, iPhone 15 case sales hit 4× your normal rate today..."
"""


def narrate_alert(sent_insights: list[dict[str, Any]], headline: str,
                   retailer: dict[str, Any] | None = None,
                   has_chart: bool = False) -> str:
    """LLM #2 — phrase the rule+judge-approved alert in the interruption voice."""
    retailer = retailer or {}
    payload = {
        "shop_name": retailer.get("name", ""),
        "currency": retailer.get("currency", ""),
        "headline": headline,
        "has_chart": has_chart,
        "alerts": [
            {"title": i["title"], "finding": i["finding"], "metrics": i.get("metrics", {})}
            for i in sent_insights
        ],
    }
    system_prompt = ALERT_SYSTEM_PROMPT_WITH_CHART if has_chart else ALERT_SYSTEM_PROMPT_TEXT
    instruction = (
        "Write the chart caption. Exactly 1 line." if has_chart
        else "Write the alert. Exactly 2 lines."
    )
    resp = chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",
             "content": f"{instruction}\n\n{json.dumps(payload, default=str)}"},
        ],
        max_tokens=200,
    )
    return to_whatsapp(resp.choices[0].message.content or "")


def narrate(bundle: dict[str, Any], retailer: dict[str, Any] | None = None,
            mode: str = "digest", has_chart: bool = False) -> str:
    """mode='digest' → morning summary. mode='alert' → interruption alert.

    `has_chart=True` shrinks the caption because the chart carries the data.
    """
    retailer = retailer or {}
    if mode == "digest":
        system_prompt = SYSTEM_PROMPT_WITH_CHART if has_chart else SYSTEM_PROMPT_TEXT
        instruction = (
            "Write the chart caption. Exactly 2 lines." if has_chart
            else "Write the morning digest. 2 to 3 lines max."
        )
    else:
        system_prompt = ALERT_SYSTEM_PROMPT_WITH_CHART if has_chart else ALERT_SYSTEM_PROMPT_TEXT
        instruction = (
            "Write the chart caption. Exactly 1 line." if has_chart
            else "Write a SHORT urgent alert. Exactly 2 lines."
        )

    payload = {
        "shop_name": retailer.get("name", ""),
        "currency": retailer.get("currency", ""),
        "mode": mode,
        "has_chart": has_chart,
        "bundle": bundle,
    }
    resp = chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",
             "content": f"{instruction}\n\nInsight bundle:\n{json.dumps(payload, default=str)}"},
        ],
        max_tokens=300,
    )
    return to_whatsapp(resp.choices[0].message.content or "")


if __name__ == "__main__":  # python -m app.ai.narrator <csv>
    sys.stdout.reconfigure(encoding="utf-8")
    from app.analytics.engine import build_bundle
    from app.connectors.csv_loader import load_csv

    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_sales.csv"
    rtl = {"name": "Amina's Mini-Mart", "currency": "KES"}
    b = build_bundle(load_csv(path), {"currency": "KES"})
    print("──── DIGEST (text) ────")
    print(narrate(b, rtl, "digest"))
    print("\n──── DIGEST (chart caption) ────")
    print(narrate(b, rtl, "digest", has_chart=True))
    print("\n──── ALERT (text) ────")
    print(narrate(b, rtl, "alert"))
    print("\n──── ALERT (chart caption) ────")
    print(narrate(b, rtl, "alert", has_chart=True))
