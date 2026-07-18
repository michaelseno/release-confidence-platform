# ADR: Report Issuance Governance — An Independent Checkpoint Distinct From Phase 6 Completion and Phase 7 Certification

## Status

Proposed — Workstream A2 Planning Deliverable (SDLC planning only; implementation not authorized)

## Context

`docs/architecture/adr_phase7_certification_independence.md` establishes that Phase 7 (Audit Platform Integrity) is operator-invoked, non-blocking, and runs strictly after Phase 6 (`ReportMetadata.status = COMPLETE`) with no event-driven trigger. This is a deliberate, ratified design: Phase 6 must not wait on Phase 7, and Phase 7 must never write to any Phase 6 record.

That same ADR's Decision 5 rationale explains the trade-off explicitly: "The Product Constitution requires explicit operator confirmation before a Release Confidence Report may be issued" — i.e., the non-blocking design was accepted *because* it assumed operator discipline would honor the Product Constitution's own non-negotiable rule:

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

Both independent SDLC Verification Gate review passes confirmed that no architectural control exists today enforcing this rule — a `COMPLETE` report can be retrieved via the engineering retrieval CLI regardless of whether certification ever ran, failed, or was blocked. `docs/product/evidence_governance_workstream_a_product_spec.md` (FR-A2-1 through FR-A2-7, AC-A2-1 through AC-A2-7) requires an enforcement point — the "issuance checkpoint" — that closes this gap without reopening or amending `adr_phase7_certification_independence.md`.

Three design dimensions required explicit architectural resolution:

1. **Where does the checkpoint live, without becoming a Phase 6 or Phase 7 internal concern?** The Product Spec explicitly requires issuance to be "distinct from `ReportMetadata.status = COMPLETE`" (FR-A2-1) and requires that "if an issuance checkpoint reads Phase 7 state, it must do so at issuance time, as a separate concern from Phase 6 report generation."
2. **What concrete operations does "issuance" attach to today?** No customer-facing delivery mechanism exists. The Product Spec provisionally named the Phase 6 engineering retrieval commands (`rcp retrieve report-json` / `report-markdown`) as an assumption requiring confirmation, referencing `retrieval/service.py`.
3. **How does the checkpoint behave correctly across force re-certification (AC-A2-5) and force report regeneration (AC-A2-7)?** The Product Spec explicitly flags both as lineage-integrity-sensitive and states they "must not be left ambiguous."

## Decision

### Decision 1: A New, Third Ownership Domain — "Issuance Governance" — Distinct From Both Phase 6 and Phase 7

Neither `deterministic_reporting/` (Phase 6) nor `audit_platform_integrity/` (Phase 7) is modified. A new module, `report_issuance_governance/`, is introduced at the same package level as the existing phase modules. This module owns exactly one responsibility: evaluating whether a specific, already-produced report artifact may be treated as issued. It does not generate reports, does not perform certification, and does not re-derive any conclusion either phase produced.

This mirrors the existing constitutional-boundary-statement convention used for Phase 6/Phase 7 ("Reporting owns presentation. Phase 7 owns platform integrity certification."). This ADR adds a third statement: **"Phase 6 owns reporting. Phase 7 owns platform integrity certification. Issuance Governance owns the customer-facing release gate — it composes Phase 6 completion and Phase 7 certification (or explicit disclosure) into a single enforceable checkpoint, without owning, modifying, or being read by either."**

### Decision 2: The Checkpoint Attaches to Every `rcp retrieve report-*` Command Backed by a Full-Artifact Read — `report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage` — Exempting Only `report-status`. Located in `deterministic_reporting/report_retrieve_commands.py` and Wired at `operator_cli/main.py` — Correcting the Product Spec's Provisional Location

Direct code inspection establishes that the Product Spec's provisional reference to `retrieval/service.py` names the wrong module: `retrieval/service.py` (`RetrievalService`, Phase 4A Engineering Retrieval) serves aggregation-layer diagnostic queries (job status, lineage manifests, timelines) and never touches `ReportMetadata` or full report content. The seven `rcp retrieve report-*` commands actually live in `deterministic_reporting/report_retrieve_commands.py` (parser + dispatch) backed by `deterministic_reporting/report_service.py` (`ReportRetrievalService`), wired into the CLI at `operator_cli/main.py` (the `if retrieve_command.startswith("report-"):` block).

**Revised finding (corrects an earlier draft of this ADR):** direct inspection of `deterministic_reporting/report_service.py` and `report_retrieve_commands.py` establishes that `report-summary`, `report-endpoints`, `report-methodology`, and `report-lineage` — not only `report-json`/`report-markdown` — each call `ReportRetrievalService.get_report_dto()`, which loads the full S3 report artifact and parses it into the same, fully-populated `ReleaseConfidenceReport` DTO that `report-json` serializes wholesale. These four commands are provenance-enveloped *renderings* of that same complete DTO, not reduced-content reads: combined, they emit the full executive summary, every endpoint's complete five-dimension score breakdown, the full methodology disclosure (including limitations), and the full input lineage — in aggregate, effectively the entire substantive content of the report, reachable without ever calling `report-json` or `report-markdown`. The earlier premise that these five commands are minimal "fragments" not needing gating does not hold once traced against `get_report_dto()`'s actual behavior.

Of the seven `report-*` commands, exactly one — `report-status` — is genuinely DynamoDB-only: `_handle_report_status` calls `ReportRetrievalService.get_report_status()`, which reads only the `ReportMetadata` DynamoDB record and never calls `get_report_dto()` or `get_report_artifact()`; no S3 read, and therefore no report content, occurs on that path. The issuance checkpoint gates all six commands that resolve to `get_report_dto()` or `get_report_artifact()` — `report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage` — and exempts only `report-status`.

This scoping rule — "gate every command backed by a full-artifact read; exempt only the DynamoDB-only status check" — is a direct, code-verified consequence of `report_service.py`'s actual method boundaries, not a judgment call requiring further confirmation. It replaces the earlier narrower scoping, which is retracted.

### Decision 3: The Checkpoint Is a Synchronous Guard Invoked Inline at the CLI Dispatch Boundary — Not a Modification to Either Phase's Service or Repository Layer

The guard function (`evaluate_issuance_checkpoint`) is invoked in `operator_cli/main.py`, immediately before `dispatch_report_retrieve(...)` is called for any `retrieve_command` other than `report-status`, and raises a structured `IssuanceBlockedError` on failure (caught by the existing CLI error-handling path, non-zero exit). `operator_cli/main.py` is the platform's existing cross-phase composition layer (it already imports and wires Phase 6 and Phase 7 retrieval services independently) — it is not owned by Phase 6 or Phase 7, so adding a third, independent import here does not touch either phase's internals.

The guard performs three read-only lookups, none of which write anywhere:

1. `ReportMetadata` (already read by the existing retrieval call; the checkpoint additionally uses its `report_id` for the freshness check in Decision 5).
2. `CertificationMetadata`, read using the exact `phase8_consumer_contract_v1` access pattern and restrictions (read-only, by identity-tuple key, never `CertificationJob`) — the checkpoint is architecturally a second Phase 7 consumer alongside Phase 8, not a special-cased reader.
3. A new `DisclosureRecord`, read-only, from a new sort-key namespace (`#DISC#`) that collides with no existing Phase 4–7 namespace.

### Decision 4: Absence of `CertificationMetadata` and Non-`CERTIFIED` States Both Require an Explicit, Structured Disclosure — Never an Implicit Pass

A `DisclosureRecord` is a new record type, written only via a new, explicit CLI action (`rcp issuance disclose ...`), never inferred or auto-generated. Its `disclosure_reason` is one of a bounded set (`NO_CERTIFICATION_RECORD`, `NON_CERTIFIED_TERMINAL_STATE`, `CERTIFIED_BUT_SUPERSEDED_REPORT` — see Decision 5), and its `acknowledged_failures` field is computed server-side from `CertificationMetadata.disclosed_failures` at write time (never operator-supplied free text), so a partial disclosure cannot be constructed even by operator error — the write path itself enforces completeness (AC-A2-4's "full `disclosed_failures` list" requirement and the edge case prohibiting partial disclosure).

### Decision 5: Force Re-Certification and Force Report Regeneration — Explicit, Concrete Evaluation Rules

**AC-A2-5 (force re-certification):** `CertificationMetadata` is written via unconditional `PutItem` at a fixed identity-tuple sort key (`repository.py:write_cert_metadata_complete`); every read of that key returns the latest certification event by construction. The issuance checkpoint requires no additional logic to satisfy AC-A2-5 — reading `CertificationMetadata` for the current identity tuple always yields the record produced by the most recent `--force` re-certification, and the prior certificate S3 artifact remains preserved unmodified at its original key per Phase 7's own immutability guarantee (untouched by this ADR).

**Concurrent issuance during an in-progress force re-certification:** The checkpoint reads only `CertificationMetadata`, never `CertificationJob`. Phase 7 writes intermediate `PENDING`/`IN_PROGRESS` states only to `CertificationJob`; `CertificationMetadata` is updated exactly once, atomically, when the new certification reaches `COMPLETE`. A concurrent issuance attempt therefore always observes either the prior terminal state (if the new certification has not yet completed) or the new terminal state (once it has) — DynamoDB `GetItem` is atomic per item, so no torn or partial read is possible. This is the authoritative-record rule for the transition window.

**AC-A2-7 (force report regeneration):** Per `phase_6_report_schema.md` §5.2, a force-regenerated report does **not** receive a new identity-tuple sort key — `ReportMetadata` is updated in place, with `report_job_id`, `report_id`, and `s3_artifact_ref` all changing while the identity tuple (and therefore the `CertificationMetadata` sort key Phase 7 would use) stays identical. A prior `CERTIFIED` `CertificationMetadata` record for that same identity tuple would therefore still read as `CERTIFIED`, while `CertificationMetadata.report_id` now points to the *superseded* report, not the newly regenerated one.

This ADR resolves AC-A2-7 decisively: **the checkpoint requires `CertificationMetadata.report_id == ReportMetadata.report_id` (current) in addition to `terminal_state == CERTIFIED`.** A mismatch is treated identically to a non-`CERTIFIED` condition — it requires an explicit disclosure (`disclosure_reason = CERTIFIED_BUT_SUPERSEDED_REPORT`) before issuance may proceed. A prior `CERTIFIED` state does **not** automatically govern a force-regenerated report; fresh re-certification against the new report artifact (or an explicit disclosure acknowledging the mismatch) is required. This is the conservative reading, consistent with Phase 7's own stated purpose: "a stale `CERTIFIED` state evaluated against new report content would be a lineage-integrity violation of the type Phase 7 itself exists to prevent" (Product Spec, Edge Cases, A2).

## Rationale

### Why a third module rather than embedding the check in Phase 6 or Phase 7

Embedding the check in Phase 6 would require Phase 6 to read `CertificationMetadata`, which the Product Spec's own Constraints section prohibits ("must not introduce a mechanism by which Phase 6 reads `CertificationMetadata` as part of its own generation pipeline"). Embedding it in Phase 7 would require Phase 7 to know about retrieval/issuance concerns that are downstream of its own certification responsibility, and would blur "Phase 7 owns platform integrity certification" the same way Phase 6 embedding blurred "Phase 6 owns reporting" — the exact anti-pattern `adr_phase7_certification_independence.md` Alternative 1 already rejected for Phase 7 itself. A third, independent module that reads both phases' outputs read-only, at issuance time, is the design that satisfies every non-negotiable invariant simultaneously without special-casing either phase.

### Why the CLI dispatch boundary, not a service-layer wrapper inside `deterministic_reporting/`

Placing the guard inside `report_service.py` or `report_retrieve_commands.py` would make those modules depend on Phase 7's repository — a Phase 6 → Phase 7 dependency in the wrong direction, and a modification to Phase 6 code to enforce a Phase 7-adjacent concern. `operator_cli/main.py` already composes both phases' retrieval services independently for the `report-*` and `cert-*` command families; adding a third, independent composition point there requires no change to either phase's package.

### Why six of seven `report-*` commands, exempting only `report-status`

FR-A2's own language scopes issuance to operations that "produce full, customer-facing report content for external use." An earlier draft of this ADR assumed `report-summary`, `report-endpoints`, `report-methodology`, and `report-lineage` were partial/diagnostic fragments, distinguishable from `report-json`/`report-markdown` by their provenance-envelope wrapping. Code inspection (Decision 2) disproved that premise: all four load and parse the identical full S3 artifact via `get_report_dto()` that `report-json` serializes wholesale — the provenance envelope is a formatting choice, not a content restriction. In aggregate, an operator could reconstruct the entire substantive report (executive summary, every endpoint's full score breakdown, complete methodology disclosure including limitations, and full lineage) through those four commands alone, without ever calling `report-json` or `report-markdown`, and never trip a checkpoint gating only the latter two. Gating all six full-artifact-backed commands and exempting only `report-status` (verified DynamoDB-only, no S3 read, no report content) closes this gap. This is now a direct consequence of `report_service.py`'s method boundaries, not a discretionary scoping choice.

### Why `report_id` equality, not `s3_artifact_ref` equality, for the superseded-report check

Both fields change together on force regeneration, so either would detect the mismatch. `report_id` is the field explicitly named in both `phase_6_report_schema.md` and `phase_7_phase8_consumer_contract.md` as the canonical cross-phase report identifier (`CertificationMetadata.report_id`, `CertificationReportReference.report_id`), making it the more semantically direct comparison and the one least likely to be affected by any future S3 key-structure change.

## Consequences

### What This Architecture Enables

- A `COMPLETE` report cannot be retrieved as full content via the engineering CLI unless it is either certified against the current report artifact or an explicit, structured disclosure has been recorded — closing the "operator-discipline-only" gap.
- The disclosure record is itself durable and evidence-linked (`certificate_id`, `terminal_state`, full `disclosed_failures`), satisfying the platform-wide Evidence Principle that no conclusion may exist without evidence lineage.
- Force re-certification and force report regeneration both have unambiguous, testable evaluation rules — no operator judgment call is required at issuance time to determine which record governs.
- All six non-negotiable invariants in `adr_phase7_certification_independence.md` remain intact: Phase 6 does not wait on or read Phase 7 state during generation; Phase 7 never writes to any Phase 6 record; Phase 7 remains operator-invoked; no event-driven trigger is introduced.

### Constraints This Architecture Creates

- **The checkpoint only covers the six commands it is wired to (`report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage`).** If a future delivery mechanism (Workstream E, out of scope here) is added, it must independently invoke the same checkpoint; the checkpoint's protection does not automatically extend to code paths that do not call it. This is a design responsibility for future work, not a gap in this ADR's scope.
- **A direct AWS API call using the same operator credentials the CLI already requires (`aws s3 cp` against the report artifact's known S3 key, or a raw DynamoDB `GetItem`) bypasses the CLI-layer checkpoint entirely.** This is not a gap this design closes — it is an accepted characteristic of RCP's operator-only trust model: every existing CLI command in this platform is enforced only at the CLI layer, with no independent server-side authorization boundary between an operator's AWS credentials and the underlying S3/DynamoDB resources. The issuance checkpoint raises the bar for the *intended* retrieval path; it does not, and is not designed to, prevent an operator with direct AWS access from reading the same underlying objects by other means. This should be stated explicitly to reviewers and operators rather than left for a reader to assume the CLI gate is the only path to report content.
- **A disclosure recorded against one `certificate_id` does not carry forward to a new `certificate_id` produced by a later force re-certification.** Operators must re-disclose (or rely on the fresh `CERTIFIED` state) after every force re-certification that changes the governing certificate. This is intentional (see Decision 5) but is an operational step operators must be aware of.
- **The checkpoint depends on `phase7_consumer_contract_v1` / `phase8_consumer_contract_v1` remaining stable**, exactly as Phase 8 already does. Any future breaking change to `CertificationMetadata`'s stable field set requires updating this checkpoint alongside Phase 8, per the existing contract-versioning governance process.

## Alternatives Considered

### Alternative 1: Embed the Gate Inside Phase 6's `ReportRetrievalService`

Rejected. Requires Phase 6 to depend on and read Phase 7's `CertificationRepository`, violating the Product Spec's explicit constraint against Phase 6 reading `CertificationMetadata` as part of its own pipeline, and blurs Phase 6's "owns reporting" boundary the same way embedding certification in Phase 6 (rejected in `adr_phase7_certification_independence.md` Alternative 1) would have blurred it.

### Alternative 2: Make `ReportMetadata.status` Itself Conditional on Certification (Merge Issuance Into Phase 6 Completion)

Rejected outright — this is the one option the Product Spec and `adr_phase7_certification_independence.md` both foreclose explicitly. It would make Phase 6 wait on Phase 7, violating Non-Negotiable Invariant 4 ("`ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 certification; no alternative completeness signal may substitute") in spirit if not literally, and would reopen a decision this workstream is constitutionally required not to reopen.

### Alternative 3: Event-Driven Issuance Check Triggered by `CertificationMetadata` Writes

Rejected. Would require a DynamoDB Streams trigger on `MetadataTable` reacting to Phase 7 writes — exactly the event-driven Phase 7 automation `adr_phase7_certification_independence.md` Alternative 4 rejected for MVP, and explicitly disallowed again by FR-A2-7 of the Product Spec ("shall not introduce an event-driven trigger for Phase 7 certification"). A synchronous, on-demand guard invoked at the point of retrieval is both sufficient and compliant.

### Alternative 4: Allow a Disclosure to Persist Across Force Re-Certification (Bind Disclosure to Identity Tuple, Not `certificate_id`)

Rejected. Binding disclosure to the identity tuple rather than the specific `certificate_id` would let a stale disclosure silently satisfy issuance against a certificate it never actually reviewed, reintroducing exactly the kind of unverifiable, non-evidence-linked override the Constraints section prohibits ("Disclosure records must be structured and evidence-linked"). Binding to `certificate_id` forces re-evaluation whenever the governing certificate changes.

## Non-Negotiable Invariants

Carried forward unconditionally from `adr_phase7_certification_independence.md` (reproduced here because A2 is the workstream most likely to be tempted to relax them):

1. Phase 7 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion or Phase 6 report section. The Issuance Governance checkpoint does not re-derive anything either — it composes existing terminal states and identifiers, nothing more.
2. Phase 7 shall never read Phase 5 or Phase 4 artifacts directly. Not touched by this ADR.
3. `ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 certification. Not touched — issuance evaluation happens strictly after, and independently of, that gate.
4. Phase 7 shall never mutate any Phase 6 report artifact, `ReportMetadata` record, or `ReportJob` record. Not touched — Issuance Governance also never mutates any Phase 6 or Phase 7 record; its only writes are to its own new `#DISC#` namespace.
5. Reporting owns presentation. Phase 7 owns platform integrity certification. Issuance Governance owns the customer-facing release gate — a new, third, non-overlapping ownership statement introduced by this ADR.
6. No event-driven trigger for Phase 7 certification is introduced by this workstream. The checkpoint is a synchronous, on-demand guard, not a stream/event consumer.
7. Issuance Governance code must assert its own write-target sort key (`_assert_issuance_sk`) before every `PutItem`/`UpdateItem` call, mirroring `_assert_phase7_sk` in `audit_platform_integrity/repository.py` and `_assert_retention_sk`/`_assert_disposal_sk` introduced by the sibling A1 ADR. This is a code-level, programming-error guard, not an IAM-enforced boundary (DynamoDB IAM cannot condition `PutItem` on sort-key substrings) — it guarantees at the code level, not merely by convention, that Issuance Governance can never write to a Phase 6 or Phase 7 sort key. Required, not optional, at implementation time.

## Traceability

- Brownfield Initiative: `docs/product/evidence_governance_workstream_a_brownfield_initiative.md`
- Product Specification: `docs/product/evidence_governance_workstream_a_product_spec.md` (FR-A2-1 through FR-A2-7; AC-A2-1 through AC-A2-7)
- Technical Design: `docs/architecture/evidence_governance_workstream_a2_issuance_governance_technical_design.md`
- ADR — Certification Independence (all six invariants carried forward): `docs/architecture/adr_phase7_certification_independence.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 7 → Phase 8 Consumer Contract (access-pattern precedent for a read-only Phase 7 consumer): `docs/architecture/phase_7_phase8_consumer_contract.md`
- Sanitization Boundary ADR (governs `client_id`/`audit_id`/`certificate_id`/`report_id` handling in new `report_issuance_governance/` records — `sanitize()` must never reach persistence-bound dicts): `docs/architecture/adr_sanitization_boundary.md`
- Code inspected to correct the Product Spec's provisional location: `src/release_confidence_platform/deterministic_reporting/report_retrieve_commands.py`, `src/release_confidence_platform/deterministic_reporting/report_service.py`, `src/release_confidence_platform/operator_cli/main.py`
- Product Constitution: `RCP_Product_Strategy.md`
