"""Offline verification of the intelligent alert pipeline (no WhatsApp, no scheduler).

    python scripts/verify_alerts.py
"""
from __future__ import annotations

import copy
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
logging.disable(logging.CRITICAL)  # silence the intentionally-triggered fail-open exception log

from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.retailers import get_retailer
from app.scheduler import alert_state as st
from app.scheduler.alert_policy import alert_key, select_candidates

# Isolate state to a temp file so we never touch real runtime state.
st._PATH = Path(tempfile.mkdtemp()) / "alert_state.json"

R = get_retailer("demo")
DF = load_source(R["source"])
BUNDLE = build_bundle(DF, {"currency": R["currency"], "retailer": R})
NOON = datetime(2026, 5, 17, 12, 0, tzinfo=ZoneInfo(R.get("timezone", "UTC")))
NIGHT = datetime(2026, 5, 17, 23, 0, tzinfo=ZoneInfo(R.get("timezone", "UTC")))


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        check.failed = True


check.failed = False

# 1. Fresh state → high insights surface as "new"
state = {"_digest": {}}
c1 = select_candidates(BUNDLE, R, state, now=NOON)
print("  candidates:", [(i["name"], r) for i, r in c1])
check("fresh state yields candidates (reason=new)",
      len(c1) > 0 and all(r == "new" for _, r in c1))

# 2. Mark them sent → identical poll yields nothing (no spam)
now_iso = NOON.isoformat()
for ins, _ in c1:
    st.set_insight_state(state, R["id"], ins["name"], ins["severity"],
                         alert_key(ins), now_iso)
c2 = select_candidates(BUNDLE, R, state, now=NOON + timedelta(minutes=5))
check("no re-alert when nothing changed (anti-spam)", c2 == [])

# 3. low_stock goes high (Sugar days drop), gets alerted, then WORSENS → re-alerts
b_hi = copy.deepcopy(BUNDLE)
ls = next(i for i in b_hi["insights"] if i["name"] == "low_stock")
ls["severity"] = "high"                                  # engine would set this at <=3 days
for it in ls["metrics"]["items"]:
    it["days_to_reorder"] = 3.0
state3 = {"_digest": {}}
c3a = select_candidates(b_hi, R, state3, now=NOON)
st.set_insight_state(state3, R["id"], "low_stock", "high",
                     alert_key(ls), NOON.isoformat())
b_worse = copy.deepcopy(b_hi)
lw = next(i for i in b_worse["insights"] if i["name"] == "low_stock")
for it in lw["metrics"]["items"]:
    it["days_to_reorder"] = 1.0                           # worsened + critical (<=2)
c3 = select_candidates(b_worse, R, state3, now=NOON + timedelta(minutes=10))
check("high low_stock alerts, then re-alerts when it worsens",
      any(i["name"] == "low_stock" for i, _ in c3a)
      and any(i["name"] == "low_stock" for i, _ in c3))

# 4. Quiet hours defer non-critical (use a fresh state so reason=new, non-critical)
state_q = {"_digest": {}}
c4 = select_candidates(BUNDLE, R, {**state_q}, now=NIGHT)
non_crit = [i for i, _ in c4 if i["name"] != "low_stock"]
check("quiet hours defer non-critical new alerts", len(c4) < len(c1))

# 5. Digest suppression: digest just covered it, not worsened → suppressed
state_d = {"_digest": {}}
st.record_digest(state_d, R["id"], NOON.isoformat(),
                 [i["name"] for i in BUNDLE["insights"]])
c5 = select_candidates(BUNDLE, R, state_d, now=NOON + timedelta(minutes=30))
check("recent digest suppresses unchanged 'new' items", c5 == [])

# 6. Judge fail-open when the LLM errors
import app.ai.alert_judge as aj

orig = aj.chat
aj.chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LLM down"))
try:
    v = aj.judge(c1, [], R)
finally:
    aj.chat = orig
check("judge fails OPEN (sends all rule-validated on LLM error)",
      set(v["send"]) == {i["name"] for i, _ in c1})

# 7. Judge contract: it may not invent items
class _Msg:  # minimal stub matching resp.choices[0].message.content
    content = '{"send":["totally_made_up","wow_change"],"dropped":[],"headline":"hi"}'


class _Resp:
    choices = [type("C", (), {"message": _Msg()})()]


aj.chat = lambda *a, **k: _Resp()
try:
    has_wow = any(i["name"] == "wow_change" for i, _ in c1)
    v2 = aj.judge(c1, [], R)
finally:
    aj.chat = orig
check("judge cannot add items outside candidates",
      "totally_made_up" not in v2["send"]
      and (("wow_change" in v2["send"]) if has_wow else True))

# 8. reorder_risk tool returns velocity items (the stock-Q&A fix)
from app.ai.agent import _run_tool

rr = _run_tool("reorder_risk", {}, DF, R["currency"])
check("reorder_risk tool returns items",
      isinstance(rr.get("items"), list) and len(rr["items"]) > 0)
print("  reorder_risk sample:", rr["items"][0] if rr["items"] else None)

print("\n" + ("SOME CHECKS FAILED" if check.failed else "ALL CHECKS PASSED"))
sys.exit(1 if check.failed else 0)
