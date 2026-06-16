# Technical Design

## 1. Feature Overview

Phase 4A formalizes, validates, and extends the deterministic aggregation foundation from Phase 4. It introduces the Engineering Retrieval Layer, publishes the Phase 5 consumer contract, eliminates brownfield operational debt, and completes an operational validation campaign.

This technical design defines:

- The aggregation architecture confirmation scope (Phase 4A.4).
- The Engineering Retrieval Layer design (Phase 4A.5).
- The Phase 5 consumer contract technical boundary (Phase 4A.3).
- The `src/packages` divergence remediation strategy (Phase 4A.6).
- Structured logging improvements across all lifecycle stages (Phase 4A.5).

This design explicitly does not implement or modify reliability intelligence, scoring, reports, dashboards, or Phase 5 behavior.

## 2. Phase 4 Implementation Baseline

Phase 4 delivered the following components, all present and operational on `main`:

| Component | Location |
| --- | --- |
| Aggregation trigger handler | `apps/backend/handlers/aggregation_handler.py` |
| Aggregation orchestrator | `src/release_confidence_platform/aggregation/orchestrator.py` |
| Eligibility service | `src/release_confidence_platform/aggregation/eligibility.py` |
| Evidence integrity validator | `src/release_confidence_platform/aggregation/integrity.py` |
| Aggregation engine | `src/release_confidence_platform/aggregation/engine.py` |
| Lineage manifest repository | `src/release_confidence_platform/aggregation/lineage.py` |
| Aggregate repository | `src/release_confidence_platform/aggregation/repository.py` |
| Identity resolver | `src/release_confidence_platform/aggregation/identity.py` |
| Constants and models | `src/release_confidence_platform/aggregation/constants.py`, `models.py` |
| Events | `src/release_confidence_platform/aggregation/events.py` |
| Finalization handler (intent) | `apps/backend/handlers/audit_finalization_handler.py` |
| IAM resources | `infra/resources/phase4-aggregation-iam.yml` |

Phase 4A builds on this foundation without modifying the core aggregation contract.

## 3. Phase 4A.4 — Aggregation Persistence Confirmation

### Scope

Phase 4A.4 confirms Phase 4 aggregation persistence is production-ready. This includes:

- Validating the DynamoDB write paths for all aggregate record types.
- Confirming idempotent behavior under retry scenarios.
- Confirming aggregate-set completion marker is written atomically.
- Confirming immutability enforcement via conditional writes.

### Acceptance Boundary

Phase 4A.4 is complete when:

- At least one full aggregation cycle completes end-to-end with all artifact types persisted.
- Duplicate trigger produces `DUPLICATE_COMPLETED` without new aggregate writes.
- Retry after a simulated failure produces exactly one aggregate set.

### Out of Scope

Phase 4A.4 does not modify aggregation logic, add new aggregate types, or introduce schema changes.

## 4. Phase 4A.5 — Engineering Retrieval Layer

### Constitutional Invariant

The Engineering Retrieval Layer is a **platform invariant**. It SHALL NEVER create, update, delete, repair, recompute, compact, or otherwise modify persisted audit evidence, aggregation artifacts, lineage manifests, lifecycle records, or any platform state.

Allowed operations are limited to: **inspect**, **retrieve**, **list**, **summarize**, **verify**, and **export**.

This invariant is unconditional and applies regardless of requested output format, filtering parameters, or operational context. Violation of this invariant compromises evidence integrity and trustworthiness.

### Design Philosophy

The Engineering Retrieval Layer is an internal engineering tool. Its purpose is operational debugging, evidence inspection, audit traceability, and engineering support. It is not customer-facing, not operator-facing, and not a reporting surface.

Engineering Retrieval Layer and any future customer-facing evidence retrieval capability must remain separate bounded contexts. Engineering retrieval is an internal operational capability. Customer evidence delivery belongs to a future roadmap phase and must not reuse or expose engineering retrieval interfaces directly.

### Architecture

The Engineering Retrieval CLI is implemented as a new `rcp retrieve` subcommand group within the existing operator CLI infrastructure. It reuses existing DynamoDB/S3 access patterns and identifier validation.

```
rcp retrieve <command> [--client <id>] [--audit <id>] [--output json|human] [options]
```

The retrieval layer follows strict bounded-context layering. CLI commands must never interact with storage implementation details directly:

```
CLI Command  (argument parsing + output formatting only)
    ↓
RetrievalService  (query logic, filtering, immutable DTO construction)
    ↓
RetrievalRepository  (storage provider interactions only)
    ↓
Storage Provider  (DynamoDB / S3)
```

### Retrieval Output Provenance

Every retrieval command output must include a provenance envelope as the outermost wrapper:

```json
{
  "_notice": "This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.",
  "retrieved_at": "<UTC ISO-8601>",
  "retrieval_version": "<retrieval layer version>",
  "aggregation_version": "<aggregation_version of retrieved artifact>",
  "manifest_hash": "<aggregate_set_hash from AggregateSetCompletion marker, or null>",
  "audit_id": "<scoped audit identifier>",
  "client_id": "<scoped client identifier>",
  "data": { ... }
}
```

For human-readable output, the disclaimer must appear at the top of every retrieval response.

### Deterministic Retrieval Ordering

The retrieval layer must produce deterministically ordered output for all collections. For identical persisted aggregation state, retrieval output must be identical across repeated invocations.

Canonical ordering precedence for all collections:

1. `audit_id` (lexicographic ascending)
2. `audit_execution_id` (lexicographic ascending)
3. `endpoint_id` (lexicographic ascending)
4. `scenario_id` (lexicographic ascending)
5. `timestamp` (UTC ascending)

### Component: RetrievalService

Suggested location: `src/release_confidence_platform/retrieval/service.py`

Responsibilities:
- Accept validated retrieval parameters.
- Query DynamoDB through `RetrievalRepository` only (never directly to storage).
- Apply filtering by client, audit, run, endpoint, scenario, or window.
- Return **immutable snapshot DTOs** only. DTOs must not be mutated after construction.
- Never write, update, or delete records.
- Enforce sensitive data exclusion on all returned fields.

### Component: RetrievalRepository

Suggested location: `src/release_confidence_platform/retrieval/repository.py`

Responsibilities:
- Execute all DynamoDB and S3 read operations.
- Own all storage provider interactions.
- Return raw storage records to `RetrievalService` for DTO construction.
- Never accept write, update, or delete operations.

### Component: RetrievalFormatter

Suggested location: `src/release_confidence_platform/retrieval/formatter.py`

Responsibilities:
- Accept immutable retrieval DTOs. Must not mutate retrieval objects.
- Format as machine-readable JSON or human-readable text.
- Apply canonical serialization normalization before output generation:
  - Field ordering: canonical alphabetical or defined priority order
  - Collection ordering: canonical precedence per deterministic ordering rules above
  - Timestamp formatting: UTC ISO-8601
  - Numeric precision: consistent decimal representation
- Produce byte-identical serialized JSON output for identical input DTOs across invocations.
- Prepend provenance envelope on all output.

### Command Implementations

| Command | DynamoDB Query Pattern | Notes |
| --- | --- | --- |
| `aggregation-results` | `PK = CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}#EXEC#...#AGG#` | Returns all aggregate record types for an aggregate set |
| `aggregation-metadata` | `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#AGGJOB#...` | Latest job metadata |
| `aggregation-lineage` | `SK = AUDIT#{audit_id}#EXEC#...#LINEAGE#...` | Manifest refs and source ref counts |
| `aggregation-status` | Latest `AggregationJob` record | Status, failure_category, reason_code |
| `orchestration-timeline` | Lifecycle history items under audit key | Ordered by timestamp |
| `lifecycle-transitions` | Lifecycle history items | State machine trace |
| `execution-summary` | Completed run metadata items | Count, duration, outcome |
| `audit-event-timeline` | All items under `PK = CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}#` | Full event order |
| `engineering-logs` | Sanitized structured log query; or read from consolidated audit metadata | Operational events only |
| `retry-history` | All `AGGJOB` items for audit | Multiple job attempts |
| `aggregation-generation-status` | `AggregateSetCompletion` marker and latest job | Completeness proof |
| `aggregation-version` | `AggregateSetCompletion` or latest aggregate record | `aggregation_version` field |
| `evidence-references` | `LineageManifest` records | Source refs |
| `failure-summaries` | `FailureClassificationAggregate` records | Classification counts |
| `processing-timeline` | Job metadata timestamps | Per-stage timing |

### Sensitive Data Handling

The RetrievalService must apply the same allowed-field contract used by Phase 4 aggregation:

- Output contains only: sanitized identifiers, counts, distributions, timestamps, versions, bounded source references, and controlled reason codes.
- Output must not contain: raw request/response bodies, headers, cookies, tokens, credentials, PII, raw URLs, query strings, raw S3 keys, or payload content.
- Raw S3 key values must be represented as sanitized key hashes or short references in engineering output.

### File Structure Additions

```text
src/release_confidence_platform/retrieval/
  __init__.py
  commands.py      (CLI command definitions — argument parsing + output only)
  service.py       (RetrievalService — immutable DTOs, query logic, filtering)
  repository.py    (RetrievalRepository — storage provider interactions)
  formatter.py     (RetrievalFormatter — canonical serialization + provenance)
  filters.py       (filter validation and application)
  dtypes.py        (immutable DTO definitions)

tests/unit/retrieval/
  test_retrieval_commands.py
  test_retrieval_formatter.py
  test_retrieval_sensitive_data.py
  test_retrieval_filtering.py
  test_retrieval_provenance.py
  test_retrieval_determinism.py
```

## 5. Phase 4A.5 — Structured Logging Improvements

### Logs Are Not Evidence

Structured logs are operational diagnostics. They shall never become authoritative evidence or replace immutable aggregation artifacts.

The platform evidence hierarchy is:

```
Raw execution evidence (S3)
    ↓
Aggregation artifacts (DynamoDB)
    ↓
Lineage manifests (DynamoDB)
    ↓
AggregateSetCompletion marker (DynamoDB)
```

Structured logs support debugging but are not part of this chain. Any operational conclusion derived solely from logs — not from immutable aggregation artifacts — must be treated as advisory only.

### Current State

Structured logging exists but coverage is inconsistent across lifecycle stages. Some stages emit rich structured events; others emit ad hoc strings that prevent programmatic correlation.

### Required Log Events

Every lifecycle stage must emit at minimum the following structured events:

**Orchestration**
- `aggregation_job_claimed` — job_id, audit_id, client_id, aggregation_version
- `aggregation_eligibility_evaluated` — result (eligible/ineligible), reason_code
- `aggregation_integrity_gate_evaluated` — result (pass/fail), expected_count, observed_count, reason_code
- `aggregation_manifest_write_started` — manifest scope, source_ref_count
- `aggregation_set_completed` — aggregate_record_count, endpoint_count, manifest_count
- `aggregation_job_failed` — failure_category, reason_code, component

**Scheduling**
- `audit_schedule_created` — audit_id, client_id, schedule_expression
- `execution_window_opened` — audit_id, window start
- `execution_window_closed` — audit_id, window end, execution_count

**Execution**
- `run_started` — run_id, audit_id, endpoint_id
- `run_completed` — run_id, outcome, duration_ms
- `evidence_captured` — run_id, result_count

**Lifecycle**
- `lifecycle_transition` — audit_id, from_state, to_state, actor, reason

**Finalization**
- `finalization_eligibility_evaluated` — audit_id, result, reason
- `finalization_gate_evaluated` — result, execution_count
- `aggregation_intent_recorded` — aggregation_job_id, audit_id
- `aggregation_invocation_status` — status (requested/failed)

### Log Field Standard

All structured log events must include:

```json
{
  "timestamp": "<UTC ISO-8601>",
  "level": "<DEBUG|INFO|WARNING|ERROR>",
  "service": "<handler or component name>",
  "stage": "<scheduling|execution|lifecycle|finalization|aggregation|retrieval>",
  "event_type": "<event name from above>",
  "client_id": "<sanitized id>",
  "audit_id": "<sanitized id>",
  "run_id": "<sanitized id, if applicable>",
  "aggregation_job_id": "<sanitized id, if applicable>",
  "correlation_id": "<request correlation id, if available>"
}
```

Logs must not include `endpoint_id` values that contain unsafe raw content. Sanitize or omit.

## 6. Phase 4A.6 — src/packages Divergence Remediation

### Current State

Two directory trees contain copies of the same modules:

| src path | packages path |
| --- | --- |
| `src/release_confidence_platform/audit_lifecycle/` | `packages/audit_lifecycle/` |
| `src/release_confidence_platform/audit_scheduling/` | `packages/audit_scheduling/` |
| `src/release_confidence_platform/config/` | `packages/config/` |
| `src/release_confidence_platform/core/` | `packages/core/` |
| `src/release_confidence_platform/data_generation/` | `packages/data_generation/` |
| `src/release_confidence_platform/operator_cli/` | `packages/operator_cli/` |
| `src/release_confidence_platform/sanitization/` | `packages/sanitization/` |
| `src/release_confidence_platform/storage/` | `packages/storage/` |

The `packages/` tree also contains `data-generation/` and `report-engine/` directories that have no `src/` counterparts.

The `src/release_confidence_platform/aggregation/` module has no `packages/` copy.

### Remediation Strategy

Phase 4A.6 will:

1. **Audit divergence** — compare each divergent module pair and document behavioral differences.
2. **Establish authority** — `src/release_confidence_platform/` is the canonical implementation. Lambda functions import from `src/`.
3. **Synchronize** — apply changes from `src/` to `packages/` where they diverge, or remove `packages/` copies where the import path is not used by deployed code.
4. **Add divergence detection** — add a CI-level test that asserts selected critical functions in `packages/` and `src/` have identical behavior against shared fixtures.
5. **Startup validation** — add startup validation to Lambda handlers that imports critical modules and fails fast if import errors occur.

### Deterministic Startup Validation

Each Lambda handler must include a pre-handler import validation block:

```python
# At module load time, validate critical imports
try:
    from release_confidence_platform.aggregation import orchestrator  # noqa
    from release_confidence_platform.storage import audit_metadata_client  # noqa
except ImportError as exc:
    import logging
    logging.critical("STARTUP_IMPORT_FAILURE: %s", exc)
    raise
```

This fails the Lambda cold start before serving requests if a required module is missing.

### Import Smoke Test

A dedicated test file `tests/unit/test_handler_import_smoke.py` must confirm all Lambda handler modules import without errors. This test is already partially implemented; Phase 4A.6 must complete coverage for all handlers including the aggregation handler.

## 7. Phase 4A.3 — Phase 5 Consumer Contract

### Contract Authority and Ownership Boundary

**Aggregation owns facts. Phase 5 owns interpretation.**

Phase 5 may derive intelligence from aggregation outputs. Phase 5 shall never redefine or reinterpret persisted aggregation facts.

This ownership boundary is a constitutional statement and must be stated explicitly in the published Phase 5 Consumer Contract document.

The full ownership statement:
- Aggregation owns data production, persistence, and lineage.
- Phase 5 owns analytical interpretation and reliability intelligence derivation.
- Phase 5 may consume aggregation outputs as stable inputs.
- Phase 5 shall never reinterpret, re-summarize, or re-aggregate raw execution evidence.
- Phase 5 shall never mutate aggregation artifacts.
- Phase 5 shall never bypass the `AggregateSetCompletion` marker.

### What Phase 5 May Consume

Phase 5 may consume only the following from aggregation:

1. `AggregateSetCompletion` marker — to confirm the aggregate set is complete before consuming child records.
2. `AuditAggregate` record — for audit-level counts, distributions, latency summaries, and execution duration.
3. `EndpointAggregate` records — for per-endpoint counts, success inputs, latency distributions, failure classifications, and HTTP distributions.
4. `FailureClassificationAggregate` records — for classification-level counts.
5. `LineageManifest` — for evidence lineage traceability (read-only).

### What Phase 5 Must Not Do

- Consume raw execution evidence directly from S3 or DynamoDB run metadata.
- Mutate, delete, or extend any aggregation artifact.
- Reinterpret persisted evidence through its own aggregation logic.
- Read `AggregationJob` or `AggregationJobIntent` records (these are internal aggregation implementation details).
- Bypass the `AggregateSetCompletion` marker and consume aggregate records directly.
- Infer aggregation completeness from child record count without the `AggregateSetCompletion` marker.

### Stability Guarantee

The following fields on the `AggregateSetCompletion` marker are stable for Phase 5 consumption:

- `aggregate_type`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`
- `completion_status`, `created_at`
- `expected_execution_count`, `source_run_count`, `source_raw_result_count`
- `aggregate_record_count`, `endpoint_aggregate_count`, `manifest_count`
- `audit_lineage_manifest_ref`, `aggregate_set_hash`

The following fields on `AuditAggregate` are stable for Phase 5 consumption:

- `aggregate_type`, `aggregation_version`, `created_at`
- `lineage` (all sub-fields)
- `request_counts` (all sub-fields: `total`, `successful`, `failed`, `skipped`, `timeout`, `network_failure`)
- `status_code_distribution`, `execution_duration_ms`
- `latency_summary_ms` (all sub-fields)
- `endpoint_execution_counts`

The following fields on `EndpointAggregate` are stable:

- `aggregate_type`, `endpoint_id`, `execution_count`
- `success_inputs` (`numerator`, `denominator`)
- `latency_distribution_ms`, `timeout_count`
- `failure_classification_counts`, `http_response_distribution`
- `lineage`

### Contract Versioning

If a future aggregation version introduces new or changed fields, the consumer contract is versioned alongside `aggregation_version`. Phase 5 must select an `aggregation_version` to consume and must not assume forward compatibility across versions.

Phase 4 / `agg_v1` is the initial stable contract baseline.

### Consumer Contract Compatibility Gate

The published Phase 5 Consumer Contract is a compatibility gate. Future aggregation changes that would affect the stable field set must be validated against the published contract before implementation.

Breaking contract changes require:
1. Contract version increment.
2. HITL approval.
3. Explicit consumer migration documentation.
4. Automated regression tests confirming the new contract version does not silently break Phase 5 assumptions.

Phase 4A.6 or Phase 4A.7 must add a baseline automated test that validates the `agg_v1` consumer contract fields are present and correctly typed in a fixture aggregate set. This test becomes the compatibility gate regression baseline for all future versions.

## 8. Backward Compatibility

Phase 4A introduces no breaking changes to Phase 4 behavior:

- Aggregation lifecycle, eligibility, integrity validation, and persistence remain unchanged.
- No existing DynamoDB key patterns are modified.
- No existing Lambda handler signatures are changed.
- Retrieval CLI is additive only.
- Structured logging improvements are additive (new events alongside existing ones, not replacing them).

## 9. Security

- Engineering Retrieval CLI enforces the same sensitive-data exclusion as Phase 4 aggregation. Raw evidence content must not appear in retrieval output.
- Retrieval commands require IAM-authorized internal access; no public or operator-facing invocation path.
- Retrieval commands are read-only; no write or update permissions are required beyond existing aggregation read access.
- `src/packages` divergence remediation must not introduce new IAM or security configuration; existing access patterns are preserved.

## 10. File Structure Summary

```text
src/release_confidence_platform/
  retrieval/
    __init__.py
    commands.py      (CLI command definitions)
    service.py       (RetrievalService — read-only DynamoDB queries)
    formatter.py     (JSON and human output formatting)
    filters.py       (filter validation and application)

tests/unit/
  retrieval/
    test_retrieval_commands.py
    test_retrieval_formatter.py
    test_retrieval_sensitive_data.py
    test_retrieval_filtering.py

tests/integration/
  test_phase4a_retrieval_integration.py

docs/product/
  phase_4a_aggregation_foundation_product_spec.md   ← this initiative's product spec

docs/architecture/
  phase_4a_aggregation_foundation_technical_design.md  ← this document
  adr_phase_4a_engineering_retrieval_consumer_contract.md
  phase_4a_phase5_consumer_contract.md              ← Phase 4A.3 artifact

docs/qa/
  phase_4a_aggregation_foundation_test_plan.md
```

## 11. Dependencies

- Phase 4 aggregation implementation on `main`.
- Existing operator CLI infrastructure.
- Existing DynamoDB table with Phase 4 key patterns.
- Existing identifier validation and sanitization utilities.
- Existing `structured_logging.md` standard.

## 12. Risks / Open Questions

- **src/packages divergence severity:** audit may reveal behavioral differences that require more investigation than a simple sync. Remediation scope may expand.
- **Retrieval command coverage:** some retrieval targets (e.g., `engineering-logs`) may require structured log indexing that does not currently exist; fallback to DynamoDB event metadata is the MVP approach.
- **Consumer contract immutability pressure:** Phase 5 implementation may request contract additions; any addition requires a formal Phase 4A.3 update with HITL approval.
- **48-hour campaign infrastructure:** campaigns require sustained real execution; CI may not support this; operational validation may be manual.
