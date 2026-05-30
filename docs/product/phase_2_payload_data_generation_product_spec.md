# Product Specification

## 1. Feature Overview

Phase 2 implements deterministic and scalable payload handling for the Release Confidence Platform.

This phase extends the existing Phase 1 backend execution engine with a payload strategy system that supports static payloads, generated payloads, and reusable data-pool-backed payloads. The implementation must preserve the platform objective: operational API reliability auditing through deterministic evidence collection and operational traceability.

Phase 2 is limited to backend payload preparation, validation, duplicate prevention, safety controls, and fingerprint generation. It does not add scheduling, lifecycle management, dashboards, analytics reporting, AI insights, authentication, billing, or self-serve onboarding.

### Operator-Facing Impact

- Operators can configure endpoint payload behavior using explicit payload strategies.
- Operators can rely on deterministic generated values across repeated execution of the same run context.
- Operators can provide reusable data pools for controlled test data selection.
- Operators receive safer execution behavior through duplicate prevention and destructive-operation safeguards.
- Operators can inspect payload and response fingerprints for consistency tracking and traceability without exposing unsanitized sensitive content.
- Operators can inspect generated/payload handling metadata in raw results to understand strategy, duplicate handling, generation attempts, and data-pool usage without exposing unsafe payload or record values.

### Backend / System Impact

- The runner must resolve payload strategy before outbound request execution.
- Payload validation must occur before a request is sent.
- Duplicate checking must be integrated into payload generation flow.
- Raw results must include `response_fingerprint` and `payload_metadata.payload_fingerprint` generated from canonical sanitized representations.
- Raw results must keep `payload_strategy` at the raw result top level and nest Phase 2-specific payload handling details under `payload_metadata` while preserving `raw_result_version = "v1"` as a backward-compatible schema extension.
- Data pools must be loaded from S3-compatible object storage paths under `data-pools/{client_id}/{pool_name}.json`.
- Payload safety configuration must be enforced at the endpoint level.
- Endpoint payload configuration field names and shape are confirmed for Phase 2 and must use `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- In-run duplicate reservation must use an in-memory duplicate tracker scoped to the orchestrator run. For `current_run`, the reservation scope key must include `client_id + audit_id + run_id`.

## 2. Problem Statement

The Phase 1 engine can execute configured requests, but it does not provide a deterministic, scalable way to prepare dynamic payload data or safely reuse client-provided datasets. Without this capability, audit runs either rely on static payloads only or risk non-repeatable request data, accidental destructive reuse, duplicate submissions, and weak traceability.

Phase 2 solves this by introducing a strict payload strategy system with deterministic substitution, data-pool assignment, duplicate prevention policies, payload validation, safety controls, and sanitized fingerprinting. This enables repeatable evidence collection while supporting realistic endpoint interaction patterns.

## 3. User Persona / Target User

- **Technical operator / maintainer:** configures audit endpoints and needs safe, deterministic payload behavior across audit runs.
- **Platform engineer / developer:** implements payload strategy execution, validation, duplicate checking, and fingerprinting within the existing backend engine.
- **QA engineer:** validates that payload generation, data-pool assignment, duplicate policy behavior, and safety controls are deterministic and testable.

## 4. User Stories

- As a technical operator, I want to choose a payload strategy per endpoint so that each API check uses the correct type of request data.
- As a technical operator, I want generated payload values to be deterministic so that audit evidence is repeatable for the same run context.
- As a technical operator, I want to use reusable data pools so that realistic client-provided datasets can drive audit requests safely.
- As a technical operator, I want duplicate payload handling to be policy-driven so that duplicate submissions are prevented or explicitly allowed.
- As a platform engineer, I want payload and response fingerprints so that consistency and traceability can be validated without storing unsafe raw content.
- As a QA engineer, I want strict validation and safety failure modes so that unsafe payload execution is blocked before outbound requests occur.

## 5. Goals / Success Criteria

Phase 2 is successful when:

- The runner supports `static`, `generated`, and `data_pool` payload strategies.
- Generated payload variables are replaced deterministically for `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, and `{{uuid}}`.
- `{{uuid}}` is derived deterministically from `client_id + audit_id + run_id + endpoint_id + iteration + field_path + token_index`, where `token_index` differentiates repeated `{{uuid}}` tokens in the same field.
- `{{timestamp}}` is captured once at run level and reused for all timestamp substitutions in that run.
- Data pools are loaded from `data-pools/{client_id}/{pool_name}.json`.
- Data-pool record assignment is deterministic using `hash(client_id, audit_id, run_id, endpoint_id, scenario_type, iteration) % pool_size`.
- Data-pool payload mapping supports using the selected record as the full request payload and using the selected record as a substitution source for a payload template.
- When a `data_pool` endpoint has no payload template, the selected data-pool record is used as the full request payload by default.
- Duplicate prevention supports `regenerate`, `fail_fast`, and `allow`, with `regenerate` as the default policy.
- The `regenerate` policy retries with an incremented deterministic attempt salt up to 5 attempts.
- The runner emits `payload_metadata.payload_fingerprint` and `response_fingerprint` using SHA-256 over canonical sanitized JSON/string representations.
- Raw results record top-level `payload_strategy` and nest Phase 2-specific details under `payload_metadata`, including `payload_fingerprint`, `duplicate_check_scope`, `duplicate_detected`, `duplicate_allowed`, `duplicate_policy`, `generation_attempt`, `data_pool_name`, and `data_pool_record_fingerprint`.
- Raw result `payload_metadata` includes `duplicate_allowed`; when `duplicate_policy = allow`, it must be `true` only when a duplicate was detected and allowed, and must be `false` when no duplicate was detected.
- Phase 2 `payload_metadata` does not expose unsafe raw payload values, secrets, tokens, credentials, cookies, PII, sensitive data, or raw data-pool record contents.
- Payload validation blocks missing variables, invalid payload structure, invalid payload type, unsafe generation patterns, and non-deterministic substitutions before outbound request execution.
- Endpoint-level payload safety config is enforced.
- Destructive operations are blocked when `payload_safety.destructive_operation = true` unless `payload_safety.allow_destructive_operation = true`; `allow_destructive_operation` defaults to `false`.
- Phase 2 can be validated without implementing Phase 3 scheduling or lifecycle behavior.

## 6. Feature Scope

### In Scope

Phase 2 includes only the following functionality:

- Payload strategy resolution for configured endpoints.
- `static` payload strategy for GET, idempotent, and baseline checks.
- `generated` payload strategy with deterministic variable substitution.
- `data_pool` payload strategy backed by client-provided JSON datasets.
- Data-pool loading from `data-pools/{client_id}/{pool_name}.json`.
- Data-pool JSON parsing for both a plain list of records and a wrapped object containing a `records` list; the wrapped object form is preferred for future metadata compatibility.
- Configurable data-pool selection by pool name.
- Deterministic data-pool record assignment.
- Controlled data-pool record reuse based on endpoint payload safety configuration.
- Duplicate payload checking in `packages/data-generation/duplicate_checker.py`.
- Duplicate policies: `regenerate`, `fail_fast`, and `allow`.
- Default duplicate prevention scope of `current_run`.
- In-run duplicate reservation using an in-memory duplicate tracker per orchestrator run for `current_run` scope.
- Payload validation before outbound requests.
- Endpoint-level payload safety controls using:

  ```json
  {
    "payload_safety": {
      "allow_generated_payloads": true,
      "allow_data_pool_reuse": true,
      "destructive_operation": false,
      "allow_destructive_operation": false
    }
  }
  ```

- Blocking destructive payload execution unless explicitly allowed by endpoint configuration.
- Concurrency-safe duplicate checking for payload generation within a run.
- `payload_metadata.payload_fingerprint` and `response_fingerprint` generation for raw results.
- Raw result metadata extensions for Phase 2 payload handling while preserving `raw_result_version = "v1"`.
- Sanitization before fingerprint generation when fingerprinting persisted or logged representations.
- Unit-testable and integration-testable backend behavior.

### Out of Scope

The following are explicitly excluded from Phase 2:

- Frontend or dashboard implementation.
- User authentication, RBAC, billing, subscriptions, multi-user account management, or self-serve onboarding.
- AI insights or AI-generated recommendations.
- Reliability scoring or analytics report generation as a product feature.
- Advanced observability, distributed tracing, or operational dashboards.
- Load testing, uptime monitor clone behavior, or chaos engineering.
- Heavy API frameworks.
- Phase 3 scheduling, lifecycle management, recurring execution, or retry orchestration beyond existing runner retry behavior.
- New public customer API surface.
- Config authoring UI.
- Secret lifecycle management beyond existing Phase 1 secret resolution behavior.
- Non-deterministic random data generation.
- General-purpose test data generation libraries unless wrapped to meet deterministic requirements.
- Persisting or exposing raw generated payload values, raw data-pool record contents, secrets, tokens, credentials, cookies, PII, or sensitive data in raw result `payload_metadata`.
- Audit-wide duplicate tracking across historical or concurrent runs outside the current orchestrator run.
- Persistent duplicate reservation storage until a durable audit-wide reservation design is approved.

### Future Considerations

- Full persisted duplicate detection across all historical runs for the same `client_id + audit_id`.
- Durable audit-wide duplicate reservation that can safely coordinate across orchestrator runs.
- Additional payload variable types if explicitly approved in a later phase.
- Data-pool management UI or validation tooling.
- Operator-facing reports that summarize duplicate trends or payload consistency patterns.

## 7. Functional Requirements

### FR-001: Payload Strategy Selection

The runner must support endpoint-level payload strategy selection with exactly these Phase 2 strategy values:

- `static`
- `generated`
- `data_pool`

If an endpoint omits a payload strategy, the system must use `static` only when a static payload is already provided or the request does not require a body. Otherwise, the system must fail with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

Endpoint payload configuration must use the following confirmed Phase 2 field names and shape:

```json
{
  "payload_strategy": "generated",
  "payload_template": {
    "email": "audit-{{uuid}}@example.test",
    "run": "{{run_id}}"
  },
  "payload_iterations": 1,
  "duplicate_policy": "regenerate",
  "duplicate_check_scope": "current_run",
  "data_pool_name": null,
  "payload_safety": {
    "allow_generated_payloads": true,
    "allow_data_pool_reuse": true,
    "destructive_operation": false,
    "allow_destructive_operation": false
  }
}
```

Implementation must not introduce alternate Phase 2 endpoint field names for these concepts.

### FR-002: Static Payload Strategy

The `static` strategy must pass configured payload content through validation and sanitization without dynamic variable substitution. Static payloads are intended for GET, idempotent, and baseline checks.

If a static payload contains Phase 2 variable tokens such as `{{run_id}}`, the system must fail validation unless the endpoint explicitly uses the `generated` strategy.

### FR-003: Generated Payload Strategy

The `generated` strategy must support deterministic replacement of:

- `{{run_id}}`
- `{{iteration}}`
- `{{timestamp}}`
- `{{uuid}}`

The system must reject unknown variables and malformed variable tokens with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

### FR-004: Deterministic Generated Values

Generated substitutions must be repeatable for the same input context.

`{{timestamp}}` must use a single run-level timestamp captured once and reused for every timestamp substitution in that run.

`{{uuid}}` must be derived deterministically from:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `iteration`
- `field_path`
- `token_index`

`token_index` must be included when resolving `{{uuid}}` tokens so repeated `{{uuid}}` tokens within the same field path produce deterministic but distinct values. Token indexing must be stable for the same payload template and run context.

When duplicate regeneration is required, the deterministic attempt salt may alter generated values, but the same salted attempt context must still produce repeatable output.

### FR-005: Data Pool Loading

The `data_pool` strategy must load reusable client-provided datasets from:

`data-pools/{client_id}/{pool_name}.json`

The endpoint configuration must identify the data pool using `data_pool_name`. Missing, unreadable, empty, or invalid data pool files must cause `PAYLOAD_VALIDATION_ERROR` before outbound execution.

Data-pool JSON must support both of the following schemas:

- **Plain list:** the file root is a JSON array of record objects.
- **Wrapped object:** the file root is a JSON object with a `records` property containing an array of record objects.

The wrapped object schema is preferred for future metadata support. Phase 2 must ignore unsupported wrapper metadata unless required validation fails, and must use only the `records` array for deterministic assignment.

### FR-006: Deterministic Data Pool Assignment

For a selected pool, the runner must assign records using:

`hash(client_id, audit_id, run_id, endpoint_id, scenario_type, iteration) % pool_size`

The same execution context and pool contents must select the same record. Different iterations may select different records according to the hash result.

### FR-006A: Data Pool Payload Mapping

The `data_pool` strategy must support both of the following payload mapping modes:

- **Full-payload mode:** the selected data-pool record becomes the full request payload.
- **Template-substitution mode:** the selected data-pool record is used as the substitution source for a configured payload template.

If a `data_pool` endpoint does not provide `payload_template`, the system must use full-payload mode by default.

If a `data_pool` endpoint provides `payload_template`, the system must use the selected data-pool record as the substitution source for that template. Missing template fields, unresolved substitutions, or substitutions that produce an invalid payload must fail with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

### FR-007: Controlled Data Pool Reuse

The system must enforce endpoint-level reuse controls. If a selected data-pool record has already been used within the configured duplicate scope and `allow_data_pool_reuse` is not true, the system must apply the configured duplicate policy.

### FR-008: Duplicate Prevention

The duplicate checker in `packages/data-generation/duplicate_checker.py` must support these policies:

- `regenerate`
- `fail_fast`
- `allow`

The default policy must be `regenerate` when no policy is configured.

The default duplicate scope must be `current_run`.

For `current_run`, duplicate reservation must use an in-memory duplicate tracker owned by the orchestrator run. The duplicate reservation scope key must include:

- `client_id`
- `audit_id`
- `run_id`

Audit-wide duplicate checking across multiple runs is out of scope for Phase 2 and must not be simulated with partial or unreliable persistence.

### FR-009: Duplicate Policy Behavior

For `regenerate`, the system must retry deterministic generation with an incremented deterministic attempt salt up to 5 attempts. If all attempts remain duplicate, the system must fail with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

For `fail_fast`, the system must fail with `PAYLOAD_VALIDATION_ERROR` on the first detected duplicate before outbound execution.

For `allow`, the system must proceed with execution and record the duplicate outcome in `payload_metadata` using `duplicate_detected = true` and `duplicate_policy = "allow"` for that request.

When `duplicate_policy = "allow"`, `payload_metadata.duplicate_allowed` must be:

- `true` only when a duplicate was detected and execution proceeded because duplicates were allowed.
- `false` when no duplicate was detected.

For non-`allow` policies, `duplicate_allowed` must be `false` whenever metadata is recorded.

### FR-010: Payload Fingerprint

The runner must generate `payload_fingerprint` for each executed request using SHA-256 over a canonical sanitized JSON/string representation of the final payload sent or effective request body.

Equivalent JSON content with different key ordering must produce the same fingerprint.

When a request has no body or an absent effective payload, the canonical payload representation must be the exact sentinel string `EMPTY_PAYLOAD`. The `payload_fingerprint` must be the SHA-256 hash of the canonical string `EMPTY_PAYLOAD`.

### FR-011: Response Fingerprint

The runner must generate `response_fingerprint` for each response using SHA-256 over a canonical sanitized JSON/string representation of the response content used for evidence.

Equivalent JSON response content with different key ordering must produce the same fingerprint.

Phase 1/Phase 2 response fingerprinting is evidence collection only. The runner must not compare response fingerprints across iterations, endpoints, schedules, or runs, and must not emit response-consistency verdicts or statuses in this phase. Fingerprint comparison analytics are deferred to a later reporting/aggregation phase.

### FR-012: Payload Validation

Payload validation must check:

- required variables are present when required by the strategy
- no unknown or malformed variables are present
- payload structure is valid for the configured content type
- payload type is valid for the request method and endpoint configuration
- generation behavior is deterministic
- generated substitutions are safe for persistence and logging after sanitization
- destructive operation execution is not allowed unless explicitly configured with `payload_safety.allow_destructive_operation = true`

Validation failures must occur before outbound requests and must be classified as `PAYLOAD_VALIDATION_ERROR`.

### FR-013: Endpoint-Level Safety Controls

The system must support endpoint-level payload safety configuration with these fields:

- `allow_generated_payloads`
- `allow_data_pool_reuse`
- `destructive_operation`
- `allow_destructive_operation`

Generated payloads must be blocked when `allow_generated_payloads` is not true for an endpoint using the `generated` strategy.

Data-pool reuse must be blocked when `allow_data_pool_reuse` is not true and reuse is detected within the configured duplicate scope.

`allow_destructive_operation` must default to `false` when omitted.

If `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation != true`, validation must fail with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

Destructive operations must be blocked unless the endpoint configuration explicitly sets `payload_safety.allow_destructive_operation = true`. A destructive operation must not proceed due to missing, false, null, or default configuration.

### FR-014: Concurrency Safety

Duplicate detection and generation attempts must be safe when multiple endpoint iterations execute concurrently within the same run. The system must not allow two concurrent iterations to unintentionally reserve or submit the same generated payload when the configured policy prohibits duplicates.

### FR-015: Raw Result Payload Handling Metadata

Raw result records must include top-level `payload_strategy`, with value `static`, `generated`, or `data_pool`.

Raw result records must nest Phase 2-specific payload handling details under `payload_metadata` where applicable to the endpoint strategy and execution outcome:

```json
{
  "payload_strategy": "generated",
  "payload_metadata": {
    "payload_fingerprint": "...",
    "duplicate_check_scope": "current_run",
    "duplicate_detected": false,
    "duplicate_allowed": false,
    "duplicate_policy": "regenerate",
    "generation_attempt": 1,
    "data_pool_name": null,
    "data_pool_record_fingerprint": null
  }
}
```

`payload_metadata` fields must use the following meanings:

- `payload_fingerprint`: SHA-256 fingerprint of the canonical sanitized final payload or effective request body representation.
- `duplicate_check_scope`: the duplicate scope used for the request, including the default `current_run` when no scope is configured.
- `duplicate_detected`: boolean indicating whether duplicate checking detected a duplicate during payload preparation.
- `duplicate_allowed`: boolean indicating whether a detected duplicate was allowed to proceed. It must be `true` only when `duplicate_policy = "allow"` and a duplicate was detected; it must be `false` when no duplicate was detected.
- `duplicate_policy`: the resolved duplicate policy used for the request, including the default `regenerate` when no policy is configured.
- `generation_attempt`: the final deterministic generation attempt number used for payload preparation. The initial attempt must be represented consistently as attempt `1`.
- `data_pool_name`: the configured data-pool name when the `data_pool` strategy is used; otherwise `null`.
- `data_pool_record_fingerprint`: SHA-256 fingerprint of the canonical sanitized selected data-pool record representation when the `data_pool` strategy is used; otherwise `null`.

These fields are Phase 2 extensions to the raw result schema/records and must preserve `raw_result_version = "v1"`. They must be added in a backward-compatible way that does not break Phase 1 raw evidence consumers.

### FR-016: Raw Result Metadata Sanitization and Safety

Raw result `payload_metadata` must not expose unsafe raw payload values, raw generated values, raw data-pool record contents, secrets, tokens, credentials, cookies, PII, or sensitive data.

`payload_fingerprint` and `data_pool_record_fingerprint` must use SHA-256 over canonical sanitized JSON/string representations. `data_pool_record_fingerprint` must identify the selected sanitized record representation for traceability without exposing the record contents.

Phase 2 must preserve Phase 1 raw evidence trust, sanitization, and persistence requirements. If a value cannot be safely sanitized for raw result persistence, the raw result must store only the appropriate fingerprint or safe metadata indicator, not the unsafe value.

## 8. Acceptance Criteria

### AC-000A: Confirmed Endpoint Config Shape

Given an endpoint payload configuration uses `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety` fields  
When the runner resolves Phase 2 payload settings  
Then those fields are used as the authoritative configuration source and no alternate Phase 2 field names are required

### AC-001: Static Strategy Pass-Through

Given an endpoint configured with `static` payload strategy and a valid static payload  
When the runner prepares the request  
Then the payload is used without Phase 2 variable substitution and the request may execute after validation succeeds

### AC-002: Static Strategy Rejects Dynamic Tokens

Given an endpoint configured with `static` payload strategy and a payload containing `{{run_id}}`  
When the runner validates the payload  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-003: Generated Strategy Replaces Supported Variables

Given an endpoint configured with `generated` payload strategy and a payload containing `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, and `{{uuid}}`  
When the runner prepares iteration `3` for a valid run context  
Then all supported variables are replaced with deterministic values before the request is sent

### AC-004: Generated Strategy Rejects Unknown Variables

Given an endpoint configured with `generated` payload strategy and a payload containing `{{random}}`  
When the runner validates the payload  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-005: Run-Level Timestamp Reuse

Given a run with multiple endpoints and iterations using `{{timestamp}}`  
When generated payloads are prepared during that run  
Then every `{{timestamp}}` substitution uses the same run-level timestamp value

### AC-006: Deterministic UUID Generation

Given the same `client_id`, `audit_id`, `run_id`, `endpoint_id`, `iteration`, `field_path`, and `token_index`  
When `{{uuid}}` is substituted in repeated executions of the same run context  
Then the generated UUID value is identical

### AC-007: UUID Field Path Differentiation

Given one generated payload containing `{{uuid}}` in two different field paths  
When the payload is prepared  
Then each field path receives a deterministic UUID derived from its own field path

### AC-007A: Repeated UUID Tokens in Same Field

Given one generated payload field contains repeated `{{uuid}}` tokens in the same field path  
When the payload is prepared  
Then each repeated token is resolved using the same `field_path` and its own stable `token_index`

### AC-007B: Repeated UUID Tokens Are Stable

Given the same payload template contains repeated `{{uuid}}` tokens in the same field path  
When the same run context is prepared more than once  
Then each repeated token position resolves to the same deterministic UUID value for that token index

### AC-008: Data Pool Load Path

Given an endpoint configured with `data_pool` strategy and `data_pool_name` of `users` for `client_id` `client-a`  
When the runner loads the pool  
Then it reads the dataset from `data-pools/client-a/users.json`

### AC-009: Data Pool Missing File

Given an endpoint configured with `data_pool` strategy and a missing pool file  
When the runner prepares the request  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-009A: Data Pool Plain List Schema

Given a data-pool file contains a valid JSON array of record objects at the file root  
When the runner loads the data pool  
Then the array is accepted as the complete set of assignable records

### AC-009B: Data Pool Wrapped Records Schema

Given a data-pool file contains a valid JSON object with `records` set to an array of record objects  
When the runner loads the data pool  
Then the `records` array is accepted as the complete set of assignable records

### AC-009C: Data Pool Invalid Wrapped Records Schema

Given a data-pool file contains a JSON object without a valid `records` array  
When the runner loads the data pool  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-010: Deterministic Data Pool Assignment

Given the same `client_id`, `audit_id`, `run_id`, `endpoint_id`, `scenario_type`, `iteration`, and unchanged pool contents  
When data-pool assignment is calculated repeatedly  
Then the same pool record is selected each time

### AC-010A: Data Pool Full-Payload Default

Given an endpoint uses `data_pool` strategy, a valid data-pool record is selected, and no `payload_template` is configured  
When the runner prepares the request payload  
Then the selected data-pool record is used as the full request payload

### AC-010B: Data Pool Template Substitution

Given an endpoint uses `data_pool` strategy, a valid data-pool record is selected, and `payload_template` is configured  
When the runner prepares the request payload  
Then the selected data-pool record is used as the substitution source for the payload template

### AC-010C: Data Pool Template Substitution Failure

Given an endpoint uses `data_pool` strategy and the configured `payload_template` references a field not available from the selected data-pool record  
When the runner validates the prepared payload  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-011: Regenerate Duplicate Policy

Given duplicate prevention policy is `regenerate` and the first generated payload is detected as duplicate  
When the runner prepares the payload  
Then it retries deterministic generation with incremented deterministic attempt salt up to 5 attempts

### AC-012: Regenerate Exhaustion

Given duplicate prevention policy is `regenerate` and all 5 regeneration attempts produce duplicates  
When the runner prepares the payload  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-013: Fail Fast Duplicate Policy

Given duplicate prevention policy is `fail_fast` and a duplicate payload is detected  
When the runner prepares the payload  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-014: Allow Duplicate Policy

Given duplicate prevention policy is `allow` and a duplicate payload is detected  
When the runner prepares and executes the request  
Then the request proceeds and `payload_metadata` records `duplicate_detected = true`, `duplicate_allowed = true`, and `duplicate_policy = "allow"`

### AC-014A: Allow Policy Without Duplicate

Given duplicate prevention policy is `allow` and no duplicate payload is detected  
When the runner prepares and executes the request  
Then the request proceeds and `payload_metadata` records `duplicate_detected = false`, `duplicate_allowed = false`, and `duplicate_policy = "allow"`

### AC-015: Default Duplicate Policy

Given duplicate prevention policy is not configured  
When duplicate checking is performed  
Then the system applies the `regenerate` policy

### AC-016: Default Duplicate Scope

Given duplicate prevention scope is not configured  
When duplicate checking is performed  
Then the system checks duplicates within `current_run`

### AC-016A: Current Run Duplicate Reservation Scope Key

Given duplicate checking is performed with `duplicate_check_scope = current_run`  
When the runner reserves or checks a payload fingerprint  
Then the in-memory duplicate tracker uses a scope key that includes `client_id`, `audit_id`, and `run_id`

### AC-016B: Audit-Wide Duplicate Tracking Excluded

Given a duplicate payload exists only in a previous run for the same `client_id` and `audit_id`  
When Phase 2 duplicate checking runs with `duplicate_check_scope = current_run`  
Then the previous run does not cause a duplicate failure or regeneration in Phase 2

### AC-017: Payload Fingerprint Canonicalization

Given two final sanitized JSON payloads with equivalent content but different key ordering  
When `payload_metadata.payload_fingerprint` is generated  
Then both payloads produce the same SHA-256 fingerprint

### AC-017A: Empty Payload Fingerprint Sentinel

Given a request has no body or an absent effective payload  
When `payload_metadata.payload_fingerprint` is generated  
Then the canonical payload representation is the exact string `EMPTY_PAYLOAD` and the fingerprint is the SHA-256 hash of that string

### AC-018: Response Fingerprint Canonicalization

Given two sanitized JSON responses with equivalent content but different key ordering  
When `response_fingerprint` is generated  
Then both responses produce the same SHA-256 fingerprint

### AC-019: Generated Payload Safety Block

Given an endpoint uses `generated` strategy and `payload_safety.allow_generated_payloads` is not true  
When the runner validates the endpoint payload configuration  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-020: Data Pool Reuse Safety Block

Given a data-pool record is selected more than once within the configured duplicate scope and `payload_safety.allow_data_pool_reuse` is not true  
When the runner validates the selected record  
Then the system applies the configured duplicate policy before outbound execution

### AC-021: Destructive Operation Default Block

Given `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation` is omitted  
When the runner validates payload safety  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-021A: Destructive Operation Non-True Allow Block

Given `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation` is not `true`  
When the runner validates payload safety  
Then validation fails with `PAYLOAD_VALIDATION_ERROR` before any outbound request is sent

### AC-022: Destructive Operation Explicit Allow

Given `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation = true`  
When all other payload validation checks pass  
Then the runner may prepare and execute the request according to the configured payload strategy

### AC-023: Concurrency Duplicate Safety

Given multiple iterations for the same endpoint are prepared concurrently and duplicate policy prohibits duplicates  
When payload generation and duplicate reservation occur  
Then no two iterations proceed with the same `payload_metadata.payload_fingerprint` within the configured duplicate scope

### AC-024: Raw Result Metadata for Generated Payload

Given an endpoint executes with the `generated` payload strategy  
When the raw result record is written  
Then the raw result includes top-level `payload_strategy = generated` and `payload_metadata` containing `payload_fingerprint`, `duplicate_check_scope`, `duplicate_detected`, `duplicate_allowed`, `duplicate_policy`, `generation_attempt`, `data_pool_name = null`, and `data_pool_record_fingerprint = null` with values matching the resolved payload preparation outcome

### AC-025: Raw Result Metadata for Data Pool Payload

Given an endpoint executes with the `data_pool` payload strategy and a record is selected from pool `users`  
When the raw result record is written  
Then the raw result includes top-level `payload_strategy = data_pool` and `payload_metadata` containing `payload_fingerprint`, `duplicate_check_scope`, `duplicate_detected`, `duplicate_allowed`, `duplicate_policy`, `generation_attempt`, `data_pool_name = users`, and `data_pool_record_fingerprint`

### AC-026: Raw Result Metadata Preserves Schema Version

Given a Phase 2 request completes or fails after payload preparation metadata is available  
When the raw result record is persisted  
Then top-level `payload_strategy` and nested `payload_metadata` are recorded as backward-compatible raw result extensions while `raw_result_version` remains `v1`

### AC-027: Raw Result Metadata Does Not Expose Unsafe Values

Given a generated payload or selected data-pool record contains secrets, tokens, credentials, cookies, PII, or other sensitive values  
When `payload_metadata` is persisted  
Then `payload_metadata` does not contain those unsafe raw values and contains only safe metadata and SHA-256 fingerprints derived from canonical sanitized representations

### AC-028: Data Pool Record Fingerprint Hides Raw Record Contents

Given a `data_pool` strategy selects a data-pool record containing raw record fields  
When `data_pool_record_fingerprint` is generated and stored in `payload_metadata`  
Then the stored value is a SHA-256 fingerprint of the canonical sanitized record representation and does not expose the raw record contents

### AC-029: Duplicate Metadata Reflects Duplicate Outcome

Given duplicate checking is performed for a payload  
When the raw result record is written after payload preparation succeeds or fails with a duplicate-related outcome  
Then `payload_metadata.duplicate_detected`, `payload_metadata.duplicate_allowed`, `payload_metadata.duplicate_policy`, `payload_metadata.duplicate_check_scope`, and `payload_metadata.generation_attempt` reflect the actual duplicate handling outcome used by the runner

## 9. Edge Cases

- Empty payload with `static` strategy for a method that does not require a body; absent/no-body payload fingerprint must use the canonical `EMPTY_PAYLOAD` sentinel.
- Static payload containing generated variable syntax.
- Generated payload containing unknown, malformed, nested, or repeated variable tokens.
- Multiple `{{uuid}}` tokens in the same payload at different field paths.
- Multiple `{{uuid}}` tokens at the same field path across repeated attempts.
- Multiple `{{uuid}}` tokens repeated within the same field path; each repeated token must use a stable `token_index` and must not collapse to the same generated value solely because the field path matches.
- Same generated payload after all regeneration attempts.
- Missing `data_pool_name` for `data_pool` strategy.
- Data-pool file exists but is empty, malformed JSON, not a supported plain list or wrapped object with `records`, or contains records that cannot produce a valid payload.
- Data-pool wrapped object contains metadata fields but a valid `records` array; unsupported metadata must not alter deterministic record assignment.
- Data-pool endpoint has no `payload_template`; the selected record must become the full request payload.
- Data-pool endpoint has `payload_template`; the selected record must be used only as the substitution source and unresolved template substitutions must fail validation.
- Data-pool selected record is valid as source data but produces an invalid final payload after template substitution.
- Data-pool size of 1 with duplicate policy `fail_fast` or `regenerate` and reuse disallowed.
- Hash assignment result changes only because pool contents or pool size changed.
- Response body is empty, non-JSON, binary-like, or malformed JSON.
- Payload or response contains sensitive values that must be sanitized before fingerprinting persisted/logged representations.
- Generated payload metadata contains only safe strategy, policy, attempt, scope, boolean, null, and fingerprint values, never unsafe raw payload values.
- Data-pool selected record contains secrets, tokens, credentials, cookies, PII, or sensitive data that must not appear in raw results.
- Sanitization changes data-pool record content before fingerprinting; the fingerprint must be based on the canonical sanitized representation, not raw record contents.
- Duplicate detection fails before outbound execution after one or more generation attempts; available safe duplicate metadata must still reflect the payload handling outcome if a raw result is recorded for the failure.
- Endpoint uses `static` strategy with no request body; raw result `payload_metadata` must handle an absent or empty effective payload with `EMPTY_PAYLOAD` fingerprinting and without inventing unsafe values.
- Duplicate policy is `allow` and no duplicate is detected; `duplicate_allowed` must remain `false` for analytics consistency.
- Duplicate policy is `allow` and a duplicate is detected; `duplicate_allowed` must be `true` only for that allowed duplicate outcome.
- Concurrent iterations attempt to reserve the same generated payload or data-pool record.
- A duplicate exists in a previous run for the same `client_id + audit_id`; Phase 2 `current_run` duplicate checking must not treat it as in scope.
- Endpoint safety configuration is missing one or more safety fields.
- `payload_safety.destructive_operation = true` with `payload_safety.allow_destructive_operation` omitted, false, null, or any value other than true.
- Destructive endpoint has ambiguous safety configuration.
- Raw result contains top-level `payload_strategy` but missing, malformed, or unsafe `payload_metadata`.

## 10. Constraints

- Phase 2 must build on the existing Phase 1 orchestrator, runner, raw result schema v1, sanitization, S3/DynamoDB/Secrets wrappers, strict `run_id` validation, and duplicate `run_id` protection.
- Payload generation must be deterministic for the same context and configured attempt salt.
- Non-deterministic randomness is not allowed for generated substitutions.
- Fingerprints must use SHA-256.
- Fingerprints must be calculated from canonical sanitized JSON/string representations.
- Absent or no-body payload fingerprints must use SHA-256 over the exact canonical sentinel string `EMPTY_PAYLOAD`.
- `payload_fingerprint`, `response_fingerprint`, and `data_pool_record_fingerprint` must use SHA-256 over canonical sanitized JSON/string representations.
- Phase 2 payload handling metadata must be stored in raw results without changing `raw_result_version` from `v1`.
- Raw results must keep `payload_strategy` as a top-level field and must nest Phase 2-specific payload details under `payload_metadata`.
- Raw results must preserve Phase 1 raw evidence trust and sanitization requirements.
- `payload_metadata` must not expose unsafe raw payload values, raw data-pool record contents, secrets, tokens, credentials, cookies, PII, or sensitive data.
- Payload validation failures must use the existing `PAYLOAD_VALIDATION_ERROR` classification.
- `payload_safety.allow_destructive_operation` must default to `false`.
- If `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation != true`, execution must be blocked with `PAYLOAD_VALIDATION_ERROR`.
- Data pools must be client-scoped by S3 path under `data-pools/{client_id}/`.
- Data-pool files must support a plain list root and a wrapped object root containing `records`; the wrapped object form is preferred for future metadata.
- Data-pool selected records may be used either as the full request payload or as `payload_template` substitution source; full-payload mode is the default when no `payload_template` is configured.
- Duplicate reservation for `current_run` must be in-memory per orchestrator run and scoped by `client_id + audit_id + run_id`; persistent audit-wide duplicate tracking is excluded from Phase 2.
- Phase 2 must not introduce frontend, user account, billing, AI, reporting, scheduler, load testing, uptime monitoring, or chaos engineering functionality.

## 11. Dependencies

- Phase 1 core engine merged into main.
- Existing orchestrator and runner execution flow.
- Existing Raw Result Schema v1 extension points or compatible metadata fields for Phase 2 payload handling metadata.
- Existing sanitization layer.
- Existing S3 wrapper for loading data pools.
- Existing failure classification support for `PAYLOAD_VALIDATION_ERROR`.
- Existing strict `run_id` validation and duplicate `run_id` protection.

## 12. Assumptions

- Endpoint configuration can be extended with the confirmed Phase 2 payload fields without changing Phase 1 public behavior.
- Destructive operation classification is provided by endpoint configuration through `payload_safety.destructive_operation`; Phase 2 does not infer destructiveness solely from HTTP method.

## 13. Open Questions

- Do existing raw result consumers tolerate top-level `payload_strategy` plus nested `payload_metadata` without additional migration handling?

## 14. Definition of Done

Phase 2 is complete when:

- Product requirements in this specification are implemented only within Phase 2 scope.
- `static`, `generated`, and `data_pool` strategies are supported and validated.
- Deterministic substitutions work for all approved generated variables.
- Repeated `{{uuid}}` tokens in the same field resolve deterministically using `field_path + token_index`.
- Data-pool loading and deterministic assignment work from the required path structure.
- Data-pool loading accepts both supported schemas: plain list and wrapped object with `records`.
- Data-pool selected records can be used as full request payloads by default and as substitution sources when `payload_template` is configured.
- Duplicate checker supports all required policies and default behavior.
- In-run duplicate reservation uses an in-memory tracker per orchestrator run and scopes `current_run` checks by `client_id + audit_id + run_id`.
- Audit-wide duplicate tracking and persistent duplicate reservation are not implemented in Phase 2.
- Safety controls block unsafe generated payloads, data-pool reuse, and destructive operations according to endpoint configuration, including blocking `destructive_operation = true` unless `allow_destructive_operation = true`.
- Runner outputs sanitized SHA-256 `payload_metadata.payload_fingerprint` and `response_fingerprint` values.
- Runner fingerprints absent/no-body payloads using SHA-256 over the canonical sentinel string `EMPTY_PAYLOAD`.
- Runner records top-level `payload_strategy` and nested `payload_metadata` in raw results where applicable, including `payload_fingerprint`, `duplicate_check_scope`, `duplicate_detected`, `duplicate_allowed`, `duplicate_policy`, `generation_attempt`, `data_pool_name`, and `data_pool_record_fingerprint`.
- `duplicate_allowed` metadata is `true` only for detected duplicates that proceed under `duplicate_policy = allow`; otherwise it is `false`.
- Raw result `payload_strategy` and `payload_metadata` preserve `raw_result_version = "v1"` and remain backward-compatible with Phase 1 raw evidence consumers.
- Raw result `payload_metadata` never exposes unsafe raw payload values, raw data-pool record contents, secrets, tokens, credentials, cookies, PII, or sensitive data.
- Validation failures occur before outbound request execution and use `PAYLOAD_VALIDATION_ERROR`.
- Automated tests cover deterministic generation, data-pool assignment, duplicate policies, fingerprint canonicalization, safety controls, and edge cases listed in this spec.
- No out-of-scope Phase 3, frontend, auth, billing, AI, reporting, load testing, uptime monitoring, or chaos engineering functionality is included in the Phase 2 PR.
