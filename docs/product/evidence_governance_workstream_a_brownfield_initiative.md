# Evidence Governance Workstream A — Governance Compliance Corrections

## Brownfield Initiative Document

---

## 1. Title

Evidence Governance Workstream A — Governance Compliance Corrections (A1: Evidence Retention Enforcement, A2: Report Issuance Governance Enforcement)

---

## 2. Objective

Correct two confirmed conflicts between RCP's already-implemented Phase 1–7 behavior and the approved Evidence Governance Baseline v1.0 / Product Constitution:

1. **A1 — Evidence Retention Enforcement.** Replace unconditional, indefinite evidence retention with a technically enforced mechanism ensuring evidence does not outlive its authorized governance purpose.
2. **A2 — Report Issuance Governance Enforcement.** Replace operator-discipline-only sequencing between Phase 6 report completion and Phase 7 platform integrity certification with an architectural enforcement point that a report cannot be issued unless certification has succeeded or all material limitations have been explicitly disclosed.

Both corrections bring existing, already-locked implementation into compliance with governance defaults and constitutional rules that already exist today. Neither introduces new product scope, new customer-facing capability, or a new roadmap phase.

---

## 3. Background

This initiative originates from two sequential governance activities, both already completed and approved prior to this planning work:

1. **SDLC Verification Gate — Evidence Governance Baseline v1.0.** Two independent SDLC review passes (Claude and OpenCode) each reviewed the Product Guardian-locked Evidence Governance Baseline v1.0 package against RCP's existing architecture, ADRs, technical designs, and infrastructure configuration. Both passes returned **PASS WITH OBSERVATIONS** and, independently and without coordination, converged on the same two live findings via direct infrastructure inspection:
   - No S3 `LifecycleConfiguration` and no DynamoDB TTL attribute exist anywhere in `infra/` — every audit's raw evidence, aggregates, reports, and certificates are retained indefinitely by default, the opposite of the governance model's "evidence shall not outlive its authorized governance purpose" default.
   - Phase 6 report completion (`ReportMetadata.status = COMPLETE`) is not architecturally gated on Phase 7 certification, which is operator-invoked and explicitly non-blocking by design (`docs/architecture/adr_phase7_certification_independence.md`, Decision 5). This currently relies entirely on operator discipline to honor the Product Constitution's own non-negotiable issuance rule.
   - Reference: `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_claude.md`, `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_opencode.md`.

2. **Product Strategy Transition Plan.** Following the SDLC Verification Gate, the Product Guardian approved a Product Strategy Transition Plan that authorizes SDLC planning (not implementation) to begin on the corrections identified above. The Transition Plan designates these two corrections collectively as **Workstream A — Governance Compliance Corrections**, and authorizes Workstream A alone to enter planning at this time. Workstreams B (constitutional clarifications), C (roadmap expansion), D (further technical design of net-new Evidence Governance scope), and E (implementation) remain out of scope until separately authorized.

Both SDLC review passes explicitly ranked these two findings above the larger, net-new Evidence Governance scope (Evidence Package composition, evidence profiles, sufficiency evaluation, customer delivery, authentication) precisely because they are **conflicts with governance defaults in already-shipped behavior**, not absent future capability — and therefore carry live risk independent of whether or when the broader governance baseline is adopted.

---

## 4. Governing Principle (Non-Negotiable)

> **"Governance Before Implementation"**

The approved governance model is authoritative. Existing implementation shall evolve to satisfy governance. Governance shall not be modified to accommodate existing implementation.

This principle governs every decision made under Workstream A. Where A1 or A2 requirements conflict with current implementation convenience, the implementation must change — the governance model is not renegotiated to fit what already exists.

---

## 5. Scope

### A1 — Evidence Retention Enforcement

**Confirmed conflict:** `infra/resources/s3.yml` (`RawResultsBucket`) has `VersioningConfiguration.Status: Enabled` and no `LifecycleConfiguration`. `infra/resources/dynamodb.yml` (`MetadataTable`) defines no TTL attribute. Every version of every S3 object and every DynamoDB record across all phases (raw evidence, aggregates, intelligence, reports, certificates) is retained indefinitely today.

**Objective:** Plan the technical enforcement mechanism — lifecycle enforcement and automated disposal enforcement — ensuring evidence does not outlive its authorized governance purpose.

**Explicitly excluded from A1:** The exact retention duration(s) / custody period value(s). These are a Product Strategy decision ("Default Evidence Custody Period" — SDLC Verification Gate §9 item 6 / §16 item 1), tracked separately and at lower priority than the enforcement mechanism itself. A1 plans the *mechanism* — where a custody-period parameter is consumed, how expiration and disposal are enforced, how legal hold overrides the clock — without inventing or assuming a specific duration value.

### A2 — Report Issuance Governance Enforcement

**Confirmed conflict:** Phase 6 (`ReportMetadata.status = COMPLETE`) completes independently of Phase 7 certification. Phase 7 is operator-invoked via `rcp certify audit` and explicitly non-blocking by design (`docs/architecture/adr_phase7_certification_independence.md`, Decision 5; Alternative 4 — event-driven trigger — was considered and rejected). Nothing today architecturally prevents a completed report from being treated as final/issued before Phase 7 certification completes. This conflicts with the Product Constitution's own non-negotiable rule:

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

**Objective:** Plan an architectural enforcement point — distinct from Phase 6's internal `COMPLETE` status — that a report cannot be issued unless Audit Platform Integrity requirements are satisfied (`CertificationMetadata.terminal_state = CERTIFIED`) or required limitations are explicitly disclosed.

**Non-negotiable constraints carried forward from `adr_phase7_certification_independence.md`:**

- Phase 7 remains a distinct phase that runs strictly after Phase 6 completes and reads only Phase 6 artifacts (never Phase 4/5 directly).
- Phase 7 remains read-only with respect to all prior-phase artifacts; it must never write to `ReportMetadata` or any Phase 6 record.
- Phase 6 must not be made to wait on, or block on, Phase 7 completion as part of its own `COMPLETE` transition.
- Phase 7 remains operator-invoked in MVP; no event-driven trigger is mandated by this workstream.

The exact architectural mechanism for the new issuance enforcement point is Technical Design's responsibility, not this initiative's. This document defines the behavioral requirement and its constraints only.

---

## 6. Explicit Out of Scope

The following are not part of Workstream A and must not be addressed, resolved, or scope-crept into A1/A2 planning. Where a dependency on these items is identified, it must be flagged as a risk/dependency, not resolved:

- Evidence Package composition/generation (Evidence Governance Baseline 2.1 / 2.7)
- Evidence profiles / minimization defaults (2.2)
- Evidence sufficiency evaluation / conclusion narrowing or withholding (2.5)
- Customer/recipient authentication, authorization, or delivery mechanisms (2.8 / 2.9)
- Roadmap phase placement decisions for net-new Evidence Governance scope (Workstream C)
- Terminology reconciliation between "Audit Platform Integrity" and "Audit Process Integrity" (Workstream B2)
- The Assessment-vs-Report artifact-count question (Workstream B1)
- Exact Evidence Custody Period durations (Product Strategy decision, tracked separately, lower priority)
- Any implementation, code change, PR, merge, or deployment

---

## 7. Constitutional Principles Preserved

- **Governance Before Implementation** (quoted in full in Section 4). The controlling principle for this initiative.
- **Trust Before Convenience** — per Evidence Governance Baseline Initiative 2.11 Principle 10. Referenced, not redefined, by this initiative.
- **Product Positioning Preservation** — RCP remains an Independent Pre-Release API Reliability Audit Platform. RCP is not a monitoring platform, a CI/CD utility, a testing framework, or a dashboard-first product. A1 and A2 must not introduce any behavior, artifact, or interface that shifts RCP toward these categories.
- **Incremental Architecture** — only the two authorized corrections (A1, A2) are planned. No speculative scope, no net-new Evidence Governance capability, no anticipatory design for Workstreams B–E.
- **Core Product Philosophy** (`RCP_Product_Strategy.md`) — runner correctness, evidence integrity, deterministic execution, data integrity, audit repeatability, operational safety, customer trust remain the governing priority order for any design decision made under this workstream.
- **Audit Platform Integrity Principles** (`RCP_Product_Strategy.md`) — "Trust in the report depends on trust in the auditor." A2 exists specifically to make this principle architecturally enforced rather than operator-trusted.

---

## 8. Priority

**Highest**, per the approved Product Strategy Transition Plan. Both SDLC review passes independently ranked these two corrections ahead of all other Evidence Governance Baseline work because they represent live conflicts with governance defaults in already-shipped, already-locked behavior — not absent future capability.

---

## 9. Authorization Status

**Authorized now:**
- SDLC planning for A1 and A2: product specification, technical design, architecture review, security review, QA/test strategy, and implementation issue drafting (documentation only).

**NOT authorized:**
- Implementation code changes of any kind.
- Pull request creation.
- Merge to `main`.
- Deployment to any environment.

Implementation may not begin until this planning package receives explicit HITL approval and a separate, explicit authorization to proceed to Workstream A implementation is given. This is consistent with the platform's Human-in-the-Loop Release Gate — QA and planning approval are necessary but not sufficient for implementation or release authorization.

---

## 10. Expected SDLC Deliverables

1. `docs/product/evidence_governance_workstream_a_brownfield_initiative.md` — this document.
2. `docs/product/evidence_governance_workstream_a_product_spec.md` — Product Specification for A1 and A2 (companion document).
3. Technical Design document(s) for A1 and A2, including any ADR(s) required to formalize the enforcement mechanisms and their relationship to `adr_phase7_certification_independence.md` and `adr_sanitization_boundary.md`.
4. Independent Architecture Review and Security Review of the Technical Design, given A1 touches infrastructure/persistence (S3 lifecycle, DynamoDB TTL) and A2 touches API contracts and phase boundaries.
5. QA / Test Strategy mapping every acceptance criterion in the Product Specification to an executable validation plan.
6. Implementation-ready GitHub Issues with sequencing, scoped strictly to A1 and A2, for future authorized implementation. No implementation performed under this deliverable.

---

## 11. Traceability

- SDLC Verification Gate reviews: `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_claude.md`, `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_opencode.md`
- Product Constitution: `RCP_Product_Strategy.md` (Phase 7 — Audit Platform Integrity; Audit Platform Integrity Principles; Evidence Principles)
- ADR — Certification Independence: `docs/architecture/adr_phase7_certification_independence.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 7 → Phase 8 Consumer Contract: `docs/architecture/phase_7_phase8_consumer_contract.md`
- Phase 7 Product Spec (format and terminology reference): `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Infrastructure under review: `infra/resources/s3.yml`, `infra/resources/dynamodb.yml`
- Companion document: `docs/product/evidence_governance_workstream_a_product_spec.md`
