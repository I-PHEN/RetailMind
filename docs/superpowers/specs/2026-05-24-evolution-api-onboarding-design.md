# Design Spec — Evolution API + Self-Serve Onboarding
**Date:** 2026-05-24
**Status:** Approved

---

## 1. Goal

Replace Twilio with Evolution API (self-hosted, Baileys protocol) and add a WhatsApp-first
self-serve onboarding flow backed by Supabase. The result: a retailer taps a `wa.me` link,
completes a short conversation, connects their Google Sheet via OAuth, and starts receiving
daily digests — with no operator intervention.

---

## 2. Architecture Overview

```
wa.me link / QR code
       ↓
Retailer messages RetailMind WhatsApp number
       ↓
Evolution API (Docker on Render, persistent disk at /evolution/instances)
       ↓  POST webhook (JSON)
FastAPI — app/messaging/webhook.py
       ↓
  Is number known in Supabase?
       ├── NO  → app/onboarding/fsm.py  (conversation state machine)
       │              ↓ on completion
       │         Supabase retailers table (status: active)
       └── YES → app/ai/agent.py  (existing Q&A — unchanged)
                      ↓
              app/analytics/engine.py  (unchanged)
                      ↓
              app/messaging/evolution_client.py  (send reply)
```

**Unchanged:** `app/analytics/`, `app/ai/narrator.py`, `app/ai/agent.py`, `app/schema.py`,
`app/scheduler/jobs.py` (already calls `all_retailers()` — Supabase swap is transparent).

---

## 3. Evolution API

### Deployment
- New Docker service on Render using `atendai/evolution-api` official image
- Persistent disk mounted at `/evolution/instances` — stores Baileys session JSON (auth state
  from QR scan); survives restarts and deploys
- Instance name: `retailmind`
- Setup: hit Evolution's `/instance/create` once, scan QR with the business WhatsApp number,
  done — that number is now the bot

### Sending — `app/messaging/evolution_client.py`
Replaces `app/messaging/twilio_client.py` entirely. Public interface:

```python
def send_whatsapp(to: str, body: str) -> None
def send_whatsapp_link(to: str, url: str, title: str, body: str) -> None
```

- `to` format: plain `+2348012345678` (no `whatsapp:` prefix)
- Calls `POST /message/sendText/{instance}` and `POST /message/sendLink/{instance}`
- Strips `whatsapp:` prefix if present (backward compat with any existing callers)

### Receiving — `app/messaging/webhook.py`
Evolution POSTs JSON (not Twilio's form-encoded). Inbound shape:

```json
{
  "event": "messages.upsert",
  "data": {
    "key": { "remoteJid": "2348012345678@s.whatsapp.net" },
    "message": { "conversation": "Hi RetailMind" }
  }
}
```

Webhook handler:
1. Extracts `remoteJid` → strips `@s.whatsapp.net` → normalises to `+<digits>`
2. Extracts message body from `data.message.conversation` (text) or
   `data.message.extendedTextMessage.text` (quoted/rich text)
3. Looks up number in Supabase via `retailers.by_whatsapp(number)`
4. Routes: unknown → `onboarding.fsm.handle()`, known → `agent.answer()`
5. Returns 200 immediately; reply sent out-of-band (same pattern as current webhook)

Webhook URL registered in Evolution: `https://yourapp.onrender.com/webhook/whatsapp`

---

## 4. Supabase Retailer Store

Replaces `config/retailers.yaml` as the live retailer store.

### Schema

```sql
create table retailers (
  id              text primary key,          -- slug e.g. "amina_minimart"
  name            text not null,             -- "Amina's Mini-Mart"
  whatsapp        text not null unique,      -- "+2348012345678"
  currency        text not null default 'USD',
  timezone        text not null default 'Africa/Lagos',
  digest_time     text not null default '08:00',
  spreadsheet_id  text,                      -- Google Sheet ID, null until OAuth done
  google_token    jsonb,                     -- {access_token, refresh_token, expiry}
  status          text not null default 'onboarding',  -- onboarding | active | paused
  created_at      timestamptz default now()
);

create table onboarding_state (
  whatsapp    text primary key,
  step        text not null,    -- greeting | awaiting_name | awaiting_oauth | done
  data        jsonb default '{}',  -- scratch: {name, shop_name, oauth_state_token}
  updated_at  timestamptz default now()
);
```

### `app/retailers.py` — rewritten, same public interface

```python
def all_retailers() -> list[dict]        # scheduler reads this — returns status='active' only
def get_retailer(retailer_id: str)       # trigger endpoint reads this
def by_whatsapp(number: str)             # webhook reads this
def create_retailer(data: dict)          # onboarding calls on completion
def update_retailer(id: str, data: dict) # OAuth token refresh calls this
```

**Dev fallback:** if `SUPABASE_URL` is not set, `retailers.py` falls back to reading
`config/retailers.yaml` — local dev and smoke-tests continue to work with zero external deps.

---

## 5. Onboarding Module — `app/onboarding/`

### Files
```
app/onboarding/
  __init__.py
  fsm.py          # handle(whatsapp, text) → reply string; manages onboarding_state table
  oauth.py        # build_oauth_url(), exchange_code(), store_token()
  name_parser.py  # extract (owner_name, shop_name) from free-form text
```

### Conversation Flow

```
Step: "greeting"  (triggered on first message from unknown number)
  RetailMind: "Hi 👋 I'm RetailMind, your AI business partner.
               What's your name and what do you call your shop?"
  → save step: "awaiting_name"

Step: "awaiting_name"
  Retailer sends: "I'm Amina, Amina's Mini-Mart"
  name_parser extracts: owner="Amina", shop="Amina's Mini-Mart"
  RetailMind: "Nice to meet you Amina! 🛒
               Now I need to see your sales data.
               Tap below to connect your Google Sheet:"
               [link card with OAuth URL]
  → save step: "awaiting_oauth", data: {name, shop_name}

Step: "awaiting_oauth"
  Retailer is in phone browser completing Google OAuth.
  If they message again before completing:
    RetailMind: "Still waiting for you to connect your Google Sheet 👆
                 Tap the link above when you're ready!"
  OAuth redirect received → see Section 6.
```

### Timezone Detection
Phone number prefix → default timezone (no need to ask):
```python
"+234" → "Africa/Lagos"
"+254" → "Africa/Nairobi"
"+233" → "Africa/Accra"
"+256" → "Africa/Kampala"
"+255" → "Africa/Dar_es_Salaam"
# default fallback: "Africa/Lagos"
```

### On Completion (triggered by OAuth redirect, not a WhatsApp message)
1. Create retailer row in Supabase (`status: active`)
2. Delete `onboarding_state` row
3. Send confirmation:
   ```
   "Perfect! I can see [X] products, data from [start]–[end]. 
    I'll message you every morning at [time] ⏰ 
    First summary coming now 👇"
   ```
4. Immediately run the analytics pipeline and send the first digest

---

## 6. Google OAuth Flow

### Setup (one-time, already partially done)
- Google Cloud project: existing (Sheets API already enabled)
- Add `https://yourapp.onrender.com/auth/google/callback` as authorized redirect URI
- Scope: `https://www.googleapis.com/auth/spreadsheets.readonly`

### State Token Pattern (links OAuth back to WhatsApp number)
1. `oauth.build_oauth_url(whatsapp)`:
   - Generate short random token (16 hex chars)
   - Store `{oauth_state_token: token}` in `onboarding_state.data`
   - Return Google OAuth URL with `state=<token>`
2. Retailer completes OAuth on their phone browser
3. Google redirects to `GET /auth/google/callback?code=...&state=<token>`
4. `oauth.exchange_code(code)` → get access + refresh tokens
5. Look up `onboarding_state` where `data->>'oauth_state_token' = state`
   → recover the WhatsApp number
6. Store tokens in `retailers.google_token`
7. Send confirmation WhatsApp + first digest

### New FastAPI Route
```
GET /auth/google/callback
```
Registered in `app/main.py`. Handles token exchange, Supabase writes, WhatsApp confirmation,
first digest trigger. Returns a plain HTML success page (the retailer's phone browser sees it
briefly before they switch back to WhatsApp).

---

## 7. Change Inventory

| File | Action |
|---|---|
| `app/messaging/twilio_client.py` | **Delete** |
| `app/messaging/webhook.py` | **Rewrite** (Evolution JSON format + onboarding routing) |
| `app/messaging/evolution_client.py` | **New** |
| `app/retailers.py` | **Rewrite** (Supabase + YAML fallback) |
| `app/onboarding/__init__.py` | **New** |
| `app/onboarding/fsm.py` | **New** |
| `app/onboarding/oauth.py` | **New** |
| `app/onboarding/name_parser.py` | **New** |
| `app/main.py` | **Extend** (register `/auth/google/callback` route) |
| `app/settings.py` | **Extend** (new env vars) |
| `render.yaml` | **Extend** (Evolution Docker service + persistent disk) |
| `config/retailers.yaml` | **Keep** (dev fallback) |
| `app/analytics/**` | **Untouched** |
| `app/ai/narrator.py` | **Untouched** |
| `app/ai/agent.py` | **Untouched** |
| `app/schema.py` | **Untouched** |
| `app/scheduler/jobs.py` | **Untouched** |

---

## 8. New Environment Variables

```
EVOLUTION_API_URL          # https://evolution.yourapp.onrender.com
EVOLUTION_API_KEY          # set in Evolution dashboard
EVOLUTION_INSTANCE         # retailmind

SUPABASE_URL
SUPABASE_KEY               # service role key (server-side only, never exposed)

GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI  # https://yourapp.onrender.com/auth/google/callback
```

---

## 9. Discovery — How Retailers Find the Number

Retailers never "sign up" on a website. Discovery is a `wa.me` deep link:

```
https://wa.me/2348012345678?text=Hi+RetailMind
```

Tapping this on a phone opens WhatsApp with a pre-filled message. Distribute via:
- A simple one-page landing site (optional, for SEO / sharing)
- Physical flyers with a QR code encoding the `wa.me` link
- Social media bios

The QR-on-flyer pattern is familiar to African SMB owners from M-Pesa / mobile money.

---

## 10. Out of Scope (this iteration)

- CSV/Excel file attachment in WhatsApp (Phase B1 of PRD roadmap)
- Digest time preference during onboarding (default 8am, timezone-detected)
- Multi-language support
- Meta Business API / template messages (PRD Phase A1)
- Billing, admin dashboard
