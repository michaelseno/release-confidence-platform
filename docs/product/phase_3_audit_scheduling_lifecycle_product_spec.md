# Product Specification

## 1. Feature Overview

Phase 3 implements the recurring audit execution model for the Release Confidence Platform.

This phase adds a backend-first, AWS-native, event-driven audit lifecycle and scheduling system on top of the merged Phase 1 execution engine and Phase 2 payload/data-generation capabilities. The system must support deterministic lifecycle state transitions, recurring EventBridge Scheduler-driven execution, operational reliability scenario taxonomy, audit-window finalization, and production-safe execution safeguards.

Phase 3 is limited to backend audit scheduling, lifecycle orchestration, audit-window management, scenario classification, and finalization event triggering. It does not add frontend dashboards, user auth, RBAC, billing, subscriptions, multi-user onboarding, AI insights, report generation beyond the finalization event boundary, advanced observability, distributed tracing, load testing, uptime monitor clone behavior, chaos engineering, or heavy API frameworks.

### Operator-Facing Impact

- Operators can define an audit as a bounded recurring operational reliability audit rather than manually triggering isolated runs.
- Operators can rely on default baseline execution every 15 minutes during the audit window.
- Operators can configure burst schedules to evaluate short-window concurrency stability and transient degradation.
- Operators can configure repeated sequential execution to detect consistency issues and flaky behavior.
- Operators can expect audit execution to stop or finalize when the configured audit window expires.
- Operators can associate scenarios with approved operational reliability dimensions instead of generic test names.
- Operators receive safer execution behavior through request caps, concurrency caps, environment restrictions, production-safe limits, audit-scoped temporary token handling, and audit expiration handling.
- Operators receive deterministic failure and cancellation behavior: failed schedule creation rolls back created schedules where possible, cancelled audits attempt schedule cleanup and transition to `CANCELLED` with any `cleanup_errors` recorded, and zero-execution audits fail after finalization is recorded.

### Backend / System Impact

- The platform must persist and enforce an audit lifecycle state machine.
- EventBridge Scheduler must be used to trigger recurring and one-time audit execution events.
- Scheduled execution events must omit `run_id`; each accepted scheduled occurrence must create a new execution result set with a newly generated `run_id` through the existing Phase 1 orchestrator/runner contract without bypassing run ID validation, duplicate run ID protection, sanitization, persistence, or payload controls.
- Scheduling must generate deterministic execution intent for baseline, burst, repeated, and finalization-trigger schedule types.
- Scheduling must use deterministic EventBridge schedule names and safe truncation with a deterministic hash suffix when AWS length limits require it.
- Scheduled events must include a deterministic `schedule_occurrence_id`, claim each occurrence in DynamoDB before execution, and skip duplicate deliveries with sanitized duplicate-delivery logging.
- Lifecycle transition logic must reject invalid transitions and record controlled failures.
- Audit window metadata must control schedule creation, expiration handling, and automatic finalization triggering.
- Scenario taxonomy and reliability category grouping must be preserved in metadata for downstream analysis/reporting phases without executing analytics or reporting workflows in Phase 3.
- Temporary execution credentials/tokens must be audit-scoped, least-privilege, and tracked for expiration.

## 2. Problem Statement

The platform can currently execute individual audit runs and generate deterministic payload-backed evidence, but it does not yet provide a recurring audit model. Without lifecycle and scheduling, operators must manually trigger runs, cannot execute consistent baseline intervals, cannot define bounded burst or repeated stability checks, and cannot reliably detect when an audit window should finalize.

Phase 3 solves this by introducing a deterministic audit lifecycle system and AWS EventBridge Scheduler integration that coordinates recurring execution, operational reliability scenario classification, safe bounded execution, and automatic transition to finalization at audit-window completion.

## 3. User Persona / Target User

- **Technical operator / maintainer:** configures bounded recurring audits and needs predictable execution without manual triggering.
- **Platform engineer / developer:** implements lifecycle state management, schedule creation, EventBridge Scheduler integration, and finalization triggering while preserving Phase 1 and Phase 2 contracts.
- **QA engineer:** validates state transitions, scheduled trigger behavior, caps, expiration handling, and deterministic metadata.

## 4. User Stories

- As a technical operator, I want audits to run on a recurring schedule so that reliability evidence is collected consistently during an audit window.
- As a technical operator, I want baseline checks to run every 15 minutes by default so that latency trends, intermittent failures, and uptime consistency can be tracked.
- As a technical operator, I want burst checks with configurable windows, concurrency, and request counts so that transient degradation and concurrency stability can be assessed safely.
- As a technical operator, I want repeated sequential checks with configurable iteration counts so that flaky behavior and response consistency issues can be detected.
- As a technical operator, I want the audit to automatically enter finalization when the audit window completes so that downstream analysis/reporting can begin later without manual intervention.
- As a platform engineer, I want strict lifecycle transitions so that audit state cannot become ambiguous or contradictory.
- As a QA engineer, I want all schedule types and lifecycle transitions to have testable outcomes and controlled failure modes.

## 5. Goals / Success Criteria

Phase 3 is successful when:

- The platform supports the audit lifecycle states `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, `FAILED`, and `CANCELLED`.
- All lifecycle transitions are validated against an explicit transition map and invalid transitions are rejected.
- EventBridge Scheduler is integrated for Phase 3 schedule creation and triggering.
- The system supports baseline schedules, burst schedules, repeated schedules, and a one-time finalization trigger.
- Baseline schedules default to every 15 minutes during the audit window.
- The initial MVP audit window defaults to 48 hours and may only be overridden to a shorter approved duration.
- The maximum configured audit window is capped at 48 hours for Phase 3.
- Burst schedules support configurable windows per day, configurable concurrency, and configurable request counts subject to caps.
- Repeated schedules support sequential repeated execution and configurable iteration counts subject to caps.
- A finalization trigger is scheduled for audit-window completion and transitions the audit lifecycle to `FINALIZING`.
- Phase 3 finalization records finalization metadata and must not auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED`.
- If finalization occurs with zero recorded executions, the audit transitions from `FINALIZING` to `FAILED`.
- Scenario taxonomy is restricted to the approved operational reliability dimensions listed in this specification.
- Scenario taxonomy is grouped into the approved reliability categories listed in this specification.
- Request caps, concurrency caps, environment restrictions, production-safe limits, audit expiration handling, and temporary token expiration tracking are enforced before execution.
- Default operational caps are enforced as `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, and `max_audit_window_hours = 48`.
- Production-safe caps are enforced as `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, and `prod_requires_explicit_allow_production = true`.
- Scheduled execution preserves Phase 1 raw result schema v1, sanitization, S3/DynamoDB wrappers, generated `run_id` validation, duplicate `run_id` protection, and Phase 2 payload controls.
- Duplicate EventBridge Scheduler delivery for the same `schedule_occurrence_id` is skipped after DynamoDB occurrence-claim detection and logged only as a sanitized duplicate delivery event.
- Phase 3 can be validated without implementing dashboard UI, user auth/RBAC, AI insights, analytics/report generation, load testing, uptime-monitor clone behavior, or chaos engineering.

## 6. Feature Scope

### In Scope

Phase 3 includes only the following functionality:

- Audit lifecycle state machine with states:
  - `DRAFT`
  - `SCHEDULED`
  - `RUNNING`
  - `FINALIZING`
  - `ANALYZING`
  - `REPORTING`
  - `COMPLETED`
  - `FAILED`
  - `CANCELLED`
- Deterministic lifecycle transition validation.
- Lifecycle state persistence and audit metadata updates.
- Controlled failure behavior for invalid lifecycle transitions.
- EventBridge Scheduler integration for recurring and one-time schedules.
- Schedule type support for:
  - `baseline`
  - `burst`
  - `repeated`
  - `finalization`
- Baseline schedule default interval of 15 minutes.
- Initial MVP audit window of 48 hours.
- Maximum configured audit window of 48 hours.
- Audit-window start/end metadata used to bound scheduling and execution.
- Automatic one-time finalization trigger at audit-window completion.
- Scheduled execution event construction for the existing Phase 1 orchestrator/runner.
- Deterministic schedule naming using:
  - `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}` for baseline, burst, and repeated schedules.
  - `rcp-{stage}-{client_id}-{audit_id}-finalization` for finalization schedules.
  - Safe truncation with a deterministic hash suffix when required by AWS EventBridge Scheduler name length limits.
- Duplicate EventBridge Scheduler delivery handling using `schedule_occurrence_id` and DynamoDB occurrence claims.
- Scenario taxonomy support for:
  - `baseline_health`
  - `repeated_stability`
  - `burst_stability`
  - `invalid_payload_handling`
  - `missing_fields_validation`
  - `auth_failure_handling`
  - `timeout_sensitivity`
  - `response_consistency`
- Reliability category grouping:
  - **Stability:** `baseline_health`, `repeated_stability`, `burst_stability`, `response_consistency`
  - **Resilience:** `timeout_sensitivity`, `auth_failure_handling`
  - **Validation Robustness:** `invalid_payload_handling`, `missing_fields_validation`
- Operational safeguards for request caps, concurrency caps, environment restrictions, production-safe limits, audit expiration handling, and schedule expiration handling.
- Schedule creation failure handling that fails scheduling, rolls back created schedules where possible, transitions the audit to `FAILED`, and does not introduce `SCHEDULED_WITH_ERRORS`.
- Cancellation handling that attempts to delete or disable all associated EventBridge schedules, transitions the audit to `CANCELLED`, records any cleanup failures in `cleanup_errors`, and retains schedule metadata in DynamoDB for audit traceability.
- Zero-execution finalization handling that transitions to `FINALIZING`, records zero executions, and then transitions to `FAILED`.
- Valid future lifecycle transition definitions for `ANALYZING`, `REPORTING`, and `COMPLETED` without executing analytics, reporting, scoring, or completion workflows in Phase 3.
- Append-only lifecycle history and schedule metadata persistence for audit traceability.
- Temporary audit-scoped token handling metadata, including expiration tracking and recommended 48–72 hour validity.
- Unit-testable and integration-testable backend behavior.

### Out of Scope

The following are explicitly excluded from Phase 3:

- Frontend or dashboard implementation.
- User authentication.
- RBAC.
- Billing.
- Subscriptions.
- Multi-user account management.
- Self-serve onboarding.
- AI insights or AI-generated recommendations.
- Reliability scoring as a product feature.
- Analytics or report generation beyond emitting/recording the finalization event boundary.
- Automatic transition from `FINALIZING` to `ANALYZING`, from `ANALYZING` to `REPORTING`, or from `REPORTING` to `COMPLETED`.
- Advanced observability, distributed tracing, operational dashboards, or metrics products.
- Load testing, stress testing, uptime monitor clone behavior, synthetic monitoring product features, or chaos engineering.
- Heavy API frameworks.
- Changes to Phase 1 raw result schema versioning beyond backward-compatible metadata additions required for scheduled execution traceability.
- Replacement of Phase 1 orchestrator/runner execution contracts.
- Replacement of Phase 2 payload strategy, duplicate controls, fingerprints, or endpoint safety controls.
- Public customer-facing API, config authoring UI, or self-service schedule management UI.
- Long-lived client credentials or broad client-level execution permissions.

### Future Considerations

- UI for schedule configuration and lifecycle inspection.
- Operator-facing reports that summarize audit lifecycle and reliability categories.
- Automated analysis and reliability scoring after finalization.
- Advanced schedule optimization or adaptive cadence.
- Durable cross-audit concurrency governance across many customers or tenants.

## 7. Functional Requirements

### FR-001: Audit Lifecycle States

The system must represent each audit with exactly one lifecycle state from the approved state set: `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, `FAILED`, or `CANCELLED`.

Unknown lifecycle states must be rejected before persistence or transition processing.

### FR-002: Valid Lifecycle Transitions

The system must enforce the following lifecycle transition map:

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

Invalid transitions must fail with a controlled lifecycle error and must not partially update persisted audit state.

The `FINALIZING` -> `ANALYZING`, `ANALYZING` -> `REPORTING`, and `REPORTING` -> `COMPLETED` transitions are valid future transitions only. Phase 3 must define and validate these transitions in the state machine, but must not execute analytics workflows, reporting workflows, scoring workflows, or automatic completion behavior.

Phase 3 ownership stops at `FINALIZING` except for the zero-execution failure path. Phase 4 or later owns transitions beyond `FINALIZING`.

### FR-003: Lifecycle Transition Metadata

Every accepted lifecycle transition must persist transition metadata including at minimum:

- `client_id`
- `audit_id`
- previous lifecycle state
- next lifecycle state
- transition reason or trigger type
- transition timestamp
- actor/source, such as scheduler, orchestrator, finalization trigger, or system failure handler

Lifecycle metadata must include the current `lifecycle_state`, an append-only `lifecycle_history` array, and a `schedules` array for schedule traceability.

The persisted lifecycle metadata shape must support fields equivalent to:

```json
{
  "lifecycle_state": "SCHEDULED",
  "lifecycle_history": [
    {
      "from_state": "DRAFT",
      "to_state": "SCHEDULED",
      "timestamp": "...",
      "reason": "schedules_created"
    }
  ],
  "schedules": [
    {
      "schedule_name": "...",
      "schedule_type": "baseline",
      "scenario_type": "baseline_health",
      "status": "created"
    }
  ]
}
```

All lifecycle transitions must append a new entry to `lifecycle_history`. The system must not overwrite, truncate, or mutate previous lifecycle history entries during normal transition processing.

Transition metadata and schedule metadata must not include secrets, temporary token values, raw payloads, PII, or unsanitized response content.

### FR-003A: DynamoDB Key Shapes

Phase 3 audit lifecycle and scheduling records must use the following confirmed DynamoDB primary key shapes:

| Record Type | Partition Key (`PK`) | Sort Key (`SK`) |
| --- | --- | --- |
| Audit-level metadata | `CLIENT#{client_id}` | `AUDIT#{audit_id}` |
| Occurrence claim | `CLIENT#{client_id}` | `AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` |
| Run metadata | `CLIENT#{client_id}` | `AUDIT#{audit_id}#RUN#{run_id}` |

Audit-level metadata must persist lifecycle state, lifecycle history, schedule metadata, finalization metadata, and sanitized cleanup/failure metadata under the audit-level metadata key.

Occurrence claims must be persisted under the occurrence-claim key before outbound execution begins. The occurrence-claim key must be unique for one `client_id`, `audit_id`, and `schedule_occurrence_id`.

Run metadata must continue to use the existing run metadata key shape and must not be replaced by occurrence-claim records.

### FR-004: Audit Window

The MVP audit window must default to 48 hours and must not exceed `max_audit_window_hours = 48`.

Audit metadata must include enough information to determine audit-window start time, audit-window end time, and whether a schedule trigger is inside or outside the active audit window.

Schedule triggers occurring after audit-window completion must not start new baseline, burst, or repeated execution runs.

### FR-005: EventBridge Scheduler Integration

The system must create EventBridge Scheduler schedules for configured Phase 3 schedule types and must use scheduler events to invoke backend audit execution or lifecycle finalization.

Scheduler targets must pass only the minimum required execution metadata to the backend and must not embed secrets, raw client credentials, raw temporary token values, or unsafe payload data.

If one or more required schedules fail to create during audit scheduling, the system must fail audit scheduling, roll back already-created schedules where possible, transition the audit to `FAILED`, and record controlled failure metadata. Phase 3 must not introduce or persist a `SCHEDULED_WITH_ERRORS` lifecycle state.

### FR-005A: EventBridge Schedule Naming

The system must generate deterministic EventBridge Scheduler names using these patterns:

- Baseline, burst, and repeated schedules: `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}`
- Finalization schedules: `rcp-{stage}-{client_id}-{audit_id}-finalization`

Schedule names must preserve deterministic traceability to `stage`, `client_id`, `audit_id`, schedule type, and scenario type where applicable.

If the generated schedule name exceeds AWS EventBridge Scheduler name length limits, the system must safely truncate the name and append a deterministic hash suffix derived from the full untruncated name. The same schedule inputs must always produce the same truncated schedule name and hash suffix.

Truncation must not produce name collisions for distinct full schedule names within the supported hash collision tolerance selected by technical design.

### FR-006: Baseline Scheduling

Baseline schedules must run during the active audit window and must default to an interval of every 15 minutes.

Baseline execution is intended for latency trend analysis, intermittent failure tracking, and uptime consistency evidence. It must use the approved scenario type `baseline_health` unless explicitly configured to another approved scenario taxonomy value for a specific endpoint or audit segment.

### FR-007: Burst Scheduling

Burst schedules must support configurable execution windows per day, configurable concurrency, and configurable request counts.

Burst execution is intended for concurrency stability and transient degradation analysis. It must use the approved scenario type `burst_stability` unless explicitly configured to another approved scenario taxonomy value that remains within Phase 3 scope.

Burst configuration must be validated against request caps, concurrency caps, audit-window boundaries, and environment restrictions before schedules are created or execution begins.

Burst configuration must support the following shape:

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

Burst `start_time` values must be interpreted in the audit timezone when an audit timezone is provided. If no audit timezone is provided, burst `start_time` values must be interpreted as UTC.

Each burst window must have a positive `duration_minutes`, positive `request_count`, and positive `concurrency`, and must remain within the active audit window after timezone interpretation.

### FR-008: Repeated Scheduling

Repeated schedules must support repeated sequential execution and configurable iteration counts.

Repeated execution is intended for consistency and flaky behavior detection. It must use the approved scenario type `repeated_stability` unless explicitly configured to another approved scenario taxonomy value that remains within Phase 3 scope.

Repeated execution must preserve sequential behavior for the configured iteration set and must not convert repeated execution into concurrent burst behavior.

Before creating repeated schedules, the system must estimate whether the configured repeated execution can complete safely within applicable request, iteration, execution-duration, token-expiration, and audit-window limits.

If estimated repeated execution limits are unsafe, the system must fail scheduling before creating schedules or sending outbound API requests.

Phase 3 must not introduce chaining, follow-up executions, continuation schedules, or any mechanism that splits repeated execution across multiple chained scheduler invocations to bypass limits.

### FR-009: Finalization Trigger

For each scheduled audit, the system must create a one-time finalization trigger at audit-window completion.

When the finalization trigger fires and one or more executions exist, the system must transition the audit to `FINALIZING` if the current lifecycle state allows that transition and must record finalization metadata.

Finalization metadata must include at minimum `client_id`, `audit_id`, finalization trigger timestamp, audit-window start and end time, execution count, source schedule name, source schedule occurrence identifier when available, and transition result.

If the finalization trigger fires and zero executions exist, the system must transition the audit to `FINALIZING`, record finalization metadata with execution count `0`, and then transition the audit from `FINALIZING` to `FAILED`.

The finalization trigger must not perform analysis, reporting, scoring, or dashboard updates in Phase 3.

The finalization trigger must not auto-transition the audit to `ANALYZING`, `REPORTING`, or `COMPLETED` in Phase 3.

### FR-010: Scenario Taxonomy

The system must accept only the following Phase 3 scenario taxonomy values:

- `baseline_health`
- `repeated_stability`
- `burst_stability`
- `invalid_payload_handling`
- `missing_fields_validation`
- `auth_failure_handling`
- `timeout_sensitivity`
- `response_consistency`

Scenario taxonomy values must be treated as operational reliability dimensions, not generic test case names.

### FR-011: Reliability Category Grouping

The system must map approved scenario taxonomy values to these reliability categories:

- **Stability:** `baseline_health`, `repeated_stability`, `burst_stability`, `response_consistency`
- **Resilience:** `timeout_sensitivity`, `auth_failure_handling`
- **Validation Robustness:** `invalid_payload_handling`, `missing_fields_validation`

Unknown scenario taxonomy values or unknown category mappings must fail validation before schedule creation or execution.

### FR-012: Scheduled Execution Event Contract

Scheduled execution events must include the minimum metadata required for the existing orchestrator to execute an audit run, including fields equivalent to:

- `client_id`
- `audit_id`
- `scenario_type`
- `triggered_by`
- schedule type
- `schedule_occurrence_id`
- schedule occurrence timestamp

Scheduled execution events created by EventBridge Scheduler must omit `run_id`.

For accepted scheduled execution events, the backend must create a new execution result set with a newly generated `run_id` using the existing Phase 1 run ID generation and validation behavior.

The `schedule_occurrence_id` is the idempotency control for duplicate EventBridge Scheduler delivery. Duplicate delivery handling must be based on the occurrence-claim record, not on a scheduler-supplied `run_id`.

The `schedule_occurrence_id` must deterministically identify one intended schedule occurrence for one `client_id`, `audit_id`, schedule name, schedule type, scenario type, and occurrence timestamp.

### FR-012A: Duplicate Scheduler Delivery Handling

Before starting outbound execution for a scheduled event, the system must attempt to store an occurrence claim in DynamoDB using `schedule_occurrence_id` and audit identity metadata.

The occurrence claim must use `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.

If the occurrence claim succeeds, the system may continue normal safeguard validation and execution.

If the occurrence claim already exists, the system must treat the event as a duplicate EventBridge delivery, skip execution, avoid outbound API requests, avoid creating a duplicate run, and log a sanitized duplicate delivery event.

If the occurrence claim cannot be written or verified because DynamoDB is unavailable or returns an indeterminate error, the system must block execution, avoid outbound API requests, and record a sanitized controlled failure or skipped execution event.

The sanitized duplicate delivery event must include non-sensitive traceability fields such as `client_id`, `audit_id`, schedule type, scenario type, schedule name, and `schedule_occurrence_id`, and must not include secrets, raw temporary token values, raw payloads, PII, or unsanitized response content.

### FR-013: Operational Safeguards

The system must validate scheduled execution against operational safeguards before execution:

- request caps
- concurrency caps
- environment restrictions
- production-safe limits
- audit-window expiration
- temporary token expiration

If any safeguard validation fails, the system must block the affected execution and record a controlled failure or skipped execution event without sending outbound API requests.

The system must enforce these default operational caps for non-production execution unless stricter configured limits apply:

| Cap | Value |
| --- | --- |
| `max_requests_per_run` | `100` |
| `max_concurrency` | `5` |
| `max_burst_requests_per_window` | `500` |
| `max_repeated_iterations` | `100` |
| `max_audit_window_hours` | `48` |

The system must enforce these production-safe caps when `execution_environment.target_environment = "production"`:

| Cap | Value |
| --- | --- |
| `prod_max_requests_per_run` | `25` |
| `prod_max_concurrency` | `2` |
| `prod_max_burst_requests_per_window` | `100` |
| `prod_requires_explicit_allow_production` | `true` |

### FR-014: Environment Restrictions

The system must support environment restrictions that prevent unsafe schedules from executing against disallowed environments.

Production execution must be subject to the confirmed production-safe request, concurrency, and burst-window limits defined in FR-013.

The environment restrictions configuration must support fields equivalent to:

```json
{
  "execution_environment": {
    "target_environment": "staging",
    "allow_production_execution": false
  }
}
```

If `execution_environment.target_environment = "production"` and `execution_environment.allow_production_execution != true`, the system must block both scheduling and execution before any outbound API requests occur.

If production execution is explicitly allowed, production-safe caps must still be enforced before schedule creation and before execution.

### FR-015: Audit Expiration Handling

The system must prevent baseline, burst, and repeated executions after the audit window expires.

Expired audits must be eligible for transition to `FINALIZING` through the finalization trigger or system expiration handling when the current state permits it.

If finalization occurs and the audit has recorded zero executions, the system must transition to `FINALIZING`, persist metadata indicating zero executions, and then transition to `FAILED`.

### FR-016: Cancellation Handling

When an audit is cancelled from a cancellable lifecycle state, the system must delete or disable all associated EventBridge schedules.

After associated schedule cleanup is attempted, the audit must transition to `CANCELLED` when the lifecycle transition is valid, even if one or more schedule cleanup operations fail.

If any schedule cleanup operation fails, the system must record the failure details in `cleanup_errors` using sanitized metadata. `cleanup_errors` must identify the affected schedule, cleanup operation attempted, failure category or sanitized error code/message, and timestamp, without storing secrets, raw scheduler payloads, credentials, PII, or unsanitized provider responses.

The system must retain schedule metadata in DynamoDB for audit traceability after cancellation. Retained metadata must identify associated schedules and their cleanup status without retaining secrets or raw scheduler payloads.

### FR-017: Temporary Token Handling

Temporary client tokens must be audit-scoped, least-privilege, and tracked with expiration metadata.

The recommended token validity window is 48–72 hours. Tokens must not be persisted in raw form in lifecycle metadata, schedule input, raw results, logs, or finalization events.

Execution must be blocked if the required audit-scoped token is expired before the scheduled run starts.

### FR-018: Preservation of Existing Phase Contracts

Phase 3 must not bypass or weaken existing Phase 1 and Phase 2 behavior, including:

- Phase 1 orchestrator execution flow.
- Raw result schema v1 compatibility.
- S3/DynamoDB/Secrets wrappers.
- Centralized sanitization.
- Strict `run_id` validation.
- Duplicate `run_id` protection.
- Phase 2 payload strategy validation.
- Phase 2 duplicate payload controls.
- Phase 2 payload and response fingerprinting.
- Phase 2 endpoint safety controls.

## 8. Acceptance Criteria

### AC-001: Lifecycle State Validation

Given an audit lifecycle state value outside the approved state list  
When the system validates or persists the audit lifecycle  
Then the system rejects the state with a controlled validation error and does not persist the invalid state.

### AC-002: Valid Lifecycle Transition

Given an audit in `DRAFT` state  
When the system transitions the audit to `SCHEDULED`  
Then the transition succeeds and persisted lifecycle metadata records `DRAFT` as the previous state and `SCHEDULED` as the next state.

### AC-002A: Append-Only Lifecycle History

Given an audit has existing entries in `lifecycle_history`  
When the system performs a valid lifecycle transition  
Then the system appends one new transition entry and does not overwrite, remove, truncate, or mutate previous `lifecycle_history` entries.

### AC-003: Invalid Lifecycle Transition

Given an audit in `COMPLETED` state  
When the system attempts to transition the audit to `RUNNING`  
Then the transition is rejected with a controlled lifecycle error and the persisted state remains `COMPLETED`.

### AC-004: Baseline Schedule Default

Given a scheduled audit with no custom baseline interval configured  
When Phase 3 creates baseline scheduling  
Then the baseline schedule uses a 15-minute interval bounded by the audit window.

### AC-005: Audit Window Default

Given a new Phase 3 scheduled audit with no approved custom audit-window duration  
When the system calculates the audit-window end time  
Then the end time is 48 hours after the audit-window start time.

### AC-005A: Audit Window Cap

Given a Phase 3 scheduled audit configuration requests an audit window greater than 48 hours  
When the system validates audit-window configuration  
Then validation fails before schedules are created because `max_audit_window_hours` is `48`.

### AC-006: EventBridge Scheduler Creation

Given a valid scheduled audit configuration  
When Phase 3 schedules recurring execution  
Then EventBridge Scheduler schedules are created for the configured baseline, burst, repeated, and finalization schedule types that apply to the audit.

### AC-006A: Schedule Creation Failure Rollback

Given schedule creation partially succeeds and a required subsequent schedule fails to create  
When Phase 3 handles the schedule creation failure  
Then the system rolls back already-created schedules where possible, transitions the audit to `FAILED`, records controlled failure metadata, and does not persist `SCHEDULED_WITH_ERRORS`.

### AC-006B: Schedule Metadata Persistence

Given schedules are successfully created for an audit  
When lifecycle metadata is persisted  
Then the metadata includes schedule entries with `schedule_name`, `schedule_type`, `scenario_type`, and `status` values for audit traceability.

### AC-006B.1: Audit-Level Metadata Key Shape

Given audit-level lifecycle or scheduling metadata is persisted for `client_id = client123` and `audit_id = audit456`  
When the system writes the audit metadata record to DynamoDB  
Then the record uses `PK = CLIENT#client123` and `SK = AUDIT#audit456`.

### AC-006B.2: Run Metadata Key Shape

Given run metadata is persisted for `client_id = client123`, `audit_id = audit456`, and generated `run_id = run789`  
When the system writes the run metadata record to DynamoDB  
Then the record uses `PK = CLIENT#client123` and `SK = AUDIT#audit456#RUN#run789`.

### AC-006C: Deterministic Schedule Naming

Given a baseline, burst, or repeated schedule is created for stage `staging`, client `client123`, audit `audit456`, schedule type `baseline`, and scenario type `baseline_health`  
When the system generates the EventBridge Scheduler name  
Then the generated name is `rcp-staging-client123-audit456-baseline-baseline_health` unless AWS length limits require safe truncation.

### AC-006D: Finalization Schedule Naming

Given a finalization schedule is created for stage `staging`, client `client123`, and audit `audit456`  
When the system generates the EventBridge Scheduler name  
Then the generated name is `rcp-staging-client123-audit456-finalization` unless AWS length limits require safe truncation.

### AC-006E: Schedule Name Safe Truncation

Given a generated schedule name exceeds AWS EventBridge Scheduler name length limits  
When the system persists or creates the schedule  
Then the system truncates the name safely and appends a deterministic hash suffix derived from the full untruncated name.

### AC-007: Scheduled Event Minimal Payload

Given an EventBridge Scheduler execution event  
When the system inspects the scheduler target payload  
Then the payload contains execution metadata only and does not contain secrets, raw temporary tokens, raw payloads, PII, or unsanitized response content.

### AC-007A: Scheduled Execution Event Omits Run ID

Given an EventBridge Scheduler execution event for a baseline, burst, or repeated occurrence  
When the system inspects the scheduler target payload  
Then the payload does not include `run_id`.

### AC-007B: Scheduled Occurrence Creates New Run ID

Given an active audit window and a scheduled execution event without `run_id`  
When the system accepts the occurrence claim and starts execution  
Then the backend creates a new execution result set with a newly generated `run_id` using existing Phase 1 run ID generation and validation behavior.

### AC-008: Baseline Execution Trigger

Given an active audit window and a baseline schedule occurrence  
When EventBridge Scheduler invokes the backend execution target  
Then the system invokes the existing orchestrator with approved scenario metadata and preserves Phase 1 generated run ID validation and duplicate protection.

### AC-008A: Scheduled Occurrence Claim

Given an active audit window and a scheduled event with a new `schedule_occurrence_id`  
When the system receives the event  
Then the system stores an occurrence claim in DynamoDB before starting outbound execution.

### AC-008A.1: Occurrence Claim Key Shape

Given a scheduled event for `client_id = client123`, `audit_id = audit456`, and `schedule_occurrence_id = occurrence789`  
When the system stores the occurrence claim in DynamoDB  
Then the occurrence claim uses `PK = CLIENT#client123` and `SK = AUDIT#audit456#OCCURRENCE#occurrence789`.

### AC-008B: Duplicate Scheduler Delivery Skip

Given DynamoDB already contains an occurrence claim for a received `schedule_occurrence_id`  
When EventBridge Scheduler delivers the same occurrence again  
Then the system skips execution, does not send outbound API requests, does not create a duplicate run, and logs a sanitized duplicate delivery event.

### AC-008C: Occurrence Claim Failure Block

Given DynamoDB cannot write or verify the occurrence claim for a scheduled event  
When the system receives the scheduled event  
Then the system blocks execution, does not send outbound API requests, and records a sanitized controlled failure or skipped execution event.

### AC-009: Burst Safeguard Validation

Given a burst schedule configuration with concurrency above the configured concurrency cap  
When the system validates the burst schedule  
Then the schedule is rejected or blocked before outbound API execution occurs.

### AC-009A: Default Operational Caps Enforcement

Given a non-production audit configuration exceeds `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, or `max_audit_window_hours = 48`  
When the system validates scheduling or execution safeguards  
Then the system rejects or blocks the affected schedule or execution before outbound API requests occur.

### AC-009B: Production-Safe Caps Enforcement

Given production execution is explicitly allowed and a production audit configuration exceeds `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, or `prod_max_burst_requests_per_window = 100`  
When the system validates scheduling or execution safeguards  
Then the system rejects or blocks the affected schedule or execution before outbound API requests occur.

### AC-010: Burst Execution Metadata

Given a valid burst schedule configuration  
When a burst execution occurrence is triggered within the audit window  
Then the execution metadata identifies schedule type `burst`, configured request count, configured concurrency, and an approved scenario taxonomy value.

### AC-010A: Burst Window Timezone Interpretation

Given a burst schedule window with `start_time` of `09:00` and an audit timezone is provided  
When the system calculates the burst window occurrence time  
Then `09:00` is interpreted in the audit timezone.

### AC-010B: Burst Window UTC Default

Given a burst schedule window with `start_time` of `09:00` and no audit timezone is provided  
When the system calculates the burst window occurrence time  
Then `09:00` is interpreted as UTC.

### AC-011: Repeated Sequential Execution

Given a repeated schedule configured for a finite iteration count  
When the schedule triggers execution  
Then the system executes the configured iterations sequentially and does not execute those repeated iterations concurrently as burst traffic.

### AC-012: Repeated Iteration Cap

Given a repeated schedule with iteration count above the configured cap  
When the system validates the schedule  
Then the schedule is rejected or blocked before outbound API execution occurs.

### AC-012A: Unsafe Repeated Execution Estimate

Given a repeated schedule whose estimated execution exceeds applicable request, iteration, execution-duration, token-expiration, or audit-window limits  
When the system validates the schedule  
Then scheduling fails before schedules are created and before outbound API execution occurs.

### AC-012B: No Repeated Execution Chaining

Given a repeated schedule cannot safely complete within Phase 3 limits  
When the system evaluates scheduling options  
Then the system does not create chained, follow-up, continuation, or limit-bypassing scheduler executions.

### AC-013: Finalization Trigger

Given an audit in `RUNNING` state at audit-window completion with one or more recorded executions  
When the one-time finalization trigger fires  
Then the audit transitions to `FINALIZING`, finalization metadata is recorded, and no Phase 3 analysis, reporting, scoring, dashboard update, or auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED` is performed.

### AC-013A: Finalization With Zero Executions

Given an audit reaches audit-window completion with zero recorded executions  
When finalization is triggered  
Then the audit transitions to `FINALIZING`, records zero executions in audit metadata, and then transitions to `FAILED`.

### AC-013B: Future Transition Definition Only

Given an audit is in `FINALIZING` after Phase 3 finalization with one or more recorded executions  
When Phase 3 completes finalization metadata recording  
Then the audit remains in `FINALIZING` until a Phase 4 or later workflow performs a valid future transition.

### AC-014: Expired Audit Execution Block

Given a baseline, burst, or repeated schedule occurrence after the audit-window end time  
When the schedule attempts to trigger execution  
Then the system blocks the execution and does not send outbound API requests.

### AC-015: Scenario Taxonomy Rejection

Given a schedule configuration with scenario type `generic_api_test`  
When the system validates the schedule configuration  
Then validation fails because the scenario type is not in the approved Phase 3 taxonomy.

### AC-016: Reliability Category Mapping

Given scenario type `timeout_sensitivity`  
When the system maps the scenario to a reliability category  
Then the system maps it to `Resilience`.

### AC-017: Environment Restriction Enforcement

Given a schedule configured for an environment that is not allowed by audit safeguards  
When the schedule attempts to execute  
Then execution is blocked before outbound requests occur and a controlled failure or skipped execution event is recorded.

### AC-017A: Production Scheduling Block Without Explicit Allow

Given `execution_environment.target_environment` is `production` and `execution_environment.allow_production_execution` is not `true`  
When the system validates audit scheduling  
Then scheduling is blocked and no EventBridge schedules are created.

### AC-017B: Production Execution Block Without Explicit Allow

Given `execution_environment.target_environment` is `production` and `execution_environment.allow_production_execution` is not `true`  
When a schedule attempts to trigger execution  
Then execution is blocked before outbound API requests occur.

### AC-018: Temporary Token Expiration

Given an audit-scoped temporary token that expires before a scheduled run starts  
When the scheduled run is triggered  
Then the system blocks execution and does not expose the raw token value in logs, schedule payloads, lifecycle metadata, or raw results.

### AC-019: Terminal State Protection

Given an audit in `FAILED`, `CANCELLED`, or `COMPLETED` state  
When a recurring schedule event attempts to start execution  
Then the system does not start execution and does not transition the audit back to `RUNNING`.

### AC-020: Existing Contract Preservation

Given a scheduled execution event created by Phase 3  
When the existing Phase 1 orchestrator and Phase 2 payload handling execute the run  
Then raw result schema v1 compatibility, sanitization, generated `run_id` validation, duplicate `run_id` protection, payload strategy validation, duplicate payload controls, and endpoint safety controls remain enforced.

### AC-021: Cancellation Schedule Cleanup

Given an audit with associated EventBridge schedules is in a cancellable lifecycle state  
When the audit is cancelled  
Then the system deletes or disables all associated EventBridge schedules, transitions the audit to `CANCELLED`, and retains schedule metadata in DynamoDB for audit traceability.

### AC-021A: Cancellation Cleanup Failure Recording

Given an audit cancellation attempts to delete or disable associated EventBridge schedules and one cleanup operation fails  
When the cancellation flow completes  
Then the audit transitions to `CANCELLED` and sanitized cleanup failure details are recorded in `cleanup_errors`.

### AC-022: No SCHEDULED_WITH_ERRORS State

Given any Phase 3 scheduling failure path  
When the system records the audit lifecycle outcome  
Then the system uses only approved lifecycle states and never persists `SCHEDULED_WITH_ERRORS`.

## 9. Edge Cases

- EventBridge Scheduler fires after the audit window has expired.
- EventBridge Scheduler fires while the audit is in a terminal state.
- Finalization trigger fires when the audit is still `SCHEDULED` and no run is currently active.
- Finalization trigger fires more than once due to retry or duplicate scheduler delivery.
- Duplicate EventBridge Scheduler delivery arrives with the same `schedule_occurrence_id` after the original occurrence claim was stored.
- Duplicate EventBridge Scheduler delivery arrives while the original occurrence is still executing.
- DynamoDB occurrence claim write fails before execution starts.
- A scheduled event is delivered out of order relative to lifecycle state changes.
- Generated EventBridge schedule name exceeds AWS Scheduler length limits and requires deterministic hash-suffix truncation.
- Two long generated schedule names share the same leading truncated prefix and must still produce distinct deterministic hash suffixes.
- Burst execution overlaps with baseline execution within the same audit window.
- Burst `start_time` is interpreted across timezone offset boundaries or daylight-saving transitions.
- Burst configuration omits audit timezone and must default to UTC interpretation.
- Burst configuration exceeds request caps or concurrency caps.
- Repeated configuration exceeds iteration caps.
- Repeated execution estimate is unsafe because it cannot complete before audit-window end or token expiration.
- Repeated execution would require chained or follow-up scheduler invocations to complete.
- Temporary token expires between schedule creation and execution.
- Temporary token validity is shorter than the configured audit window.
- Schedule creation partially succeeds and one schedule type fails.
- Schedule creation partially succeeds and rollback of one already-created EventBridge schedule fails.
- Audit is cancelled after schedules are created but before the next scheduled execution.
- Audit cancellation occurs while EventBridge Scheduler concurrently delivers a schedule event.
- Audit cancellation cleanup can delete some schedules but must disable others due to provider/API behavior.
- Audit cancellation cleanup fails for one or more schedules and must still transition to `CANCELLED` with `cleanup_errors`.
- Finalization occurs for an audit with zero recorded executions.
- Finalization occurs for an audit with one or more executions and must remain in `FINALIZING` without Phase 3 analytics/reporting transitions.
- Audit configuration uses an unknown scenario taxonomy value.
- Reliability category mapping is missing or inconsistent for an approved scenario.
- Production environment is configured with unsafe request counts, concurrency, or burst windows.
- Production environment is configured without `allow_production_execution = true`.
- Lifecycle metadata already contains prior history entries when a new transition is processed.
- A scheduler event payload is malformed and includes a `run_id` even though Phase 3 EventBridge-triggered execution events must omit `run_id`.
- A valid scheduled occurrence creates a new generated `run_id`, and duplicate EventBridge delivery for the same occurrence must still be controlled by `schedule_occurrence_id`, not by run metadata.
- DynamoDB audit-level metadata, occurrence-claim records, and run metadata are written for the same audit and must remain distinguishable by their confirmed `SK` shapes.

## 10. Constraints

- Architecture must remain backend-first, AWS-native, event-driven, deterministic, and evidence-driven.
- EventBridge Scheduler is the required scheduling integration for Phase 3.
- EventBridge schedule names must use the confirmed deterministic naming patterns and safe deterministic hash-suffix truncation when AWS length limits require it.
- Scheduled event payloads must include `schedule_occurrence_id`.
- EventBridge-triggered scheduled execution payloads must omit `run_id`; accepted scheduled occurrences must create new execution result sets with newly generated `run_id` values.
- Duplicate scheduled occurrences must be detected by DynamoDB occurrence claims before outbound execution starts.
- DynamoDB audit-level metadata records must use `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}`.
- DynamoDB occurrence-claim records must use `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- DynamoDB run metadata records must continue to use `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Existing Phase 1 orchestrator, runner, S3 wrapper, DynamoDB wrapper, Secrets wrapper, sanitization, strict `run_id` validation, and duplicate `run_id` protection must remain authoritative.
- Existing Phase 2 payload strategy, payload metadata, duplicate payload controls, fingerprints, and endpoint safety controls must remain authoritative.
- Scheduled execution must be bounded by audit-window start and end times.
- Initial MVP audit window is 48 hours and `max_audit_window_hours` is 48.
- Baseline default cadence is every 15 minutes.
- Burst window `start_time` values are interpreted in the audit timezone when provided and UTC otherwise.
- Default operational caps are fixed for Phase 3 as `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, and `max_audit_window_hours = 48`.
- Production-safe caps are fixed for Phase 3 as `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, and `prod_requires_explicit_allow_production = true`.
- Production scheduling and execution must be blocked unless `execution_environment.target_environment = "production"` and `execution_environment.allow_production_execution = true` are both explicitly configured.
- Schedule creation failure must transition the audit to `FAILED`; Phase 3 must not introduce `SCHEDULED_WITH_ERRORS`.
- Repeated execution must fail scheduling if estimated limits are unsafe; Phase 3 must not use chaining or follow-up executions to bypass limits.
- Cancellation must attempt to delete or disable associated EventBridge schedules, transition to `CANCELLED`, record sanitized `cleanup_errors` for cleanup failures, and retain schedule metadata for audit traceability.
- Lifecycle history must be append-only; previous transition entries must not be overwritten during normal lifecycle processing.
- `ANALYZING`, `REPORTING`, and `COMPLETED` are valid future lifecycle states/transitions only; Phase 3 must not execute analytics/reporting workflows or auto-transition beyond `FINALIZING` except `FINALIZING` -> `FAILED` for zero executions.
- Scenario taxonomy must be treated as operational reliability dimensions rather than generic tests.
- Schedule payloads and lifecycle metadata must not contain secrets, raw token values, credentials, cookies, PII, raw payloads, or unsanitized response data.
- Temporary execution tokens must be audit-scoped, least-privilege, and expiration-tracked.
- Production-safe request and concurrency limits must be enforced before outbound execution.
- Phase 3 must not introduce UI, auth/RBAC, billing, AI insights, report generation, load testing, uptime monitor clone behavior, chaos engineering, or heavy API frameworks.

## 11. Dependencies

- Phase 1 core engine foundation is merged and available:
  - orchestrator
  - runner
  - raw result schema v1
  - sanitization
  - S3/DynamoDB/Secrets wrappers
  - strict `run_id` validation
  - duplicate `run_id` protection
- Phase 2 payload/data generation is merged and available:
  - static/generated/data_pool payload strategies
  - payload and response fingerprints
  - duplicate payload controls
  - payload metadata
  - endpoint safety controls
- AWS EventBridge Scheduler is available in the target deployment environment.
- AWS IAM permissions can be configured for schedule creation, schedule invocation, and least-privilege audit execution.
- Persistent audit metadata storage is available through the existing DynamoDB wrapper or approved metadata persistence mechanism.
- DynamoDB-backed audit metadata persistence is available for retaining lifecycle history and schedule metadata after cancellation or failure.
- DynamoDB-backed occurrence-claim storage is available for idempotent `schedule_occurrence_id` claiming before scheduled execution.
- Existing Secrets Manager integration is available for resolving secret references and temporary token references without exposing raw values.

## 12. Assumptions

- Confirmed Phase 3 decision: default operational caps are `max_requests_per_run = 100`, `max_concurrency = 5`, `max_burst_requests_per_window = 500`, `max_repeated_iterations = 100`, and `max_audit_window_hours = 48`.
- Confirmed Phase 3 decision: production-safe caps are `prod_max_requests_per_run = 25`, `prod_max_concurrency = 2`, `prod_max_burst_requests_per_window = 100`, and `prod_requires_explicit_allow_production = true`.
- Confirmed Phase 3 decision: production scheduling and execution are blocked unless `allow_production_execution = true` when `target_environment = "production"`.
- Confirmed Phase 3 decision: custom audit windows must not exceed 48 hours.
- Confirmed Phase 3 decision: EventBridge schedules use `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}` for baseline, burst, and repeated schedules; finalization uses `rcp-{stage}-{client_id}-{audit_id}-finalization`; names are safely truncated with a deterministic hash suffix if AWS limits require it.
- Confirmed Phase 3 decision: scheduled event payloads include `schedule_occurrence_id`, duplicate EventBridge deliveries are claimed through DynamoDB occurrence storage, and duplicate occurrences are skipped and logged as sanitized duplicate delivery events.
- Confirmed Phase 3 decision: DynamoDB key shapes are `PK = CLIENT#{client_id}` / `SK = AUDIT#{audit_id}` for audit-level metadata, `PK = CLIENT#{client_id}` / `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}` for occurrence claims, and `PK = CLIENT#{client_id}` / `SK = AUDIT#{audit_id}#RUN#{run_id}` for run metadata.
- Confirmed Phase 3 decision: EventBridge-triggered scheduled execution events omit `run_id`; each accepted scheduled occurrence creates a new execution result set with a newly generated `run_id`, and duplicate EventBridge delivery is controlled by `schedule_occurrence_id` occurrence claims.
- Confirmed Phase 3 decision: burst schedule windows use the documented `burst_schedule.enabled` and `burst_schedule.windows[]` configuration shape, with `start_time` interpreted in the audit timezone when provided and UTC otherwise.
- Confirmed Phase 3 decision: cancellation transitions to `CANCELLED` after cleanup is attempted, with sanitized `cleanup_errors` recorded for cleanup failures.
- Confirmed Phase 3 decision: repeated execution must fail scheduling when estimated limits are unsafe and must not use chaining or follow-up execution in Phase 3.
- Confirmed Phase 3 decision: `ANALYZING`, `REPORTING`, and `COMPLETED` are valid future transitions only; Phase 3 finalization records metadata and remains in `FINALIZING` unless zero executions require `FINALIZING` -> `FAILED`.
- Audit-scoped temporary tokens are referenced indirectly through Secrets Manager-compatible references or equivalent secure references, not embedded directly in schedules.

## 13. Open Questions

- No open product questions remain for the confirmed Phase 3 decisions in this specification.
- Technical design must still choose implementation-level non-key DynamoDB attribute names, hash algorithm/length, and provider retry parameters while preserving the product requirements in this document.

## 14. Definition of Done

Phase 3 is done when:

- The product specification is approved for Phase 3 scope only.
- Lifecycle states and allowed transitions are implemented exactly as specified or approved changes are reflected in this document.
- EventBridge Scheduler-backed baseline, burst, repeated, and finalization schedule types are implemented and testable.
- EventBridge schedule names follow the confirmed deterministic naming patterns and apply deterministic hash-suffix truncation when AWS length limits require it.
- Scheduled events include `schedule_occurrence_id`, omit `run_id`, DynamoDB occurrence claims are stored before execution using the confirmed occurrence-claim key shape, and duplicate deliveries are skipped with sanitized duplicate delivery logs.
- Audit-level metadata and run metadata use the confirmed DynamoDB key shapes.
- Baseline scheduling defaults to every 15 minutes during a 48-hour MVP audit window.
- Burst schedule configuration supports `burst_schedule.enabled` and `burst_schedule.windows[]`, and burst `start_time` values are interpreted in the audit timezone when provided and UTC otherwise.
- Burst and repeated schedules enforce default operational caps, production-safe caps, and environment restrictions before scheduling and execution.
- Repeated schedules validate estimated execution safety and fail scheduling when unsafe without chaining or follow-up executions.
- Production scheduling and execution are blocked unless explicitly allowed through `execution_environment.allow_production_execution = true`.
- Schedule creation failure rolls back created schedules where possible, transitions the audit to `FAILED`, and never persists `SCHEDULED_WITH_ERRORS`.
- Cancellation attempts to delete or disable all associated EventBridge schedules, transitions the audit to `CANCELLED`, records sanitized `cleanup_errors` for cleanup failures, and retains schedule metadata in DynamoDB.
- Lifecycle metadata persists `lifecycle_state`, append-only `lifecycle_history`, and `schedules` traceability entries.
- Finalization with zero executions transitions to `FINALIZING`, records zero executions, and then transitions to `FAILED`.
- The finalization trigger transitions eligible audits with executions to `FINALIZING`, records finalization metadata, and does not auto-transition to `ANALYZING`, `REPORTING`, or `COMPLETED`.
- `ANALYZING`, `REPORTING`, and `COMPLETED` are defined as valid future transitions only; Phase 4 or later owns transitions beyond `FINALIZING` except the Phase 3 zero-execution failure path.
- Approved scenario taxonomy and reliability category grouping are validated and persisted for scheduled executions.
- Temporary token expiration metadata is enforced without exposing raw token values.
- Expired, cancelled, failed, or completed audits do not produce new outbound scheduled executions.
- Phase 1 and Phase 2 contracts remain intact and are covered by regression validation.
- QA has testable Given/When/Then acceptance criteria for lifecycle, scheduling, safeguards, taxonomy, and expiration behavior.
