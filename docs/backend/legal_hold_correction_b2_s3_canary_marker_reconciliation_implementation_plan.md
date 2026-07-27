# Implementation Plan

## A1.LH2 — S3 Canary-Marker and Symmetric Reconciliation Foundation

*Formerly identified in the corrective architecture sequence as "Legal-Hold
Correction B2."*

## 1. Feature Overview

Build the S3-side coordination mechanism (the canary marker) for Evidence
Governance Workstream A1's legal-hold mechanism, and wire it together with
A1.LH1's already-merged DynamoDB-authoritative hold state
(`HoldTransitions`/`HoldRepository`) and the already-merged existing-object
sweep (`CustodySweepClient`) via a new, minimal, real internal
`RetentionService` orchestrator. This closes the S3-side race the companion
ADR's Decision 9 identifies: an S3 write that reads hold state before a
`PLACE`/`RELEASE` commits but completes its `PutObject` after the
corresponding sweep has already run.

## 2. Technical Scope

- A narrow marker store/writer component (`marker_store.py`) implementing
  atomic, first-write-wins canary-marker creation (`PutObject` with
  `If-None-Match: "*"`), orphan/conflict recovery via a validated
  `GetObject` read-back, and authoritative `LastModified` capture via a
  dedicated `HeadObject` read-back — never trusting `PutObject`'s own
  response.
- Deterministic marker JSON content and the `_assert_marker_key()`
  structural guard (ADR Non-Negotiable Invariant 20).
- A marker-anchored reconciliation pass, added as new public methods on
  `CustodySweepClient` (reusing its existing allowlisted S3 operations
  only — no new S3 API surface).
- A minimal, real `RetentionService` orchestrator wiring
  `HoldTransitions` → marker establishment → `CustodySweepClient`'s
  existing sweep methods → reconciliation → status confirmation, for both
  `place_legal_hold()` and `release_legal_hold()`.
- A narrowly-scoped `HoldRepository.update_hold_event_marker_fields()`
  method, since `write_hold_event()` is write-once and cannot itself record
  a marker's later confirmation/failure outcome.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` —
  Decision 9, Non-Negotiable Invariants 11–25.
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  — §19 in full (§19.2, §19.3, §19.5.1–19.5.10, §19.6, §19.11, §19.14,
  §19.15).
- Already-merged A1.LH1 code: `hold_transitions.py`, `hold_repository.py`,
  `custody_sweep_client.py`, `models.py`, `constants.py`.
- `docs/backend/legal_hold_correction_b1_authoritative_hold_state_dynamodb_coordination_implementation_report.md`
  (naming/structure convention).

## 4. API Contracts Affected

No API contract changes. `RetentionService` is an internal Python
orchestration class (two public methods, `place_legal_hold`/
`release_legal_hold`), not a CLI command or customer-facing endpoint — no
CLI wiring is included in this subphase.

## 5. Data Models / Storage Affected

- `LegalHoldEvent` (DynamoDB): no schema change (the `marker_s3_key`/
  `marker_status`/`marker_confirmed_last_modified` fields already exist
  from A1.LH1's additive plumbing) — this subphase is the first to *set*
  non-default values for them, via the new
  `update_hold_event_marker_fields()` method.
- `LegalHold` (DynamoDB): same — no schema change, `upsert_hold()`'s
  existing full-overwrite semantics already support persisting
  `marker_s3_key`/`marker_confirmed_last_modified` alongside `sweep_status`.
- New S3 prefix: `retention-markers/{client_id}/{audit_id}/{hold_id}/{hold_version}-{transition}.marker`
  (governance metadata, Category 4 — never one of the four evidence-class
  prefixes, never subject to any evidence-class Lifecycle rule).

## 6. Files Expected to Change

New:
- `src/release_confidence_platform/evidence_retention/marker_store.py`
- `src/release_confidence_platform/evidence_retention/retention_service.py`
- `tests/unit/evidence_retention/test_marker_store.py`
- `tests/unit/evidence_retention/test_retention_service.py`

Modified:
- `src/release_confidence_platform/evidence_retention/constants.py` (new
  marker-related constants)
- `src/release_confidence_platform/evidence_retention/custody_sweep_client.py`
  (new `reconcile_versions()` public method + private helpers; `_ALLOWED_S3_METHODS`
  unchanged)
- `src/release_confidence_platform/evidence_retention/hold_repository.py`
  (new `update_hold_event_marker_fields()` method)
- `tests/unit/evidence_retention/test_custody_sweep_client.py`
- `tests/unit/evidence_retention/test_hold_repository.py`

`infra/resources/s3.yml`: evaluated, not modified — see report §11 for the
flagged contradiction between two sections of this subphase's own task
briefing and the resulting deferral decision.

## 7. Security / Authorization Considerations

- `MarkerStore` gets its own S3 method allowlist (`put_object`/
  `head_object`/`get_object`, scoped logically to the `retention-markers/`
  prefix only) — a second, code-level enforcement layer beyond "the method
  doesn't exist," mirroring `CustodySweepClient`'s own allowlist discipline.
- `CustodySweepClient`'s existing `_ALLOWED_S3_METHODS`/
  `_ALLOWED_DYNAMODB_METHODS` allowlists are verified byte-for-byte
  unchanged — no `put_object`/`head_object`/`delete_object` capability is
  added to that class.
- No new IAM statements — this work is internal/operator-side,
  non-deployed; `infra/serverless.yml`'s `provider.iam.role.statements` is
  untouched.
- No secrets, tokens, or customer operational evidence in the marker
  payload — only `client_id`/`audit_id`/`hold_id`/`hold_version`/
  `transition`, already used as S3 key components elsewhere in this
  codebase.

## 8. Dependencies / Constraints

- botocore 1.43.27 (confirmed installed) supports `IfNoneMatch` on
  `put_object` — no new dependency.
- No new AWS resources requested by this subphase's code (the
  `retention-markers/` Lifecycle rule is evaluated but deferred — see §11
  of the implementation report).

## 9. Assumptions

- `HoldRepository.upsert_hold()`'s existing full-overwrite semantics are
  sufficient for persisting `sweep_status`/marker-field updates on
  `LegalHold` — confirmed by reading the actual code (docstring explicitly
  states "PutItem overwrites any existing record"); no new LegalHold-specific
  update method was added.
- A sweep/reconciliation-phase failure occurring *after* the marker is
  already confirmed leaves `sweep_status = IN_PROGRESS` (the safe,
  always-resumable branch Technical Design §19.6 explicitly permits),
  rather than attempting to positively distinguish a transient AWS failure
  from a non-retriable one — that classification machinery is out of this
  subphase's authorized scope.
- The marker JSON payload uses the field name `transition` (not `action`,
  which Technical Design §19.5.1's own worked example uses) — a
  naming-only, documented choice for consistency with this module's own
  parameter names and the rest of the ADR/Technical Design's prose.

## 10. Validation Plan

- `uv run pytest tests/unit/evidence_retention/ -q` (focused).
- `uv run pytest -q` (full canonical regression suite, no exclusion flags).
- `uv run ruff check` (lint, full repository).
- Explicit assertions that `CustodySweepClient._ALLOWED_S3_METHODS` is
  unchanged and the class still has no `put_object`/`head_object` method.
