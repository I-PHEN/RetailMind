"""Two-way conversational AI.

A retailer replies on WhatsApp; the model answers using tools that read the SAME analytics
engine / canonical DataFrame. It never computes numbers itself — it calls a tool and relays
the result. Conversation history + long-term facts are persisted to Supabase so the bot
remembers across uvicorn restarts.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil import parser as dateparser

from app.ai.llm import chat
from app.ai.textfmt import to_whatsapp
from app.analytics.engine import build_bundle
from app.charts import renderer
from app.connectors import load_source
from app.messaging.wuzapi_client import send_whatsapp_image
from app.scheduler import alert_state as st
from app.storage import conversation as conv
from app.storage import notes as notes_store
from app.storage import stock as stock_store

log = logging.getLogger("retailmind.agent")


PROMPT_PATTERNS_AND_RULES = """═══ RESPONSE PATTERNS — pick the right one ═══

▸ SINGLE FACT (one numeric answer — "how much did I make yesterday?")
Yesterday: GHS 1,240 — up 18% vs your usual.

▸ COMPARE TWO (X vs Y — "this week vs last week", "last weekend vs the one before")
This week: GHS 5,400
Last week: GHS 4,100 → up 32%

MANDATORY: BOTH numbers appear. NEVER show only one side. NEVER show a % without both raw numbers above it. If a tool returned both — show both, period.

▸ SHORT LIST (top movers, items, options) — max 5, use • bullets
• iPhone case — GHS 980
• Charger — GHS 540
• Earphones — GHS 410

▸ GROUPED BULLETS (capability / overview — "what can you do?", "what's going on?")
*What I can do*
• Pull any sales numbers (revenue, top movers, week vs week, trends)
• Send charts on request — just ask
• Alert you when sales spike or stock is running low

*What I can't do yet*
• See live stock counts unless you tell me
• Place orders or message suppliers

▸ CHART SENT (after send_chart returns {"status":"sent"})
Sent — see above.

▸ ACTION TAKEN (after set_stock / pause_alerts / remember succeed)
Saved: iPhone case — 50 left.
Quiet for 2 hours — talk soon.
Got it — won't forget.

═══ HARD RULES ═══
• 1 line if one fact. Bullets the moment you'd write a third comma.
• No greeting, no sign-off, no "let me know if…", no pep talk.
• Money: currency code + number ("GHS 1,240"). Never K, never symbols.
• Plain words: "spiked" not "z-score", "your usual" not "trailing average".
• At most one functional emoji (⚠️). Usually zero.
• When you know the owner's name, use it sparingly — first reply of a session or after a long gap, not every turn.
• NEVER claim "data unavailable" for the owner's name, shop name, currency, or anything in WHO YOU'RE TALKING TO / THINGS YOU REMEMBER. That's already in your context.
• NEVER repeat the same line or sentence twice in one reply. One statement, one place.
• For ANY comparison: show both raw numbers AND the delta. A delta with only one number is a bug.
• Date references: pull ISO dates from the DATE HINTS table. Same question = same dates every time. No freelancing.

═══ TOOL-SPECIFIC NOTES ═══
• Identity questions ("what's my name? what's my shop?") → answer directly from WHO YOU'RE TALKING TO. No tool needed.
• Stock questions:
   - If the owner TELLS you a stock count ("I have 50 cases") → call `set_stock`.
   - If they ASK "how much do I have" → call `get_stock`.
   - If they ask "what's about to run out" → call `reorder_risk` (sales-velocity estimate).
• Chart / graph / picture / "show me" → call `send_chart` with the matching kind (anomaly | trend | wow | top_movers). After it succeeds, reply with the CHART SENT pattern.
• Date comparisons the fixed `sales_summary` enum can't express → call `compare_periods` with explicit ISO dates.
• "Don't bother me / I'm busy / quiet for N hours" → call `pause_alerts`.
• When the owner volunteers a stable fact about the shop (closed Sundays, sells phones+accessories, prefers Pidgin) → call `remember`. NOT for one-off facts.

═══ BAD vs GOOD: "what can you do?" ═══
BAD (don't do this — wall of prose):
"I can pull any sales numbers you need (revenue, units, top or slow movers, week-over-week comparisons, 30-day trends, reorder-risk estimates) and send you charts of those insights…"

GOOD (use the GROUPED BULLETS pattern above)."""


def _date_hints(retailer: dict[str, Any], now: datetime | None = None) -> dict[str, str]:
    """Pre-computed ISO date ranges in the retailer's local timezone.

    Without this, the LLM guesses what "last weekend" means and contradicts
    itself across calls. With it, every compare_periods call uses the same
    canonical ranges and the math stays consistent.
    """
    try:
        tz = ZoneInfo((retailer.get("timezone") or "UTC").strip() or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    # weekday: Mon=0 … Sun=6
    wd = today.weekday()

    # Last completed Sat-Sun pair (most recent weekend that has fully passed
    # or is in progress today if today is Sat/Sun).
    if wd >= 5:  # Sat or Sun → "last weekend" = this weekend's Sat-Sun
        last_sat = today - timedelta(days=wd - 5)
    else:        # Mon..Fri → most recent past Sat
        last_sat = today - timedelta(days=wd + 2)
    last_sun = last_sat + timedelta(days=1)
    prev_sat = last_sat - timedelta(days=7)
    prev_sun = last_sun - timedelta(days=7)

    # Calendar weeks (Mon-Sun)
    this_mon = today - timedelta(days=wd)
    this_sun = this_mon + timedelta(days=6)
    last_mon = this_mon - timedelta(days=7)
    last_sun_week = this_mon - timedelta(days=1)
    prev_mon = last_mon - timedelta(days=7)
    prev_sun_week = last_mon - timedelta(days=1)

    # Months
    this_month_start = today.replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    return {
        "today_iso": today.isoformat(),
        "today_dow": today.strftime("%A"),
        "yesterday_iso": (today - timedelta(days=1)).isoformat(),
        "last_7_start": (today - timedelta(days=6)).isoformat(),
        "last_7_end": today.isoformat(),
        "prev_7_start": (today - timedelta(days=13)).isoformat(),
        "prev_7_end": (today - timedelta(days=7)).isoformat(),
        "this_week_start": this_mon.isoformat(),
        "this_week_end": this_sun.isoformat(),
        "last_week_start": last_mon.isoformat(),
        "last_week_end": last_sun_week.isoformat(),
        "week_before_last_start": prev_mon.isoformat(),
        "week_before_last_end": prev_sun_week.isoformat(),
        "last_weekend_start": last_sat.isoformat(),
        "last_weekend_end": last_sun.isoformat(),
        "weekend_before_last_start": prev_sat.isoformat(),
        "weekend_before_last_end": prev_sun.isoformat(),
        "this_month_start": this_month_start.isoformat(),
        "this_month_end": today.isoformat(),
        "last_month_start": last_month_start.isoformat(),
        "last_month_end": last_month_end.isoformat(),
    }


def _build_system_prompt(retailer: dict[str, Any], notes: list[str]) -> str:
    owner = (retailer.get("owner_name") or "").strip() or "(unknown)"
    shop = (retailer.get("name") or "").strip() or "(unknown)"
    currency = (retailer.get("currency") or "").strip() or "(unknown)"
    timezone_s = (retailer.get("timezone") or "UTC").strip()
    h = _date_hints(retailer)
    notes_block = "\n".join(f"• {n}" for n in notes) if notes else "(none yet)"
    return f"""You are RetailMind — an AI Chief Operating Officer messaging an African shop owner on WhatsApp. Be sharp, useful, and SHORT.

═══ WHO YOU'RE TALKING TO ═══
Owner name: {owner}
Shop name: {shop}
Currency: {currency}
Timezone: {timezone_s}

═══ DATE HINTS — use these EXACT ranges for date references ═══
Today: {h['today_iso']} ({h['today_dow']})
Yesterday: {h['yesterday_iso']}
Last 7 days: {h['last_7_start']} → {h['last_7_end']}
Previous 7 days: {h['prev_7_start']} → {h['prev_7_end']}
This week (Mon-Sun): {h['this_week_start']} → {h['this_week_end']}
Last week: {h['last_week_start']} → {h['last_week_end']}
Week before last: {h['week_before_last_start']} → {h['week_before_last_end']}
Last weekend (Sat-Sun): {h['last_weekend_start']} → {h['last_weekend_end']}
Weekend before last: {h['weekend_before_last_start']} → {h['weekend_before_last_end']}
This month: {h['this_month_start']} → {h['this_month_end']}
Last month: {h['last_month_start']} → {h['last_month_end']}

CRITICAL: when calling `compare_periods`, copy ISO dates from this table VERBATIM. NEVER guess or recompute. Same question must always use the same dates.

═══ THINGS YOU REMEMBER ABOUT THIS SHOP ═══
{notes_block}

ABSOLUTE RULE: every NUMBER comes from a tool result. Never invent or estimate numbers.
But the identity block above (owner, shop, currency) and the DATE HINTS are known — use them directly.

{PROMPT_PATTERNS_AND_RULES}"""


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
    _fn("sales_summary", "Total revenue and units for a fixed period.",
        {"period": {"type": "string",
                     "enum": ["yesterday", "last_7_days", "prev_7_days",
                              "last_30_days", "this_month", "all"]}},
        ["period"]),
    _fn("top_products", "Best (or slowest) selling products over the last N days.",
        {"days": {"type": "integer"},
         "limit": {"type": "integer"},
         "order": {"type": "string", "enum": ["top", "slow"]}}),
    _fn("reorder_risk",
        "Products at risk of running out soon, estimated from sales velocity "
        "(NOT live stock counts unless the owner has used set_stock).", {}),
    _fn("current_insights",
        "Full proactive insight bundle: revenue trend, week-over-week, anomalies/spikes, "
        "best/worst days, top & slow sellers, and reorder/stock-risk by sales velocity.", {}),
    _fn("send_chart",
        "Send the user a chart as a WhatsApp image. Use ONLY when the user asks for a "
        "chart, graph, picture, image, or visual. `kind` picks what to plot: "
        "'anomaly' (recent spike/drop, 14-day line with the spike day marked red), "
        "'trend' (30-day revenue line), 'wow' (this week vs last week bars), "
        "'top_movers' (top + slow products bar chart). Returns {status, kind}.",
        {"kind": {"type": "string",
                   "enum": ["anomaly", "trend", "wow", "top_movers"]}},
        ["kind"]),
    _fn("set_stock",
        "Save the owner's current stock count for a product. Call when they tell you "
        "how many units they have left (e.g. 'I have 50 iPhone cases'). Upserts.",
        {"product": {"type": "string"},
         "units": {"type": "number"}},
        ["product", "units"]),
    _fn("get_stock",
        "Look up the owner's saved stock counts. Omit `product` to get all snapshots.",
        {"product": {"type": ["string", "null"]}}),
    _fn("compare_periods",
        "Compare revenue/units between two date ranges. All dates ISO YYYY-MM-DD. "
        "ALWAYS copy ranges VERBATIM from the DATE HINTS table in your system prompt — "
        "do NOT compute or guess them. Same question must always pass the same dates. "
        "Labels are recommended (use natural phrases like 'last weekend', 'weekend before').",
        {"start_a": {"type": "string"}, "end_a": {"type": "string"},
         "start_b": {"type": "string"}, "end_b": {"type": "string"},
         "label_a": {"type": ["string", "null"]},
         "label_b": {"type": ["string", "null"]}},
        ["start_a", "end_a", "start_b", "end_b"]),
    _fn("pause_alerts",
        "Stop sending proactive alerts for N hours. Call when the owner says they're "
        "busy / in a meeting / don't want to be disturbed. Max 24 hours per call.",
        {"hours": {"type": "number"},
         "reason": {"type": ["string", "null"]}},
        ["hours"]),
    _fn("remember",
        "Save a long-term fact about this shop you should always recall in future turns "
        "(e.g. 'closed Sundays', 'sells phones and accessories', 'prefers Pidgin'). "
        "Only call for stable facts — NOT for one-off observations or numbers.",
        {"fact": {"type": "string"}},
        ["fact"]),
]


# In-memory fallback for dev / YAML-only mode (no Supabase).
_local_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=8))


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


def _date_range_slice(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    s = dateparser.parse(start).date()
    e = dateparser.parse(end).date()
    mask = (df["date"].dt.date >= s) & (df["date"].dt.date <= e)
    return df[mask]


_CHART_KIND_TO_INSIGHT = {
    "anomaly": "anomaly",
    "trend": "revenue_trend",
    "wow": "wow_change",
    "top_movers": "top_bottom_sellers",
}

_CHART_KIND_TO_RENDERER = {
    "anomaly": renderer.anomaly_spike,
    "trend": renderer.revenue_trend_line,
    "wow": renderer.wow_bars,
    "top_movers": renderer.top_movers_bar,
}


def _send_chart(kind: str, df: pd.DataFrame, currency: str, to: str) -> dict[str, Any]:
    insight_name = _CHART_KIND_TO_INSIGHT.get(kind)
    render = _CHART_KIND_TO_RENDERER.get(kind)
    if not insight_name or not render:
        return {"status": "error", "error": f"unknown chart kind: {kind}"}
    bundle = build_bundle(df, {"currency": currency})
    ins = next((i for i in bundle["insights"] if i["name"] == insight_name), None)
    if ins is None:
        return {"status": "no_data",
                "error": f"not enough data yet to draw a {kind} chart"}
    try:
        png = render(ins.get("metrics", {}))
        send_whatsapp_image(to, png)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "sent", "kind": kind}


def _pause_alerts(retailer_id: str, hours: float, reason: str | None) -> dict[str, Any]:
    hours = max(0.0, min(float(hours or 0), 24.0))
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    state = st.load_state()
    st.set_pause(state, retailer_id, until.isoformat(), reason)
    st.save_state(state)
    return {"status": "paused", "until_iso": until.isoformat(), "hours": hours}


def _run_tool(name: str, args: dict, df: pd.DataFrame, currency: str,
              retailer: dict[str, Any], to: str) -> dict[str, Any]:
    rid = retailer["id"]

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

    if name == "reorder_risk":
        bundle = build_bundle(df, {"currency": currency})
        ls = next((i for i in bundle["insights"] if i["name"] == "low_stock"), None)
        if not ls or not ls["metrics"].get("items"):
            return {"items": [], "note": "No products are running low at the current sales pace."}
        return {
            "method": "sales-velocity estimate (not live stock counts)",
            "items": ls["metrics"]["items"],
        }

    if name == "current_insights":
        bundle = build_bundle(df, {"currency": currency})
        return {"insights": [
            {"title": i["title"], "severity": i["severity"], "finding": i["finding"]}
            for i in bundle["insights"]
        ]}

    if name == "send_chart":
        return _send_chart(args.get("kind", ""), df, currency, to)

    if name == "set_stock":
        product = (args.get("product") or "").strip()
        if not product:
            return {"status": "error", "error": "product required"}
        units = float(args.get("units", 0))
        saved = stock_store.set_stock(rid, product, units)
        return {"status": "saved", "product": product, "units": units,
                "set_at": saved.get("set_at")}

    if name == "get_stock":
        product = (args.get("product") or "").strip()
        if product:
            row = stock_store.get_stock_for(rid, product)
            return {"items": [row] if row else [], "currency": currency}
        return {"items": stock_store.get_stock(rid), "currency": currency}

    if name == "compare_periods":
        try:
            sub_a = _date_range_slice(df, args["start_a"], args["end_a"])
            sub_b = _date_range_slice(df, args["start_b"], args["end_b"])
        except Exception as exc:
            return {"status": "error", "error": f"bad dates: {exc}"}
        rev_a = round(float(sub_a["revenue"].sum()), 2)
        rev_b = round(float(sub_b["revenue"].sum()), 2)
        delta = ((rev_a - rev_b) / rev_b * 100.0) if rev_b else 0.0
        return {
            "a": {"label": args.get("label_a") or f"{args['start_a']}..{args['end_a']}",
                  "revenue": rev_a, "units": int(sub_a["quantity"].sum())},
            "b": {"label": args.get("label_b") or f"{args['start_b']}..{args['end_b']}",
                  "revenue": rev_b, "units": int(sub_b["quantity"].sum())},
            "delta_pct": round(delta, 1),
            "currency": currency,
        }

    if name == "pause_alerts":
        return _pause_alerts(rid, float(args.get("hours", 0)), args.get("reason"))

    if name == "remember":
        fact = (args.get("fact") or "").strip()
        if not fact:
            return {"status": "error", "error": "fact required"}
        notes_store.add_note(rid, fact)
        return {"status": "remembered", "fact": fact}

    return {"error": f"unknown tool {name}"}


def answer(retailer: dict[str, Any], sender: str, text: str) -> str:
    """Answer one inbound WhatsApp message for `retailer` from `sender`."""
    from app.pipeline import source_from_retailer  # local import avoids cycle
    df = load_source(source_from_retailer(retailer))
    currency = retailer.get("currency", "")
    rid = retailer["id"]

    # Memory: prefer Supabase-backed history; fall back to in-memory for dev.
    persisted = conv.recent_messages(rid, limit=16)
    if persisted:
        hist: list[dict[str, str]] = persisted
    else:
        hist = list(_local_history[sender])

    notes = notes_store.get_notes(rid)
    system_prompt = _build_system_prompt(retailer, notes)

    messages: list[dict[str, Any]] = (
        [{"role": "system", "content": system_prompt}]
        + hist
        + [{"role": "user", "content": text}]
    )

    for _ in range(5):  # tool-use loop
        resp = chat(messages, tools=TOOLS, max_tokens=700)
        msg = resp.choices[0].message
        if not getattr(msg, "tool_calls", None):
            reply = to_whatsapp(msg.content or "")
            reply = reply or "Sorry, I couldn't put that together — try rephrasing?"
            # Persist both sides of this turn.
            conv.append_message(rid, "user", text)
            conv.append_message(rid, "assistant", reply)
            # Dev fallback only — Supabase is the real store.
            _local_history[sender].append({"role": "user", "content": text})
            _local_history[sender].append({"role": "assistant", "content": reply})
            return reply

        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            out = _run_tool(tc.function.name, args, df, currency,
                            retailer, retailer.get("whatsapp", sender))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(out, default=str),
            })

    return "That took a few too many steps — could you ask it a simpler way?"
