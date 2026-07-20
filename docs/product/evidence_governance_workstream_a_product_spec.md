# Product Specification

# Evidence Governance Workstream A — Governance Compliance Corrections

**Companion document:** `docs/product/evidence_governance_workstream_a_brownfield_initiative.md`
**Status:** Planning only. No implementation, code change, or PR is authorized by this document.

---

## 1. Feature Overview

Workstream A consists of two independent compliance corrections to already-implemented, already-locked RCP behavior:

- **A1 — Evidence Retention Enforcement:** a technically enforced mechanism ensuring evidence stored in the platform's S3 bucket and DynamoDB table does not outlive its authorized governance purpose, replacing today's unconditional indefinite retention.
- **A2 — Report Issuance Governance Enforcement:** an architectural enforcement point ensuring a Release Confidence Report cannot be issued unless Phase 7 Audit Platform Integrity certification has succeeded or all material limitations have been explicitly disclosed, replacing today's operator-discipline-only sequencing.

Both are corrections to existing behavior across already-locked Phase 1–7. Neither is new product scope.

---

## 2. Problem Statement

### A1

`infra/resources/s3.yml` (`RawResultsBucket`) has S3 versioning enabled with no `LifecycleConfiguration`. `infra/resources/dynamodb.yml` (`MetadataTable`) defines no TTL attribute. Confirmed by direct infrastructure inspection in both independent SDLC review passes: every audit's raw execution evidence, Phase 4 aggregates, Phase 5 intelligence, Phase 6 reports, and Phase 7 certificates are retained indefinitely today, across every S3 object version. This is the exact opposite of the Evidence Governance Baseline's default: evidence shall not outlive its authorized governance purpose. If a customer engagement ends, a contractual custody period expires, or a legal deletion obligation arises, RCP has no technical mechanism to honor it today.

### A2

Phase 6 (`ReportMetadata.status = COMPLETE`) completes independently of Phase 7 certification. Phase 7 is operator-invoked via `rcp certify audit` and is explicitly non-blocking by design (`adr_phase7_certification_independence.md`, Decision 5 — an event-driven trigger was proposed as Alternative 4 and rejected for MVP). No architectural control today prevents a `COMPLETE` report from being treated as final or issued to a customer before Phase 7 certification has run, or when certification has failed or been blocked. This directly conflicts with the Product Constitution's own non-negotiable rule:

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

Today this rule is honored entirely through operator discipline, not through any check the system enforces.

---

## 3. User Persona / Target User

- **Platform Engineer / Operator:** runs audits, generates reports (`rcp report generate`), invokes certification (`rcp certify audit`), and is currently the sole enforcement mechanism for both retention discipline and issuance sequencing. Workstream A shifts enforcement from this persona's memory to the platform.
- **Audit Customer (Indirect):** the beneficiary of both corrections. Custody of their evidence is bounded and disposed of on schedule (A1); any report they receive is guaranteed to have been certified or to carry explicit disclosure of why it was not (A2). Does not interact with either mechanism directly.
- **Compliance / Governance Reviewer (Indirect):** relies on both corrections to independently verify, after the fact, that RCP's technical behavior matches its stated governance defaults and constitutional rules.

No new customer-facing or self-service persona is introduced. No new external access surface is introduced.

---

## 4. User Stories

- As an Operator, I want evidence in the S3 bucket and DynamoDB table to be automatically disposed of once its custody period has elapsed, so that RCP does not retain evidence indefinitely by default and I am not solely responsible for manual deletion.
- As an Operator, I want the ability to place a legal hold on a specific audit's evidence, so that a pending legal or contractual obligation can override the automatic disposal clock without requiring me to disable retention enforcement platform-wide.
- As an Operator, I want the platform to prevent a report from being issued when Phase 7 certification has not succeeded and no disclosure has been recorded, so that I cannot accidentally deliver an uncertified or failed-certification report to a customer.
- As an Operator, I want to be able to record an explicit disclosure of certification limitations and still proceed with issuance, so that legitimate `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` engagements can still be delivered with full transparency, consistent with the Product Constitution's disclosure clause.
- As a Compliance Reviewer, I want a durable, evidence-backed record of every disposal action and every issuance decision, so that RCP's governance claims are independently verifiable, not merely asserted.

---

## 5. Goals / Success Criteria

Workstream A planning is successful when:

1. A1's enforcement mechanism (lifecycle + automated disposal) is fully specified at the behavioral level, including legal hold override behavior, without assuming or inventing a specific custody-period duration.
2. A2's enforcement point is fully specified at the behavioral level as a concept distinct from `ReportMetadata.status = COMPLETE`, without prescribing the specific architectural mechanism (that is Technical Design's responsibility).
3. Every acceptance criterion in Section 8 is independently testable and traceable to a concrete platform state (S3 object, DynamoDB record, or CLI command outcome).
4. No non-negotiable invariant in `adr_phase7_certification_independence.md` is violated by any A2 requirement.
5. Every dependency on out-of-scope Workstream B/C/D/E decisions is explicitly flagged in Section 13, not silently assumed.

---

## 6. Feature Scope

### 6.1 In Scope

**A1:**
- Behavioral requirement that every S3 object under the raw-results bucket and every DynamoDB record under the metadata table is subject to an enforced custody period after which it is automatically disposed of, unless an active legal hold applies.
- Behavioral requirement that legal hold, when active for a given audit identity, suspends automatic disposal for that audit's evidence until explicitly released.
- Behavioral requirement that a custody-period parameter is treated as an explicit, externally supplied configuration input to the enforcement mechanism, not a hardcoded or assumed value.
- Behavioral requirement that disposal actions are observable/traceable (a durable record that disposal occurred, for what identity, and when) — consistent with the Evidence Principles' traceability requirement, so that disposal itself does not become an unaccountable action.
- Coverage of all evidence classes currently persisted indefinitely: raw execution evidence (Phase 1/2), aggregates (Phase 4), intelligence (Phase 5), reports (Phase 6), certificates (Phase 7) — i.e., all objects in `RawResultsBucket` and all records in `MetadataTable`, regardless of which phase wrote them.
- Coverage of S3 object versions, not just current versions, given `VersioningConfiguration.Status: Enabled` on `RawResultsBucket` today.

**A2:**
- Behavioral requirement that a new concept — "issuance" — exists, distinct from `ReportMetadata.status = COMPLETE`, that gates whether report content may be treated as final/delivered/customer-facing.
- Behavioral requirement that issuance requires `CertificationMetadata.terminal_state = CERTIFIED` for the same audit identity tuple, **or** an explicit, recorded disclosure covering the reasons certification did not succeed.
- Behavioral requirement that "no certification attempted" (no `CertificationMetadata` record exists at all) is treated identically to a non-`CERTIFIED` state for issuance-gating purposes — it must not be silently treated as passing.
- Behavioral requirement that the disclosure record, when used, is structured and evidence-linked (references `certificate_id`, `terminal_state`, and `disclosed_failures`), not a free-text override with no traceability.
- Behavioral requirement that enforcement respects all non-negotiable invariants in `adr_phase7_certification_independence.md`, including: Phase 6 does not wait on Phase 7 to reach `COMPLETE`; Phase 7 never writes to `ReportMetadata`; Phase 7 remains operator-invoked (no event-driven trigger introduced by this workstream).

### 6.2 Out of Scope

**A1:**
- The exact custody-period duration(s) per evidence class. This is a Product Strategy decision ("Default Evidence Custody Period"), tracked separately, lower priority than the enforcement mechanism.
- Evidence profiles or minimization-at-persistence-time (Evidence Governance Baseline 2.2).
- Backup, replica, or archive storage outside `RawResultsBucket` and `MetadataTable` (none currently exist in `infra/`; if introduced later, they are out of scope for this correction).
- Legal hold *authorization* policy (who may place/release a hold, under what business process) — only the technical override behavior is in scope; the governance policy around it is a Workstream B/C concern.

**A2:**
- The specific architectural mechanism used to implement the issuance gate (new record type, new CLI check, new service layer, etc.) — Technical Design's responsibility.
- Building an actual customer-facing delivery/export feature. No such feature exists today; A2 defines the gating behavior that must apply to whatever operation(s) currently or in the future produce customer-facing report content.
- Terminology reconciliation between "Audit Platform Integrity" and "Audit Process Integrity" (Workstream B2).
- Any change to Phase 7's eight certification domains, terminal-state determination logic, or certificate schema (`cert_v1`). A2 consumes `CertificationMetadata.terminal_state` as-is; it does not modify how that value is produced.
- Any event-driven or automated triggering of Phase 7 certification itself.

### 6.3 Future Considerations (Not Part of This Workstream)

- A formal Evidence Package artifact incorporating disposal and issuance metadata (Evidence Governance Baseline 2.1/2.7).
- A customer-facing delivery mechanism that would consume the A2 issuance gate directly (Workstream E, contingent on a customer authentication/authorization primitive that does not yet exist).
- Extending the A1 disposal mechanism to a future customer authentication/authorization boundary once one exists.

---

## 7. Functional Requirements

### A1 — Evidence Retention Enforcement

**FR-A1-1.** The platform shall enforce an expiration point for every object stored in `RawResultsBucket`, after which the object is automatically removed, unless a legal hold is active for the owning audit identity.

**FR-A1-2.** The platform shall enforce an expiration point for every record stored in `MetadataTable`, after which the record is automatically removed, unless a legal hold is active for the owning audit identity.

**FR-A1-3.** The expiration point for a given piece of evidence shall be derived from a custody-period parameter supplied as external configuration, not hardcoded within the enforcement mechanism.

**FR-A1-4.** The platform shall support placing and releasing a legal hold scoped to an audit identity (at minimum `client_id` + `audit_id`), and evidence under an active legal hold shall not be disposed of regardless of elapsed custody period.

**FR-A1-5.** Every automatic disposal action shall produce a durable, queryable record of what was disposed, for which audit identity, and when.

**FR-A1-6.** The enforcement mechanism shall apply uniformly to evidence written by any phase (Phase 1 through Phase 7) that persists to `RawResultsBucket` or `MetadataTable`, without requiring per-phase opt-in.

### A2 — Report Issuance Governance Enforcement

**FR-A2-1.** The platform shall define an "issuance" checkpoint, distinct from `ReportMetadata.status = COMPLETE`, at which the certification-gating requirement is evaluated.

**FR-A2-2.** At the issuance checkpoint, the platform shall require either `CertificationMetadata.terminal_state = CERTIFIED` for the exact audit identity tuple, or a recorded explicit disclosure covering the non-`CERTIFIED` condition, before report content may be treated as issued.

**FR-A2-3.** The absence of any `CertificationMetadata` record for the audit identity tuple shall be treated as a non-`CERTIFIED` condition requiring disclosure — never as an implicit pass.

**FR-A2-4.** A recorded disclosure shall reference the governing `certificate_id`, `terminal_state`, and the full `disclosed_failures` list from the `CertificationMetadata`/certificate artifact it discloses against.

**FR-A2-5.** The issuance checkpoint shall evaluate against the current/latest `CertificationMetadata` record for the audit identity tuple. If a force re-certification (`--force`) has produced a new `certificate_id`, the checkpoint shall evaluate against that new record, not a stale prior one.

**FR-A2-6.** The issuance checkpoint mechanism shall not require Phase 6 to read Phase 7 records as a precondition of reaching `ReportMetadata.status = COMPLETE`, and shall not require Phase 7 to write to any Phase 6 record.

**FR-A2-7.** The issuance checkpoint shall not introduce an event-driven trigger for Phase 7 certification. Phase 7 remains operator-invoked in MVP.

---

## 8. Acceptance Criteria

All criteria follow Given / When / Then and map directly to QA validation.

### A1 — Evidence Retention Enforcement

**AC-A1-1**
Given an S3 object in `RawResultsBucket` whose configured custody period has elapsed,
When no legal hold is recorded for its owning audit identity,
Then the object must be automatically expired/removed by an enforced mechanism, without requiring manual operator action.

**AC-A1-2**
Given a DynamoDB record in `MetadataTable` whose configured custody period has elapsed,
When no legal hold is recorded for its owning audit identity,
Then the record must be automatically removed by an enforced mechanism, without requiring manual operator action.

**AC-A1-3**
Given an audit identity with an active legal hold,
When that audit's evidence custody period elapses,
Then no automatic disposal action for that audit's evidence in `RawResultsBucket` or `MetadataTable` may occur while the hold remains active.

**AC-A1-4**
Given a legal hold on an audit identity is released,
When the custody period for that audit's evidence has already elapsed at the time of release,
Then the evidence must become eligible for disposal under the enforced mechanism (the enforcement must resume, not silently skip the now-expired evidence).

**AC-A1-5**
Given the custody-period parameter has not yet been supplied by Product Strategy,
When Workstream A Technical Design is authored,
Then the design must treat the custody period as an explicit external configuration input and must not hardcode, default, or assume a specific duration value.

**AC-A1-6**
Given an automatic disposal action occurs for any object or record,
When the disposal is inspected after the fact,
Then a durable record must exist evidencing the disposed identity, the evidence class, and the disposal timestamp.

**AC-A1-7**
Given an S3 object in `RawResultsBucket` has multiple versions (versioning is enabled on the bucket today),
When the enforced expiration mechanism is designed,
Then it must account for expiration of noncurrent versions, not only the current version, to avoid indefinite retention via version history.

**AC-A1-8**
Given evidence written by any phase (Phase 1 through Phase 7) prior to Workstream A implementation,
When the enforcement mechanism is designed,
Then the design must explicitly state whether and how this pre-existing backlog is brought under custody-period enforcement, rather than leaving backlog handling undefined.

### A2 — Report Issuance Governance Enforcement

**AC-A2-1**
Given `ReportMetadata.status = COMPLETE` for an audit identity tuple and no `CertificationMetadata` record exists for that tuple,
When an issuance action is attempted,
Then issuance must be blocked unless an explicit disclosure recording "certification not performed" has been recorded for that tuple.

**AC-A2-2**
Given `ReportMetadata.status = COMPLETE` and `CertificationMetadata.terminal_state = CERTIFIED` for the same audit identity tuple,
When an issuance action is attempted,
Then issuance must proceed without requiring any additional disclosure.

**AC-A2-3**
Given `CertificationMetadata.terminal_state = CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` for the audit identity tuple,
When an issuance action is attempted without a recorded explicit disclosure covering the `disclosed_failures` for that certificate,
Then issuance must be blocked and must fail with a structured, distinguishable error.

**AC-A2-4**
Given `CertificationMetadata.terminal_state = CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED`,
When an operator has recorded an explicit disclosure referencing the governing `certificate_id`, `terminal_state`, and full `disclosed_failures` list,
Then issuance may proceed, and the disclosure record must be retrievable alongside the issued report content.

**AC-A2-5**
Given a force re-certification (`rcp certify audit --force`) produces a new `certificate_id` for an audit identity tuple that was previously `CERTIFIED`,
When issuance is evaluated after the force re-certification,
Then the issuance checkpoint must evaluate against the new `CertificationMetadata` record, and the prior certificate artifact must remain preserved at its original S3 key, unmodified, per existing ADR invariants.

**AC-A2-6**
Given the issuance checkpoint design,
When it is reviewed against `adr_phase7_certification_independence.md`,
Then it must not require `ReportMetadata.status` to transition to `COMPLETE` conditionally on Phase 7 state, must not require Phase 7 to write to `ReportMetadata` or any Phase 6 record, and must not introduce an event-driven Phase 7 trigger.

**AC-A2-7**
Given a Phase 6 report is force-regenerated (`--force`, new `report_job_id`) after a prior `CERTIFIED` certification existed for an earlier `report_job_id` under the same identity tuple,
When issuance is evaluated for the newly regenerated report,
Then the design must explicitly state whether the prior certification still governs issuance or whether re-certification against the new report artifact is required — this must not be left ambiguous.

---

## 9. Edge Cases

### A1

- Legal hold placed on an audit identity after some of its evidence has already been disposed under an earlier-elapsed custody period — the hold cannot retroactively restore disposed evidence; this limitation must be explicit, not discovered operationally.
- Custody period elapsing for a Phase 4 aggregate record while its corresponding Phase 6 report or Phase 7 certificate is still within its own (potentially independently computed) custody period — cross-phase evidence with different effective ages under the same audit identity.
- An audit whose Phase 6 report was force-regenerated multiple times, each producing new S3 artifacts at new keys per the existing "prior artifacts preserved" pattern (`phase_6_report_schema.md` §7) — the disposal mechanism must correctly enumerate and expire all historical artifact versions, not only the latest.
- Existing indefinitely-retained evidence backlog: all evidence persisted before Workstream A implementation currently has no defined custody-period start event. Migration/backfill strategy for this backlog is not resolved by this specification and must be explicitly addressed in Technical Design.
- DynamoDB TTL deletion is a best-effort, typically-within-48-hours AWS mechanism, not instantaneous — the enforcement mechanism's disposal-record semantics must account for this eventual-consistency window rather than assuming synchronous deletion.

### A2

- An audit for which Phase 7 certification was never invoked at all (no operator action taken) — must be treated as an undisclosed, non-`CERTIFIED` state (see AC-A2-1), not silently ignored.
- Concurrent issuance attempts while a `--force` re-certification is in progress for the same audit identity tuple — the design must define which `CertificationMetadata` record is authoritative during the transition window.
- A disclosed-limitation record that only partially covers the `disclosed_failures` list (e.g., discloses one failed domain but not all) — must not satisfy the disclosure requirement; disclosure must be complete.
- An audit certified `CERTIFIED` once, whose Phase 6 report is later force-regenerated — addressed explicitly in AC-A2-7; the design must not leave this silently unresolved, since a stale `CERTIFIED` state evaluated against new report content would be a lineage-integrity violation of the type Phase 7 itself exists to prevent.

---

## 10. Constraints

### A1

- Must not violate the Evidence Principle that raw evidence is the source of truth *while it remains within its authorized custody period* — disposal must only ever act on evidence whose custody period has genuinely elapsed and which is not under legal hold.
- Must be a technical, automated control — not a scheduled operator task, script run manually, or documentation-only policy. This directly closes the gap both SDLC review passes identified as "operator-discipline-only."
- Must not silently and permanently lose the traceability required to explain a completed disposal after the fact (AC-A1-6).
- Must not assume a single, uniform custody period across all evidence classes unless Product Strategy explicitly confirms that assumption; the mechanism should be designed to accept a custody-period parameter, not a specific value.

### A2

- Must not violate any of the six non-negotiable invariants in `adr_phase7_certification_independence.md`, reproduced here for direct reference:
  1. Phase 7 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion or Phase 6 report section.
  2. Phase 7 shall never read Phase 5 intelligence artifacts directly.
  3. Phase 7 shall never read Phase 4 aggregation artifacts directly.
  4. `ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 certification; no alternative signal may substitute.
  5. Phase 7 shall never mutate any Phase 6 report artifact, `ReportMetadata` record, or `ReportJob` record.
  6. Reporting owns presentation. Phase 7 owns platform integrity certification.
- Must not make Phase 6's `COMPLETE` transition conditional on Phase 7 state — Phase 6 completion semantics are unchanged by this workstream.
- Must not introduce a mechanism by which Phase 6 reads `CertificationMetadata` as part of its own generation pipeline — if an issuance checkpoint reads Phase 7 state, it must do so at issuance time, as a separate concern from Phase 6 report generation.
- Disclosure records must be structured and evidence-linked, consistent with the platform-wide Evidence Principle that no conclusion may exist without evidence lineage.

---

## 11. Dependencies

- **A1** depends on a future Product Strategy decision for the "Default Evidence Custody Period" parameter before the enforcement mechanism can be exercised end-to-end (the mechanism can be fully designed and built without this value, but cannot be operationally activated without it).
- **A1** has a flagged, unresolved dependency on legal hold *authorization policy* (who may place/release a hold) — Workstream A defines only the technical override behavior.
- **A1** has a flagged dependency on eventual retention/custody scope decisions from Workstream B/C (e.g., whether custody periods differ by evidence class or by customer contract) — not resolved here.
- **A2** depends on the existing Phase 7 `CertificationMetadata` schema and `phase7_consumer_contract_v1` remaining stable; A2 consumes `terminal_state`, `certificate_id`, and `disclosed_failures` as already defined, without modification.
- **A2** has a flagged dependency on Workstream B2 (terminology reconciliation between "Audit Platform Integrity" and "Audit Process Integrity") — not resolved here; A2 uses the current locked roadmap terminology ("Audit Platform Integrity") throughout.
- **A2** has a flagged dependency on the fact that no customer-facing delivery mechanism exists yet — the issuance checkpoint must be designed against currently-existing operations (e.g., engineering retrieval CLI commands that produce full report content) as the initial enforcement points, pending future delivery-mechanism work.

---

## 12. Assumptions

**Assumption requiring confirmation (A1):** The enforcement mechanism applies at minimum prospectively, to evidence created after Workstream A implementation. Whether and how the pre-existing indefinitely-retained backlog is retroactively brought under custody-period enforcement is treated as a distinct migration decision, not automatically assumed. Requires confirmation from Architect / Product Strategy before Technical Design finalizes backlog handling.

**Assumption requiring confirmation (A2):** In the absence of a built customer delivery mechanism, "issuance" is provisionally scoped to any platform operation that produces full, customer-facing report content for external use — today, this is understood to include the Phase 6 engineering retrieval commands that return complete report content (e.g., `rcp retrieve report-json`, `rcp retrieve report-markdown`). This provisional scoping requires confirmation from Architect / Product Strategy, since no formal "issuance" concept exists in the codebase today and this specification does not have authority to declare which CLI commands are customer-facing.

Neither assumption has been converted into a requirement above; both are flagged for confirmation before Technical Design proceeds to a specific mechanism.

---

## 13. Open Questions

1. **A1 — Default Evidence Custody Period value.** Not resolvable within Workstream A; a Product Strategy decision, tracked separately per the SDLC Verification Gate's own recommendation (lower priority than the enforcement mechanism itself).
2. **A1 — Backlog migration policy.** Should evidence already stored before Workstream A implementation be retroactively subjected to the custody-period clock (started at implementation time), grandfathered indefinitely, or handled by a separate one-time migration decision? Not resolved here; flagged for Technical Design and Product Strategy.
3. **A1 — Legal hold authorization model.** Who is authorized to place and release a legal hold, and through what process? Only the technical override behavior is specified here (FR-A1-4); the authorization policy is out of scope.
4. **A2 — Which current operations constitute "issuance."** Given no formal customer delivery mechanism exists, Technical Design must enumerate the concrete platform operations the issuance checkpoint attaches to today. A provisional assumption is stated in Section 12 but requires confirmation.
5. **A2 — Force-regeneration re-certification requirement.** Does a force-regenerated Phase 6 report artifact (new `report_job_id`) require a fresh Phase 7 certification before issuance, or does a prior `CERTIFIED` state for an earlier `report_job_id` under the same identity tuple still satisfy issuance gating? Flagged explicitly in AC-A2-7; not resolved by this specification.
6. **A2 — Terminology.** "Audit Platform Integrity" vs. "Audit Process Integrity" is explicitly out of scope (Workstream B2). This specification uses "Audit Platform Integrity" throughout, consistent with the current locked roadmap term.

---

## 14. Impacted Phase(s)

Workstream A is a set of **compliance corrections to already-locked Phase 1 through Phase 7 behavior**. It does not introduce, extend, or reopen the scope of any roadmap phase, and it is not itself a new phase.

- **A1** touches infrastructure and persistence used by every phase from Phase 1 (raw execution evidence) through Phase 7 (certificates): `infra/resources/s3.yml` (`RawResultsBucket`), `infra/resources/dynamodb.yml` (`MetadataTable`). It corrects a cross-cutting infrastructure default, not any single phase's domain logic.
- **A2** touches the boundary between Phase 6 (Deterministic Reporting) and Phase 7 (Audit Platform Integrity) — specifically, it adds a new enforcement point that is neither a Phase 6 nor a Phase 7 internal concern, but sits at the consumption/issuance boundary downstream of both. It does not reopen Phase 6 report-generation logic or Phase 7 certification-domain logic; both remain exactly as locked in their respective technical designs and the certification-independence ADR.

Per `RCP_Product_Strategy.md` Phase Governance, current completed phases remain Phase 0 through Phase 8 (with Phase 9 on governance hold). Workstream A does not advance, reopen, or gate any phase's completion status — it corrects implementation behavior within phases already marked complete, in order to bring that behavior into conformance with governance defaults and constitutional rules that predate this workstream.

---

## 15. Traceability

- Brownfield Initiative (parent document): `docs/product/evidence_governance_workstream_a_brownfield_initiative.md`
- SDLC Verification Gate reviews: `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_claude.md`, `docs/review/evidence_governance_baseline_v1_0_sdlc_verification_opencode.md`
- ADR — Certification Independence: `docs/architecture/adr_phase7_certification_independence.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 7 → Phase 8 Consumer Contract: `docs/architecture/phase_7_phase8_consumer_contract.md`
- Phase 7 Product Spec (terminology/format reference): `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Infrastructure: `infra/resources/s3.yml`, `infra/resources/dynamodb.yml`
- Product Constitution: `RCP_Product_Strategy.md`
