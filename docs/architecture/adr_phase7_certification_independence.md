# ADR: Phase 7 — Certification Independence from Prior Aggregation, Intelligence, and Reporting Phases

## Status

Accepted

## Context

The Release Confidence Platform produces Release Confidence Reports through a multi-phase pipeline:

- Phase 4 (Aggregation) transforms raw execution evidence into deterministic aggregate facts.
- Phase 5 (Reliability Intelligence) derives reliability interpretation from Phase 4 aggregates.
- Phase 6 (Deterministic Reporting) faithfully presents Phase 5 intelligence conclusions in a Release Confidence Report.

Each phase owns its output and is prohibited from mutating the outputs of prior phases. This boundary-respecting pipeline produces a Release Confidence Report that is a faithful representation of what Phase 5 concluded from Phase 4 facts.

However, the pipeline as designed through Phase 6 does not address a second-order question: can the audit process that produced the Release Confidence Report itself be trusted?

Five specific failure modes exist that prior phases do not address and that undermine the defensibility of any Release Confidence Report:

1. **Runner degradation**: A runner may produce valid-looking raw evidence while in a degraded state. Phase 3 captures execution completion; it does not certify that observation conditions were sound.

2. **Observation coverage gaps**: The scheduler may have skipped observation windows. Phase 3 enforces audit lifecycle completion but does not certify that observation density met methodology minimums.

3. **Evidence artifact integrity**: The Phase 6 report artifact may have been modified after initial write, or identity fields in the artifact may be inconsistent with the `ReportMetadata` DynamoDB record.

4. **Lineage chain breaks**: The chain from Phase 4 aggregation (via `aggregate_set_hash`) through Phase 5 intelligence to the Phase 6 report must be unbroken. No prior phase performs an end-to-end lineage verification pass.

5. **Report internal inconsistency**: The report artifact may contain fields that are internally inconsistent — out-of-range score values, unsorted endpoints, or invalid version identifiers — due to generation failures or schema changes that bypassed prior detection gates.

The Product Constitution states an unconditional requirement:

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

This requirement mandates a distinct verification phase that can certify the process, not just the output. The architectural question is: what form should this phase take, and what are the boundaries on what it may read and write?

Three design dimensions required explicit architectural resolution:

1. **Independence boundary**: Should Phase 7 read Phase 5 and Phase 4 artifacts directly, or only Phase 6 report artifacts?
2. **Separation boundary**: Should certification logic be embedded inside Phase 6 report generation, or be a distinct phase?
3. **Mutation boundary**: Should Phase 7 be permitted to amend, annotate, or rewrite Phase 6 artifacts?

---

## Decision

### Decision 1: Phase 7 Is a Distinct, Independent Phase — Not Embedded in Phase 6

Phase 7 (Audit Platform Integrity) is a separate phase that executes after Phase 6 completes. Platform integrity certification is not embedded as a post-generation step within the Phase 6 report generation pipeline.

### Decision 2: Phase 7 Reads Exclusively Phase 6 Artifacts

Phase 7 is a consumer of Phase 6 outputs only. It may read:
- The `ReportMetadata` DynamoDB record (read-only; prerequisite gate).
- The S3 report artifact located at `ReportMetadata.s3_artifact_ref`.

Phase 7 is unconditionally prohibited from reading:
- Phase 5 intelligence artifacts (`IntelligenceMetadata`, Phase 5 S3 artifacts).
- Phase 4 aggregation artifacts (`AggregateSetCompletion`, lineage manifests, aggregate records).
- Phase 1, Phase 2, or Phase 3 raw execution evidence records.

The Phase 6 report artifact faithfully carries all Phase 5 intelligence conclusions, methodology disclosure, and lineage information verbatim. Everything Phase 7 needs to verify audit integrity is present in the Phase 6 report artifact. Bypassing Phase 6 to read Phase 5 or Phase 4 directly would couple Phase 7 to those layers unnecessarily and undermine the independence of the verification.

### Decision 3: Phase 7 Is Read-Only With Respect to All Prior Phase Artifacts

Phase 7 must not create, update, delete, or extend any Phase 6 report artifact, `ReportMetadata` record, `ReportJob` record, or any Phase 5, Phase 4, or earlier artifact.

Phase 7 writes only to Phase 7-owned DynamoDB sort key namespaces (`#CERTJOB#`, `#CERT#`) and the `integrity/` S3 key prefix. These namespaces do not overlap with any prior phase.

### Decision 4: The Platform Integrity Certificate Is a Separate, Immutable Artifact

Phase 7 produces its own Platform Integrity Certificate as a separate S3 artifact under the `integrity/` key prefix. The certificate references the Phase 6 report by key (`s3_report_artifact_ref`) but does not embed report content. The final customer-facing audit deliverable references both artifacts. This composition is a Phase 8+ concern; Phase 7 is not responsible for it.

The certificate is immutable once written. Force re-certification creates a new `certificate_id` at a new S3 key; prior certificates are preserved.

### Decision 5: Phase 7 Is Operator-Invoked — No Event-Driven Trigger in MVP

Phase 7 certification is initiated by the operator via `rcp certify audit` CLI after confirming `ReportMetadata.status = COMPLETE`. No event-driven Lambda trigger from a `ReportMetadata` status change is implemented in Phase 7. Event-driven automation belongs to post-Phase 7 phases once the certification contract is stable.

---

## Rationale

### Trust Model: Independence Requires Separation

RCP's product positioning is an independent audit platform. "Independent" means the certification of the audit process must not be controlled by the same code path that produced the audit output. If Phase 7 certification logic were embedded inside Phase 6 report generation, a bug in Phase 6 could simultaneously corrupt the report and suppress the certification of that corruption. Independence requires a separate execution context with a separately defined input boundary.

The phase boundary enforces this: Phase 7 begins only after Phase 6 has persisted its outputs and signaled completion via `ReportMetadata.status = COMPLETE`. Phase 7 examines what Phase 6 produced; it does not participate in producing it.

### Evidence Independence: The Certifier Must Not Be Entangled With What It Certifies

If Phase 7 read Phase 5 or Phase 4 artifacts directly, it would be performing its own independent intelligence derivation or aggregation pass. This would not be a certification of what Phase 6 reported — it would be a re-verification of Phase 4 and Phase 5 conclusions. This conflates two distinct responsibilities:

1. Verifying what the platform produced (Phase 7's responsibility).
2. Re-deriving what the platform should have produced (no phase's responsibility; would undermine the deterministic and immutable nature of the platform).

Phase 7's role is to certify that the process Phase 6 faithfully reported was sound. The Phase 6 report artifact already carries all Phase 5 conclusions, methodology trace, and lineage references verbatim. Phase 7 verifies these fields using logical assertions — not by re-executing Phase 5 or Phase 4 logic.

### Auditability: The Platform's Own Audit Must Be Reproducible

The certificate must be reproducible: given the same Phase 6 report artifact and the same `ReportMetadata` record, the certification result must always be identical within `cert_v1`. This is only possible if Phase 7 reads exclusively from stable, immutable inputs. Phase 6 report artifacts are immutable once written; `ReportMetadata` stable fields are defined by the `phase7_consumer_contract_v1`. Reproducibility is guaranteed by design.

If Phase 7 read Phase 5 or Phase 4 directly, it would be reading records that may be updated across invocations (e.g., force re-aggregation or re-intelligence), undermining reproducibility.

### Separation of Concerns: Certification Is Not Reporting

Embedding certification inside Phase 6 would expand Phase 6's responsibilities beyond presentation. Phase 6's constitutional mandate is: "Intelligence owns interpretation. Phase 6 owns reporting." Certification of the audit process is a distinct responsibility. Mixing it into Phase 6 would blur ownership and make Phase 6 harder to reason about, test, and maintain independently.

A separate phase with a clearly defined input contract (the `phase7_consumer_contract_v1`) and a clearly defined output (the `PlatformIntegrityCertificate`) is easier to test in isolation, easier to evolve independently, and easier to explain to customers as a second-order verification step.

### Non-Mutation: Certification Must Not Change What It Certifies

If Phase 7 were permitted to amend Phase 6 artifacts (e.g., by appending a certification timestamp or status field to `ReportMetadata`), the certification process would be modifying the artifact under examination. This violates the principle that the certifier must not alter the evidence it certifies. Phase 7's non-mutation invariant is unconditional.

---

## Consequences

### What This Architecture Enables

- **Defensible second-order verification.** Every Release Confidence Report has a corresponding Platform Integrity Certificate that independently attests to the process that produced it. Customers receive not just a score but a certified statement that the process was sound.
- **Stable Phase 8 input.** The `CertificationMetadata` DynamoDB record and the Phase 7 S3 certificate artifact are stable, well-defined artifacts that Phase 8 Commercialization can reference without coupling to Phase 6 internals.
- **Independent testability.** Phase 7 can be unit tested and integration tested in isolation, using Phase 6 fixture artifacts as inputs. No Phase 5 or Phase 4 dependencies are required in the Phase 7 test suite.
- **Reproducible certification.** The same Phase 6 fixture artifact always produces the same certification result within `cert_v1`. QA validation is repeatable and deterministic.
- **Clear failure ownership.** When certification fails, the failure is attributed to a specific domain with specific evidence refs. The certificate records exactly what failed and why, without re-deriving analytical conclusions.

### Constraints This Architecture Creates

- **Phase 7 cannot verify raw evidence directly.** If a runner produced subtly incorrect raw results that nonetheless produced a coherent Phase 6 report, Phase 7 cannot detect this. Phase 7 verifies the audit process as recorded in the Phase 6 report, not the raw evidence that preceded Phase 4. This is an explicit design boundary, not a gap.

- **Phase 7 depends on Phase 6 faithfulness.** If Phase 6 misrepresented Phase 5 conclusions in the report artifact, Phase 7 would certify a misrepresentation as consistent. Phase 6's mapping fidelity regression test (`test_builder_mapping_fidelity.py`) is the guard against this risk; Phase 7 assumes Phase 6 faithfulness as a precondition.

- **Phase 7 is operator-invoked.** The operator must explicitly run `rcp certify audit` after Phase 6 completes. This requires operational discipline. Automated event-driven certification is deferred to post-Phase 7 phases.

- **The `phase7_consumer_contract_v1` boundary is a governance commitment.** Phase 6 changes that break the stable field set defined in the consumer contract require a contract version increment, HITL approval, and explicit Phase 7 migration documentation. This creates a governance obligation on Phase 6 evolution.

---

## Alternatives Considered

### Alternative 1: Embed Certification Inside Phase 6 Report Generation

Phase 7 certification logic would be implemented as a post-generation step in the Phase 6 `engine.py` pipeline, running immediately after `ReportJob → COMPLETE` and before the summary is displayed to the operator.

**Rejected because:**
- Violates independence. The certifier would be part of the same execution context as the process it certifies. A bug in report generation could corrupt both the report and its certification simultaneously.
- Expands Phase 6 scope beyond its constitutional mandate. Phase 6 owns reporting, not certification.
- Makes Phase 6 harder to test and maintain independently.
- Eliminates the ability to re-certify without re-generating the report.
- The product spec explicitly defines Phase 7 as a separate phase with a distinct invocation path and lifecycle.

### Alternative 2: Phase 7 Reads Phase 5 Intelligence Artifacts Directly

Phase 7 would read `IntelligenceMetadata` and the Phase 5 S3 intelligence artifact in addition to Phase 6 artifacts, enabling cross-validation of what Phase 5 produced against what Phase 6 reported.

**Rejected because:**
- Violates the non-negotiable invariant established in `phase7_consumer_contract_v1`: "Phase 7 must not read Phase 5 intelligence artifacts directly for any platform integrity verification purpose."
- Creates a coupling between Phase 7 and Phase 5 schema internals, increasing the blast radius of Phase 5 schema changes.
- The Phase 6 report artifact already carries Phase 5 intelligence conclusions verbatim. There is no information in Phase 5 artifacts that is not available in the Phase 6 report artifact for Phase 7's verification purposes.
- Re-reading Phase 5 would make Phase 7 a de facto Phase 5 consumer, not a Phase 6 consumer. This is a category error.

### Alternative 3: Phase 7 Reads Phase 4 Aggregation Artifacts Directly

Phase 7 would read Phase 4 `AggregateSetCompletion` and aggregate records to independently verify the lineage chain from Phase 4 forward.

**Rejected because:**
- Violates the non-negotiable invariant: "Phase 7 shall never read Phase 4 aggregation artifacts directly."
- The Phase 6 report artifact carries `aggregate_set_hash` from Phase 4 (via Phase 5) verbatim. Lineage chain verification is performed by verifying that `aggregate_set_hash` is present, non-null, consistent across all three records (`ReportMetadata`, `intelligence_provenance`, `input_lineage`), and correctly carried. This does not require reading Phase 4 records.
- Reading Phase 4 records would create a direct Phase 4 → Phase 7 dependency, bypassing the phase contract chain.

### Alternative 4: Phase 7 as an Event-Driven Lambda Triggered by ReportMetadata Status Change

Phase 7 certification would be triggered automatically by a DynamoDB Stream event on `ReportMetadata.status = COMPLETE`, without requiring operator invocation.

**Rejected for MVP because:**
- Adds infrastructure complexity (DynamoDB Streams, Lambda trigger, IAM permissions) before the certification contract is stable and validated.
- Removes operator visibility and control at a critical trust gate. The Product Constitution requires explicit operator confirmation before a Release Confidence Report may be issued. Automatic certification without operator awareness undermines this control.
- Event-driven automation is appropriate once the certification semantics are stable and tested. It belongs to post-Phase 7 phases.
- The operator CLI invocation model is consistent with Phase 6 and Phase 4A patterns; it requires no new infrastructure.

### Alternative 5: Amend the Phase 6 Report Artifact With Certification Status

Phase 7 would update `ReportMetadata` with a certification status field (e.g., `certification_status = CERTIFIED`) and embed the certificate ID in the `ReportMetadata` record, rather than maintaining a separate `CertificationMetadata` record.

**Rejected because:**
- Violates the non-mutation invariant: Phase 7 must not write to Phase 6 `ReportMetadata` records.
- Mixes Phase 6 reporting state with Phase 7 certification state in a single record, creating ownership ambiguity.
- A Phase 6 record updated by Phase 7 is no longer exclusively Phase 6-owned. This would conflict with Phase 6's guarantee of being the authoritative owner of its own records.
- A separate `CertificationMetadata` record with Phase 7-owned sort key namespace (`#CERT#`) is consistent with the platform's pattern of each phase owning its own DynamoDB namespace.

---

## Non-Negotiable Invariants

These invariants are cross-referenced from `docs/architecture/phase_6_phase7_consumer_contract.md` Section 9 and cannot be waived without a formal constitutional amendment:

1. Phase 7 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion or Phase 6 report section.
2. Phase 7 shall never read Phase 5 intelligence artifacts directly for any platform integrity verification purpose.
3. Phase 7 shall never read Phase 4 aggregation artifacts directly.
4. `ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 platform integrity certification. No alternative completeness signal may substitute.
5. Phase 7 shall never mutate any Phase 6 report artifact, `ReportMetadata` record, or `ReportJob` record.
6. Reporting owns presentation. Phase 7 owns platform integrity certification.

---

## Traceability

- Phase 7 Product Spec: `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Phase 7 Technical Design: `docs/architecture/phase_7_audit_platform_integrity_technical_design.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Phase 4A Engineering Retrieval ADR: `docs/architecture/adr_phase_4a_engineering_retrieval_consumer_contract.md`
- Phase 4 Evidence Lineage ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- Product Constitution: `RCP_Product_Strategy.md`
