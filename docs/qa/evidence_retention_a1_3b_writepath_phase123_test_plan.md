# Test Plan

## 1. Feature Overview

Workstream A1.3b implements the first execution subphase of Evidence
Governance Workstream A (GitHub Issue #95): Category 1/2 write-path
integration for Phase 1/2/3 raw execution evidence, per the governed
Technical Design §18 amendment (`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`)
and companion ADR (`docs/architecture/adr_evidence_retention_disposal_enforcement.md`,
Decision 8, Non-Negotiable Invariants 3/8/9).

Scope (TD §18.9, items 1/2/3 + §18.7 guard):

1. `packages/storage/dynamodb_client.py::put_started_once` — `RunMetadata`
   CREATE computes `custody_expires_at`/`ttl_disposal_at` independently, at
   write time, from `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE`, failing closed
   (`StorageError("CUSTODY_PERIOD_CONFIG_MISSING")`) when unresolvable.
2. `update_terminal` (`RunMetadata` FINALIZATION) never references either
   field — RunMetadata has no regeneration path (TD §18.1/§18.4 not
   applicable).
3. `packages/storage/s3_client.py::write_raw_results_once` tags raw-evidence
   S3 objects `rcp-legal-hold=false`/`rcp-evidence-class=raw_evidence`.
4. `src/release_confidence_platform/aggregation/repository.py::update_job`
   gains a two-item denylist guard (TD §18.7) rejecting
   `ttl_disposal_at`/`custody_expires_at` before its `UpdateExpression` is
   built.

Two deployment preconditions are explicitly out of this subphase's scope and
already dispositioned by Product Strategy / documented as blocking-before-deploy
(not defects to fix in this pass): (a) `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` is
not wired into any Lambda environment, so `put_started_once` fails closed on
every real invocation today; (b) `infra/serverless.yml`'s `package.patterns`
does not include `src/release_confidence_platform/evidence_retention/**`,
which the modified production files now import from transitively.

## 2. Acceptance Criteria Mapping

| Source | Requirement | Test(s) |
|---|---|---|
| TD §18.1 Category 2 | `custody_expires_at`/`ttl_disposal_at` computed independently at write time, not copied from sibling S3 write | `test_put_started_once_sets_custody_fields_from_env_config`, `test_custody_expires_at_is_not_hardcoded_and_scales_with_configured_days` |
| ADR Invariant 3 | No hardcoded custody-period duration | `test_custody_expires_at_is_not_hardcoded_and_scales_with_configured_days`; static grep for numeric literals |
| Implicit fail-closed requirement (Product Strategy decision, this subphase) | `put_started_once` raises `StorageError("CUSTODY_PERIOD_CONFIG_MISSING")` when config unresolvable, write never attempted | `test_put_started_once_fails_closed_when_custody_period_env_var_unset`, `test_put_started_once_fails_closed_for_invalid_custody_period_values` (parametrized: empty/zero/negative/non-numeric/float) |
| Implementer's claim (item 1) | Caller's original `item` dict is never mutated in place | `test_put_started_once_does_not_mutate_caller_supplied_item` |
| TD §18.1 / §18.4 (RunMetadata has no regen path) | `update_terminal` never sets, recomputes, or removes either field | `test_update_terminal_never_touches_custody_fields` (asserts on actual `ExpressionAttributeNames`, not just stored-value equality) |
| ADR Decision 2 | Raw-evidence S3 objects tagged `rcp-legal-hold=false`, `rcp-evidence-class=raw_evidence` at `PutObject` time | `test_write_raw_results_once_tags_object_legal_hold_false_and_raw_evidence_class`, `test_write_raw_results_once_evidence_class_tag_is_fixed_regardless_of_key` |
| Regression | Tagging addition does not disturb existing `PutObject` shape | `test_write_raw_results_once_preserves_existing_content_type_and_body` |
| TD §18.7 | `update_job` rejects `ttl_disposal_at`/`custody_expires_at`, individually and together, pre-write | `test_update_job_rejects_retention_governed_fields[*]`, `test_update_job_rejects_when_both_retention_governed_fields_present`, `test_update_job_guard_raises_before_any_dynamodb_call` |
| TD §18.7 | Guard does not false-positive on any real `update_job` caller | `test_update_job_does_not_raise_for_real_caller_field_sets[*]` against the 4 real field sets traced from `aggregation/orchestrator.py` |
| Scope containment | No file outside authorized A1.3b scope touched | `git diff main --stat` / `git status` review |
| Deployment-precondition documentation | Both known gaps documented, not glossed over | Manual review of implementation report §9/§11 against `infra/serverless.yml` ground truth |

## 3. Test Scenarios

- Positive: custody fields present, correctly typed (epoch seconds), and
  equal to each other on ordinary CREATE.
- Positive: fields scale proportionally with a different configured
  custody-period value (proves independent computation, not a fixed
  constant).
- Positive: S3 tag key/value pairs exactly match ADR Decision 2's vocabulary.
- Negative: `put_started_once` with unset/empty/zero/negative/non-numeric env
  var — must raise `StorageError` with `error_type ==
  "CUSTODY_PERIOD_CONFIG_MISSING"` and the underlying `put_item` must never
  be invoked.
- Negative: `update_job` with either or both denylisted fields — must raise
  `AssertionError` before any DynamoDB call.
- Regression: `update_job`'s 4 real caller field sets (traced directly from
  `aggregation/orchestrator.py`) must not raise.
- Regression: full existing suite (1517 pre-existing tests) must continue to
  pass under the new fail-closed default.

## 4. Edge Cases

- Custody-period env var set to `"0"`, `"-5"`, `"3.5"`, `""`, and a
  non-numeric string — all must fail closed identically.
- `update_terminal` called with a full realistic `updates` dict
  (status/completed_at/raw_result_s3_key/failure_summary) after a prior
  `put_started_once` — custody fields must survive untouched, verified via
  the actual DynamoDB `UpdateExpression` attribute names, not just stored
  value equality (guards against a false pass where the field is set to the
  same value it already had).
- S3 tagging correctness verified independent of key/payload content (tag
  value must not vary per-call).
- `update_job` guard must reject on partial overlap (one forbidden field
  present alongside legitimate fields) and full overlap (both forbidden
  fields).

## 5. Test Types Covered

- Functional (unit): `tests/unit/test_run_metadata_custody_fields.py`,
  `tests/unit/test_raw_evidence_s3_tagging.py`,
  `tests/unit/aggregation/test_update_job_custody_guard.py`.
- Negative coverage: fail-closed paths, guard rejection paths.
- Regression: full suite (`uv run pytest -q`), plus 6 pre-existing test
  files' `put_object` fakes updated to accept the new `Tagging` kwarg.
- Static/lint: `ruff check` on all four modified production files.
- Static scope/architecture conformance: `git diff`/`git status` scope audit,
  grep for hardcoded duration literals, manual trace of every live
  `update_job` call site against the denylist.
- Documentation-accuracy validation: implementation report cross-checked
  against `infra/serverless.yml` ground truth for both flagged deployment
  preconditions.

## 6. Coverage Justification

Coverage is scoped exactly to TD §18.9's A1.3b authorization (items 1, 2, 3
+ the `update_job` guard) — no Category 3/5/6 negative-test coverage or
Phase 4/5/6/7 regeneration-rule work is in scope for this subphase (deferred
to A1.3c/A1.3d/A1.3e per §18.9's sequencing) and none was implemented,
consistent with authorized scope. The fail-closed operational consequence
(every real invocation fails today) is a known, Product-Strategy-accepted
deployment precondition for this subphase, not a defect under test here;
QA's obligation is limited to confirming the code implements fail-closed
correctly and that the precondition is documented, per explicit QA dispatch
instructions.
