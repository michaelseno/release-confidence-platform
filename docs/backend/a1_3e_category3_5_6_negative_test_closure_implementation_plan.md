# Implementation Plan

## 1. Feature Overview

Close the last remaining gap in Evidence Governance Workstream A1.3's
cross-cutting write-path integration effort (subphase A1.3e, issue #95):
negative regression-test coverage proving that Category 3 (operational
coordination metadata) and Category 5/6 (configuration artifacts /
explicitly-excluded audit-anchor records) write paths never receive
custody/legal-hold governance fields, per Technical Design §18.1 (six-category
classification) and §18.3 ("Structural Exclusion — Enforceable in Code, Not
Convention"). This is a test-only change; it adds regression coverage
proving an already-verified absence stays true, it does not fix anything.

## 2. Technical Scope

- 22 new tests covering `AuditMetadataRepository`'s 11 write methods
  (Category 6: `AuditMetadata`, items 4a-4g; Category 3:
  `AggregationJobIntent`/`ScheduleOccurrenceClaim`, items 4h-4k), across
  both independently-maintained trees (`packages/storage/audit_metadata_client.py`,
  `src/release_confidence_platform/storage/audit_metadata_client.py`).
- 6 new tests covering `AggregationRepository`'s `put_job_once` (Category
  3), `put_audit_execution_identity_once` (Category 6), and an extension of
  the already-merged `update_job` denylist guard's regression proof
  (§18.7) from its existing 2-element check to the full 4-element
  governance-field set, over the same 4 real caller field sets
  `test_update_job_custody_guard.py` already derived from
  `aggregation/orchestrator.py`.
- 2 new tests covering `S3StorageClient.write_json` (Category 5,
  `configs/*` artifacts, §18.6), proving `write_json` never emits the
  `rcp-legal-hold`/`rcp-evidence-class` S3 object tags, for both the
  create (`overwrite=False`) and force-overwrite (`overwrite=True`) paths.

No production, configuration, application, or infrastructure code is
touched by this task.

## 3. Source Inputs

- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  §18.1 (six-category classification), §18.3 (structural exclusion /
  test-level enforcement rationale), §18.5 (dual-tree hazard), §18.6
  (Category 5 scope boundary), §18.7 (`update_job` denylist guard), §18.9
  (this negative-test-coverage list).
- `tests/unit/aggregation/test_update_job_custody_guard.py` — reference
  pattern for the recording-double style and the real caller field-set
  fixture, reused via cross-module import.
- `tests/unit/test_packages_src_divergence.py::TestAuditMetadataRepositoryEquivalence`
  — reference import style for the dual-tree `AuditMetadataRepository`
  test coverage.
- `src/release_confidence_platform/storage/audit_metadata_client.py`,
  `packages/storage/audit_metadata_client.py`,
  `src/release_confidence_platform/aggregation/repository.py`,
  `src/release_confidence_platform/storage/s3_client.py`,
  `packages/storage/s3_client.py` — read in full to determine each write
  method's exact request shape.
- `docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_plan.md`/`_report.md`
  — format/structure reference for this pass's own docs.

## 4. API Contracts Affected

No API contract changes. This task adds tests only; no production method
signature, return shape, or externally-visible behavior changes.

## 5. Data Models / Storage Affected

No data model or storage changes. This task verifies, via tests, that the
following existing write paths continue to never persist
`custody_expires_at`/`ttl_disposal_at`/`evidence_class`/`hold_version`
(DynamoDB) or `rcp-legal-hold`/`rcp-evidence-class` (S3 object tags):

- `AuditMetadataRepository.put_audit_metadata_once`,
  `update_for_force_recreate`, `append_lifecycle_transition`,
  `set_schedules`, `update_execution_counters`, `record_finalization`,
  `record_cleanup_errors` (Category 6, both trees).
- `AuditMetadataRepository.put_aggregation_job_intent_once`,
  `update_aggregation_job_intent`, `claim_occurrence`, `update_occurrence`
  (Category 3, both trees).
- `AggregationRepository.put_job_once` (Category 3),
  `put_audit_execution_identity_once` (Category 6), `update_job` (Category
  3, extending the existing runtime guard's own regression proof).
- `S3StorageClient.write_json` (Category 5, `configs/*`).

## 6. Files Expected to Change

New (2):
- `tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py`
- `tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py`

Modified (1):
- `tests/unit/test_backend_s3_storage_client.py`

Documentation, new (2, this pass):
- `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_plan.md`
- `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_report.md`

## 7. Security / Authorization Considerations

No authentication/authorization surface is touched. This task's security
relevance is narrow and specific: it is the regression enforcement
mechanism for the precondition `CustodySweepClient`'s existing
allowlist-free sweep design depends on (§18.3) — that Category 3/5/6
records structurally never carry `ttl_disposal_at`/`custody_expires_at`.
No test weakens, works around, or masks a production security control; per
the task's mandatory stop condition, any discovered violation of that
precondition would halt implementation and require escalation rather than
being fixed or the assertion weakened. No such violation was found.

## 8. Dependencies / Constraints

- No new third-party dependency.
- Reuses `urllib.parse` (standard library, already imported elsewhere in
  the test suite) for parsing `Tagging` query-string kwargs in the S3
  tests.
- Reuses the already-merged `_REAL_UPDATE_JOB_CALL_FIELD_SETS` fixture from
  `test_update_job_custody_guard.py` via cross-module import (verified
  working under this repo's `pyproject.toml`
  `[tool.pytest.ini_options] pythonpath = ["src", "."]` configuration),
  with a locally-defined fallback copy guarded by `try/except ImportError`
  in case that import path is ever disrupted by an unrelated change.

## 9. Assumptions

None requiring escalation. All argument shapes passed to each method under
test were derived directly from reading each method's own source (exact
required keys, e.g. `update_for_force_recreate`'s dependency on
`item["force_history_entry"]`/`item["lifecycle_state"]`/`item["updated_at"]`),
not guessed. Minor implementation-detail choices, documented here rather
than escalated because none changes external behavior or test intent:

- File 1 (`AuditMetadataRepository`) uses `pytest.mark.parametrize` over
  `[PkgRepo, SrcRepo]` rather than duplicating each test body, per the
  task's own "parametrize or duplicate" latitude — this keeps each of the
  11 covered methods' assertion logic defined exactly once.
- `append_lifecycle_transition`'s assertion checks
  `ExpressionAttributeValues` keys (not `ExpressionAttributeNames`, which
  this method never constructs at all — its `UpdateExpression` is entirely
  hardcoded) exactly as directed by the task brief.
- File 2's per-file test count is 6, not the task brief's initially-floated
  "aim for 5" — the task brief explicitly authorized reporting the true,
  honestly-derived count rather than forcing the arithmetic; the item-7
  extension is parametrized across all 4 real caller field sets (not
  collapsed to fewer), consistent with "extends ... across all 4 real
  field sets."

## 10. Validation Plan

- `uv run pytest -q tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py`
- `uv run pytest -q tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py`
- `uv run pytest -q tests/unit/test_backend_s3_storage_client.py`
- `uv run pytest -q tests/unit/aggregation/test_update_job_custody_guard.py tests/unit/reliability_intelligence/test_hold_coordination.py tests/unit/deterministic_reporting/test_repository.py tests/unit/audit_platform_integrity/test_repository.py tests/unit/audit_platform_integrity/test_engine.py`
- `uv run pytest --collect-only -q`
- `uv run pytest -q` (full suite)
- `uv run ruff check` / `uv run ruff format --check` on the 3 touched files
- `git diff --check main`, `git status --short`, `git diff --stat main`
- `git diff main -- src/ | packages/ | apps/ | config/custody_periods.json | infra/`
  — all five must be empty (the hard scope boundary of this task).
