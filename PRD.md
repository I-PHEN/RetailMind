# RetailMind — Product Requirement Document

> An AI business partner that messages retailers first.

---

## 1. Problem

Small and mid-size retailers in Africa — kiosks, mini-marts, pharmacies, boutiques — already
**have data**. It lives in a Google Sheet a shopkeeper updates by hand, a POS export, or a CSV.
What they lack is an **analyst**. They cannot afford one, and they do not have time to log into a
BI dashboard and figure out which chart matters.

The result: stockouts that lose sales, dead stock that ties up cash, slow weeks noticed too late,
and pricing/mix decisions made on gut feel. The data to prevent all of this exists and goes unread.

## 2. Solution

RetailMind connects to the retailer's **existing** data source, analyzes it continuously, and
**proactively messages the retailer on WhatsApp** — the app they already live in — with
plain-language insights and alerts. They can also message back and ask questions in natural
language and get answers grounded in their own numbers.

No new dashboard. No login. No analyst. A smart business partner that texts you first.

**Core principle — numbers are computed, prose is generated.** A deterministic analytics engine
(pandas) computes every metric. Claude only *narrates* those numbers and answers questions via
tools that read the same engine. RetailMind never invents a figure. This is the trust pillar.

## 3. Target users

- **Primary:** owner/operator of a single shop or a 2–5 location SMB retailer in Africa
  (Kenya, Nigeria, Ghana, etc.) who records sales in a Google Sheet or POS export.
- **Secondary:** the family member / shop assistant who maintains the sheet.

### Persona — "Amina, mini-mart owner, Nairobi"
Records daily sales in a shared Google Sheet. Checks WhatsApp 50+ times a day. Has never opened
a BI tool. Wants to know: *what's selling, what's about to run out, and is this week good or bad* —
without doing the math herself.

## 4. Scope

### In scope (hackathon MVP)
- Connect to a **Google Sheet** or **CSV** of sales data; auto-map messy column headers to a
  canonical schema.
- Analytics engine with a **pluggable insight registry**:
  - Revenue trend (daily/weekly)
  - Week-over-week change
  - Best / worst days
  - Top / bottom sellers
  - Low-stock / reorder via sales velocity (days of cover)
  - Anomaly detection (rolling-mean z-score on daily revenue)
- **Proactive delivery** over WhatsApp (Twilio):
  - Scheduled daily digest (per-retailer time/timezone)
  - Anomaly poll → unsolicited alert when a high-severity insight crosses threshold
  - On-demand `POST /trigger/{retailer_id}` for live demos
- **Two-way conversational AI**: retailer replies on WhatsApp, Claude answers from their data via
  tool use.
- Config-driven multi-retailer support (`config/retailers.yaml`).

### Out of scope (roadmap)
- Production WhatsApp sender (verified Meta Business number + templates) — MVP uses the Twilio
  sandbox; this is the #1 roadmap item and the gate for real users (see §9).
- Self-serve WhatsApp-first onboarding (§5.1) — MVP uses concierge onboarding via YAML (§5.2).
- Direct POS API integrations (Square, Loyverse, etc.).
- Inventory write-back / purchase-order generation.
- Multi-language localization (Swahili, Pidgin, French) — designed for, not shipped in MVP.
- Forecasting / ML demand prediction.
- Billing & multi-tenant auth.

## 5. Onboarding & user experience

**Guiding principle: no dashboard, ever.** The retailer never logs into a web app to "check
their numbers." Onboarding is a one-time doorway that lives as close to WhatsApp as possible;
after that, the entire product is the WhatsApp thread. A one-time setup link or setup
conversation is *not* a dashboard — it is used once and never returned to.

### 5.1 Onboarding — target model (WhatsApp-first, self-serve)

1. Retailer taps a `wa.me` link or scans a QR (flyer, word of mouth) → opens a chat with the
   RetailMind number.
2. RetailMind replies conversationally: *"Hi 👋 I'm RetailMind. To get started I need to see
   your sales. Do you keep them in a spreadsheet file, or Google Sheets?"*
3. **Connect data — two branches:**
   - **Spreadsheet file:** *"Just send me the file here."* They attach a CSV/Excel **inside
     the WhatsApp chat** → ingested. Zero external auth; fully consistent with the thesis.
     This is the primary self-serve path.
   - **Google Sheets:** RetailMind sends one secure link → a single "Connect your Google
     Sheet" page → **Google sign-in (OAuth)** → pick the sheet → done. (OAuth, *not*
     share-with-service-account — non-technical owners will not reliably do the latter.)
4. **Confirmation (trust moment):** RetailMind echoes what it understood —
   *"Got it: 14 products, data Jan–May. First summary now, then every morning at 8am 👍?"*
   This is where `schema.py`'s fuzzy column mapping gets a human sanity-check.
5. Done. Identity = the sender's WhatsApp number (no separate account/login system needed).

### 5.2 Onboarding — MVP/launch reality (concierge)

For the hackathon and the first ~10 retailers, onboarding is **operator-assisted**: the
founder adds the retailer to `config/retailers.yaml` (sheet/CSV + WhatsApp number + digest
time); the retailer joins the Twilio sandbox once (`join <code>`). This is a deliberate
"do things that don't scale" launch tactic, **not** the product onboarding — see §9.

### 5.3 Ongoing experience (this is the whole product)

1. **Morning digest:** "Good morning Amina ☀️ Yesterday you did KES 18,400 (up 12% on last
   Tuesday). Top seller: cooking oil. Heads up — sugar will run out in ~3 days at this pace."
2. **Proactive alert:** sales drop / spike / imminent stockout detected → immediate WhatsApp.
3. **Ask anything:** "how were sales last week vs the week before?" → grounded answer in seconds.

## 6. Success metrics

**Hackathon (demo):**
- End-to-end live: edit the sheet → unsolicited WhatsApp alert arrives < 1 poll interval.
- `/trigger` produces an accurate, natural digest on a real phone in < 5s.
- 3 free-form questions answered correctly from the data.
- Zero hallucinated numbers (every figure traceable to the engine).

**Post-hackathon (north-star):**
- % of proactive messages a retailer acts on (reorder, price change).
- Weekly active retailers replying to RetailMind.
- Time-to-insight: data change → retailer informed.

## 7. Architecture (summary)

```
Google Sheet / CSV → Connectors → Canonical DataFrame → Analytics engine (pluggable insights)
   → AI Narrator (proactive prose)  |  AI Agent (inbound Q&A, tool use)  → Twilio WhatsApp
   Scheduler: daily digest + anomaly poll  +  on-demand /trigger
```

See `CLAUDE.md` for the technical guide and `README.md` for setup + demo script.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinates a number | Engine computes everything; Claude only narrates/queries via tools |
| Twilio sandbox onboarding friction in demo | Pre-join sandbox before judging; documented in README |
| Messy/varied sheet headers | Fuzzy column auto-mapping in `schema.py` |
| Latency/cost in scheduler loop | Sonnet 4.6 + prompt-cached system prompt; Opus only if needed |
| Google API auth slow to set up | CSV connector works with zero external auth as fallback |

## 9. Roadmap (post-MVP)

Ordered by what unblocks real users first.

1. **Production WhatsApp Business number** — *the key dependency for any real user.* The
   Twilio sandbox `join <code>` step makes self-serve impossible. Requires a Meta Business
   account, business verification (~2–10 business days of Meta review — calendar time, not
   build time; can run in parallel with development), display-name approval, and
   **pre-approved message templates** for business-initiated messages. Design implication:
   proactive digests/alerts become templated messages (with variables); conversational
   replies stay free-form within the 24-hour window. Code change is trivial (swap the
   sender number) — this is a go-to-market gate, not an engineering one.
2. **Self-serve WhatsApp-first onboarding** (§5.1): CSV-over-WhatsApp first (no auth), then
   Google Sheets OAuth + the one-page connect link and the data-confirmation step.
3. POS integrations (Loyverse, Square, Vend).
4. Multi-language (Swahili, Pidgin, French) — the narrator is already isolated for this.
5. Reorder automation: draft purchase orders, supplier reminders.
6. Demand forecasting & promo recommendations.
7. Multi-tenant ops: retailer registry in a DB (replacing `retailers.yaml`), billing, and an
   **internal** admin view for the operator (not a retailer-facing dashboard — the
   no-dashboard promise is to the retailer, not to ops).
