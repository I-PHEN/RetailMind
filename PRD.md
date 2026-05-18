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
3. **Connect data — a ladder of methods** (the data-source connector ladder, sequenced in
   §9). RetailMind asks how they track sales and routes accordingly:
   - **Spreadsheet file in chat:** they attach a CSV/Excel **inside WhatsApp** → ingested.
     Zero external auth; primary self-serve path.
   - **Google Sheets (OAuth):** one secure link → Google sign-in → pick the sheet. (OAuth,
     *not* share-with-service-account — non-technical owners won't do the latter.)
   - **POS connect:** one OAuth/token link to their POS (first: **Loyverse**) → sales sync
     automatically, no files at all.
   - **Photo of the paper ledger / voice note:** they snap their sales book or say what they
     sold → vision/voice model → structured sales, with a confirm step. *(The big unlock —
     most micro-retailers are paper-based. Roadmap, see §9.)*
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

Strictly sequenced: once the **basic version** (this hackathon MVP — proactive intelligent
WhatsApp analyst on a connected sheet) is solid, work proceeds in this order. Each phase
unblocks the next.

### Phase A — Make it a product, not a demo (no manual onboarding)

**A1. Production WhatsApp Business number.** *The hard gate for any real user.* The Twilio
sandbox `join <code>` step makes self-serve impossible. Needs a Meta Business account,
business verification (~2–10 business days of Meta review — calendar time, not build time,
runs in parallel), display-name approval, and **pre-approved templates** for
business-initiated messages. Design implication: proactive digests/alerts become templated
messages (variables); conversational replies stay free-form inside the 24h window. Code
change is trivial (swap sender) — a go-to-market gate, not engineering.

**A2. DB-backed multi-tenant + conversational onboarding.** Replace `config/retailers.yaml`
with a datastore. **The WhatsApp phone number IS the account** — no passwords, no signup
screen, no dashboard. A conversational onboarding agent provisions a new tenant automatically
when a number completes setup. This is what removes the founder from the loop.

### Phase B — The data-source connector ladder (how retailers connect their data)

Built in this order; each is one new connector behind the existing canonical-schema layer
(`app/schema.py` + `app/connectors/`), so the engine/AI never change:

**B1. Spreadsheet file in chat** — retailer sends a CSV/Excel into WhatsApp; ingested with
zero external auth. Lowest-friction self-serve path; ship first.

**B2. Google Sheets via OAuth** — one "Connect your Google Sheet" link, Google sign-in, pick
the sheet. Replaces the MVP's manual service-account sharing. Live-updating data.

**B3. POS integration — Loyverse (the one POS for v1).** Rationale: Loyverse POS is **free,
the most widely used POS among small African retailers, and has an open REST API + OAuth +
webhooks**. One OAuth connect → automatic sales sync, no files ever. Deliberately *one* POS
done well; Square / Vend / others come later only after Loyverse proves the pattern.

**B4. Photo of the paper ledger** *(the acquisition moat).* Most micro-retailers track sales
on paper. Retailer snaps their sales book → vision model → structured sales → "here's what I
read, correct me?" confirm step. This is the differentiator no dashboard competitor matches.

**B5. Voice-note logging** — *"today I sold 12 bags rice, 3 cooking oil"* → transcription →
structured entry. Many owners prefer speaking; pairs naturally with B4.

### Phase C — Richer communication

**C1. Visual replies (image output).** RetailMind sends **images, not just text**: a 7-day
revenue trend, product-mix, or stockout-runway chart, plus the paper-ledger confirm preview.
Critical constraint — consistent with the trust pillar: charts are **rendered
deterministically by the engine from real numbers (server-side PNG) and sent via WhatsApp
media; the LLM never draws or invents a chart.** Sent as a Twilio media message with a short
caption. Big perceived-intelligence boost for low marginal effort.

**C2. Multi-language & code-switching** (Swahili, Pidgin, Hausa, French, Twi). The narrator
is already isolated, so this is mostly prompt/locale work.

### Phase D — From analyst to autonomous operator

**D1. Reorder automation** — drafts the purchase order and (with one-tap approval) messages
the supplier on WhatsApp on the owner's behalf; tracks delivery.

**D2. Demand forecasting & promo/pricing recommendations** — seasonality, paydays, holidays,
dead-stock clearance suggestions.

### Phase E — Venture-scale

**E1. Data → embedded credit.** With consent, the clean sales history becomes a credit
signal for shops invisible to banks → unlock inventory financing via partner lenders. The
"engine computes, AI only narrates" rule is what makes this auditable and fundable. Take-rate
on financing is the primary business model.

**E2. Network effects** — anonymized benchmarking ("your rice margin is 8% below similar
nearby shops"), aggregated demand → group-buying / better wholesale pricing (two-sided
marketplace), multi-shop portfolio view (still entirely in WhatsApp).

### Ops (continuous, not a blocker)

Billing and an **internal** operator admin view — *not* a retailer-facing dashboard; the
no-dashboard promise is to the retailer, not to ops.
