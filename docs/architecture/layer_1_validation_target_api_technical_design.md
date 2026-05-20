# Technical Design

## 1. Feature Overview

Layer 1 Validation Target API is a backend-only internal operational fixture that exposes five controlled HTTP health endpoints for validating release-confidence-platform audit behavior against known ground truth. The fixture is not customer-facing and intentionally avoids auth, persistence, frontend, analytics, AI, dashboards, tracing, and heavy frameworks.

The implementation must use API Gateway HTTP API routes backed by AWS Lambda functions, deployed via Serverless Framework with Python 3.11, under `apps/mock-target-api/`.

Source product specification: `docs/product/layer_1_validation_target_api.md`.

## 2. Product Requirements Summary

- Provide independent `GET` endpoints for `/health/fast`, `/health/slow`, `/health/flaky`, `/health/inconsistent`, and `/health/timeout`.
- Keep all completed responses valid JSON and include `service: mock-target-api` and endpoint identifiers.
- Use deterministic behavior only; do not use Python built-in `hash()` or uncontrolled randomness.
- Support explicit seed-based reproducibility for flaky and inconsistent behavior.
- Support deterministic slow delays and timeout behavior without forcing CI to wait for full production-like timeout duration.
- Deploy to distinct `dev`, `staging`, and `prod` stages through Serverless Framework.
- Provide local invocation, curl testing, pytest unit/integration tests, README, and behavior documentation.

## 3. Requirement-to-Architecture Mapping

| Product Requirement / Acceptance Criteria | Technical Design Response |
| --- | --- |
| FR-1 | Create the required `apps/mock-target-api/` structure with handlers, services, utils, tests, sample events, docs, Serverless config, and README. |
| FR-2, AC-1, AC-2 | `handlers/health_fast.py` returns a static 200 JSON response through `response_service`; no delay utility is called. |
| FR-3, AC-3 through AC-5 | `handlers/health_slow.py` uses `deterministic_delay.resolve_slow_delay_ms()` and sleeps for explicit valid delay, seed-derived delay, or 1000 ms default. |
| FR-4, AC-6 through AC-9 | `handlers/health_flaky.py` uses query seed, then `X-RCP-Seed`, then deterministic time-window fallback; `flaky_service` maps SHA-256-derived hash modulo 5 to 500 or 200. |
| FR-5, AC-10 through AC-12 | `handlers/health_inconsistent.py` uses forced `variant=A|B`, then seed-derived SHA-256 modulo 2, then deterministic time-window fallback. Variants intentionally use different schemas. |
| FR-6, AC-13 through AC-15 | `handlers/health_timeout.py` delegates delay selection to `timeout_service`; default is 35-45 seconds, `MOCK_TARGET_SHORT_TIMEOUT=true` uses 2-3 seconds. Unit tests validate configuration/short mode instead of sleeping full duration. |
| FR-7 | Shared response helpers enforce JSON serialization, headers, service/endpoint fields, and structured safe logging. |
| FR-8, AC-16 | `serverless.yml` defines one HTTP API and five Lambda functions using Python 3.11 with stage-based provider settings. |
| FR-9, AC-17 | Add `README.md` and `docs/validation-behavior.md` describing purpose, behavior, deployment, curl, local, and pytest usage. |
| FR-10 | Add pytest unit tests for services/handlers and optional integration tests for local/deployed HTTP invocation. |
| Constraints / Out of Scope | No frontend, Cognito, databases, S3, dashboards, billing, AI, analytics, tracing, or heavy web framework components are introduced. |

## 4. Technical Scope

### Current Technical Scope

- A standalone Serverless Framework app under `apps/mock-target-api/`.
- Five Lambda handlers, each independently addressable through API Gateway HTTP API.
- Lightweight Python services and utilities for deterministic responses, hashing, delay selection, timeout behavior, and response construction.
- Structured JSON logs without secrets or excessive payload logging.
- Pytest unit and integration test scaffolding.
- Sample HTTP API event fixtures for local invocation.
- Internal documentation for expected validation behavior.

### Out of Scope

- Customer-facing workflows, frontend UI, dashboarding, billing, analytics, AI, or reporting.
- Authentication/authorization, Cognito, RBAC, user management, or tenant management.
- Databases, DynamoDB, relational storage, S3, queues, event buses, or persistent state.
- Distributed tracing and full observability stacks beyond structured logs.
- Any non-GET API behavior.

### Future Technical Considerations

- Additional fixture endpoints for advanced validation phases.
- More inconsistent response variants beyond A/B.
- Optional environment-specific fixture behavior matrices if future audit phases require them.

## 5. Architecture Overview

### Runtime Flow

```text
HTTP client / audit runner / curl
        |
        v
API Gateway HTTP API
        |
        v
Route-specific Lambda handler
        |
        v
Small endpoint service/utilities
        |
        v
JSON Lambda proxy response
```

Each endpoint is implemented as an independent Lambda function to preserve route-level isolation and make endpoint invocation independently testable. Shared code is limited to deterministic behavior and response utilities.

### Stable Hash Recommendation

All seed-based behavior must use a deterministic cryptographic digest, not Python's built-in `hash()` because built-in hash randomization differs across Python processes.

Recommended helper contract:

- Function: `stable_hash(value: str) -> int`
- Algorithm: `hashlib.sha256(value.encode("utf-8")).hexdigest()` converted to an integer with base 16.
- Empty seed handling: `""` is a valid deterministic input and must hash successfully.
- Modulo use:
  - slow delay: `800 + (stable_hash(seed) % 701)`
  - flaky failure: `stable_hash(seed) % 5 == 0`
  - inconsistent variant: `stable_hash(seed) % 2`

This satisfies product references to `hash(seed)` while making the implementation stable across local, CI, and AWS Lambda environments.

## 6. System Components

### `handlers/health_fast.py`

Responsibilities:
- Accept API Gateway HTTP API event and Lambda context.
- Return HTTP 200 immediately with deterministic body.
- Do not call sleep/delay utilities.

Interface:
- Entrypoint: `handler(event, context)`.
- Calls `response_service.build_fast_response()` and `response_helpers.json_response()`.

### `handlers/health_slow.py`

Responsibilities:
- Parse `queryStringParameters.delay_ms` and `queryStringParameters.seed`.
- Resolve delay using explicit valid delay, seed-derived delay, or 1000 ms default.
- Sleep for resolved delay and return HTTP 200.

Interface:
- Entrypoint: `handler(event, context)`.
- Calls `deterministic_delay.resolve_slow_delay_ms()` and `response_service.build_slow_response(delay_ms, delay_source)`.

### `handlers/health_flaky.py`

Responsibilities:
- Select seed using query parameter first, `X-RCP-Seed` header second, deterministic time-window fallback third.
- Return deterministic 500 degraded or 200 healthy.

Interface:
- Entrypoint: `handler(event, context)`.
- Calls `flaky_service.resolve_seed()` and `flaky_service.evaluate_flaky_status(seed)`.

### `handlers/health_inconsistent.py`

Responsibilities:
- Select response variant using valid `variant=A|B`, then seed-derived hash, then deterministic time-window fallback.
- Always return HTTP 200.
- Variant A and B must intentionally differ in schema.

Interface:
- Entrypoint: `handler(event, context)`.
- Calls `inconsistency_service.resolve_variant()` and `response_service.build_inconsistent_response(variant, selection_source)`.

### `handlers/health_timeout.py`

Responsibilities:
- Resolve timeout delay based on `MOCK_TARGET_SHORT_TIMEOUT`.
- Sleep for a deterministic default 35-45 seconds or short 2-3 seconds.
- Return valid JSON if the Lambda completes before client/API timeout.

Interface:
- Entrypoint: `handler(event, context)`.
- Calls `timeout_service.resolve_timeout_delay_seconds()` and `response_service.build_timeout_response(delay_seconds, mode)`.

### `services/response_service.py`

Responsibilities:
- Own endpoint response body schemas.
- Ensure all completed responses include `service` and `endpoint`.
- Provide deterministic fields only.

Suggested response body fields:
- Required: `service`, `endpoint`, endpoint-specific `status` or variant fields.
- Optional deterministic diagnostic fields: `delay_ms`, `delay_source`, `seed_source`, `variant_source`, `timeout_mode`.
- Do not include wall-clock timestamps in stable endpoint bodies unless explicitly labeled as non-deterministic diagnostics. Prefer excluding timestamps to keep responses deterministic.

### `services/flaky_service.py`

Responsibilities:
- Normalize query/header seed precedence.
- Implement deterministic time-window fallback for manual exploration.
- Compute stable hash modulo 5.
- Return decision object: `seed`, `seed_source`, `hash_mod`, `http_status`, `status`.

### `services/inconsistency_service.py`

Responsibilities:
- Validate forced variant values.
- Fall back to seed-derived variant when forced variant is absent or invalid and seed exists.
- Use deterministic time-window fallback only when both valid variant and seed are absent.
- Return decision object: `variant`, `variant_source`, optional `seed`.

### `services/timeout_service.py`

Responsibilities:
- Read `MOCK_TARGET_SHORT_TIMEOUT`.
- Resolve deterministic delay ranges:
  - default mode: 35-45 seconds
  - short mode: 2-3 seconds
- Provide testable pure functions so unit tests can assert ranges without full sleep.

### `utils/deterministic_delay.py`

Responsibilities:
- Provide `stable_hash(value)` using SHA-256.
- Validate and resolve slow endpoint delay.
- Provide deterministic time-window fallback seed helpers for manual exploration.
- Encapsulate sleeping behind a small wrapper to allow monkeypatching in tests.

### `utils/response_helpers.py`

Responsibilities:
- Build Lambda proxy responses with status code, JSON body, and headers.
- Recommended headers:
  - `Content-Type: application/json`
  - `Cache-Control: no-store`
- Normalize HTTP API v2 event access for headers and query parameters.
- Emit structured logs through Python standard `logging` with JSON-like dictionaries.

## 7. Data Models

No persistence is in scope. The fixture has no databases, S3 objects, user records, or durable state.

### Response Body Schemas

#### Fast Response

Purpose: stable healthy baseline.

Fields:
- `service: "mock-target-api"`
- `endpoint: "fast"`
- `status: "healthy"`

#### Slow Response

Purpose: stable successful response with controlled latency.

Fields:
- `service: "mock-target-api"`
- `endpoint: "slow"`
- `status: "healthy"`
- `delay_ms: integer`
- `delay_source: "query" | "seed" | "default"`

#### Flaky Response

Purpose: deterministic intermittent success/failure.

Fields:
- `service: "mock-target-api"`
- `endpoint: "flaky"`
- `status: "healthy" | "degraded"`
- `seed_source: "query" | "header" | "time_window"`
- `hash_mod: integer` in `0..4`

Do not echo seed values to logs. Echoing seed in response is not required; if implemented, keep in mind seeds could be supplied by clients and should be treated as diagnostic input.

#### Inconsistent Variant A Response

Purpose: first deterministic schema variant.

Fields:
- `service: "mock-target-api"`
- `endpoint: "inconsistent"`
- `version: "A"`
- `status: "healthy"`

#### Inconsistent Variant B Response

Purpose: second deterministic schema variant with intentionally different shape.

Fields:
- `service: "mock-target-api"`
- `endpoint: "inconsistent"`
- `status: "healthy"`
- `metadata.variant: "B"`

#### Timeout Response

Purpose: completed response body if the intentional timeout sleep does not cause upstream timeout first.

Fields:
- `service: "mock-target-api"`
- `endpoint: "timeout"`
- `status: "healthy"`
- `delay_seconds: integer`
- `timeout_mode: "default" | "short"`

## 8. API Contracts

All endpoints use API Gateway HTTP API Lambda proxy integration. Handlers must accept HTTP API v2 event shape, including:

- `version: "2.0"`
- `requestContext.http.method`
- `rawPath`
- `queryStringParameters`
- `headers`

Handlers should tolerate missing `headers` and missing `queryStringParameters` by treating them as empty dictionaries.

### Endpoint: GET /health/fast

#### Purpose
Stable low-latency healthy endpoint.

#### Authentication / Authorization
None. Internal operational fixture only; access is controlled by deployment/network exposure rather than application auth.

#### Request Parameters
None.

#### Request Body
None.

#### Response Body
```json
{
  "service": "mock-target-api",
  "endpoint": "fast",
  "status": "healthy"
}
```

#### Success Status Codes
- `200 OK`

#### Error Status Codes
- No intentional application errors.
- Platform-level Lambda/API Gateway errors may occur only for infrastructure failures.

#### Validation Rules
Ignore unrelated query parameters and headers.

#### Side Effects
Structured log entry only.

#### Idempotency / Duplicate Handling
Repeated requests return the same body and status.

### Endpoint: GET /health/slow

#### Purpose
Stable healthy endpoint with controlled deterministic delay.

#### Authentication / Authorization
None.

#### Request Parameters
Query:
- `delay_ms` optional integer, valid only from 800 through 1500 inclusive.
- `seed` optional string, including empty string.

#### Request Body
None.

#### Response Body
```json
{
  "service": "mock-target-api",
  "endpoint": "slow",
  "status": "healthy",
  "delay_ms": 1000,
  "delay_source": "default"
}
```

#### Success Status Codes
- `200 OK`

#### Error Status Codes
- Invalid `delay_ms` does not return 4xx; it is ignored for fallback per product spec.

#### Validation Rules
- Use valid `delay_ms` if supplied and integer in `[800, 1500]`.
- If `delay_ms` is invalid and `seed` exists, use `800 + stable_hash(seed) % 701`.
- If neither valid `delay_ms` nor seed exists, use 1000 ms.

#### Side Effects
Sleeps for resolved delay and emits structured log metadata.

#### Idempotency / Duplicate Handling
Repeated requests with same parameters use same delay and response schema.

### Endpoint: GET /health/flaky

#### Purpose
Deterministic intermittent health/degraded endpoint.

#### Authentication / Authorization
None.

#### Request Parameters
Query:
- `seed` optional string, first precedence.

Headers:
- `X-RCP-Seed` optional string, second precedence. Header lookup must be case-insensitive.

#### Request Body
None.

#### Response Body: Success
```json
{
  "service": "mock-target-api",
  "endpoint": "flaky",
  "status": "healthy",
  "seed_source": "query",
  "hash_mod": 1
}
```

#### Response Body: Failure
```json
{
  "service": "mock-target-api",
  "endpoint": "flaky",
  "status": "degraded",
  "seed_source": "query",
  "hash_mod": 0
}
```

#### Success Status Codes
- `200 OK` when `stable_hash(seed) % 5 != 0`.

#### Error Status Codes
- `500 Internal Server Error` when `stable_hash(seed) % 5 == 0`; this is intentional fixture behavior and still returns valid JSON.

#### Validation Rules
- Query `seed` takes precedence over `X-RCP-Seed`.
- Empty seed is valid and deterministic.
- Time-window fallback may be used only when both query and header seed are absent.

#### Side Effects
Structured log entry only.

#### Idempotency / Duplicate Handling
Same seed always produces same status.

### Endpoint: GET /health/inconsistent

#### Purpose
Always-successful endpoint with deterministic response schema variation.

#### Authentication / Authorization
None.

#### Request Parameters
Query:
- `variant` optional, valid values `A` or `B`.
- `seed` optional string.

#### Request Body
None.

#### Response Body: Variant A
```json
{
  "service": "mock-target-api",
  "endpoint": "inconsistent",
  "status": "healthy",
  "version": "A"
}
```

#### Response Body: Variant B
```json
{
  "service": "mock-target-api",
  "endpoint": "inconsistent",
  "status": "healthy",
  "metadata": {
    "variant": "B"
  }
}
```

#### Success Status Codes
- `200 OK`

#### Error Status Codes
- Invalid `variant` does not return 4xx; it falls back to seed or time-window behavior per product spec.

#### Validation Rules
- Valid `variant=A|B` forces corresponding variant.
- Invalid or absent `variant` with `seed` derives `A` for `stable_hash(seed) % 2 == 0`, otherwise `B`.
- No valid variant and no seed uses deterministic time-window fallback.

#### Side Effects
Structured log entry only.

#### Idempotency / Duplicate Handling
Same valid variant or seed returns same variant.

### Endpoint: GET /health/timeout

#### Purpose
Endpoint that intentionally sleeps longer than the platform runner timeout threshold of `max_timeout_seconds=30` by default.

#### Authentication / Authorization
None.

#### Request Parameters
None.

#### Request Body
None.

#### Response Body
Returned only if the invocation is allowed to complete:
```json
{
  "service": "mock-target-api",
  "endpoint": "timeout",
  "status": "healthy",
  "delay_seconds": 35,
  "timeout_mode": "default"
}
```

#### Success Status Codes
- `200 OK` if the client/API Gateway/Lambda configuration permits completion.

#### Error Status Codes
- Upstream timeout behavior is expected for audit runner validation. API Gateway or client may terminate before JSON response is observed.

#### Validation Rules
- `MOCK_TARGET_SHORT_TIMEOUT=true` selects short 2-3 second mode.
- Any other value, including unset, selects default 35-45 second mode.

#### Side Effects
Intentional sleep and structured log entry only.

#### Idempotency / Duplicate Handling
Repeated requests have the same mode and deterministic delay selection strategy for the active mode.

## 9. Frontend Impact

No frontend impact. No UI components, customer workflows, dashboards, Cognito flows, or browser integrations are in scope.

## 10. Backend Logic

### Responsibilities

- Parse API Gateway HTTP API events defensively.
- Resolve endpoint-specific deterministic behavior.
- Sleep only where required by slow and timeout endpoints.
- Return valid JSON for all completed application responses.
- Emit structured safe logs.

### Validation Flow

- Treat missing query/header maps as empty.
- For `delay_ms`, parse as base-10 integer only; reject floats, strings with non-digits, below 800, and above 1500 for explicit delay use.
- For `variant`, accept only exact uppercase `A` or `B`; invalid values fall back rather than erroring.
- For headers, normalize names to lowercase before looking up `x-rcp-seed`.

### Business Rules

- Do not use uncontrolled randomness.
- Use SHA-256 stable hash for all seed modulo behavior.
- Time-window fallback is only for manual exploration and must not be used in deterministic tests.
- Fast endpoint must not intentionally sleep.
- Timeout default mode must exceed 30 seconds in deployed stages unless explicitly configured otherwise.

### Persistence Flow

No persistence.

### Error Handling

- Expected invalid inputs (`delay_ms`, `variant`) use specified fallback behavior and do not produce 4xx errors.
- Unexpected handler exceptions should be caught at the handler boundary and returned as valid JSON `500` with `service`, `endpoint`, `status: error`, and a generic `error: internal_error`. Do not include stack traces or raw event payloads in responses.
- Intentional flaky `500` must use `status: degraded`, not `status: error`, to distinguish fixture behavior from implementation failure.

### Delay and Timeout Strategy

- Slow endpoint delay is in milliseconds and should use `time.sleep(delay_ms / 1000.0)` behind an injectable/wrappable utility for tests.
- Timeout endpoint delay is in seconds and should also call a wrapper to support monkeypatching.
- Timeout default range selection must be deterministic. Recommended approach: derive a stable bucket from a fixed mode seed such as `"timeout:default"` or a time-window fallback and map into `[35, 45]`; short mode maps into `[2, 3]`.
- Unit tests should monkeypatch sleep and assert intended duration. Integration tests should use short mode for local/CI.

## 11. File Structure

Required structure:

```text
apps/mock-target-api/
  handlers/
    health_fast.py
    health_slow.py
    health_flaky.py
    health_inconsistent.py
    health_timeout.py
  services/
    response_service.py
    flaky_service.py
    inconsistency_service.py
    timeout_service.py
  utils/
    deterministic_delay.py
    response_helpers.py
  tests/
    unit/
    integration/
  events/
    sample_events/
  docs/
    validation-behavior.md
  requirements.txt
  serverless.yml
  README.md
```

### `serverless.yml` Resource / Function Shape

Recommended Serverless configuration shape:

- `service: mock-target-api`
- `frameworkVersion` pinned to the repository-supported Serverless version if a project standard exists.
- `provider.name: aws`
- `provider.runtime: python3.11`
- `provider.stage: ${opt:stage, 'dev'}`
- `provider.region: ${opt:region, 'us-east-1'}` unless repository deployment standards specify otherwise.
- `provider.httpApi` enabled with default HTTP API behavior.
- `provider.environment`:
  - `STAGE: ${sls:stage}`
  - `SERVICE_NAME: mock-target-api`
  - `MOCK_TARGET_SHORT_TIMEOUT: ${env:MOCK_TARGET_SHORT_TIMEOUT, 'false'}`
- Functions:
  - `healthFast`: `handler: handlers/health_fast.handler`, event `httpApi: GET /health/fast`, timeout small such as 3 seconds.
  - `healthSlow`: `handler: handlers/health_slow.handler`, event `httpApi: GET /health/slow`, timeout at least 5 seconds.
  - `healthFlaky`: `handler: handlers/health_flaky.handler`, event `httpApi: GET /health/flaky`, timeout small such as 3 seconds.
  - `healthInconsistent`: `handler: handlers/health_inconsistent.handler`, event `httpApi: GET /health/inconsistent`, timeout small such as 3 seconds.
  - `healthTimeout`: `handler: handlers/health_timeout.handler`, event `httpApi: GET /health/timeout`, timeout must exceed max intended sleep; recommend 50 seconds to allow 35-45 second sleep to complete if API/client permits.

Stage configuration:
- Deploy with `sls deploy --stage dev|staging|prod` from `apps/mock-target-api/`.
- Default `MOCK_TARGET_SHORT_TIMEOUT` must be `false` for all deployed stages unless explicitly set by deployment environment.
- Do not define IAM permissions beyond Lambda execution logging unless required by the Serverless provider default. No boto3 use is expected.

## 12. Security

- Authentication/authorization is intentionally out of scope per product specification.
- The API is internal operational infrastructure; exposure should be limited through AWS account/environment controls, non-public documentation, stage naming, and deployment permissions.
- Do not log raw request bodies, full headers, authorization-like headers, cookies, or secret-looking values.
- If logging seed usage, log `seed_source` and `hash_mod`, not raw seed values.
- Validate all query inputs before use and avoid reflecting arbitrary input in responses unless necessary.
- Set `Cache-Control: no-store` to reduce accidental caching of fixture responses.
- No persistence means no stored PII or retained customer data.

## 13. Reliability

- Handlers should be small, deterministic, and independent to minimize blast radius.
- Invalid query values should not fail endpoints unless explicitly intended; fallback behavior is required for `delay_ms` and `variant`.
- Use explicit Lambda timeouts appropriate to endpoint behavior; especially configure `/health/timeout` above 45 seconds.
- Avoid external network calls and boto3 dependencies to reduce cold-start and runtime failure modes.
- Logs should include endpoint, status code, selected mode/source, and delay/variant/hash modulo, but not sensitive inputs.
- API Gateway HTTP API maximum integration behavior may affect whether `/health/timeout` returns a body; this is acceptable because the endpoint's purpose is runner timeout classification.
- Tests must avoid nondeterministic time-window fallback except in targeted manual/fallback tests.

## 14. Dependencies

- AWS Lambda.
- AWS API Gateway HTTP API.
- Serverless Framework.
- Python 3.11 standard library.
- Pytest for tests.
- `boto3` is not required for current scope and should not be added unless deployment/runtime needs are discovered.

## 15. Assumptions

- Stage names are `dev`, `staging`, and `prod` as specified by the product context.
- SHA-256 integer hashing is the approved stable interpretation of product references to `hash(seed)`.
- Integration tests can run against either local Serverless invocation or a deployed base URL supplied by environment variable.
- Endpoint response bodies may include deterministic diagnostic fields like `delay_ms`, `delay_source`, `seed_source`, `hash_mod`, and `timeout_mode` because they support validation without altering required fields.

## 16. Risks / Open Questions

- API Gateway and Lambda timeout limits may affect whether `/health/timeout` returns JSON versus client/API timeout. The implementation must document expected deployed behavior and keep Lambda timeout compatible with the intended sleep.
- If `MOCK_TARGET_SHORT_TIMEOUT=true` is accidentally set in deployed dev/staging/prod, timeout validation will not represent the required 35-45 second default.
- Time-window fallback can reduce reproducibility if tests use it. Tests should prefer explicit seeds/variants.
- Exact AWS region and Serverless version may be governed by repository deployment standards not described in the product spec.
- Open question for engineering: whether diagnostic fields should echo seed values. This design recommends not echoing raw seed values by default.

## 17. Implementation Notes

### Implementation Sequencing for dev-backend

1. Create `apps/mock-target-api/` with the required directory structure and minimal `requirements.txt`.
2. Implement `utils/response_helpers.py` for JSON Lambda proxy responses, query/header normalization, and structured logging helpers.
3. Implement `utils/deterministic_delay.py` with SHA-256 `stable_hash`, slow delay resolution, and sleep wrapper.
4. Implement `services/response_service.py` for all deterministic response bodies.
5. Implement `services/flaky_service.py`, `services/inconsistency_service.py`, and `services/timeout_service.py` as pure, unit-testable logic.
6. Implement each handler as a thin adapter from HTTP API event to service calls and response helpers.
7. Add sample HTTP API v2 events under `events/sample_events/` for each endpoint.
8. Add unit tests for hash stability, delay resolution, seed precedence, variant selection, timeout mode selection, response schemas, and handler outputs with monkeypatched sleep.
9. Add integration tests that can target local invocation or deployed base URL; use short timeout mode for CI.
10. Add `serverless.yml` with five route/function mappings and stage-aware configuration.
11. Add `README.md` and `docs/validation-behavior.md` documenting fixture purpose, endpoint ground truth, curl/local/deploy/pytest usage, and timeout caveats.

### Local Invocation Strategy

- Use Serverless Framework local invocation with sample events, for example `sls invoke local -f healthFast -p events/sample_events/health_fast.json`.
- For HTTP-style local testing, use whichever repository-approved Serverless local HTTP plugin/tooling exists; do not introduce a heavy web framework.
- Curl testing should target deployed HTTP API base URL or local HTTP emulation when available.

### Test Strategy

- Unit tests:
  - Assert SHA-256 hash is stable across repeated calls.
  - Assert slow `delay_ms` valid boundaries 800 and 1500 are accepted.
  - Assert invalid slow delays fall back to seed/default.
  - Assert flaky query seed overrides header seed.
  - Assert seeds with modulo 0 produce 500 degraded and others produce 200 healthy.
  - Assert inconsistent forced variants and seed-derived variants.
  - Assert timeout short/default ranges without sleeping full duration.
  - Assert all completed responses are valid JSON with service/endpoint identifiers.
- Integration tests:
  - Exercise each route through local/deployed HTTP when `MOCK_TARGET_API_BASE_URL` is set.
  - Mark deployed integration tests optional/skippable when no base URL is configured.
  - Use explicit seeds/variants and `MOCK_TARGET_SHORT_TIMEOUT=true` for timeout tests in CI/local.
