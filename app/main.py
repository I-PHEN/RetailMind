"""RetailMind FastAPI app: health, on-demand trigger, inbound webhook, scheduler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.messaging.webhook import router as webhook_router
from app.pipeline import run_digest
from app.retailers import all_retailers, get_retailer
from app.scheduler.jobs import run_poll, start_scheduler
from app.settings import get_settings

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


_PICKER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Pick your sales sheet</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 480px;
          margin: 0 auto; padding: 24px; color: #1a1a1a; }}
  h2 {{ font-weight: 600; }}
  button {{ background: #25D366; color: white; border: 0; padding: 14px 22px;
            font-size: 16px; border-radius: 12px; cursor: pointer; width: 100%; }}
  button:disabled {{ background: #ccc; cursor: wait; }}
  .picked {{ margin-top: 16px; padding: 12px; background: #f5f5f5; border-radius: 8px;
             font-size: 14px; }}
  .err {{ color: #c00; margin-top: 16px; }}
</style></head><body>
<h2>One last step ✅</h2>
<p>Tap below to choose the Google Sheet that has your sales data.</p>
<button id="pickbtn">Choose Google Sheet</button>
<div id="picked" class="picked" style="display:none"></div>
<div id="err" class="err"></div>

<script src="https://apis.google.com/js/api.js"></script>
<script src="https://accounts.google.com/gsi/client"></script>
<script>
const ACCESS_TOKEN = {access_token!r};
const API_KEY = {api_key!r};
const STATE_TOKEN = {state_token!r};
const APP_ID = {app_id!r};  // project number from oauth client id

let pickerInited = false;
function loadPicker() {{
  gapi.load('picker', () => {{ pickerInited = true; }});
}}
gapi.load('client', loadPicker);

document.getElementById('pickbtn').onclick = () => {{
  if (!pickerInited) {{ document.getElementById('err').textContent = 'Picker still loading, try again in a sec.'; return; }}
  const view = new google.picker.View(google.picker.ViewId.SPREADSHEETS);
  const picker = new google.picker.PickerBuilder()
    .setAppId(APP_ID)
    .setOAuthToken(ACCESS_TOKEN)
    .setDeveloperKey(API_KEY)
    .addView(view)
    .setCallback(onPicked)
    .build();
  picker.setVisible(true);
}};

function onPicked(data) {{
  if (data.action !== google.picker.Action.PICKED) return;
  const doc = data.docs[0];
  document.getElementById('picked').style.display = 'block';
  document.getElementById('picked').textContent = 'Selected: ' + doc.name + ' — finalising...';
  const btn = document.getElementById('pickbtn');
  btn.disabled = true; btn.textContent = 'Working...';

  fetch('/onboarding/pick-sheet', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: 'state_token=' + encodeURIComponent(STATE_TOKEN)
        + '&spreadsheet_id=' + encodeURIComponent(doc.id),
  }}).then(r => r.text()).then(html => {{
    document.open(); document.write(html); document.close();
  }}).catch(e => {{
    document.getElementById('err').textContent = 'Error: ' + e;
    btn.disabled = false; btn.textContent = 'Choose Google Sheet';
  }});
}}
</script></body></html>
"""


def _app_id_from_client_id(client_id: str) -> str:
    # OAuth client IDs look like "247061318220-xxx.apps.googleusercontent.com"
    # The Picker setAppId wants just the leading project number.
    return client_id.split("-", 1)[0] if "-" in client_id else ""


@app.get("/auth/google/callback", response_class=HTMLResponse)
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> HTMLResponse:
    """Google redirects here after the retailer grants OAuth.

    We exchange the code for tokens, then render a Picker page so the user can
    choose which spreadsheet to connect.
    """
    from app.onboarding.oauth import handle_oauth_callback
    try:
        _, access_token = handle_oauth_callback(code=code, state_token=state)
    except Exception:
        log.exception("OAuth callback failed")
        return HTMLResponse(
            "<html><body><h2>Something went wrong.</h2>"
            "<p>Please go back to WhatsApp and try again.</p></body></html>",
            status_code=500,
        )
    s = get_settings()
    html = _PICKER_HTML.format(
        access_token=access_token,
        api_key=s.google_api_key,
        state_token=state,
        app_id=_app_id_from_client_id(s.google_oauth_client_id),
    )
    return HTMLResponse(html)


@app.post("/onboarding/pick-sheet", response_class=HTMLResponse)
def pick_sheet(
    state_token: str = Form(...),
    spreadsheet_id: str = Form(...),
) -> HTMLResponse:
    """The picker page POSTs here once the user picks a sheet."""
    from app.onboarding.oauth import finalize_with_sheet
    try:
        finalize_with_sheet(state_token=state_token, spreadsheet_id=spreadsheet_id)
    except Exception:
        log.exception("finalize_with_sheet failed")
        return HTMLResponse(
            "<html><body><h2>Something went wrong while connecting that sheet.</h2>"
            "<p>Go back to WhatsApp and try again, or pick a different sheet.</p></body></html>",
            status_code=500,
        )
    return HTMLResponse(
        "<html><body style='font-family:system-ui;max-width:480px;margin:0 auto;padding:24px'>"
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
