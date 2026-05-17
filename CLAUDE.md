# CLAUDE.md — RetailMind technical guide

RetailMind is a proactive AI business partner for African SMB retailers. It connects to a
retailer's existing sales data (Google Sheet or CSV), analyzes it, and **messages them first on
WhatsApp** with plain-language insights, alerts, and answers to follow-up questions.

Read `PRD.md` for product context. This file is the engineering contract.

## The one rule that matters: numbers are computed, prose is generated

The analytics engine (pandas, `app/analytics/`) computes **every** number. Claude **only**:
1. Narrates a pre-computed insight bundle into WhatsApp prose (`app/ai/narrator.py`), or
2. Answers questions by calling tools that read the same engine (`app/ai/agent.py`).

**Claude must never produce a figure that did not come from the engine.** Any new capability that
involves a metric goes into the engine first, then the narrator/agent surfaces it. This is the
product's trust pillar — do not violate it for convenience.

## Architecture

```
Google Sheet / CSV
   └─ app/connectors/        Connector protocol → canonical pandas DataFrame
        └─ app/schema.py     fuzzy header auto-mapping → canonical columns
             └─ app/analytics/
                  registry.py   @insight decorator (pluggable)
                  insights/     one file per insight
                  engine.py     runs registry → ordered insight bundle (JSON-able)
                       ├─ app/ai/narrator.py   bundle → WhatsApp digest/alerts (Claude)
                       └─ app/ai/agent.py      inbound Q&A, Claude tool-use over engine
                            └─ app/messaging/  Twilio send + inbound webhook
                                 └─ app/scheduler/jobs.py  daily digest + anomaly poll
                                      └─ app/main.py  FastAPI app, scheduler lifespan
```

## Canonical schema

`app/schema.py` defines the single internal sales schema. All connectors return a DataFrame with:

| column | type | required | notes |
|---|---|---|---|
| `date` | datetime64 | yes | parsed via dateutil |
| `product` | str | yes | item name |
| `quantity` | float | yes | units sold |
| `unit_price` | float | yes | price per unit |
| `revenue` | float | yes | derived if missing: `quantity * unit_price` |
| `category` | str | no | optional grouping |
| `unit_cost` | float | no | enables margin insights |

`schema.py` fuzzy-maps common header variants (Item/Product, Qty/Quantity, Amount/Total/Sales →
revenue, Date/Day, etc.). Add header aliases there, not in connectors.

## Adding a new insight (the extensibility path)

This is the most common change ("keep adding capabilities"). One new file, nothing else:

```python
# app/analytics/insights/my_insight.py
from app.analytics.registry import insight, Insight

@insight(name="my_insight", order=50)
def my_insight(df, ctx) -> Insight | None:
    # df: canonical DataFrame.  ctx: {currency, retailer, now, ...}
    ...
    return Insight(
        title="...",
        severity="info",          # info | warn | high
        metrics={"key": value},   # only numbers the engine computed
        finding="one-line factual statement, no prose flourish",
    )
```

`engine.py` auto-discovers everything in `app/analytics/insights/`. `severity="high"` is what the
anomaly poll escalates to a proactive alert. Keep `finding` factual — the narrator adds the warmth.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env                                   # then fill in keys
uvicorn app.main:app --reload
```

Phase smoke-tests (no external services needed for 1–3):

```bash
python -m app.connectors.csv_loader data/sample_sales.csv   # Phase 1: canonical df
python -m app.analytics.engine data/sample_sales.csv         # Phase 2: insight bundle JSON
python -m app.ai.narrator data/sample_sales.csv              # Phase 3: WhatsApp message
curl -X POST http://localhost:8000/trigger/demo              # Phase 4: real WhatsApp send
```

## Conventions

- Python 3.11+, FastAPI, pandas. Type hints on public functions.
- Secrets only via `app/settings.py` (pydantic-settings, reads `.env`). Never hardcode keys.
  Never commit `.env` or `service-account*.json` (see `.gitignore`).
- Retailers are config-driven in `config/retailers.yaml` (no DB in MVP).
- Anthropic: prompt-cache the system prompt; default model from `ANTHROPIC_MODEL` env.
- Keep each phase independently demoable — never break an earlier phase's smoke-test.
- WhatsApp messages: short, warm, action-first, currency-aware. The narrator owns tone.

## Env vars

See `.env.example`. Required for full run: `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`. CSV path works without Google creds; Google Sheets
needs `GOOGLE_SERVICE_ACCOUNT_JSON` and the sheet shared with the service-account email.

## Demo (live)

1. Daily digest already scheduled (or fire `/trigger/demo`).
2. Edit the Google Sheet — add a spike/drop row.
3. Within one anomaly-poll interval an unsolicited WhatsApp alert arrives.
4. Reply with a free-form question → grounded answer.

Full script lives in `README.md`.
