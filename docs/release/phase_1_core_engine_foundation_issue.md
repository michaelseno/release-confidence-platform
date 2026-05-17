# GitHub Issue

## 1. Feature Name

Phase 1 Core Engine Foundation

## 2. Problem Summary

The Release Confidence Platform needs a deterministic, auditable backend execution foundation before it can produce trustworthy release confidence findings. Phase 1 establishes a backend-only, config-driven core engine that can validate audit invocation input, load tenant/audit configuration, resolve secrets safely, execute configured API requests, produce sanitized Raw Result Schema v1 evidence, and persist immutable run evidence plus metadata for downstream phases.

## 3. Linked Planning Documents

- Product Spec: `docs/product/phase_1_core_engine_foundation_product_spec.md`
- Technical Design: `docs/architecture/phase_1_core_engine_foundation_technical_design.md`
- QA Test Plan: `docs/qa/phase_1_core_engine_foundation_test_plan.md`
- UI/UX Spec: not applicable; Phase 1 is backend-only and no frontend/dashboard implementation is in scope.

## 4. Scope Summary

### In scope

- Generic Lambda orchestrator for a single config-driven audit run.
- Event contract with `client_id`, `audit_id`, `scenario_type`, `triggered_by`, and optional `run_id`.
- Strict run identity validation for supplied `run_id` using exact regex `^[A-Za-z0-9_-]{8,80}$`.
- Rejection of invalid supplied `run_id` values without normalization, replacement generation, or raw value logging.
- Generated UUIDv4-compatible `run_id` only when `run_id` is absent.
- Duplicate `run_id` protection for the same `client_id` + `audit_id` before raw evidence or metadata mutation.
- Controlled `DUPLICATE_RUN_ID` run-level orchestration/storage control error on duplicate S3 raw result object or DynamoDB metadata item.
- S3 config loading from exact keys:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
- DynamoDB configuration/run metadata access using `PK = CLIENT#{client_id}` and `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Secrets Manager-only runtime secret resolution from secret references.
- Lightweight API runner using `requests` with configured method, URL, headers, payload/body, timeout, and retries.
- Monotonic outbound request duration measurement.
- Raw Result Schema v1 with `raw_result_version = "v1"` and approved endpoint failure classifications only.
- Sanitized raw evidence persistence once at run completion to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- Centralized sanitization before S3 writes, DynamoDB writes, logs, responses, or report-handoff boundaries.
- Explicit sanitized log categories: `internal_operational_logs` and `client_safe_logs`.
- Unit, integration, security, regression, and static review coverage as defined by the QA test plan.

### Out of scope

- Frontend/dashboard implementation.
- UI/UX workflows or customer-facing dashboard states.
- Application authentication, authorization, RBAC, billing, subscriptions, account management, or onboarding.
- Public customer API surface or config authoring UI.
- Reliability scoring, analytics dashboards, generated findings, or report product features.
- AI insights or AI recommendations.
- Advanced observability, distributed tracing, load testing, uptime monitor clone behavior, continuous synthetic monitoring product behavior, or chaos engineering.
- Multi-region execution and production hardening beyond Phase 1 engine correctness/safe evidence handling.
- Heavy API frameworks or later-phase implementation work.

## 5. Implementation Notes

### Frontend expectations

- No frontend or dashboard code is expected for Phase 1.
- Existing frontend placeholders must remain placeholders only.
- Branch review must confirm no frontend/dashboard, auth, account, billing, AI, scoring, reporting, load, uptime, or chaos functionality is introduced.

### Backend expectations

- Implement a backend-only Lambda handler/orchestrator path with no client-specific business logic.
- Validate event fields before config loading or outbound API execution.
- Validate supplied `run_id` exactly against `^[A-Za-z0-9_-]{8,80}$`; reject invalid values as received.
- Do not normalize, trim, decode, repair, hash, replace, or convert invalid supplied `run_id` values.
- Do not log, persist, return, or interpolate raw rejected `run_id` values in S3 paths, DynamoDB keys, raw results, metadata, logs, or responses.
- Check duplicate state for the resolved `client_id` + `audit_id` + `run_id` against both:
  - S3 object `raw-results/{client_id}/{audit_id}/{run_id}/results.json`
  - DynamoDB item `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`
- On duplicate detection, fail fast with controlled `DUPLICATE_RUN_ID` and do not overwrite, append, merge, or treat the request as idempotent success.
- Treat `DUPLICATE_RUN_ID` as a run-level orchestration/storage control error, not an endpoint `failure_type`.
- Preserve raw evidence immutability: one sanitized `results.json` object is written at run completion; existing raw evidence must not be overwritten, appended to, or merged.
- Resolve secrets only through AWS Secrets Manager references; literal secrets in config or persisted/logged output are prohibited.
- Use `requests` for HTTP execution and monotonic timing around the outbound request boundary only.
- Endpoint `failure_type` values are limited to `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, and `PAYLOAD_VALIDATION_ERROR`.
- Runtime statuses are limited to `STARTED`, `COMPLETED`, and `FAILED`.
- Sanitization must redact sensitive data with `"[REDACTED]"` before persistence, logging, responses, or report handoff.

### Dependencies or blockers

- Phase 0 project foundation merged into `main`.
- AWS Lambda runtime and deployment conventions from Phase 0.
- S3 for configuration and raw result storage.
- DynamoDB for configuration and run metadata.
- AWS Secrets Manager for runtime secret resolution.
- IAM permissions for required S3, DynamoDB, and Secrets Manager operations.
- Python `requests` dependency.
- Local/mock AWS clients and local mock API support for tests.
- Open implementation decisions to resolve or document during development:
  - exact config metadata item shape beyond client/audit queryability;
  - exact consumed config schema fields;
  - aggregate metadata status for runs with endpoint-level failures but successful evidence persistence;
  - stable project command wrappers for Phase 1 test execution.

## 6. QA Section

### Planned test coverage

- Unit tests for schemas, constants, validators, run identity, sanitizer, config loaders/validators, secret reference handling, runner classification/timing/retry behavior, raw result builder, metadata builder, storage key generation, duplicate detection, and logging wrappers.
- Integration tests for Lambda handler/orchestrator behavior with mocked AWS clients, fake S3/DynamoDB/Secrets Manager, local mock API, raw evidence persistence, metadata lifecycle, and log capture.
- Security tests for `run_id` injection/path traversal prevention, secret/PII redaction, literal secret rejection, no raw invalid `run_id` logging, and client-safe log restrictions.
- Regression/static review checks for Phase 0 validation commands, `requests` usage, monotonic timing, approved enums, no live AWS dependency in tests, and Phase 1 scope boundaries.

### Acceptance criteria mapping

- AC-001 through AC-002G: event validation, supplied/generated `run_id`, invalid `run_id` rejection, no normalization/replacement, duplicate fail-fast, immutable evidence, and `DUPLICATE_RUN_ID` as control error only.
- AC-003 through AC-006: exact S3 config loading and DynamoDB metadata queryability.
- AC-007 through AC-008: Secrets Manager-only resolution and sanitized secret failure behavior.
- AC-009 through AC-012: configured request execution, monotonic timing, and retry recording.
- AC-013 through AC-020: approved endpoint failure classification behavior.
- AC-021 through AC-024: Raw Result Schema v1, exact S3 raw result path, exact DynamoDB keys, and metadata locator behavior.
- AC-025 through AC-029: sanitization before persistence/logging and explicit safe log categories.
- AC-030 through AC-031: Phase 1 boundary enforcement and no out-of-scope features.

### Key edge cases

- Supplied `run_id` at exact length boundaries: 8 accepted, 80 accepted, 7 rejected, 81 rejected.
- Supplied `run_id` containing slash, backslash, dot, traversal-like values, URL-encoded traversal, whitespace, tabs, newlines, control characters, or shell/log/key injection characters.
- Invalid supplied `run_id` values that would become valid only after trimming, decoding, replacing, or removing unsafe characters.
- Missing required event fields.
- Duplicate existing S3 raw result object, duplicate existing DynamoDB metadata item, and both duplicate.
- Missing, denied, unreadable, or invalid JSON configs.
- Literal secrets in config and failed Secrets Manager resolution.
- Endpoint timeout, connection error, malformed JSON response, assertion failure, invalid payload, and unexpected runner error.
- Multiple endpoints where one endpoint fails and others remain executable.
- Partial persistence failures involving S3 and DynamoDB.
- Sanitization of nested payloads, URLs, metadata, logs, exceptions, and unexpected data types.

### Test types expected

- Unit tests.
- Integration tests with mocked AWS clients and local mock API only.
- Security/negative tests.
- Regression tests.
- Static/code review checks.

## 7. Risks / Open Questions

- Duplicate `run_id` race protection depends on conditional write/non-overwrite behavior in storage abstractions and must be reviewed/tested carefully.
- Config schema beyond minimum executable fields remains partly implementation-defined and must be documented by implementation.
- Aggregate run metadata status for endpoint-level failures is not fully product-defined; technical design recommends `COMPLETED` when execution completes and raw evidence persists, with endpoint failures represented in results.
- Partial persistence failure behavior requires deterministic storage mock hooks for reliable QA evidence.
- Exact config metadata item shape beyond client/audit queryability remains open.
- Stable local Phase 1 test command wrappers may need to be confirmed once implementation is present.

## 8. Definition of Done

- All in-scope Phase 1 functional requirements are implemented or explicitly documented as deferred/not implemented with approval before merge.
- All acceptance criteria from the product spec are satisfied by automated tests, reviewed evidence, or both.
- Supplied `run_id` validation uses exact regex `^[A-Za-z0-9_-]{8,80}$` and rejects unsafe values without normalization, replacement generation, or raw value logging.
- Duplicate `run_id` detection fails fast with controlled `DUPLICATE_RUN_ID` and proves no overwrite, append, or merge of raw evidence or metadata.
- `DUPLICATE_RUN_ID` remains a run-level orchestration/storage control error and is not included in endpoint `failure_type` values.
- Raw evidence is immutable and persisted only at the required S3 key after sanitization.
- Raw Result Schema v1 is stable with `raw_result_version = "v1"`.
- DynamoDB run metadata uses the required key pattern and sanitized values.
- Secrets and sensitive data are not present in configs, logs, raw results, metadata, responses, fixtures, or QA artifacts.
- Unit, integration, security, regression, and static review validations pass with documented evidence.
- QA report is created/updated after implementation and contains sufficient evidence for QA sign-off.
- Branch review confirms no out-of-scope frontend, account, auth, billing, AI, analytics/reporting product, load testing, uptime monitoring, chaos engineering, or heavy framework capabilities were introduced.
