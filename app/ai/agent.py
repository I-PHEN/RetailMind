"""Two-way conversational AI.

A retailer replies on WhatsApp; Claude answers using tools that read the SAME analytics
engine / canonical DataFrame. Claude never computes numbers itself — it calls a tool and
relays the result. Short in-memory history keeps follow-ups coherent.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import pandas as pd
from anthropic import Anthropic

from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.settings import get_settings

SYSTEM_PROMPT = """You are RetailMind, a warm, sharp business partner the shop owner chats \
with on WhatsApp. Answer questions about THEIR shop using the tools provided.

ABSOLUTE RULE: every number you state must come from a tool result. Never estimate or \
invent figures. If a tool can't answer, say so plainly and suggest what you can tell them.

Keep replies short and WhatsApp-friendly: plain language, a little warmth, money with the \
currency code, action-first when something needs attention. No markdown headers, no essays."""

TOOLS = [
    {
        "name": "sales_summary",
        "description": "Total revenue and units for a period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["yesterday", "last_7_days", "prev_7_days",
                             "last_30_days", "this_month", "all"],
                }
            },
            "required": ["period"],
        },
    },
    {
        "name": "top_products",
        "description": "Best (or slowest) selling products over the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 14},
                "limit": {"type": "integer", "default": 5},
                "order": {"type": "string", "enum": ["top", "slow"], "default": "top"},
            },
        },
    },
    {
        "name": "current_insights",
        "description": "The current proactive insight bundle (trends, anomalies, reorder).",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=8))


def _period_slice(df: pd.DataFrame, period: str) -> pd.DataFrame:
    end = df["date"].max().normalize()
    if period == "yesterday":
        return df[df["date"].dt.normalize() == end]
    if period == "last_7_days":
        return df[df["date"] >= end - timedelta(days=6)]
    if period == "prev_7_days":
        return df[(df["date"] >= end - timedelta(days=13)) & (df["date"] <= end - timedelta(days=7))]
    if period == "last_30_days":
        return df[df["date"] >= end - timedelta(days=29)]
    if period == "this_month":
        return df[df["date"] >= end.replace(day=1)]
    return df


def _run_tool(name: str, args: dict, df: pd.DataFrame, currency: str) -> dict[str, Any]:
    if name == "sales_summary":
        sub = _period_slice(df, args.get("period", "last_7_days"))
        return {
            "period": args.get("period"),
            "revenue": round(float(sub["revenue"].sum()), 2),
            "units": int(sub["quantity"].sum()),
            "days": int(sub["date"].dt.normalize().nunique()),
            "currency": currency,
        }
    if name == "top_products":
        days = int(args.get("days", 14))
        end = df["date"].max().normalize()
        sub = df[df["date"] >= end - timedelta(days=days - 1)]
        agg = sub.groupby("product").agg(
            revenue=("revenue", "sum"), units=("quantity", "sum")
        ).sort_values("revenue", ascending=args.get("order") == "slow")
        rows = agg.head(int(args.get("limit", 5)))
        return {
            "window_days": days,
            "products": [
                {"product": p, "revenue": round(float(r.revenue), 2), "units": int(r.units)}
                for p, r in rows.iterrows()
            ],
            "currency": currency,
        }
    if name == "current_insights":
        bundle = build_bundle(df, {"currency": currency})
        return {"insights": [
            {"title": i["title"], "severity": i["severity"], "finding": i["finding"]}
            for i in bundle["insights"]
        ]}
    return {"error": f"unknown tool {name}"}


def answer(retailer: dict[str, Any], sender: str, text: str) -> str:
    """Answer one inbound WhatsApp message for `retailer` from `sender`."""
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)
    df = load_source(retailer["source"])
    currency = retailer.get("currency", "")

    hist = _history[sender]
    messages: list[dict[str, Any]] = list(hist) + [{"role": "user", "content": text}]

    for _ in range(5):  # tool-use loop
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=700,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            hist.append({"role": "user", "content": text})
            hist.append({"role": "assistant", "content": reply})
            return reply or "Sorry, I couldn't put that together — try rephrasing?"

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = _run_tool(block.name, block.input or {}, df, currency)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(out),
                })
        messages.append({"role": "user", "content": results})

    return "That took a few too many steps — could you ask it a simpler way?"
