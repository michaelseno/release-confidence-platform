# Test Plan

## 1. Feature Overview

Phase 1 validates the backend-only core execution engine for the Release Confidence Platform on branch `feature/phase_1_core_engine_foundation`.

The QA scope is limited to the Phase 1 core engine foundation defined by:

- Product specification: `docs/product/phase_1_core_engine_foundation_product_spec.md`
- Technical design: `docs/architecture/phase_1_core_engine_foundation_technical_design.md`

The feature under test is a generic, config-driven Lambda orchestrator that validates an invocation event, establishes a safe `run_id`, loads S3-backed configuration, resolves secrets only through AWS Secrets Manager references, executes configured API requests with `requests`, produces deterministic Raw Result Schema v1 evidence, sanitizes all logs and persisted outputs, writes one raw result object at run completion, and persists/query metadata in DynamoDB.

Confirmed Phase 1 constraints that QA will enforce:

- Event contract includes `client_id`, `audit_id`, `scenario_type`, `triggered_by`, and optional `run_id`.
- Supplied `run_id` is valid only when it exactly matches `^[A-Za-z0-9_-]{8,80}$`.
- Invalid supplied `run_id` values are rejected without normalization, without replacement generation, and without raw-value logging.
- Generated `run_id` is UUIDv4 only when `run_id` is absent.
- Duplicate `run_id` detection checks existing S3 raw result object and existing DynamoDB run metadata before raw evidence write and fails with controlled `DUPLICATE_RUN_ID` without overwrite, append, or merge.
- `DUPLICATE_RUN_ID` is a run-level orchestration/storage control error, not an endpoint `failure_type`.
- Raw Result Schema v1 uses `raw_result_version = "v1"`.
- Raw evidence is persisted once at run completion to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- DynamoDB metadata keys are `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Sanitization replaces sensitive values with `"[REDACTED]"` before logs, S3 persistence, DynamoDB persistence, and response/report handoff.
- Log categories are `internal_operational_logs` and `client_safe_logs`.
- Phase 1 statuses are limited to `STARTED`, `COMPLETED`, and `FAILED`.
- Endpoint `failure_type` values are limited to `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, and `PAYLOAD_VALIDATION_ERROR`.

Out of scope for QA approval in this plan: frontend/dashboard, application authentication/RBAC, billing, subscriptions, AI insights, scoring, report-generation product behavior, load testing product behavior, uptime monitoring, chaos engineering, and heavy API framework behavior.

## 2. Acceptance Criteria Mapping

| AC | Requirement summary | Required QA validation | Primary test level |
| --- | --- | --- | --- |
| AC-001 | Valid event starts one audit run | Valid event accepted; identifiers used consistently; exactly one orchestrated run lifecycle | Unit, integration |
| AC-002 | Missing required event fields fail safely | Missing `client_id`, `audit_id`, `scenario_type`, or `triggered_by` returns structured validation failure and no outbound request | Unit, integration |
| AC-002A | Safe supplied `run_id` used unchanged | Valid supplied `run_id` appears unchanged in response, raw results, S3 key, DynamoDB SK, and sanitized logs | Unit, integration |
| AC-002B | Absent `run_id` generates UUIDv4 | Generated UUIDv4 matches allowlist and is used consistently across outputs | Unit, integration |
| AC-002C | Unsafe supplied `run_id` rejected | Empty, short, long, slash, backslash, dot/traversal, whitespace, control char, URL-encoded traversal, and injection values fail before side effects and raw value is not logged | Unit, integration, security |
| AC-002D | Invalid `run_id` is not normalized | Values requiring trim/decode/replace/remove are rejected as received | Unit, security |
| AC-002E | Invalid supplied `run_id` does not trigger generation | Validation error occurs and no replacement UUID is produced | Unit, integration |
| AC-002F | Duplicate `run_id` fails before raw evidence write | Existing S3 object or DynamoDB metadata returns `DUPLICATE_RUN_ID`; no overwrite/append/merge | Unit, integration |
| AC-002G | Duplicate is not endpoint failure classification | `DUPLICATE_RUN_ID` appears only as run-level/control error and never in endpoint `failure_type` enum/results | Unit, integration |
| AC-003 | Configs loaded from exact S3 keys | Client, audit, and endpoint configs read from exact required paths | Unit, integration |
| AC-004 | Missing config fails safely | Missing/unreadable configs produce structured failure and no endpoint request | Unit, integration |
| AC-005 | Invalid JSON config fails safely | Invalid JSON produces structured failure and no endpoint request | Unit, integration |
| AC-006 | Config metadata queryable | DynamoDB metadata access supports client/audit lookup without scanning raw result S3 objects | Unit, integration |
| AC-007 | Secrets resolved only from Secrets Manager | Secret references are resolved via Secrets Manager mock; literal secrets in configs are rejected in secret-bearing fields | Unit, integration, security |
| AC-008 | Secret resolution failure sanitized | Missing/denied/invalid secret ref fails without leaking secret ref values or resolved values | Unit, integration, security |
| AC-009 | Runner executes configured HTTP request | Method, URL, headers, payload, timeout, and retries match endpoint config | Unit, integration |
| AC-010 | Timing excludes non-request overhead | `duration_ms` timer wraps only outbound request call boundary | Unit |
| AC-011 | Timing uses monotonic clock | Runner uses monotonic source, not wall-clock subtraction | Unit/static review |
| AC-012 | Retry attempts recorded | `retry_attempts` equals retries after initial attempt and final classification remains accurate | Unit, integration |
| AC-013 | Failure type is approved | All endpoint outcomes use exactly one approved failure classification | Unit, integration/schema |
| AC-014 | Successful execution records PASS | 2xx/expected status and assertions pass => `PASS` plus status code | Unit, integration |
| AC-015 | HTTP error classification | Configured HTTP error/mismatch maps to `HTTP_ERROR` unless specific assertion failure applies | Unit, integration |
| AC-016 | Timeout classification | Request timeout maps to `TIMEOUT` with `duration_ms` present | Unit, integration |
| AC-017 | Connection error classification | DNS/TLS/refused/network failure maps to `CONNECTION_ERROR` | Unit, integration |
| AC-018 | Invalid response classification | Malformed/unparseable expected JSON maps to `INVALID_RESPONSE` | Unit, integration |
| AC-019 | Payload validation classification | Invalid payload maps to `PAYLOAD_VALIDATION_ERROR` and sends no outbound request | Unit, integration |
| AC-020 | Runner error classification | Unexpected runner exception maps to sanitized `RUNNER_ERROR` | Unit |
| AC-021 | Raw Result v1 required fields | Every record contains required fields with `raw_result_version = "v1"` and null-safe values | Unit, integration/schema |
| AC-022 | Raw results stored at required S3 path | One sanitized `results.json` object written at exact raw result key at run completion | Unit, integration |
| AC-023 | DynamoDB metadata uses required keys | Metadata uses exact `PK` and `SK` format from validated/generated identifiers | Unit, integration |
| AC-024 | Metadata locates raw results | Metadata includes corresponding raw result S3 key when available | Unit, integration |
| AC-025 | Sanitization before raw result persistence | Secrets/PII/sensitive headers/payloads/query params redacted in S3 object | Unit, integration, security |
| AC-026 | Sanitization before metadata persistence | Metadata contains no secrets, credentials, PII, or sensitive values | Unit, integration, security |
| AC-027 | Sanitization before logging | All log entries are sanitized before emission | Unit, integration, security |
| AC-028 | Log categories explicit | Relevant logs include `log_category` with only approved values | Unit, integration |
| AC-029 | Client-safe logs exclude internals/sensitive data | `client_safe_logs` exclude stack traces, internals, credentials, PII, and sensitive payloads | Unit, integration, security |
| AC-030 | Phase 1 excludes frontend/account features | Repository/branch review confirms no frontend/dashboard/auth/RBAC/billing/account features | Static review |
| AC-031 | Phase 1 excludes deferred intelligence/testing products | Repository/branch review confirms no AI/scoring/advanced observability/report product/load/uptime/chaos behavior | Static review |

## 3. Test Scenarios

### 3.1 Unit Test Expectations

Unit tests must be isolated, deterministic, and not require live AWS credentials or live external APIs.

#### Schemas, constants, and validators

- Validate approved constants only:
  - `raw_result_version` is exactly `"v1"`.
  - statuses are only `STARTED`, `COMPLETED`, `FAILED`.
  - endpoint failure classifications are only the approved eight values.
  - `DUPLICATE_RUN_ID` is defined as control/orchestration error and excluded from endpoint `failure_type` enum.
- Validate orchestrator event schema:
  - accepts required non-empty string fields.
  - rejects missing, null, empty, or non-string required fields.
  - rejects invalid identifiers before config load or outbound execution.
- Validate Raw Result Schema v1:
  - requires `raw_result_version`, `client_id`, `audit_id`, `run_id`, `endpoint_id`, `scenario_type`, `method`, `url`, `status_code`, `duration_ms`, `failure_type`, `payload_strategy`, `timestamp`, and `retry_attempts`.
  - allows documented null-safe values only where expected.
  - rejects unapproved `failure_type` values and incorrect raw result versions.
- Validate metadata schema:
  - exact key construction: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
  - statuses restricted to Phase 1 values.
  - raw result locator field matches required S3 key.

#### Run identity validation

- Accepted supplied `run_id` examples:
  - `release_2026-01`
  - `RUN-12345678`
  - minimum 8-character valid value
  - maximum 80-character valid value
- Rejected supplied `run_id` examples:
  - empty string, null, non-string
  - fewer than 8 characters
  - more than 80 characters
  - `/`, `\`, `.`, `..`, `../`, `..\`
  - `%2e`, `%2E`, `%2e%2e`, `%2f`, `%2F`, `%5c`, `%5C`
  - leading/trailing/internal whitespace, tabs, newlines, carriage returns
  - control characters
  - shell/log/key injection characters such as `;`, `|`, `&`, `$`, `` ` ``, `<`, `>`, `"`, `'`, `:`, `=`, `?`, `#`, `{}`, `[]`
  - values that would become valid only after trimming, decoding, replacing, or removing unsafe characters
- Validation assertions:
  - invalid supplied values return structured `INVALID_RUN_ID` or equivalent validation failure.
  - invalid supplied values are not normalized.
  - invalid supplied values do not trigger UUID generation.
  - invalid supplied values are not used in S3 paths, DynamoDB keys, raw results, metadata, logs, or responses.
  - absent `run_id` generates UUIDv4 satisfying the allowlist and uses the same value everywhere.

#### Sanitizer

- Redacts sensitive values as `"[REDACTED]"` in nested dictionaries, lists, strings, headers, payloads, URLs, errors, metadata, raw results, and log payloads.
- Required redaction coverage:
  - Authorization headers
  - cookies and set-cookie
  - API keys, tokens, secrets, passwords, client secrets
  - emails and phone numbers
  - sensitive query parameter values
  - nested sensitive payload fields
- Handles unexpected data types and deeply nested objects without leaking; if sanitization fails, behavior must fail closed.
- Does not attempt to make unsafe `run_id` values path/key safe; run identity validation remains separate.

#### Runner and assertion evaluator

- Uses `requests` for HTTP execution.
- Sends configured method, URL, headers, payload/body, timeout.
- Applies retry behavior deterministically:
  - default retries `0`.
  - max retries `3`.
  - `retry_attempts` counts retries after the initial attempt.
  - final classification reflects final outcome.
- Enforces timeout limits:
  - default timeout `10` seconds.
  - max timeout `30` seconds.
  - invalid timeout fails validation before request.
- Uses monotonic clocks around outbound request boundary only.
- Maps outcomes:
  - success + assertions pass => `PASS`.
  - status/required field assertion failure => `ASSERTION_FAILURE` where applicable.
  - HTTP error expectation => `HTTP_ERROR`.
  - timeout exception => `TIMEOUT` with `duration_ms`.
  - network exception => `CONNECTION_ERROR`.
  - expected JSON invalid/malformed => `INVALID_RESPONSE`.
  - invalid payload before send => `PAYLOAD_VALIDATION_ERROR` with no outbound request.
  - unexpected exception => `RUNNER_ERROR` with sanitized result/error.

#### Config loaders and validators

- Client config loader reads exactly `configs/{client_id}/client_config.json`.
- Audit config loader reads exactly `configs/{client_id}/audits/{audit_id}/audit_config.json`.
- Endpoint config loader reads exactly `configs/{client_id}/audits/{audit_id}/endpoints.json`.
- Missing, denied/unreadable, or invalid JSON configs produce structured failures before outbound requests.
- Config schema validation covers consumed fields only but must reject unsafe methods, missing/malformed URLs, unsupported schemes, invalid payloads, invalid timeout/retry settings, unsupported assertions, and literal secrets in secret-bearing fields.
- Loaders preserve secret references and do not resolve secrets.

#### Storage clients and duplicate detection

- S3 raw result key generation uses only validated/generated identifiers and exactly matches `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- DynamoDB keys use only validated/generated identifiers and exactly match `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Duplicate detection:
  - existing S3 raw result object returns/raises controlled `DUPLICATE_RUN_ID`.
  - existing DynamoDB metadata item returns/raises controlled `DUPLICATE_RUN_ID`.
  - both existing still produce controlled `DUPLICATE_RUN_ID`.
  - no overwrite, append, merge, or endpoint execution occurs after duplicate detection.
  - conditional write behavior protects against race where practical.
- Persistence payloads are sanitized before writes.
- Raw evidence is written once at run completion, not incrementally or to multiple objects.

#### Logging

- Every relevant structured log includes `log_category` with only `internal_operational_logs` or `client_safe_logs`.
- Logs are sanitized before emission.
- Invalid `run_id` logs include safe reason code only, never raw rejected value.
- Duplicate logs use `DUPLICATE_RUN_ID` and may include validated canonical identifiers only.
- `client_safe_logs` exclude stack traces, implementation internals, secrets, credentials, PII, and sensitive payloads.

### 3.2 Integration Test Expectations

Integration tests must use mocked AWS clients/fakes and a local mock API. They must not require live AWS resources.

#### Happy path orchestration

- Arrange mocked S3 configs at exact required keys, DynamoDB metadata availability, Secrets Manager responses, and a local mock API success endpoint.
- Invoke the Lambda handler/orchestrator with valid event and either supplied safe `run_id` or absent `run_id`.
- Assert:
  - duplicate checks occur before config load/execution/persistence.
  - configs are loaded from exact keys.
  - secrets resolve only via Secrets Manager mock.
  - local mock API receives expected method, headers, payload, and timeout behavior.
  - raw result envelope is written once to exact S3 key.
  - each result record includes required Raw Result Schema v1 fields.
  - DynamoDB metadata transitions through allowed Phase 1 statuses and includes required keys/raw result locator.
  - logs are categorized and sanitized.

#### Failure path orchestration

- Missing required event field: no config load, secret resolution, metadata write, raw result write, or outbound request.
- Invalid supplied `run_id`: no generated replacement and no side effects; logs/responses do not include raw rejected value.
- Existing S3 raw result object: controlled `DUPLICATE_RUN_ID`; no metadata overwrite, no config load, no endpoint request, no raw evidence write.
- Existing DynamoDB metadata: controlled `DUPLICATE_RUN_ID`; no overwrite/update, no config load, no endpoint request, no raw evidence write.
- Missing/unreadable/invalid JSON config: structured failure and no outbound request.
- Secret resolution failure: structured sanitized failure; no secret values in logs/metadata/raw results.
- S3 persistence failure after endpoint execution: metadata status `FAILED` where possible and sanitized failure logs.
- DynamoDB terminal update failure after S3 success: sanitized operational error, S3 evidence preserved.

#### Local mock API endpoint outcomes

- `PASS`: expected status and assertions pass.
- `HTTP_ERROR`: 4xx/5xx or status classified as error by expectations.
- `TIMEOUT`: mock endpoint delays beyond configured timeout.
- `CONNECTION_ERROR`: connect to unavailable local port or simulated connection exception.
- `INVALID_RESPONSE`: mock returns malformed JSON when JSON is expected.
- `ASSERTION_FAILURE`: mock returns valid response missing required field or unexpected status per assertion rules.
- `PAYLOAD_VALIDATION_ERROR`: invalid request payload blocks outbound request.
- Retry behavior: transient failure followed by final outcome; assert `retry_attempts` and final classification.

### 3.3 Negative Tests Required

- Secrets leakage:
  - literal secret in secret-bearing config rejected.
  - resolved secret never appears in raw results, metadata, logs, exceptions, or responses.
  - sensitive values redacted as `"[REDACTED]"`.
- Invalid `run_id`:
  - path traversal, URL-encoded traversal, whitespace/control characters, shell/log/key injection, empty, too short, too long, non-string.
  - verify no normalization, no replacement generation, no side effects, no raw rejected value in logs/errors.
- Duplicate `run_id`:
  - S3 duplicate, DynamoDB duplicate, and both duplicate.
  - verify `DUPLICATE_RUN_ID` is not an endpoint `failure_type` and no overwrite/append/merge occurs.
- Timeout:
  - endpoint timeout maps to `TIMEOUT` with duration present and sanitized output.
- Connection error:
  - network/connect failure maps to `CONNECTION_ERROR`.
- Invalid JSON:
  - invalid config JSON fails before outbound request.
  - invalid response JSON when JSON expected maps to `INVALID_RESPONSE`.
- Assertion failure:
  - expected status/required field mismatch maps to `ASSERTION_FAILURE` or `HTTP_ERROR` according to configured precedence.

## 4. Edge Cases

- Boundary run_id lengths: exactly 8 and exactly 80 accepted; 7 and 81 rejected.
- Valid run_id characters: uppercase, lowercase, digits, underscore, hyphen.
- Unsafe run_id variants requiring no normalization: leading/trailing spaces, decoded traversal candidates, mixed-case encoded traversal, embedded newline/log injection text.
- Multiple endpoints where one endpoint fails and others are executable; endpoint-level failures should not prevent remaining endpoints unless a global dependency/safety failure occurs.
- Endpoint with no response body.
- Endpoint with unsupported HTTP method.
- Endpoint URL missing, malformed, or unsupported scheme.
- Retry config omitted, zero, max allowed, and above max.
- Timeout omitted, max allowed, and above max.
- Duration for no-response failures where status code is `null`.
- Sanitization of nested arrays/objects and unexpected scalar/object types.
- Logs emitted during exception handling.
- Duplicate discovered at initial pre-run check and at final pre-write guard.
- Partial persistence failure: S3 success followed by DynamoDB failure; DynamoDB failure before S3 write; S3 failure after endpoint execution.
- Phase boundary review for accidental addition of out-of-scope directories/dependencies/features.

## 5. Test Types Covered

- **Unit tests:** schemas, validators, run identity, sanitizer, config loaders, config validators, secret reference handling, runner classification/timing/retry behavior, raw result builder, metadata builder, storage key generation, duplicate detection, logging wrappers.
- **Integration tests:** orchestrator/handler with mocked AWS clients, fake S3/DynamoDB/Secrets Manager, local mock API, raw evidence persistence, metadata lifecycle, log capture.
- **Security tests:** run_id injection/path traversal prevention, secret/PII redaction, literal secret rejection, no raw invalid run_id logging, client-safe log restrictions.
- **Regression tests:** existing Phase 0 validation commands, repository structure checks, no out-of-scope Phase 1 additions.
- **Static/code review checks:** monotonic clock usage, `requests` usage, no heavy API framework, no live AWS dependency in tests, Phase 1 boundary enforcement.

Performance/load testing is not in Phase 1 scope. Timing tests are correctness tests for monotonic outbound-request measurement, not load or benchmark tests.

## 6. Coverage Justification

The planned coverage maps every Phase 1 acceptance criterion to at least one test or static review activity. Unit tests provide deterministic validation for individual contracts and failure classification. Integration tests prove cross-component behavior from Lambda event through mocked AWS clients and local HTTP execution. Security-focused negative tests protect the highest-risk boundaries: unsafe `run_id` usage, duplicate immutable evidence identity, secret leakage, sanitization, and log category separation. Regression/static checks protect Phase 0 foundation behavior and confirm the branch remains Phase 1 only.

QA approval will not be granted unless evidence demonstrates:

- all critical ACs are covered by automated tests or explicit reviewed evidence;
- all required validation commands pass;
- raw result, metadata, and logs are sanitized;
- duplicate detection prevents evidence mutation;
- endpoint failure classifications are restricted to the approved set;
- no blocking defects or unresolved failures remain.

## 7. Required Validation Commands

Exact command names may be adjusted only to match the repository tooling once implementation is present. QA report must record the final commands, timestamps, and full outputs.

Required local validation command set:

```bash
python --version
python -m pytest tests/unit
python -m pytest tests/integration
python -m pytest tests/security
python -m pytest
```

If the project uses Make/Nox/Tox/Poetry commands, execute the equivalent project-standard commands in addition to raw `pytest`, for example:

```bash
make test
make lint
make typecheck
```

Static/review validation required in QA report:

- Search/review confirms runner uses `requests` and monotonic clock source.
- Search/review confirms endpoint `failure_type` enum excludes `DUPLICATE_RUN_ID`.
- Search/review confirms `raw_result_version` is consistently `"v1"`.
- Search/review confirms no frontend/auth/billing/AI/reporting/load/uptime/chaos/heavy framework implementation was introduced for Phase 1.
- Search/review confirms tests use mocked AWS clients/local mock API, not live AWS credentials.

## 8. Security/Sanitization/Logging Checklist

QA must verify each item below before sign-off:

- [ ] Unsafe supplied `run_id` values are rejected before S3 key, DynamoDB key, raw result, metadata, response, or log construction.
- [ ] Invalid supplied `run_id` is not normalized, decoded, trimmed, repaired, hashed, replaced, or converted to a generated UUID.
- [ ] Raw rejected `run_id` values do not appear in captured logs, responses, exceptions, metadata, or raw results.
- [ ] Duplicate valid `run_id` returns controlled `DUPLICATE_RUN_ID` without overwrite, append, merge, endpoint execution, or endpoint failure classification.
- [ ] Configs contain only secret references in secret-bearing fields.
- [ ] Resolved secrets come only from Secrets Manager mock/client.
- [ ] Resolved secret values never appear in S3 raw results, DynamoDB metadata, logs, exceptions, test reports, or fixtures.
- [ ] Sanitizer redacts with exact token `"[REDACTED]"`.
- [ ] Authorization, cookies, API keys, passwords, tokens, emails, phone numbers, PII, nested sensitive payload fields, and sensitive URL query params are redacted.
- [ ] Raw result persistence payload is sanitized before write.
- [ ] Metadata persistence payload is sanitized before write.
- [ ] All log entries include explicit `log_category`.
- [ ] `log_category` values are limited to `internal_operational_logs` and `client_safe_logs`.
- [ ] `client_safe_logs` contain no stack traces, internals, secrets, credentials, PII, or sensitive payload values.
- [ ] Exception-handling paths are sanitized and categorized.

## 9. Evidence Required in QA Report

The Phase 1 QA report must be created or updated at `docs/qa/phase_1_core_engine_foundation_test_report.md` after implementation/tests are available. It must include:

- Test execution summary with total, passed, failed, skipped, and xfailed counts.
- Full validation command outputs or links/paths to captured logs.
- Per-test or per-suite outcome mapped to acceptance criteria.
- Evidence from mocked AWS interactions:
  - S3 config keys requested.
  - S3 raw result key written.
  - duplicate S3 object checks.
  - DynamoDB keys and status writes.
  - duplicate metadata checks.
  - Secrets Manager calls for secret refs.
- Captured local mock API request evidence for method, headers, payload, retry behavior, timeout behavior, and no-request validation cases.
- Raw Result Schema v1 sample evidence showing required fields and `raw_result_version = "v1"`.
- Sanitized raw result, metadata, and log excerpts proving sensitive values are replaced by `"[REDACTED]"`.
- Invalid `run_id` evidence proving raw rejected values are not logged and no side effects occur.
- Duplicate `run_id` evidence proving no overwrite, append, merge, or endpoint `failure_type` pollution.
- Static review evidence for monotonic timing, `requests` usage, approved failure/status enums, and Phase 1 scope boundaries.
- Failure analysis for any failed/flaky/skipped test, including classification as Application Bug, Test Bug, Environment Issue, or Flaky Test, with root cause hypothesis, reproduction steps, and impact severity.

## 10. Sign-Off Criteria

QA sign-off is approved only if all of the following are true:

- All critical Phase 1 acceptance criteria pass with evidence.
- Required unit, integration, security, and regression validations pass.
- No blocking or high-severity defects remain open.
- No unresolved test failures, unexplained skips, or unclassified flaky tests remain.
- No endpoint raw result contains unapproved `failure_type` values.
- `DUPLICATE_RUN_ID` is verified as a run-level/control error and not endpoint `failure_type`.
- Invalid supplied `run_id` behavior is proven safe: reject only, no normalization, no replacement generation, no side effects, no raw rejected value logged.
- Duplicate detection is proven safe for existing S3 object and existing DynamoDB item with no overwrite/append/merge.
- Raw results and metadata use exact required paths/keys and are sanitized.
- Logs are categorized and sanitized, with `client_safe_logs` free of internals and sensitive data.
- Branch review confirms no out-of-scope Phase 1 features or heavy frameworks were introduced.
- QA report contains adequate execution output and artifacts to support the decision.

If any sign-off criterion is not satisfied, QA decision must be **not approved**, with issues escalated in the test report.

## 11. Risks and Open Questions

### Risks

- Exact implementation file paths and test command wrappers may vary from the technical design; QA will adapt commands without reducing coverage.
- Config schema beyond minimum executable fields remains partly implementation-defined; QA must validate whatever consumed schema is documented by backend implementation.
- Duplicate `run_id` race protection depends on conditional write/non-overwrite semantics available in storage abstractions; QA must verify mocked behavior and review implementation safeguards.
- Aggregate run status semantics for endpoint failures are not fully product-defined; technical design recommends `COMPLETED` when execution completed and raw evidence persisted, with endpoint failures represented in results.
- Partial persistence failure behavior may be difficult to assert without well-designed storage mocks; QA must require deterministic mock hooks for S3/DynamoDB failure injection.

### Open Questions

- Should a run with one or more endpoint-level failures but successful raw evidence persistence be marked `COMPLETED` or `FAILED` in metadata? Technical design recommends `COMPLETED` for completed execution with endpoint failures captured in results.
- What exact config metadata item shape is required beyond client/audit queryability?
- Will implementation expose a stable local command for running only Phase 1 tests, or should QA use direct `pytest` suite paths?
