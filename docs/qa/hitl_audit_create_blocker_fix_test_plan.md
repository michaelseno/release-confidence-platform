# Test Plan

## 1. Feature Overview

QA validation for the HITL blocker fix on branch `bugfix/scheduled_execution_orchestration_rca`. The fix addresses `audit create --force` blocking during active/non-eligible lifecycle states and `audit list` returning DynamoDB child records (`#RUN#`, `#OCCURRENCE#`, unknown child suffixes) as duplicate/minimal audits.

## 2. Acceptance Criteria Mapping

| AC | Requirement | Planned Evidence |
|---|---|---|
| 1 | `audit list` returns exactly one canonical audit row when partition includes `RUN`, `OCCURRENCE`, and unknown child rows. | Unit/API discovery tests covering positive canonical sort-key filtering. |
| 2 | `audit list` pagination remains correct when child rows appear before/around canonical rows. | Repository pagination test validating follow-up query via `ExclusiveStartKey` and canonical-only returned items. |
| 3 | `FORCE_RECREATE_BLOCKED` guidance clearly states allowed states (`DRAFT`/`FAILED`) and safe Phase 3 recovery via fresh audit ID/config bundle. | Result rendering unit test assertions. |
| 4 | Force recreate still succeeds only from `DRAFT`/`FAILED` and remains blocked for `FINALIZING` and other ineligible states. | Audit creation service unit tests for allowed and blocked lifecycle states. |
| 5 | Nonzero finalization remains `FINALIZING`. | Phase 3 cancellation/finalization integration regression test. |
| 6 | Zero-execution finalization still transitions to `FAILED`. | Phase 3 cancellation/finalization integration regression test. |
| 7 | Duplicate finalization delivery remains idempotent/skipped. | Phase 3 duplicate delivery integration regression test. |
| 8 | Original scheduled execution fix remains passing: distinct occurrence IDs, duplicate skip, orchestrator call, logs, cleanup/cancel, CLI behavior. | Phase 3 scheduled execution, duplicate delivery, cancellation/finalization, scheduling lifecycle, and CLI regression tests. |

## 3. Test Scenarios

1. **Canonical audit list filtering**
   - Purpose: Verify list output excludes child records and unknown future suffixes.
   - Input: Partition with `AUDIT#audit1`, `AUDIT#audit1#RUN#run1`, `AUDIT#audit1#OCCURRENCE#1`, `AUDIT#audit1#UNKNOWN#child1`.
   - Expected output: one item with `audit_id=audit1`; no child records.
   - Validation logic: assert returned items exactly match canonical row.

2. **Pagination across non-canonical records**
   - Purpose: Verify canonical filtering does not stop on first DynamoDB page containing only children.
   - Input: first page with child rows and `LastEvaluatedKey`, second page with canonical row plus unknown child.
   - Expected output: canonical row returned, repository performs second query using encoded `ExclusiveStartKey`.
   - Validation logic: assert two query calls and canonical-only result.

3. **Force recreate guidance**
   - Purpose: Verify operator error message is actionable and safe.
   - Input: render `FORCE_RECREATE_BLOCKED` error for `audit create`.
   - Expected output: message includes DRAFT/FAILED, `audit list`, fresh audit ID/config bundle, and DynamoDB mutation warning.
   - Validation logic: string assertions.

4. **Force recreate lifecycle guard**
   - Purpose: Verify lifecycle semantics are preserved.
   - Input: force create attempts from DRAFT, FAILED, FINALIZING, SCHEDULED, RUNNING, COMPLETED.
   - Expected output: DRAFT/FAILED succeed; ineligible states fail before repository/S3 mutation.
   - Validation logic: success result or `FORCE_RECREATE_BLOCKED` with no mutation side effects.

5. **Finalization regressions**
   - Purpose: Verify Phase 3 finalization semantics remain unchanged.
   - Input: finalization event with nonzero and zero executions; duplicate delivery fixture.
   - Expected output: nonzero remains FINALIZING; zero transitions FINALIZING -> FAILED; duplicates skipped/idempotent.
   - Validation logic: lifecycle state/history assertions.

6. **Scheduled execution RCA regressions**
   - Purpose: Verify original scheduling orchestration fix remains passing.
   - Input: Phase 3 scheduled execution and CLI regression fixtures.
   - Expected output: distinct occurrence IDs, duplicate skip, orchestrator invoked, logs present, cleanup/cancel behavior unchanged.
   - Validation logic: integration and unit assertions in existing regression tests.

## 4. Edge Cases

- Unknown future child sort-key suffixes must be excluded through positive canonical shape matching.
- Child-only first query pages must not produce empty final results when later pages contain canonical rows.
- Force recreate must not mutate S3 or repository state for blocked lifecycle states.
- FINALIZING must remain ineligible for force recreate even when operator uses `--force`.

## 5. Test Types Covered

- Unit tests: discovery service, metadata repository, result rendering, audit creation lifecycle guards.
- API/contract tests: operator CLI discovery contract.
- Integration tests: Phase 3 scheduled execution, duplicate delivery, cancellation/finalization, scheduling lifecycle.
- Regression tests: original scheduled execution RCA coverage and force recreate lifecycle protections.

## 6. Coverage Justification

The planned suite maps every acceptance criterion to existing automated regression tests and source-level inspection points. The highest-risk behavior is DynamoDB listing with mixed canonical/child rows, so coverage includes both service-level filtering and repository pagination behavior. Lifecycle semantics are covered through audit creation service and Phase 3 integration tests.
