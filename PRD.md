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
- Production WhatsApp sender (verified Meta Business / paid Twilio number) — MVP uses Twilio sandbox.
- Self-serve onboarding UI (MVP configures retailers via YAML).
- Direct POS API integrations (Square, Loyverse, etc.).
- Inventory write-back / purchase-order generation.
- Multi-language localization (Swahili, Pidgin, French) — designed for, not shipped in MVP.
- Forecasting / ML demand prediction.
- Billing & multi-tenant auth.

## 5. User experience

1. **Onboarding (operator-assisted):** retailer's sheet/CSV + WhatsApp number added to config;
   they join the Twilio sandbox once (`join <code>`).
2. **Morning digest:** "Good morning Amina ☀️ Yesterday you did KES 18,400 (up 12% on last
   Tuesday). Top seller: cooking oil. Heads up — sugar will run out in ~3 days at this pace."
3. **Proactive alert:** sales drop / spike / imminent stockout detected → immediate WhatsApp.
4. **Ask anything:** "how were sales last week vs the week before?" → grounded answer in seconds.

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

1. Self-serve WhatsApp onboarding ("send me your sheet link").
2. Production WhatsApp sender + multi-language (Swahili, Pidgin, French).
3. POS integrations (Loyverse, Square, Vend).
4. Reorder automation: draft purchase orders, supplier reminders.
5. Demand forecasting & promo recommendations.
6. Multi-tenant SaaS: auth, billing, dashboard (optional companion to WhatsApp).
