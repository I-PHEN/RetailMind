"""RetailMind FastAPI app: health, on-demand trigger, inbound webhook, scheduler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.messaging.webhook import router as webhook_router
from app.pipeline import run_digest
from app.retailers import all_retailers, get_retailer
from app.scheduler.jobs import run_poll, start_scheduler

logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("retailmind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = start_scheduler()
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="RetailMind", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "retailers": [r["id"] for r in all_retailers()]}


@app.post("/trigger/{retailer_id}")
def trigger(retailer_id: str, mode: str = "digest", send: bool = True) -> dict:
    """Fire a digest (or alert) on demand — the live-demo button.

    `?send=false` returns the message without sending (safe to call without Twilio).
    `?mode=alert` produces just the urgent items.
    """
    retailer = get_retailer(retailer_id)
    if not retailer:
        raise HTTPException(404, f"unknown retailer {retailer_id!r}")
    try:
        return run_digest(retailer, mode=mode, send=send)
    except Exception as exc:
        log.exception("trigger failed for %s", retailer_id)
        raise HTTPException(500, str(exc))


@app.post("/poll/{retailer_id}")
def poll(retailer_id: str) -> dict:
    """Run one intelligent-alert cycle on demand (the autonomous-alert demo button).

    Same logic the scheduler runs every few minutes: engine → policy → LLM judge →
    alert voice. Returns the outcome: no_candidates / judge_suppressed_all / alert_sent.
    Call it twice with no data change to show it alerts once, then stays quiet.
    """
    retailer = get_retailer(retailer_id)
    if not retailer:
        raise HTTPException(404, f"unknown retailer {retailer_id!r}")
    try:
        return run_poll(retailer)
    except Exception as exc:
        log.exception("poll failed for %s", retailer_id)
        raise HTTPException(500, str(exc))
