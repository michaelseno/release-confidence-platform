# GitHub Issue

## 1. Feature Name

Phase 2 Payload Data Generation

## 2. Problem Summary

The Phase 1 backend engine can execute configured API requests, but it does not yet provide deterministic, scalable, and safe payload preparation for dynamic request data or reusable client-provided datasets. Without Phase 2, audit runs are limited to static payloads or risk non-repeatable generated values, accidental destructive operations, duplicate submissions, weak traceability, and unsafe exposure of sensitive payload/data-pool content.

Phase 2 introduces backend-only payload strategy handling, deterministic generation, data-pool-backed payloads, duplicate prevention, destructive-operation safety controls, and sanitized fingerprint evidence while preserving Raw Result Schema v1 compatibility.

## 3. Linked Planning Documents

- Product Spec: `docs/product/phase_2_payload_data_generation_product_spec.md`
- Technical Design: `docs/architecture/phase_2_payload_data_generation_technical_design.md`
- QA Test Plan: `docs/qa/phase_2_payload_data_generation_test_plan.md`
- UI/UX Spec: not applicable; Phase 2 is backend-only and no frontend/dashboard implementation is in scope.

## 4. Scope Summary

### In scope

- Backend payload strategy resolution for exactly `static`, `generated`, and `data_pool` endpoint strategies.
- Deterministic generated substitutions for `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, and `{{uuid}}`.
- Run-level `{{timestamp}}` captured once and reused across the run.
- Deterministic `{{uuid}}` derived from `client_id + audit_id + run_id + endpoint_id + iteration + field_path + token_index`, with deterministic attempt salt for regeneration attempts.
- Data-pool loading from `data-pools/{client_id}/{pool_name}.json` using endpoint field `data_pool_name`.
- Deterministic data-pool record assignment using the approved hash tuple modulo pool size.
- Data-pool payload mapping where supported data-pool schemas are either a plain record list or a wrapped `{ "records": [...] }` object, and the selected record can be used as the full request payload by default or as a template substitution source when `payload_template` is configured.
- Duplicate prevention with policies `regenerate`, `fail_fast`, and `allow`; default policy `regenerate`; default and only supported Phase 2 scope `current_run`; maximum regeneration attempts of 5.
- Concurrency-safe in-memory duplicate checking/reservation within a run, scoped by `client_id + audit_id + run_id`.
- Endpoint-level payload safety controls for generated payloads, data-pool reuse, and destructive operations.
- Fail-closed destructive-operation behavior: if `payload_safety.destructive_operation = true`, execution is blocked unless `payload_safety.allow_destructive_operation = true`; the allow flag defaults to `false`.
- SHA-256 fingerprints over canonical sanitized JSON/string representations for payloads, responses, and selected data-pool records.
- Raw result extensions that preserve `raw_result_version = "v1"`, keep top-level `payload_strategy`, and nest Phase 2 details under `payload_metadata`.
- Safe payload metadata containing no unsafe raw payload values, generated values, raw data-pool records, secrets, tokens, credentials, cookies, PII, or sensitive data.
- Pre-request validation failures classified as `PAYLOAD_VALIDATION_ERROR`.
- Unit, integration, negative/security, regression, and static review coverage defined by the QA test plan.

### Out of scope

- Frontend/dashboard implementation, UI workflows, or config authoring UI.
- Public customer APIs or changes to the Phase 1 Lambda invocation API contract.
- User authentication, RBAC, billing, subscriptions, account management, or self-serve onboarding.
- AI insights, AI recommendations, reliability scoring, analytics reporting, or report generation as a product feature.
- Phase 3 scheduling, lifecycle management, recurring execution, or retry orchestration beyond existing Phase 1 runner retry behavior.
- Load testing, uptime-monitor clone behavior, chaos engineering, advanced observability, or distributed tracing.
- Secret lifecycle management beyond existing Phase 1 secret resolution behavior.
- Non-deterministic random data generation or general-purpose test data generation that cannot be wrapped deterministically.
- Full persisted historical/audit-wide duplicate detection across all runs; audit-wide duplicate tracking is explicitly out of scope until a persistent reservation design is approved.
- Persisting or exposing raw generated payload values, raw data-pool records, secrets, tokens, credentials, cookies, PII, or sensitive data in raw results, logs, or metadata.

## 5. Implementation Notes

### Frontend expectations

- No frontend, dashboard, or UI/UX implementation is expected for Phase 2.
- No frontend API integration is introduced.
- No dashboard states, config authoring UI, reporting UI, auth/account/billing UX, or analytics views are in scope.
- Branch review must confirm that all Phase 2 work remains backend-only.

### Backend expectations

- Build on the merged Phase 1 orchestrator, runner, S3/DynamoDB/Secrets wrappers, sanitization layer, structured logging, strict `run_id` validation, duplicate `run_id` protection, and Raw Result Schema v1.
- Add a payload preparation service invoked before outbound request execution.
- Resolve and validate the confirmed flat endpoint config fields before sending any request: `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- Support `static`, `generated`, and `data_pool` only; invalid/missing strategy cases must fail closed when a body strategy cannot be safely inferred.
- Reject Phase 2 variable tokens in `static` payloads.
- Resolve generated variables deterministically, including run-level timestamp reuse and field-path/token-index-specific UUID generation.
- Load data pools only from `data-pools/{client_id}/{pool_name}.json` using `data_pool_name`; validate the pool name so it cannot escape the client-scoped path; accept only a plain list of record objects or a wrapped object with `{ "records": [...] }`.
- Treat data-pool records as in-memory request construction inputs only; never log or persist raw selected records.
- Enforce duplicate policies using sanitized canonical fingerprints and an in-memory `current_run` tracker scoped by `client_id + audit_id + run_id`, with `regenerate` retrying attempts 1 through 5; reject audit-wide/non-`current_run` scopes in Phase 2.
- Enforce destructive-operation safety controls before outbound execution and fail closed unless explicitly allowed with boolean `true`.
- Generate `payload_metadata.payload_fingerprint`, `data_pool_record_fingerprint`, and `response_fingerprint` using SHA-256 over canonical sanitized representations; absent/no-body payloads use SHA-256 of the exact canonical string `EMPTY_PAYLOAD`.
- Keep raw result `payload_strategy` at the top level and Phase 2-specific details nested under `payload_metadata` while preserving `raw_result_version = "v1"`.
- Ensure `payload_metadata` contains only safe metadata such as scope, policy, booleans, generation attempt, pool name, nulls, and fingerprints; `duplicate_allowed` is `true` only when a duplicate is detected and allowed, and `false` is preferred when no duplicate is detected.
- Map all payload preparation validation failures to `PAYLOAD_VALIDATION_ERROR` and prevent outbound requests for those failures.
- HTTP retries must reuse the same prepared payload and metadata; retries must not trigger regeneration.

### Dependencies or blockers

- Phase 1 core engine must be merged and available on `main`.
- Existing runner/orchestrator extension points must support pre-request payload preparation and safe failure recording.
- Existing S3 wrapper is required for data-pool reads.
- Existing sanitization must be suitable for fingerprint inputs before canonicalization and hashing.
- Existing raw result consumers must tolerate top-level `payload_strategy` plus nested `payload_metadata` while `raw_result_version = "v1"` remains unchanged.
- Final Phase 2 implementation confirmations are incorporated in the product, architecture, and QA documents:
  - endpoint config uses confirmed flat fields `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and nested `payload_safety`;
  - data-pool files support both a plain list of record objects and a wrapped `{ "records": [...] }` object;
  - duplicate reservation uses an in-memory current-run tracker scoped by `client_id + audit_id + run_id`;
  - audit-wide duplicate tracking is explicitly out of scope for Phase 2;
  - absent/no-body payload fingerprints use SHA-256 of the canonical string `EMPTY_PAYLOAD`;
  - `duplicate_allowed` is `true` only when a duplicate is detected and allowed; `false` is preferred when no duplicate is detected;
  - raw results keep top-level `payload_strategy` and nest Phase 2 details under `payload_metadata`.

## 6. QA Section

### Planned test coverage

- Unit tests for strategy resolution, validators, template parsing, deterministic generation, data-pool loading/mapping, duplicate checker, fingerprint canonicalization, safety controls, and raw result metadata building.
- Integration tests through the Phase 1 orchestrator/runner with mocked AWS dependencies and a local mock API.
- Negative tests proving invalid strategies, unknown/malformed variables, invalid data pools, unsafe `pool_name` values, unsupported duplicate scopes, unsafe destructive config, duplicate exhaustion, and sanitizer/fingerprint failures do not send outbound requests.
- Security/sanitization/logging tests proving raw generated values, raw data-pool records, secrets, tokens, credentials, cookies, PII, and sensitive data are absent from `payload_metadata`, raw results, and logs.
- Regression tests for Phase 1 raw result v1 compatibility, strict run identity behavior, existing runner retry behavior, no-body/static behavior, and existing config validation boundaries.

### Acceptance criteria mapping

- AC-001 through AC-002: static strategy pass-through and dynamic-token rejection.
- AC-003 through AC-007B: deterministic generated variables, run-level timestamp reuse, UUID field-path differentiation, and repeated same-field UUID `token_index` stability.
- AC-008 through AC-010C: data-pool S3 path, missing/invalid data-pool failure, deterministic assignment, full-payload default, template substitution, and template failure behavior.
- AC-011 through AC-016: duplicate policies, regeneration attempts up to 5, fail-fast, allow, default policy, and default scope.
- AC-017 through AC-018: canonical SHA-256 payload and response fingerprinting.
- AC-019 through AC-023: generated payload opt-in, data-pool reuse controls, destructive-operation fail-closed behavior, explicit destructive allow, and concurrency duplicate safety.
- AC-024 through AC-029: top-level `payload_strategy`, nested `payload_metadata`, `raw_result_version = "v1"`, no unsafe metadata values, data-pool record fingerprint safety, and duplicate outcome metadata accuracy.

### Key edge cases

- Static no-body endpoint and explicit empty/null/string payload fingerprint behavior, including absent/no-body SHA-256 fingerprinting of canonical string `EMPTY_PAYLOAD`.
- Static payload containing `{{run_id}}` or any Phase 2 token syntax.
- Generated payloads with unknown, malformed, adjacent, nested, repeated, and path-sensitive tokens.
- Multiple `{{uuid}}` tokens at different field paths and repeated within the same field using stable zero-based `token_index`.
- Duplicate regeneration where generated values can change by attempt and where they cannot change; exhaustion after 5 attempts.
- Data-pool size 1 with reuse disallowed and `regenerate` or `fail_fast` policy.
- Missing, unreadable, empty, malformed, or unsupported data-pool files.
- Unsafe `pool_name` values including slashes, backslashes, dots/traversal, URL-encoded traversal-like values, whitespace, and control characters.
- Data-pool template references to missing fields, nested fields, reserved-name conflicts, or invalid final payload structures.
- Payload/response values containing secrets, tokens, credentials, cookies, PII, or sensitive data before sanitization.
- Equivalent JSON payload/response content with different key ordering.
- Empty, non-JSON, malformed JSON, and binary-like response bodies.
- `payload_safety.destructive_operation = true` with omitted, false, null, string, numeric, or any non-boolean-true allow value.
- Concurrent endpoint iterations attempting to reserve the same generated payload or data-pool record.
- Unsupported future duplicate scope for same client/audit across all runs; audit-wide tracking remains out of scope and must not silently degrade to current-run behavior.
- Raw result records with missing, malformed, duplicated, or unsafe `payload_metadata` fields.

### Test types expected

- Functional unit tests.
- Integration tests with mocked AWS clients and local mock API only.
- Negative/error-path tests.
- Security, sanitization, and log-leakage tests.
- Concurrency tests for duplicate reservation.
- Regression tests for Phase 1 behavior and Raw Result Schema v1 compatibility.
- Static review and required validation commands from the QA test plan.

## 7. Risks / Open Questions

- Audit-wide duplicate detection is out of scope for Phase 2; full cross-run duplicate prevention requires a future persisted conditional reservation design.
- Endpoint configuration field names and schema details are finalized as the flat Phase 2 fields `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety` without breaking Phase 1 behavior.
- Data-pool accepted JSON schemas are finalized as either a plain list of record objects or a wrapped `{ "records": [...] }` object; the wrapped object is preferred for future metadata compatibility.
- Existing raw result consumers must be checked for compatibility with nested `payload_metadata` and top-level `payload_strategy` while preserving `raw_result_version = "v1"`.
- Payload fingerprint behavior for absent/no-body requests is finalized as SHA-256 over the exact canonical string `EMPTY_PAYLOAD`.
- Data-pool substitution syntax may conflict with reserved generated token names; validators must keep strategy-specific behavior explicit.
- Destructive operation classification is config-driven; Phase 2 should not infer destructiveness solely from HTTP method unless later approved.
- In-memory duplicate checking protects one run/process only, with scope identity `client_id + audit_id + run_id`; it does not provide cross-process or historical/audit-wide protection.

## 8. Definition of Done

- `static`, `generated`, and `data_pool` payload strategies are implemented and validated within Phase 2 backend scope only.
- Generated substitutions are deterministic for all approved variables, including run-level `{{timestamp}}` reuse and deterministic `{{uuid}}` with `field_path + token_index`.
- Data-pool loading uses `data-pools/{client_id}/{pool_name}.json` with endpoint field `data_pool_name`, validates path safety, accepts plain-list and wrapped `{ "records": [...] }` schemas, and supports deterministic assignment.
- Data-pool selected records can be used as full request payloads by default or as template substitution sources when configured.
- Duplicate prevention supports `regenerate`, `fail_fast`, and `allow`, with default `regenerate`, default/only-supported `current_run`, accurate metadata including `duplicate_allowed`, concurrency-safe in-memory tracking within `client_id + audit_id + run_id`, and maximum regeneration attempts of 5.
- Safety controls block generated payloads unless allowed, apply data-pool reuse policy, and block destructive operations unless `allow_destructive_operation = true`.
- Payload, response, and data-pool record fingerprints use SHA-256 over canonical sanitized representations; absent/no-body payload fingerprints use SHA-256 of canonical string `EMPTY_PAYLOAD`.
- Raw results preserve `raw_result_version = "v1"`, keep top-level `payload_strategy`, and nest safe Phase 2 details under `payload_metadata`.
- `payload_metadata` contains no unsafe raw payload values, generated values, raw data-pool records, secrets, tokens, credentials, cookies, PII, or sensitive data.
- Payload validation failures occur before outbound request execution and use `PAYLOAD_VALIDATION_ERROR`.
- Automated tests cover AC-001 through AC-029 or document any approved exception.
- Required QA validation commands pass and evidence is captured in the QA report after implementation.
- Branch review confirms no out-of-scope frontend, auth, billing, AI, reporting, scheduler, load testing, uptime monitoring, chaos engineering, or public API functionality is introduced.
