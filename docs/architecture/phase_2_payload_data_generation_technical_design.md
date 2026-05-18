# Technical Design

## 1. Feature Overview

Phase 2 extends the merged Phase 1 backend execution engine with deterministic payload preparation, data-pool-backed request data, duplicate prevention, endpoint-level payload safety controls, and sanitized payload/response fingerprints.

This design is backend-only and applies to the current branch `feature/phase_2_payload_data_generation`. It builds on Phase 1 orchestrator, runner, S3/DynamoDB/Secrets wrappers, Raw Result Schema v1, sanitization, structured logging, strict `run_id` validation, and duplicate `run_id` protection. Phase 2 preserves `raw_result_version = "v1"` by adding backward-compatible payload metadata fields.

## 2. Product Requirements Summary

Phase 2 must provide:

- Endpoint-level payload strategies: `static`, `generated`, and `data_pool`, configured with confirmed flat Phase 2 endpoint fields: `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- Deterministic substitutions for `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, and `{{uuid}}`.
- `{{timestamp}}` captured once per run and reused throughout the run.
- `{{uuid}}` derived from `client_id + audit_id + run_id + endpoint_id + iteration + field_path + token_index`, plus deterministic attempt salt when regeneration is required.
- Data-pool loading from `data-pools/{client_id}/{pool_name}.json`.
- Deterministic data-pool assignment using `hash(client_id, audit_id, run_id, endpoint_id, scenario_type, iteration) % pool_size`.
- Data-pool payload mapping supports both selected record as the full request payload and selected record as a substitution source for a configured payload template. When no payload template is provided, the selected record is the full request payload by default.
- Duplicate policy support: `regenerate`, `fail_fast`, and `allow`; default policy is `regenerate`.
- Duplicate scope support with default/current `current_run` only. Scope keys include `client_id + audit_id + run_id`; audit-wide duplicate tracking is out of scope until persistent reservation is designed.
- Endpoint-level safety controls for generated payloads, data-pool reuse, and destructive operations.
- SHA-256 fingerprints over canonical sanitized JSON/string representations for payloads, responses, selected data-pool records, and the canonical sentinel `EMPTY_PAYLOAD` for absent/no-body payloads.
- Raw Result Schema v1 metadata extensions that keep top-level `payload_strategy` and nest Phase 2-specific safe details under `payload_metadata` without exposing unsafe payload values or raw data-pool contents.
- Pre-request validation failures classified as `PAYLOAD_VALIDATION_ERROR`.

## 3. Requirement-to-Architecture Mapping

| Product Requirement / Decision | Technical Design Response |
| --- | --- |
| FR-001, AC-001, AC-002 | Add endpoint `payload_strategy` resolution and validation with static default only when safe. Static strategy does not substitute variables and rejects Phase 2 tokens. |
| FR-003, FR-004, AC-003 through AC-007 | Implement deterministic template resolver in `packages/data-generation/templates.py` and generator orchestration in `generator.py`. |
| Confirmed decisions 2 and 3 | Capture a run-level timestamp once in orchestrator/run context; UUID generation is context-, field-path-, and token-index-derived. |
| FR-005, FR-006, AC-008 through AC-010 | Add data-pool loader using S3 path `data-pools/{client_id}/{pool_name}.json` and deterministic record assignment. |
| Confirmed decision 5 | Use stable hash input tuple `client_id`, `audit_id`, `run_id`, `endpoint_id`, `scenario_type`, `iteration` modulo pool size. |
| Confirmed Phase 2 endpoint config shape | Consume flat endpoint fields: `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`; do not require nested `payload_generation`, `data_pool`, or `duplicate_prevention` objects for Phase 2. |
| Confirmed data-pool schema decision | Accept both a plain list of record objects and a wrapped object containing `records`; normalize both to a records array, with wrapped object preferred for future metadata. |
| Final Phase 2 data-pool mapping decision | If no payload template is configured, selected record becomes the full request payload. If a payload template is configured, selected record fields are available as substitution values while final payload follows the template shape. |
| FR-007 through FR-009, FR-014, AC-011 through AC-016, AC-020, AC-023 | Implement duplicate checker with reserve/check contract, in-run concurrency-safe state, scope model, duplicate policies, and attempt loop. |
| Confirmed decision 8 | `regenerate` retries deterministic generation with incrementing attempt salt up to 5 attempts; `fail_fast` fails; `allow` proceeds and records `duplicate_allowed = true`. |
| Confirmed in-run duplicate reservation decision | Use an in-memory duplicate tracker per orchestrator run. For `current_run`, the duplicate scope key includes `client_id + audit_id + run_id`. Audit-wide duplicate tracking is explicitly out of scope until a persistent reservation design is approved. |
| FR-010, FR-011, AC-017, AC-018 | Add fingerprint utility: sanitize first, canonicalize second, SHA-256 third. |
| Confirmed absent/no-body fingerprint decision | Represent absent/no-body payloads with canonical sentinel string `EMPTY_PAYLOAD`; `payload_fingerprint` is SHA-256 over that canonical string. |
| FR-012, FR-013, AC-019, AC-021, AC-022 and final destructive-operation decision | Add payload validators and safety enforcement before outbound request execution. If `payload_safety.destructive_operation = true` and `payload_safety.allow_destructive_operation != true`, block execution with `PAYLOAD_VALIDATION_ERROR`; default `allow_destructive_operation = false`. |
| FR-015, FR-016, AC-024 through AC-029 and final raw result nesting decision | Extend raw result builder with top-level `payload_strategy` and nested `payload_metadata` while preserving `raw_result_version = "v1"`; never persist raw generated values or raw data-pool records. |
| Confirmed `duplicate_allowed` metadata decision | Emit `duplicate_allowed: true` only when policy `allow` detected and allowed a duplicate. When no duplicate is detected, prefer `duplicate_allowed: false` for analytics consistency. |
| Phase 2 out-of-scope constraints | No frontend, public API, scheduling/lifecycle, analytics, scoring, AI, auth, billing, load testing, or chaos behavior. |

## 4. Technical Scope

### Current Technical Scope

Phase 2 implementation includes:

- Config schema additions consumed by the backend runner/config validator.
- Payload preparation service invoked before each outbound request.
- Static/generated/data-pool strategy handlers.
- Deterministic template substitution and field-path traversal.
- Data-pool S3 loading and deterministic record selection.
- Payload validation and endpoint safety enforcement.
- In-run duplicate checking and reservation with policy handling.
- Fingerprint generation for final effective payload, selected data-pool record, and response content.
- Raw Result Schema v1-compatible payload metadata extensions.
- Unit and integration test coverage for deterministic behavior, safety, duplicate policy, and metadata safety.

### Out of Scope

Phase 2 must not implement:

- Frontend/dashboard/config authoring UI.
- Public customer APIs.
- User authentication, RBAC, billing, subscriptions, account management, or self-serve onboarding.
- Phase 3 scheduling, recurring runs, lifecycle management, or retry orchestration beyond Phase 1 runner retry behavior.
- Reliability scoring, analytics reporting, AI insights, uptime-monitor clone behavior, load testing, or chaos engineering.
- Secret lifecycle management beyond Phase 1 Secrets Manager resolution.
- Non-deterministic random data generation.
- Full persisted historical/audit-wide duplicate detection across runs. Audit-wide duplicate tracking must wait for an approved persistent reservation design.
- Persisting or exposing raw generated payload values, raw data-pool records, secrets, tokens, credentials, cookies, PII, or sensitive data in raw results/logs.

### Future Technical Considerations

- Persisted audit-wide duplicate registry for all runs under the same `client_id + audit_id`, backed by an explicit conditional-write reservation design.
- Data-pool validation tooling and management UI.
- Additional variable types if approved by a later product spec.
- Reports summarizing duplicate trends and payload consistency.

## 5. Architecture Overview

### Runtime Flow

1. Lambda handler delegates to Phase 1 orchestrator.
2. Orchestrator validates event identifiers and resolves/generates safe `run_id` using Phase 1 rules.
3. Orchestrator captures `run_timestamp` once after run identity validation and before endpoint execution. Use UTC ISO-8601 with stable formatting, for example `2026-05-18T12:34:56Z`.
4. Orchestrator initializes a run-scoped duplicate registry/checker instance keyed by validated `client_id`, `audit_id`, and `run_id`.
5. Config loaders load Phase 1 config plus Phase 2 endpoint payload fields.
6. Config validator validates the confirmed flat endpoint schema, payload strategy fields, duplicate settings, data-pool fields, and safety config.
7. For each endpoint iteration, runner calls `PayloadPreparationService.prepare(...)` before any outbound request.
8. Payload preparation resolves strategy:
   - `static`: validate and use configured payload/effective body without substitution.
   - `generated`: validate safety, resolve `payload_template` deterministically, validate final payload, fingerprint, duplicate-check/reserve.
   - `data_pool`: validate safety, load pool from `data_pool_name`, select record deterministically, construct final payload from either the selected record directly or `payload_template` using the record as substitution source, fingerprint selected record and final payload, duplicate-check/reserve.
9. If validation/duplicate safety fails, runner records endpoint outcome with `failure_type = PAYLOAD_VALIDATION_ERROR`; no outbound request is sent.
10. If preparation succeeds, runner sends final prepared payload using existing Phase 1 request execution behavior.
11. Runner/builders compute response fingerprint from sanitized canonical response evidence.
12. Raw result builder records top-level `payload_strategy`, nests Phase 2 safe details under `payload_metadata`, and preserves `raw_result_version = "v1"`.
13. Phase 1 sanitization runs before logs, metadata, and raw evidence persistence.

### Key Design Constraint

Payload values are necessarily present in memory long enough to send the outbound request, but raw generated values and raw data-pool records must not be logged or persisted. Persisted payload evidence is limited to fingerprints and safe metadata.

## 6. System Components

### PayloadPreparationService

**Suggested location:** `packages/data-generation/generator.py` or a service imported by the runner.

**Purpose:** Single runner-facing entrypoint for Phase 2 payload preparation.

**Input contract:**

- Validated run context: `client_id`, `audit_id`, `run_id`, `scenario_type`, `run_timestamp`.
- Endpoint config: `endpoint_id`, `method`, `content_type`/body mode where available, existing static payload/body if applicable, and confirmed Phase 2 fields `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- Iteration number as integer. Initial/default iteration is `1`; endpoint iteration count is read from `payload_iterations` with default `1`.
- Run-scoped duplicate checker instance.
- S3/data-pool loader dependency.
- Sanitizer and fingerprint utility dependency.

**Output contract:**

Return a `PreparedPayloadResult` containing:

| Field | Type | Description |
| --- | --- | --- |
| `payload` | object/string/null | Final effective payload/body for outbound request. Not safe for persistence without sanitization; do not log. |
| `content_type` | string/null | Effective content type if used by runner. |
| `metadata` | object | Safe raw result metadata listed in Section 7. |
| `payload_fingerprint` | string | SHA-256 hex over canonical sanitized final payload/effective body. |
| `duplicate_detected` | boolean | Whether any duplicate was detected during preparation. |
| `duplicate_allowed` | boolean | True only when policy `allow` detected and allowed a duplicate; false when no duplicate was detected. |

Raise/return structured `PayloadValidationError` for all pre-request validation failures. Runner maps this to `failure_type = PAYLOAD_VALIDATION_ERROR`.

### Template Resolver

**Suggested location:** `packages/data-generation/templates.py`.

**Responsibilities:**

- Traverse JSON-compatible dictionaries/lists/scalars and string payloads.
- Detect standard Phase 2 tokens exactly matching `{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, `{{uuid}}`.
- For `data_pool` templates only, also detect selected-record field tokens such as `{{field_name}}` and `{{nested.field}}` according to the Data-Pool Payload Mapper rules.
- Reject unknown tokens such as `{{random}}`, missing data-pool field references, and malformed tokens before outbound execution.
- Resolve repeated tokens deterministically.
- Provide deterministic `field_path` for each value occurrence.

**Field path rules:**

- Root path is `$`.
- Object fields append `.<key>` using the exact JSON object key. For keys containing `.`, `[`, `]`, or whitespace, use bracket notation `$['literal.key']` with JSON-style escaping.
- Array elements append `[index]` with zero-based index.
- For a string containing one or more tokens, the field path is the path to that string value.
- Multiple `{{uuid}}` tokens in the same string at the same path use `token_index` in the UUID seed to avoid identical UUIDs inside the same field while preserving repeatability.
- `token_index` is zero-based and determined by scanning the original string value from left to right after JSON parsing and before substitution. Count only `{{uuid}}` token occurrences in that one string value; reset the counter for each distinct field path. Non-UUID tokens do not increment `token_index`. Example: `"{{uuid}}-{{run_id}}-{{uuid}}"` at `$.request_id` resolves UUIDs with `token_index=0` and `token_index=1`.
- Object key order must not affect path identity; traversal should use parsed object structure but UUID seed uses the actual path, not traversal order.

### Deterministic Generator

**Suggested location:** `packages/data-generation/generator.py`.

**Responsibilities:**

- Build deterministic substitution context.
- Replace supported variables:
  - `{{run_id}}` => validated canonical run id.
  - `{{iteration}}` => decimal string form of iteration.
  - `{{timestamp}}` => run-level timestamp captured once by orchestrator.
  - `{{uuid}}` => deterministic UUID derived from a SHA-256/UUIDv5-like seed.
- Add deterministic attempt salt only for regeneration attempts.

**UUID seed format:**

```text
phase2.uuid.v1|client_id|audit_id|run_id|endpoint_id|iteration|field_path|token_index=<token_index>|attempt=<generation_attempt>
```

`generation_attempt` is `1` for the initial attempt and increments through `5` for `regenerate`. `token_index` is determined by the Template Resolver rules above. The seed must be UTF-8 encoded. Implementation may convert SHA-256 bytes into an RFC 4122 version-5-shaped UUID or use `uuid.uuid5` with a fixed project namespace and the seed string. The same algorithm must be centralized and covered by tests.

### Payload Validator

**Suggested location:** `packages/data-generation/validators.py`.

**Responsibilities:**

- Validate strategy-specific required fields.
- Validate confirmed flat Phase 2 endpoint fields and defaults: `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- Reject unknown strategies and invalid defaults.
- Reject Phase 2 tokens in `static` payloads.
- Reject unknown/malformed variables in `generated` payloads.
- Validate payload/body type against method/content-type configuration.
- Validate data-pool file structure and selected record usability.
- Accept and normalize both data-pool JSON container shapes: plain records list and wrapped object with `records`.
- Enforce endpoint-level safety config before outbound request.
- Classify all failures as `PAYLOAD_VALIDATION_ERROR` at runner result boundary.

### DuplicateChecker

**Suggested location:** `packages/data-generation/duplicate_checker.py`.

**Responsibilities:**

- Provide concurrency-safe in-memory duplicate detection/reservation for `current_run`.
- Support policy values `regenerate`, `fail_fast`, and `allow`.
- Support scope value `current_run` now and reject unsupported audit-wide scope values. Do not silently degrade audit-wide duplicate tracking to current-run behavior.
- Expose `check_and_reserve(scope_key, fingerprint, duplicate_subject_type)` as an atomic operation within a process. For `current_run`, `scope_key` must include `client_id`, `audit_id`, and `run_id`.

**Concurrency model:**

- For Phase 2 `current_run`, duplicate state lives inside the orchestrator/run process and is shared by endpoint iterations for that run. The scope identity is `client_id + audit_id + run_id`.
- Use a lock/mutex around check+reserve so concurrent local threads/tasks cannot both proceed with the same fingerprint when duplicates are prohibited.
- This protects concurrency within one Lambda/process. It does not provide cross-process or cross-run duplicate safety; that is a documented future boundary.

### DataPoolLoader

**Suggested location:** `packages/data-generation/data_pools.py` or `packages/storage` adapter plus data-generation wrapper.

**Responsibilities:**

- Build S3 key exactly as `data-pools/{client_id}/{pool_name}.json` using validated `client_id` and validated pool name from endpoint field `data_pool_name`.
- Load through existing S3 wrapper.
- Parse JSON and validate accepted schema.
- Cache loaded pools within a run by `(client_id, pool_name)` to avoid repeated S3 reads.
- Return selected record only to payload preparation; never log raw records.

### Data-Pool Payload Mapper

**Suggested location:** `packages/data-generation/data_pools.py` or `packages/data-generation/generator.py`.

**Responsibilities:**

- For `payload_strategy = "data_pool"`, select one record using the deterministic assignment rule before payload construction.
- If endpoint `payload_template` is absent, use the selected data-pool record as the full request payload. This is the default data-pool mapping behavior.
- If endpoint `payload_template` is present, render that template using the selected record as a substitution source in addition to the standard Phase 2 generated tokens.
- Resolve data-pool substitutions deterministically and fail with `PAYLOAD_VALIDATION_ERROR` when a template references a missing record field or a value cannot be represented in the target template location.
- Keep raw record values in memory only; expose only `data_pool_name` and `data_pool_record_fingerprint` in metadata.

**Data-pool substitution rules:**

- The selected record is treated as a JSON object substitution context.
- Template tokens that match selected-record field paths are resolved from the record. Top-level fields use `{{field_name}}`; nested fields use dot notation such as `{{user.id}}` when the underlying record contains `{ "user": { "id": "..." } }`.
- Standard Phase 2 tokens (`{{run_id}}`, `{{iteration}}`, `{{timestamp}}`, `{{uuid}}`) remain reserved and are resolved from run context, not from data-pool record fields.
- If a selected record contains keys that conflict with reserved token names, the reserved token behavior wins. Record-field references for those names are not available in Phase 2 unless a later spec defines an escape syntax.
- Missing fields, malformed paths, or unsupported token syntax fail before outbound execution.

### Fingerprint Utility

**Suggested location:** `packages/data-generation/fingerprints.py` or a shared core utility if Phase 1 already centralizes evidence hashing.

**Responsibilities:**

- Apply sanitizer before canonicalization and hashing.
- Canonicalize JSON-compatible payloads deterministically with sorted object keys and stable scalar serialization.
- Canonicalize strings/non-JSON bodies as sanitized UTF-8 strings with collision-safe internal typing where needed.
- Canonicalize absent/no-body payloads using the exact sentinel string `EMPTY_PAYLOAD` for the externally recorded `payload_fingerprint`.
- Compute lowercase SHA-256 hex digests for payload, response, and data-pool record fingerprints.
- Keep the fingerprinting contract centralized so runner, raw result builder, and tests do not diverge.

### Runner Extension

**Suggested location:** existing `apps/backend/runner/` modules.

**Responsibilities:**

- Invoke payload preparation before each request attempt sequence, not before each retry. HTTP retries must reuse the same prepared payload for that endpoint iteration to preserve evidence consistency.
- Do not send outbound request when preparation fails.
- Include prepared safe metadata in raw result record for success and failure outcomes where available.
- Compute response fingerprint from final response evidence using fingerprint utility.

### Orchestrator Extension

**Responsibilities:**

- Capture run-level timestamp once.
- Initialize duplicate checker.
- Pass run context and shared duplicate checker to runner.
- Preserve Phase 1 raw evidence persistence and run metadata behavior.

### Raw Result Builder Extension

**Responsibilities:**

- Add Phase 2 metadata in a backward-compatible way: keep `payload_strategy` top-level and place Phase 2-specific details under `payload_metadata`.
- Preserve existing Phase 1 required fields and `raw_result_version = "v1"`.
- Avoid embedding raw payloads or raw data-pool records.
- Include `duplicate_allowed = false` when duplicate checking runs and no duplicate was detected; include `duplicate_allowed = true` only when a duplicate was detected and allowed by `duplicate_policy = "allow"`.

## 7. Data Models

### Endpoint Configuration Extension

#### Purpose

Configure payload strategy, generation, duplicate handling, and safety per endpoint.

#### Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `payload_strategy` | string | Conditional | One of `static`, `generated`, `data_pool`. If omitted, resolve to `static` only when static payload exists or no body is required; otherwise fail. |
| `payload_template` | object/string/null | Strategy-dependent | Generated template payload, or optional target payload template for data-pool records. For `data_pool`, absence/null means selected record is the full request payload. Static payloads use the existing Phase 1 static payload/body field, not `payload_template`, unless existing config conventions already route the body through this field. |
| `payload_iterations` | integer | No | Number of endpoint payload iterations. Default `1`; must be positive and bounded by existing execution limits if any. |
| `data_pool_name` | string/null | Required for `data_pool` | Data-pool name used in S3 key. Must be path-safe; no slashes, dots, traversal, or empty values. Null for non-`data_pool` strategies. |
| `duplicate_check_scope` | string | No | Default and only supported Phase 2 value is `current_run`. Unsupported audit-wide values must fail validation until persistent reservation is designed. |
| `duplicate_policy` | string | No | One of `regenerate`, `fail_fast`, `allow`; default `regenerate`. |
| `payload_safety.allow_generated_payloads` | boolean | Required for generated allow | Must be `true` for `generated` strategy. Missing/false blocks generated payloads. |
| `payload_safety.allow_data_pool_reuse` | boolean | No | True permits duplicate selected data-pool record reuse; missing/false applies duplicate policy on reuse. |
| `payload_safety.destructive_operation` | boolean | Required for destructive endpoints | Indicates endpoint is destructive. If true, an explicit allow is also required as below. |
| `payload_safety.allow_destructive_operation` | boolean | No | Defaults to `false`. Must be exactly `true` to execute when `destructive_operation = true`; otherwise execution is blocked with `PAYLOAD_VALIDATION_ERROR`. |

#### Example

```json
{
  "endpoint_id": "create-order",
  "method": "POST",
  "url": "https://api.example.test/orders",
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

This flat shape is the confirmed Phase 2 implementation contract. Downstream agents should not implement the earlier nested `payload_generation`, `data_pool`, or `duplicate_prevention` endpoint objects for Phase 2 unless required for backward compatibility by existing fixtures.

Destructive endpoint blocking example:

```json
"payload_safety": {
  "destructive_operation": true,
  "allow_destructive_operation": false
}
```

This configuration must block before outbound execution with `PAYLOAD_VALIDATION_ERROR`. Missing `allow_destructive_operation` is equivalent to `false`.

### Data Pool File

#### Purpose

Client-scoped reusable dataset for `data_pool` payload strategy.

#### Primary Key

S3 object key: `data-pools/{client_id}/{pool_name}.json`.

#### Accepted Schema

Phase 2 must accept both a plain array of JSON record objects and a wrapped object with a `records` array. The wrapped object form is preferred for new data-pool files because it leaves room for future metadata without changing the record container shape.

Preferred wrapped schema:

```json
{
  "records": [
    {
      "user_id": "user-001",
      "email": "example@example.test",
      "account_type": "trial"
    }
  ]
}
```

Also accepted plain-list schema:

```json
[
  { "user_id": "user-001" }
]
```

The loader normalizes both forms to an internal records array. Wrapped object metadata fields, if present in the future, must be ignored by Phase 2 unless a later design explicitly consumes them.

Records must be non-empty JSON objects. Empty files, malformed JSON, empty arrays, non-object records, or records that cannot produce the configured payload fail with `PAYLOAD_VALIDATION_ERROR` before outbound execution.

#### Ownership Model

Scoped by `client_id` path segment. The loader must not allow `pool_name` to escape `data-pools/{client_id}/`.

#### Lifecycle

Phase 2 reads data pools only. It does not create, update, delete, archive, or validate pools outside run execution.

### PreparedPayloadResult

#### Purpose

Internal handoff from payload preparation to runner.

#### Fields

| Field | Type | Safe to Persist | Description |
| --- | --- | --- | --- |
| `payload` | object/string/null | No | Final request body for outbound execution. |
| `payload_fingerprint` | string | Yes | SHA-256 hex of canonical sanitized payload/effective body. |
| `metadata.payload_strategy` | string | Yes | Resolved strategy. |
| `metadata.payload_metadata.payload_fingerprint` | string | Yes | SHA-256 hex of canonical sanitized payload/effective body. |
| `metadata.payload_metadata.duplicate_check_scope` | string | Yes | Resolved scope. |
| `metadata.payload_metadata.duplicate_detected` | boolean | Yes | Whether a duplicate was observed. |
| `metadata.payload_metadata.duplicate_policy` | string | Yes | Resolved policy. |
| `metadata.payload_metadata.duplicate_allowed` | boolean | Yes | True only when policy allowed a detected duplicate; false when no duplicate was detected. |
| `metadata.payload_metadata.generation_attempt` | integer | Yes | Initial attempt is `1`; max `5` for regenerate. |
| `metadata.payload_metadata.data_pool_name` | string/null | Yes | Pool name for `data_pool`, or null. |
| `metadata.payload_metadata.data_pool_record_fingerprint` | string/null | Yes | SHA-256 hex of canonical sanitized selected record, or null. |

### Duplicate Registry Entry

#### Purpose

In-run duplicate prevention state.

#### Primary Key

In memory by tuple:

```text
(scope_name="current_run", client_id, audit_id, run_id, duplicate_subject_type, fingerprint)
```

`duplicate_subject_type` is `payload` for final payload fingerprints and `data_pool_record` for selected data-pool record reuse checks.

#### Fields

| Field | Type | Description |
| --- | --- | --- |
| `fingerprint` | string | SHA-256 canonical sanitized fingerprint. |
| `endpoint_id` | string | Endpoint that reserved the fingerprint. |
| `iteration` | integer | Iteration that reserved the fingerprint. |
| `payload_strategy` | string | Strategy used. |
| `reserved_at` | string | UTC timestamp for operational debugging; sanitized safe. |

#### Lifecycle

Created during payload preparation before outbound execution. Exists only for the duration of the current run in Phase 2.

### Raw Result Schema v1 Extension

#### Purpose

Record payload handling evidence without unsafe values.

#### Fields Added to Each Endpoint Record Where Applicable

| Field | Type | Required When | Description |
| --- | --- | --- | --- |
| `response_fingerprint` | string/null | When response evidence exists | SHA-256 of canonical sanitized response representation; null/no field if no response. |
| `payload_strategy` | string | All endpoint records | Top-level field. Resolved `static`, `generated`, or `data_pool`. Phase 1 already included strategy label; Phase 2 makes values strict. |
| `payload_metadata` | object | When payload preparation is attempted | Nested object containing Phase 2-specific safe payload metadata. |

`payload_metadata` fields:

| Field | Type | Required When | Description |
| --- | --- | --- | --- |
| `payload_fingerprint` | string | When payload/effective body known, including absent/no-body payloads | SHA-256 of canonical sanitized final payload/effective body. For absent/no-body payloads, compute SHA-256 over canonical sentinel `EMPTY_PAYLOAD`. |
| `duplicate_check_scope` | string | When duplicate check configured/performed | Default `current_run`. |
| `duplicate_detected` | boolean | When duplicate check performed | True if duplicate detected at any attempt. |
| `duplicate_policy` | string | When duplicate check performed | Default `regenerate`. |
| `duplicate_allowed` | boolean | When duplicate check performed | True when policy `allow` proceeds after duplicate detection; false when no duplicate was detected. |
| `generation_attempt` | integer | Generated/data-pool and duplicate-checked static payloads | Attempt used; initial attempt `1`. |
| `data_pool_name` | string/null | Always in `payload_metadata` | Configured safe pool name for `data_pool`; null otherwise. |
| `data_pool_record_fingerprint` | string/null | Always in `payload_metadata` | SHA-256 of canonical sanitized selected record for `data_pool`; null otherwise. |

Required nesting example:

```json
{
  "raw_result_version": "v1",
  "payload_strategy": "generated",
  "payload_metadata": {
    "payload_fingerprint": "...",
    "duplicate_check_scope": "current_run",
    "duplicate_detected": false,
    "duplicate_policy": "regenerate",
    "duplicate_allowed": false,
    "generation_attempt": 1,
    "data_pool_name": null,
    "data_pool_record_fingerprint": null
  }
}
```

Do not persist raw final payload, generated substitutions, raw selected data-pool record, resolved secrets, tokens, credentials, cookies, PII, or sensitive values.

## 8. API Contracts

Phase 2 introduces no public HTTP API and does not change the Phase 1 Lambda invocation event contract. The only runtime contract change is internal: the orchestrator/runner pass run context and endpoint config to payload preparation before outbound execution.

## 9. Frontend Impact

### Components Affected

None. Phase 2 is backend-only.

### API Integration

None. No frontend API integration is introduced.

### UI States

None.

## 10. Backend Logic

### Responsibilities

- Resolve payload strategy per endpoint.
- Validate payload configuration and safety before outbound requests.
- Prepare deterministic generated payloads.
- Load and select data-pool records deterministically.
- Compute sanitized canonical fingerprints.
- Enforce duplicate prevention policy.
- Add safe payload metadata to raw results with `payload_strategy` top-level and Phase 2 details nested under `payload_metadata`.

### Validation Flow

1. Validate Phase 1 event/config identifiers first.
2. Validate endpoint `payload_strategy`:
   - if missing and body is absent or static body exists safely, resolve `static`;
   - if missing and request requires/generated/data-pool configuration is implied, fail with `PAYLOAD_VALIDATION_ERROR`.
3. Validate `payload_safety`:
    - `generated` requires `allow_generated_payloads = true`;
    - data-pool reuse is controlled by `allow_data_pool_reuse`;
    - if `destructive_operation = true` and `allow_destructive_operation != true`, fail closed with `PAYLOAD_VALIDATION_ERROR`; missing `allow_destructive_operation` defaults to `false`.
4. Validate duplicate settings from `duplicate_policy` and `duplicate_check_scope`; apply defaults: policy `regenerate`, scope `current_run`. Reject any non-`current_run` scope in Phase 2.
5. Validate strategy payload/data-pool fields from `payload_template`, `payload_iterations`, and `data_pool_name`.
6. Resolve payload/data-pool record for attempt `1`. For `data_pool`, select the data-pool record first; use it as the full request payload when `payload_template` is absent/null, or as the substitution source when `payload_template` is configured.
7. Sanitize and canonicalize final payload/effective body, then compute fingerprint.
8. Atomically check/reserve duplicate fingerprints.
9. Apply duplicate policy:
   - `regenerate`: if duplicate and strategy can regenerate, retry with attempt `2` through `5`; if still duplicate, fail `PAYLOAD_VALIDATION_ERROR`.
   - `fail_fast`: fail immediately on duplicate.
   - `allow`: reserve/proceed and set `duplicate_allowed = true` only when a duplicate was detected and allowed; set/prefer `duplicate_allowed = false` when no duplicate was detected.
10. Return prepared payload to runner or failure metadata to raw result builder.

### Business Rules

- Static payloads never perform Phase 2 variable substitution.
- Static payloads containing `{{...}}` Phase 2 token syntax fail unless strategy is `generated` or `data_pool` with an explicit payload template.
- Unknown or malformed variables always fail before outbound execution.
- All generation is deterministic for identical context and attempt.
- HTTP retries reuse the prepared payload and metadata; they do not regenerate payloads.
- Duplicate checking uses fingerprints of sanitized canonical representations, not raw payload bytes.
- Absent/no-body payloads use canonical sentinel `EMPTY_PAYLOAD` for fingerprinting, not JSON `null` or an empty string.
- Data-pool record reuse check uses `data_pool_record_fingerprint`; final payload duplicate check uses `payload_fingerprint`.
- Data-pool strategy default mapping is selected record as full request payload when no `payload_template` is provided.
- Data-pool strategy template mapping uses the selected record only as an in-memory substitution source and never persists the selected record's raw values.
- Destructive operations default blocked. If `payload_safety.destructive_operation = true`, execution requires `payload_safety.allow_destructive_operation = true`. Missing `allow_destructive_operation` is treated as `false`.
- Raw result records keep `payload_strategy` top-level and put Phase 2-specific details under `payload_metadata`; do not emit duplicated top-level Phase 2 metadata fields such as `payload_fingerprint`, `duplicate_policy`, or `data_pool_record_fingerprint`.
- Production safeguards: configs for production-like endpoints must not rely on missing safety defaults. The validator should fail closed for generated/data-pool/destructive ambiguity rather than infer permissive behavior.

### Persistence Flow

- No new Phase 2 persisted table is required for default `current_run` scope.
- Raw result persistence remains Phase 1 single S3 write to `raw-results/{client_id}/{audit_id}/{run_id}/results.json`.
- Data pools are read from S3 only.
- Audit-wide duplicate scope is not implemented in Phase 2. If future audit-wide duplicate scope is implemented using DynamoDB or another persistent store, it must use conditional writes/atomic reservation semantics and must be documented before enabling.

### Error Handling

| Failure Condition | Classification / Handling |
| --- | --- |
| Missing/invalid strategy requiring body | Endpoint raw result `failure_type = PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Static payload contains variable token | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Unknown/malformed variable | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Generated strategy not explicitly allowed | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| `destructive_operation = true` and `allow_destructive_operation != true` or missing | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Missing/unreadable/empty/invalid data pool | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Data-pool template references missing/invalid record field | `PAYLOAD_VALIDATION_ERROR`; no request sent. |
| Duplicate + `fail_fast` | `PAYLOAD_VALIDATION_ERROR`; metadata reflects duplicate detected. |
| Duplicate + `regenerate` exhausted after 5 attempts | `PAYLOAD_VALIDATION_ERROR`; metadata reflects duplicate detected and final attempt `5`. |
| Duplicate + `allow` | Request proceeds; metadata includes `duplicate_detected = true`, `duplicate_policy = "allow"`, `duplicate_allowed = true`. |
| No duplicate detected with any policy | Request proceeds; metadata includes `duplicate_detected = false` and should include `duplicate_allowed = false` for analytics consistency. |
| Fingerprint/sanitization failure | Fail closed with `PAYLOAD_VALIDATION_ERROR` before request for payload fingerprint failures; response fingerprint failure after response should produce sanitized `RUNNER_ERROR` only if raw evidence cannot be safely produced. |

## 11. File Structure

Expected implementation locations:

```text
packages/data-generation/
  generator.py            # PayloadPreparationService and deterministic generation orchestration
  templates.py            # variable token detection, field-path traversal, substitution
  validators.py           # strategy, payload, data-pool, safety validation
  duplicate_checker.py    # run-scoped duplicate registry and policy helpers
  data_pools.py           # new data-pool loading/normalization wrapper, if not placed elsewhere
  fingerprints.py         # new canonicalization + SHA-256 utility, if not placed in core
apps/backend/orchestrator/
  # capture run_timestamp, initialize duplicate checker, pass run context
apps/backend/runner/
  # invoke payload preparation, response fingerprinting, raw result metadata integration
packages/config/
  # endpoint config schema validation additions
packages/sanitization/
  # reuse existing sanitizer before fingerprinting persisted/logged representations
packages/storage/s3_client.py
  # existing S3 read wrapper used by DataPoolLoader
tests/unit/data_generation/
  # generator, templates, validator, duplicate checker, fingerprint tests
tests/integration/
  # runner/orchestrator payload preparation with mocked S3 and mock API
docs/architecture/phase_2_payload_data_generation_technical_design.md
```

## 12. Security

### Authentication

No application-level authentication is introduced. Lambda invocation remains controlled by AWS IAM/deployment configuration from Phase 1.

### Authorization

No RBAC or tenant user authorization is introduced. Data access is scoped by validated identifiers:

- Data pools under `data-pools/{client_id}/`.
- Raw results under `raw-results/{client_id}/{audit_id}/{run_id}/`.
- Duplicate scope defaults to one validated current run.

### Input Validation

- Validate `pool_name` as a safe identifier; reject slashes, backslashes, dots/traversal, URL-encoded traversal-like content, whitespace/control characters, and empty values.
- Validate endpoint `payload_strategy`, duplicate policy, duplicate scope, and safety fields with allowlists.
- Validate generated templates for unknown/malformed tokens.
- Validate content type/payload type compatibility before outbound execution.
- Validate data-pool JSON structure and non-empty record set.

### Sensitive Data Handling

- Use raw payload/data-pool values only in memory for request construction/execution.
- Never log or persist raw generated values or raw data-pool records.
- Fingerprint order is sanitize -> canonicalize -> SHA-256.
- Existing sanitizer redacts secrets, tokens, credentials, cookies, PII, and sensitive fields before fingerprinting persisted/logged representations.
- Resolved Secrets Manager values must not be included in payload metadata or fingerprints unless they are part of an outbound payload representation that is first sanitized; preferable design is to exclude resolved secret-bearing headers from payload fingerprint and let request/response evidence fingerprint only safe payload/body content.

### Misuse Risks

- Misconfigured generated payloads could create production data. Safety config fails closed, and destructive endpoints require explicit allow.
- Data-pool names could attempt path traversal. Validate before S3 key construction.
- Operators could permit duplicates unintentionally. Defaults prohibit duplicates through `regenerate`; `allow` records explicit `duplicate_allowed` metadata.
- Sanitized fingerprints are not reversible in practice but can still correlate equivalent sanitized values; treat fingerprints as client-scoped evidence, not public identifiers.

## 13. Reliability

### Failure Modes

- Payload validation failures are endpoint-local and should not necessarily stop unrelated endpoints, matching Phase 1 endpoint failure behavior.
- Missing global dependencies such as config/S3 wrappers can fail the run according to Phase 1 orchestrator rules.
- Data-pool load failures for an endpoint fail that endpoint before outbound execution.
- Duplicate registry is in-memory; Lambda/process restart loses state, but current-run execution state is rebuilt during a single invocation.

### Retries

- Duplicate `regenerate` attempts are payload preparation attempts, not HTTP retries.
- Maximum generation attempts for `regenerate` is `5` including the initial attempt.
- HTTP retry behavior remains Phase 1 behavior and must not trigger payload regeneration.
- AWS SDK retries may use existing wrapper behavior; do not hide missing data-pool validation failures with excessive retries.

### Timeouts

- Data-pool S3 reads rely on existing S3 client timeout/default SDK behavior.
- Outbound request timeouts remain Phase 1 runner timeout behavior.

### Logging / Monitoring

- Emit sanitized operational logs for payload preparation start/failure/success using safe identifiers and metadata only.
- Log duplicate events with safe fields: strategy, scope, policy, endpoint_id, iteration, generation_attempt, and fingerprint prefix only if project logging policy permits. Full fingerprints are acceptable in raw results; logs may use full or truncated fingerprints after sanitizer.
- Do not log raw payload, selected data-pool record, generated UUID values, or resolved secrets.

### Performance Considerations

- Cache data pools per run by `(client_id, pool_name)`.
- Canonicalization should sort object keys deterministically and avoid unnecessary repeated serialization.
- In-memory duplicate registry size is proportional to endpoint iterations; Phase 2 does not target load-testing scale.

## 14. Dependencies

- Phase 1 orchestrator, runner, raw result builder/schema v1, and evidence sink.
- Phase 1 S3 wrapper for config/data-pool reads and raw result writes.
- Phase 1 DynamoDB wrapper only if future audit-wide duplicate scope is explicitly enabled.
- Phase 1 sanitizer and structured logging utilities.
- Phase 1 exception/failure classification support for `PAYLOAD_VALIDATION_ERROR`.
- Python standard libraries for hashing, JSON serialization, UUID formatting, and synchronization primitives.

## 15. Assumptions

### Confirmed Assumptions

- Phase 2 supports exactly `static`, `generated`, and `data_pool` strategies.
- `{{uuid}}` uses deterministic context including field path and `token_index`.
- Repeated `{{uuid}}` tokens in the same field use zero-based `token_index` determined left-to-right per field path.
- `{{timestamp}}` is captured once at run level.
- Data pools live at `data-pools/{client_id}/{pool_name}.json`.
- Data-pool mapping supports selected record as full request payload and selected record as substitution source for payload template; selected record as full payload is the default when no template is provided.
- Destructive operation execution requires `allow_destructive_operation = true`; its default is `false`.
- Duplicate default and only supported Phase 2 scope is `current_run`.
- `current_run` duplicate reservation uses an in-memory tracker per orchestrator run with scope key including `client_id + audit_id + run_id`.
- Audit-wide duplicate tracking is out of scope until a persistent reservation design is approved.
- Raw results preserve `raw_result_version = "v1"`, keep top-level `payload_strategy`, and nest Phase 2 details under `payload_metadata`.
- Endpoint Phase 2 config uses the confirmed flat field shape: `payload_strategy`, `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`.
- Data-pool JSON accepts both plain list and wrapped `{ "records": [...] }` object; wrapped object is preferred for future metadata.
- Absent/no-body payload fingerprint uses canonical sentinel `EMPTY_PAYLOAD`.
- `duplicate_allowed` is true only when `duplicate_policy = allow` detected and allowed a duplicate; no-duplicate cases should emit/prefer `false`.

### Technical Assumptions Requiring Confirmation

- Initial/default endpoint iteration is `1` when no iteration system exists in Phase 1.
- Static payload/body field naming remains whatever Phase 1 already uses unless the implementation has standardized all request bodies on `payload_template`; Phase 2 confirmed fields apply to generated/data-pool behavior.

## 16. Risks / Open Questions

- **Audit-wide duplicate detection:** Future scope requires persisted reservation state and conditional writes. In-memory Phase 2 duplicate checking is not sufficient across Lambda invocations or runs.
- **Data-pool substitution syntax compatibility:** This design defines record-field tokens as `{{field_name}}` / `{{nested.field}}` for implementation clarity. Existing configs using unknown generated tokens may now be interpreted as data-pool field references only under `data_pool` strategy with a selected record; validators must keep strategy-specific behavior explicit.
- **Raw result consumers:** Consumers expecting Phase 2 metadata at top level must be updated to read nested `payload_metadata`, while `payload_strategy` remains top-level for backward-compatible discovery.

## 17. Implementation Notes

### Fingerprint Canonicalization Algorithm

1. Accept raw value to fingerprint: final effective payload/body, response evidence body, or selected data-pool record.
2. Apply existing sanitizer first. If sanitization fails or cannot guarantee safe output, fail closed for payload/data-pool preparation; for response, omit unsafe body and record a safe failure according to runner policy.
3. Canonicalize sanitized value:
   - JSON objects: recursively sort keys lexicographically; serialize without insignificant whitespace; preserve arrays in order; use UTF-8; represent `null`, booleans, numbers, and strings using standard JSON encoding.
   - Strings/non-JSON bodies: use exact sanitized string bytes in UTF-8 with a type prefix such as `string:` to avoid collision with JSON serialization.
   - Absent/no-body payloads: use the exact canonical sentinel string `EMPTY_PAYLOAD`.
   - Bytes/binary-like responses: do not persist raw bytes; use sanitized safe placeholder or metadata indicator before fingerprinting.
4. Compute SHA-256 over canonical bytes.
5. Store lowercase hex digest.

Recommended canonical byte prefixing:

```text
json:<canonical-json>
string:<sanitized-string>
empty:EMPTY_PAYLOAD
binary:<safe-placeholder>
```

For `payload_fingerprint` specifically, an absent/no-body payload is the SHA-256 digest of canonical string `EMPTY_PAYLOAD` as confirmed for Phase 2. Implementers may include an internal `empty:` type prefix for generic utility dispatch only if tests verify the externally recorded fingerprint follows the confirmed `EMPTY_PAYLOAD` canonical string contract.

### Duplicate Prevention Algorithm

For each endpoint iteration:

1. Resolve `policy = duplicate_policy || "regenerate"`.
2. Resolve `scope = duplicate_check_scope || "current_run"`; reject any value other than `current_run` in Phase 2.
3. Build `scope_key` for `current_run` from validated `client_id`, `audit_id`, and `run_id`.
4. For `attempt` from `1` to `5` when policy is `regenerate`; otherwise only `1`:
   - Prepare deterministic payload using attempt in seed context. For repeated same-field `{{uuid}}` tokens, include zero-based `token_index` in each UUID seed.
   - Compute `data_pool_record_fingerprint` if applicable.
   - Compute `payload_fingerprint`.
   - If data-pool reuse is disallowed, check/reserve selected record fingerprint first.
   - Check/reserve payload fingerprint.
   - If neither duplicate, return success metadata with `duplicate_detected = false` and `duplicate_allowed = false`.
   - If duplicate and policy is `allow`, return success metadata with `duplicate_detected = true` and `duplicate_allowed = true`.
   - If duplicate and policy is `fail_fast`, fail `PAYLOAD_VALIDATION_ERROR`.
   - If duplicate and policy is `regenerate`, continue to next attempt.
5. If all regenerate attempts are duplicates, fail `PAYLOAD_VALIDATION_ERROR` with final safe metadata.

For `data_pool` strategy, regeneration attempt salt may alter generated/template-derived parts only. It does not alter deterministic pool index unless implementation explicitly includes attempt in a documented fallback. If a one-record pool is reused while reuse is disallowed, `regenerate` will likely exhaust and fail; this is acceptable per edge cases. When no template is provided, the selected record is the full payload and regeneration cannot change it.

### QA / Test Strategy

Unit tests must cover:

- Strategy resolution defaults and invalid strategy rejection.
- Confirmed flat endpoint config field handling: `payload_template`, `payload_iterations`, `duplicate_policy`, `duplicate_check_scope`, `data_pool_name`, and `payload_safety`; nested legacy Phase 2 objects are not required.
- Static pass-through and static token rejection.
- Supported generated variables and unknown/malformed variable rejection.
- Run-level timestamp reuse across endpoints/iterations.
- UUID determinism for same context and differentiation by field path, zero-based same-field `token_index`, and attempt.
- Repeated `{{uuid}}` in the same string resolves with stable left-to-right token indexes, resets per field path, and ignores non-UUID tokens for index counting.
- Data-pool S3 key construction, missing/invalid/empty pool failures, deterministic assignment, accepted plain-list schema, accepted wrapped `{ "records": [...] }` schema, wrapped-object normalization, selected-record-as-full-payload default, selected-record-as-template-substitution-source behavior via `payload_template`, and missing record-field failures.
- Fingerprint canonicalization for equivalent JSON with different key ordering.
- Absent/no-body payload fingerprint equals SHA-256 of canonical string `EMPTY_PAYLOAD`.
- Sanitization-before-fingerprint ordering and absence of raw unsafe values in metadata.
- Duplicate policies: `regenerate`, exhaustion, `fail_fast`, `allow`, default policy, default scope, `current_run` scope key containing `client_id + audit_id + run_id`, and validation failure for audit-wide/non-`current_run` scope.
- `duplicate_allowed` metadata: true only when an actual duplicate was detected and allowed under policy `allow`; false when no duplicate was detected.
- Concurrent duplicate reservation with multiple threads/tasks within a run.
- Safety enforcement: generated blocked unless allowed, data-pool reuse policy, `destructive_operation = true` blocked unless `allow_destructive_operation = true`, and default `allow_destructive_operation = false`.
- Raw result metadata nesting: `payload_strategy` top-level, Phase 2 details under `payload_metadata`, no unsafe values exposed, and `raw_result_version = "v1"` preservation.

Integration tests must cover:

- Orchestrator/runner execution with mocked S3 data-pool objects and local mock API.
- No outbound request occurs for `PAYLOAD_VALIDATION_ERROR` cases.
- Successful generated payload execution records safe metadata and fingerprints.
- Successful generated payload execution using the confirmed example shape records `duplicate_allowed = false` when no duplicate occurs.
- Successful data-pool execution records pool name and record fingerprint under `payload_metadata` without raw record contents, for both full-payload and `payload_template` substitution modes, using both accepted data-pool JSON container shapes.
- No-body endpoint execution records the confirmed `EMPTY_PAYLOAD` fingerprint.
- Response fingerprint generated from sanitized canonical response evidence.
- HTTP retry reuses the same prepared payload.

### Backend Agent Guidance

- Keep Phase 2 behind internal module boundaries; do not add public APIs.
- Centralize constants for strategy names, policy names, scope names, max generation attempts, token names, and raw result metadata field names.
- Treat payload values as unsafe by default; only metadata/fingerprints are safe to persist.
- Prefer small pure functions for hashing, canonicalization, token parsing, and field-path generation to make determinism easy to test.
- Do not infer destructive behavior solely from HTTP method unless product confirms this. Use explicit endpoint configuration and fail closed on ambiguity.
- Do not implement audit-wide duplicate persistence in the same PR unless scoped and tested separately; expose a clear validation error for unsupported non-`current_run` scope if needed.
