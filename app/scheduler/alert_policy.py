"""Deterministic decision: which high-severity insights are worth interrupting the owner.

This is the safety net. The LLM judge runs AFTER this and may only narrow the list further —
it can never widen it. Only `severity == "high"` insights are ever eligible for an unsolicited
WhatsApp; warn/info live in the morning digest, not interruptions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from app.scheduler import alert_state as st

log = logging.getLogger("retailmind.alert_policy")

WORSEN_STEP = 0.15            # key must grow >15% over last alerted value to re-alert
DEFAULT_COOLDOWN_H = 6
DEFAULT_QUIET = "21:00-07:00"
DEFAULT_DIGEST_SUPPRESS_MIN = 90
_SEV_RANK = {"info": 1, "warn": 2, "high": 3}


def alert_key(ins: dict) -> float:
    """Scalar 'how bad is this' — larger = more urgent. Used for worsening detection."""
    name, m = ins["name"], ins.get("metrics", {})
    if name == "anomaly":
        return abs(float(m.get("z_score", 0)))
    if name == "wow_change":
        return abs(float(m.get("delta_pct", 0)))
    if name == "low_stock":
        days = [it["days_to_reorder"] for it in m.get("items", []) if "days_to_reorder" in it]
        return -min(days) if days else 0.0      # fewer days left = larger key
    return float(_SEV_RANK.get(ins.get("severity"), 1))


def _is_critical(ins: dict) -> bool:
    """Critical events bypass cooldown AND quiet hours."""
    name, m = ins["name"], ins.get("metrics", {})
    if name == "low_stock":
        days = [it["days_to_reorder"] for it in m.get("items", []) if "days_to_reorder" in it]
        return bool(days) and min(days) <= 2
    if name == "anomaly":
        return abs(float(m.get("z_score", 0))) >= 4.0
    return False


def _now_tz(retailer: dict) -> datetime:
    try:
        return datetime.now(ZoneInfo(retailer.get("timezone", "UTC")))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def _in_quiet_hours(now: datetime, window: str) -> bool:
    try:
        start_s, end_s = window.split("-")
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
    except Exception:
        return False
    t = now.time()
    start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = t.replace(hour=eh, minute=em, second=0, microsecond=0)
    cur = now.time()
    if start <= end:                       # same-day window
        return start <= cur < end
    return cur >= start or cur < end        # wraps midnight (e.g. 21:00-07:00)


def select_candidates(bundle: dict, retailer: dict, state: dict,
                      now: datetime | None = None) -> list[tuple[dict, str]]:
    """Return [(insight, reason)] where reason ∈ {new, worsened, escalated}."""
    rid = retailer["id"]
    now = now or _now_tz(retailer)
    cooldown = timedelta(hours=float(retailer.get("alert_cooldown_hours", DEFAULT_COOLDOWN_H)))
    quiet = retailer.get("quiet_hours", DEFAULT_QUIET)
    suppress = timedelta(
        minutes=float(retailer.get("digest_suppress_minutes", DEFAULT_DIGEST_SUPPRESS_MIN))
    )

    dg = st.last_digest(state, rid)
    dg_recent, dg_names = False, []
    if dg:
        try:
            dg_recent = (now - dateparser.parse(dg["at_iso"])) < suppress
            dg_names = dg.get("names", [])
        except Exception:
            dg_recent = False

    out: list[tuple[dict, str]] = []
    for ins in bundle.get("insights", []):
        if ins.get("severity") != "high":
            continue
        name = ins["name"]
        key = alert_key(ins)
        prev = st.get_insight_state(state, rid, name)

        if prev is None:
            reason = "new"
        elif _SEV_RANK.get(ins["severity"], 1) > _SEV_RANK.get(prev.get("severity"), 1):
            reason = "escalated"
        elif key > float(prev.get("key", 0)) * (1 + WORSEN_STEP):
            reason = "worsened"
        else:
            continue  # already alerted and not materially worse → stay quiet

        critical = _is_critical(ins)
        if not critical:
            # Cooldown applies to re-alerts (worsened/escalated of a known insight).
            if prev and prev.get("last_sent_iso"):
                try:
                    since = now - dateparser.parse(prev["last_sent_iso"])
                    if since < cooldown and reason != "escalated":
                        continue
                except Exception:
                    pass
            # Don't re-ping what the morning digest just covered, unless it worsened.
            if dg_recent and name in dg_names and reason == "new":
                continue
            # Quiet hours: defer non-critical (re-evaluated on the next poll).
            if _in_quiet_hours(now, quiet):
                continue

        out.append((ins, reason))

    if out:
        log.info("policy candidates for %s: %s", rid,
                 [(i["name"], r) for i, r in out])
    return out
