"""RetailMind FastAPI app: health, on-demand trigger, inbound webhook, scheduler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

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


@app.get("/auth/google/callback", response_class=HTMLResponse)
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> HTMLResponse:
    """Google redirects here after the retailer authorises access to their Sheet."""
    from app.onboarding.oauth import complete_onboarding
    try:
        complete_onboarding(code=code, state_token=state)
    except Exception:
        log.exception("OAuth callback failed")
        return HTMLResponse(
            "<html><body><h2>Something went wrong.</h2>"
            "<p>Please go back to WhatsApp and try again.</p></body></html>",
            status_code=500,
        )
    return HTMLResponse(
        "<html><body>"
        "<h2>You're connected! ✅</h2>"
        "<p>Go back to WhatsApp — RetailMind is sending your first summary now.</p>"
        "</body></html>"
    )


@app.post("/trigger/{retailer_id}")
def trigger(retailer_id: str, mode: str = "digest", send: bool = True) -> dict:
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
    retailer = get_retailer(retailer_id)
    if not retailer:
        raise HTTPException(404, f"unknown retailer {retailer_id!r}")
    try:
        return run_poll(retailer)
    except Exception as exc:
        log.exception("poll failed for %s", retailer_id)
        raise HTTPException(500, str(exc))
