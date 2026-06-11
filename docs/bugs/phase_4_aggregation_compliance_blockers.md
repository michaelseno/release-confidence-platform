# Bug Report

## 1. Summary

Phase 4 Aggregation Layer is **Blocked** at the release/HITL gate due to accepted architecture compliance blockers documented in `docs/review/phase_4_architecture_compliance_review.md`.

This report preserves the governance blocker trail and routes remediation. This is not a new runtime root-cause investigation; the compliance review already provides the primary evidence and was accepted for remediation.

**Status:** Blocked / HITL compliance blocker

## 2. Investigation Context

- **Source of report:** Architecture compliance review after QA sign-off and before proceeding past release/HITL gate.
- **Detection source:** `docs/review/phase_4_architecture_compliance_review.md`
- **Related feature/workflow:** Phase 4 Aggregation Layer; evidence aggregation after successful audit finalization.
- **Affected branch:** `feature/phase_4_aggregation_layer`
- **Branch context observed:** current branch is `feature/phase_4_aggregation_layer`; local Phase 4 changes and untracked artifacts exist.
- **Relevant action:** User accepted compliance findings and directed remediation.

Primary references:

- Compliance review: `docs/review/phase_4_architecture_compliance_review.md`
- Product spec: `docs/product/phase_4_aggregation_layer_product_spec.md`
- Technical design: `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- QA report: `docs/qa/phase_4_aggregation_layer_qa_report.md`
- QA test plan: `docs/qa/phase_4_aggregation_layer_test_plan.md`
- Release readiness evidence: `docs/release/phase_4_aggregation_layer_release_status_evidence.md`
- Implementation report: `docs/backend/phase_4_aggregation_layer_implementation_report.md`

## 3. Observed Symptoms

The architecture compliance review concluded Phase 4 is **Non-Compliant / Blocked**.

Relevant review excerpts:

- `docs/review/phase_4_architecture_compliance_review.md:5`: “Phase 4 is **Non-Compliant / Blocked** for architecture compliance at this time.”
- `docs/review/phase_4_architecture_compliance_review.md:9`: implementation lacks an explicit evidence integrity validation gate reconciling expected execution count, completed execution count, raw evidence availability, duplicate source references, lineage completeness, `audit_execution_id`, and `config_version` before aggregation proceeds.
- `docs/review/phase_4_architecture_compliance_review.md:13`: “If the platform cannot guarantee completeness/integrity of evidence, it must not produce aggregate/intelligence/report.”
- `docs/review/phase_4_architecture_compliance_review.md:29`: Phase 4 must not proceed to further implementation, merge, PR, release preparation, or release action until blockers are remediated and evidence is refreshed.

Expected behavior from user directive:

- Preserve HITL blocker trail under `docs/bugs/`.
- Route design remediation to Architect first.
- Route implementation remediation to Dev-backend after design/ADR updates.
- Require QA revalidation and Security/Quality re-review after remediation.
- No push, PR, merge, release preparation, or HITL approval until fixed and re-reviewed.

Accepted blocker list:

1. Missing explicit Evidence Integrity Validation Gate.
2. Aggregation may proceed over partial evidence due missing count reconciliation.
3. Failure classes not separated: evidence-producing vs evidence-transforming.
4. Endpoint lineage not endpoint-scoped/exact.
5. Same-job/concurrent duplicate handling gaps.
6. Trigger failure lacks durable aggregation lifecycle evidence.

## 4. Evidence Collected

Evidence is inherited from the accepted compliance review:

- **Missing integrity gate:** review cites `validate_eligibility()` in `src/release_confidence_platform/aggregation/eligibility.py`, `list_completed_runs()` in `src/release_confidence_platform/aggregation/repository.py`, and orchestration checks in `src/release_confidence_platform/aggregation/orchestrator.py`; there is no gate comparing `finalization.execution_count` to persisted completed run count or raw evidence count before aggregation.
- **Partial evidence risk:** review states implementation allows aggregation with any non-empty completed run list and any non-empty raw record list in `src/release_confidence_platform/aggregation/orchestrator.py`.
- **Failure classification gap:** review states raw read/schema failures, missing evidence, duplicate refs, storage conflicts, and conditional write failures are recorded under generic `FAILED` or `INELIGIBLE` outcomes rather than durable evidence-producing vs evidence-transforming classifications.
- **Endpoint lineage gap:** review states endpoint aggregate records receive the same audit-wide lineage object rather than endpoint-scoped exact source references.
- **Duplicate/concurrent handling gap:** review states `put_job_once()` occurs before controlled orchestration handling and transaction conflicts do not reload aggregate-set completeness as required by design.
- **Trigger lifecycle gap:** review states `apps/backend/handlers/audit_finalization_handler.py` logs `aggregation_trigger_failed` but does not persist an aggregation lifecycle/job-intent artifact when asynchronous invocation fails.

Referenced evidence artifacts:

- `docs/review/phase_4_architecture_compliance_review.md`
- `docs/product/phase_4_aggregation_layer_product_spec.md`
- `docs/architecture/phase_4_aggregation_layer_technical_design.md`
- `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- `docs/qa/phase_4_aggregation_layer_qa_report.md`
- `docs/release/phase_4_aggregation_layer_release_status_evidence.md`
- `docs/backend/phase_4_aggregation_layer_implementation_report.md`

## 5. Execution Path / Failure Trace

Based on the compliance review, the architectural failure path is:

1. Audit finalization completes and triggers Phase 4 aggregation.
2. Aggregation validates high-level eligibility/finalization metadata.
3. Aggregation loads completed run metadata and raw evidence records.
4. Because no explicit evidence integrity gate reconciles expected finalization execution count against persisted completed runs and raw evidence count, aggregation can continue when loaded evidence is incomplete but non-empty.
5. Aggregate records/manifests may be written and later consumed as valid, despite unresolved evidence completeness, lineage, duplicate/retry, or trigger lifecycle gaps.

For trigger failure specifically:

1. Finalization invokes aggregation asynchronously.
2. If invocation fails, the handler logs `aggregation_trigger_failed`.
3. No durable aggregation job/outcome/intent is persisted, leaving no lifecycle-managed retry or recovery artifact for the completed audit.

## 6. Failure Classification

- **Primary classification:** Contract Mismatch
- **Secondary classification:** Application Bug
- **Severity:** Blocker

Severity rationale: the accepted compliance review states Phase 4 is Non-Compliant / Blocked and must not proceed to implementation continuation, merge, PR, release preparation, release action, or HITL approval until remediation and re-review are complete.

## 7. Root Cause Analysis

**Confidence label:** Confirmed Root Cause for compliance blocker status.

Immediate failure point:

- Architecture compliance review rejected Phase 4 at HITL/release gate.

Underlying root cause:

- Implemented Phase 4 behavior does not fully satisfy approved Phase 4 architecture/product/ADR obligations around evidence integrity validation, completeness reconciliation, lineage exactness, failure classification, duplicate/concurrent idempotency handling, and durable aggregation lifecycle evidence.

Supporting evidence:

- The accepted review explicitly documents `Non-Compliant / Blocked` status and identifies the six accepted blockers listed above.
- The review cites specific implementation files and approved artifacts for each blocker.

Contributing factors:

- QA sign-off occurred before this architecture compliance review identified governance blockers; QA/security/quality evidence must be refreshed after remediation.

## 8. Confidence Level

**High.** The blocker status and remediation direction are directly supported by the accepted architecture compliance review and user directive. No additional runtime reproduction is required to preserve this governance blocker trail.

## 9. Recommended Fix

Remediation routing:

1. **Architect first**
   - Update technical design and ADR as needed for:
     - explicit Evidence Integrity Validation Gate,
     - incomplete-evidence outcome semantics,
     - evidence-producing vs evidence-transforming failure taxonomy,
     - endpoint-scoped exact lineage or approved alternative,
     - duplicate/concurrent retry semantics,
     - durable trigger failure lifecycle/job-intent handling.

2. **Dev-backend after architecture updates**
   - Implement the approved design in the aggregation orchestration/repository/finalization trigger paths.
   - Likely affected areas include:
     - `src/release_confidence_platform/aggregation/orchestrator.py`
     - `src/release_confidence_platform/aggregation/eligibility.py`
     - `src/release_confidence_platform/aggregation/repository.py`
     - `src/release_confidence_platform/aggregation/lineage.py`
     - `apps/backend/handlers/audit_finalization_handler.py`
     - aggregation IAM/infrastructure if durable queue/job-intent or DR semantics change.

3. **QA**
   - Revalidate all blocker-specific behavior and Phase 4 regression coverage after implementation.

4. **Security and Quality reviewers**
   - Re-review after remediation, especially IAM, DR invocation, data exposure/lineage, lifecycle evidence, idempotency, and release-readiness evidence.

Cautions:

- Preserve Phase 4 boundary: no reporting, scoring, AI interpretation, release recommendations, dashboards, or public operator workflow behavior.
- Aggregation must fail closed when evidence integrity cannot be established.
- No push/PR/merge/HITL approval until blockers are fixed and re-reviewed.

## 10. Suggested Validation Steps

Required tests after remediation:

- Execution count mismatch blocks aggregation and creates no aggregate/manifest records.
- Partial evidence blocks aggregation even when completed runs/raw records are non-empty.
- Missing raw evidence blocks aggregation with evidence-producing failure classification.
- Duplicate raw source references block aggregation with durable classification.
- Missing `audit_execution_id` or `config_version` blocks aggregation.
- Evidence-producing failures are durably distinct from evidence-transforming failures.
- Evidence-transforming failures can be retried deterministically without re-running the audit where design allows.
- Endpoint aggregates contain endpoint-scoped exact source lineage, or tests reflect an approved architecture amendment.
- Same `aggregation_job_id` duplicate event is side-effect safe and auditable.
- Concurrent aggregate write conflict reloads aggregate-set completeness and records duplicate/conflict according to design.
- Aggregation trigger invocation failure persists lifecycle evidence, job intent, queue/dead-letter state, or other approved durable recovery artifact.
- Regression tests confirm deterministic aggregation and raw evidence immutability remain intact.

Review gates after tests:

- Updated architecture compliance review.
- Updated QA report/test evidence.
- Security review after any IAM, durable queue, DR, or lineage changes.
- Quality review/release readiness refresh.

## 11. Open Questions / Missing Evidence

- Architect must decide whether endpoint lineage requires endpoint-scoped manifest records or whether an explicit ADR/design amendment can justify audit-wide lineage as exact enough.
- Architect must define canonical aggregate-set completion semantics if remediation changes aggregate record identity or lifecycle model.
- Architect must define durable trigger failure recovery mechanism: persisted job intent, metadata marker, queue/dead-letter, or another reviewed pattern.
- Architect must define whether privileged administrative DR invocation is in Phase 4 scope or explicitly deferred with documented operational consequences.

## 12. Final Investigator Decision

**Ready for developer fix after architecture remediation.**

Further bug investigation is not needed before architecture remediation. The accepted compliance review provides sufficient evidence for design/ADR updates and downstream implementation routing.
