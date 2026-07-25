# Test Report

## 1. Execution Summary

- Total tests (new, this subphase): 21
- Passed: 21
- Failed: 0
- Full suite (post-change): 1538 passed, 2 skipped (pre-existing skips,
  unrelated to this change)
- Full suite (pre-change baseline, per implementation report, independently
  consistent with 1538 - 21 = 1517): 1517 passed, 2 skipped

## 2. Detailed Results

New test files, executed independently by QA (`.venv/bin/python -m pytest
tests/unit/test_run_metadata_custody_fields.py
tests/unit/test_raw_evidence_s3_tagging.py
tests/unit/aggregation/test_update_job_custody_guard.py -v`):

```
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_sets_custody_fields_from_env_config PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_does_not_mutate_caller_supplied_item PASSED
tests/unit/test_run_metadata_custody_fields.py::test_custody_expires_at_is_not_hardcoded_and_scales_with_configured_days PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_when_custody_period_env_var_unset PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_for_invalid_custody_period_values[] PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_for_invalid_custody_period_values[0] PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_for_invalid_custody_period_values[-5] PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_for_invalid_custody_period_values[not-a-number] PASSED
tests/unit/test_run_metadata_custody_fields.py::test_put_started_once_fails_closed_for_invalid_custody_period_values[3.5] PASSED
tests/unit/test_run_metadata_custody_fields.py::test_update_terminal_never_touches_custody_fields PASSED
tests/unit/test_raw_evidence_s3_tagging.py::test_write_raw_results_once_tags_object_legal_hold_false_and_raw_evidence_class PASSED
tests/unit/test_raw_evidence_s3_tagging.py::test_write_raw_results_once_evidence_class_tag_is_fixed_regardless_of_key PASSED
tests/unit/test_raw_evidence_s3_tagging.py::test_write_raw_results_once_preserves_existing_content_type_and_body PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_rejects_retention_governed_fields[ttl_disposal_at] PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_rejects_retention_governed_fields[custody_expires_at] PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_rejects_when_both_retention_governed_fields_present PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_guard_raises_before_any_dynamodb_call PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_does_not_raise_for_real_caller_field_sets[updates0] PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_does_not_raise_for_real_caller_field_sets[updates1] PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_does_not_raise_for_real_caller_field_sets[updates2] PASSED
tests/unit/aggregation/test_update_job_custody_guard.py::test_update_job_does_not_raise_for_real_caller_field_sets[updates3] PASSED

============================== 21 passed in 0.18s ==============================
```

Full suite (`.venv/bin/python -m pytest -q`):

```
........................................................................ [  4%]
........................................................................ [  9%]
........................................................................ [ 14%]
........................................................................ [ 18%]
........................................................................ [ 23%]
........................................................................ [ 28%]
........................................................................ [ 32%]
........................................................................ [ 37%]
........................................................................ [ 42%]
........................................................................ [ 46%]
........................................................................ [ 51%]
........................................................................ [ 56%]
...............................................................s.s...... [ 60%]
........................................................................ [ 65%]
........................................................................ [ 70%]
........................................................................ [ 74%]
........................................................................ [ 79%]
........................................................................ [ 84%]
........................................................................ [ 88%]
........................................................................ [ 93%]
............................                                             [100%]
1538 passed, 2 skipped in 2.71s
```

Lint (`.venv/bin/python -m ruff check` on all four modified production files
plus new/updated test files):

```
All checks passed!
```

## 3. Failed Tests

None.

## 4. Failure Classification

Not applicable — no failures observed.

## 5. Observations

### Code correctness (independently verified, not implementer-trusted)

- `packages/storage/dynamodb_client.py::put_started_once` (lines 103–123):
  confirmed `item_with_custody = {**item, **_run_metadata_custody_fields()}`
  is a new dict — the caller's `item` is never mutated. Verified both by
  direct read and by `test_put_started_once_does_not_mutate_caller_supplied_item`.
- `_resolve_custody_period_days_env` (lines 40–67): reads
  `os.environ.get(env_var)` fresh on every call, requires a positive
  integer, raises `StorageError("CUSTODY_PERIOD_CONFIG_MISSING")` on
  unset/empty/non-numeric/zero/negative — confirmed by 5 parametrized
  negative-value cases plus the unset-var case, all asserting `put_item` was
  never invoked.
- `update_terminal` (lines 125–149): read the full method body — no
  reference to `custody_expires_at`/`ttl_disposal_at` anywhere. Confirmed
  further by `test_update_terminal_never_touches_custody_fields`, which
  inspects the actual `ExpressionAttributeNames` sent to `update_item`
  rather than only checking stored-value equality (a stronger assertion —
  it would fail even if the method set the field to a value identical to
  what it already had).
- `packages/storage/s3_client.py::write_raw_results_once` (line ~119): the
  `Tagging=_RAW_EVIDENCE_TAGGING` kwarg is applied at the actual
  `put_object` call site, not merely constructed and discarded. Confirmed by
  direct read and by `test_write_raw_results_once_tags_object_legal_hold_false_and_raw_evidence_class`.
- `src/release_confidence_platform/aggregation/repository.py::update_job`
  (lines 27–39, 83–90): guard raises `AssertionError` on
  `ttl_disposal_at`/`custody_expires_at`, individually and together, before
  any `UpdateExpression` construction (`_call` is never reached — confirmed
  via a `dynamodb_client=None` repository instance that would otherwise blow
  up with `AttributeError`, not `AssertionError`, if the guard did not
  short-circuit first).

### `update_job` call-site trace (independently performed, not trusted from implementer's list)

Traced every live call site in
`src/release_confidence_platform/aggregation/orchestrator.py` directly via
grep (4 call sites: lines 114, 144, 363, 752). Field sets used:

1. `status, started_at, reason_code, failure_category`
2. `audit_execution_id, config_version`
3. `status, reason_code, failure_category, completed_at, source_run_count, source_raw_result_count, error_summary`
4. `status, reason_code, failure_category, completed_at, source_run_count, source_raw_result_count, aggregate_record_count, lineage_manifest_ref, aggregate_set_ref`

None of the 4 call sites' field sets intersect the denylist
(`ttl_disposal_at`, `custody_expires_at`). No repo-wide caller of
`update_job` exists outside `orchestrator.py` (confirmed by a repo-wide
grep). The guard does not false-positive on any real caller.

### No hardcoded duration (independently verified)

Grepped `packages/storage/dynamodb_client.py` for numeric literals in the
custody-computation path. The only numeric literal present is
`_SECONDS_PER_DAY = 86400`, a unit-conversion constant (seconds per day),
not a duration value — consistent with ADR Non-Negotiable Invariant 3 ("The
custody-period duration must never be hardcoded in application code"). The
actual duration is read exclusively from `os.environ`.

### Minor, non-blocking observations (not defects)

- `packages/storage/s3_client.py`'s hardcoded `"raw_evidence"` string
  literal for `EVIDENCE_CLASS_TAG_KEY`'s value duplicates, rather than
  references, the `"raw_evidence"` member already present in
  `evidence_retention/constants.py::EVIDENCE_CLASSES`. Not a defect (both
  values are identical and the TD confirms `write_raw_results_once` is the
  sole call site for this evidence class), but a future subphase touching
  this constant could consider sourcing it from `EVIDENCE_CLASSES` for a
  single source of truth. No action required for A1.3b sign-off.
- The module-level comment in `dynamodb_client.py` (line 23) references
  `custody_period_days.raw_evidence.${stage}` (TD §18.1's notation for the
  serverless-config source), while the actual env var name consumed is
  `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` (no stage suffix). This is consistent
  with standard serverless deployment practice — the stage dimension is
  baked into which value gets deployed to which stage's Lambda environment,
  not into the variable name itself — and matches FR-A1-3's own language
  ("consumed by ... Lambda environment variables at write time"). Not a
  defect.

### Flakiness

None observed — new tests are deterministic (env var control via
`monkeypatch`, in-memory stubs, no wall-clock-sensitive assertions beyond a
bounded `before`/`after` window in
`test_put_started_once_sets_custody_fields_from_env_config`, which is a
standard and low-risk pattern already used elsewhere in this suite).

## 6. Regression Check

- Full suite: 1538 passed, 2 skipped — zero regressions against the
  pre-change baseline of 1517 passed, 2 skipped (21 new tests account
  exactly for the delta).
- 6 pre-existing test files
  (`tests/unit/test_phase1_core_engine.py`,
  `tests/integration/test_phase1_orchestrator_integration.py`,
  `tests/integration/test_phase2_orchestrator_payloads.py`,
  `tests/integration/test_phase4a7_aggregation_envelope_compatibility.py`,
  `tests/api/test_audit_run_orchestrator_observability.py`,
  `tests/security/test_phase1_qa_contracts.py`) were modified only to add a
  `Tagging=None` parameter to fixed-signature `put_object` test doubles —
  confirmed via `git diff` that no assertion or fixture data changed in any
  of these files.
- `tests/conftest.py` (new, autouse fixture) defaults
  `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE=90` for the whole suite so ~1500
  pre-existing tests that exercise `put_started_once` indirectly continue to
  pass under the new fail-closed requirement. Confirmed the fixture is
  explicitly documented as a test-only placeholder with no product meaning,
  and that tests needing the fail-closed path itself override it via
  `monkeypatch.delenv`/`monkeypatch.setenv`.

## 7. Scope, Hardcoding, and Documentation Verification (explicit confirmation per QA dispatch)

**7. Scope containment — CONFIRMED.** `git diff main --stat` / `git status`
show only: 3 authorized production files
(`packages/storage/dynamodb_client.py`, `packages/storage/s3_client.py`,
`src/release_confidence_platform/aggregation/repository.py`), 3 new unit
test files, 1 new `tests/conftest.py`, 6 pre-existing test files with a
mechanical `Tagging=None` fixture accommodation, and 2 new docs under
`docs/backend/`. No Phase 4/5/6/7 write path was touched beyond the
authorized `update_job` guard. No `RetentionService`/CLI/Lambda-handler code
was touched. No file under `evidence_retention/` was modified (confirmed —
only imported from, via `from release_confidence_platform.evidence_retention.constants
import ...`). `src/release_confidence_platform/storage/{dynamodb_client,s3_client}.py`
(the confirmed dead-tree copies) were not touched.

**8. No hardcoded duration value — CONFIRMED.** The only numeric literal in
the custody-computation code path is `_SECONDS_PER_DAY = 86400`, a
unit-conversion constant, not a duration. The duration value is read
exclusively from `os.environ.get("CUSTODY_PERIOD_DAYS_RAW_EVIDENCE")` at
call time, with no fallback/default.

**9. Deployment preconditions documented — CONFIRMED.** Both flagged gaps
are explicitly and honestly documented in
`docs/backend/evidence_retention_a1_3b_writepath_phase123_implementation_report.md`
(§1 summary, §9 Assumptions, §11 Known Limitations):

- The `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` env var is not wired into any
  Lambda's environment (`infra/serverless.yml`'s `provider.environment`
  block was independently inspected by QA and confirmed to have no such
  entry), so `put_started_once` fails closed on every real invocation today.
  Report explicitly states this "needs an explicit decision before merge."
- `infra/serverless.yml`'s `package.patterns` (independently inspected by
  QA, lines 117–137) does not include
  `src/release_confidence_platform/evidence_retention/**`, which the
  modified production files now import from transitively — confirmed a real
  `ModuleNotFoundError`-at-cold-start risk if deployed as-is, and confirmed
  accurately described in the report as blocking-before-deploy, not fixed
  in this subphase (correctly out of scope, per authorized A1.3b scope
  which is code-only).

Both are treated by this QA pass as documented deployment preconditions per
explicit dispatch instruction, not as defects — they do not affect the
PASS verdict below.

## 8. QA Decision

All 21 new tests pass, the full 1538-test suite passes with zero
regressions, `ruff check` is clean on all modified files, the code
independently and correctly implements TD §18.1/§18.4/§18.7 and ADR
Non-Negotiable Invariants 3/8/9 for RunMetadata CREATE, RunMetadata
FINALIZATION (no-op), S3 raw-evidence tagging, and the `update_job`
denylist guard. Scope containment, no-hardcoded-duration, and
deployment-precondition documentation are all independently confirmed. No
concrete defects were found. The two flagged operational gaps (custody
config unwired; Lambda packaging gap) are pre-accepted, out-of-scope
deployment preconditions per Product Strategy direction, correctly
documented, and are not blocking for this subphase's own PASS/FAIL
determination.

[QA SIGN-OFF APPROVED]
