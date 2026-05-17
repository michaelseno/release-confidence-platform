# Product Specification

## 1. Feature Overview

Phase 1 establishes the core backend execution engine for the Release Confidence Platform.

The platform is an Operational API Reliability Audit Platform focused on release confidence, deterministic evidence collection, evidence-driven API auditing, operational reliability, and trustworthy operational findings.

Phase 1 is limited to a config-driven backend engine that can load audit configuration, orchestrate an audit run, execute configured API requests, produce deterministic raw evidence, sanitize sensitive data, and persist raw results plus run metadata.

Phase 1 does not produce reliability scores, reports, dashboards, AI insights, user-facing account features, advanced observability, load testing, uptime monitoring, or chaos engineering capabilities.

## 2. Problem Statement

The platform cannot provide trustworthy release confidence findings unless it first has a deterministic and auditable execution foundation. Operators need a backend mechanism that can run API checks from explicit configuration, collect raw evidence consistently, protect secrets and sensitive information, and persist results in predictable locations for later analysis.

Phase 1 solves this by implementing the foundational execution engine: a generic Lambda orchestrator, S3/DynamoDB-backed configuration lookup, Secrets Manager-based secret resolution, deterministic API request execution, standardized failure classification, centralized sanitization, versioned raw result output, and metadata persistence.

## 3. User Persona / Target User

- **Technical operator / maintainer:** triggers or inspects configured audit runs and needs deterministic evidence, safe logs, and traceable run metadata.
- **Platform engineer / developer:** implements and maintains the backend engine and needs clear contracts for orchestration, configuration loading, execution, sanitization, and persistence.
- **QA engineer:** validates that Phase 1 executes configured API requests deterministically, handles failures consistently, prevents sensitive data exposure, and persists evidence in the required schema and storage locations.

## 4. User Stories

- As a technical operator, I want to trigger a configured audit run using client and audit identifiers so that the platform can execute the correct API checks without manual code changes.
- As a technical operator, I want raw evidence stored in predictable S3 paths so that audit runs can be inspected and replayed by downstream phases.
- As a technical operator, I want sensitive data sanitized before persistence or logging so that audit execution does not expose secrets, credentials, or PII.
- As a platform engineer, I want configuration loaded from S3 with metadata discoverable through DynamoDB so that runtime execution is config-driven and tenant/audit-specific.
- As a platform engineer, I want secrets resolved only through Secrets Manager references so that secrets are never stored in configs, metadata, logs, raw results, or reports.
- As a QA engineer, I want standardized failure classifications and a stable Raw Result Schema v1 so that execution outcomes are testable and deterministic.

## 5. Goals / Success Criteria

Phase 1 is successful when:

- A generic config-driven Lambda orchestrator accepts an event containing `client_id`, `audit_id`, `scenario_type`, and `triggered_by` or equivalent fields.
- The orchestrator uses a `run_id` supplied by the trigger event when present; otherwise, it generates a unique `run_id` for the audit run.
- Any externally supplied `run_id` is validated against the confirmed allowlist before it is used in S3 paths, DynamoDB keys, raw results, or logs; unsafe supplied values are rejected without normalization and without logging the raw rejected value.
- The engine loads `client_config`, `audit_config`, and `endpoint_config` from S3 using the required S3 key structure.
- Configuration metadata is queryable through DynamoDB.
- Config files contain only secret references and never contain literal secret values.
- Runtime secret values are resolved through AWS Secrets Manager only.
- The API runner executes configured HTTP requests using `requests`.
- The API runner supports configurable HTTP method, headers, payload, timeout, and retry behavior.
- Timing is measured using monotonic clocks and includes only outbound request duration from immediately before the request to immediately after the response or error.
- Raw results conform to Raw Result Schema v1 and include all required fields.
- Raw evidence is stored in S3 at `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- Run metadata is stored in DynamoDB with `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Before writing raw evidence for an externally supplied or generated `run_id`, the engine checks whether the target S3 result object or DynamoDB metadata record already exists and fails fast with a controlled `DUPLICATE_RUN_ID` control error if either exists.
- All persisted outputs and logs pass through a centralized sanitization layer before being written.
- Logs are separated into `internal_operational_logs` and `client_safe_logs` categories.
- Phase 1 can be validated without adding frontend, authentication, billing, AI insights, reporting, load testing, uptime monitor clone behavior, or chaos engineering functionality.

## 6. Feature Scope

### In Scope

Phase 1 includes only the following functionality:

- Generic config-driven Lambda orchestrator for audit execution.
- Orchestrator event model supporting fields equivalent to:
  - `client_id`
  - `audit_id`
  - `scenario_type`
  - `triggered_by`
  - optional `run_id`
- Audit run identity handling through `run_id`.
- Strict validation of externally supplied `run_id` values before path, key, raw result, metadata, or log usage.
- Rejection of unsafe externally supplied `run_id` values without normalization and without logging the raw rejected value.
- Duplicate `run_id` protection for the same `client_id` + `audit_id` before raw evidence is written.
- Config loaders for:
  - `client_config`
  - `audit_config`
  - `endpoint_config`
- S3-backed configuration loading using the following key structure:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
- DynamoDB metadata records that make configuration and run metadata queryable.
- Secrets Manager integration for resolving secret references at runtime.
- Enforcement that configs contain secret references only.
- Lightweight deterministic API runner implemented with `requests`.
- HTTP request execution for configured endpoints.
- Configurable request method, headers, payload, timeout, and retries.
- Deterministic duration measurement using monotonic clocks.
- Structured execution failure handling using the approved failure classifications:
  - `PASS`
  - `ASSERTION_FAILURE`
  - `HTTP_ERROR`
  - `TIMEOUT`
  - `CONNECTION_ERROR`
  - `INVALID_RESPONSE`
  - `RUNNER_ERROR`
  - `PAYLOAD_VALIDATION_ERROR`
- Stable versioned Raw Result Schema v1.
- Raw result persistence to S3 at `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- Run metadata persistence to DynamoDB with the required key pattern.
- Centralized sanitization before persistence, logging, or report-generation handoff.
- Sanitization of Authorization headers, cookies, API keys, passwords, emails, phone numbers, PII, and sensitive payload values.
- Log categorization into:
  - `internal_operational_logs`
  - `client_safe_logs`
- Unit-testable backend behavior for orchestration, config loading, request execution, failure classification, sanitization, and persistence path/key generation.

### Out of Scope

The following are explicitly excluded from Phase 1:

- Frontend or dashboard implementation.
- User authentication.
- RBAC.
- Billing.
- Subscriptions.
- Multi-user account management.
- Self-serve onboarding.
- AI insights or AI-generated recommendations.
- Reliability scoring.
- Operational findings generation beyond raw execution outcomes.
- Analytics dashboards.
- Report generation as a product feature.
- Advanced observability.
- Distributed tracing.
- Load testing or performance stress testing.
- Uptime monitor clone behavior.
- Synthetic continuous monitoring scheduler unless needed only for local/manual invocation testing.
- Chaos engineering.
- Heavy API frameworks.
- Public API product surface for customers.
- Config authoring UI.
- Secret creation or lifecycle management outside resolving existing Secrets Manager references.
- Multi-region execution.
- Production hardening beyond Phase 1 engine correctness and safe evidence handling.
- Later phase implementation work in this branch/PR.

### Future Considerations

The following may be considered in later phases only:

- Reliability scoring and audit findings derived from raw evidence.
- Report generation from persisted raw results.
- Operator dashboard or frontend workflows.
- Authentication, RBAC, billing, and multi-user tenant management.
- AI-assisted analysis.
- Scheduled recurring audit execution.
- Expanded observability dashboards and distributed tracing.
- Advanced scenario types and policy evaluation.
- Load testing, uptime monitoring, and chaos testing as separate products or modules if explicitly approved later.

## 7. Functional Requirements

### FR-001: Generic Lambda Orchestrator

The system must provide a generic Lambda-based orchestrator that coordinates a single audit run from event input through configuration loading, request execution, sanitization, raw result persistence, and metadata persistence.

The orchestrator must not contain client-specific execution logic.

### FR-002: Orchestrator Event Contract

The orchestrator must accept an event containing, at minimum, fields equivalent to:

- `client_id`
- `audit_id`
- `scenario_type`
- `triggered_by`

The orchestrator event may also contain an optional externally supplied `run_id`.

The orchestrator must validate required event fields before loading configuration or executing requests.

If required event fields are missing or invalid, the orchestrator must fail with a structured error and must not execute outbound API requests.

### FR-003: Run Identity

Each audit execution must have a `run_id`.

If the triggering event supplies a `run_id`, the orchestrator must use that supplied `run_id` only after validating it for safe use.

If the triggering event does not supply a `run_id`, the orchestrator must generate a unique `run_id`.

An externally supplied `run_id` is valid only when it matches all of the following rules:

- contains only uppercase letters `A-Z`, lowercase letters `a-z`, digits `0-9`, underscore `_`, and hyphen `-`
- has a minimum length of 8 characters
- has a maximum length of 80 characters

An externally supplied `run_id` must be rejected when it is empty or contains any disallowed value, including:

- slash `/`
- backslash `\\`
- dot `.` or traversal-like values
- whitespace
- control characters
- URL-encoded traversal-like values
- shell, log, or key injection characters

The orchestrator must not normalize unsafe externally supplied `run_id` values into safe values.

The orchestrator must generate a `run_id` only when `run_id` is absent, not when a supplied `run_id` is invalid.

If an externally supplied `run_id` is empty or invalid, the orchestrator must fail with a structured validation error before configuration loading, outbound API execution, raw result persistence, metadata persistence, or run-specific logging that includes the unsafe value.

The orchestrator must not log the raw rejected `run_id` value.

The same `run_id` must be used in:

- raw result records
- S3 raw result path
- DynamoDB metadata record sort key
- operational logs related to the run

### FR-003A: Duplicate Run ID Protection

Before writing raw evidence, the system must check whether either of the following already exists for the same `client_id` + `audit_id` + `run_id`:

- target raw result object at `raw-results/{client_id}/{audit_id}/{run_id}/results.json`
- DynamoDB run metadata record with `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`

If either target already exists, the system must fail fast with a controlled `DUPLICATE_RUN_ID` error.

On `DUPLICATE_RUN_ID`, the system must not overwrite, append to, or merge with existing raw evidence or metadata.

`DUPLICATE_RUN_ID` is an orchestrator/storage control error for Phase 1 unless the architecture explicitly decides otherwise. It must not be silently added to endpoint execution `failure_type` classifications unless explicitly appropriate in the implementation architecture.

The rationale for this requirement is that raw evidence is immutable and duplicate `run_id` values for the same `client_id` + `audit_id` weaken traceability.

The controlled `DUPLICATE_RUN_ID` error must not expose unsanitized identifiers or raw unsafe input values in logs or persisted error metadata.

### FR-004: S3 Configuration Loading

The engine must load configuration from S3 using the following required key structure:

- `configs/{client_id}/client_config.json`
- `configs/{client_id}/audits/{audit_id}/audit_config.json`
- `configs/{client_id}/audits/{audit_id}/endpoints.json`

The engine must treat missing, unreadable, or invalid JSON configuration as a structured run failure.

### FR-005: Configuration Metadata in DynamoDB

The system must store or query configuration metadata through DynamoDB so configuration availability and run metadata are discoverable without scanning S3 objects.

At minimum, metadata access must support identifying records by `client_id` and `audit_id`.

### FR-006: Secrets Handling

Configuration files must contain secret references only.

Runtime secret values must be retrieved from AWS Secrets Manager only.

Secret values must never be written to:

- S3 configuration objects
- DynamoDB metadata records
- raw result files
- internal operational logs
- client-safe logs
- future report-generation handoff data

If a required secret reference cannot be resolved, the run must fail with a structured failure and must not expose the unresolved or resolved secret value.

### FR-007: API Runner

The engine must include a lightweight API runner using `requests` for HTTP execution.

The runner must support configured:

- HTTP method
- URL
- headers
- payload/body
- timeout
- retry attempts

The runner must produce one raw result record per executed endpoint attempt summary or final endpoint execution outcome as defined by Raw Result Schema v1.

### FR-008: Deterministic Timing

The runner must measure `duration_ms` using a monotonic clock.

Timing must start immediately before the outbound HTTP request and stop immediately after receiving a response or catching a request error.

Timing must exclude:

- Lambda cold start time
- orchestrator overhead
- config loading time
- secret resolution time
- S3 persistence time
- DynamoDB persistence time
- logging time

### FR-009: Retry Handling

The runner must apply configured retry behavior deterministically.

The raw result must include `retry_attempts` representing the number of retries attempted for the endpoint execution.

Retry behavior must not obscure the final failure classification.

### FR-010: Failure Classification

Every endpoint execution outcome must map to exactly one of the approved failure classifications:

- `PASS`
- `ASSERTION_FAILURE`
- `HTTP_ERROR`
- `TIMEOUT`
- `CONNECTION_ERROR`
- `INVALID_RESPONSE`
- `RUNNER_ERROR`
- `PAYLOAD_VALIDATION_ERROR`

No unapproved failure classification may be persisted in Raw Result Schema v1.

Orchestrator/storage control errors, including `DUPLICATE_RUN_ID`, are outside the endpoint execution `failure_type` classification set unless the implementation architecture explicitly maps such errors to endpoint-level results and that mapping is approved.

### FR-011: Raw Result Schema v1

Raw results must use `raw_result_version` value `1` or `v1` consistently as defined by implementation documentation.

Each raw result record must include the following required fields:

- `raw_result_version`
- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_type`
- `method`
- `url`
- `status_code`
- `duration_ms`
- `failure_type`
- `payload_strategy`
- `timestamp`
- `retry_attempts`

Fields that cannot be populated due to execution failure must still be present with a documented null-safe value where applicable.

### FR-012: Raw Evidence Persistence

The engine must store sanitized raw evidence in S3 at:

`raw-results/{client_id}/{audit_id}/{run_id}/results.json`

The persisted object must contain Raw Result Schema v1 records for the run.

The object must not contain secrets, credentials, PII, or unsanitized sensitive payload values.

### FR-013: DynamoDB Run Metadata Persistence

The engine must store sanitized run metadata in DynamoDB using the key pattern:

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#RUN#{run_id}`

The metadata record must allow operators and downstream phases to locate the corresponding S3 raw result object.

### FR-014: Centralized Sanitization Layer

The system must route data through a centralized sanitization layer before persistence, logging, or report-generation handoff.

The sanitization layer must sanitize, at minimum:

- Authorization headers
- cookies
- API keys
- passwords
- emails
- phone numbers
- PII
- sensitive payload values

The sanitization layer must be reusable by orchestrator, runner, persistence, and logging paths.

### FR-015: Logging Categories

The system must produce logs in two explicit categories:

- `internal_operational_logs`
- `client_safe_logs`

Both categories must be sanitized before emission.

`client_safe_logs` must not include implementation internals, secrets, credentials, PII, or sensitive payload values.

### FR-016: Phase Boundary Enforcement

Phase 1 implementation must not introduce frontend, authentication, billing, AI, reporting, load testing, uptime monitoring, chaos engineering, or other explicitly out-of-scope capabilities.

## 8. Acceptance Criteria

### AC-001: Orchestrator Accepts Valid Event

Given an orchestrator event containing valid `client_id`, `audit_id`, `scenario_type`, and `triggered_by` values  
When the Lambda orchestrator is invoked  
Then it validates the event and starts a single audit run using those identifiers.

### AC-002: Orchestrator Rejects Missing Required Event Fields

Given an orchestrator event missing `client_id`, `audit_id`, `scenario_type`, or `triggered_by`  
When the Lambda orchestrator is invoked  
Then it returns or records a structured validation failure and does not execute any outbound API request.

### AC-002A: Orchestrator Uses Supplied Run ID When Safe

Given an orchestrator event contains valid `client_id`, `audit_id`, `scenario_type`, `triggered_by`, and an externally supplied `run_id` that contains only `A-Z`, `a-z`, `0-9`, `_`, and `-` and is 8 to 80 characters long  
When the Lambda orchestrator is invoked  
Then it validates the supplied `run_id` before use and uses the supplied `run_id` unchanged in raw results, the S3 raw result path, the DynamoDB metadata sort key, and sanitized run logs.

### AC-002B: Orchestrator Generates Run ID When Not Supplied

Given an orchestrator event contains valid `client_id`, `audit_id`, `scenario_type`, and `triggered_by` but does not contain `run_id`  
When the Lambda orchestrator is invoked  
Then the orchestrator generates a unique `run_id` and uses it consistently in raw results, the S3 raw result path, the DynamoDB metadata sort key, and sanitized run logs.

### AC-002C: Orchestrator Rejects Unsafe Supplied Run ID

Given an orchestrator event contains an externally supplied `run_id` that is empty, shorter than 8 characters, longer than 80 characters, or contains slashes, backslashes, dots, traversal-like values, whitespace, control characters, URL-encoded traversal-like values, or shell/log/key injection characters  
When the Lambda orchestrator is invoked  
Then it returns or records a structured validation failure before configuration loading, outbound API execution, S3 raw result persistence, DynamoDB metadata persistence, or emitting logs containing the raw rejected `run_id` value.

### AC-002D: Orchestrator Does Not Normalize Invalid Supplied Run ID

Given an orchestrator event contains an invalid externally supplied `run_id` that could be made safe only by trimming, decoding, replacing, or removing characters  
When the Lambda orchestrator is invoked  
Then it rejects the supplied `run_id` and does not normalize it into a generated or modified `run_id`.

### AC-002E: Orchestrator Generates Run ID Only When Absent

Given an orchestrator event contains a present but invalid externally supplied `run_id`  
When the Lambda orchestrator is invoked  
Then it fails with a structured validation error and does not generate a replacement `run_id`.

### AC-002F: Duplicate Run ID Fails Before Raw Evidence Write

Given an audit run is using a valid `run_id` and the target S3 raw result object or DynamoDB run metadata record already exists for the same `client_id`, `audit_id`, and `run_id`  
When the engine reaches the pre-write duplicate check before writing raw evidence  
Then it fails fast with a controlled `DUPLICATE_RUN_ID` error and does not overwrite, append to, or merge with the existing object or metadata record.

### AC-002G: Duplicate Run ID Is Not Endpoint Failure Classification By Default

Given a duplicate `run_id` is detected before raw evidence is written  
When the controlled error is produced  
Then `DUPLICATE_RUN_ID` is treated as an orchestrator/storage control error and is not persisted as an endpoint `failure_type` unless the architecture explicitly defines and approves that mapping.

### AC-003: Configuration Loaded From Required S3 Paths

Given valid configuration objects exist at the required S3 keys for a client and audit  
When an audit run starts for that `client_id` and `audit_id`  
Then the engine loads `client_config.json`, `audit_config.json`, and `endpoints.json` from those exact key patterns.

### AC-004: Missing Configuration Fails Safely

Given one or more required S3 configuration objects are missing or unreadable  
When an audit run starts  
Then the run fails with a structured failure and no endpoint HTTP request is executed.

### AC-005: Invalid Configuration JSON Fails Safely

Given a required S3 configuration object contains invalid JSON  
When the engine attempts to load configuration  
Then the run fails with a structured failure and no endpoint HTTP request is executed.

### AC-006: Configuration Metadata Is Queryable

Given configuration metadata exists for a client and audit  
When the engine or operator queries DynamoDB by the supported client/audit metadata access pattern  
Then the metadata can be retrieved without scanning raw S3 result objects.

### AC-007: Secrets Are Resolved Only From Secrets Manager

Given a configuration value references a secret  
When the engine prepares the request  
Then it resolves the secret value from AWS Secrets Manager and does not read a literal secret from S3 or DynamoDB configuration data.

### AC-008: Secret Resolution Failure Is Sanitized

Given a required secret reference is missing, inaccessible, or invalid  
When the engine attempts to resolve the secret  
Then the run fails with a structured failure and no secret value is written to logs, DynamoDB, or S3 raw results.

### AC-009: API Runner Executes Configured HTTP Request

Given a valid endpoint configuration with method, URL, headers, payload, timeout, and retry settings  
When the runner executes the endpoint  
Then it sends an HTTP request using the configured values and records the execution outcome.

### AC-010: Timing Excludes Non-Request Overhead

Given an endpoint execution is performed  
When `duration_ms` is calculated  
Then timing starts immediately before the outbound HTTP request and stops immediately after response or request error, excluding Lambda cold start, orchestration, config loading, secret resolution, persistence, and logging time.

### AC-011: Timing Uses Monotonic Clock

Given an endpoint execution is performed  
When duration is measured  
Then the implementation uses a monotonic clock source rather than wall-clock timestamp subtraction.

### AC-012: Retry Attempts Are Recorded

Given an endpoint configuration allows retries and an execution requires retry attempts  
When the final endpoint outcome is recorded  
Then `retry_attempts` equals the number of retries attempted for that endpoint execution.

### AC-013: Failure Type Is Approved

Given any endpoint execution outcome occurs  
When the raw result is generated  
Then `failure_type` is exactly one of `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, or `PAYLOAD_VALIDATION_ERROR`.

### AC-014: Successful Execution Records PASS

Given an endpoint responds successfully and all configured assertions pass  
When the raw result is generated  
Then `failure_type` is `PASS` and the response `status_code` is recorded.

### AC-015: HTTP Error Classification

Given an endpoint returns an HTTP response classified as an error by the configured expectations  
When the raw result is generated  
Then `failure_type` is `HTTP_ERROR` unless a more specific configured assertion failure applies.

### AC-016: Timeout Classification

Given an endpoint request exceeds the configured timeout  
When the raw result is generated  
Then `failure_type` is `TIMEOUT` and `duration_ms` is present.

### AC-017: Connection Error Classification

Given an endpoint cannot establish a network connection  
When the raw result is generated  
Then `failure_type` is `CONNECTION_ERROR`.

### AC-018: Invalid Response Classification

Given an endpoint response cannot be parsed or interpreted according to the configured response expectations  
When the raw result is generated  
Then `failure_type` is `INVALID_RESPONSE`.

### AC-019: Payload Validation Classification

Given a configured request payload is invalid before execution  
When the runner validates the payload  
Then `failure_type` is `PAYLOAD_VALIDATION_ERROR` and no outbound request is sent for that endpoint.

### AC-020: Runner Error Classification

Given an unexpected runner exception occurs that is not covered by another failure classification  
When the raw result is generated  
Then `failure_type` is `RUNNER_ERROR` and the persisted result remains sanitized.

### AC-021: Raw Result v1 Required Fields

Given an endpoint execution outcome exists  
When the raw result record is persisted  
Then the record includes `raw_result_version`, `client_id`, `audit_id`, `run_id`, `endpoint_id`, `scenario_type`, `method`, `url`, `status_code`, `duration_ms`, `failure_type`, `payload_strategy`, `timestamp`, and `retry_attempts`.

### AC-022: Raw Results Stored At Required S3 Path

Given an audit run completes with one or more endpoint outcomes  
When raw evidence is persisted  
Then the engine writes sanitized results to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.

### AC-023: DynamoDB Metadata Uses Required Keys

Given an audit run completes or reaches a persisted terminal state  
When run metadata is stored  
Then the DynamoDB record uses `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.

### AC-024: Metadata Locates Raw Results

Given a DynamoDB run metadata record exists  
When an operator or downstream component reads the metadata  
Then it can identify the corresponding S3 raw result object path for that run.

### AC-025: Sanitization Before Raw Result Persistence

Given request or response data contains Authorization headers, cookies, API keys, passwords, emails, phone numbers, PII, or sensitive payload values  
When raw results are persisted to S3  
Then those values are sanitized and no literal sensitive value appears in the persisted object.

### AC-026: Sanitization Before Metadata Persistence

Given run metadata contains values derived from configuration, execution, or errors  
When metadata is written to DynamoDB  
Then secrets, credentials, PII, and sensitive payload values are sanitized before persistence.

### AC-027: Sanitization Before Logging

Given execution data contains secrets, credentials, PII, or sensitive payload values  
When either log category emits a log entry  
Then the emitted log entry contains sanitized values only.

### AC-028: Log Categories Are Explicit

Given the engine emits logs during an audit run  
When logs are inspected  
Then each relevant log entry is categorized as `internal_operational_logs` or `client_safe_logs`.

### AC-029: Client-Safe Logs Exclude Sensitive and Internal Data

Given `client_safe_logs` are emitted  
When the log content is inspected  
Then it does not contain secrets, credentials, PII, sensitive payload values, stack traces, or implementation internals.

### AC-030: Phase 1 Excludes Frontend and Account Features

Given the Phase 1 branch is reviewed  
When scope is validated  
Then no frontend/dashboard, authentication, RBAC, billing, subscriptions, multi-user account, or self-serve onboarding feature is introduced.

### AC-031: Phase 1 Excludes Deferred Intelligence and Testing Products

Given the Phase 1 branch is reviewed  
When scope is validated  
Then no AI insights, advanced observability, distributed tracing, load testing, uptime monitor clone, chaos engineering, analytics/report-generation product feature, or heavy API framework is introduced.

## 9. Edge Cases

- Orchestrator event is missing required identifiers.
- Orchestrator event includes empty strings or invalid identifier formats.
- Orchestrator event does not include `run_id`, requiring orchestrator-generated run identity.
- Orchestrator event includes externally supplied `run_id` shorter than 8 characters or longer than 80 characters.
- Orchestrator event includes externally supplied `run_id` containing slash, backslash, dot, traversal-like values, whitespace, control characters, URL-encoded traversal-like values, or shell/log/key injection characters.
- Externally supplied `run_id` could be made safe only through trimming, decoding, replacement, or character removal; the value must still be rejected rather than normalized.
- Externally supplied `run_id` is invalid; the orchestrator must not generate a replacement `run_id`.
- Target raw result object already exists for the same `client_id` + `audit_id` + `run_id`.
- Target DynamoDB run metadata record already exists for the same `client_id` + `audit_id` + `run_id`.
- Duplicate `run_id` is detected after some run preparation but before raw evidence write; existing evidence and metadata must remain unchanged.
- `client_id` exists but `audit_id` does not exist.
- Required S3 config object is missing.
- Required S3 config object is inaccessible due to permissions.
- Required S3 config object contains invalid JSON.
- Config schema is syntactically valid JSON but missing required fields.
- Config includes a literal value where a secret reference is required.
- Secret reference is missing from Secrets Manager.
- Secret reference exists but access is denied.
- Secret value is resolved but must be excluded from every persisted and logged output.
- Endpoint configuration contains an unsupported HTTP method.
- Endpoint URL is missing, malformed, or uses an unsupported scheme.
- Header values include sensitive data requiring sanitization.
- Payload contains nested sensitive values requiring sanitization.
- Request payload fails validation before execution.
- Endpoint returns no response body.
- Endpoint returns malformed JSON when JSON is expected.
- Endpoint returns HTTP 4xx or 5xx.
- Endpoint times out.
- DNS, TLS, connection refused, or network errors occur.
- Retry configuration is zero, omitted, or exceeds an implementation-defined safe maximum.
- Multiple endpoints are configured and one endpoint fails while others are executable.
- Persistence to S3 fails after endpoint execution.
- Metadata write to DynamoDB fails after raw result generation.
- Sanitization receives unexpected data types or deeply nested objects.
- Logs are emitted during exception handling.
- Duration measurement occurs for failures where `status_code` is unavailable.

## 10. Constraints

- Phase 1 is restricted to backend core engine foundation work.
- The API runner must use `requests`.
- Secrets must be handled through AWS Secrets Manager only.
- Literal secrets must not be stored in S3 configs, DynamoDB records, logs, raw results, or report-generation handoff data.
- S3 config keys must follow the required structure exactly.
- Raw result S3 keys must follow `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- DynamoDB run metadata keys must follow `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- `run_id` ownership is defined as: use the trigger event supplied `run_id` if present and safe; otherwise generate `run_id` in the orchestrator.
- Any externally supplied `run_id` must be validated before use in S3 paths, DynamoDB keys, raw result records, metadata records, or logs.
- Externally supplied `run_id` values are allowed only when they contain `A-Z`, `a-z`, `0-9`, `_`, and `-`, with minimum length 8 and maximum length 80.
- Externally supplied `run_id` values must not permit slashes, backslashes, dots, traversal-like values, whitespace, control characters, URL-encoded traversal-like values, shell/log/key injection characters, or log/key ambiguity.
- Invalid externally supplied `run_id` values must fail validation before configuration loading, outbound API execution, persistence, or unsafe log emission.
- Invalid externally supplied `run_id` values must not be normalized, trimmed, decoded into accepted form, replaced, or repaired.
- The orchestrator must generate `run_id` only when the event omits `run_id`, not when a supplied value is invalid.
- The raw rejected `run_id` value must not be logged.
- Before writing raw evidence, the system must check for an existing target S3 raw result object and existing DynamoDB run metadata record for the same `client_id` + `audit_id` + `run_id`.
- If the target raw result object or metadata record exists, the system must fail fast with controlled `DUPLICATE_RUN_ID` and must not overwrite, append, or merge evidence or metadata.
- `DUPLICATE_RUN_ID` is an orchestrator/storage control error unless the architecture explicitly decides otherwise; it must not be silently added to endpoint failure classifications.
- Raw Result Schema v1 must be stable for Phase 1 outputs.
- Failure classifications must be limited to the approved set.
- Timing must use monotonic clocks and exclude non-request overhead.
- Logs must be categorized as `internal_operational_logs` or `client_safe_logs`.
- All logs and persisted outputs must be sanitized before write/emission.
- The implementation must avoid heavy API frameworks.
- This branch must remain Phase 1 only and must not include later phase capabilities.

## 11. Dependencies

- Phase 0 project foundation merged into `main`.
- Existing repository structure, tooling, documentation conventions, and Serverless packaging foundation from Phase 0.
- AWS Lambda for orchestrator runtime.
- Amazon S3 for configuration and raw result object storage.
- Amazon DynamoDB for configuration/run metadata query and persistence.
- AWS Secrets Manager for runtime secret resolution.
- IAM permissions allowing the Lambda runtime to read required S3 config objects, write raw result objects, read/write required DynamoDB metadata, and read approved Secrets Manager secrets.
- Python `requests` library for HTTP execution.
- Python monotonic clock capability for duration measurement.

## 12. Assumptions

- **Confirmed for Phase 1:** The orchestrator must use a trigger event supplied `run_id` when present and valid; otherwise, it must generate `run_id`.
- **Confirmed for Phase 1:** Externally supplied `run_id` values are valid only when they contain `A-Z`, `a-z`, `0-9`, `_`, and `-`, with minimum length 8 and maximum length 80.
- **Confirmed for Phase 1:** Unsafe externally supplied `run_id` values must be rejected without normalization, the raw rejected value must not be logged, and the orchestrator must not generate a replacement `run_id` for invalid supplied values.
- **Confirmed for Phase 1:** Duplicate `run_id` for the same `client_id` + `audit_id` must fail fast with controlled `DUPLICATE_RUN_ID` before raw evidence is written, and existing raw evidence or metadata must not be overwritten, appended, or merged.
- **Requires confirmation:** Raw Result Schema v1 may represent `raw_result_version` as either `1` or `v1`, but the implementation must choose one representation and use it consistently.
- **Requires confirmation:** The exact DynamoDB table names and S3 bucket names follow Phase 0 naming conventions and environment/stage configuration.
- **Requires confirmation:** Endpoint assertion rules are limited to what is necessary to classify `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, and `INVALID_RESPONSE` in Phase 1.
- **Requires confirmation:** A single `results.json` object may contain an array of endpoint result records for the run.
- **Requires confirmation:** If one endpoint fails, the orchestrator should continue executing remaining configured endpoints unless configuration loading, secret resolution, or a global runner failure prevents safe continuation.

## 13. Open Questions

- What exact value should Raw Result Schema v1 use for `raw_result_version`: numeric `1` or string `v1`?
- What minimum config schema fields are required for `client_config.json`, `audit_config.json`, and `endpoints.json` beyond the S3 path requirements?
- What are the exact assertion types required in Phase 1 to distinguish `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, and `INVALID_RESPONSE`?
- Should raw result persistence occur only at the end of a run or incrementally during execution?
- What terminal metadata statuses are required for run metadata records?
- What is the approved maximum retry count and timeout range for Phase 1?
- What masking tokens or redaction format should sanitization use for secrets and PII?

## 14. Operator-Facing Impact

- Operators can trigger or inspect backend audit runs by `client_id`, `audit_id`, `scenario_type`, and `run_id` without changing code.
- Operators can locate raw run evidence in a deterministic S3 path.
- Operators can locate run metadata in DynamoDB using a predictable client/audit/run key pattern.
- Operators receive a controlled duplicate-run failure instead of overwritten, appended, or merged evidence when a `run_id` is reused for the same client and audit.
- Operators receive sanitized logs separated into internal operational and client-safe categories.
- Operators do not receive dashboards, reports, scoring, or AI-derived findings in Phase 1.

## 15. Backend/System Impact

- Adds the first runtime audit execution path to the backend platform.
- Introduces S3-backed runtime configuration loading.
- Introduces DynamoDB metadata access and run metadata persistence.
- Introduces Secrets Manager dependency for runtime secret resolution.
- Introduces deterministic HTTP execution through `requests`.
- Introduces Raw Result Schema v1 as the first persisted evidence contract.
- Introduces centralized sanitization as a mandatory system boundary before persistence and logging.
- Introduces operational log categorization requirements for all Phase 1 execution paths.
- Introduces duplicate run identity protection before raw evidence writes to preserve immutable evidence traceability.

## 16. Definition of Done

Phase 1 is done when:

- All in-scope functional requirements are implemented or explicitly documented as not implemented with approval before merge.
- All acceptance criteria in this specification are satisfied by tests, documented validation evidence, or both.
- Unit tests cover orchestrator validation, config loading, secret-reference behavior, runner outcome mapping, timing boundaries where practical, retry recording, raw result schema generation, S3 path generation, DynamoDB key generation, and sanitization.
- Unit tests cover externally supplied `run_id` allowlist validation before use in S3 path generation, DynamoDB key generation, raw result records, metadata records, and logs.
- Unit tests cover rejection of externally supplied `run_id` values containing slashes, backslashes, dots/traversal-like values, whitespace, control characters, URL-encoded traversal-like values, shell/log/key injection characters, empty values, values shorter than 8 characters, and values longer than 80 characters.
- Unit tests verify invalid externally supplied `run_id` values are not normalized, are not replaced by generated `run_id` values, and are not logged in raw rejected form.
- Unit tests cover duplicate `run_id` detection before raw evidence write for both existing S3 raw result object and existing DynamoDB metadata record.
- Validation evidence confirms `DUPLICATE_RUN_ID` does not overwrite, append, or merge existing raw evidence or metadata and is treated as an orchestrator/storage control error unless explicitly approved otherwise by architecture.
- No test fixture, log, raw result, metadata record, or documentation example contains real secrets or real PII.
- Raw Result Schema v1 is documented and stable for downstream phases.
- Failure classifications are implemented exactly as listed in this specification.
- The branch does not introduce out-of-scope frontend, account, AI, analytics/reporting product, load testing, uptime monitoring, chaos engineering, or heavy framework capabilities.
- Local validation commands from the project foundation pass for Phase 1 changes.
- The Phase 1 product specification is stored under `docs/product/` and reviewed as part of the phase PR.
