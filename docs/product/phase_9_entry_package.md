# Phase 9 — Market Validation: Entry Package

**Document type:** Phase Entry Planning  
**Status:** APPROVED — Phase 9 gate open pending final governance confirmation  
**Prepared:** 2026-07-09  
**Basis:** Phase 8 GO decision and commercialization decisions (ADR: `docs/architecture/adr_phase_8_commercialization_positioning.md`)

---

## Purpose

This document defines the frameworks, templates, and process guidance required to execute Phase 9 Market Validation through founder-led customer engagements.

Phase 9 objective (from product constitution): Validate product-market fit through real customer engagements.

Phase 9 success criteria:
- Market demand validated
- Pricing validated
- Product positioning validated
- Business assumptions validated through evidence

This document is planning guidance only. No customer outreach, no platform feature changes, and no roadmap modifications are authorized by this document.

---

## 1. Founder-Led Outreach Framework

### 1.1 Target Persona Priority

Based on the Phase 8 assessment, outreach should prioritize in this order:

**Tier 1 — Highest immediate comprehension:**
- VP Engineering or CTO at a B2B SaaS company preparing a significant release (major version, new market, enterprise launch)
- Platform Engineering Lead at a company with defined pre-release quality gates
- Release Engineering Manager at a company with recent release-related incidents

**Tier 2 — Strong fit, higher education burden:**
- Head of API Platform at a company expanding their API surface to external partners or enterprise customers
- Engineering Director at a company subject to compliance or SLA commitments for their API layer

**Tier 3 — Longer sales cycle:**
- General Engineering Manager without a current release incident context
- QA Lead (will require independence framing to distinguish from internal QA)

### 1.2 Outreach Trigger Conditions

Prioritize outreach to contacts where at least one of the following is true:

- The company recently experienced a production incident attributable to a release
- The company is preparing a significant external launch (enterprise customer, new market, major version)
- The company has publicly discussed API reliability challenges (engineering blog, conference talk, job posting referencing reliability)
- The contact has personally written or spoken about the challenge of release confidence

### 1.3 Opening Message Framework

**Do not lead with the product name or category.**

Lead with the problem and the analogy:

> Most engineering teams have good automated test suites and monitoring in place. But automated tests verify functional correctness — they don't tell you how the API actually behaves under realistic conditions before you release. And monitoring tells you after a customer already experienced the failure.
>
> We run independent operational audits of API reliability before high-stakes releases — like commissioning an external pen test, but focused on reliability evidence rather than security vulnerabilities. The output is a Release Confidence Report: evidence-backed, traceable, produced by a party outside your development process.
>
> I'd like to understand whether this is a problem you're currently solving, and how.

### 1.4 Outreach Channels

Recommended initial channels for founder-led Phase 9:

1. Direct LinkedIn or email to personal connections with engineering leadership roles
2. Second-degree introductions through existing network
3. Engineering communities where release quality is actively discussed
4. Conference follow-up (after engineering leadership conference talks)

Do not invest in paid acquisition channels in Phase 9. The goal is learning, not scale. Every Phase 9 conversation is a discovery interview as much as a sales conversation.

---

## 2. Discovery Interview Framework

### 2.1 Interview Goals

Each Phase 9 discovery conversation should produce answers to:

1. How does this organization currently make the release confidence decision?
2. What evidence do they rely on before releasing?
3. Who owns the decision? (individual, committee, process)
4. Have they experienced a failure that could have been prevented by better pre-release evidence?
5. Do they distinguish between internal testing and independent external verification?
6. How do they currently think about API reliability vs. API functionality?
7. What would need to be true for them to commission an independent reliability audit?
8. What objections do they immediately raise?

### 2.2 Interview Structure (60 minutes)

| Time | Section |
|---|---|
| 0–5 min | Context setting: their role, team structure, release cadence |
| 5–15 min | Current release quality process: what gates exist, what evidence is used |
| 15–25 min | Release incident history: has a release caused a reliability failure? what happened? |
| 25–35 min | RCP positioning introduction: present the analogy, observe comprehension |
| 35–45 min | Objection surfacing: actively invite objections, probe "what would make this not valuable" |
| 45–55 min | Pricing and buying motion: what would the decision process look like, who approves, what budget category |
| 55–60 min | Next steps and referrals |

### 2.3 Critical Questions

Ask these explicitly in every interview:

- "When I describe this as an independent audit of API reliability before a release, what's your first instinct about how this is different from your current monitoring setup?"
- "If I said we do this pre-release rather than post-release, does that change how you think about it?"
- "Who in your organization would be the primary stakeholder for a report like this?"
- "What would a positive outcome from this audit look like for you personally?"

### 2.4 Interview Documentation

After each interview, document:

1. Company profile (size, industry, tech stack if known, release cadence)
2. Current release quality process (what they do today)
3. Comprehension score: did they understand the positioning without extensive explanation? (1–5)
4. Key objections raised and how they responded to addressing them
5. Buying motion assessment: who decides, what budget, what timeline
6. Verbatim phrases they used to describe the problem or value
7. Referral potential: would they refer another contact?
8. Pilot interest: did they express interest in a pilot audit?

---

## 3. Pilot Audit Engagement Workflow

### 3.1 Pilot Audit Purpose

A pilot audit is the primary Phase 9 conversion event. It converts a discovery conversation into a reference customer.

A pilot audit should:
- Produce a complete Release Confidence Report with Platform Integrity Certificate
- Demonstrate that the methodology is sound and the evidence is defensible
- Generate a testimonial and referral opportunity
- Provide pricing validation data

### 3.2 Pilot Audit Selection Criteria

Approve a pilot audit engagement when:

- The contact has a specific upcoming release or API surface they want assessed
- The engagement can be scoped to 1 application, up to 10 endpoints, 48-hour observation
- The contact has authority to approve the engagement or can identify the approver
- The API is accessible for external observation (production-realistic environment)
- The expected report date is confirmed and meaningful to the buyer's release timeline

Do not start a pilot audit against a deprecated, decommissioned, or internal-only API endpoint.

### 3.3 Pilot Audit Scoping

The standard pilot audit scope (from product constitution):

| Parameter | Value |
|---|---|
| Application scope | 1 application or service |
| Endpoint scope | Up to 10 critical API endpoints |
| Observation duration | 48 hours continuous |
| Output | Release Confidence Report + Platform Integrity Certificate |

For pilot engagements, consider pricing at 50–70% of full commercial rate to reduce adoption friction. Document the rationale and use pricing data to inform full commercial pricing in Phase 9.3.

### 3.4 Pilot Engagement Kickoff

Before starting a pilot audit:

1. Confirm endpoint list (names, URLs, expected behavior)
2. Confirm production-realistic environment access
3. Confirm expected report delivery date
4. Document the buyer's intended use of the report (release decision, stakeholder communication, compliance documentation)
5. Confirm point of contact for report delivery

### 3.5 Report Delivery

Deliver the Release Confidence Report in a 30-minute review session, not as a raw PDF drop:

1. Walk through the executive summary and overall Release Confidence Assessment
2. Review each endpoint finding
3. Walk through the Audit Platform Integrity Certificate
4. Solicit immediate reactions and objections
5. Document verbatim feedback
6. Ask explicitly: "Is this evidence defensible enough to change how you communicate release confidence to your stakeholders?"

---

## 4. Pricing Validation Approach

### 4.1 Phase 9 Pricing Goal

Phase 9 does not establish final commercial pricing. It validates the pricing range and buying motion assumptions made in Phase 8.

Specific questions to answer:

1. What budget category does this fall into? (Engineering tooling? Professional services? Consulting? Compliance?)
2. Who approves it? (Engineering leader, finance, procurement?)
3. What is the natural price anchor the buyer uses to evaluate the price? (Hourly consulting? Tool subscription? Security audit?)
4. What price triggers immediate "too expensive" vs. "this seems fair" vs. "this is surprisingly affordable"?

### 4.2 Pricing Conversation Approach

Do not name a price before understanding the buyer's budget context. Instead:

1. Ask: "If you were going to commission a security penetration test of this scope, what would you expect to budget for that?"
2. Ask: "How does your team currently budget for external validation or professional services vs. internal tooling?"
3. After establishing context, present pricing as: "Our standard engagement is priced at [X]. This covers [scope]. How does that compare to what you'd budgeted for something like this?"
4. Document the reaction, not just the response.

### 4.3 Pricing Documentation

After each pricing conversation, document:

- The price presented
- The buyer's immediate reaction (pause, negotiation, acceptance, dismissal)
- The budget category they placed it in
- The price anchor they used for comparison
- Whether they required procurement approval and at what threshold

---

## 5. Customer Interview Template

Use this template to document each Phase 9 customer conversation.

```
## Interview Record — [Date] — [Company/Contact Pseudonym]

### Context
- Company: [size, industry]
- Contact role: [title, tenure]
- Release cadence: [frequency, last major release]
- Known incident history: [yes/no/unknown]

### Current Release Process
[What they do today before releasing]

### Positioning Comprehension
- First response to "independent pre-release API reliability audit": 
- Did timing distinction (pre-release) land immediately: [yes/no/required explanation]
- Objections raised (verbatim if possible):
- Comprehension score (1–5): 

### Key Quotes
[Verbatim language they used to describe the problem or value]

### Objections Raised
1. [Objection] → [How they responded to the addressing message]
2. ...

### Buying Motion
- Decision maker: [self / team / committee]
- Budget category: [tooling / services / compliance / other]
- Approval threshold: [$ amount requiring procurement]
- Timeline: [urgency]

### Pricing Reaction
- Price presented: 
- Reaction: 
- Anchor comparison used: 

### Pilot Interest
- Expressed interest in pilot: [yes/no/maybe]
- API/application identified: [yes/no]
- Timeline: 

### Referral Potential
- Would refer: [yes/no/maybe]
- Referred contacts: [names/roles if provided]

### Next Steps
[Agreed actions and timeline]
```

---

## 6. Testimonial Capture Process

### 6.1 When to Request

Request a testimonial after report delivery, specifically after the 30-minute review session, when the buyer has had the opportunity to react to the evidence. Do not request before delivery.

### 6.2 Testimonial Request Framing

> "We're building our initial reference set. Would you be willing to share a brief statement about what you found most valuable about the audit — specifically the evidence quality and how it compared to what your internal process produces? We'd want to attribute it to your role and company."

If they hesitate on company attribution, offer role-only attribution: "VP Engineering, B2B SaaS."

### 6.3 Testimonial Content Goals

A useful Phase 9 testimonial addresses at least one of:

- The independence value: "Unlike our internal tests, this came from outside our process."
- The timing value: "We had this before the release, not after the incident."
- The evidence quality: "Every finding traced back to actual observations."
- The decision-enablement: "This gave us confidence to release / confidence to delay."

### 6.4 Testimonial Documentation

Store each testimonial in `docs/product/phase_9_testimonials.md` with:
- Verbatim text
- Attribution (role + company category)
- Date of collection
- Whether it may be used publicly

---

## 7. Roadmap Feedback Process

### 7.1 Purpose

Phase 9 conversations will surface requests for features or capabilities that RCP does not currently have. The roadmap feedback process ensures these requests are captured without immediately becoming commitments.

### 7.2 Collection

During each discovery or pilot conversation, document any request for functionality beyond the current platform scope. Capture:

- What was requested (verbatim if possible)
- Why the buyer wants it (the underlying need, not just the feature)
- Whether the absence of this feature is a blocker to adoption or a nice-to-have

### 7.3 Classification

Classify each request against the existing roadmap:

| Classification | Action |
|---|---|
| Already planned (Phase 10+) | Confirm the roadmap direction, do not over-commit to timeline |
| Not planned, high frequency | Log for Phase 8 retrospective and roadmap review after Phase 9 closes |
| Not planned, single mention | Log and monitor |
| Constitutional conflict | Escalate immediately — do not promise anything that conflicts with product identity |

### 7.4 Non-Negotiable Constraints

Do not promise or imply:
- Real-time monitoring capabilities
- CI/CD integration as a primary feature
- AI-generated test synthesis
- Dashboard-first deliverables
- Subscription tooling access (Phase 10 scope)

If a buyer asks for any of these, acknowledge the interest and explain the positioning: "We intentionally focus on the pre-release audit engagement rather than continuous monitoring. That's a deliberate boundary — it's what makes the evidence defensible and the report independent."

---

## Traceability

- Phase 8 Closure Record: `docs/release/phase_8_closure.md`
- Commercialization ADR: `docs/architecture/adr_phase_8_commercialization_positioning.md`
- Objection Analysis: `docs/research/phase_8_objection_analysis.md`
- Messaging Framework: `docs/product/phase_8_messaging_framework.md`
- Product Constitution: `RCP_Product_Strategy.md`
