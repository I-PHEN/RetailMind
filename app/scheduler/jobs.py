"""Proactive engine: per-retailer daily digest + an anomaly poll.

The anomaly poll is what makes RetailMind feel autonomous in the demo — edit the sheet,
and an unsolicited alert arrives without anyone asking. Alerts are de-duped by signature so
the same spike isn't sent every poll.
"""
from __future__ import annotations

import hashlib
import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.pipeline import build_for, run_digest
from app.retailers import all_retailers

log = logging.getLogger("retailmind.scheduler")

# retailer_id -> last alerted high-severity signature (in-memory; MVP has no DB)
_last_alert_sig: dict[str, str] = {}


def _high_sig(bundle: dict) -> str | None:
    highs = [i for i in bundle["insights"] if i["severity"] == "high"]
    if not highs:
        return None
    key = json.dumps(
        [(i["name"], i["metrics"]) for i in highs], sort_keys=True, default=str
    )
    return hashlib.sha1(key.encode()).hexdigest()


def _daily_digest(retailer: dict) -> None:
    try:
        res = run_digest(retailer, mode="digest", send=True)
        log.info("daily digest sent to %s (sid=%s)", retailer["id"], res["twilio_sid"])
    except Exception:
        log.exception("daily digest failed for %s", retailer.get("id"))


def _anomaly_poll(retailer: dict) -> None:
    rid = retailer["id"]
    try:
        bundle = build_for(retailer)
        sig = _high_sig(bundle)
        if sig and sig != _last_alert_sig.get(rid):
            res = run_digest(retailer, mode="alert", send=True)
            _last_alert_sig[rid] = sig
            log.info("ALERT sent to %s (sid=%s)", rid, res["twilio_sid"])
        else:
            log.debug("anomaly poll for %s — nothing new", rid)
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
