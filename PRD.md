# RetailMind — Product Requirement Document

> An AI Chief Operating Officer for African shopkeepers, delivered over WhatsApp.

---

## 0. Status snapshot (as of 2026-05-26)

What's actually running today:

| Capability | Status |
|---|---|
| WhatsApp gateway (Wuzapi, dockerised, paired to a real number) | ✅ Working |
| LLM-driven WhatsApp onboarding agent (single `act` tool) | ✅ Working |
| Google OAuth + Picker for sheet selection (drive.file scope) | ✅ Working |
| Self-hosted `/go/<token>` short-link redirect | ✅ Working |
| Typing indicator on inbound messages | ✅ Working |
| Supabase persistence (`retailers`, `onboarding_state`) | ✅ Working |
| Analytics engine + 6 insights | ✅ Working (proven offline + via Q&A agent) |
| Q&A agent answering grounded questions from sales data | ✅ Just working end-to-end |
| Daily digest (scheduled, per-retailer time) | ⚠️ Coded, not yet demoed live with a real onboarded retailer |
| Anomaly poll → unsolicited alert | ⚠️ Coded, not yet demoed live |
| Production WhatsApp Business API (WABA) | ❌ Not built — Wuzapi is the stand-in |
| Spreadsheet-in-chat ingestion (CSV attached to WhatsApp) | ❌ Not built |
| Loyverse / POS integrations | ❌ Not built |
| Photo of paper ledger | ❌ Not built |

**Where we are on the roadmap:** mid Phase A → Phase B. A2 (DB-backed multi-tenant + conversational onboarding) is done. A1 (production WABA number) is not — Wuzapi covers it for dev/demo only. B2 (Google Sheets OAuth) is done. B1, B3, B4, B5 are not. See §9 for the full picture.

---

## 1. Problem

Small and mid-size retailers in Africa — kiosks, mini-marts, pharmacies, boutiques — already
**have data**. It lives in a Google Sheet a shopkeeper updates by hand, a POS export, or a CSV.
What they lack is an **operator** — someone who reads the numbers every day and tells them
what to do about them. They can't afford a real analyst, and they won't log into a BI
dashboard to figure out which chart matters.

The result: stockouts that lose sales, dead stock that ties up cash, slow weeks noticed too
late, pricing/mix decisions made on gut feel. The data to prevent all of this exists and
goes unread.

## 2. Solution

RetailMind connects to the retailer's **existing** data source, analyzes it continuously, and
**proactively messages the retailer on WhatsApp** — the app they already live in — with
plain-language insights and the action to take. They can reply in natural language and get
grounded answers from their own numbers.

No new dashboard. No login. No analyst. **An AI Chief Operating Officer that texts you first.**

**Core principle — numbers are computed, prose is generated.** A deterministic analytics
engine (pandas, `app/analytics/`) computes every metric. The LLM only *narrates* those
numbers and answers questions via tools that read the same engine. **RetailMind never invents
a figure.** This is the product's trust pillar — and it's also what makes the data exhaust
auditable enough to plug into financial products later (§9, Phase E).

## 3. Target users

- **Primary:** owner/operator of a single shop or a 2–5 location SMB retailer in Africa
  (Ghana, Kenya, Nigeria, etc.) who already records sales in a Google Sheet, CSV, or POS.
- **Secondary:** the family member / shop assistant who maintains the sheet.

### Persona — "Amina, mini-mart owner, Nairobi"
Records daily sales in a shared Google Sheet. Checks WhatsApp 50+ times a day. Has never
opened a BI tool. Wants to know: *what's selling, what's about to run out, and is this week
good or bad* — without doing the math herself.

## 4. Scope

### In scope (current build)
- **WhatsApp inbound + outbound** via a self-hosted Wuzapi (whatsmeow) gateway, dockerised.
- **LLM-driven onboarding agent** — natural-language conversation, extracts name + shop,
  triggers an OAuth flow when both are known. Single `act` tool call per turn to stay within
  the LLM's per-turn tool-call budget.
- **Google Sheets via OAuth + Picker widget** — retailer signs in with their own Google
  account and picks the sheet (drive.file scope means we only see what they pick).
- **Canonical schema with fuzzy header mapping** — handles `Unit Price`, `unit_price`, `Unit
  Price (GHS)`, `Unit-Price [USD]` etc. without per-sheet config.
- **Analytics engine with a pluggable insight registry**:
  - Revenue trend (daily/weekly)
  - Week-over-week change
  - Best / worst days
  - Top / bottom sellers
  - Low-stock / reorder via sales velocity (days of cover)
  - Anomaly detection (rolling-mean z-score on daily revenue)
- **Two-way conversational AI**: retailer replies on WhatsApp, an LLM tool-use loop calls
  engine tools and answers from real numbers.
- **Proactive delivery** scheduled per-retailer in their local timezone:
  - Daily digest at the retailer's configured time
  - Anomaly poll → unsolicited alert when a high-severity insight crosses threshold
  - On-demand `POST /trigger/{retailer_id}` for live demos
- **Supabase persistence** — `retailers` and `onboarding_state` tables; YAML kept as a dev
  fallback in `config/retailers.yaml`.
- **UX details**: typing indicator on inbound, self-hosted `/go/<token>` redirect for short
  shareable OAuth links, phone-prefix → currency + timezone auto-detection.

### Out of scope (roadmap — §9)
- **Production WhatsApp Business API** (Meta-verified number + templates) — needed before any
  non-test user. Wuzapi is the dev/demo stand-in.
- Spreadsheet file attached **inside** WhatsApp (B1).
- Direct POS API integrations (Loyverse first, then others).
- Photo-of-paper-ledger ingestion and voice-note logging.
- Inventory write-back / purchase-order generation.
- Multi-language localisation (Swahili, Pidgin, French, Twi).
- Forecasting / ML demand prediction.
- Billing & multi-tenant auth UI.

## 5. Onboarding & user experience

**Guiding principle: no dashboard, ever.** The retailer never logs into a web app to "check
their numbers." The only web page in the entire product is the one-time Google Picker after
OAuth — used once, never returned to.

### 5.1 Onboarding — what's built today (WhatsApp-first, self-serve)

1. **First message.** Retailer texts the bot's WhatsApp number. The webhook (`app/messaging/
   webhook.py`) parses the form-encoded Wuzapi payload, recovers the sender's phone (even
   when WhatsApp's `@lid` privacy mode hides it), checks for an existing retailer row, and
   routes to the LLM-driven onboarding agent (`app/onboarding/agent.py`).
2. **Conversational extraction.** The agent's system prompt positions RetailMind as an
   AI Chief Operating Officer (not "chatbot," not "sidekick"). It uses a single `act` tool
   to remember name/shop and decide when to send the OAuth link. Handles partial extractions
   ("Hello I am Michael" → asks only for the shop name).
3. **OAuth link.** When both fields are known, the agent generates a Google OAuth URL with
   PKCE (verifier persisted in onboarding state for the callback), wraps it behind a
   self-hosted `/go/<token>` redirect for a short shareable link, and sends it on WhatsApp
   with a typing indicator beforehand.
4. **Google Picker.** Retailer taps the link → Google login → consent → lands on our Picker
   page → taps the spreadsheet they want connected. We only ever see that one file
   (drive.file scope).
5. **Retailer provisioned.** We POST the picked spreadsheet_id + OAuth tokens into Supabase
   as a new `retailers` row, delete the `onboarding_state` row, send a WhatsApp confirmation,
   and fire the first digest. Future inbound messages skip onboarding entirely — the webhook
   sees the retailer row and routes straight to the Q&A agent.

Identity = the sender's WhatsApp number. No passwords, no signup screen.

### 5.2 Ongoing experience (this is the whole product)

1. **Morning digest** (per-retailer local time, computed offline, narrated by the LLM):
   *"Good morning Amina ☀️ Yesterday you did KES 18,400 (up 12% on last Tuesday). Top
   seller: cooking oil. Heads up — sugar will run out in ~3 days at this pace."*
2. **Proactive alert** (anomaly poll runs every N minutes): sales drop / spike / imminent
   stockout detected → immediate unsolicited WhatsApp.
3. **📈 Auto-rendered charts** on visual insights (anomaly spike, week-over-week, trend,
   top movers) — sent as a WhatsApp image with a 1-2 line caption. List-shaped insights
   (e.g. low_stock) stay text-only. A deterministic policy in `app/charts/policy.py` decides.
4. **Ask anything**: *"how were sales last week vs the week before?"* → typing indicator →
   grounded answer in seconds, every figure traced back to the engine.

## 6. Success metrics

**Demo readiness (where we are pushing now):**
- End-to-end live: a freshly onboarded retailer edits the sheet → unsolicited WhatsApp alert
  arrives within one poll interval.
- `/trigger/{retailer_id}` produces an accurate, natural digest in <5s.
- 3 free-form questions answered correctly from the data.
- Zero hallucinated numbers (every figure traceable to the engine).
- Self-serve onboarding from a fresh number completes without operator intervention.

**Post-MVP (north-star):**
- % of proactive messages a retailer acts on (reorder, price change).
- Weekly active retailers replying to RetailMind.
- Time-to-insight: data change → retailer informed.
- Retention week 4 / week 12.

## 7. Architecture (summary)

```
WhatsApp ── Wuzapi (dockerised whatsmeow) ── webhook (form-encoded, @lid-aware)
                                                  │
                                                  ▼
                                    by_whatsapp(number) in Supabase?
                                          │              │
                                       known          unknown
                                          │              │
                                          ▼              ▼
                                Q&A agent          Onboarding agent
                              (tool-use loop)    (single `act` tool)
                                  │                    │
                                  │                    ├─ remembers name + shop
                                  │                    ├─ on both known: PKCE OAuth URL
                                  │                    │  → /go/<token> redirect → Picker
                                  │                    └─ creates retailers row
                                  ▼
                Engine tools (top_products, daily_summary,
                reorder_risk, current_insights, ...)
                                  │
                                  ▼
                load_source → Connectors → canonical DataFrame (schema.py)
                                  │
                                  ▼
                Analytics engine — pluggable @insight registry
                                  │
                                  ├─ Narrator → daily digest / alerts (LLM prose)
                                  └─ Scheduler (APScheduler) — per-retailer cron + poll
```

**LLM provider**: Groq, `openai/gpt-oss-120b` with `reasoning_effort="low"` for fast
tool-use turns. Single entry point in `app/ai/llm.py` — swap providers in one file.

**WhatsApp gateway**: Wuzapi (free, self-hosted, talks whatsmeow). Replaces an earlier
attempt to use Evolution API. Both are stand-ins for the real WhatsApp Business Cloud API,
which we'll need before non-test users.

**Persistence**: Supabase Postgres (`retailers`, `onboarding_state`). YAML registry kept as a
local dev fallback.

See `CLAUDE.md` for the engineering contract and file map. See `README.md` for setup +
demo script.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates a number | Engine computes everything; the LLM only narrates / queries via tools. Never write a metric in prompt text. |
| WhatsApp linked-device session goes silent | Health-check + reconnect logic; ultimately migrate to WABA for production (gates real users). |
| Wuzapi is not WhatsApp-Business-API-compliant for commercial use | Acceptable for dev/demo and small early users; mandatory swap to WABA before scale. |
| Messy/varied sheet headers (Date vs date vs Order Date, "Unit Price (GHS)") | Fuzzy column auto-mapping in `schema.py`, including paren/bracket-unit stripping. |
| LLM only emits one tool call per turn (observed with gpt-oss on Groq) | Collapsed onboarding into a single `act(name, shop, send_oauth_link, reply)` tool. |
| LLM doesn't call any tool / returns plain content | Agent falls back to `msg.content` if no tool call, then to a generic "say that again" prompt. |
| Latency / cost of LLM calls | Groq is ~250–500 tok/s; per-turn cost is sub-cent at this scale. Prompt-cache system prompts where supported. |
| OAuth interstitial / scope creep scares the retailer | `drive.file` scope (we only see picked files) + a Picker widget framed as "tap your sales sheet". |
| Old retailer dict cached in scheduler after sheet swap | Scheduler re-fetches `get_retailer(id)` on every tick (recently fixed). |

## 9. Roadmap

Strictly sequenced — each phase unblocks the next. Status as of today is marked.

### Phase A — Make it a product, not a demo

**A1. Production WhatsApp Business number** — ❌ Not done. *The hard gate for any
non-test user.* Needs a Meta Business account, business verification (~2–10 business days of
Meta review), display-name approval, and **pre-approved templates** for business-initiated
messages. Wuzapi is the current stand-in: it works because OUR number runs the bot and
retailers WhatsApp it, but it leans on the linked-device protocol which is grey-zone for
commercial use and prone to silent disconnects. Code change to swap senders is trivial
(single client module — `app/messaging/wuzapi_client.py` → `app/messaging/waba_client.py`);
the work is the Meta paperwork. **The next priority after MVP-demo is solid.**

**A2. DB-backed multi-tenant + conversational onboarding** — ✅ **Done.** Supabase
`retailers` + `onboarding_state` tables; LLM-driven onboarding agent provisions tenants
automatically. WhatsApp phone number IS the account. No founder-in-the-loop YAML edits any
more. YAML still loads as a dev fallback when Supabase isn't configured.

### Phase B — The data-source connector ladder

Built behind the existing canonical-schema layer (`app/schema.py` + `app/connectors/`), so
the engine / AI never change:

**B1. Spreadsheet file in chat** — ❌ Not built. Retailer sends a CSV/Excel into WhatsApp;
ingested with zero external auth. We skipped this in favour of B2 because OAuth was
conceptually cleaner, but B1 remains the lowest-friction self-serve path for retailers who
just have a file on their phone. Worth coming back to.

**B2. Google Sheets via OAuth + Picker** — ✅ **Done.** OAuth with `drive.file` scope +
embedded Google Picker. PKCE-protected. Self-hosted `/go/<token>` redirect to keep links
short.

**B3. POS integration — Loyverse** — ❌ Not built. Loyverse is free, the most widely used
POS among small African retailers, and has an open REST API + OAuth + webhooks. One OAuth
connect → automatic sales sync, no files. Deliberately one POS done well first.

**B4. Photo of the paper ledger** — ❌ Not built. *The acquisition moat.* Most micro-
retailers track sales on paper. Retailer snaps their sales book → vision model → structured
sales → "here's what I read, correct me?" confirm step. This is the differentiator no
dashboard competitor matches.

**B5. Voice-note logging** — ❌ Not built. *"today I sold 12 bags rice, 3 cooking oil"* →
transcription → structured entry. Pairs naturally with B4.

### Phase C — Richer communication

**C1. Visual replies (image output).** RetailMind sends **images, not just text**: a 7-day
revenue trend, product-mix, or stockout-runway chart, plus the paper-ledger confirm preview.
Critical constraint — consistent with the trust pillar: charts are **rendered
deterministically by the engine from real numbers (server-side PNG) and sent via WhatsApp
media; the LLM never draws or invents a chart.**

**C2. Multi-language & code-switching** (Swahili, Pidgin, Hausa, French, Twi). The narrator
is already isolated, so this is mostly prompt/locale work. Onboarding already detects
country from phone prefix for currency + timezone; same mechanism extends to default
language.

### Phase D — From analyst to autonomous operator

**D1. Reorder automation** — drafts the purchase order and (with one-tap approval) messages
the supplier on WhatsApp on the owner's behalf; tracks delivery.

**D2. Demand forecasting & promo/pricing recommendations** — seasonality, paydays, holidays,
dead-stock clearance suggestions.

**D3. Multi-sheet per retailer** — `retailer_sheets` table, pipeline concatenates. Needed
once retailers have multiple branches or year-archives. Pairs with an in-agent "connect
another sheet" tool that fires a fresh OAuth link.

### Phase E — Venture-scale

**E1. Data → embedded credit.** With consent, the clean sales history becomes a credit
signal for shops invisible to banks → unlock inventory financing via partner lenders. The
"engine computes, AI only narrates" rule is what makes this auditable and fundable.
Take-rate on financing is the primary business model.

**E2. Network effects** — anonymised benchmarking ("your rice margin is 8% below similar
nearby shops"), aggregated demand → group-buying / better wholesale pricing (two-sided
marketplace), multi-shop portfolio view (still entirely in WhatsApp).

### Ops (continuous, not a blocker)

Billing and an **internal** operator admin view — *not* a retailer-facing dashboard; the
no-dashboard promise is to the retailer, not to ops.
