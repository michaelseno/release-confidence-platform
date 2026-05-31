# Technical Design

## 1. Feature Overview

Phase 3 adds a backend-only audit scheduling and lifecycle layer on top of the merged Phase 1 execution engine and Phase 2 payload controls. It introduces deterministic audit lifecycle state management, EventBridge Scheduler-backed baseline/burst/repeated execution triggers, a one-time finalization trigger at audit-window completion, scenario taxonomy validation, operational caps, production restrictions, audit expiration handling, cancellation cleanup, temporary-token reference validation, and confirmed DynamoDB key shapes for audit metadata, occurrence claims, and run metadata.

**Scheduled execution occurrence identity update:** ADR `docs/architecture/adr_scheduled_execution_occurrence_identity.md` supersedes the original recurring baseline `rate(...)` shape. Baseline scheduling must now create bounded discrete `at(...)` occurrence schedules inside the audit window. `schedule_occurrence_id` identifies an intended occurrence, not a recurring schedule definition.

This design is scoped to branch `feature/phase_3_audit_scheduling_lifecycle` and is based on `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`. Phase 3 must not replace Phase 1 orchestrator/runner behavior or Phase 2 payload behavior; scheduled events are another invocation source for the existing execution contract.

## 2. Product Requirements Summary

Phase 3 must provide:

- Lifecycle states: `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Strict transition validation using the approved transition map.
- Append-only lifecycle history plus schedule metadata persisted in DynamoDB under the audit-level item key `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- EventBridge Scheduler integration for `baseline`, `burst`, `repeated`, and `finalization` schedule types.
- Deterministic schedule naming using `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}` and `rcp-{stage}-{client_id}-{audit_id}-finalization`, with deterministic hash suffix truncation when AWS limits require it.
- Baseline cadence defaulting to every 15 minutes during an audit window, implemented as bounded discrete `at(...)` occurrence schedules rather than a recurring `rate(...)` schedule.
- MVP audit window default and maximum of 48 hours.
- Burst windows configured under `burst_schedule.windows[]` with audit-timezone interpretation when provided, otherwise UTC.
- Repeated sequential executions with configurable iteration counts, subject to caps; Phase 3 validates estimated execution limits and fails scheduling when unsafe rather than creating chained/follow-up executions.
- Finalization event at audit-window completion, with zero-execution handling: `FINALIZING` then `FAILED`.
- Approved scenario taxonomy and reliability category mapping.
- Operational safeguards: request caps, concurrency caps, burst caps, repeated iteration caps, environment restrictions, production-safe limits, audit expiration handling, and temporary token expiration checks.
- Production block when `target_environment = "production"` and `allow_production_execution != true`.
- Schedule creation failure rollback where possible, then audit `FAILED`; no `SCHEDULED_WITH_ERRORS` state.
- Cancellation cleanup by deleting/disabling schedules, transition to `CANCELLED`, retention of schedule metadata, and recording of `cleanup_errors` when cleanup fails.
- Duplicate EventBridge deliveries handled by `schedule_occurrence_id` in scheduled payloads and DynamoDB occurrence claims before orchestrator invocation. Scheduler execution events must omit `run_id`; each accepted occurrence creates a new execution result set with a new Phase 1-generated `run_id`.
- Temporary token handling by reference only; raw token values must never be persisted, logged, or embedded in scheduler payloads.
- Local/test validation with mocked EventBridge Scheduler, DynamoDB, S3, and Secrets as needed.

## 3. Requirement-to-Architecture Mapping

| Product Requirement / Decision | Technical Design Response |
| --- | --- |
| FR-001, FR-002, AC-001 through AC-003 | Add a centralized lifecycle state machine service with approved states and transition table. Persist transition and history atomically. |
| FR-003, AC-002A, AC-006B, final key-shape confirmation | Store audit metadata items at `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}` with `lifecycle_state`, append-only `lifecycle_history`, and `schedules` metadata. Use conditional DynamoDB updates to avoid invalid partial updates. |
| FR-004, AC-005, AC-005A, AC-014 | Add audit window validation, default 48-hour window, max 48-hour cap, and execution-time expiration guard. |
| FR-005, AC-006, AC-007 | Add EventBridge Scheduler wrapper and schedule builder for minimal, secret-free target events. |
| FR-006 | Build baseline schedule occurrences with default 15-minute interval and bounded execution by audit-window checks; per ADR `adr_scheduled_execution_occurrence_identity`, each intended occurrence is a discrete `at(...)` schedule with its own deterministic occurrence ID. |
| FR-007, AC-009, AC-010 | Validate burst windows, request count, and concurrency against non-production or production caps before schedule creation and execution. |
| Confirmed burst config | Accept burst configuration as `burst_schedule.enabled` plus `burst_schedule.windows[]`; interpret `start_time` in audit timezone when supplied, otherwise UTC. |
| FR-008, AC-011, AC-012, confirmed repeated limit policy | Build repeated schedule events that invoke a sequential repeated execution wrapper; reject iteration counts above cap and reject schedules whose estimated runtime/request limits are unsafe. Do not create chained/follow-up executions in Phase 3. |
| FR-009, AC-013, AC-013A, confirmed finalization policy | Create one-time finalization schedule at audit-window end; with executions present, transition only to `FINALIZING` and record metadata. With zero executions, transition `FINALIZING -> FAILED`. Do not auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED`. |
| FR-010, FR-011, AC-015, AC-016 | Add taxonomy constants and reliability category mapping with fail-fast validation for unknown values. |
| FR-012, FR-018, AC-008, AC-020, final scheduler event confirmation | Scheduler execution events invoke Phase 1 orchestrator contract while omitting `run_id`; Phase 1 generates a fresh run ID for each accepted occurrence. Preserve Phase 1 run ID validation, duplicate run ID protection, raw schema v1, sanitization, and Phase 2 payload controls for generated/returned run metadata. |
| FR-013, FR-014, AC-009A, AC-009B, AC-017A, AC-017B | Add shared safeguard validator used both during schedule creation and immediately before outbound execution. |
| FR-015, AC-019 | Block recurring executions for expired, terminal, or cancelled audits. Finalize eligible expired audits. |
| FR-016, AC-021 | Cancellation service deletes or disables all associated schedules, records cleanup status, and then transitions to `CANCELLED` when valid. |
| FR-017, AC-018 | Store temporary token metadata by reference and expiration only; execution is blocked if expired. |
| Confirmed schedule failure policy | Schedule creation is all-or-fail. Partial success triggers rollback attempts, controlled failure metadata, and lifecycle transition to `FAILED`. |
| Confirmed duplicate delivery policy | Include `schedule_occurrence_id` in each scheduled event, claim the occurrence in DynamoDB using `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` and a conditional write, and skip/log sanitized duplicate deliveries. The ID represents the intended occurrence time and schedule context, not the schedule definition. |

## 4. Technical Scope

### Current Technical Scope

Phase 3 implementation includes:

- Backend lifecycle state constants, transition validator, transition service, and audit metadata persistence helpers.
- Audit scheduling service that validates configuration and creates EventBridge Scheduler schedules.
- EventBridge Scheduler wrapper boundary for `create_schedule`, `delete_schedule`, `disable_schedule`, and schedule metadata normalization.
- Schedule builders for baseline, burst, repeated, and finalization schedule types.
- Scheduler target handlers for scheduled execution and finalization events.
- Execution guard that loads audit metadata before invoking the existing Phase 1 orchestrator.
- DynamoDB-backed schedule occurrence claims for duplicate EventBridge delivery suppression.
- Sequential repeated execution coordinator that invokes the existing orchestrator one iteration at a time.
- Scenario taxonomy and reliability category mapping constants.
- Operational cap/environment/expiration/token validators used at schedule-time and execution-time.
- Cancellation and schedule rollback services.
- Local/unit/integration tests using mocked AWS dependencies.

### Out of Scope

Phase 3 must not implement:

- Frontend/dashboard/config authoring UI.
- Public customer-facing APIs or self-service schedule management UI.
- User authentication, RBAC, billing, subscriptions, tenant onboarding, or account management.
- AI insights, reliability scoring, analytics, report generation, or dashboard updates beyond recording/emitting the finalization boundary.
- Load testing, stress testing, uptime-monitor clone behavior, continuous synthetic monitoring product features, or chaos engineering.
- Heavy API frameworks.
- Changes that weaken Phase 1 raw result schema v1, S3/DynamoDB/Secrets wrappers, sanitization, strict `run_id` validation, or duplicate run ID protection.
- Changes that replace Phase 2 payload strategies, duplicate controls, payload fingerprints, or endpoint safety controls.
- Long-lived client credentials or broad client-level execution permissions.
- Chained/follow-up executions to continue repeated schedules across handler/runtime limits.
- Analytics/reporting workflows or automatic transitions to `ANALYZING`, `REPORTING`, or `COMPLETED`.

### Future Technical Considerations

- UI for creating/cancelling audits and viewing lifecycle history.
- Downstream analysis from `FINALIZING` to `ANALYZING`.
- Reporting from `ANALYZING` to `REPORTING` to `COMPLETED`.
- Reliability scoring and analytics over scenario category metadata.
- Cross-audit/tenant-wide global concurrency governance.
- Schedule repair tooling for interrupted deployments or operator-initiated reconciliation.

## 5. Architecture Overview

### Runtime Scheduling Flow

1. A backend caller submits or constructs a scheduled audit configuration. Phase 3 does not define a public API/UI for this; implementation may expose an internal function/handler for tests and operator tooling.
2. `AuditSchedulingService` validates identifiers, lifecycle state, audit window, schedule configuration, scenario taxonomy, temporary token metadata, environment restrictions, and operational caps.
3. If the audit is new, metadata is initialized in DynamoDB with `lifecycle_state = DRAFT`, an empty or seed lifecycle history, audit window metadata, safeguard config, token metadata, and no created schedules.
4. Schedule builders construct deterministic schedule definitions and minimal target payloads for applicable baseline, burst, repeated, and finalization schedules. Baseline builders enumerate each intended occurrence in the audit window and emit one `at(...)` schedule per occurrence. Schedule names use the confirmed `rcp-{stage}-...` convention and only apply safe truncation with deterministic hash suffix when AWS length limits require it; for discrete baseline occurrences, the occurrence time must participate in the name/hash input.
5. EventBridge Scheduler wrapper creates schedules. Created schedule metadata is accumulated in memory and persisted only as sanitized metadata.
6. If all required schedules are created, lifecycle transitions `DRAFT -> SCHEDULED`, appending a history entry and schedule metadata.
7. If any required schedule fails to create, rollback attempts are made for already-created schedules. Cleanup outcomes are recorded, and the audit transitions to `FAILED`; no `SCHEDULED_WITH_ERRORS` state exists.

### Scheduled Execution Flow

1. EventBridge Scheduler invokes the Phase 3 scheduled execution handler with a minimal target event.
2. Handler validates target event shape and identifiers before using them in logs, DynamoDB keys, or orchestrator events.
3. Handler loads audit metadata from DynamoDB.
4. Handler claims `schedule_occurrence_id` in DynamoDB using `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` before lifecycle mutations, counter updates, or orchestrator invocation. A successful claim proceeds; an existing claim is skipped and logged as a sanitized duplicate delivery event.
5. Execution guard rejects terminal/cancelled audits, expired audits, production without explicit allow, cap violations, unknown scenario/category, and expired token references before outbound requests. If a claimed occurrence is later blocked by safeguards, update only safe occurrence/audit counters as skipped or failed.
6. If current state is `SCHEDULED`, handler attempts `SCHEDULED -> RUNNING`. If already `RUNNING`, the event may continue only when it is within caps and schedule type semantics allow it. Terminal states never transition back.
7. For `baseline` and `burst`, handler creates a Phase 1 orchestrator event with `client_id`, `audit_id`, `scenario_type`, and `triggered_by = "eventbridge_scheduler"`. The scheduler event and the derived orchestrator event must omit `run_id`; Phase 1 generates a new `run_id` for each accepted scheduled occurrence.
8. For `repeated`, the repeated coordinator invokes the orchestrator sequentially for each configured iteration. The next iteration starts only after the previous orchestrator invocation completes. Each accepted orchestrator invocation omits caller-supplied `run_id`.
9. Run metadata remains under Phase 1 DynamoDB run keys. Audit-level metadata may increment safe execution counters and record schedule occurrence metadata without raw results or secrets.

### Baseline Occurrence Scheduling Update

- Do not create recurring baseline `rate(...)` schedules for the current fix.
- Enumerate intended baseline occurrence times from `audit_window.start_time` using `interval_minutes` until the audit execution boundary. Occurrences must be inside the audit window and must not rely on Lambda wall-clock bucketing.
- Each occurrence uses `expression = at(<scheduled_at formatted for EventBridge Scheduler>)` and a target payload whose `scheduled_at` is the canonical intended UTC occurrence time.
- Each occurrence has a deterministic `schedule_occurrence_id` over `{client_id, audit_id, schedule_type, scenario_type, scheduled_at_iso}` or a deterministic hash of those canonical fields if the clear-text value is too long.
- EventBridge duplicate delivery/retry of the same occurrence reuses the same target payload and must skip through the existing conditional occurrence claim.
- Distinct baseline occurrence schedules must never share `schedule_occurrence_id`, even when schedule names are truncated.
- Manual `rcp audit run` and Phase 1 run ID generation remain unchanged.

### Finalization Flow

1. EventBridge Scheduler invokes finalization handler at `audit_window.end_time`.
2. Handler loads audit metadata and attempts transition to `FINALIZING` when current state is `SCHEDULED` or `RUNNING`.
3. If one or more executions exist, handler transitions to `FINALIZING` and records finalization boundary metadata: trigger time, execution count, zero-execution flag `false`, source `eventbridge_scheduler`, and finalization schedule metadata.
4. If recorded execution count is zero, handler transitions to `FINALIZING`, records zero-execution metadata, then transitions `FINALIZING -> FAILED` with reason `zero_executions_at_finalization`.
5. Phase 3 does not perform analysis, reporting, scoring, dashboard updates, or automatic transitions to `ANALYZING`, `REPORTING`, or `COMPLETED`. Phase 4+ owns transitions beyond `FINALIZING` except the zero-execution failure path.

## 6. System Components

### LifecycleStateMachine

**Suggested location:** `packages/audit_lifecycle/state_machine.py`

**Responsibilities:**

- Own the approved lifecycle state list.
- Own the approved transition table.
- Reject unknown states.
- Reject invalid transitions with a controlled lifecycle error.

**Valid transition table:**

`ANALYZING`, `REPORTING`, and `COMPLETED` are valid lifecycle states for future phases. Phase 3 validates these future transitions in the state machine only; Phase 3 handlers must not execute analytics/reporting workflows or automatically move an audit into these states.

| Current State | Allowed Next States |
| --- | --- |
| `DRAFT` | `SCHEDULED`, `CANCELLED`, `FAILED` |
| `SCHEDULED` | `RUNNING`, `CANCELLED`, `FAILED`, `FINALIZING` |
| `RUNNING` | `FINALIZING`, `FAILED`, `CANCELLED` |
| `FINALIZING` | `ANALYZING`, `FAILED` |
| `ANALYZING` | `REPORTING`, `FAILED` |
| `REPORTING` | `COMPLETED`, `FAILED` |
| `COMPLETED` | none |
| `FAILED` | none |
| `CANCELLED` | none |

### AuditLifecycleService

**Suggested location:** `packages/audit_lifecycle/service.py`

**Responsibilities:**

- Load audit lifecycle metadata.
- Apply transition validation.
- Append lifecycle history entries.
- Persist current state and history atomically via DynamoDB conditional update.
- Sanitize all persisted transition metadata.
- Never mutate prior history entries.

**Transition input contract:**

| Field | Required | Description |
| --- | --- | --- |
| `client_id` | yes | Validated client identifier. |
| `audit_id` | yes | Validated audit identifier. |
| `expected_current_state` | yes | State read by caller; used in condition expression. |
| `next_state` | yes | Approved next state. |
| `reason` | yes | Controlled reason, e.g. `schedules_created`, `finalization_trigger`, `schedule_creation_failed`. |
| `actor` | yes | `scheduler`, `orchestrator`, `finalization_handler`, `cancellation_handler`, or `system_failure_handler`. |
| `metadata` | no | Safe supplemental metadata only. |

### AuditMetadataRepository

**Suggested location:** `packages/storage/audit_metadata_client.py`

**Responsibilities:**

- Provide DynamoDB access for audit-level metadata separate from Phase 1 run metadata methods.
- Preserve existing Phase 1 run metadata key contract: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Use confirmed audit-level item key: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- Use occurrence claim item key: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Provide conditional put/update helpers for audit metadata, schedule metadata, lifecycle transitions, execution counter updates, occurrence claim writes, and cleanup status updates.

### AuditSchedulingService

**Suggested location:** `packages/audit_scheduling/service.py`

**Responsibilities:**

- Validate audit scheduling configuration.
- Compute default audit window.
- Build schedule definitions.
- Create EventBridge schedules via wrapper.
- Persist schedule metadata.
- Transition `DRAFT -> SCHEDULED` on full success.
- Roll back and transition to `FAILED` on partial failure.

### EventBridgeSchedulerClient

**Suggested location:** `packages/aws/eventbridge_scheduler_client.py` or `packages/storage/eventbridge_scheduler_client.py`

**AWS wrapper boundary:**

- `create_schedule(definition) -> CreatedScheduleMetadata`
- `delete_schedule(schedule_name, group_name=None) -> CleanupResult`
- `disable_schedule(schedule_name, group_name=None) -> CleanupResult`
- `get_schedule(schedule_name, group_name=None) -> ScheduleProviderState` for tests/reconciliation if needed.

The wrapper is the only module that directly imports/uses boto3 EventBridge Scheduler. It must normalize AWS exceptions into sanitized project errors and must not log target payloads containing unsafe data.

### ScheduleBuilder

**Suggested location:** `packages/audit_scheduling/builders.py`

**Responsibilities:**

- Build deterministic schedule names.
- Build EventBridge schedule expressions.
- Build minimal target payloads that include `schedule_occurrence_id` and never include `run_id`.
- Enforce schedule-type defaults and shape.
- Return definitions without performing AWS calls.

**Baseline occurrence guidance:** `build_baseline` may become `build_baseline_occurrences` or return multiple baseline `ScheduleDefinition` instances through `build_all`. The generated schedule name should include an occurrence token derived from `scheduled_at` where possible, or include occurrence fields in the stable hash input when truncation is needed. Existing tests that assert `rate(15 minutes)` must be updated to assert multiple bounded `at(...)` definitions for the audit window.

### ScheduledExecutionHandler

**Suggested location:** `apps/backend/handlers/scheduled_execution_handler.py`

**Responsibilities:**

- Receive scheduler execution events.
- Validate event payload.
- Load audit metadata.
- Claim `schedule_occurrence_id` before orchestrator invocation.
- Skip and log sanitized duplicate deliveries when the claim already exists.
- Run execution safeguards.
- Invoke Phase 1 `CoreEngineOrchestrator` with the existing contract.
- Update safe audit-level execution counters/occurrence metadata.

### RepeatedExecutionCoordinator

**Suggested location:** `packages/audit_scheduling/repeated.py`

**Responsibilities:**

- Enforce `iteration_count <= cap`.
- Estimate repeated execution request/runtime limits before schedule creation and reject unsafe configurations.
- Invoke the orchestrator sequentially.
- Stop on audit expiration, cancellation, terminal state, token expiration, or safeguard failure.
- Record safe per-iteration summaries, not raw results.
- Do not create EventBridge chaining, self-reinvocation, queues, or follow-up executions in Phase 3.

### FinalizationHandler

**Suggested location:** `apps/backend/handlers/audit_finalization_handler.py`

**Responsibilities:**

- Receive finalization event.
- Transition eligible audits to `FINALIZING`.
- Record finalization boundary metadata when executions exist.
- If execution count is zero, transition `FINALIZING -> FAILED`.
- Do not auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED`; do not perform analysis/reporting/scoring.

### AuditCancellationService

**Suggested location:** `packages/audit_lifecycle/cancellation.py`

**Responsibilities:**

- Validate current state is cancellable through state machine.
- Delete or disable all associated schedules.
- Treat each discrete baseline occurrence schedule as an associated schedule; cleanup must iterate persisted schedule metadata rather than assuming one baseline schedule per audit.
- Retry cleanup using bounded internal retry policy.
- Record cleanup outcome per schedule.
- Transition to `CANCELLED` when lifecycle transition is valid, even if cleanup had recorded cleanup failures that require operator follow-up.
- Persist audit-level `cleanup_errors` containing sanitized error codes and affected schedule names for failed cleanup attempts.

## 7. Data Models

## AuditMetadata


### Purpose

Stores audit-level lifecycle state, audit window, scheduling metadata, safeguards, token reference metadata, execution counters, and finalization boundary metadata.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Validated client identifier. |
| `audit_id` | string | Validated audit identifier. |
| `lifecycle_state` | string | One approved lifecycle state. |
| `lifecycle_history` | array | Append-only transition history entries. |
| `audit_window` | object | `start_time`, `end_time`, `duration_hours`, `timezone` if needed; all comparisons use UTC timestamps. |
| `schedules` | array | Schedule metadata entries, retained after cancellation/failure. |
| `scenario_defaults` | object | Default scenario type per schedule type where configured. |
| `reliability_category_by_scenario` | object | Optional persisted mapping result for traceability. |
| `execution_environment` | object | `target_environment`, `allow_production_execution`. |
| `operational_caps` | object | Effective caps used for this audit. |
| `temporary_token` | object/null | Token reference metadata only. |
| `execution_counters` | object | Safe counters: `total_started`, `total_completed`, `total_failed`, `total_skipped`, `last_execution_at`. |
| `finalization` | object/null | Finalization trigger metadata and zero-execution flag. |
| `cleanup_errors` | array | Sanitized cleanup failures recorded during cancellation/rollback; no raw AWS exception messages or target payloads. |
| `created_at` / `updated_at` | string | UTC ISO-8601 timestamps. |

### Ownership Model

Audit metadata is scoped by `client_id` and `audit_id`. Phase 3 does not introduce user-level ownership/RBAC.

### Lifecycle

- Created before or during scheduling as `DRAFT`.
- Updated through validated lifecycle transitions only.
- Schedule metadata is appended/updated for status changes and retained after failure/cancellation.
- Terminal states are immutable except for non-state cleanup-status annotations explicitly needed for traceability.

## LifecycleHistoryEntry


### Purpose

Append-only audit trail for lifecycle transitions.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `from_state` | string | Previous lifecycle state. |
| `to_state` | string | Next lifecycle state. |
| `timestamp` | string | UTC ISO-8601 transition timestamp. |
| `reason` | string | Controlled transition reason. |
| `actor` | string | Source actor/handler. |
| `client_id` | string | Client identifier for standalone traceability. |
| `audit_id` | string | Audit identifier for standalone traceability. |
| `metadata` | object | Safe supplemental fields, no secrets/raw payloads/PII. |

### Append-Only Strategy

Use DynamoDB conditional update with current-state condition and list append semantics. Do not rewrite existing list elements. If concurrent transitions race, only the update whose condition matches succeeds; losers reload state and return controlled lifecycle conflict/invalid transition errors.

## ScheduleMetadata


### Purpose

Trace EventBridge schedules associated with an audit without storing unsafe target data.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `stage` | string | Deployment stage used in deterministic schedule name. |
| `schedule_name` | string | Deterministic EventBridge schedule name. |
| `schedule_group` | string/null | EventBridge Scheduler group if configured. |
| `schedule_type` | string | `baseline`, `burst`, `repeated`, or `finalization`. |
| `scenario_type` | string | Approved scenario taxonomy value. |
| `reliability_category` | string | Mapped category. |
| `status` | string | `planned`, `created`, `rollback_deleted`, `rollback_disabled`, `rollback_failed`, `cancel_deleted`, `cancel_disabled`, `cancel_cleanup_failed`, `provider_not_found`, `fired`, `expired_skipped`. |
| `created_at` | string | UTC ISO-8601 timestamp. |
| `last_cleanup_attempt_at` | string/null | Cleanup timestamp if applicable. |
| `last_error_code` | string/null | Sanitized controlled error code. |
| `schedule_expression_summary` | string | Safe human-readable summary; do not persist raw target payload if it may contain unsafe data. |
| `target_handler` | string | Logical target, e.g. `scheduled_execution_handler` or `audit_finalization_handler`. |
| `name_hash_suffix` | string/null | Deterministic hash suffix used when collision avoidance or AWS length-limit truncation is required. |

### Lifecycle

Created in `planned` memory state, persisted as `created` after successful AWS creation, updated with cleanup status during rollback/cancellation. Entries remain after terminal states.

## ScheduleOccurrenceClaim


### Purpose

Stores one conditional claim per scheduled occurrence so duplicate EventBridge deliveries do not create duplicate Phase 1 runs. Phase 3 scheduler execution events always omit `run_id`; `schedule_occurrence_id` is the idempotency key for the scheduler delivery, while Phase 1 generates a new `run_id` for the accepted execution result set.

Per ADR `adr_scheduled_execution_occurrence_identity`, `schedule_occurrence_id` must be interpreted as an intended occurrence identity. It must not be reused across multiple baseline fires from a recurring schedule definition.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Validated client identifier. |
| `audit_id` | string | Validated audit identifier. |
| `schedule_occurrence_id` | string | Deterministic occurrence identifier from scheduler payload. |
| `schedule_name` | string | Deterministic EventBridge schedule name. |
| `schedule_type` | string | `baseline`, `burst`, or `repeated`. |
| `scenario_type` | string | Approved scenario taxonomy value. |
| `scheduled_at` | string | UTC ISO-8601 intended occurrence time. |
| `claim_status` | string | `claimed`, `completed`, `failed`, or `skipped`. |
| `claimed_at` | string | UTC ISO-8601 timestamp for first successful claim. |
| `run_id` | string/null | Phase 1-generated run ID captured after successful orchestrator invocation when available. This field must never be sourced from the scheduler event payload. |
| `duplicate_delivery_count` | number | Optional counter incremented on duplicate delivery detection. |
| `last_duplicate_at` | string/null | UTC ISO-8601 timestamp of most recent duplicate delivery. |
| `ttl_expires_at` | number/null | Optional DynamoDB TTL epoch seconds for long-term cleanup after audit retention. |

### Ownership Model

Occurrence claims are scoped by `client_id`, `audit_id`, and `schedule_occurrence_id`.

### Claim Behavior

- Scheduled execution handler performs a conditional put with `attribute_not_exists(PK) AND attribute_not_exists(SK)` before invoking Phase 1.
- Successful claim permits execution guard and orchestrator invocation to continue.
- The occurrence claim is keyed by `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` and is separate from both audit-level metadata (`SK = AUDIT#{audit_id}`) and run metadata (`SK = AUDIT#{audit_id}#RUN#{run_id}`).
- The scheduled payload must not include `run_id`; after successful orchestration, the handler may update the claim with the Phase 1-generated `run_id` for traceability.
- Conditional failure means the occurrence was already claimed; handler must skip orchestrator invocation, increment safe duplicate metadata where possible, and log `duplicate_occurrence_skipped` with sanitized identifiers only.
- Claim records must not contain raw payloads, response bodies, tokens, credentials, PII, or unsanitized AWS errors.

## TemporaryTokenMetadata


### Purpose

Tracks audit-scoped temporary token references and expiration without exposing secret values.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `token_ref` | string/object | Secrets Manager ARN/name/reference only. |
| `expires_at` | string | UTC ISO-8601 expiration timestamp. |
| `issued_at` | string/null | UTC ISO-8601 issue timestamp if known. |
| `scope` | string | Must indicate audit-scoped or equivalent narrow scope. |
| `least_privilege_description` | string/null | Safe description of scope; no secret values. |

### Validation Rules

- Raw token values are never accepted in audit metadata or schedule target payloads.
- Recommended validity is 48–72 hours.
- Scheduling validation must require a parseable future `expires_at` and must retain expiration metadata for execution-time checks. Execution always fails if `expires_at <= scheduled_run_start`.
- If token validity is shorter than the audit window, record safe metadata indicating that later occurrences may be blocked; do not execute any occurrence after expiration.

## 8. API Contracts

Phase 3 does not introduce public HTTP APIs. The following are backend handler/function contracts.

## Contract: Schedule Audit

### Purpose

Validate a Phase 3 audit configuration, create EventBridge schedules, persist metadata, and transition to `SCHEDULED`.

### Authentication / Authorization

No public user auth/RBAC in Phase 3. Internal invocation only. IAM must restrict the handler/tooling to approved deployment/operator roles.

### Request Body

```json
{
  "client_id": "clientA",
  "audit_id": "audit123",
  "audit_window": {
    "start_time": "2026-05-19T00:00:00Z",
    "duration_hours": 48,
    "timezone": "America/New_York"
  },
  "execution_environment": {
    "target_environment": "staging",
    "allow_production_execution": false
  },
  "baseline": {
    "enabled": true,
    "interval_minutes": 15,
    "scenario_type": "baseline_health",
    "requests_per_run": 1
  },
  "burst_schedule": {
    "enabled": true,
    "windows": [
      {
        "start_time": "09:00",
        "duration_minutes": 30,
        "request_count": 100,
        "concurrency": 5,
        "scenario_type": "burst_stability"
      }
    ]
  },
  "repeated": [
    {
      "enabled": true,
      "schedule_time": "2026-05-19T18:00:00Z",
      "scenario_type": "repeated_stability",
      "iteration_count": 25
    }
  ],
  "temporary_token": {
    "token_ref": "arn:aws:secretsmanager:region:acct:secret:audit-token",
    "expires_at": "2026-05-21T12:00:00Z",
    "scope": "audit"
  }
}
```

### Response Body

```json
{
  "client_id": "clientA",
  "audit_id": "audit123",
  "lifecycle_state": "SCHEDULED",
  "schedule_count": 4,
  "audit_window": {
    "start_time": "2026-05-19T00:00:00Z",
    "end_time": "2026-05-21T00:00:00Z"
  }
}
```

### Success Status Codes

- Internal function success or `200` if wrapped by internal tooling.

### Error Status Codes

- `400`/controlled validation error: invalid config, unknown scenario, cap violation, audit window > 48h, production not explicitly allowed.
- `409`/controlled lifecycle conflict: invalid current state or concurrent transition.
- `500`/controlled scheduling error: AWS schedule creation failure after rollback and audit transition to `FAILED` where possible.

### Validation Rules

- `duration_hours <= 48`; default to 48 if absent.
- Baseline interval defaults to 15 minutes.
- Burst windows use `burst_schedule.enabled` and `burst_schedule.windows[]`; `start_time` values are interpreted in `audit_window.timezone` when provided, otherwise UTC.
- Unknown scenario taxonomy values are rejected.
- Caps are selected by environment and enforced before AWS schedule creation.
- Repeated schedules must pass estimated request/runtime limit validation. Unsafe estimates fail scheduling; Phase 3 must not compensate by creating chained/follow-up executions.
- Production requires `target_environment = "production"` and `allow_production_execution = true`; otherwise block scheduling.
- Temporary token metadata must be reference-only and unexpired for the planned audit window.

### Side Effects

- DynamoDB audit metadata writes.
- EventBridge Scheduler schedule creation.
- Lifecycle transition to `SCHEDULED` or `FAILED`.

### Idempotency / Duplicate Handling

Phase 3 should reject duplicate scheduling for an audit already in `SCHEDULED`, `RUNNING`, or terminal states unless a future schedule repair design is approved. If retried after an ambiguous failure, implementation should rely on deterministic schedule names and DynamoDB state to avoid duplicate created schedules.

## Contract: Scheduled Execution Event

### Purpose

Invoke an audit run for a scheduled baseline, burst, or repeated occurrence.

### Request Body

Scheduler execution event payloads must not include `run_id`. `schedule_occurrence_id` is required to suppress duplicate EventBridge delivery; Phase 1 creates the new `run_id` only after the occurrence claim succeeds.

```json
{
  "event_type": "audit_schedule_execution",
  "schema_version": "phase3.schedule_event.v1",
  "client_id": "clientA",
  "audit_id": "audit123",
  "schedule_name": "rcp-dev-clientA-audit123-baseline-baseline_health",
  "schedule_type": "baseline",
  "scenario_type": "baseline_health",
  "triggered_by": "eventbridge_scheduler",
  "schedule_occurrence_id": "baseline#2026-05-19T00:15:00Z",
  "scheduled_at": "2026-05-19T00:15:00Z",
  "burst": null,
  "repeated": null
}
```

For burst events, include safe fields:

```json
{
  "burst": {
    "request_count": 100,
    "concurrency": 5,
    "window_start": "2026-05-19T09:00:00-04:00",
    "window_end": "2026-05-19T09:30:00-04:00"
  }
}
```

For repeated events, include:

```json
{
  "repeated": {
    "iteration_count": 25,
    "execution_mode": "sequential"
  }
}
```

### Response Body

```json
{
  "client_id": "clientA",
  "audit_id": "audit123",
  "schedule_type": "baseline",
  "status": "accepted",
  "run_id": "phase1-generated-run-id-or-null-for-skipped"
}
```

### Validation Rules

- Payload contains metadata only: no secrets, no raw tokens, no raw client credentials, no raw payloads, no PII.
- Validate identifiers using existing project identifier rules before DynamoDB/log usage.
- `schedule_occurrence_id` is required for every scheduled execution event and must be stable for a specific intended schedule occurrence. For baseline occurrence schedules, it must differ across distinct `scheduled_at` values and remain identical for duplicate delivery/retry of the same `at(...)` schedule.
- `run_id` is forbidden in EventBridge Scheduler execution event payloads. If present, reject the event as invalid before occurrence claim or orchestrator invocation.
- Validate `scenario_type` and category mapping.
- Enforce audit-window, lifecycle terminal-state, environment, cap, and token expiration checks before orchestrator invocation.
- The derived Phase 1 orchestrator invocation must also omit `run_id`; Phase 1 remains authoritative for generating and validating the run ID persisted under `SK = AUDIT#{audit_id}#RUN#{run_id}`.

### Side Effects

- May transition `SCHEDULED -> RUNNING`.
- Invokes Phase 1 orchestrator, which writes raw results and run metadata.
- Updates audit-level safe execution counters/occurrence metadata.

### Idempotency / Duplicate Handling

Duplicate scheduler deliveries must not create multiple Phase 1 result sets. Because the final design requires scheduler execution events to omit `run_id`, Phase 3 must use occurrence claims keyed by `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` with a conditional write before orchestrator invocation. If the claim already exists, skip execution and log `duplicate_occurrence_skipped` with sanitized `client_id`, `audit_id`, `schedule_name`, `schedule_type`, and `schedule_occurrence_id` only. This duplicate path must not call `CoreEngineOrchestrator.run(...)`.

## Contract: Finalization Event

### Purpose

Transition eligible audits to `FINALIZING` at audit-window completion.

### Request Body

```json
{
  "event_type": "audit_finalization",
  "schema_version": "phase3.finalization_event.v1",
  "client_id": "clientA",
  "audit_id": "audit123",
  "schedule_name": "rcp-dev-clientA-audit123-finalization",
  "triggered_by": "eventbridge_scheduler",
  "audit_window_end": "2026-05-21T00:00:00Z",
  "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z"
}
```

### Validation Rules

- Current state must allow transition to `FINALIZING`; Phase 3 must not transition from `FINALIZING` to `ANALYZING` or beyond.
- Duplicate finalization events should be idempotent: if already `FINALIZING`, return accepted/no-op; if terminal, return skipped/no-op without state mutation.
- If executions exist, transition to `FINALIZING` and record finalization metadata only.
- If zero executions are recorded, transition to `FINALIZING`, record zero-execution metadata, then transition to `FAILED`.

### Side Effects

- DynamoDB lifecycle transition(s).
- Finalization boundary metadata update.
- No analysis/reporting/scoring/dashboard side effects.

## Contract: Cancel Audit

### Purpose

Cleanup associated schedules and transition an audit to `CANCELLED`.

### Request Body

```json
{
  "client_id": "clientA",
  "audit_id": "audit123",
  "reason": "operator_cancelled"
}
```

### Validation Rules

- Current lifecycle state must allow transition to `CANCELLED`.
- Cleanup target list is loaded from retained `schedules` metadata.

### Side Effects

- EventBridge Scheduler delete/disable attempts.
- Schedule metadata cleanup status updates.
- Audit metadata update with `cleanup_errors` for any schedule cleanup failures.
- Lifecycle transition to `CANCELLED` when valid.

### Cleanup Failure Handling

If delete fails, attempt disable. If both fail after bounded retries, record schedule status `cancel_cleanup_failed` and append a sanitized audit-level `cleanup_errors[]` entry containing schedule name, schedule type, cleanup action attempted, controlled error code, and timestamp. The audit still transitions to `CANCELLED` when the lifecycle transition is valid; operational follow-up is driven by recorded cleanup failures.

## 9. Frontend Impact

No frontend implementation is in scope for Phase 3.

### Components Affected

- None.

### API Integration

- None public/customer-facing.

### UI States

- None.

Future dashboards may read `lifecycle_state`, `lifecycle_history`, `schedules`, and finalization metadata, but Phase 3 must not implement UI behavior.

## 10. Backend Logic

### Responsibilities

- Lifecycle validation and atomic transition persistence.
- Schedule validation and EventBridge Scheduler creation.
- Execution-time guard before Phase 1 orchestrator invocation.
- Sequential repeated execution coordination.
- Finalization boundary state transition.
- Cancellation and rollback cleanup.
- Safe metadata and logging.

### Validation Flow

1. Validate identifiers and approved lifecycle state values.
2. Validate transition is allowed for the current state.
3. Validate audit window: default 48h, max 48h, UTC start/end, start before end.
4. Validate environment restrictions.
5. Select effective caps:
   - Non-production defaults: `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, `max_audit_window_hours = 48`.
   - Production: `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, production allow required.
6. Validate schedule-specific caps.
   - Burst config shape: `burst_schedule.enabled` and `burst_schedule.windows[]`.
   - Burst `start_time` is interpreted in audit timezone when `audit_window.timezone` is present, otherwise UTC.
   - Repeated schedules must pass estimated request/runtime validation before any schedule is created.
7. Validate scenario taxonomy and reliability mapping.
8. Validate token metadata by reference and expiration.
9. At execution time, repeat environment/cap/window/token/terminal-state checks before invoking Phase 1.

### Business Rules

- Baseline default interval is 15 minutes.
- Baseline schedule type defaults to `baseline_health`.
- Burst schedule type defaults to `burst_stability`.
- Repeated schedule type defaults to `repeated_stability`.
- Repeated execution is sequential only.
- Repeated schedules that exceed configured iteration caps or estimated safe runtime/request limits fail scheduling; Phase 3 does not create chained/follow-up execution mechanisms.
- Finalization trigger fires once at audit-window completion.
- With existing executions, finalization transitions to `FINALIZING` and records metadata only.
- With zero executions, finalization transitions `FINALIZING -> FAILED`.
- `ANALYZING`, `REPORTING`, and `COMPLETED` are future valid transitions only; Phase 3 never auto-transitions into them.
- Baseline/burst/repeated schedule occurrences after window end are skipped before outbound API requests.
- Terminal states cannot be left.
- `SCHEDULED_WITH_ERRORS` is invalid and must never be persisted.
- Raw tokens, raw payloads, PII, credentials, cookies, and unsanitized response content are forbidden in schedules, metadata, logs, and finalization events.

### Persistence Flow

- Use confirmed DynamoDB audit metadata item key for lifecycle/schedules: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- Use existing Phase 1 run metadata item key for individual orchestrator runs: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Use conditional writes for lifecycle transitions and occurrence deduplication.
- Occurrence deduplication uses separate claim items keyed by `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Use list append for `lifecycle_history`.
- Sanitize all metadata before persistence.

### Error Handling

- Validation errors fail before schedule creation or outbound requests.
- Invalid transitions return controlled lifecycle errors and leave persisted state unchanged.
- Schedule creation failure triggers rollback, schedule cleanup status recording, and transition to `FAILED`.
- Rollback cleanup failure is recorded but does not create a partial lifecycle state.
- Cancellation cleanup failure is recorded in schedule metadata and audit-level `cleanup_errors`, then the audit transitions to `CANCELLED` when valid.
- Execution safeguard failure records a skipped/blocked occurrence and does not invoke outbound requests.
- Duplicate EventBridge delivery records/logs sanitized duplicate metadata and does not invoke outbound requests.
- Zero executions at finalization transitions to `FAILED` after recording `FINALIZING` and zero-execution metadata.

### Schedule Construction Rules

#### Naming Convention

Use deterministic, path/log-safe names:

```text
rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}
rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}-{occurrence_token}
rcp-{stage}-{client_id}-{audit_id}-finalization
```

- `stage` is the deployment stage/environment identifier used to prevent cross-environment name collisions, e.g. `dev`, `staging`, or `prod`.
- `client_id` and `audit_id` must be validated identifiers and may need normalization to EventBridge Scheduler allowed characters. Do not silently accept invalid identifiers.
- `schedule_type` is one of `baseline`, `burst`, or `repeated` for execution schedules. Finalization uses the dedicated finalization name and does not append `scenario_type`.
- `scenario_type` is the approved scenario taxonomy value for the schedule.
- If multiple schedules would otherwise produce the same name for the same audit/stage/type/scenario, append a deterministic short hash derived from stable schedule config before applying length enforcement. For discrete baseline occurrence schedules, include `scheduled_at` or an occurrence token in the full intended name/hash input.
- Keep names within EventBridge Scheduler length limits. If the full confirmed pattern exceeds the AWS limit, safely truncate variable segments and append a deterministic hash suffix. The hash input must include the untruncated full intended name plus stable schedule config so collisions are deterministic and traceable.
- Persist the final schedule name plus enough schedule metadata to map it back to `stage`, `client_id`, `audit_id`, `schedule_type`, `scenario_type`, and the stable schedule config.

#### Baseline

- Create one discrete `at(...)` schedule per intended baseline occurrence using the default `15` minute interval unless a validated interval override is supplied.
- Enumerate only bounded occurrence times inside the audit window; execution guard must still enforce window bounds at runtime.
- Target payload includes schedule metadata, canonical `scheduled_at`, and deterministic per-occurrence `schedule_occurrence_id` only; it must omit `run_id`.

#### Burst

- Accept configuration in this shape:

```json
{
  "burst_schedule": {
    "enabled": true,
    "windows": [
      {
        "start_time": "09:00",
        "duration_minutes": 30,
        "request_count": 100,
        "concurrency": 5
      }
    ]
  }
}
```

- Create schedules for each configured burst window.
- Interpret `start_time` in the audit timezone when `audit_window.timezone` is provided; otherwise interpret it as UTC. Store/execute normalized UTC timestamps while retaining safe original config for traceability.
- Each burst occurrence payload includes `request_count`, `concurrency`, `window_start`, `window_end`, and `schedule_occurrence_id`; it must omit `run_id`.
- `request_count <= max_burst_requests_per_window` and per-run request count does not exceed environment cap.
- `concurrency <= effective max_concurrency`.
- Burst windows must be inside the audit window.

#### Repeated

- Create schedules for configured repeated occurrence times/windows.
- Payload includes `iteration_count`, `execution_mode = sequential`, and `schedule_occurrence_id`; it must omit `run_id`.
- `iteration_count <= max_repeated_iterations`.
- Before schedule creation, estimate whether the configured iteration count/request volume can complete within applicable runtime and audit-window safety limits. If unsafe, fail scheduling with a controlled validation error.
- Coordinator loops sequentially and re-checks safeguards before each iteration.
- Do not create chained EventBridge schedules, self-invocation continuations, queues, or follow-up executions in Phase 3.

#### Finalization

- Create exactly one one-time schedule at `audit_window.end_time`.
- Payload includes only finalization metadata.
- Handler transitions to `FINALIZING` and records boundary metadata when executions exist.
- Handler transitions `FINALIZING -> FAILED` only for zero-execution audits.
- Handler never transitions to `ANALYZING`, `REPORTING`, or `COMPLETED` in Phase 3.

### Scenario Taxonomy Constants

Approved scenario types:

```text
baseline_health
repeated_stability
burst_stability
invalid_payload_handling
missing_fields_validation
auth_failure_handling
timeout_sensitivity
response_consistency
```

Reliability category mapping:

| Category | Scenario Types |
| --- | --- |
| `Stability` | `baseline_health`, `repeated_stability`, `burst_stability`, `response_consistency` |
| `Resilience` | `timeout_sensitivity`, `auth_failure_handling` |
| `Validation Robustness` | `invalid_payload_handling`, `missing_fields_validation` |

Unknown scenario values or missing mappings fail validation before scheduling or execution.

The scenario taxonomy mapping does not imply built-in scenario-specific verdict computation in Phase 3. `response_consistency` uses ordinary runner execution and raw `response_fingerprint` persistence; Phase 3 must not compare fingerprints or emit response-consistency verdict/status fields. Fingerprint comparison analytics are deferred to downstream reporting/aggregation after finalization.

## 11. File Structure

Suggested backend additions:

```text
apps/backend/handlers/
  scheduled_execution_handler.py
  audit_finalization_handler.py

packages/audit_lifecycle/
  __init__.py
  constants.py
  state_machine.py
  service.py
  cancellation.py
  exceptions.py

packages/audit_scheduling/
  __init__.py
  constants.py
  validators.py
  builders.py
  service.py
  repeated.py
  safeguards.py
  events.py

packages/storage/
  audit_metadata_client.py
  eventbridge_scheduler_client.py

tests/unit/
  test_phase3_lifecycle_state_machine.py
  test_phase3_schedule_builders.py
  test_phase3_safeguards.py
  test_phase3_occurrence_claims.py
  test_phase3_taxonomy.py
  test_phase3_token_metadata.py

tests/integration/
  test_phase3_scheduling_lifecycle.py
  test_phase3_scheduled_execution.py
  test_phase3_duplicate_delivery.py
  test_phase3_cancellation_finalization.py
```

If implementation prefers `packages/aws/eventbridge_scheduler_client.py`, keep the wrapper boundary explicit and avoid direct boto3 calls elsewhere.

## 12. Security

### Authentication

Phase 3 does not add user authentication. Internal handlers/tooling must be protected by deployment/IAM controls only.

### Authorization

- EventBridge Scheduler role may invoke only the specific scheduled execution and finalization handlers.
- Scheduling/cancellation code may create/delete/disable schedules only under approved schedule group/name prefix.
- Execution role may read only required audit metadata, configs, raw result buckets/keys, and Secrets Manager references.
- Temporary tokens must be audit-scoped and least-privilege.

### Input Validation

- Validate identifiers before DynamoDB keys, scheduler names, logs, or orchestrator events.
- Validate lifecycle states and transitions centrally.
- Validate schedule type, scenario type, category mapping, environment, caps, and token metadata.
- Reject raw token fields and unsafe secret-bearing fields in all Phase 3 metadata and schedule payloads.

### Misuse Risks

- Accidental production traffic: blocked unless explicit allow is true and production caps are enforced.
- Unbounded request volume: capped at schedule creation and execution.
- Schedule payload leakage: target payloads contain only safe metadata.
- Token leakage: token values are never persisted or logged; only references and expiration metadata are stored.
- Duplicate scheduler delivery: occurrence deduplication and Phase 1 run ID duplicate protection prevent unsafe duplicate behavior where configured.

## 13. Reliability

### Retries

- EventBridge Scheduler delivery retries may produce duplicate events; handlers must be idempotent or guarded by occurrence tracking.
- Schedule cleanup retry policy: bounded retry, e.g. 3 attempts with short exponential backoff and jitter inside handler constraints. Record final cleanup failure if still unsuccessful.
- Do not retry outbound client API requests at Phase 3 level; preserve Phase 1 runner retry settings.

### Timeouts

- Scheduler wrapper calls should use AWS SDK/client configured timeouts where available.
- Handler execution must leave enough timeout budget for cleanup/final metadata writes.
- Repeated coordinator must avoid running past Lambda timeout; schedule-time estimated limit validation should prevent unsafe configurations, and runtime remaining-time checks should stop and record controlled failure/skipped summary rather than chaining or timing out silently.

### Failure Modes

- Partial schedule creation: rollback then `FAILED`.
- Rollback cleanup failure: record cleanup failure and still transition to `FAILED`.
- Cancellation cleanup failure: record cleanup failure and transition to `CANCELLED` when valid.
- Expired audit execution: skip before outbound requests.
- Terminal-state event: no-op/skip before outbound requests.
- Expired token: block execution before secret resolution/outbound requests.
- Finalization duplicate: no-op if already `FINALIZING` or terminal.
- Duplicate scheduled execution delivery: occurrence claim conditional write fails; skip orchestrator invocation and log sanitized duplicate delivery event.

### Logging / Monitoring

- Use existing structured logging categories.
- Log safe event categories: `audit_schedule_created`, `audit_schedule_failed`, `audit_lifecycle_transition`, `audit_execution_skipped`, `duplicate_occurrence_skipped`, `audit_cancelled`, `audit_finalization_triggered`.
- Scheduled execution handler logs must be Lambda-visible at INFO level and include: `scheduled_execution_handler_started`, `event_contract_validated`, `occurrence_claim_attempted`, `occurrence_claim_created`, `duplicate_occurrence_skipped`, `orchestrator_execution_started`, `orchestrator_execution_completed`, `raw_results_written`, `run_metadata_written`, and `scheduled_execution_failed`.
- Never log raw tokens, raw target payloads, raw client payloads, unsanitized responses, PII, cookies, or credentials.
- Advanced observability/dashboards/distributed tracing are out of scope.

### Performance Considerations

- DynamoDB lifecycle updates should be conditional and small; large history arrays may become a future concern but are acceptable for 48-hour MVP windows.
- Burst concurrency must remain within configured caps and production caps.
- Repeated sequential execution may exceed handler runtime if iteration count and endpoint latency are high; implementation must reject unsafe estimated schedules and still check remaining time at runtime. Phase 3 must not add continuation/chaining infrastructure.

## 14. Dependencies

- Phase 1 `CoreEngineOrchestrator`, runner, raw result schema v1, S3/DynamoDB/Secrets wrappers, sanitization, strict `run_id` validation, duplicate run ID protection.
- Phase 2 payload strategies, payload metadata, duplicate payload controls, fingerprints, endpoint safety controls.
- AWS EventBridge Scheduler availability and IAM permissions for schedule create/delete/disable/invoke.
- DynamoDB table used by existing metadata storage or an approved table for audit metadata.
- Secrets Manager-compatible token references.
- Existing structured logger and sanitizer.

## 15. Assumptions

### Confirmed Assumptions

- Default caps are `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, `max_audit_window_hours = 48`.
- Production caps are `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, `prod_requires_explicit_allow_production = true`.
- When `target_environment = "production"`, scheduling and execution are blocked unless `allow_production_execution = true`.
- Schedule creation failure rolls back where possible and transitions to `FAILED`.
- Cancellation deletes/disables schedules, transitions to `CANCELLED`, and retains schedule metadata.
- Cancellation cleanup failures do not block `CANCELLED`; they are recorded in schedule metadata and audit-level `cleanup_errors`.
- Zero executions at finalization transitions to `FINALIZING`, records zero executions, then transitions to `FAILED`.
- If executions exist, Phase 3 finalization transitions to `FINALIZING` and records metadata only; Phase 4+ owns transitions to `ANALYZING`, `REPORTING`, and `COMPLETED`.
- Duplicate EventBridge deliveries are suppressed with `schedule_occurrence_id` and DynamoDB occurrence claims.
- Burst config shape is `burst_schedule.enabled` and `burst_schedule.windows[]`; window times use audit timezone when provided, otherwise UTC.
- Phase 3 does not implement chained/follow-up repeated executions; unsafe estimated repeated limits fail scheduling.
- Audit-level metadata uses `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- Occurrence claims use `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Run metadata remains under the existing Phase 1 shape: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Phase 3 EventBridge Scheduler execution events must omit `run_id`; each successfully claimed occurrence invokes Phase 1 without a supplied `run_id` so Phase 1 creates a new execution result set with a new `run_id`.

### Technical Assumptions Requiring Confirmation

- EventBridge schedule group name, if used, will be environment-specific and configured outside product logic.
- Internal schedule/cancel entrypoints may be exposed as Lambda handlers or direct service calls; Phase 3 does not require a public API.

## 16. Risks / Open Questions

- **Duplicate scheduler delivery claim races:** Conditional occurrence claims mitigate exact duplicate deliveries, but implementation must ensure the claim occurs before orchestrator invocation and that duplicate logging cannot leak target payload content.
- **Repeated execution estimation accuracy:** Schedule-time estimated limits may be conservative or miss endpoint-specific latency variance; runtime remaining-time checks remain required and may still stop an occurrence before all iterations complete.
- **Schedule expression precision:** Burst windows may require multiple one-time schedules or cron expressions depending on implementation choices; builders should keep the confirmed config shape minimal and testable.
- **Large lifecycle history arrays:** A 48-hour window limits growth, but future longer windows or many schedules may require separate history items.
- **Future lifecycle ownership:** `ANALYZING`, `REPORTING`, and `COMPLETED` transitions are valid only for future phases; Phase 4+ must define the services and metadata required to advance beyond `FINALIZING`.

## 17. Implementation Notes

- Keep Phase 3 code behind new lifecycle/scheduling modules; avoid modifying Phase 1/2 internals except for minimal metadata extension points if required.
- Centralize constants for lifecycle states, schedule types, scenario taxonomy, category mapping, and caps.
- Reuse existing sanitizer for all persisted/logged Phase 3 metadata.
- Reuse existing identifier validation where safe, but ensure schedule names satisfy EventBridge Scheduler constraints and length limits.
- Use DynamoDB conditional writes for:
  - audit metadata initialization at `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`,
  - lifecycle transitions based on expected current state,
  - occurrence deduplication at `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`,
  - terminal-state protection.
- Do not include `run_id` in EventBridge Scheduler execution event payloads or in the derived orchestrator invocation. Let Phase 1 generate and persist the run under `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}` after the occurrence claim succeeds.
- If the handler can observe the generated Phase 1 `run_id`, update the occurrence claim with that value only after successful orchestrator invocation; never use it as the idempotency key for scheduler delivery.
- Implement EventBridge Scheduler wrapper with fake/mock client compatibility from the start.

### QA / Test Strategy

- Test schedule name generation for:
  - `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}` execution schedules,
  - deterministic discrete baseline occurrence names/IDs that differ for two distinct `scheduled_at` values,
  - `rcp-{stage}-{client_id}-{audit_id}-finalization`,
  - deterministic uniqueness for repeated/burst schedules with the same type/scenario,
  - AWS length-limit truncation with deterministic hash suffix.
- Test scheduled event contracts require `schedule_occurrence_id` and reject missing/invalid occurrence identifiers before DynamoDB/log/orchestrator usage.
- Test scheduled event contracts reject any EventBridge Scheduler execution event containing `run_id`.
- Test the derived Phase 1 orchestrator event omits `run_id` and that the accepted occurrence results in a Phase 1-generated run metadata item shaped as `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Test audit metadata reads/writes use `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}` and occurrence claims use `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Test duplicate EventBridge delivery by sending the same `schedule_occurrence_id` twice; assert only the first call invokes the orchestrator and the second records/logs sanitized duplicate delivery metadata.
- Test scheduled handler invokes `CoreEngineOrchestrator.run(...)` for a successfully claimed scheduled occurrence and that raw result plus run metadata side effects are produced through the existing Phase 1 path.
- Test scheduled handler emits the required startup, validation, claim, orchestration, raw-result, run-metadata, duplicate-skip, and failure log events with sanitized fields.
- Test schedule cleanup/cancellation handles multiple discrete baseline occurrence schedules, not only one logical baseline schedule.
- Test occurrence claim conditional-write race behavior with mocked DynamoDB conditional failure.
- Test burst config validation for the confirmed `burst_schedule.windows[]` shape, timezone interpretation with `audit_window.timezone`, UTC fallback, caps, and audit-window bounds.
- Test repeated execution schedule-time validation for cap exceedance and unsafe estimated runtime/request limits; assert no chained/follow-up schedule or continuation artifact is created.
- Test schedule creation failure by making the Nth schedule creation throw and assert rollback attempts plus final `FAILED` state.
- Test cancellation when delete succeeds, delete-not-found, delete fails then disable succeeds, and both delete/disable fail; assert final state is `CANCELLED` and `cleanup_errors` contains only sanitized details for failed cleanup.
- Test execution guard blocks production without allow, expired windows, terminal states, cap violations, unknown scenarios, and expired tokens before orchestrator invocation.
- Test finalization with zero and nonzero execution counters:
  - nonzero executions: transition to `FINALIZING`, record metadata, do not enter `ANALYZING`/`REPORTING`/`COMPLETED`,
  - zero executions: transition `FINALIZING -> FAILED` with `zero_executions_at_finalization`.
- Test state machine permits future transitions (`FINALIZING -> ANALYZING`, `ANALYZING -> REPORTING`, `REPORTING -> COMPLETED`) but Phase 3 handlers never initiate them.
- For local tests, mock:
  - EventBridge Scheduler client,
  - DynamoDB audit metadata repository,
  - S3 config/raw result clients as needed by Phase 1 integration,
  - Secrets Manager client/token refs,
  - Phase 1 orchestrator for lifecycle-only tests, and real orchestrator for selected regression integration tests.
