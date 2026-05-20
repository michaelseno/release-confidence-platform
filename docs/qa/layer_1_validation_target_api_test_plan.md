# Test Plan

## 1. Feature Overview

Layer 1 Validation Target API is a backend-only/internal validation fixture implemented under `apps/mock-target-api/` using Serverless Framework, AWS Lambda Python 3.11 handlers, and API Gateway HTTP API routes.

The fixture exposes controlled `GET` endpoints used as ground truth for validating release-confidence-platform audit runner behavior:

- `/health/fast`: stable low-latency success.
- `/health/slow`: stable success with deterministic intentional delay.
- `/health/flaky`: deterministic intermittent 200/500 behavior using seeds.
- `/health/inconsistent`: deterministic schema variation using forced variants or seeds.
- `/health/timeout`: intentional timeout behavior exceeding `max_timeout_seconds=30` by default, with short local/test mode.

This plan is implementation-ready but not executed yet because the implementation is not complete. Execution evidence and final QA decision will be captured later in `docs/qa/layer_1_validation_target_api_test_report.md`.

Primary upstream artifacts:

- Product spec: `docs/product/layer_1_validation_target_api.md`
- Technical design: `docs/architecture/layer_1_validation_target_api_technical_design.md`

Assumed stable hash contract from technical design:

```python
stable_hash(seed) = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
```

If implementation uses a different stable hash function, expected seed outcomes below must be regenerated from the exposed implementation helper before test execution.

## 2. Acceptance Criteria Mapping

| Product AC / FR | Requirement | QA validation approach |
| --- | --- | --- |
| AC-1, FR-2 | `/health/fast` returns HTTP 200 and valid JSON with `service`, `endpoint`, `status` | Unit handler test and local/deployed HTTP integration test assert status/body/schema. |
| AC-2, FR-2 | `/health/fast` has no intentional sleep/delay | Unit test monkeypatches sleep/delay wrappers and asserts no invocation; static review ensures no delay utility call. |
| AC-3, FR-3 | `/health/slow?delay_ms=800` applies 800ms delay and returns stable 200 JSON | Unit test monkeypatches sleep and asserts 0.8s; integration latency check expects 800-1500ms plus bounded overhead where applicable. |
| AC-4, FR-3 | Invalid explicit delay falls back to seed-derived delay | Unit test for `delay_ms=799&seed=abc` expects SHA-256-derived delay `1234ms`; integration asserts response body reports seed source if diagnostic fields exist. |
| AC-5, FR-3 | Missing delay and seed uses fixed default 1000ms | Unit test asserts 1000ms sleep and stable response; integration latency within tolerance. |
| AC-6, FR-4 | Flaky endpoint uses query seed before `X-RCP-Seed` | Unit and integration tests send conflicting query/header seeds and assert query outcome. |
| AC-7, FR-4 | Flaky deterministic failure when `stable_hash(seed)%5==0` | Use known failing seed `seed-4` or `abc`; expect HTTP 500 JSON `status: degraded`, `hash_mod: 0` if included. |
| AC-8, FR-4 | Flaky deterministic success when `stable_hash(seed)%5!=0` | Use known passing seed `seed-0`; expect HTTP 200 JSON `status: healthy`, `hash_mod: 1` if included. |
| AC-9, FR-4 | Flaky header fallback | Send no query seed and header `X-RCP-Seed: seed-4`; expect 500 degraded. Validate case-insensitive header lookup. |
| AC-10, FR-5 | Inconsistent forced Variant A | `/health/inconsistent?variant=A` returns 200 JSON with `version: A`. |
| AC-11, FR-5 | Inconsistent forced Variant B | `/health/inconsistent?variant=B` returns 200 JSON with `metadata.variant: B`. |
| AC-12, FR-5 | Inconsistent seed-derived variant | Use `seed-3` for Variant A (`%2==0`) and `seed-0` for Variant B (`%2==1`). |
| AC-13, FR-6 | Timeout default sleeps 35-45s and exceeds runner threshold 30s | Unit test pure delay resolver and handler with sleep monkeypatched; serverless function timeout review expects timeout >45s. No full sleep in CI. Optional manual AWS validation may use client timeout <30s. |
| AC-14, FR-6 | `MOCK_TARGET_SHORT_TIMEOUT=true` uses 2-3s | Unit test environment-controlled resolver; local integration may invoke short mode and assert 2-3s plus overhead. |
| AC-15, FR-6 | CI does not wait 35-45s | Automated timeout tests monkeypatch sleep or use short mode only; no CI test invokes default mode with real sleep. |
| AC-16, FR-8 | Serverless deploy config uses HTTP API, Lambda, Python 3.11, dev/staging/prod stage separation | Static config tests parse `serverless.yml`; optional `sls print --stage dev|staging|prod` validation. |
| AC-17, FR-9 | README and validation behavior docs complete | Documentation review test/checklist validates required sections and audit interpretation coverage. |
| FR-1 | Required app structure under `apps/mock-target-api/` | Static file existence tests. |
| FR-7 | All completed responses valid JSON and include identifiers; no uncontrolled randomness | Unit/integration schema assertions; code review/static checks for Python built-in `hash(` and `random` usage. |
| Constraints | No prohibited dependencies/features; structured logs without secrets/noise | Dependency/config review; unit log capture tests assert structured fields and no raw secrets/authorization/cookies/raw seed logging. |

## 3. Test Scenarios

### Test strategy by level

#### Unit tests: `apps/mock-target-api/tests/unit/`

Purpose: validate deterministic business rules without network and without real long waits.

Coverage:

- Stable hash helper uses SHA-256 and is consistent across repeated calls.
- Query/header parsing tolerates missing maps and normalizes header case.
- Response helper returns Lambda proxy-compatible response with valid JSON body and headers.
- Each handler returns required status/body when invoked with HTTP API v2 sample events.
- Slow and timeout sleeps are called through injectable/wrappable functions so tests monkeypatch sleep and assert requested duration.
- Structured logs contain endpoint/status/source metadata and do not contain raw secrets, auth headers, cookies, raw event payloads, or unnecessary noise.

#### Integration/local tests: `apps/mock-target-api/tests/integration/`

Purpose: validate route-level behavior through local Serverless invocation or HTTP base URL without deployed AWS dependency.

Execution modes:

- Local Lambda invocation using `sls invoke local -f <function> -p events/sample_events/<event>.json`.
- HTTP-style integration against `MOCK_TARGET_API_BASE_URL` when set. Tests must skip clearly when no base URL is configured.
- Timeout integration must set `MOCK_TARGET_SHORT_TIMEOUT=true` and must never perform real 35-45s sleep in CI.

#### Optional manual AWS/dev validation

Purpose: confirm deployed API Gateway HTTP API and Lambda behavior in dev after implementation and deployment.

Suggested commands to document and later execute:

```bash
curl -i "$MOCK_TARGET_API_BASE_URL/health/fast"
curl -i "$MOCK_TARGET_API_BASE_URL/health/slow?delay_ms=800"
curl -i "$MOCK_TARGET_API_BASE_URL/health/flaky?seed=seed-4"
curl -i "$MOCK_TARGET_API_BASE_URL/health/inconsistent?variant=A"
curl --max-time 30 -i "$MOCK_TARGET_API_BASE_URL/health/timeout"
```

Manual `/health/timeout` default validation should use a client-side timeout and verify runner/client timeout classification, not wait for a full response in normal QA automation.

### Deterministic seed reference values

Expected values below assume the technical-design SHA-256 integer stable hash.

| Seed | `stable_hash(seed)%5` | Flaky expected result | `stable_hash(seed)%2` | Inconsistent expected variant | Slow delay `800 + hash%701` |
| --- | ---: | --- | ---: | --- | ---: |
| `seed-0` | 1 | 200 healthy | 1 | B | 1251ms |
| `seed-3` | not primary | not primary | 0 | A | 1117ms |
| `seed-4` | 0 | 500 degraded | not primary | not primary | 1327ms |
| `abc` | 0 | 500 degraded | 1 | B | 1234ms |
| empty string `""` | 4 | 200 healthy | 1 | B | 1071ms |

If implementation exposes `stable_hash()` but uses a different approved deterministic algorithm, add a small seed-discovery utility/test fixture that scans candidate seeds and records selected seeds where modulo outcomes are known before asserting endpoint behavior.

### Specific test cases

| ID | Level | Maps to | Purpose | Input | Expected output / validation logic |
| --- | --- | --- | --- | --- | --- |
| L1VTA-U-001 | Unit | AC-1 | Validate fast response body | Invoke `health_fast.handler` with HTTP API v2 event | `statusCode=200`; body JSON exactly/stably includes `service=mock-target-api`, `endpoint=fast`, `status=healthy`; content type JSON. |
| L1VTA-U-002 | Unit/static | AC-2 | Ensure fast has no intentional delay | Monkeypatch shared sleep wrapper and call fast handler; inspect imports/calls | Sleep wrapper not called; no deterministic delay service invoked by fast handler. |
| L1VTA-I-003 | Integration | AC-1, AC-2 | Validate fast local/HTTP low latency and determinism | `GET /health/fast` repeated 5 times | All 200; JSON body identical across requests; observed warm/local latency target 50-150ms where environment supports reliable measurement; no intentional sleep evidence if latency exceeds target due to environment. |
| L1VTA-U-004 | Unit | AC-3 | Explicit slow lower boundary | `/health/slow?delay_ms=800` with monkeypatched sleep | Sleep called once with `0.8`; 200 JSON includes required fields and, if present, `delay_ms=800`, `delay_source=query`. |
| L1VTA-U-005 | Unit | AC-3 | Explicit slow upper boundary | `/health/slow?delay_ms=1500` | Sleep called with `1.5`; 200 stable JSON. |
| L1VTA-U-006 | Unit | AC-4 | Invalid low delay falls back to seed | `/health/slow?delay_ms=799&seed=abc` | Does not use 799; sleep called with `1.234`; 200 JSON stable. |
| L1VTA-U-007 | Unit | AC-4 | Invalid high/non-integer delays fall back | `delay_ms=1501`, `delay_ms=abc`, `delay_ms=1.2`, `delay_ms=` with `seed=seed-0` | Each invalid explicit delay ignored; seed-derived delay used; no 4xx. |
| L1VTA-U-008 | Unit | AC-5 | Slow default delay | `/health/slow` without query params | Sleep called with `1.0`; 200 JSON with `delay_ms=1000`, `delay_source=default` if diagnostics exist. |
| L1VTA-I-009 | Integration/local | AC-3-AC-5 | Validate slow route timings without excessive runtime | Requests for `delay_ms=800`, `delay_ms=1500`, no params | 200 JSON; elapsed duration approximately matches requested/default delay with documented tolerance for local/AWS overhead. |
| L1VTA-U-010 | Unit | AC-7 | Flaky deterministic failure | `/health/flaky?seed=seed-4` | `statusCode=500`; valid JSON includes `endpoint=flaky`, `status=degraded`; `hash_mod=0` if present. |
| L1VTA-U-011 | Unit | AC-8 | Flaky deterministic success | `/health/flaky?seed=seed-0` | `statusCode=200`; valid JSON includes `status=healthy`; repeated calls identical. |
| L1VTA-U-012 | Unit | AC-6 | Flaky query seed precedence | Query `seed=seed-0`, header `X-RCP-Seed: seed-4` | Query seed wins; response is 200 healthy, not header-driven 500. |
| L1VTA-U-013 | Unit | AC-9 | Flaky header fallback and case-insensitive lookup | No query seed; headers `X-RCP-Seed: seed-4` and separately `x-rcp-seed: seed-4` | Both return 500 degraded using header seed source. |
| L1VTA-U-014 | Unit | FR-7 edge | Empty seed deterministic | `/health/flaky?seed=` | No crash; deterministic 200 healthy for SHA-256 empty seed (`%5=4`). |
| L1VTA-I-015 | Integration | AC-6-AC-9 | Validate flaky HTTP behavior | HTTP requests with `seed-4`, `seed-0`, conflicting query/header | Expected 500/200/status precedence; all responses parse as JSON including intentional 500. |
| L1VTA-U-016 | Unit | AC-10 | Forced inconsistent Variant A | `/health/inconsistent?variant=A` | `statusCode=200`; JSON includes `version=A`; Variant B-only `metadata.variant` absent unless documented otherwise. |
| L1VTA-U-017 | Unit | AC-11 | Forced inconsistent Variant B | `/health/inconsistent?variant=B` | `statusCode=200`; JSON includes `metadata.variant=B`; Variant A-only `version` absent unless documented otherwise. |
| L1VTA-U-018 | Unit | AC-12 | Seed-derived Variant A | `/health/inconsistent?seed=seed-3` | 200; Variant A schema because SHA-256 `%2=0`. |
| L1VTA-U-019 | Unit | AC-12 | Seed-derived Variant B | `/health/inconsistent?seed=seed-0` | 200; Variant B schema because SHA-256 `%2=1`. |
| L1VTA-U-020 | Unit | FR-5 edge | Invalid variant fallback to seed | `/health/inconsistent?variant=C&seed=seed-3` | No 4xx; falls back to seed-derived Variant A. |
| L1VTA-U-021 | Unit | FR-5 edge | Variant exactness | `variant=a`, `variant=b`, `variant= A ` with seed fallback | Lowercase/whitespace variants are invalid unless architecture is explicitly changed; seed/fallback behavior used. |
| L1VTA-I-022 | Integration | AC-10-AC-12 | Validate inconsistent route schemas | Requests for `variant=A`, `variant=B`, `seed-3`, `seed-0` | All HTTP 200; Variant A and B intentionally differ in schema; identifiers present. |
| L1VTA-U-023 | Unit | AC-13 | Timeout default delay configuration without full sleep | Unset `MOCK_TARGET_SHORT_TIMEOUT`; call resolver and handler with sleep monkeypatched | Resolved delay in `[35,45]`; handler attempts sleep with that value; no real wait; response body valid if handler completes. |
| L1VTA-U-024 | Unit | AC-14 | Timeout short mode | Set `MOCK_TARGET_SHORT_TIMEOUT=true`; monkeypatch sleep | Resolved delay in `[2,3]`; body includes `timeout_mode=short` if diagnostics exist. |
| L1VTA-U-025 | Unit | AC-15 | CI timeout guard | Test suite marker/config inspection | No automated default-mode test performs real sleep; default mode tests use monkeypatch. |
| L1VTA-I-026 | Integration/local | AC-14, AC-15 | Short timeout integration | Run with `MOCK_TARGET_SHORT_TIMEOUT=true`; call `/health/timeout` | Completes successfully after 2-3s plus overhead; valid JSON if response observed. |
| L1VTA-M-027 | Manual AWS/dev | AC-13 | Default timeout behavior with client cap | Deployed dev, short mode disabled; `curl --max-time 30 /health/timeout` or runner max timeout 30s | Client/runner times out before endpoint completes; confirms target exceeds runner threshold. Do not include in CI. |
| L1VTA-S-028 | Static/config | AC-16 | Serverless route/runtime validation | Parse `apps/mock-target-api/serverless.yml`; optionally `sls print --stage dev/staging/prod` | Python `python3.11`; HTTP API routes for all five endpoints; stage defaults and stage separation support; timeout function timeout >45s; other functions appropriately short. |
| L1VTA-S-029 | Static/config | FR-1 | File structure validation | Check required directories/files from product spec | All required handlers/services/utils/tests/events/docs/config files exist under `apps/mock-target-api/`. |
| L1VTA-S-030 | Static/dependency | Constraints | No prohibited dependencies/features | Review `requirements.txt`, imports, config | No DB, S3 persistence, Cognito/auth, frontend, analytics/AI, heavy frameworks, uncontrolled random, Python built-in `hash()` for behavior, or unnecessary boto3. |
| L1VTA-U-031 | Unit/logging | Global QA | Structured safe logs | Capture logs while invoking each handler with seed/header/secret-like headers | Logs include endpoint/status/mode/source metadata; do not log raw authorization/cookie headers, raw event payload, stack traces on expected paths, or raw seed values if design recommendation is followed. |
| L1VTA-S-032 | Docs review | AC-17 | README completeness | Review `apps/mock-target-api/README.md` | Documents fixture purpose, backend-only/internal and non-production status, endpoint behavior, audit interpretation, deployment, local invocation, curl, pytest. |
| L1VTA-S-033 | Docs review | AC-17 | Validation behavior docs completeness | Review `apps/mock-target-api/docs/validation-behavior.md` | Documents each endpoint as audit ground truth, deterministic seeds/variants, timeout interpretation, and expected evidence classification. |
| L1VTA-U-034 | Unit | FR-7 | Completed response JSON validity | Invoke all handlers, including flaky 500 and timeout short/monkeypatched completion | Every completed response body parses as JSON and contains `service` and `endpoint`. |
| L1VTA-U-035 | Unit | Error handling design | Unexpected exception sanitized | Monkeypatch a service to raise unexpected exception | Handler boundary returns valid generic JSON 500 with identifiers and no stack trace/raw event, if implementation includes boundary handling per design. |

## 4. Edge Cases

- `delay_ms=800` and `delay_ms=1500` are valid inclusive boundaries.
- `delay_ms=799`, `delay_ms=1501`, negative values, floats, non-numeric values, empty values, repeated query keys if represented by API Gateway, and leading/trailing whitespace must not be accepted as explicit delays unless implementation documents stricter normalization.
- Missing `queryStringParameters` and missing `headers` must be treated as empty maps.
- Empty string seed is valid and deterministic; tests must not assume truthiness means absence when API Gateway provides `seed=`.
- Flaky query seed takes precedence over header even when the header would produce a different status.
- `X-RCP-Seed` header lookup must be case-insensitive.
- Flaky and inconsistent tests must not rely on no-seed time-window fallback except optional manual exploratory checks because reproducibility is required.
- Inconsistent invalid `variant` values (`C`, lowercase `a`, whitespace-padded values) must not return 4xx; they fall back to seed or documented fallback behavior.
- Variant A and Variant B must intentionally differ in schema while still retaining `service` and `endpoint`.
- `/health/timeout` default must not be accidentally shortened in deployed `dev`, `staging`, or `prod`; only explicit `MOCK_TARGET_SHORT_TIMEOUT=true` may shorten local/test behavior.
- Lambda/API Gateway timeout values must support intended behavior: timeout function configured above the 35-45s sleep, while audit runner/client timeout may be 30s.
- Completed HTTP 500 flaky responses must still be valid JSON and represent intentional `degraded` fixture behavior, not `error` implementation failure.
- Logs must not include raw authorization headers, cookies, full request payloads, secret-looking values, or excessive per-request noise.

## 5. Test Types Covered

- Functional tests: all endpoint core behaviors, status codes, response schemas, delay/variant/flaky decisions.
- Negative tests: invalid `delay_ms`, invalid `variant`, missing query/header maps, unexpected exception sanitization where supported.
- Edge/boundary tests: delay boundaries, empty seed, header case-insensitivity, timeout range boundaries.
- Integration/local tests: route-level behavior via Serverless local invocation or HTTP base URL.
- Optional manual AWS/dev validation: deployed route smoke checks and timeout classification using client timeout.
- Static/config tests: required file structure, `serverless.yml`, runtime, routes, function timeout settings, stage separation, prohibited dependency review.
- Documentation tests/review: README and validation behavior documentation completeness.
- Security/safety checks: structured logs, no secret logging, no prohibited persistence/auth/frontend/heavy frameworks.
- Regression checks: deterministic response stability across repeated requests and preservation of internal fixture scope/no out-of-scope capabilities.

## 6. Coverage Justification

This plan covers every acceptance criterion in the product specification and validates the key technical-design decisions required for deterministic backend fixture behavior. Unit tests provide fast, deterministic coverage of business rules and avoid full timeout sleeps. Integration/local tests confirm handler and route behavior at the boundary closest to consumers. Static/config and documentation checks protect deployment correctness, monorepo structure, prohibited-scope constraints, and audit interpretation readiness.

Timeout coverage deliberately separates configuration validation from real waiting:

- Default mode is validated by pure resolver tests and monkeypatched handler tests asserting a 35-45s requested sleep.
- CI is protected by prohibiting real default-mode sleeps.
- Short mode validates executable timeout behavior in 2-3s for local/test runs.
- Optional AWS/dev manual validation may use a client timeout below 35s to confirm runner timeout classification without waiting for endpoint completion.

Regression risks to monitor during implementation and future changes:

- Replacing SHA-256 stable hashing with Python built-in `hash()` causing non-reproducible behavior across processes.
- Introducing wall-clock timestamps or request IDs into supposedly stable response bodies and breaking deterministic comparisons.
- Accidentally using time-window fallback in automated tests.
- Short timeout mode leaking into deployed dev/staging/prod configuration.
- Serverless function timeout for `/health/timeout` set below intended sleep range, causing Lambda failures instead of target-induced runner timeout behavior.
- Adding prohibited dependencies such as web frameworks, persistence, auth, analytics, AI, or unnecessary AWS SDK usage.
- Logging raw seeds, headers, authorization values, cookies, or full events.

QA sign-off criteria for the later execution report:

- All critical unit, integration/local, static/config, and documentation tests pass.
- No unresolved application bugs affecting deterministic behavior, route availability, timeout strategy, JSON validity, or deployment configuration.
- No blocking regressions or prohibited out-of-scope dependencies/features.
- Timeout tests prove default configuration without full CI sleep and prove short mode behavior where executable.
- Evidence includes test command output, relevant logs, and any optional manual AWS/dev curl output.
- Any flaky test must be investigated and classified; approval is not allowed with unresolved flakiness.

Current QA status: planning artifact only. No tests executed and no QA sign-off issued because implementation has not occurred.
