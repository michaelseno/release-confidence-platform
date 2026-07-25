# Implementation Plan

## 0. Correction Addendum (2026-07-25, GitHub Issue #95)

Product Strategy authorized a narrow correction to this plan's original §8
statement that leaving `infra/serverless.yml` unmodified, including the
Lambda-packaging gap it created, was "out of authorized scope." That
framing is superseded: §8 below is updated in place with a pointer to this
addendum. The correction adds exactly one line to `infra/serverless.yml`'s
global `package.patterns` list
(`'../src/release_confidence_platform/evidence_retention/**'`) plus one new
static test in `tests/unit/test_infra_configuration.py`. It does not touch
the custody-period-value gap (§9's fail-closed/env-var-wiring assumptions,
still correctly unresolved and unauthorized) or any of this plan's
originally-authorized production files. See the implementation report's §0
for the full traced per-Lambda justification and verification evidence.

## 1. Feature Overview

Workstream A1.3b (GitHub Issue #95, first subphase): Category 1/2 write-path
integration for Phase 1/2/3 raw execution evidence, plus the
`AggregationRepository.update_job` retention-governed-field denylist guard.
This is the first code (not infrastructure) subphase since the Technical
Design's §18 governed-record-boundary amendment — it adds
`custody_expires_at`/`ttl_disposal_at` to `RunMetadata` CREATE writes and
`rcp-legal-hold`/`rcp-evidence-class` S3 tags to raw-evidence writes, without
touching `RunMetadata`'s FINALIZATION path or any Phase 4–7 write path.

## 2. Technical Scope

- Item 1 (TD §11 row 1): `packages/storage/dynamodb_client.py::DynamoDBMetadataClient.put_started_once`
  — add `custody_expires_at`/`ttl_disposal_at` to the RunMetadata CREATE
  item, computed independently at write time from
  `custody_period_days.raw_evidence.${stage}` (TD §18.1 Category 2
  clarification).
- Item 2 (TD §11 row 2): `update_terminal` — verify and document that this
  FINALIZATION method never touches either field (RunMetadata has no
  regeneration path).
- Item 3 (TD §11 row 3): `packages/storage/s3_client.py::S3StorageClient.write_raw_results_once`
  — add `rcp-legal-hold=false` / `rcp-evidence-class=raw_evidence` S3 object
  tags at `PutObject` time (TD §18.1 Category 1, ADR Decision 2).
- TD §18.7 guard: `AggregationRepository.update_job` two-item denylist
  (`ttl_disposal_at`, `custody_expires_at`) raising `AssertionError`,
  verified against `_complete_job`'s and other callers' real field sets in
  `aggregation/orchestrator.py`.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
  (Decision 8, Non-Negotiable Invariants 8–10).
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  §18 (governed-record boundary, structural exclusion, regeneration
  semantics, `update_job` guard, revised sequencing) and §11 (verified
  write-path inventory).
- Already-merged `evidence_retention/` package (`constants.py`, read-only
  reference for reusable field/tag constants).
- Task dispatch instructions from the orchestrator (execution authorization
  for exactly items 1/2/3 + the §18.7 guard; explicit constraints on infra
  and out-of-tree changes).

## 4. API Contracts Affected

No API contract changes. No CLI command, HTTP endpoint, or Lambda handler
signature changes.

## 5. Data Models / Storage Affected

- `RunMetadata` (DynamoDB, `MetadataTable`): additive fields
  `custody_expires_at`, `ttl_disposal_at` on CREATE only (`put_started_once`).
  `update_terminal` (FINALIZATION) unaffected.
- Raw evidence S3 objects (`raw-results/{client_id}/{audit_id}/{run_id}/results.json`):
  additive object tags `rcp-legal-hold`, `rcp-evidence-class` at `PutObject`
  time.
- `AggregationJob` (DynamoDB): no field change; `update_job` gains a
  pre-write rejection guard only.

## 6. Files Expected to Change

- `packages/storage/dynamodb_client.py`
- `packages/storage/s3_client.py`
- `src/release_confidence_platform/aggregation/repository.py`
- New/updated unit tests for the above (see §10).
- `tests/conftest.py` (new — see §9 for why this was necessary and out of
  the two-file authorized production scope).

## 7. Security / Authorization Considerations

- No new external attack surface; no auth/authz change.
- Custody-period configuration is read from environment, never hardcoded
  (ADR Non-Negotiable Invariant 3).
- `sanitize()` is not applied to the custody fields or S3 tag values before
  persistence (consistent with `adr_sanitization_boundary.md` — these are
  not client-controlled free text).
- `AggregationRepository.update_job`'s new guard is a defense-in-depth,
  programming-error guard (`AssertionError`), not a security boundary,
  mirroring `_assert_phase7_sk`/`_assert_retention_sk`/`_assert_disposal_sk`.

## 8. Dependencies / Constraints

- No new third-party dependency.
- New intra-repo dependency: `packages/storage/{dynamodb_client,s3_client}.py`
  now import `release_confidence_platform.evidence_retention.constants` —
  reusing already-defined `TTL_DISPOSAL_AT_ATTRIBUTE`,
  `CUSTODY_EXPIRES_AT_ATTRIBUTE`, `LEGAL_HOLD_TAG_KEY`,
  `LEGAL_HOLD_TAG_VALUE_FALSE`, `EVIDENCE_CLASS_TAG_KEY` per the dispatch
  instructions, rather than redefining equivalents.
- `custody_period_days.raw_evidence.${stage}` remains unset in
  `infra/serverless.yml`; this remains unauthorized and unchanged. See
  implementation report §9/§11 for the resulting operational gap.
- **Superseded by the §0 correction addendum above**: the original text here
  stated that no infra file was modified and that the Lambda-packaging gap
  this cross-tree import exposed was out of authorized scope. A subsequent,
  narrowly-authorized correction added
  `'../src/release_confidence_platform/evidence_retention/**'` to
  `infra/serverless.yml`'s `package.patterns` to close that specific gap —
  see implementation report §0 for the traced per-Lambda justification. The
  custody-period-value gap above is unaffected and remains open.

## 9. Assumptions

## Assumptions Made

- **Fail-closed scope.** The dispatch instructions explicitly required
  `put_started_once` to fail closed (raise, not silently omit the fields)
  when `custody_period_days` is unresolvable, citing "local/test invocation
  with no config" as an example. Implemented literally. This is a real,
  significant behavior change with production blast radius — flagged as a
  deviation requiring confirmation in the implementation report, not
  silently softened.
- **Env var name.** `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` was chosen as the
  Lambda-environment-variable name mapping to
  `custom.custodyPeriodDays.raw_evidence.${stage}`; no existing naming
  convention covers this specific config key, and no infra change was made
  to actually wire it (out of scope) — this is a forward-declared
  consumption point.
- **`tests/conftest.py` addition.** Not one of the two authorized production
  files, but necessary to keep ~1500 pre-existing tests green under the new
  fail-closed requirement without touching production handler/orchestrator
  files (also out of scope). Flagged for explicit review.

## 10. Validation Plan

- `uv run pytest -q` — full existing suite plus new tests, confirm zero
  regressions.
- `uv run ruff check` on all changed files.
- New unit tests: `tests/unit/test_run_metadata_custody_fields.py`,
  `tests/unit/test_raw_evidence_s3_tagging.py`,
  `tests/unit/aggregation/test_update_job_custody_guard.py`.
