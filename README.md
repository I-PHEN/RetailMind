# RetailMind 🧠🛒

**An AI business partner that messages retailers first.**

RetailMind connects to a retailer's existing sales data (Google Sheet or CSV), analyzes it
continuously, and proactively sends plain-language insights and alerts over **WhatsApp** — then
answers their follow-up questions in natural language. Built for small/mid-size retailers in
Africa who have data but no analyst.

> Numbers are computed by a deterministic pandas engine. Claude only narrates them and answers
> via tools over that same engine — **RetailMind never invents a figure.**

See [`PRD.md`](PRD.md) for product context and [`CLAUDE.md`](CLAUDE.md) for the engineering guide.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env            # fill in ANTHROPIC + TWILIO keys
python scripts/generate_sample_data.py   # (sample data is already committed)
uvicorn app.main:app --reload
```

### Smoke-test each layer (no external services for 1–3)

```bash
python -m app.connectors.csv_loader data/sample_sales.csv   # canonical DataFrame
python -m app.analytics.engine     data/sample_sales.csv    # insight bundle JSON
python -m app.ai.narrator          data/sample_sales.csv    # WhatsApp message text
curl -X POST http://localhost:8000/trigger/demo             # real WhatsApp send
```

## WhatsApp setup (Twilio sandbox)

1. Twilio Console → Messaging → Try WhatsApp. Note the sandbox number and join code.
2. From the retailer's phone, WhatsApp `join <code>` to the sandbox number.
3. Put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` in `.env`.
4. Set the sandbox **inbound** webhook to `https://<your-host>/webhook/whatsapp`.
5. Put the retailer's number in `config/retailers.yaml` as `whatsapp:+254...`.

## Deploy (Render)

`render.yaml` defines a web service. Push the repo, create a Render Blueprint from it, set the
env vars in the Render dashboard, and point the Twilio inbound webhook at the Render URL.

## Live demo script (≈ 2 minutes)

1. **Proactive digest** — `curl -X POST <host>/trigger/demo`. A warm WhatsApp summary lands on
   the phone (yesterday's revenue, WoW change, top seller, a low-stock heads-up).
2. **Autonomous alert** — open the Google Sheet, add a big sales row (or run the spike). Within
   one anomaly-poll interval an *unsolicited* WhatsApp alert arrives — RetailMind noticed on its
   own.
3. **Ask anything** — reply on WhatsApp: *"how were sales last week vs the week before?"* and
   *"what's about to run out of stock?"* → grounded answers in seconds.
4. **The pitch line:** every number is traceable to the engine; the AI is the messenger and the
   analyst's voice, not the source of truth.

## Architecture

```
Google Sheet / CSV → Connectors → Canonical DataFrame → Analytics engine (pluggable insights)
   → AI Narrator (proactive prose) | AI Agent (inbound Q&A, tool use) → Twilio WhatsApp
   Scheduler: daily digest + anomaly poll  +  on-demand POST /trigger/{retailer_id}
```

Add a new capability = add one file in `app/analytics/insights/`. See `CLAUDE.md`.

## Status

Hackathon MVP. Twilio sandbox (production WhatsApp sender on the roadmap — see `PRD.md`).
