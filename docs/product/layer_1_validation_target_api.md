# Product Specification

## 1. Feature Overview

Layer 1 Validation Target API is an internal, backend-only operational validation fixture for the release-confidence-platform. It provides controlled HTTP endpoints with deterministic healthy, slow, flaky, inconsistent, and timeout behaviors so the platform can validate audit execution, scheduler behavior, runner correctness, raw evidence integrity, failure classification, lifecycle handling, sanitization, and future deterministic analytics inputs.

The API will be implemented as AWS API Gateway HTTP API endpoints backed by AWS Lambda functions, deployed through the Serverless Framework using Python 3.11.

## 2. Problem Statement

The release-confidence-platform needs known ground-truth target behavior to compare expected endpoint behavior against actual audit findings. Without a controlled validation target, failures in the core engine, scheduler, runner, evidence capture, or classification logic cannot be reliably distinguished from unpredictable behavior in external systems.

This feature solves that problem by introducing deterministic target endpoints that intentionally represent common operational conditions: fast healthy responses, slow stable responses, intermittent failures, inconsistent response shapes, and request timeouts.

## 3. User Persona / Target User

- As a platform engineer, I need deterministic validation endpoints so that I can verify audit runner behavior against known outcomes.
- As a QA engineer, I need reproducible endpoint behavior so that I can validate failure classification and lifecycle handling.
- As a backend engineer, I need an isolated fixture service so that platform behavior can be tested without depending on customer-facing systems or third-party APIs.

## 4. User Stories

- As a platform engineer, I want a fast stable endpoint so that I can validate low-latency successful audit execution.
- As a platform engineer, I want a slow but successful endpoint so that I can validate latency measurement without failure classification.
- As a QA engineer, I want a deterministic flaky endpoint so that intermittent failures can be reproduced using a seed.
- As a QA engineer, I want a deterministic inconsistent endpoint so that response schema and fingerprint variation can be validated.
- As a backend engineer, I want a timeout endpoint so that runner timeout and retry classification can be validated without external dependencies.

## 5. Goals / Success Criteria

- Provide five independent HTTP GET endpoints with known deterministic behavior.
- Enable local invocation, curl testing, AWS dev deployment, and pytest-based unit/integration validation.
- Ensure endpoint responses are valid JSON and include service and endpoint identifiers.
- Ensure unstable behavior is controlled and reproducible using seeds where specified.
- Enable audit validation outcomes:
  - `fast` -> low latency, high stability, consistent responses.
  - `slow` -> higher latency, stable response, minimal failures.
  - `flaky` -> intermittent failures, higher variance, degraded stability.
  - `inconsistent` -> response/schema/fingerprint variation.
  - `timeout` -> timeout failures, retry behavior, timeout classification.
- Keep implementation lightweight, deterministic, isolated, and backend-only.

## 6. Feature Scope

### In Scope

- Create the Layer 1 Validation Target API under `apps/mock-target-api/`.
- Implement AWS Lambda handlers for:
  - `GET /health/fast`
  - `GET /health/slow`
  - `GET /health/flaky`
  - `GET /health/inconsistent`
  - `GET /health/timeout`
- Use API Gateway HTTP API with independent endpoint invocation.
- Deploy using Serverless Framework.
- Use Python 3.11.
- Provide deterministic service utilities for delays, response helpers, flaky behavior, inconsistent behavior, and timeout behavior.
- Support stage separation for `dev`, `staging`, and `prod`.
- Provide local invocation and curl-based testing instructions.
- Provide pytest unit and integration tests for endpoint behavior.
- Provide `docs/validation-behavior.md` inside the mock target API app documenting expected behavior and audit interpretation.
- Provide `README.md` explaining fixture purpose, non-production product status, endpoint behavior, deployment, and local testing.
- Emit structured logs without secrets and without excessive noise.

### Out of Scope

- Frontend UI.
- Customer-facing product workflows.
- Authentication or authorization.
- Cognito integration.
- Databases, DynamoDB, or relational persistence.
- S3 persistence.
- User management.
- Dashboards.
- Billing.
- AI logic.
- Analytics implementation.
- Observability tooling beyond basic structured logs.
- Distributed tracing.
- Heavy web frameworks.

### Future Considerations

- Additional fixture endpoints for advanced analytics validation.
- Expanded response-shape variants beyond A/B.
- Optional environment-specific behavior matrices if future audit phases require them.

## 7. Functional Requirements

### FR-1: Monorepo Placement

The feature must be located under `apps/mock-target-api/` with the following structure:

- `handlers/health_fast.py`
- `handlers/health_slow.py`
- `handlers/health_flaky.py`
- `handlers/health_inconsistent.py`
- `handlers/health_timeout.py`
- `services/response_service.py`
- `services/flaky_service.py`
- `services/inconsistency_service.py`
- `services/timeout_service.py`
- `utils/deterministic_delay.py`
- `utils/response_helpers.py`
- `tests/unit/`
- `tests/integration/`
- `events/sample_events/`
- `docs/validation-behavior.md`
- `requirements.txt`
- `serverless.yml`
- `README.md`

### FR-2: Fast Health Endpoint

`GET /health/fast` must always return HTTP 200 with a stable deterministic JSON body. The response must identify:

- `service`: `mock-target-api`
- `endpoint`: `fast`
- `status`: `healthy`

The endpoint must target 50-150 ms latency and must not intentionally sleep.

### FR-3: Slow Health Endpoint

`GET /health/slow` must always return HTTP 200 with a stable deterministic JSON body. The response must identify:

- `service`: `mock-target-api`
- `endpoint`: `slow`
- `status`: `healthy`

Delay behavior must be deterministic:

- If `delay_ms` query parameter is supplied and is an integer from 800 through 1500 inclusive, use that value.
- If `delay_ms` is absent or invalid and `seed` is supplied, derive delay using `delay_ms = 800 + (hash(seed) % 701)`.
- If both valid `delay_ms` and `seed` are absent, use a fixed default delay of 1000 ms.

### FR-4: Flaky Health Endpoint

`GET /health/flaky` must produce deterministic intermittent instability. It must sometimes return HTTP 200 and sometimes return HTTP 500 based on a stable hash.

Seed selection precedence:

1. Query parameter `seed`.
2. Header `X-RCP-Seed`.
3. Deterministic time-window fallback for manual exploration only.

Behavior:

- Convert the selected seed to a stable hash.
- Return HTTP 500 when `hash(seed) % 5 == 0`.
- Return HTTP 200 otherwise.
- Success responses must include `status`: `healthy`.
- Failure responses must include `status`: `degraded`.
- All responses must include `service`: `mock-target-api` and `endpoint`: `flaky`.

### FR-5: Inconsistent Health Endpoint

`GET /health/inconsistent` must always return HTTP 200 while intentionally varying response structure or fields deterministically.

Variant selection precedence:

1. Query parameter `variant=A|B`.
2. If `variant` is absent or invalid and `seed` is supplied, derive variant using `hash(seed) % 2`:
   - `0` -> Variant A
   - `1` -> Variant B
3. Deterministic time-window fallback for manual exploration only.

Response behavior:

- All responses must include `service`: `mock-target-api` and `endpoint`: `inconsistent`.
- Variant A must include `version`: `A`.
- Variant B must include `metadata.variant`: `B`.

### FR-6: Timeout Health Endpoint

`GET /health/timeout` must intentionally exceed the platform runner timeout threshold.

Behavior:

- Default runtime sleep must be 35-45 seconds.
- The default behavior must exceed `max_timeout_seconds=30`.
- Deployed `dev`, `staging`, and `prod` stages must keep the 35-45 second default unless explicitly configured otherwise.
- If environment variable `MOCK_TARGET_SHORT_TIMEOUT=true` is set, local/test timeout behavior may be shortened to 2-3 seconds.
- Normal CI tests must not be forced to wait 35-45 seconds.

### FR-7: Global Response Requirements

- All completed endpoint responses must be valid JSON.
- All completed endpoint responses must include service identifier and endpoint identifier.
- Responses must include deterministic fields appropriate to endpoint behavior.
- No endpoint may use uncontrolled randomness.
- Intentional instability must be controlled and reproducible.

### FR-8: Deployment and Environment Requirements

- The API must be deployable through Serverless Framework.
- The runtime must be Python 3.11.
- The API must use AWS Lambda and API Gateway HTTP API.
- The API must support distinct `dev`, `staging`, and `prod` stages.
- Endpoint invocation must be independently testable through HTTP API routes.

### FR-9: Documentation Requirements

The `README.md` must document:

- Fixture purpose.
- Backend-only/internal operational status.
- Non-production product status.
- Expected endpoint behavior.
- Expected audit interpretation per endpoint.
- Deployment instructions.
- Local invocation and curl testing instructions.
- Pytest testing instructions.

The `docs/validation-behavior.md` file must document endpoint behavior as ground truth for audit validation.

### FR-10: Test Requirements

The feature must include pytest unit and integration tests covering:

- `/health/fast`: returns 200, low latency, stable response.
- `/health/slow`: returns 200, delayed response, stable schema.
- `/health/flaky`: deterministic intermittent failure and reproducible behavior.
- `/health/inconsistent`: deterministic schema variation.
- `/health/timeout`: exceeds configured timeout threshold without forcing normal CI to wait 35-45 seconds.

## 8. Acceptance Criteria

### AC-1: Fast Endpoint Stable Success

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/fast`  
Then the API returns HTTP 200 with valid JSON containing `service: mock-target-api`, `endpoint: fast`, and `status: healthy`.

### AC-2: Fast Endpoint Has No Intentional Delay

Given the fast endpoint implementation is executed  
When endpoint behavior is reviewed or unit tested  
Then no intentional sleep or deterministic delay is applied by `/health/fast`.

### AC-3: Slow Endpoint Uses Valid Explicit Delay

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/slow?delay_ms=800`  
Then the API returns HTTP 200 after applying an 800 ms intentional delay and returns valid JSON containing `service: mock-target-api`, `endpoint: slow`, and `status: healthy`.

### AC-4: Slow Endpoint Rejects Invalid Explicit Delay for Fallback

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/slow?delay_ms=799&seed=abc`  
Then the API ignores the invalid `delay_ms`, derives delay using `800 + (hash("abc") % 701)`, and returns HTTP 200 with the stable slow response schema.

### AC-5: Slow Endpoint Uses Fixed Default Delay

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/slow` without `delay_ms` or `seed`  
Then the API applies a 1000 ms intentional delay and returns HTTP 200 with the stable slow response schema.

### AC-6: Flaky Endpoint Uses Query Seed First

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/flaky?seed=<value>` with any `X-RCP-Seed` header  
Then the endpoint determines success or failure using the query parameter seed and not the header seed.

### AC-7: Flaky Endpoint Produces Deterministic Failure

Given a seed where `hash(seed) % 5 == 0`  
When a client sends `GET /health/flaky?seed=<seed>`  
Then the API returns HTTP 500 with valid JSON containing `service: mock-target-api`, `endpoint: flaky`, and `status: degraded`.

### AC-8: Flaky Endpoint Produces Deterministic Success

Given a seed where `hash(seed) % 5 != 0`  
When a client sends `GET /health/flaky?seed=<seed>`  
Then the API returns HTTP 200 with valid JSON containing `service: mock-target-api`, `endpoint: flaky`, and `status: healthy`.

### AC-9: Flaky Endpoint Header Fallback

Given the request has no `seed` query parameter and includes header `X-RCP-Seed: <value>`  
When a client sends `GET /health/flaky`  
Then the endpoint determines success or failure using the header seed.

### AC-10: Inconsistent Endpoint Variant A

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/inconsistent?variant=A`  
Then the API returns HTTP 200 with valid JSON containing `service: mock-target-api`, `endpoint: inconsistent`, and `version: A`.

### AC-11: Inconsistent Endpoint Variant B

Given the Layer 1 Validation Target API is running  
When a client sends `GET /health/inconsistent?variant=B`  
Then the API returns HTTP 200 with valid JSON containing `service: mock-target-api`, `endpoint: inconsistent`, and `metadata.variant: B`.

### AC-12: Inconsistent Endpoint Seed-Derived Variant

Given no valid `variant` query parameter is supplied and a `seed` query parameter is supplied  
When a client sends `GET /health/inconsistent?seed=<seed>`  
Then the endpoint returns Variant A if `hash(seed) % 2 == 0` and Variant B if `hash(seed) % 2 == 1`.

### AC-13: Timeout Endpoint Default Exceeds Runner Threshold

Given the timeout endpoint is running without `MOCK_TARGET_SHORT_TIMEOUT=true`  
When a client sends `GET /health/timeout`  
Then the endpoint intentionally sleeps for 35-45 seconds, exceeding `max_timeout_seconds=30`.

### AC-14: Timeout Endpoint Supports Short Local/Test Mode

Given environment variable `MOCK_TARGET_SHORT_TIMEOUT=true` is configured  
When `/health/timeout` behavior is invoked in local or test validation  
Then the endpoint uses a shortened 2-3 second timeout behavior instead of the 35-45 second default.

### AC-15: CI Does Not Wait for Full Timeout

Given the automated CI test suite runs timeout endpoint tests  
When timeout behavior is validated  
Then CI validates timeout configuration or short mode without requiring a 35-45 second sleep.

### AC-16: Serverless Deployment Configuration

Given the mock target API app is configured  
When the Serverless Framework deployment is executed for `dev`, `staging`, or `prod`  
Then API Gateway HTTP API routes are deployed to AWS Lambda functions using Python 3.11.

### AC-17: Documentation Completeness

Given the feature is ready for handoff  
When `apps/mock-target-api/README.md` and `apps/mock-target-api/docs/validation-behavior.md` are reviewed  
Then they document fixture purpose, non-production status, endpoint behavior, audit interpretation, deployment, local testing, curl testing, and pytest testing.

## 9. Edge Cases

- `delay_ms` below 800 or above 1500 must not be used as explicit slow endpoint delay.
- Non-integer `delay_ms` must be treated as invalid and must fall back to seed-derived or default delay behavior.
- Empty string seed must be handled deterministically and must not cause runtime failure.
- Flaky endpoint must use query seed before `X-RCP-Seed` if both are present.
- Flaky endpoint without seed or header may use deterministic time-window fallback only for manual exploration; tests must prefer explicit seeds.
- Inconsistent endpoint with invalid `variant` must fall back to seed-derived behavior when seed is present.
- Inconsistent endpoint without valid variant or seed may use deterministic time-window fallback only for manual exploration; tests must prefer explicit variants or seeds.
- Timeout endpoint local/test short mode must not accidentally alter deployed default behavior unless explicitly configured.
- Lambda/API Gateway timeout configuration must be compatible with the endpoint's intended timeout behavior and test strategy.
- Responses must remain valid JSON for completed responses, including HTTP 500 flaky responses.

## 10. Constraints

- Backend-only/internal operational infrastructure; not customer-facing.
- Must use API Gateway HTTP API -> AWS Lambda architecture.
- Must use Serverless Framework.
- Must use Python 3.11.
- Must remain lightweight, deterministic, and isolated.
- Must not introduce authentication, databases, persistence layers, frontend dependencies, analytics logic, AI logic, heavy frameworks, or observability tooling beyond structured logs.
- Logs must be structured, must not contain secrets, and must avoid excessive noise.
- Randomness must be deterministic or derived from controlled inputs.
- Deployed timeout endpoint default must remain 35-45 seconds for `dev`, `staging`, and `prod` unless explicitly configured otherwise.

## 11. Dependencies

- AWS Lambda.
- AWS API Gateway HTTP API.
- Serverless Framework.
- Python 3.11 runtime.
- Pytest for unit and integration tests.
- Release-confidence-platform runner timeout expectation of `max_timeout_seconds=30` for timeout validation.

## 12. Assumptions

- Requires confirmation: The platform's stable hash implementation may be defined by engineering, but it must be deterministic across local, CI, and AWS Lambda environments.
- Requires confirmation: Stage names are exactly `dev`, `staging`, and `prod`.
- Requires confirmation: Integration tests may target local invocation and/or deployed AWS endpoints depending on environment configuration.

## 13. Open Questions

- Which exact stable hash algorithm should be standardized for seed-based behavior across Python versions and environments?
- Should response bodies include additional fields such as timestamp, request id, delay applied, seed used, or variant selected, provided they remain deterministic where required?
- What is the required Lambda timeout setting for `/health/timeout` relative to API Gateway and runner timeout behavior?

## 14. Risks

- If the hash algorithm is not standardized, seed-based behavior may differ between local, CI, and deployed environments.
- If Lambda or API Gateway timeout settings are misconfigured, `/health/timeout` may not produce the intended runner classification.
- If tests rely on time-window fallback instead of explicit seeds, results may become difficult to reproduce.
- If short timeout mode is accidentally enabled in deployed stages, timeout validation will no longer represent production-like runner behavior.

## 15. Definition of Done

- All five required endpoints are available through API Gateway HTTP API and Lambda handlers.
- Endpoint behavior matches the deterministic rules in this specification.
- All completed endpoint responses are valid JSON and include service and endpoint identifiers.
- Unit and integration tests cover all required endpoint behaviors.
- Timeout tests do not require normal CI to wait 35-45 seconds.
- Serverless deployment supports `dev`, `staging`, and `prod` stage separation.
- README and validation behavior documentation are complete.
- No out-of-scope systems or frameworks are introduced.
