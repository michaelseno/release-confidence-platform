# Test Plan

## 1. Feature Overview

Phase 2 adds backend-only payload preparation to the Phase 1 execution engine. QA validation will verify deterministic payload strategies, data-pool loading and mapping, duplicate prevention, endpoint safety controls, fingerprint canonicalization, and safe raw result metadata while preserving `raw_result_version = "v1"`.

Confirmed Phase 2 endpoint configuration fields are `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and nested `payload_safety` with `allow_generated_payloads`, `allow_data_pool_reuse`, `destructive_operation`, and `allow_destructive_operation`.

Scope is limited to branch `feature/phase_2_payload_data_generation` and the upstream artifacts:

- Product spec: `docs/product/phase_2_payload_data_generation_product_spec.md`
- Technical design: `docs/architecture/phase_2_payload_data_generation_technical_design.md`

Out of scope for this QA plan: frontend, Phase 3 scheduling/lifecycle behavior, auth/RBAC, billing, AI insights, dashboards, reporting, load testing, chaos testing, and audit-wide duplicate tracking. Phase 2 duplicate reservation is confirmed as an in-memory tracker scoped to a single orchestrator run.

## 2. Acceptance Criteria Mapping

| AC | Requirement | Planned validation |
| --- | --- | --- |
| AC-001 | Static strategy pass-through | Unit and integration tests confirm valid static payload is sent unchanged after validation. |
| AC-002 | Static rejects dynamic tokens | Unit and integration negative tests assert `PAYLOAD_VALIDATION_ERROR` and no outbound request. |
| AC-003 | Generated replaces supported variables | Unit tests verify `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, `{{uuid}}`; integration verifies final request reaches mock API with resolved values. |
| AC-004 | Generated rejects unknown variables | Unit/integration tests for `{{random}}` and malformed tokens fail before outbound execution. |
| AC-005 | Run-level timestamp reuse | Orchestrator/generator tests verify one timestamp reused across endpoints and iterations in same run. |
| AC-006 | Deterministic UUID generation | Unit tests repeat same context and assert identical UUID output. |
| AC-007 | UUID field path differentiation | Unit tests assert different field paths produce different deterministic UUIDs. |
| AC-007A | Repeated UUID tokens in same field | Unit tests assert left-to-right zero-based `token_index` creates distinct UUIDs in one string field. |
| AC-007B | Repeated UUID tokens stable | Unit tests rerun same template/context and assert each token position is stable. |
| AC-008 | Data-pool load path | DataPoolLoader unit tests verify exact key `data-pools/{client_id}/{pool_name}.json`. |
| AC-009 | Data-pool missing file | Unit/integration tests simulate missing object and assert `PAYLOAD_VALIDATION_ERROR`, no request. |
| AC-010 | Deterministic data-pool assignment | Unit tests verify stable assignment by hash tuple modulo pool size. |
| AC-010A | Data-pool full-payload default | Unit/integration tests confirm selected record is full request payload when no template exists. |
| AC-010B | Data-pool template substitution | Unit/integration tests confirm selected record fields populate configured template. |
| AC-010C | Data-pool template substitution failure | Negative tests for missing record field/unresolved substitution fail pre-request. |
| AC-011 | Regenerate duplicate policy | Duplicate checker/generator tests force first duplicate and assert deterministic retry attempts. |
| AC-012 | Regenerate exhaustion | Tests force duplicates for attempts 1-5 and assert `PAYLOAD_VALIDATION_ERROR`, no request. |
| AC-013 | Fail-fast duplicate policy | Tests assert first duplicate fails with `PAYLOAD_VALIDATION_ERROR`, no request. |
| AC-014 | Allow duplicate policy | Tests assert request proceeds when a duplicate is detected under `duplicate_policy = "allow"` and metadata has `duplicate_detected = true`, `duplicate_policy = "allow"`, and `duplicate_allowed = true`. Tests also assert `duplicate_allowed = false` is preferred when no duplicate was detected. |
| AC-015 | Default duplicate policy | Unit tests assert omitted policy resolves to `regenerate`. |
| AC-016 | Default duplicate scope | Unit tests assert omitted scope resolves to `current_run`. |
| AC-017 | Payload fingerprint canonicalization | Fingerprint unit tests assert equivalent JSON with different key order has identical SHA-256 and absent/no-body payload fingerprints use SHA-256 of canonical string `EMPTY_PAYLOAD`. |
| AC-018 | Response fingerprint canonicalization | Unit/integration tests assert equivalent response JSON key order has identical SHA-256. |
| AC-019 | Generated payload safety block | Validator tests assert generated strategy fails unless `allow_generated_payloads = true`. |
| AC-020 | Data-pool reuse safety block | Duplicate/data-pool tests assert reuse applies configured duplicate policy when reuse is not allowed. |
| AC-021 | Destructive default block | Validator/integration tests assert destructive endpoint with omitted allow fails closed. |
| AC-021A | Destructive non-true allow block | Tests cover false, null, string, and other non-true values failing closed. |
| AC-022 | Destructive explicit allow | Positive test confirms destructive endpoint may proceed only with explicit boolean `true` and all other checks passing. |
| AC-023 | Concurrency duplicate safety | Unit/concurrency tests assert in-memory check/reserve prevents duplicate fingerprints under prohibited policies within one orchestrator run using a scope key containing `client_id + audit_id + run_id` for `current_run`. |
| AC-024 | Raw metadata for generated payload | Integration/raw result builder tests verify top-level `payload_strategy` and nested generated metadata fields. |
| AC-025 | Raw metadata for data-pool payload | Integration/raw result builder tests verify pool name and record fingerprint, with no raw record values. |
| AC-026 | Raw result schema version preserved | Raw result tests assert `raw_result_version = "v1"`. |
| AC-027 | Raw metadata does not expose unsafe values | Security tests inspect raw results/log capture for secrets, tokens, cookies, credentials, PII, generated UUIDs where unsafe. |
| AC-028 | Data-pool record fingerprint hides raw record | Tests assert stored value is SHA-256 hex and raw record fields/values are absent. |
| AC-029 | Duplicate metadata reflects outcome | Tests assert scope, policy, duplicate flag, allow flag where applicable, and final generation attempt match duplicate handling path. |

## 3. Test Scenarios

### Unit Test Expectations

Planned unit test locations: `tests/api/` for backend/API-adjacent behavior and lower-level Python test modules under the repository's existing test layout if implementation uses `tests/unit/`. No UI tests are required because Phase 2 is backend-only.

#### Payload generator / preparation service

- Static strategy returns payload unchanged and validates empty/no-body behavior.
- Generated strategy resolves all supported variables deterministically.
- Initial iteration defaults to `1` when omitted by Phase 1 runner, if implemented as designed.
- HTTP retry path reuses one prepared payload and does not regenerate.
- Regeneration attempt salt changes eligible generated values while preserving deterministic replay for the same attempt.

#### Template resolver

- Detect exact supported tokens: `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, `{{uuid}}`.
- Reject unknown and malformed tokens, including nested braces, partial braces, whitespace variants if unsupported, and unsupported `{{random}}`.
- Resolve field paths for objects, arrays, root strings, keys requiring bracket notation, and strings containing multiple tokens.
- Verify same-field repeated `{{uuid}}` uses zero-based left-to-right `token_index`, resets per field path, and ignores non-UUID tokens for UUID token indexing.
- For data-pool templates, resolve top-level and nested record fields while keeping reserved Phase 2 tokens reserved.

#### Validators

- Reject invalid or missing `payload_strategy` when a body is required.
- Resolve omitted strategy to `static` only for safe static/no-body cases.
- Reject Phase 2 tokens in static payloads.
- Validate payload/body type versus method/content type.
- Validate duplicate policy/scope allowlists and defaults using confirmed endpoint config field names: `duplicate_policy` and `duplicate_check_scope`.
- Enforce generated payload opt-in and destructive-operation fail-closed behavior.
- Reject unsupported future duplicate scope unless safely implemented and documented.

#### Duplicate checker

- Default policy `regenerate`; default scope `current_run`.
- In-run reservation uses an in-memory tracker per orchestrator run; for `current_run`, the duplicate scope key must include `client_id + audit_id + run_id`.
- Audit-wide duplicate tracking is out of scope and must not be assumed for sign-off.
- `regenerate` retries through max 5 attempts and fails on exhaustion.
- `fail_fast` fails on first duplicate.
- `allow` proceeds and records `duplicate_allowed = true` only when a duplicate was detected and allowed; when no duplicate is detected, `duplicate_allowed = false` is the preferred expected metadata value.
- Atomic check/reserve under concurrent threads/tasks prevents two prohibited duplicates from proceeding.
- Separate subject types for final payload fingerprint and data-pool record fingerprint are enforced.

#### Data-pool loader and mapper

- Builds exact S3/object key `data-pools/{client_id}/{pool_name}.json`.
- Rejects unsafe `pool_name`: empty, slashes, backslashes, dots/traversal, URL-encoded traversal-like values, whitespace, control characters.
- Handles missing, unreadable, malformed, empty, empty records, and non-object records as `PAYLOAD_VALIDATION_ERROR`.
- Accepts both supported data-pool schema shapes: a plain list of object records and a wrapped object containing `{ "records": [...] }`.
- Caches by `(client_id, pool_name)` within a run without leaking records to logs.
- Deterministically selects record using `hash(client_id, audit_id, run_id, endpoint_id, scenario_type, iteration) % pool_size`.
- Uses selected record as full payload by default and as substitution source when a template is configured.

#### Fingerprint canonicalization

- SHA-256 lowercase hex output for payload, response, and data-pool record fingerprints.
- Absent/no-body payload fingerprint is SHA-256 of canonical string `EMPTY_PAYLOAD`.
- Sanitization occurs before canonicalization and hashing.
- Equivalent JSON with different key order has the same fingerprint.
- Arrays preserve order; strings/non-JSON bodies use string canonicalization; null/empty explicit behavior matches the technical design.
- Binary-like or unsafe values are sanitized/placeholdered before fingerprinting or fail closed as specified.

#### Safety controls

- Generated strategy blocked unless `payload_safety.allow_generated_payloads` is exactly true.
- Destructive operation is indicated by `payload_safety.destructive_operation` and blocked unless `payload_safety.allow_destructive_operation` is exactly boolean true; omitted defaults to false.
- Data-pool reuse blocked or policy-applied when `payload_safety.allow_data_pool_reuse` is not true.
- Ambiguous safety config fails closed.

#### Raw result metadata builder

- Top-level `payload_strategy` is present and strict.
- Phase 2 fields are nested under `payload_metadata`; no duplicate top-level Phase 2 fields are emitted except allowed `payload_strategy` and `response_fingerprint`.
- Required metadata fields are present with correct values: `payload_fingerprint`, `duplicate_check_scope`, `duplicate_detected`, `duplicate_policy`, `generation_attempt`, `data_pool_name`, `data_pool_record_fingerprint`, and `duplicate_allowed`. `duplicate_allowed` must be true only when a duplicate was detected and allowed; false is preferred when no duplicate was detected.
- `raw_result_version` remains `v1`.
- Metadata contains only safe values and fingerprints, never raw payload, data-pool record contents, secrets, tokens, credentials, cookies, or PII.

### Integration Expectations

Planned integration tests should use the Phase 1 orchestrator/runner with mocked AWS dependencies and a local mock API server. No real AWS resources should be mutated.

- Successful static endpoint execution writes raw result metadata and preserves Phase 1 behavior.
- Successful generated endpoint execution sends resolved payload to mock API, records payload and response fingerprints, and writes safe metadata.
- Successful data-pool execution loads mocked S3 object from `data-pools/{client_id}/{pool_name}.json`, supports both plain-list and `{ "records": [...] }` wrapped data-pool schemas, supports full-payload and template modes, and records safe metadata.
- Validation failures (`PAYLOAD_VALIDATION_ERROR`) do not send outbound requests; mock API request count remains zero for the failed endpoint.
- Duplicate policies are exercised through orchestrator/runner path, not only unit tests.
- HTTP retry behavior, if available in Phase 1 runner, reuses the same prepared payload and metadata across retries.
- Raw result persistence path remains Phase 1-compatible and schema version remains `v1`.
- Response fingerprint is generated from sanitized canonical response evidence for JSON and non-JSON responses.

### Mocking / Fixtures

- Mock S3/data-pool storage with safe and malicious fixture pools.
- Do not mock DynamoDB for duplicate tracking unless future implementation explicitly adds audit-wide scope; Phase 2 sign-off validates in-memory current-run tracking only.
- Mock Secrets Manager/secret resolution when verifying secret leakage boundaries.
- Mock/local API should capture exact outbound body count and return deterministic JSON/non-JSON responses.
- Log capture should be enabled for leakage assertions.

## 4. Edge Cases

- Static no-body endpoint and explicit empty string/null payload fingerprint behavior; absent/no-body must hash canonical string `EMPTY_PAYLOAD`.
- Static payload containing `{{run_id}}` or other `{{...}}` token syntax.
- Generated payload with unknown, malformed, adjacent, nested, repeated, and path-sensitive tokens.
- Repeated same-field UUID tokens with stable `token_index` values.
- Duplicate regeneration where generated payload changes by attempt and where it cannot change.
- Data pool size 1 with reuse disallowed and `regenerate` or `fail_fast` policy.
- Missing `data_pool_name`, unsafe path traversal pool name, malformed JSON, empty plain list, empty `records` wrapper, non-object record, and unsupported wrapper shape other than `{ "records": [...] }`.
- Data-pool template references missing nested field or reserved-name conflict.
- Data-pool selected record contains secrets/PII and must not appear in metadata/logs.
- Equivalent JSON payload/response ordering, arrays with different ordering, strings, null, empty body, malformed JSON response, and binary-like response.
- `payload_safety.destructive_operation = true` with omitted, false, null, string `"true"`, numeric `1`, or any non-boolean-true allow value.
- Concurrent duplicate reservations within one run.
- Unsupported/future duplicate scope for same client/audit across all runs remains out of scope; current-run duplicate tracking must be isolated by `client_id + audit_id + run_id`.

## 5. Test Types Covered

- Functional: strategy resolution, generated substitutions, data-pool mapping, duplicate policies, raw metadata.
- Negative: invalid strategies, invalid variables, invalid payload structures, invalid data pools, unsafe config, unsupported duplicate scopes, fingerprint/sanitization failures.
- Edge: boundaries listed above including repeated UUID token indexing, empty bodies, one-record pools, and concurrency.
- Integration: Phase 1 orchestrator/runner, mocked AWS/local mock API, raw result persistence shape.
- Security/sanitization/logging: metadata and logs inspected for absence of unsafe values.
- Regression: Phase 1 validation, run ID behavior, raw result v1 compatibility, existing runner retry and no-body/static behavior.

## 6. Coverage Justification

The planned coverage maps every product acceptance criterion AC-001 through AC-029 to at least one unit or integration test. Low-level deterministic rules are covered with pure unit tests to isolate repeatability, canonicalization, and validation. Runner/orchestrator integration tests prove the feature is wired into Phase 1 boundaries and that validation failures block outbound requests. Security and logging checks protect the core Phase 2 trust requirement: payload values may be used in memory for outbound execution but must not be persisted or logged unsafely.

### Required Validation Commands

Run from repository root unless noted. Capture full command output in the QA report.

```bash
python --version
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m pytest tests/api
python scripts/validate_config.py --samples-dir configs/samples
```

If integration tests are added under `tests/integration/`, also run:

```bash
python -m pytest tests/integration
```

If infrastructure/package validation is impacted, run local-only package validation:

```bash
cd infra
npm install
npx serverless package --stage dev
```

No command may deploy or mutate real AWS resources during QA validation.

### Security / Sanitization / Logging Checklist

- [ ] Raw results do not contain raw generated payload values, raw data-pool records, secrets, tokens, credentials, cookies, PII, or sensitive values in `payload_metadata`.
- [ ] Logs do not contain raw payloads, selected records, generated UUID values where unsafe, resolved secrets, tokens, credentials, cookies, or PII.
- [ ] Fingerprints are SHA-256 lowercase hex values over sanitized canonical representations.
- [ ] Sanitization occurs before canonicalization and hashing.
- [ ] Data-pool `pool_name` cannot escape `data-pools/{client_id}/`.
- [ ] Destructive operations fail closed unless explicitly allowed with boolean true.
- [ ] Generated payloads fail closed unless explicitly allowed.
- [ ] Duplicate `allow` policy is explicit in metadata and does not mask duplicate detection.
- [ ] Audit-wide duplicate scope is not assumed; current-run duplicate tracking evidence shows in-memory scope isolation by `client_id + audit_id + run_id`.
- [ ] `raw_result_version = "v1"` is preserved and Phase 2 metadata is nested under `payload_metadata`.

### Negative Test Requirements

- Invalid variables: `{{random}}`, malformed braces, unsupported whitespace/case variants, unresolved data-pool record fields.
- Invalid payload structures: method/content-type mismatch, non-JSON where JSON required, unsupported body types, invalid final template output.
- Unsafe destructive config: omitted/false/null/non-true `allow_destructive_operation` when destructive is true.
- Duplicate policies: invalid policy value, regenerate exhaustion, fail-fast duplicate, allow duplicate metadata, default policy/scope, and `duplicate_allowed = false` when no duplicate is detected.
- Fingerprint safety: unsafe sanitizer failure, non-canonical JSON ordering, raw unsafe values excluded from fingerprint inputs used for persisted metadata.
- Data-pool leakage: unsafe `pool_name`, path traversal, raw record fields/values absent from metadata/logs, client-scoped path only.
- Secret leakage: resolved secret-bearing headers/payload fields not emitted in metadata/logs; raw results contain fingerprints/safe indicators only.

### Evidence Required in QA Report

- Git branch and commit SHA under test.
- Implementation files/modules covered by tests.
- Test commands executed with full output or attached logs.
- Test counts: total, passed, failed, skipped/xfailed.
- Integration evidence: mock API request counts proving pre-request failures did not send outbound requests.
- Raw result samples with safe metadata only and `raw_result_version = "v1"`.
- Sanitization/log-capture excerpts proving absence of unsafe values.
- Duplicate-policy evidence showing final attempt counts and metadata outcomes.
- Fingerprint evidence showing equivalent JSON key ordering produces same SHA-256.
- Failure classification for every failure: Application Bug, Test Bug, Environment Issue, or Flaky Test, with root cause hypothesis, reproduction steps, and impact severity.

### Sign-off Criteria

QA sign-off may be approved only when all of the following are true:

- All critical Phase 2 acceptance criteria AC-001 through AC-029 are covered by automated tests or explicitly documented with approved rationale.
- Required validation commands pass in the QA environment.
- No blocking or high-severity application defects remain open.
- No unresolved flaky tests affect Phase 2 confidence.
- Negative tests prove validation failures use `PAYLOAD_VALIDATION_ERROR` and block outbound requests.
- Security checklist passes with evidence that metadata/logs do not leak unsafe values.
- Raw results preserve `raw_result_version = "v1"`, keep `payload_strategy` top-level, and nest Phase 2 details under `payload_metadata`.
- Audit-wide duplicate tracking remains out of scope; current-run duplicate tracking is proven with the confirmed in-memory scope key behavior.

If any criterion is not met, QA must withhold approval and document failures in `docs/qa/phase_2_payload_data_generation_test_report.md`.
