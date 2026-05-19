# GitHub Issue

## 1. Feature Name

Phase 3 Audit Scheduling Lifecycle

## 2. Problem Summary

The platform can execute individual audit runs and generate deterministic payload-backed evidence, but it does not yet support bounded recurring audits with deterministic lifecycle state management. Operators currently lack baseline cadence, burst stability checks, repeated sequential execution, automatic audit-window finalization, production-safe execution restrictions, and duplicate scheduler-delivery protection.

Phase 3 introduces a backend-only, AWS-native audit scheduling and lifecycle layer that coordinates recurring operational reliability execution while preserving Phase 1 orchestrator/run contracts and Phase 2 payload/data-generation controls.

## 3. Linked Planning Documents

- Product Spec: `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
- Technical Design: `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- QA Test Plan: `docs/qa/phase_3_audit_scheduling_lifecycle_test_plan.md`
- UI/UX Spec: Not applicable. Phase 3 is backend-only; no frontend/dashboard implementation is in scope.

## 4. Scope Summary

### In scope

- Audit lifecycle states: `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Strict lifecycle transition validation and controlled errors for invalid transitions.
- Append-only `lifecycle_history` and schedule metadata persisted for audit traceability.
- EventBridge Scheduler integration for baseline, burst, repeated, and one-time finalization schedules.
- Baseline execution defaulting to every 15 minutes during the audit window.
- MVP audit window default and maximum of 48 hours.
- Deterministic EventBridge schedule naming: `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}` for execution schedules and `rcp-{stage}-{client_id}-{audit_id}-finalization` for finalization.
- Safe schedule-name truncation with deterministic hash suffix when AWS length limits require it.
- Scheduled execution payloads that omit `run_id`; accepted scheduled occurrences generate new `run_id` values through the existing Phase 1 orchestrator boundary.
- Occurrence idempotency using `schedule_occurrence_id` and DynamoDB occurrence claims before outbound execution.
- DynamoDB key shapes:
  - Audit metadata: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`
  - Occurrence claim: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`
  - Run metadata: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`
- Scenario taxonomy and reliability category grouping for operational reliability dimensions.
- Operational caps, production-safe caps, environment restrictions, audit expiration handling, and temporary token expiration checks.
- Schedule creation rollback to `FAILED` when required schedule creation fails.
- Cancellation cleanup that transitions to `CANCELLED` and records sanitized `cleanup_errors` when cleanup fails.
- Finalization boundary behavior, including `FINALIZING -> FAILED` when zero executions exist.
- Unit and integration test coverage with mocked EventBridge Scheduler, DynamoDB, S3, Secrets, and Phase 1/2 boundaries.

### Out of scope

- Frontend/dashboard implementation.
- Public customer-facing APIs, config authoring UI, or self-service schedule management UI.
- User authentication, RBAC, billing, subscriptions, tenant onboarding, or account management.
- AI insights, reliability scoring, analytics, report generation, or dashboards beyond finalization boundary metadata.
- Automatic Phase 3 transition from `FINALIZING` to `ANALYZING`, from `ANALYZING` to `REPORTING`, or from `REPORTING` to `COMPLETED`.
- Load testing, stress testing, uptime-monitor clone behavior, synthetic monitoring product features, or chaos engineering.
- Heavy API frameworks.
- Replacing or weakening Phase 1 raw result schema v1, orchestrator/runner behavior, S3/DynamoDB/Secrets wrappers, sanitization, run ID validation, or duplicate run ID protection.
- Replacing or weakening Phase 2 payload strategies, duplicate controls, payload fingerprints, or endpoint safety controls.
- Long-lived client credentials or broad client-level execution permissions.

## 5. Implementation Notes

### Frontend expectations

- No frontend work is expected in Phase 3.
- No dashboard, UI state, public API integration, or customer-facing schedule management interface is required.
- Future dashboards may read lifecycle state, lifecycle history, schedule metadata, and finalization metadata, but Phase 3 must not implement UI behavior.

### Backend expectations

- Implement centralized lifecycle state machine and transition service with the approved state list and transition map.
- Persist lifecycle metadata atomically, including current `lifecycle_state`, append-only `lifecycle_history`, `schedules`, finalization metadata, and sanitized cleanup/failure metadata.
- Implement EventBridge Scheduler wrapper boundaries for create/delete/disable/get operations and normalize provider errors into sanitized project errors.
- Implement schedule builders for baseline, burst, repeated, and finalization schedules using deterministic names and deterministic hash-suffix truncation.
- Build minimal scheduler target payloads with safe metadata only; scheduled execution events must include `schedule_occurrence_id` and must omit `run_id`.
- Claim each scheduled occurrence in DynamoDB before lifecycle mutation, execution counters, or Phase 1 orchestrator invocation.
- Skip duplicate EventBridge deliveries when the occurrence claim already exists; do not create a duplicate run or send outbound requests.
- Preserve Phase 1 run ID generation, validation, duplicate protection, raw schema v1, storage wrappers, and sanitization.
- Preserve Phase 2 payload strategy validation, duplicate payload controls, fingerprints, and endpoint safety controls.
- Validate default caps: `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, `max_audit_window_hours = 48`.
- Validate production caps and restrictions: `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, `prod_requires_explicit_allow_production = true`; block production scheduling/execution unless `allow_production_execution = true`.
- Roll back already-created schedules where possible and transition audit to `FAILED` if required schedule creation fails; never persist `SCHEDULED_WITH_ERRORS`.
- On cancellation, delete or disable associated schedules, retain schedule metadata, transition to `CANCELLED`, and record sanitized `cleanup_errors` for cleanup failures.
- Finalization with one or more executions records finalization metadata and leaves the audit in `FINALIZING`.
- Finalization with zero executions records finalization metadata and transitions `FINALIZING -> FAILED`.
- `ANALYZING`, `REPORTING`, and `COMPLETED` are future valid transitions only; Phase 3 handlers must not execute analytics/reporting/scoring workflows or auto-transition into them.

### Dependencies or blockers

- Requires mocked/local test coverage for EventBridge Scheduler, DynamoDB, S3/Secrets, and Phase 1/2 orchestrator boundaries.
- Requires implementation to preserve existing Phase 1 and Phase 2 contracts without bypassing run ID validation, duplicate run ID protection, sanitization, storage wrappers, or payload controls.
- Requires controlled IAM/deployment role assumptions for EventBridge Scheduler in real environments, though live AWS resources are not required for the planned QA gate.
- No remote GitHub issue is required by the current repo workflow for this planning artifact.

## 6. QA Section

### Planned test coverage

- Unit tests for lifecycle state validation, transition table enforcement, append-only lifecycle history, schedule naming/truncation, schedule builders, event contracts, safeguards, token metadata, taxonomy/category mapping, occurrence claims, cancellation, rollback, and finalization behavior.
- Integration tests with mocked EventBridge Scheduler and DynamoDB for full scheduling lifecycle, scheduled execution, duplicate delivery, cancellation, finalization, rollback, and Phase 1/2 regression boundaries.
- Security/sanitization assertions confirming no raw tokens, secrets, raw payloads, PII, cookies/session headers, authorization headers, unsanitized AWS provider exceptions, unsafe scheduler payloads, or scheduler-created `run_id` values are persisted or logged.
- Regression tests proving Phase 1/2 orchestrator, generated run IDs, run metadata key shape, payload controls, endpoint safety, fingerprints, and sanitization remain authoritative.

### Acceptance criteria mapping

- Lifecycle validation and append-only history: AC-001 through AC-003.
- Audit window and baseline defaults: AC-004, AC-005, AC-005A.
- Scheduler creation, rollback, metadata, and naming: AC-006 through AC-006E.
- Minimal scheduler payloads, omitted `run_id`, and generated Phase 1 run IDs: AC-007 through AC-008.
- Occurrence claims and duplicate delivery suppression: AC-008A through AC-008C.
- Burst/repeated caps, metadata, timezone handling, and sequential execution: AC-009 through AC-012B.
- Finalization boundaries and future-only transitions: AC-013 through AC-013B.
- Expiration, taxonomy, reliability mapping, environment restrictions, production safety, and temporary token handling: AC-014 through AC-018.
- Terminal-state protection and Phase 1/2 preservation: AC-019, AC-020.
- Cancellation cleanup and cleanup failure recording: AC-021, AC-021A.
- No `SCHEDULED_WITH_ERRORS` persistence: AC-022.

### Key edge cases

- Invalid lifecycle state or invalid transition from terminal state.
- Existing lifecycle history remains append-only during new transitions.
- Audit window omitted defaults to 48 hours; audit window greater than 48 hours is rejected.
- EventBridge schedule name exceeds AWS length limit and requires deterministic hash suffix.
- Two long schedule names share the same truncated prefix and must remain distinct via hash suffix.
- Scheduled execution event contains `run_id` and must be rejected before occurrence claim or orchestrator invocation.
- Missing or duplicate `schedule_occurrence_id` handling.
- DynamoDB occurrence claim failure blocks execution before outbound requests.
- Duplicate EventBridge delivery skips execution and logs sanitized duplicate metadata only.
- Burst timezone interpretation, UTC default, invalid burst window, and cap violations.
- Repeated execution exceeds iteration cap or safe runtime/request/token/audit-window estimate.
- Repeated execution must not create chained/follow-up/continuation schedules.
- Production target without explicit allow is blocked at scheduling and execution time.
- Production-safe caps remain enforced even when production execution is explicitly allowed.
- Token expires before or during the audit window; affected executions are blocked without leaking raw token values.
- Partial schedule creation failure triggers rollback and `FAILED` without `SCHEDULED_WITH_ERRORS`.
- Cancellation cleanup fails for one or more schedules but audit still transitions to `CANCELLED` with sanitized `cleanup_errors`.
- Finalization duplicate is no-op when already `FINALIZING` or terminal.
- Finalization with executions remains `FINALIZING`; finalization with zero executions becomes `FAILED`.
- Future states `ANALYZING`, `REPORTING`, and `COMPLETED` exist only in state machine definitions for Phase 3.

### Test types expected

- Unit: Yes.
- Integration: Yes, with mocked AWS dependencies and mocked Phase 1/2 boundaries.
- Backend handler/function contract tests: Yes.
- Security/sanitization tests: Yes.
- Regression tests: Yes, focused on Phase 1/2 contract preservation.
- UI tests: No, frontend is out of scope.
- Performance/load tests: No, explicit load testing is out of scope; caps and repeated-execution safety are validated through deterministic safeguards.

## 7. Risks / Open Questions

- EventBridge Scheduler provider behavior for delete/disable and retry semantics must be normalized behind a wrapper and validated with mocks; live AWS behavior may require later operational verification.
- Deterministic schedule-name truncation must choose a stable hash strategy with acceptable collision tolerance.
- Repeated execution safety estimates must be conservative enough to avoid runtime timeout/chaining pressure.
- Concurrent cancellation and scheduler delivery must be guarded so cancelled or terminal audits cannot restart execution.
- Token validity shorter than the audit window may cause later occurrences to be skipped; this must be represented safely and treated as an operator-visible risk.
- IAM permissions for scheduler invocation and schedule cleanup must be restricted by deployment role/name prefix outside the code-level test scope.
- No frontend/UI exists in Phase 3, so operator interaction depends on backend tooling/internal invocation patterns until a future phase.

## 8. Definition of Done

- Product, technical design, QA plan, and release issue documents are present and aligned.
- Backend implementation supports approved lifecycle states and transition map.
- All accepted lifecycle transitions append to `lifecycle_history` without mutating prior entries.
- EventBridge Scheduler integration supports baseline, burst, repeated, and finalization schedules.
- Schedule names are deterministic and safely truncated with deterministic hash suffix when needed.
- Scheduled execution events omit `run_id`; accepted occurrences use Phase 1-generated run IDs.
- `schedule_occurrence_id` occurrence claims prevent duplicate scheduler deliveries from producing duplicate runs.
- DynamoDB audit metadata, occurrence claim, and run metadata key shapes match the approved contract.
- Default caps, production caps, production allow requirements, audit-window limits, environment restrictions, and token expiration checks are enforced at scheduling and execution time.
- Schedule creation failure rolls back created schedules where possible and transitions to `FAILED` without `SCHEDULED_WITH_ERRORS`.
- Cancellation transitions to `CANCELLED`, retains schedule metadata, and records sanitized `cleanup_errors` when cleanup fails.
- Finalization with executions remains in `FINALIZING`; zero-execution finalization transitions to `FAILED`.
- Phase 3 does not perform analytics, reporting, scoring, dashboard updates, or auto-transitions to `ANALYZING`, `REPORTING`, or `COMPLETED`.
- Phase 1 and Phase 2 contracts remain preserved.
- Required unit, integration, security, and regression tests pass with documented QA evidence.
- QA sign-off is granted only after all critical lifecycle, scheduling, duplicate-delivery, rollback, cancellation, finalization, production-safety, and sanitization paths pass.
