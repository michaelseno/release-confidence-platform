# Test Plan

## 1. Feature Overview

Phase 3 validates the backend-only audit scheduling and lifecycle layer for the Release Confidence Platform on branch `feature/phase_3_audit_scheduling_lifecycle`.

Scope is limited to:

- deterministic audit lifecycle state management
- append-only audit lifecycle metadata and schedule traceability
- EventBridge Scheduler wrappers and schedule builders for baseline, burst, repeated, and finalization schedules
- deterministic schedule naming and safe truncation
- audit window defaults/caps and execution-time expiration guards
- operational caps, production restrictions, scenario taxonomy, reliability category grouping, and temporary token metadata validation
- DynamoDB key shapes for audit metadata, occurrence claims, and existing Phase 1 run metadata
- scheduled execution contracts that omit `run_id` and generate run IDs through the existing Phase 1 orchestrator boundary
- duplicate EventBridge delivery suppression using `schedule_occurrence_id` occurrence claims
- schedule creation rollback, cancellation cleanup, and finalization behavior

Out of scope for Phase 3 QA approval:

- frontend/dashboard behavior
- public customer-facing APIs
- auth/RBAC/billing/subscriptions
- analytics/reporting/scoring workflows beyond finalization boundary metadata
- load testing, stress testing, chaos engineering, or uptime-monitor clone behavior

Primary upstream artifacts:

- Product spec: `docs/product/phase_3_audit_scheduling_lifecycle_product_spec.md`
- Technical design: `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`

## 2. Acceptance Criteria Mapping

| AC | Requirement Summary | Test Coverage |
| --- | --- | --- |
| AC-001 | Reject unknown lifecycle states before persistence | Unit tests for state validator and persistence guard; negative integration with mocked DynamoDB confirms no write. |
| AC-002 | Valid `DRAFT -> SCHEDULED` transition persists previous/next state | Unit lifecycle transition test; integration schedule success path verifies persisted audit metadata. |
| AC-002A | Lifecycle history is append-only | Unit and repository tests verify list append, prior entries unchanged, no truncation/mutation. |
| AC-003 | Invalid `COMPLETED -> RUNNING` rejected and state unchanged | Unit transition table tests; repository integration verifies conditional update does not mutate state. |
| AC-004 | Baseline default interval is 15 minutes | Schedule builder unit test verifies `rate(15 minutes)` or equivalent safe schedule definition. |
| AC-005 | Default audit window is 48 hours | Validator unit test verifies default end time = start + 48h. |
| AC-005A | Audit window >48h rejected before schedules | Validator unit and scheduling integration tests verify no EventBridge create calls. |
| AC-006 | EventBridge schedules created for applicable baseline/burst/repeated/finalization types | Integration test with mocked EventBridge verifies create calls and definitions. |
| AC-006A | Partial schedule creation failure rolls back and transitions `FAILED` | Integration failure test verifies rollback attempts, sanitized failure metadata, no `SCHEDULED_WITH_ERRORS`. |
| AC-006B | Schedule metadata persisted with required traceability fields | Unit metadata shape tests; integration DynamoDB assertions. |
| AC-006B.1 | Audit metadata key shape | Repository unit/integration assertions for `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`. |
| AC-006B.2 | Run metadata key shape remains Phase 1 shape | Regression integration at orchestrator boundary verifies `SK=AUDIT#{audit_id}#RUN#{run_id}`. |
| AC-006C | Baseline/burst/repeated deterministic schedule naming | Schedule naming unit tests for exact names and repeated deterministic output. |
| AC-006D | Finalization deterministic schedule naming | Schedule naming unit tests for finalization pattern without scenario suffix. |
| AC-006E | Long names safely truncate with deterministic hash suffix | Unit tests for max length, stable hash, distinct suffixes for colliding prefixes. |
| AC-007 | Scheduler payload contains metadata only, no secrets/raw payloads/PII | Unit payload builder tests and security assertions. |
| AC-007A | Scheduler execution event omits `run_id` | Unit event contract tests; integration verifies rejected malformed inbound event with `run_id`. |
| AC-007B | Accepted occurrence creates new generated Phase 1 run ID | Integration test with mocked orchestrator verifies scheduler input has no `run_id`, returned/generated `run_id` is captured after claim. |
| AC-008 | Baseline occurrence invokes existing orchestrator preserving Phase 1 behavior | Integration boundary test verifies orchestrator call contract, sanitization path, duplicate run ID protection not bypassed. |
| AC-008A | Occurrence claim stored before outbound execution | Integration order assertion: DynamoDB claim conditional put occurs before orchestrator invocation. |
| AC-008A.1 | Occurrence claim key shape | Repository/handler test asserts `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`. |
| AC-008B | Duplicate scheduler delivery skipped | Integration duplicate claim test verifies no outbound/orchestrator call, no duplicate run, sanitized duplicate log. |
| AC-008C | Occurrence claim write/verify failure blocks execution | Negative integration test simulates DynamoDB indeterminate error; verifies no outbound/orchestrator call. |
| AC-009 | Burst concurrency above cap rejected/blocked | Validator unit tests and scheduling integration no-create assertion. |
| AC-009A | Default operational caps enforced | Unit parameterized cap boundary tests and execution-time guard tests. |
| AC-009B | Production caps enforced when production explicitly allowed | Unit and integration tests for prod request/concurrency/burst caps. |
| AC-010 | Burst execution metadata includes type, request count, concurrency, scenario | Event builder and handler integration tests. |
| AC-010A | Burst time interpreted in audit timezone | Unit timezone calculation tests including DST boundary where deterministic. |
| AC-010B | Burst time defaults to UTC without audit timezone | Unit timezone default test. |
| AC-011 | Repeated execution is sequential, not concurrent | Unit test with ordered mocked orchestrator calls; verifies next iteration starts after previous completes. |
| AC-012 | Repeated iteration count above cap rejected | Validator unit boundary tests at 100 and 101. |
| AC-012A | Unsafe repeated runtime/request/token/window estimate fails before schedules/outbound | Unit estimator tests and scheduling integration no-create assertion. |
| AC-012B | No repeated chaining/follow-up/continuation schedules | Builder/service tests verify no chained schedule artifacts are created for unsafe repeated schedules. |
| AC-013 | Finalization with executions transitions only to `FINALIZING` and records metadata | Finalization integration test verifies no analysis/reporting/scoring side effects and no auto-transition beyond `FINALIZING`. |
| AC-013A | Finalization with zero executions transitions `FINALIZING -> FAILED` | Integration test verifies two history entries and final failed metadata. |
| AC-013B | Future transitions defined only; Phase 3 remains in `FINALIZING` | Unit state machine accepts future transition definitions; handler test does not invoke them. |
| AC-014 | Expired audit schedule occurrence blocked | Execution guard integration verifies no outbound/orchestrator invocation after end time. |
| AC-015 | Unknown scenario taxonomy rejected | Unit taxonomy validator and scheduling negative test for `generic_api_test`. |
| AC-016 | Reliability mapping for `timeout_sensitivity` is `Resilience` | Unit mapping tests for all approved scenarios and missing mapping failure. |
| AC-017 | Disallowed environment execution blocked | Execution guard negative tests. |
| AC-017A | Production scheduling blocked without explicit allow | Scheduling validator integration no EventBridge create calls. |
| AC-017B | Production execution blocked without explicit allow | Execution handler integration no orchestrator/outbound calls. |
| AC-018 | Expired temporary token blocks execution and never exposes raw token | Token validator unit tests, execution guard integration, log/metadata sanitization assertions. |
| AC-019 | Terminal states cannot start execution or transition to `RUNNING` | Execution handler parameterized tests for `FAILED`, `CANCELLED`, `COMPLETED`. |
| AC-020 | Existing Phase 1/2 contracts preserved | Regression integration with mocked orchestrator/payload controls verifies raw schema v1, generated run ID validation, duplicate run ID protection, payload controls, endpoint safety controls remain authoritative. |
| AC-021 | Cancellation deletes/disables schedules, transitions `CANCELLED`, retains metadata | Cancellation integration with mocked EventBridge and DynamoDB assertions. |
| AC-021A | Cleanup failures recorded but cancellation still reaches `CANCELLED` | Negative cancellation integration verifies sanitized `cleanup_errors`. |
| AC-022 | `SCHEDULED_WITH_ERRORS` is never persisted | Unit state validator plus rollback/failure integration assertions search persisted metadata/history. |

## 3. Test Scenarios

### Unit Test Expectations

Planned unit tests should be implemented under existing project test conventions. If a different test layout already exists, use the closest matching unit test location while preserving Phase 3 names.

#### Lifecycle State Machine and Metadata

- Validate approved lifecycle states exactly: `DRAFT`, `SCHEDULED`, `RUNNING`, `FINALIZING`, `ANALYZING`, `REPORTING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Validate full transition table, including future-only transitions: `FINALIZING -> ANALYZING`, `ANALYZING -> REPORTING`, `REPORTING -> COMPLETED`.
- Reject unknown states and `SCHEDULED_WITH_ERRORS`.
- Reject invalid transitions from terminal states and ensure no state mutation.
- Verify lifecycle transition entries include `client_id`, `audit_id`, `from_state`, `to_state`, timestamp, reason, actor/source, and safe metadata.
- Verify append-only behavior: one new entry per accepted transition; previous entries are byte-for-byte or deep-equal unchanged.
- Verify transition metadata sanitizer removes/blocks secrets, raw token values, raw payloads, PII-like fields, and unsanitized response content.

Suggested files:

- `tests/unit/test_phase3_lifecycle_state_machine.py`
- `tests/unit/test_phase3_lifecycle_metadata.py`

#### Scheduler Naming and Schedule Builders

- Generate exact baseline/burst/repeated names using `rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}`.
- Generate exact finalization names using `rcp-{stage}-{client_id}-{audit_id}-finalization`.
- Enforce allowed schedule types only: `baseline`, `burst`, `repeated`, `finalization`.
- Reject unsafe/invalid schedule-name inputs rather than silently accepting path/log unsafe identifiers.
- Apply deterministic truncation and hash suffix only when length exceeds AWS EventBridge Scheduler limit.
- Verify same input produces same truncated name and hash suffix.
- Verify two long names with same leading prefix produce distinct deterministic suffixes.
- Verify target payloads contain minimum safe metadata and always omit `run_id`.
- Verify baseline defaults to 15 minutes and is bounded by audit window through metadata/guard design.
- Verify finalization schedule is one-time at audit-window end.

Suggested file:

- `tests/unit/test_phase3_schedule_builders.py`

#### Event Contracts and Scheduled Execution Guards

- Validate scheduled execution event schema: required `event_type`, `schema_version`, `client_id`, `audit_id`, `schedule_name`, `schedule_type`, `scenario_type`, `triggered_by`, `schedule_occurrence_id`, `scheduled_at`.
- Reject scheduler-created execution events containing `run_id` before occurrence claim or orchestrator invocation.
- Verify derived Phase 1 orchestrator event also omits `run_id`.
- Validate finalization event schema and finalization payload is metadata-only.
- Block malformed identifiers before DynamoDB keys, scheduler names, or logs.
- Block expired audit windows, terminal lifecycle states, disallowed environments, cap violations, and expired tokens before outbound execution.

Suggested file:

- `tests/unit/test_phase3_event_contracts.py`

#### Occurrence Claims and DynamoDB Key Shapes

- Verify audit metadata key: `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}`.
- Verify occurrence claim key: `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`.
- Verify run metadata key remains `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#RUN#{run_id}`.
- Verify occurrence conditional put uses attribute-not-exists semantics.
- Verify duplicate claim maps to duplicate scheduler delivery skip.
- Verify claim indeterminate failure blocks execution.
- Verify occurrence claim record never stores raw payloads, response bodies, tokens, credentials, PII, or raw provider errors.

Suggested file:

- `tests/unit/test_phase3_occurrence_claims.py`

#### Caps, Environment Restrictions, Audit Window, and Token Metadata

- Boundary-test non-production caps:
  - `max_requests_per_run = 100`: 100 allowed, 101 rejected
  - `max_concurrency = 5`: 5 allowed, 6 rejected
  - `max_burst_requests_per_window = 500`: 500 allowed, 501 rejected
  - `max_repeated_iterations = 100`: 100 allowed, 101 rejected
  - `max_audit_window_hours = 48`: 48 allowed, >48 rejected
- Boundary-test production caps when explicitly allowed:
  - `prod_max_requests_per_run = 25`: 25 allowed, 26 rejected
  - `prod_max_concurrency = 2`: 2 allowed, 3 rejected
  - `prod_max_burst_requests_per_window = 100`: 100 allowed, 101 rejected
- Verify production is blocked when `target_environment = "production"` and `allow_production_execution != true` at both scheduling and execution time.
- Verify default audit window end time is start + 48h.
- Verify burst `start_time` uses audit timezone when provided and UTC when omitted.
- Verify burst window positive `duration_minutes`, `request_count`, and `concurrency` requirements.
- Verify repeated unsafe runtime/request/token/audit-window estimates fail before schedule creation.
- Verify no chained, follow-up, continuation, queue, or self-invocation constructs are created for repeated schedules.
- Verify token metadata accepts only refs plus expiration metadata; raw token-like fields are rejected.
- Verify expired token refs block execution.
- Verify token expiration before audit-window end is represented safely and later executions after expiration are blocked.

Suggested files:

- `tests/unit/test_phase3_safeguards.py`
- `tests/unit/test_phase3_token_metadata.py`
- `tests/unit/test_phase3_repeated_execution.py`

#### Scenario Taxonomy and Reliability Grouping

- Accept only approved scenario types:
  - `baseline_health`
  - `repeated_stability`
  - `burst_stability`
  - `invalid_payload_handling`
  - `missing_fields_validation`
  - `auth_failure_handling`
  - `timeout_sensitivity`
  - `response_consistency`
- Reject unknown scenario values such as `generic_api_test`.
- Verify reliability category mapping:
  - `Stability`: `baseline_health`, `repeated_stability`, `burst_stability`, `response_consistency`
  - `Resilience`: `timeout_sensitivity`, `auth_failure_handling`
  - `Validation Robustness`: `invalid_payload_handling`, `missing_fields_validation`
- Verify approved scenario with missing category mapping fails validation before schedule creation/execution.

Suggested file:

- `tests/unit/test_phase3_taxonomy.py`

#### Finalization, Cancellation, and Rollback Behavior

- Finalization with execution count >0 transitions eligible `SCHEDULED`/`RUNNING` audits to `FINALIZING`, records metadata, and does not transition beyond `FINALIZING`.
- Finalization with zero executions records zero-execution metadata and transitions `FINALIZING -> FAILED`.
- Duplicate finalization when already `FINALIZING` is accepted/no-op; terminal states are skipped/no-op.
- Schedule creation partial failure rolls back created schedules where possible, records sanitized failure metadata, transitions to `FAILED`, and never persists `SCHEDULED_WITH_ERRORS`.
- Rollback cleanup failures are recorded safely and do not create partial lifecycle states.
- Cancellation deletes/disables all associated schedules, retains schedule metadata, transitions to `CANCELLED`, and records sanitized `cleanup_errors` when cleanup fails.
- Cancellation from invalid/terminal states is rejected without cleanup side effects unless design explicitly allows no-op behavior for terminal states.

Suggested files:

- `tests/unit/test_phase3_finalization.py`
- `tests/unit/test_phase3_cancellation_rollback.py`

### Integration Test Expectations

Integration tests should use mocked EventBridge Scheduler, mocked DynamoDB, and mocked S3/Secrets only where needed to preserve Phase 1/2 boundaries. They must not require live AWS resources.

Suggested files:

- `tests/integration/test_phase3_scheduling_lifecycle.py`
- `tests/integration/test_phase3_scheduled_execution.py`
- `tests/integration/test_phase3_duplicate_delivery.py`
- `tests/integration/test_phase3_cancellation_finalization.py`

Required integration scenarios:

1. **Successful full scheduling path**
   - Input: valid staging audit with baseline enabled, one burst window, one repeated schedule, finalization required.
   - Expected: EventBridge create wrapper called for applicable schedules; audit metadata written under audit-level key; lifecycle transitions `DRAFT -> SCHEDULED`; schedule metadata contains safe traceability fields; no secrets/raw tokens/raw payloads persisted.

2. **Scheduling validation blocks before AWS calls**
   - Inputs: audit window >48h, invalid scenario, invalid caps, production without explicit allow, expired/unsafe token ref, unsafe repeated estimate.
   - Expected: controlled validation error; zero EventBridge create calls; no outbound execution; no unsafe metadata persistence.

3. **Partial schedule creation rollback**
   - Input: second or later EventBridge create fails after earlier creates succeed.
   - Expected: rollback delete/disable attempted for already-created schedules; lifecycle transitions to `FAILED`; sanitized failure/cleanup metadata recorded; `SCHEDULED_WITH_ERRORS` absent.

4. **Scheduled execution accepted occurrence**
   - Input: valid scheduler event without `run_id`, active audit window, `SCHEDULED` audit.
   - Expected: occurrence claim written before orchestrator invocation; transition to `RUNNING` if current state is `SCHEDULED`; Phase 1 orchestrator receives metadata-only event without `run_id`; generated `run_id` captured after orchestrator success; run metadata retains Phase 1 key shape.

5. **Duplicate scheduler delivery**
   - Input: same `schedule_occurrence_id` delivered twice.
   - Expected: first delivery claims and may execute; second delivery detects existing claim, skips execution, creates no duplicate run, sends no outbound requests, emits sanitized duplicate log.

6. **Occurrence claim failure**
   - Input: DynamoDB conditional put/write verification fails indeterminately.
   - Expected: execution blocked; no orchestrator/outbound call; sanitized failure/skipped event recorded.

7. **Malformed scheduler-created event with `run_id`**
   - Input: scheduled execution event includes `run_id`.
   - Expected: event rejected before occurrence claim and orchestrator invocation; sanitized validation error logged; no run created.

8. **Expired/terminal execution guards**
   - Inputs: schedule occurrence after audit-window end; audit in `FAILED`, `CANCELLED`, or `COMPLETED`; production blocked; expired token ref.
   - Expected: no transition to `RUNNING`, no orchestrator/outbound call, safe skipped/failure metadata.

9. **Repeated sequential execution boundary**
   - Input: valid repeated event with finite iteration count.
   - Expected: orchestrator called sequentially in order, derived calls omit `run_id`, guard re-checked per iteration, no chained scheduler artifacts.

10. **Cancellation cleanup success and failure**
    - Input: cancellable audit with multiple schedules; one variant all deletes/disables succeed, one variant cleanup failure occurs.
    - Expected: audit transitions to `CANCELLED`; schedule metadata retained and cleanup statuses updated; cleanup failure variant records sanitized `cleanup_errors`.

11. **Finalization with executions and zero executions**
    - Input A: `RUNNING` or `SCHEDULED` audit with execution count >0.
    - Expected A: transition to `FINALIZING`, metadata recorded, no auto-analysis/reporting/completion.
    - Input B: audit with execution count =0.
    - Expected B: `FINALIZING` metadata recorded, then `FAILED`; history contains both accepted transitions.

12. **Phase 1/2 orchestrator regression boundary**
    - Input: scheduled execution accepted by Phase 3.
    - Expected: Phase 1 run ID generation/validation and duplicate run ID protection remain authoritative; Phase 2 payload strategy validation, duplicate payload controls, fingerprints, endpoint safety controls, and sanitization remain invoked as before.

### Required Validation Commands

Exact command names may be adjusted to the repository's package/test tooling once implementation is present. QA execution must record the exact commands and outputs in the Phase 3 QA report.

Required baseline commands:

```bash
git status --short
python --version
pytest tests/unit/test_phase3_lifecycle_state_machine.py -q
pytest tests/unit/test_phase3_schedule_builders.py -q
pytest tests/unit/test_phase3_safeguards.py -q
pytest tests/unit/test_phase3_occurrence_claims.py -q
pytest tests/unit/test_phase3_taxonomy.py -q
pytest tests/unit/test_phase3_token_metadata.py -q
pytest tests/integration/test_phase3_scheduling_lifecycle.py -q
pytest tests/integration/test_phase3_scheduled_execution.py -q
pytest tests/integration/test_phase3_duplicate_delivery.py -q
pytest tests/integration/test_phase3_cancellation_finalization.py -q
pytest tests/unit tests/integration -q
```

If the repository uses a wrapper such as `make test`, `poetry run pytest`, `uv run pytest`, or `npm test`, QA must execute the project-standard equivalent and document the substitution.

Required regression commands:

```bash
pytest tests -q
```

If full-suite execution is not feasible, the QA report must state why, list the subset executed, and classify the gap as a release risk.

### Security, Sanitization, and Logging Checklist

QA must verify through automated assertions and/or log inspection that Phase 3 never persists or logs:

- raw temporary token values
- client credentials
- secrets manager secret values
- raw request/response payload bodies
- PII
- cookies/session headers/authorization headers
- unsanitized AWS provider exceptions
- unsafe scheduler target payloads
- scheduler-created `run_id` values

Required positive checks:

- metadata/logs include safe traceability fields only: `client_id`, `audit_id`, schedule type, scenario type, schedule name, `schedule_occurrence_id`, controlled error code, timestamp
- duplicate delivery log event is sanitized and does not include raw payloads or token data
- cleanup and rollback errors use controlled/sanitized error codes/messages
- finalization metadata is boundary metadata only and contains no analysis/reporting/scoring output
- schedule metadata stores schedule expression summaries and traceability, not unsafe full target payloads
- token metadata stores `token_ref`, `expires_at`, optional `issued_at`, scope, and safe least-privilege description only
- production blocking failures occur before any outbound API requests

## 4. Edge Cases

Required negative and edge coverage:

- invalid lifecycle state outside approved list
- invalid lifecycle transition, including terminal state to non-terminal
- lifecycle history with existing entries remains append-only
- audit window omitted defaults to 48h
- audit window >48h rejected
- baseline default interval omitted uses 15 minutes
- burst window with zero/negative duration, request count, or concurrency rejected
- burst window outside audit window after timezone interpretation rejected
- burst timezone provided vs omitted UTC default
- DST/timezone boundary for burst window normalization where project date-time library supports deterministic behavior
- non-production cap violations for requests, concurrency, burst requests, repeated iterations, audit window
- production blocked without `allow_production_execution = true`
- production caps enforced even with explicit allow
- unknown scenario type rejected
- approved scenario missing category mapping rejected
- token ref expired before scheduled run blocked
- raw token value supplied in metadata/payload rejected
- token expiration shorter than audit window does not leak token and blocks later affected executions
- scheduler-created event includes `run_id` rejected
- scheduled execution event missing `schedule_occurrence_id` rejected
- duplicate occurrence claim skips execution and logs sanitized duplicate event
- occurrence claim write/verify failure blocks execution
- generated schedule name exceeds AWS length limit and receives deterministic hash suffix
- two long names with same truncated prefix remain distinct via hash suffix
- unsafe schedule names/identifiers rejected
- schedule creation partial failure triggers rollback and `FAILED`
- rollback cleanup failure recorded safely and no partial lifecycle state introduced
- cancellation cleanup partial failure records `cleanup_errors` and still transitions `CANCELLED`
- cancellation while scheduler event is delivered concurrently does not restart terminal/cancelled audit
- finalization duplicate event is no-op when already `FINALIZING` or terminal
- finalization with executions remains `FINALIZING`
- finalization with zero executions transitions `FINALIZING -> FAILED`
- `ANALYZING`, `REPORTING`, `COMPLETED` future transitions exist only in state machine, not in Phase 3 handlers
- `SCHEDULED_WITH_ERRORS` is never accepted or persisted

## 5. Test Types Covered

| Test Type | Covered | Notes |
| --- | --- | --- |
| Unit | Yes | Required for validators, state machine, builders, event contracts, caps, token metadata, taxonomy, occurrence key helpers, cancellation/finalization logic. |
| Integration | Yes | Required with mocked EventBridge Scheduler, DynamoDB, and Phase 1/2 orchestrator boundary. |
| API/Handler | Yes | Backend handler/function contracts for scheduling, scheduled execution, finalization, cancellation. No public HTTP API expected. |
| Security | Yes | Metadata/payload/log sanitization, production restrictions, token reference-only validation, secret leakage prevention. |
| Regression | Yes | Existing Phase 1/2 orchestrator, run metadata key shape, run ID validation, duplicate run ID protection, payload controls, raw schema v1. |
| Performance/Load | No | Explicitly out of scope; repeated execution safety is validated through caps/estimate logic, not load generation. |
| UI | No | No frontend in Phase 3 scope. |

## 6. Coverage Justification

The planned coverage maps every Phase 3 acceptance criterion to at least one automated test expectation and emphasizes both creation-time and execution-time enforcement. Unit tests isolate deterministic logic: lifecycle transition rules, schedule naming, event payloads, caps, taxonomy, token metadata, and sanitization. Integration tests validate system boundaries that unit tests cannot prove alone: mocked EventBridge Scheduler calls, DynamoDB key/conditional write behavior, rollback/cancellation side effects, duplicate occurrence handling, and preservation of Phase 1/2 orchestrator contracts.

Risk-based focus areas are duplicate delivery suppression, production safety, secret/token leakage prevention, rollback/cancellation cleanup integrity, and finalization boundaries because failures in these areas could cause unsafe customer traffic, duplicate executions, corrupted lifecycle state, or leakage of sensitive data.

### Evidence Required in QA Report

The Phase 3 QA report must include:

- test execution date/time and branch/commit SHA
- exact validation commands executed
- full command outputs or linked captured logs
- total tests, passed, failed, skipped
- per-test or per-suite result summary mapped to acceptance criteria
- mocked AWS/DynamoDB/orchestrator setup notes
- evidence that no live AWS resources were required unless explicitly approved
- relevant sanitized log snippets for duplicate delivery, rollback failure, cancellation cleanup failure, blocked production, expired token, and finalization
- DynamoDB mock assertions for audit metadata, occurrence claim, and run metadata key shapes
- EventBridge mock call assertions for schedule creation, rollback delete/disable, cancellation delete/disable
- proof that scheduler-created payloads and derived orchestrator events omit `run_id`
- proof that accepted scheduled occurrences use Phase 1-generated run IDs after occurrence claim
- proof that no secrets/raw tokens/raw payloads/PII are present in persisted metadata or logs
- regression test results for existing Phase 1/2 contracts
- failure classifications for any non-passing tests using: Application Bug, Test Bug, Environment Issue, or Flaky Test

### Sign-Off Criteria

QA sign-off for Phase 3 may be approved only if all of the following are true:

- all critical Phase 3 unit and integration tests pass
- all acceptance criteria are covered by automated tests or explicitly justified with equivalent evidence
- no blocking or high-severity defects remain unresolved
- no tests fail, unless the failure is proven unrelated and formally classified with release-owner acceptance
- no flaky tests remain unresolved in critical lifecycle/scheduling/security paths
- schedule creation, rollback, cancellation, duplicate occurrence, and finalization paths have evidence-backed validation
- production restrictions and operational caps are proven at scheduling and execution time
- security/sanitization checklist passes with evidence
- Phase 1/2 regression checks pass and existing contracts are not weakened
- no `SCHEDULED_WITH_ERRORS` state is accepted or persisted anywhere

If any critical test fails, if execution evidence is missing, or if acceptance coverage is incomplete, QA must not approve Phase 3.
