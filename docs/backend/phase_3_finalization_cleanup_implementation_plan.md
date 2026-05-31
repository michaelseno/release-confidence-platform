# Implementation Plan

## 1. Feature Overview
Implement approved Phase 3 finalization cleanup fixes: one-time schedule auto-delete, successful finalization completion, safe auditFinalization observability logs, and targeted regression coverage.

## 2. Technical Scope
- Set EventBridge Scheduler `ActionAfterCompletion="DELETE"` only for one-time `at(...)` schedule expressions.
- Update lifecycle transition constants to allow direct `FINALIZING -> COMPLETED` while preserving `FINALIZING -> FAILED`.
- Update audit finalization handler to complete nonzero finalizations through `AuditLifecycleService.transition(...)` and preserve zero-execution failure behavior.
- Preserve idempotent skips for terminal states and complete retried `FINALIZING` audits when prior finalization metadata shows a nonzero execution count.
- Add safe structured auditFinalization logs.

## 3. Source Inputs
- `docs/bugs/phase_3_finalization_cleanup_bug_report.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- User-approved architecture guardrails in the implementation request.
- Existing handler, lifecycle, scheduler wrapper, and test patterns.

## 4. API Contracts Affected
No public API contract changes. Internal Lambda handler response status changes from `finalizing` to `completed` for successful nonzero finalization.

## 5. Data Models / Storage Affected
No schema changes. Existing audit metadata `lifecycle_state`, `lifecycle_history`, and `finalization` fields are updated using existing repository methods.

## 6. Files Expected to Change
- `apps/backend/handlers/audit_finalization_handler.py`
- `packages/audit_lifecycle/constants.py`
- `src/release_confidence_platform/audit_lifecycle/constants.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- Targeted unit/integration tests.
- Architecture decision documentation under `docs/architecture/`.

## 7. Security / Authorization Considerations
No new AWS permissions or mutations outside existing runtime schedule creation. Logs use sanitized structured fields only and avoid raw target payloads, credentials, request/response bodies, tokens, and unsanitized provider errors.

## 8. Dependencies / Constraints
No new dependencies. Do not implement Phase 4 aggregation, `ANALYZING`, `REPORTING`, or stale schedule cleanup tooling. Do not mutate AWS.

## 9. Assumptions
- Mirrored `packages/` and `src/release_confidence_platform/` modules should remain synchronized for lifecycle constants and scheduler wrapper behavior.
- Existing lifecycle transition service remains the authoritative validation boundary.

## 10. Validation Plan
- Run targeted scheduler wrapper and finalization tests with `pytest`.
- Run broader related Phase 3 tests if feasible.
