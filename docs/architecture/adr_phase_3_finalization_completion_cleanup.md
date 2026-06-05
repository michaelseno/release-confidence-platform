# ADR: Phase 3 Finalization Completion and One-Time Schedule Cleanup

## Status

Approved for Phase 3 follow-up implementation.

## Context

Phase 3 finalization currently records finalization metadata but leaves successful nonzero audits in `FINALIZING`. EventBridge Scheduler one-time `at(...)` schedules are also retained because schedule creation omits `ActionAfterCompletion`, which causes the provider default of `NONE`.

Phase 4 aggregation, `ANALYZING`, and `REPORTING` workflows remain out of scope for this follow-up.

## Decision

- Allow a direct lifecycle transition from `FINALIZING` to `COMPLETED` for successful Phase 3 finalization with `execution_count > 0`.
- Preserve `FINALIZING -> FAILED` for zero-execution finalization.
- Require the finalization handler to use `AuditLifecycleService.transition(...)` for both success and failure closeout.
- Configure EventBridge Scheduler `ActionAfterCompletion="DELETE"` only for one-time `at(...)` schedule expressions at the scheduler wrapper boundary.
- Treat stale schedule cleanup tooling for previously created schedules as deferred operator tooling and do not include it in this Phase 3 fix.

## Consequences

- Phase 3 audits can reach terminal success without invoking Phase 4 analysis or reporting behavior.
- New one-time schedules self-delete after successful EventBridge Scheduler completion; recurring `rate(...)` and `cron(...)` expressions are not changed.
- Existing stale schedules are not remediated by this change and require separately approved cleanup tooling.
