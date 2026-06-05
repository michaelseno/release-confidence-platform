# Test Plan

## 1. Feature Overview

Validate the approved Phase 3 finalization/cleanup fixes on branch `bugfix/phase_3_finalization_cleanup_rca` without mutating AWS resources.

Approved scope:
- Set `ActionAfterCompletion="DELETE"` for one-time `at(...)` EventBridge Scheduler schedules only.
- Transition successful finalization from `FINALIZING` to `COMPLETED` through the lifecycle service.
- Add safe `auditFinalization` observability logs.
- Add automated coverage for scheduler auto-delete, successful completion, duplicate idempotency, retry from `FINALIZING`, and zero-execution failure.

Out of scope:
- Phase 4 aggregation.
- `ANALYZING` / `REPORTING` workflow implementation.
- Stale schedule cleanup tooling or live AWS mutation.

## 2. Acceptance Criteria Mapping

| Acceptance criterion | Planned validation |
| --- | --- |
| One-time `at(...)` schedules set `ActionAfterCompletion="DELETE"` | Inspect scheduler wrapper and execute unit tests covering `at(...)` request payloads. |
| Recurring `rate(...)` / `cron(...)` schedules do not set delete-on-completion | Inspect scheduler wrapper and execute recurring-expression unit tests. |
| Successful nonzero finalization transitions to `COMPLETED` via lifecycle service | Inspect finalization handler and execute integration coverage asserting transition history. |
| Duplicate terminal finalization is idempotent | Execute terminal-state duplicate-delivery integration tests. |
| Retry from `FINALIZING` with prior nonzero finalization metadata completes | Execute retry integration test. |
| Zero-execution finalization still fails | Execute zero-execution integration tests. |
| Observability logs are present and do not expose raw payloads/secrets | Inspect log calls and sanitization boundaries; execute tests if present. |
| ADR/docs reflect lifecycle contract change and deferred stale cleanup tooling | Inspect ADR and implementation report. |
| No out-of-scope Phase 4/stale cleanup implementation | Inspect changed implementation areas and searches for Phase 4/stale cleanup behavior. |

## 3. Test Scenarios

1. Scheduler one-time auto-delete request shape.
   - Input: schedule definition with `expression="at(2026-05-30T09:00:00)"`.
   - Expected output: AWS request includes `ActionAfterCompletion="DELETE"`.
   - Validation logic: captured fake scheduler payload assertion.

2. Scheduler recurring expressions remain unchanged.
   - Input: schedule definitions with `rate(15 minutes)` and `cron(0 12 * * ? *)`.
   - Expected output: AWS request omits `ActionAfterCompletion`.
   - Validation logic: captured fake scheduler payload assertion.

3. Successful finalization closeout.
   - Input: audit in `RUNNING` with `execution_counters.total_completed=1`.
   - Expected output: handler response `status=completed`, lifecycle state `COMPLETED`, transition history `FINALIZING -> COMPLETED`.
   - Validation logic: fake repository transition history assertions.

4. Terminal duplicate idempotency.
   - Input: audit already in `COMPLETED`, `FAILED`, or `CANCELLED`.
   - Expected output: handler returns `status=skipped`, no new lifecycle history, existing finalization metadata preserved.
   - Validation logic: fake repository state/history assertions.

5. Retry from `FINALIZING` with prior finalization metadata.
   - Input: audit in `FINALIZING` with `finalization.execution_count=1`.
   - Expected output: lifecycle transitions to `COMPLETED`.
   - Validation logic: fake repository transition assertion.

6. Zero-execution failure path.
   - Input: audit in `RUNNING` or `FINALIZING` with zero finalization executions.
   - Expected output: lifecycle transitions to `FAILED`.
   - Validation logic: fake repository transition assertion.

7. Safe observability logs.
   - Input: finalization events across success, skip, retry, and failure paths.
   - Expected output: structured log fields include identifiers/status/state/reason only; no raw target payloads, secrets, authorization headers, bearer tokens, or credentials.
   - Validation logic: source inspection and targeted automated assertions where available.

## 4. Edge Cases

- Whitespace/case variations of `at(...)` expressions should be treated as one-time schedules by the wrapper boundary.
- `FINALIZING` retry without usable finalization execution metadata should not guess success; it should skip and remain `FINALIZING`.
- Terminal duplicate finalization must not overwrite existing finalization metadata.
- Existing stale EventBridge schedules from previous deployments must not be mutated by this validation.

## 5. Test Types Covered

- Unit tests: scheduler request-shape behavior and recurring expression guardrails.
- Integration tests: finalization lifecycle behavior and idempotency.
- Static/source inspection: architecture scope, safe logging, docs/ADR alignment, absence of out-of-scope stale cleanup tooling.
- Regression tests: targeted Phase 3 suites and full test suite when executable.

## 6. Coverage Justification

The selected coverage maps directly to the approved user scope and Phase 3 architecture guardrails. E2E-style assertions are deterministic and use fake repositories/scheduler clients to validate system-visible lifecycle outcomes without mutating AWS.
