"""Proactive engine: per-retailer daily digest + an intelligent anomaly poll.

The poll is what makes RetailMind feel autonomous. Pipeline per poll:
  engine bundle → deterministic policy (cooldown/quiet/worsening) → bounded LLM judge
  → dedicated alert voice → ONE WhatsApp → persist state.
It alerts on a real, new/worsened change and then stays quiet — that contrast is the demo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.ai.alert_judge import judge
from app.ai.narrator import narrate_alert
from app.charts.policy import pick_chart_for_message
from app.messaging.wuzapi_client import send_whatsapp, send_whatsapp_image
from app.pipeline import build_for, run_digest
from app.retailers import all_retailers, get_retailer
from app.scheduler import alert_state as st
from app.scheduler.alert_policy import alert_key, select_candidates

log = logging.getLogger("retailmind.scheduler")


def _daily_digest(retailer: dict) -> None:
    rid = retailer["id"]
    # Re-fetch from the DB so we see updated spreadsheet_id / google_token,
    # not the stale snapshot the scheduler was registered with.
    retailer = get_retailer(rid) or retailer
    try:
        res = run_digest(retailer, mode="digest", send=True)
        # Tell the judge what the owner already heard today (avoid re-pinging it).
        state = st.load_state()
        st.record_digest(state, rid, datetime.now(timezone.utc).isoformat(),
                          res.get("insight_names", []))
        st.save_state(state)
        log.info("daily digest sent to %s", rid)
    except Exception:
        log.exception("daily digest failed for %s", rid)


def run_poll(retailer: dict) -> dict:
    """One intelligent-alert cycle. Returns what happened (used by the demo endpoint)."""
    rid = retailer["id"]
    bundle = build_for(retailer)
    state = st.load_state()

    candidates = select_candidates(bundle, retailer, state)
    if not candidates:
        return {"retailer": rid, "outcome": "no_candidates", "sent": []}

    dg = st.last_digest(state, rid)
    verdict = judge(candidates, (dg or {}).get("names", []), retailer)
    send_names = set(verdict["send"])
    if not send_names:
        return {"retailer": rid, "outcome": "judge_suppressed_all",
                "candidates": [i["name"] for i, _ in candidates],
                "dropped": verdict.get("dropped", []), "sent": []}

    sent = [ins for ins, _ in candidates if ins["name"] in send_names]
    # Chart is restricted to the insights the judge approved.
    pick = pick_chart_for_message(sent)
    has_chart = pick is not None
    message = narrate_alert(sent, verdict.get("headline", ""), retailer, has_chart=has_chart)
    if pick is not None:
        try:
            send_whatsapp_image(retailer["whatsapp"], pick[1], caption=message)
        except Exception:
            log.exception("alert image send failed, falling back to text-only")
            send_whatsapp(retailer["whatsapp"], message)
    else:
        send_whatsapp(retailer["whatsapp"], message)

    now_iso = datetime.now(timezone.utc).isoformat()
    for ins in sent:
        st.set_insight_state(state, rid, ins["name"],
                             ins["severity"], alert_key(ins), now_iso)
    st.save_state(state)
    log.info("ALERT sent to %s insights=%s",
             rid, [i["name"] for i in sent])
    return {"retailer": rid, "outcome": "alert_sent",
            "headline": verdict.get("headline", ""),
            "has_chart": has_chart,
            "chart_insight": pick[0]["name"] if pick else None,
            "sent": [i["name"] for i in sent], "message": message}


def _anomaly_poll(retailer: dict) -> None:
    rid = retailer.get("id")
    # Re-fetch — see _daily_digest for why.
    retailer = get_retailer(rid) or retailer
    try:
        result = run_poll(retailer)
        log.info("poll %s — %s", rid, result["outcome"])
    except Exception:
        log.exception("anomaly poll failed for %s", rid)


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler()
    for r in all_retailers():
        tz = r.get("timezone", "UTC")
        hh, mm = (r.get("digest_time", "08:00").split(":") + ["00"])[:2]
        sched.add_job(
            _daily_digest, CronTrigger(hour=int(hh), minute=int(mm), timezone=tz),
            args=[r], id=f"digest:{r['id']}", replace_existing=True,
        )
        sched.add_job(
            _anomaly_poll, "interval",
            minutes=int(r.get("anomaly_poll_minutes", 5)),
            args=[r], id=f"poll:{r['id']}", replace_existing=True,
        )
    sched.start()
    log.info("scheduler started for %d retailer(s)", len(all_retailers()))
    return sched
