# Technical Design

## 1. Feature Overview

Phase 1 implements the backend-only core execution engine for the Release Confidence Platform. The engine accepts a Lambda invocation event, validates audit identifiers, loads tenant/audit configuration from S3, resolves runtime secrets through AWS Secrets Manager, executes configured API requests with `requests`, generates deterministic Raw Result Schema v1 evidence, sanitizes all persisted/logged data, writes raw evidence to S3, and persists run metadata to DynamoDB.

This design translates `docs/product/phase_1_core_engine_foundation_product_spec.md` plus confirmed Phase 1 decisions into an implementation-ready blueprint for backend engineering. It is intentionally limited to Phase 1 and must not introduce frontend, authentication, reporting, scoring, AI, load testing, uptime monitoring, chaos engineering, or later-phase audit lifecycle behavior.

## 2. Product Requirements Summary

Phase 1 must provide:

- A generic Lambda orchestrator for one audit run at a time.
- An orchestrator event contract containing `client_id`, `audit_id`, `scenario_type`, `triggered_by`, and optional `run_id`.
- Safe run identity handling where a supplied `run_id` is accepted only when it exactly matches `^[A-Za-z0-9_-]{8,80}$`; otherwise it is rejected without normalization or raw-value logging. When absent, the orchestrator generates a compliant `run_id`.
- S3 configuration loading from exact required keys:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
- DynamoDB metadata access and run metadata persistence using `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Secrets Manager-only runtime secret resolution; no literal secrets in configs, logs, metadata, or raw evidence.
- API execution through `requests` with configured method, URL, headers, payload, timeout, and explicit retries.
- Timing measured with monotonic clocks only around outbound request execution.
- Foundational assertions only: expected status codes, response JSON validity, and optional required response fields.
- Approved failure classifications only: `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`.
- Raw Result Schema v1 using `raw_result_version = "v1"`.
- Single end-of-run raw evidence write to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`, preserving a future incremental persistence boundary without changing the schema, with duplicate `run_id` detection before writing raw evidence or metadata.
- Centralized sanitization with sensitive values replaced by `"[REDACTED]"`.
- Explicit structured logging categories: `internal_operational_logs` and `client_safe_logs`.
- Local/unit validation with mock AWS clients and a local mock API.

## 3. Requirement-to-Architecture Mapping

| Product Requirement / Decision | Technical Design Response |
| --- | --- |
| FR-001, AC-001: Generic orchestrator | Define a Lambda handler boundary that delegates to an orchestrator service and contains no client-specific logic. |
| FR-002, AC-002: Event validation | Define event schema, required fields, identifier rules, optional `run_id` validation, and fail-before-execution behavior. |
| Confirmed decision 1 and additional confirmed run-id safety requirement: `run_id` | Allow caller-supplied `run_id` only when it exactly matches `^[A-Za-z0-9_-]{8,80}$`; reject slashes, backslashes, dots/traversal-like values, whitespace, control characters, URL-encoded traversal-like values, shell/log/key injection characters, empty values, and non-matching values before any S3 path, DynamoDB key, metadata, response, or log use. Do not normalize unsafe values or log raw rejected values. Generate a compliant `run_id` only when absent, not when invalid. |
| Confirmed duplicate supplied `run_id` behavior | Fail fast with controlled `DUPLICATE_RUN_ID` orchestration/storage error when the target raw result object or run metadata already exists for the same validated `client_id` + `audit_id` + `run_id`. Do not overwrite, append, or merge immutable raw evidence. Keep `DUPLICATE_RUN_ID` distinct from endpoint `failure_type` classifications. |
| FR-004, AC-003 through AC-005: S3 configs | Define exact S3 config keys and config loader behavior for missing/unreadable/invalid JSON/config schema failures. |
| FR-005, FR-013, AC-006, AC-023, AC-024: DynamoDB metadata | Define metadata key model, Phase 1 statuses, raw result locator fields, and table access through storage client abstraction. |
| FR-006, AC-007, AC-008: Secrets | Define Secrets Manager-only reference format behavior, resolution boundary, and no-secret logging/persistence policy. |
| FR-007 through FR-009, AC-009 through AC-012: Runner/timing/retries | Define runner contract, monotonic timing boundary, timeout/retry limits, and retry recording semantics. |
| Confirmed decision 5: retry/timeout defaults | Use `default_timeout_seconds = 10`, `max_timeout_seconds = 30`, `default_retries = 0`, `max_retries = 3`. |
| FR-010, AC-013 through AC-020: Failure classification | Define exactly one approved `failure_type` per endpoint outcome and precedence rules. |
| FR-011, AC-021, confirmed decision 2 | Define Raw Result Schema v1 with `raw_result_version = "v1"` and required fields. |
| FR-012, AC-022, confirmed decision 3 | Define one write at run completion to `results.json`; internal evidence sink remains array-based for future incremental persistence. |
| Confirmed decision 4 | Limit assertions to expected status codes, JSON validity, and optional required response fields. |
| FR-014, AC-025 through AC-027, confirmed decision 6 | Define sanitizer contract and redaction token `"[REDACTED]"` before persistence or logging. |
| FR-015, AC-028, AC-029 | Define two sanitized structured log categories and content boundaries. |
| Confirmed decision 7 | Restrict Phase 1 metadata statuses to `STARTED`, `COMPLETED`, and `FAILED`. |
| FR-016, AC-030, AC-031 | Explicitly exclude frontend, auth, scoring, reporting, AI, advanced observability, load testing, uptime monitoring, chaos, and heavy frameworks. |

## 4. Technical Scope

### Current Technical Scope

Phase 1 implementation includes:

- Lambda entrypoint and orchestrator service for a single audit run.
- Event validation and run id creation/validation before path, key, metadata, response, or log construction.
- Duplicate `run_id` detection for immutable raw evidence before metadata creation/update and before raw result write.
- Config loaders for client, audit, and endpoint configs from S3.
- Minimal config schema validation necessary for execution safety.
- DynamoDB access for configuration metadata lookup where needed and run metadata persistence.
- Secrets Manager client wrapper for resolving approved secret references.
- API runner using `requests`.
- Foundational assertion evaluation.
- Failure classification and raw result model/schema generation.
- Central sanitizer and logging wrappers.
- S3 raw result persistence and DynamoDB metadata status updates.
- Unit/local tests using mock AWS clients and local mock API fixtures.

### Out of Scope

Phase 1 must not implement:

- Frontend or dashboard behavior.
- User authentication, authorization, RBAC, billing, subscriptions, account management, or onboarding.
- Public customer API surface.
- Config authoring UI or secret lifecycle management.
- Reliability scoring, analytics dashboards, generated findings, or report product features.
- AI insights or AI recommendations.
- Advanced observability, distributed tracing, production SLOs, or incident workflows.
- Load testing, uptime-monitor clone behavior, continuous synthetic monitoring, or chaos engineering.
- Multi-region execution.
- Heavy API frameworks.
- Full audit lifecycle states beyond `STARTED`, `COMPLETED`, and `FAILED`.

### Future Technical Considerations

Later phases may add:

- Incremental/append raw evidence persistence using the same Raw Result Schema v1 record shape.
- Aggregation, scoring, findings, and report generation from raw results.
- Dashboards and operator workflows.
- Authentication, RBAC, tenant lifecycle management, and public APIs.
- Expanded assertion types and scenario policies.
- Scheduled recurring audits and richer lifecycle/audit trail states.
- Advanced observability and distributed tracing.

These future considerations must not alter Phase 1 implementation scope.

## 5. Architecture Overview

### Runtime Flow

1. Lambda handler receives invocation event.
2. Handler delegates to orchestrator.
3. Orchestrator validates event fields and obtains a safe canonical `run_id`; externally supplied values must exactly match `^[A-Za-z0-9_-]{8,80}$` before any log, S3 path, DynamoDB key, metadata, or response construction. Invalid supplied values are rejected; a generated `run_id` is used only when the event omits `run_id`.
4. Orchestrator checks duplicate state for the resolved `client_id` + `audit_id` + `run_id` before writing metadata or raw evidence: S3 target object existence and DynamoDB metadata existence are checked, and any existing object/item fails fast with `DUPLICATE_RUN_ID`.
5. Orchestrator emits sanitized `STARTED` operational log and writes sanitized DynamoDB run metadata status `STARTED` using only validated canonical identifiers.
6. Config loader retrieves required S3 config JSON objects from exact configured keys.
7. Config validator verifies required structure, endpoint executability, no literal secrets where secret references are required, timeout/retry limits, methods, URLs, payload shape, and assertion shape.
8. Secrets client resolves secret references through AWS Secrets Manager only.
9. Runner executes each valid endpoint using `requests`, measuring each outbound attempt duration with monotonic clocks.
10. Runner applies explicit retry behavior and returns one final endpoint outcome record including retry count.
11. Assertion evaluator maps response and expectations to `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, or `INVALID_RESPONSE` as applicable.
12. Raw result builder creates one Raw Result Schema v1 record per endpoint final outcome or pre-request endpoint failure.
13. Sanitizer processes raw result records, metadata, and all log payloads before write/emission.
14. Before final raw evidence persistence, storage performs a final duplicate guard for the exact target raw result object and ensures terminal metadata updates apply only to the item created by this invocation. Any pre-existing object/item discovered before invocation-owned creation fails with `DUPLICATE_RUN_ID`; raw evidence must not be overwritten, appended, or merged.
15. S3 storage client writes one sanitized `results.json` object at run completion.
16. DynamoDB storage client updates/persists run metadata status `COMPLETED` or `FAILED`, including raw result S3 location when available.
17. Orchestrator returns a structured, sanitized invocation result to the caller/runtime.

### Boundary for Future Incremental Persistence

Phase 1 writes raw evidence once at run completion. Internally, the orchestrator should collect endpoint result records through a narrow evidence sink/buffer contract, for example `record_endpoint_result(raw_result_record)`. In Phase 1 this sink is an in-memory list flushed once to `results.json`; future phases may swap the sink to incremental writes without changing individual Raw Result Schema v1 records.

## 6. System Components

### Lambda Handler

**Location:** `apps/backend/handlers/` or existing Serverless handler path.

**Responsibilities:**

- Accept Lambda event/context.
- Instantiate configured runtime dependencies from environment variables.
- Delegate to orchestrator.
- Return sanitized structured success/failure response.
- Avoid business logic beyond dependency wiring and top-level exception handling.

### Orchestrator

**Location:** `apps/backend/orchestrator/`.

**Runtime contract:**

- Input: validated or raw Lambda event dictionary plus dependency clients.
- Output: sanitized run summary containing `client_id`, `audit_id`, `run_id`, final status, raw result path when available, and high-level failure summary when failed.
- Coordinates exactly one audit run.
- Uses same `run_id` across logs, raw results, S3 paths, and DynamoDB keys.
- Writes `STARTED` before endpoint execution when event validation succeeds.
- Writes terminal `COMPLETED` when all runnable endpoints are processed and raw evidence persistence succeeds.
- Writes terminal `FAILED` for validation/config/secret/global/persistence failures or when implementation chooses run-level failure for endpoint failures. Endpoint-level failures still produce Raw Result Schema v1 records when execution reached the runner.

### Event Validator / Run Identity Service

**Location:** `packages/core/models/`, `packages/core/schemas/`, or orchestrator-adjacent module.

**Contract:**

- Validate required event fields: `client_id`, `audit_id`, `scenario_type`, `triggered_by`.
- Accept optional `run_id`.
- Generate `run_id` only when omitted. Do not generate a replacement when an externally supplied `run_id` is invalid.
- Treat event-supplied `run_id` as untrusted external input until it has passed the centralized run identity validation routine.
- Exact externally supplied `run_id` policy: accept only strings matching `^[A-Za-z0-9_-]{8,80}$`.
- This regex intentionally permits only uppercase letters `A-Z`, lowercase letters `a-z`, digits `0-9`, underscore `_`, and hyphen `-`, with minimum length 8 and maximum length 80.
- Reject externally supplied `run_id` values that are empty, non-strings, shorter than 8 characters, longer than 80 characters, contain slashes `/`, backslashes `\\`, dots `.`, traversal-like values, whitespace, leading/trailing whitespace, tabs, newlines, carriage returns, control characters, percent/URL-encoded traversal-like values such as `%2e`, `%2f`, `%5c`, shell/log/key injection characters, or any character outside the approved regex.
- Do not normalize, trim, decode-and-accept, case-fold, append, prefix, hash, or otherwise transform unsafe externally supplied `run_id` values. If the supplied value does not exactly match the regex as received, reject the event.
- Return and persist/log only the validated canonical `run_id`; never include the rejected raw external `run_id` in logs, errors, S3 keys, DynamoDB keys, metadata, or responses.
- Generated `run_id` format: canonical UUIDv4 string such as `550e8400-e29b-41d4-a716-446655440000` (`36` characters; lowercase hex digits plus hyphens). This naturally satisfies `^[A-Za-z0-9_-]{8,80}$` and is generated only when `run_id` is absent.
- Other identifiers (`client_id`, `audit_id`, `scenario_type`, `triggered_by`, `endpoint_id`) remain path/key/log-safe identifiers under the broader project identifier routine unless separately tightened by implementation; do not apply the dot-permitting generic identifier policy to `run_id`.

### Config Loaders

**Location:** `packages/config/client_config/`, `packages/config/audit_config/`, `packages/config/endpoint_config/`.

**Runtime contracts:**

- `ClientConfigLoader.load(client_id)` reads `configs/{client_id}/client_config.json`.
- `AuditConfigLoader.load(client_id, audit_id)` reads `configs/{client_id}/audits/{audit_id}/audit_config.json`.
- `EndpointConfigLoader.load(client_id, audit_id)` reads `configs/{client_id}/audits/{audit_id}/endpoints.json`.
- Loaders return parsed dictionaries/models or structured configuration failures.
- Missing, inaccessible, unreadable, or invalid JSON configs fail safely before outbound API requests.
- Loaders must not resolve secrets; they only preserve secret references for the secrets client.

### Config Validator

**Responsibilities:**

- Validate minimal executable schema.
- Validate supported HTTP methods: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS` unless implementation narrows further by documented config schema.
- Validate URLs are present and use `http` or `https`.
- Validate headers are key/value-compatible and do not contain literal secrets where a secret reference is required.
- Validate payload/body is JSON-serializable when configured for JSON request payloads.
- Validate timeout and retry settings against Phase 1 defaults and maxima.
- Validate assertion config is limited to Phase 1 foundational assertions.

### Secrets Client

**Location:** `packages/storage/secrets_client.py`.

**Runtime contract:**

- Resolve secret references only through AWS Secrets Manager.
- Accept only explicit secret reference structures. Recommended shape:

```json
{
  "secret_ref": "arn:aws:secretsmanager:region:account-id:secret:example"
}
```

or a project-standard Secrets Manager name if ARN is not used. Literal secret values must not be accepted in fields declared as secret-bearing.
- Return resolved secret values only to the request preparation path.
- Never return resolved secret values to logging, raw result builder, metadata builder, or errors.
- On missing/inaccessible/invalid secret reference, raise/return structured sanitized failure and prevent outbound request execution for the affected run or endpoint, depending on whether the secret is global or endpoint-scoped.

### Storage Clients

**S3 client location:** `packages/storage/s3_client.py`.

**DynamoDB client location:** `packages/storage/dynamodb_client.py`.

**S3 contract:**

- Read required config objects by exact keys.
- Write sanitized raw results once at run completion to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`, using only validated canonical `client_id`, `audit_id`, and `run_id` values.
- Before writing raw results, check whether the exact target object already exists. If it exists, return/raise controlled `DUPLICATE_RUN_ID` and do not overwrite, append, or merge.
- Refuse to construct or write S3 keys with an externally supplied `run_id` before the Event Validator / Run Identity Service has accepted it as path-safe.
- Do not write unsanitized intermediate artifacts.

**DynamoDB contract:**

- Query/read configuration metadata by `client_id` and `audit_id` access patterns when required.
- Put/update run metadata using required keys built only from validated canonical identifiers.
- Before initial `STARTED` metadata creation for a resolved `run_id`, check whether metadata already exists at `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`. If it exists, return/raise controlled `DUPLICATE_RUN_ID` and do not overwrite, append, or merge.
- Metadata writes should use conditional put/update semantics where available to protect against race conditions between duplicate check and write.
- Refuse to construct `PK`/`SK` values with an externally supplied `run_id` before the Event Validator / Run Identity Service has accepted it as key-safe.
- Store only sanitized metadata.
- Use only Phase 1 statuses: `STARTED`, `COMPLETED`, `FAILED`.

### Runner

**Location:** `apps/backend/runner/`.

**Runtime contract:**

- Input: endpoint execution model with resolved request values and sanitized-safe metadata identifiers.
- Uses `requests` for outbound HTTP execution.
- Supports method, URL, headers, JSON/body payload, timeout, and explicit retry attempts.
- Measures each attempt duration using a monotonic clock from immediately before `requests` call to immediately after response/error.
- Returns a final endpoint outcome containing status code where available, total/selected duration semantics, retry count, final failure classification, assertion details safe for sanitization, and timestamp.
- Must not directly persist raw results or metadata.

### Assertion Evaluator

**Contract:**

- Supports only:
  - expected status codes,
  - response JSON validity when configured/expected,
  - optional required response fields.
- Does not support JSONPath, schema validation, latency assertions, regex assertions, business logic assertions, chained assertions, or advanced policies in Phase 1.

### Sanitizer

**Location:** `packages/sanitization/`.

**Runtime contract:**

- Central reusable function/service invoked before logs, S3 writes, DynamoDB writes, and future report handoff boundaries.
- Replaces sensitive values with `"[REDACTED]"`.
- Traverses dictionaries/lists/scalars safely.
- Redacts by sensitive key names and patterns, including Authorization headers, cookies, API keys, passwords, tokens, secrets, emails, phone numbers, and known sensitive payload fields.
- Handles unexpected data types and nested payloads without throwing where practical; if sanitization fails, fail closed by not emitting/persisting the unsafe payload.

### Logger

**Location:** shared logging utility under `packages/core/` or backend common module.

**Runtime contract:**

- Emit structured JSON logs only after sanitizer processing.
- Each log event includes `log_category` with value `internal_operational_logs` or `client_safe_logs`.
- Include correlation identifiers when known: `client_id`, `audit_id`, validated canonical `run_id`, `endpoint_id`, `scenario_type`, `raw_result_version`.
- Do not log raw externally supplied `run_id` values before validation. Validation failure logs may include a generic reason code such as `INVALID_RUN_ID` but must not echo unsafe input.
- Duplicate `run_id` logs must use reason code `DUPLICATE_RUN_ID`. Because duplicate checks occur only after validation, logs may include the validated canonical `run_id`, but must not include any raw invalid candidate value or unsanitized event payload.
- `internal_operational_logs` may include sanitized implementation context and sanitized error types.
- `client_safe_logs` excludes stack traces, implementation internals, secrets, credentials, PII, and sensitive payload values.

### Schemas / Models

**Location:** `packages/core/models/`, `packages/core/schemas/`, `packages/core/constants/`, `packages/core/exceptions/`.

**Responsibilities:**

- Define constants for approved statuses, failure classifications, raw result version, timeout/retry limits, log categories, and S3/DynamoDB key templates.
- Define validation models for orchestrator event, endpoint config, raw result record, and run metadata.
- Define typed structured exceptions/failures for config, secret, runner, persistence, validation, sanitization, and orchestration/storage control errors.
- Define `DUPLICATE_RUN_ID` as a run-level orchestration/storage control error. It must not be added to the endpoint Raw Result Schema v1 `failure_type` enum.

## 7. Data Models

### Orchestrator Event

#### Purpose

Invocation payload that starts one audit run.

#### Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `client_id` | string | Yes | Client/config scope. Path-safe identifier. |
| `audit_id` | string | Yes | Audit definition id. Path-safe identifier. |
| `scenario_type` | string | Yes | Scenario category to execute. Path-safe identifier. |
| `triggered_by` | string | Yes | Actor/system label initiating run. Path-safe identifier or safe label. No PII/secrets. |
| `run_id` | string | No | Caller-supplied run id. Treated as untrusted external input; must pass sanitization and path/key/log-safety validation before use. Generated when omitted. |

#### Validation Rules

- Required fields must be non-empty strings.
- Identifiers must be safe for S3 paths and DynamoDB keys.
- Supplied `run_id` must exactly match `^[A-Za-z0-9_-]{8,80}$`.
- Supplied `run_id` must reject path separators, backslashes, dots, traversal-like values, URL-encoded traversal-like values, control characters, newlines, carriage returns, tabs, all whitespace, leading/trailing whitespace, unsafe path characters, shell/log/key injection characters, empty values, and any character outside `A-Z`, `a-z`, `0-9`, `_`, and `-`.
- Supplied `run_id` must not be normalized. The accepted value becomes the canonical `run_id` used everywhere; raw external input must not be used in S3 paths, DynamoDB keys, logs, errors, metadata, or responses.
- When `run_id` is absent, generate a canonical UUIDv4 string that satisfies the same regex. When `run_id` is present but invalid, fail validation instead of generating a replacement.
- Invalid events produce structured validation failure and no S3 config load, secret resolution, or outbound API request.

### Client Configuration

#### Purpose

Client-scoped non-secret execution settings and references.

#### Primary Storage Key

S3: `configs/{client_id}/client_config.json`.

#### Minimum Fields

The product spec does not finalize exact config schema fields. Phase 1 implementation should validate only fields it consumes and must reject literal secrets in declared secret-bearing positions.

### Audit Configuration

#### Purpose

Audit-scoped non-secret settings, scenario selection, and defaults.

#### Primary Storage Key

S3: `configs/{client_id}/audits/{audit_id}/audit_config.json`.

#### Minimum Fields

- `audit_id` if present must match event `audit_id`.
- Default timeout/retry values if present must obey Phase 1 limits.
- Assertion defaults, if present, must be limited to foundational assertions.

### Endpoint Configuration

#### Purpose

Defines API endpoints to execute.

#### Primary Storage Key

S3: `configs/{client_id}/audits/{audit_id}/endpoints.json`.

#### Minimum Endpoint Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `endpoint_id` | string | Yes | Path/log-safe endpoint identifier. |
| `method` | string | Yes | Supported HTTP method. |
| `url` | string | Yes | `http` or `https` URL. |
| `headers` | object | No | Header values or secret references. |
| `payload` / `body` | object/string/null | No | Request payload. Must be valid for chosen request mode. |
| `payload_strategy` | string | Yes | Strategy label persisted into raw results. |
| `timeout_seconds` | number | No | Defaults to 10; max 30. |
| `retries` | integer | No | Defaults to 0; max 3. Must be explicit if retrying. |
| `assertions` | object | No | Foundational assertions only. |

### Raw Result Schema v1

#### Purpose

Stable endpoint-level raw execution evidence for downstream phases.

#### Primary Key

Raw result records are stored as array elements in S3 object `raw-results/{client_id}/{audit_id}/{run_id}/results.json`, where `run_id` is the generated or validated canonical value. There is no independent database primary key in Phase 1.

#### Required Fields

| Field | Type | Null-safe Value | Description |
| --- | --- | --- | --- |
| `raw_result_version` | string | Never null | Must be exactly `"v1"`. |
| `client_id` | string | Never null | Client identifier. |
| `audit_id` | string | Never null | Audit identifier. |
| `run_id` | string | Never null | Run identifier. |
| `endpoint_id` | string | Never null for configured endpoint; `"unknown"` only for non-endpoint global failures if represented | Endpoint identifier. |
| `scenario_type` | string | Never null | Scenario type from event/config. |
| `method` | string | Configured method or `null` if unavailable before endpoint parsing | HTTP method. |
| `url` | string | Configured URL or `null` if unavailable before endpoint parsing | Target URL; sanitized if sensitive query params are present. |
| `status_code` | integer/null | `null` when no HTTP response is available | Final HTTP status code. |
| `duration_ms` | integer/null | Present as measured value for attempts reaching request boundary; `null` for pre-request validation failures | Outbound request duration in milliseconds. |
| `failure_type` | string | Never null | One approved failure classification. |
| `payload_strategy` | string | Configured value or `"unknown"` if unavailable | Request payload strategy label. |
| `timestamp` | string | Never null | ISO-8601 UTC timestamp when final outcome record is created. |
| `retry_attempts` | integer | `0` when no retries attempted | Number of retries attempted after initial try. |

#### Optional Phase 1 Fields

Implementation may include sanitized optional fields if useful for tests/debugging, such as `assertion_results`, `error_code`, or `attempts`, but downstream agents must treat only the required fields as the stable Phase 1 contract unless separately approved.

#### Ownership Model

Scoped by `client_id`, `audit_id`, and `run_id` S3 prefix. Phase 1 does not implement authentication or tenant authorization.

#### Lifecycle

Created once at run completion. Existing raw evidence for the same `client_id` + `audit_id` + `run_id` is immutable in Phase 1 and must not be overwritten, appended, or merged. Retention/archive/delete policies are not defined in Phase 1.

#### S3 Object Shape

Recommended persisted JSON shape:

```json
{
  "raw_result_version": "v1",
  "client_id": "example_client",
  "audit_id": "example_audit",
  "run_id": "example_run",
  "results": []
}
```

Each item in `results` must be a Raw Result Schema v1 record with the required fields. The top-level envelope supports future run-level metadata while preserving record schema.

### DynamoDB Run Metadata

#### Purpose

Queryable run state and raw evidence locator.

#### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#RUN#{run_id}`

`client_id`, `audit_id`, and `run_id` must be validated canonical values before key construction. Externally supplied raw `run_id` must never be interpolated directly into DynamoDB keys.

#### Fields

| Field | Type | Description |
| --- | --- | --- |
| `PK` | string | Partition key. |
| `SK` | string | Sort key. |
| `client_id` | string | Client id. |
| `audit_id` | string | Audit id. |
| `run_id` | string | Run id. |
| `scenario_type` | string | Scenario type. |
| `triggered_by` | string | Sanitized trigger source. |
| `status` | string | One of `STARTED`, `COMPLETED`, `FAILED`. |
| `raw_result_s3_key` | string/null | `raw-results/{client_id}/{audit_id}/{run_id}/results.json` when available. |
| `raw_result_version` | string | `"v1"`. |
| `started_at` | string | ISO-8601 UTC timestamp. |
| `completed_at` | string/null | ISO-8601 UTC timestamp when terminal. |
| `failure_summary` | object/null | Sanitized high-level failure code/message for failed runs. |

#### Lifecycle

- Create/put/update `STARTED` after event validation and before endpoint execution.
- Update to `COMPLETED` after successful raw result persistence and metadata write.
- Update to `FAILED` for validation/config/secret/global runner/persistence failures, sanitized.
- If metadata already exists for the same `client_id` + `audit_id` + `run_id` before this invocation creates `STARTED`, fail with `DUPLICATE_RUN_ID` instead of overwriting or merging.

### Configuration Metadata

#### Purpose

Discover client/audit configuration availability without scanning raw results.

#### Access Pattern

Must support identifying records by `client_id` and `audit_id`. Exact item shapes may follow Phase 0 table conventions, but implementation must not require scanning S3 raw result objects to discover configuration metadata.

## 8. API Contracts

Phase 1 has no public HTTP API. The runtime contract is a Lambda event contract.

## Endpoint: Lambda Invocation Event

### Purpose

Start one backend audit run for a configured client/audit/scenario.

### Authentication / Authorization

No user authentication or RBAC is implemented in Phase 1. Invocation permissions are controlled by AWS IAM/deployment configuration only. Tenant authorization is out of scope.

### Request Parameters

None. Event body contains all inputs.

### Request Body

```json
{
  "client_id": "example_client",
  "audit_id": "example_audit",
  "scenario_type": "release_smoke",
  "triggered_by": "manual_operator",
  "run_id": "optional-safe-run-id"
}
```

### Response Body

Recommended sanitized success shape:

```json
{
  "client_id": "example_client",
  "audit_id": "example_audit",
  "run_id": "generated-or-supplied-run-id",
  "status": "COMPLETED",
  "raw_result_s3_key": "raw-results/example_client/example_audit/generated-or-supplied-run-id/results.json"
}
```

Recommended sanitized failure shape:

```json
{
  "client_id": "example_client",
  "audit_id": "example_audit",
  "run_id": "generated-or-supplied-run-id",
  "status": "FAILED",
  "failure_summary": {
    "error_type": "CONFIG_VALIDATION_ERROR",
    "message": "Configuration validation failed"
  }
}
```

### Success Status Codes

Not applicable as a public HTTP endpoint. If fronted by Lambda/API Gateway in a future phase, status code mapping must be designed separately.

### Error Status Codes

Not applicable as a public HTTP endpoint. Lambda failures should be structured return values where possible and sanitized exceptions otherwise.

### Validation Rules

- `client_id`, `audit_id`, `scenario_type`, and `triggered_by` are required non-empty strings.
- Optional `run_id` must exactly match `^[A-Za-z0-9_-]{8,80}$` before any use. Invalid supplied values are rejected without normalization; a generated UUIDv4 `run_id` is created only when `run_id` is absent.
- Raw externally supplied `run_id` must not be echoed in validation errors or logs; use sanitized reason codes instead.
- Invalid event: no config loading, secret resolution, or outbound request execution.

### Side Effects

- May write `STARTED`/terminal run metadata to DynamoDB after event validation.
- May read S3 config, read Secrets Manager secrets, execute HTTP requests, write S3 raw results, and update DynamoDB metadata.

### Idempotency / Duplicate Handling

Phase 1 does not provide idempotent replay semantics. A caller-supplied `run_id` is accepted for traceability only after exact validation. Duplicate supplied `run_id` behavior is fail-fast:

1. Build the raw result key and metadata key only from validated canonical identifiers.
2. Before writing `STARTED` metadata or executing endpoints, check whether either of the following already exists for the same `client_id` + `audit_id` + `run_id`:
   - S3 object `raw-results/{client_id}/{audit_id}/{run_id}/results.json`
   - DynamoDB item `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`
3. If either exists, fail with controlled orchestration/storage error `DUPLICATE_RUN_ID`.
4. Do not overwrite, append, merge, or treat the request as idempotent success.
5. Before final raw evidence write, perform a final duplicate guard against the S3 target object where possible, and ensure DynamoDB terminal updates are conditional on the run item created by this invocation. Use DynamoDB conditional writes and S3 non-overwrite checks/conditional behavior where available to reduce race risk.

`DUPLICATE_RUN_ID` is not an endpoint `failure_type`; it is a run-level orchestration/storage control error because endpoint execution must not begin for duplicate immutable evidence identity.

## 9. Frontend Impact

### Components Affected

None. `apps/frontend/README.md` remains a placeholder only.

### API Integration

None in Phase 1.

### UI States

None in Phase 1.

## 10. Backend Logic

### Responsibilities

- Validate event and identifiers.
- Generate `run_id` or accept only a sanitized and validated canonical externally supplied `run_id`.
- Load and validate S3 configs.
- Resolve secrets only through Secrets Manager.
- Execute endpoint requests with deterministic timeout/retry/timing behavior.
- Evaluate foundational assertions.
- Classify endpoint outcomes.
- Build Raw Result Schema v1 records.
- Sanitize all logs, raw results, and metadata.
- Persist raw evidence to S3 and metadata to DynamoDB.

### Validation Flow

1. Validate Lambda event required fields.
2. Validate/generate `run_id`:
   - supplied value must exactly match `^[A-Za-z0-9_-]{8,80}$`,
   - invalid supplied value is rejected without normalization and without raw-value logging,
   - absent value generates a UUIDv4 canonical string satisfying the same regex.
3. Build S3 raw result key and DynamoDB metadata key from validated identifiers only.
4. Check for duplicate raw result object and metadata item for the resolved `client_id` + `audit_id` + `run_id`; if either exists, fail with `DUPLICATE_RUN_ID` before config loading, metadata creation, secret resolution, endpoint execution, or raw evidence writes.
5. Build S3 config keys from validated identifiers only.
6. Load config JSON.
7. Validate config schema and endpoint settings.
8. Validate secrets are references only in secret-bearing config fields.
9. Validate retry/timeout limits:
   - missing timeout => `10` seconds,
   - max timeout => `30` seconds,
   - missing retries => `0`,
   - max retries => `3`,
   - retry count must be integer >= 0.
10. Resolve required secrets.
11. Execute endpoints.

### Business Rules

- The orchestrator must contain no client-specific logic.
- Required config load/parse failures prevent all outbound requests.
- Payload validation failure for an endpoint produces `PAYLOAD_VALIDATION_ERROR` and no outbound request for that endpoint.
- One endpoint failure should not prevent execution of remaining valid endpoints unless a global dependency failure or safety issue occurs.
- Retries are attempted only when explicitly configured above zero and within max limit.
- Retry attempts must be recorded in the final raw result as the number of retries attempted after the initial attempt.
- Raw result version must always be `"v1"`.
- All persisted/logged data must pass through sanitizer.
- Raw externally supplied `run_id` must never be interpolated into S3 paths, DynamoDB keys, structured log fields, error messages, or metadata. Only the generated or validated canonical `run_id` may be used.
- Duplicate `run_id` for the same `client_id` + `audit_id` weakens traceability for immutable evidence and must fail fast with `DUPLICATE_RUN_ID`; implementation must not overwrite, append, merge, or silently continue.

### Persistence Flow

1. After valid event and resolved canonical `run_id`, check duplicate state before any metadata write:
   - S3 `HeadObject`/equivalent for `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
   - DynamoDB `GetItem`/equivalent for `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
   - If either exists, raise/return `DUPLICATE_RUN_ID` and stop.
2. Write sanitized metadata `STARTED` with conditional create semantics so an existing item fails rather than overwrites.
3. Buffer sanitized-or-to-be-sanitized endpoint result records internally during execution.
4. Before final raw evidence write, re-check or use conditional/non-overwrite write behavior for the exact S3 target object. If the object already exists, fail with `DUPLICATE_RUN_ID`; do not overwrite.
5. Sanitize final raw result envelope and write to S3:
   `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
6. Write/update sanitized metadata to `COMPLETED` including `raw_result_s3_key` when S3 write succeeds, using the existing run item created by this invocation only.
7. On failure before raw result persistence, write/update sanitized metadata to `FAILED` where possible, only for the item created by this invocation.
8. On S3 persistence failure after endpoint execution, write sanitized metadata `FAILED` with no raw result key or with a null/unavailable marker.
9. On DynamoDB terminal metadata failure after S3 success, return/log sanitized persistence failure; raw result S3 object remains the source of execution evidence.

### Error Handling

- Use structured internal exception/failure types.
- Sanitize all error messages before logging or persistence.
- For `run_id` validation failures, return/log sanitized validation failure information without echoing the raw rejected value.
- For duplicate identity failures, return/log sanitized `DUPLICATE_RUN_ID` information. Logs may include validated canonical `client_id`, `audit_id`, and `run_id`; they must not include any unsafe raw rejected value.
- Preserve exact endpoint `failure_type` from approved list.
- Global orchestrator/config/secret/persistence/control errors, including `DUPLICATE_RUN_ID`, may use internal error types in `failure_summary`, but endpoint raw results may only use approved `failure_type` values.

### Failure Classification Contract

Each endpoint final outcome maps to exactly one of:

| Classification | Conditions |
| --- | --- |
| `PASS` | Request completed and all configured foundational assertions passed. |
| `ASSERTION_FAILURE` | Response received but expected status code or required response field assertion failed, where not classified as HTTP error by configured expectations. |
| `HTTP_ERROR` | Response status is classified as an HTTP error by configured expectations, unless a more specific assertion failure applies. |
| `TIMEOUT` | `requests` timeout occurred. `duration_ms` must be present from monotonic measurement. |
| `CONNECTION_ERROR` | DNS, TLS, connection refused, network connectivity, or `requests` connection exception. |
| `INVALID_RESPONSE` | Response cannot be parsed/interpreted according to configured JSON validity expectations. |
| `RUNNER_ERROR` | Unexpected runner exception not covered by another classification. |
| `PAYLOAD_VALIDATION_ERROR` | Configured request payload is invalid before outbound execution; no request sent. |

Precedence guidance:

1. Pre-request payload validation => `PAYLOAD_VALIDATION_ERROR`.
2. Timeout exception => `TIMEOUT`.
3. Connection exception => `CONNECTION_ERROR`.
4. Unexpected runner exception => `RUNNER_ERROR`.
5. Invalid/malformed response for configured JSON expectation => `INVALID_RESPONSE`.
6. HTTP status/error expectation mismatch => `HTTP_ERROR` or `ASSERTION_FAILURE` per config; if both apply, product acceptance says HTTP error unless a more specific configured assertion failure applies.
7. All assertions pass => `PASS`.

### Runner Timing Rules

- Use `time.monotonic()` or equivalent monotonic source.
- Start timer immediately before each `requests` outbound call.
- Stop timer immediately after response is returned or request exception is caught.
- Do not include Lambda cold start, orchestration, config loading, secret resolution, S3, DynamoDB, or logging time.
- For retried requests, record the final endpoint `duration_ms` as the final attempt duration unless the optional `attempts` field records per-attempt durations. This keeps required schema simple; retry count records total retries attempted.

### Retry / Timeout Rules

- `default_timeout_seconds = 10`.
- `max_timeout_seconds = 30`.
- `default_retries = 0`.
- `max_retries = 3`.
- Omitted retry config means no retries.
- Retry config above max fails config validation before endpoint execution.
- Timeout above max fails config validation before endpoint execution.
- Retried outcomes must not obscure final classification; the final raw result classification represents the final attempt/outcome.

### Foundational Assertion Behavior

- Expected status code assertions may be a single integer or approved list/range representation defined by config validator.
- JSON validity assertion requires response body to parse as JSON when configured/expected.
- Required response fields assertion checks top-level field presence unless implementation explicitly documents safe dotted-path support; advanced JSONPath is out of scope.
- No latency, schema, regex, semantic, chained, AI, or business logic assertions in Phase 1.

### Sanitization Pipeline

Sanitization must occur at these boundaries:

1. Before every log emission.
2. Before S3 raw result write.
3. Before DynamoDB metadata write.
4. Before returning a structured Lambda response.
5. Before any future report handoff interface, if a placeholder exists.

Redaction behavior:

- Replace sensitive values with `"[REDACTED]"`.
- Redact whole values for keys matching sensitive names such as `authorization`, `cookie`, `set-cookie`, `api_key`, `apikey`, `x-api-key`, `password`, `passwd`, `secret`, `token`, `access_token`, `refresh_token`, `id_token`, `client_secret`, `email`, `phone`.
- Redact detected emails and phone numbers in strings.
- Redact sensitive query parameter values in URLs.
- Never log or persist resolved secret values, even in internal logs.

Run identity safety behavior:

- Identifier validation is separate from redaction and must occur before the sanitizer/logging/persistence pipeline consumes externally supplied `run_id`.
- The sanitizer must not be relied on to make an unsafe `run_id` safe for S3 paths or DynamoDB keys; unsafe externally supplied `run_id` values are rejected by the Event Validator / Run Identity Service and are never normalized into accepted values.
- Structured logs may include only the generated or validated canonical `run_id`, never the raw external value.

## 11. File Structure

Expected implementation locations, aligned with Phase 0 structure:

```text
apps/backend/handlers/
  # Lambda handler entrypoint for Phase 1 orchestrator
apps/backend/orchestrator/
  # orchestration service, event validation delegation, run lifecycle coordination
apps/backend/runner/
  # requests-based HTTP runner and assertion evaluation
packages/core/constants/
  # raw_result_version, statuses, failure types, retry/timeout limits, log categories
packages/core/models/
  # event, endpoint, raw result, metadata models
packages/core/schemas/
  # schema validation helpers/contracts
packages/core/exceptions/
  # structured exceptions/failure summaries
packages/config/client_config/
packages/config/audit_config/
packages/config/endpoint_config/
  # S3 config loading and validation boundaries
packages/sanitization/
  # sanitizer and redaction rules
packages/storage/
  # s3_client.py, dynamodb_client.py, secrets_client.py wrappers
tests/unit/
  # isolated unit tests with mocked dependencies
tests/integration/
  # local-only integration tests, no live AWS requirement
tests/mock_api/
  # local mock API used by runner tests
docs/architecture/phase_1_core_engine_foundation_technical_design.md
```

Infrastructure should continue using Phase 0 resource naming conventions unless already configured differently:

- Raw results bucket: `release-confidence-platform-${stage}-raw-results`.
- Metadata table: `release-confidence-platform-${stage}-metadata`.

Runtime environment variables should include non-secret configuration such as:

- `STAGE`
- `AWS_REGION`
- `RAW_RESULTS_BUCKET`
- `CONFIG_BUCKET` if distinct from raw results bucket
- `METADATA_TABLE`
- `LOG_LEVEL`

## 12. Security

### Authentication

No application-level authentication is implemented in Phase 1. Lambda invocation control relies on AWS IAM/deployment configuration.

### Authorization

No RBAC or tenant/user authorization model is implemented in Phase 1. All data access must be scoped by validated `client_id`, `audit_id`, and `run_id` to prevent accidental cross-prefix writes, but this is not a user permission system.

### Input Validation

- Strictly validate event identifiers before deriving S3 or DynamoDB keys.
- Validate externally supplied `run_id` with exact regex `^[A-Za-z0-9_-]{8,80}$` before deriving S3 keys, DynamoDB keys, metadata fields, responses, or logs.
- Reject unsafe path characters, slashes, backslashes, dots, traversal-like values, URL-encoded traversal-like values, whitespace, control characters, line breaks, delimiters outside the approved identifier set, and shell/log/key injection patterns in `run_id`.
- Do not normalize unsafe supplied `run_id`; reject it and do not generate a replacement unless `run_id` was absent.
- Use only a generated or validated canonical `run_id`; never log or persist raw rejected values.
- Validate endpoint URLs and supported schemes.
- Validate timeout/retry bounds.
- Validate payload serializability before outbound execution.

### Secrets and Sensitive Data

- Secrets resolved only from AWS Secrets Manager.
- Configs contain secret references only, never literal secret values in secret-bearing fields.
- Resolved secrets live only in request preparation/execution memory and are never included in raw result, metadata, or logs.
- Sanitizer redacts sensitive values as `"[REDACTED]"`.
- Sample/test fixtures must not contain real secrets or real PII.

### Misuse Risks

- A caller could attempt path traversal, DynamoDB key manipulation, ambiguous identifier usage, or log injection via supplied `run_id`; validation must reject it before path/key/log generation and must avoid echoing rejected raw values.
- A caller could intentionally reuse a valid `run_id`; duplicate detection must fail with `DUPLICATE_RUN_ID` before raw evidence or metadata is overwritten, appended, or merged.
- Misconfigured logs could expose secrets; logging wrapper must require sanitizer and log category.
- Configs may accidentally contain literal secrets; validator should reject fields marked/known as secret-bearing unless they use secret reference structures.
- Client-safe logs could leak internals; enforce a stricter log schema for `client_safe_logs`.

## 13. Reliability

### Failure Modes

- Invalid event: structured validation failure, no execution side effects beyond sanitized log.
- Invalid supplied `run_id`: structured validation failure, no generated replacement, no config loading, no metadata write, no raw evidence write, no outbound execution, and no raw rejected value in logs/errors.
- Duplicate valid `run_id`: controlled `DUPLICATE_RUN_ID` run-level orchestration/storage error before endpoint execution; no overwrite, append, or merge of raw evidence or metadata.
- Missing/unreadable/invalid config: metadata `FAILED` if run id exists and event valid; no outbound requests.
- Secret resolution failure: sanitized failure; no secret value emitted.
- Endpoint timeout/connection/error: endpoint raw result classification and continued execution of remaining endpoints where safe.
- S3 raw result write failure: run metadata `FAILED` where possible.
- DynamoDB metadata write failure: sanitized operational error; if raw results were written, preserve S3 evidence and return/log failure.

### Retries

- Endpoint HTTP retries are controlled by endpoint config and capped at 3.
- Phase 1 does not require retries for S3, DynamoDB, or Secrets Manager beyond SDK defaults. Additional retry policy must not obscure failures or emit secrets.

### Timeouts

- Runner HTTP timeout defaults to 10 seconds and caps at 30 seconds.
- AWS SDK client timeouts may use default SDK behavior unless project infrastructure requires explicit configuration later.

### Logging / Monitoring

- All logs structured and sanitized.
- Every run-level log includes `client_id`, `audit_id`, and validated canonical `run_id` when available.
- Logs must never include raw externally supplied `run_id` before validation or after rejection; validation failures should use reason codes instead of unsafe values.
- Invalid `run_id` logs should include `error_type = INVALID_RUN_ID` and safe reason categories such as `regex_mismatch`, `length_out_of_range`, or `invalid_character`, but not the rejected value.
- Duplicate `run_id` logs should include `error_type = DUPLICATE_RUN_ID` and may include the validated canonical `run_id` plus whether the duplicate was detected in `s3_raw_result_object`, `dynamodb_metadata_item`, or both.
- Endpoint logs include `endpoint_id` when available.
- Log categories must be explicit:
  - `internal_operational_logs`
  - `client_safe_logs`
- Advanced observability, dashboards, metrics aggregation, and distributed tracing are out of scope.

### Performance Considerations

- Phase 1 favors correctness and deterministic evidence over throughput.
- Endpoint execution may be sequential for simplicity and determinism.
- Avoid parallel execution unless explicitly implemented with deterministic result ordering and unchanged failure semantics.
- Keep dependencies lightweight; no heavy API frameworks.

## 14. Dependencies

- Phase 0 project foundation.
- AWS Lambda runtime for orchestrator.
- Amazon S3 for configs and raw results.
- Amazon DynamoDB for metadata.
- AWS Secrets Manager for runtime secrets.
- IAM permissions for required S3/DynamoDB/Secrets Manager operations.
- Python 3.11.
- `requests` for HTTP execution.
- `boto3` for AWS clients.
- `pytest` and mocks/fakes for local validation.
- Local mock API under `tests/mock_api` for runner tests.

## 15. Assumptions

### Confirmed Assumptions / Decisions

- Phase 1 is the only implementation scope for branch `feature/phase_1_core_engine_foundation`.
- `run_id` may be supplied by the trigger event only when it exactly matches `^[A-Za-z0-9_-]{8,80}$`; otherwise the orchestrator rejects it.
- Generated `run_id` is created only when absent and uses canonical UUIDv4 format, which satisfies the same regex.
- Externally supplied invalid `run_id` values must not be normalized, replaced, or logged raw.
- Duplicate supplied `run_id` for the same `client_id` + `audit_id` fails fast with `DUPLICATE_RUN_ID`; raw evidence is immutable and must not be overwritten, appended, or merged.
- `DUPLICATE_RUN_ID` is a run-level orchestration/storage control error, distinct from endpoint `failure_type` classifications.
- `raw_result_version` is the string `"v1"`.
- Phase 1 writes raw results once at run completion to one `results.json` object.
- The design preserves a future incremental persistence boundary without schema change.
- Assertions are limited to expected status codes, response JSON validity, and optional required response fields.
- Retry/timeout defaults and maxima are: 10s default timeout, 30s max timeout, 0 default retries, 3 max retries.
- Retries must be explicit and recorded in raw results.
- Sanitization replaces sensitive values with `"[REDACTED]"`.
- Phase 1 metadata statuses are only `STARTED`, `COMPLETED`, and `FAILED`.

### Technical Assumptions Requiring Confirmation

- Whether the config bucket is the same physical bucket as the raw results bucket or a separate `CONFIG_BUCKET` resource. The design supports either through environment configuration while keeping required key paths unchanged.
- Exact configuration metadata item shape beyond queryability by `client_id` and `audit_id` remains unspecified.
- Exact endpoint config JSON schema beyond minimum executable fields remains unspecified and should be documented by the backend agent when implemented.

## 16. Risks / Open Questions

### Risks

- **Secret leakage through overlooked fields:** Mitigate by central sanitizer, secret-reference validation, and tests covering nested headers/payloads/URLs/logs.
- **Ambiguous config schema:** Product spec defines paths but not complete JSON schema. Backend implementation must keep schema minimal and document consumed fields.
- **Persistence partial failure:** S3 success followed by DynamoDB failure may leave raw evidence without discoverable metadata. Log sanitized operational failure and add tests for this path.
- **Duplicate `run_id` race condition:** Caller-supplied run ids can collide, and concurrent invocations could pass a pre-write existence check. Mitigate with fail-fast duplicate checks plus conditional DynamoDB writes and non-overwrite/conditional S3 write behavior where available.
- **Unsafe `run_id` handling gaps:** If any code path logs or interpolates raw external `run_id` before validation, S3 path traversal, DynamoDB key ambiguity, or log injection could occur. Mitigate with a single run identity service, tests for rejected inputs, and code review focused on pre-validation logging/key construction.
- **Duration ambiguity with retries:** Required schema has one `duration_ms`. This design records final attempt duration; optional attempt records can preserve per-attempt detail without changing required schema.
- **Endpoint failure vs run failure semantics:** Product requires endpoint classifications but does not fully define aggregate run status. This design permits endpoint failures while completing the run if persistence succeeds; run status may still be `COMPLETED` with failed endpoint records unless a global failure occurs.

### Open Questions

- Should config and raw results use one S3 bucket or separate buckets in deployed environments?
- What exact config metadata records should exist before a run, and should orchestrator require them or only use S3 object existence?
- Should a run with one or more endpoint `failure_type` values other than `PASS` be marked metadata `COMPLETED` or `FAILED`? Recommended: `COMPLETED` means execution completed and raw evidence persisted; endpoint failures are represented in raw results.
- Should Raw Result Schema v1 include optional per-attempt records in Phase 1, or only final endpoint outcome? Required fields support final outcome only.

## 17. Implementation Notes

Guidance for the backend implementation agent:

1. Implement only Phase 1 core engine foundation behavior described here.
2. Keep the Lambda handler thin; place orchestration logic in `apps/backend/orchestrator`.
3. Put reusable constants/models/schemas/exceptions under `packages/core`.
4. Use `requests` directly in the runner; do not introduce a heavy API framework.
5. Use validated identifiers only to build S3 keys and DynamoDB keys.
   - For externally supplied `run_id`, enforce exact regex `^[A-Za-z0-9_-]{8,80}$` before any S3 path, DynamoDB key, metadata, response, or log use.
   - Reject invalid supplied `run_id` values without normalization and without generating a replacement.
   - Generate canonical UUIDv4 `run_id` only when absent.
6. Implement `raw_result_version` as exact string `"v1"` everywhere.
7. Keep raw evidence persistence as one final `results.json` write, but route endpoint records through an evidence sink/buffer abstraction.
8. Enforce timeout/retry bounds before execution.
9. Use monotonic clocks only for `duration_ms` measurement.
10. Ensure `retry_attempts` records retries attempted, not total attempts.
11. Ensure payload validation failures do not send outbound requests.
12. Keep assertion evaluator limited to expected status code, JSON validity, and required response fields.
13. Route every log and persistence payload through sanitizer.
14. Redact with `"[REDACTED]"` and add tests for authorization headers, cookies, API keys, passwords, emails, phone numbers, nested payloads, and sensitive query params.
15. Implement mockable AWS clients; unit tests must not require live AWS credentials.
16. Add local mock API tests for success, HTTP error, timeout, connection error where practical, invalid JSON, assertion failure, payload validation failure, and retry recording.
17. Validate S3 path generation exactly, using only the canonical validated/generated `run_id`:
    `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
18. Validate DynamoDB key generation exactly, using only the canonical validated/generated `run_id`:
    `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
19. Add validation tests for externally supplied `run_id`:
    - invalid cases: empty value, non-string value, fewer than 8 characters, more than 80 characters, slash, backslash, dot, `.`, `..`, `../`, `..\\`, `%2e%2e`, `%2f`, `%5c`, whitespace, tab, newline, carriage return, control characters, leading/trailing whitespace, shell/log/key injection characters, and any character outside `A-Z`, `a-z`, `0-9`, `_`, `-`;
    - assert invalid supplied values return/log sanitized `INVALID_RUN_ID` without the raw rejected value;
    - assert invalid supplied values do not cause generated replacement ids, config loads, metadata writes, raw evidence writes, secret resolution, or outbound requests.
20. Keep `client_safe_logs` free of stack traces, implementation internals, secrets, credentials, PII, and raw rejected identifiers.
21. Add run identity success tests:
    - absent `run_id` generates a UUIDv4 value satisfying `^[A-Za-z0-9_-]{8,80}$` and uses it consistently in response, metadata keys, S3 key, raw result envelope, and logs;
    - valid supplied `run_id` examples such as `release_2026-01` or `RUN-12345678` are accepted unchanged and used consistently.
22. Add duplicate `run_id` tests:
    - existing S3 raw result object causes `DUPLICATE_RUN_ID` before metadata creation, config loading, endpoint execution, or raw evidence write;
    - existing DynamoDB metadata item causes `DUPLICATE_RUN_ID` before overwrite/update, config loading, endpoint execution, or raw evidence write;
    - both existing object and metadata item still produce one controlled `DUPLICATE_RUN_ID` response/log;
    - duplicate behavior does not append, merge, overwrite, or classify an endpoint result `failure_type`.
23. Do not add frontend, auth, scoring, reporting, AI, load testing, uptime monitoring, chaos engineering, scheduled monitoring, or Phase 2/3 behavior in this branch.
