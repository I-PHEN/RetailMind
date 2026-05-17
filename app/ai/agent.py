"""Two-way conversational AI.

A retailer replies on WhatsApp; the model answers using tools that read the SAME analytics
engine / canonical DataFrame. It never computes numbers itself — it calls a tool and relays
the result. Short in-memory history keeps follow-ups coherent.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import pandas as pd

from app.ai.llm import chat
from app.analytics.engine import build_bundle
from app.connectors import load_source

SYSTEM_PROMPT = """You are RetailMind, a warm, sharp business partner the shop owner chats \
with on WhatsApp. Answer questions about THEIR shop using the tools provided.

ABSOLUTE RULE: every number you state must come from a tool result. Never estimate or \
invent figures. If a tool can't answer, say so plainly and suggest what you can tell them.

Keep replies short and WhatsApp-friendly: plain language, a little warmth, money with the \
currency code, action-first when something needs attention. No markdown headers, no essays."""


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


TOOLS = [
    _fn("sales_summary", "Total revenue and units for a period.",
        {"period": {"type": "string",
                     "enum": ["yesterday", "last_7_days", "prev_7_days",
                              "last_30_days", "this_month", "all"]}},
        ["period"]),
    _fn("top_products", "Best (or slowest) selling products over the last N days.",
        {"days": {"type": "integer"},
         "limit": {"type": "integer"},
         "order": {"type": "string", "enum": ["top", "slow"]}}),
    _fn("current_insights",
        "The current proactive insight bundle (trends, anomalies, reorder).", {}),
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
    df = load_source(retailer["source"])
    currency = retailer.get("currency", "")

    hist = _history[sender]
    messages: list[dict[str, Any]] = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + list(hist)
        + [{"role": "user", "content": text}]
    )

    for _ in range(5):  # tool-use loop
        resp = chat(messages, tools=TOOLS, max_tokens=700)
        msg = resp.choices[0].message
        if not getattr(msg, "tool_calls", None):
            reply = (msg.content or "").strip()
            hist.append({"role": "user", "content": text})
            hist.append({"role": "assistant", "content": reply})
            return reply or "Sorry, I couldn't put that together — try rephrasing?"

        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            out = _run_tool(tc.function.name, args, df, currency)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(out, default=str),
            })

    return "That took a few too many steps — could you ask it a simpler way?"
