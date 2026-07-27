# Test Plan

## A1.LH2 — S3 Canary-Marker and Symmetric Reconciliation Foundation

*Formerly identified in the corrective architecture sequence as "Legal-Hold
Correction B2."*

## 1. Feature Overview

A1.LH2 implements the S3 canary-marker mechanism
and symmetric PLACE/RELEASE reconciliation pass specified in ADR
`adr_evidence_retention_disposal_enforcement.md` Decision 9 (Non-Negotiable
Invariants 15-25) and Technical Design
`evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
§19.5 (marker mechanism), §19.2/§19.3 (PLACE/RELEASE sequences),
§19.6 (sweep/failure-recovery). It builds on the already-merged A1.LH1
(`HoldTransitions`, DynamoDB-authoritative hold state, `hold_version`/
`sweep_status`).

Scope of this subphase: `MarkerStore` (new), `RetentionService` (new, the
end-to-end orchestrator), `CustodySweepClient.reconcile_versions` (new
method on existing class), `HoldRepository.update_hold_event_marker_fields`
(new method on existing class), new `constants.py` values, and a fifth,
untagged S3 Lifecycle rule for the `retention-markers/` prefix
(`infra/resources/s3.yml`/`infra/serverless.yml`). No CLI wiring, no API
surface, no IAM change, no custody-period value supplied — all confirmed
out of scope and verified absent below.

## 2. Acceptance Criteria Mapping

Acceptance criteria are the 16 QA scenarios enumerated in Technical Design
§19.11 items 15-21 (marker-identity/key-collision scenarios) plus §19.5.10
(marker-specific test list), read together with ADR Invariants 15-25, and
the orchestrator's 17-item validation checklist (which folds in one
additional item — allowlist preservation — not separately numbered in
§19.11/§19.5.10 but required by ADR Invariant 10 and Technical Design
§19.5.9). Full mapping is the Requirement-to-Test table in the Test Report,
§2.

## 3. Test Scenarios

1. Atomic first marker creation (`IfNoneMatch="*"`, never check-then-write).
2. Idempotent replay with identical content (resumed attempt, marker already confirmed).
3. Rejection of conflicting existing content (`MarkerIntegrityError`).
4. PLACE/RELEASE marker non-collision, same episode.
5. PLACE → RELEASE → PLACE episodes, three markers, no aliasing.
6. Authoritative `LastModified` via dedicated `HeadObject` read-back.
7. Marker establishment timeout/failure — deterministic error, never silent proceed.
8. Marker status confirmation/failure persisted via `HoldRepository`.
9. Stale re-invocation after marker disposal — no-op through full `RetentionService` orchestration.
10. PLACE reconciliation racing object creation.
11. RELEASE reconciliation racing object creation (independent coverage).
12. Clock-boundary/defense-in-depth buffer behavior (just inside/outside window).
13. Pagination and version handling in the reconciliation pass.
14. Sweep interruption and retry (partial failure, safe resumption).
15. Terminal no-op at the full `RetentionService` orchestration layer.
16. Preservation of `CustodySweepClient`'s method allowlists.
17. Structural absence of unconditioned marker overwrite.

## 4. Edge Cases

- Two genuinely overlapping marker-establishment attempts for the same
  transition (neither may overwrite the other's confirmed timestamp).
- Marker establishment exceeding the wall-clock budget with retry attempts
  still remaining (must still fail closed).
- Wall-clock budget shared across both the `PutObject` and `HeadObject`
  phases (not reset between them).
- A version's `LastModified` exactly at the buffer boundary (just inside
  vs. just outside).
- A prior attempt's `marker_status=FAILED` must be retried; `CONFIRMED` must
  never be re-attempted.
- Reconciliation pass idempotent across two independent runs.
- Sweep failure occurring after marker confirmation must leave
  `sweep_status=IN_PROGRESS`, not `FAILED`.

## 5. Test Types Covered

- **Unit / functional:** `tests/unit/evidence_retention/test_marker_store.py`,
  `test_retention_service.py`, `test_custody_sweep_client.py` (new methods),
  `test_hold_repository.py` (new method).
- **Negative coverage:** structural guard rejection tests
  (`_assert_marker_key`), integrity-error tests, retry-exhaustion tests,
  allowlist-rejection tests.
- **Infrastructure configuration:** `tests/unit/test_infra_configuration.py`
  (Lifecycle rule shape, fail-closed custody-period reference).
- **Static verification:** `ruff check`, `sls print --stage dev` (fail-closed
  proof), diff-based confirmation of allowlist/IAM non-modification.
- **Regression:** full canonical suite (`uv run pytest -q`).

## 6. Coverage Justification

All 16 QA scenarios named in Technical Design §19.11/§19.5.10, plus ADR
Invariants 15-25, map to at least one specifically-named, independently
executed test (see Test Report §2). The orchestration layer
(`RetentionService`) is exercised as a real component (not a test double)
using a real `HoldTransitions` wired to fake `HoldRepository`/`MarkerStore`/
`CustodySweepClient` collaborators — consistent with this codebase's
established collaborator-fake pattern (`test_hold_transitions.py`) and with
Product Strategy's explicit requirement that the orchestrator not be a test
double standing in for production logic. Infrastructure change (Lifecycle
rule) is verified both by dedicated unit tests and by an independent,
directly-executed `sls print` run reproducing the claimed fail-closed error.
