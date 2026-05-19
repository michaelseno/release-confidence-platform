# Implementation Plan

## 1. Feature Overview
Implement the Phase 3 backend-only audit scheduling and lifecycle layer: deterministic lifecycle transitions, EventBridge Scheduler wrapper boundaries, schedule construction, execution/finalization handlers, occurrence deduplication, cancellation, safeguards, taxonomy, and token metadata validation.

## 2. Technical Scope
Add internal Python services and handlers for lifecycle metadata, scheduling, scheduler event validation, duplicate occurrence claims, repeated sequential execution, finalization, rollback, and cancellation. No public API, frontend, analytics/reporting workflow, RBAC, billing, or live AWS deployment is in scope.

This update fixes the QA-reported Phase 3 operational-cap defect by enforcing `max_requests_per_run` for burst schedules at both schedule-time and execution-time guard boundaries, including non-production burst windows.

## 3. Source Inputs
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
- `docs/qa/phase_3_audit_scheduling_lifecycle_test_plan.md`
- `docs/qa/phase_3_audit_scheduling_lifecycle_qa_report.md`
- `docs/release/phase_3_audit_scheduling_lifecycle_issue.md`

## 4. API Contracts Affected
No public API contract changes. Internal function/handler contracts added:
- Schedule audit internal service returns `client_id`, `audit_id`, `lifecycle_state`, `schedule_count`, and audit window.
- Scheduled execution events require Phase 3 schedule metadata and must omit `run_id`.
- Finalization events transition eligible audits to `FINALIZING`, then `FAILED` only for zero executions.
- Cancellation service accepts `client_id`, `audit_id`, and reason.

## 5. Data Models / Storage Affected
- Audit metadata item: `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`.
- Occurrence claim item: `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Existing run metadata item remains `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#RUN#{run_id}`.
- Append-only `lifecycle_history`, retained `schedules`, safe execution counters, finalization, token metadata, and cleanup errors.

## 6. Files Expected to Change
- New `packages/audit_lifecycle/` modules.
- New `packages/audit_scheduling/` modules.
- New `packages/storage/audit_metadata_client.py` and `packages/storage/eventbridge_scheduler_client.py`.
- New scheduled execution and finalization handlers under `apps/backend/handlers/`.
- Phase 3 unit/integration tests.
- Backend implementation plan/report docs.
- For the QA cap fix: `packages/audit_scheduling/validators.py`, `packages/audit_scheduling/safeguards.py`, and `tests/unit/test_phase3_safeguards.py`.

## 7. Security / Authorization Considerations
Phase 3 is internal/IAM-bound only. Validate identifiers before key/log/name use. Reject raw tokens and `run_id` in scheduled events. Persist only sanitized metadata. Enforce production opt-in and production caps before schedule creation and execution. Do not log secrets, raw payloads, or provider details.

## 8. Dependencies / Constraints
No new dependencies. EventBridge Scheduler is accessed only through a mockable wrapper. Tests use mocks/in-memory fakes; no live AWS deployment is performed.

## 9. Assumptions
- Internal services are sufficient because Phase 3 does not define public HTTP APIs.
- Schedule expression summaries are safe metadata and do not persist full target payloads.
- Repeated execution safety uses conservative iteration/request/window/token checks without implementing continuation/chaining.

## 10. Validation Plan
- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m ruff format --check .`
- `.venv/bin/python -m pytest`
- `.venv/bin/python scripts/validate_config.py --samples-dir configs/samples`
- From `infra/`: `npx serverless package --stage dev`, `staging`, `prod`
- From `infra/`: `npx serverless package --stage qa` expected to fail
