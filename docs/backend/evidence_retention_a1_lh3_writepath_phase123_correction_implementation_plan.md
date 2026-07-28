# Implementation Plan

## 0. Scope Amendment — Corrected Entry-Point Inventory (Product Strategy Approved)

The original task briefing for this subphase named `apps/backend/handlers/orchestrator_handler.py` as "likely" the sole Lambda construction point for `DynamoDBMetadataClient`/`S3StorageClient`, based on tracing the one known caller of `put_started_once`/`write_raw_results_once` (`apps/backend/orchestrator/service.py::CoreEngineOrchestrator`) back to its one known entry point. This was **incomplete, not incorrect about what it checked** — it did not separately verify whether any *other* Lambda handler also constructs these same clients and reaches the same `CoreEngineOrchestrator` instance through a different entry point.

Implementation-time verification found exactly that: `apps/backend/handlers/scheduled_execution_handler.py` independently constructs its own `DynamoDBMetadataClient`/`S3StorageClient` pair and passes them into a `CoreEngineOrchestrator` of its own — the `SCHEDULE_TYPE_REPEATED` path the companion ADR's own motivating example cites (repeated, separately-scheduled invocations across an audit's execution window). This is the exact same governed-write call path (`put_started_once`/`write_raw_results_once`), reached through a second, independent construction site.

**Corrected, exhaustive entry-point inventory** (verified via `grep -rn ".write_raw_results_once(\|.put_started_once("` across `apps/`, `packages/`, `src/`): these two methods have **exactly two call sites in the entire codebase**, both inside `apps/backend/orchestrator/service.py::CoreEngineOrchestrator.run`. That single class is constructed from exactly two Lambda handlers:

- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/handlers/scheduled_execution_handler.py`

Three other production sites construct `DynamoDBMetadataClient`/`S3StorageClient` instances but were verified **not** to reach either governed write method, and are therefore correctly out of scope:

- `apps/backend/handlers/aggregation_handler.py` — constructs the unrelated `release_confidence_platform.storage.s3_client.S3StorageClient` (the divergent `src/` mirror, no legal-hold logic at all), used only for `read_json` (`AggregationOrchestrator` reads raw evidence, never writes it).
- `apps/backend/handlers/audit_finalization_handler.py` — constructs the same `packages.storage.s3_client.S3StorageClient` class this subphase modified, but calls only `list_raw_evidence_keys` (a list operation); `write_raw_results_once` is never invoked here.
- `packages/storage/aws_client_factory.py` / `src/release_confidence_platform/storage/aws_client_factory.py` (operator-CLI client construction) — no CLI command reaches `put_started_once`/`write_raw_results_once` (confirmed during the A1.LH3 read-only investigation; unchanged by this subphase).

**Product Strategy disposition**: the `scheduled_execution_handler.py` wiring is approved as required, in-scope A1.LH3 work, not new product behavior or scope expansion — it is the same fail-closed correction applied to the second of exactly two real entry points into the same already-authorized governed write paths. Leaving it unwired would have broken every scheduled/repeated execution outright, since both write methods now fail closed (`HOLD_COORDINATION_NOT_CONFIGURED`) without a configured `HoldRepository`.

## 1. Feature Overview

Evidence Governance Workstream A1, subphase A1.LH3 ("Corrective wiring of merged A1.3b/A1.3b.1", Technical Design §19.10 item (c+d)). Wires the two already-merged production write paths that predate the legal-hold mechanism — `packages/storage/dynamodb_client.py::put_started_once` (RunMetadata CREATE) and `packages/storage/s3_client.py::write_raw_results_once` (raw-evidence S3 CREATE) — to the already-merged A1.LH1 (DynamoDB `TransactWriteItems` hold coordination) and A1.LH2 (S3 canary-marker mechanism, not directly consumed here — only its prerequisite, `HoldRepository.get_legal_hold`, is extended).

## 2. Technical Scope

- RunMetadata CREATE resolves current legal-hold state via a `TransactWriteItems` call (governed `Put` + `LegalHold.hold_version` `ConditionCheck`, bounded retry, fail-closed on exhaustion).
- Raw-evidence S3 CREATE resolves current legal-hold state via a `ConsistentRead=True` `HoldRepository.get_legal_hold` call immediately before every `put_object`, computing per-call tags.
- `HoldRepository.get_legal_hold` gains an opt-in `consistent_read` parameter, default `False` (byte-identical default behavior).
- Runtime wiring: one `HoldRepository` constructed per Lambda invocation, injected into both `DynamoDBMetadataClient` and `S3StorageClient`, in both `orchestrator_handler.py` and (a discovered second production writer) `scheduled_execution_handler.py`.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` (Decision 3 amendment note, Decision 9, Non-Negotiable Invariants 11–14, 25).
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md` §19.4, §19.5.4, §19.7, §19.8, §19.9, §19.10, §19.14, §19.15.
- Already-merged A1.LH1 (`hold_coordination.py`, `hold_repository.py`, `hold_transitions.py`) and A1.LH2 (`marker_store.py`, `retention_service.py`, `custody_sweep_client.py` — not modified).
- Existing code: `packages/storage/dynamodb_client.py`, `packages/storage/s3_client.py`, `apps/backend/handlers/orchestrator_handler.py`.

## 4. API Contracts Affected

No external/HTTP API contract changes. Internal Python constructor signatures changed (additive, optional-with-fail-closed):

- `DynamoDBMetadataClient.__init__(table_name, dynamodb_client, hold_repository=None, transact_dynamodb_client=None)`.
- `S3StorageClient.__init__(bucket_name, s3_client, hold_repository=None)`.
- `HoldRepository.get_legal_hold(client_id, audit_id, *, consistent_read=False)` (new keyword-only parameter, default preserves prior behavior exactly).

`put_started_once`/`write_raw_results_once` now raise `StorageError("HOLD_COORDINATION_NOT_CONFIGURED", ...)` if constructed without a `hold_repository`, and `StorageError("HOLD_STATE_CONCURRENCY_EXCEEDED", ...)` / `StorageError("HOLD_STATE_UNRESOLVABLE", ...)` on hold-resolution failure — all new, additive failure modes on an existing error-return contract (`CoreEngineOrchestrator.run()`'s sanitized failure response), not a new endpoint.

## 5. Data Models / Storage Affected

- `RunMetadata` item: `ttl_disposal_at` now conditionally omitted (present only when the audit is not under an ACTIVE hold) — `custody_expires_at`/`evidence_class` unchanged in shape.
- No schema change to `LegalHold`/`LegalHoldEvent` (A1.LH1's schema already final).
- S3 object tags on raw-evidence objects: `rcp-legal-hold` now computed per-call instead of hardcoded `false`.

## 6. Files Expected to Change

- `packages/storage/dynamodb_client.py`
- `packages/storage/s3_client.py`
- `src/release_confidence_platform/evidence_retention/hold_repository.py`
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/handlers/scheduled_execution_handler.py` (discovered second production writer, same fix applied)
- Test files exercising either write path (enumerated in the implementation report).

## 7. Security / Authorization Considerations

- Fail-closed on every path where legal-hold state cannot be deterministically resolved (TD §19.14) — no availability exception for Phase 1's critical execution path.
- No new IAM surface (existing `dynamodb:GetItem/PutItem/UpdateItem/TransactWriteItems`, `s3:PutObject` permissions already cover this; `transact_write_items`/`ConsistentRead` are existing-permission operations, not new grants).
- No secrets, tokens, or credentials touched.

## 8. Dependencies / Constraints

No new third-party dependencies. Reuses `boto3.dynamodb.types` (already a transitive dependency via `dynamodb_codec.py`). No new environment variables or custody-duration values introduced. No `infra/serverless.yml` change (packaging already sufficient — verified, not assumed; see packaging regression test).

## 9. Assumptions

- **Second production writer** (`scheduled_execution_handler.py`) requires the identical wiring fix — treated as in-scope completion of this subphase's own stated goal (closing the temporal-coverage gap for RunMetadata/raw-evidence CREATE), not scope expansion, since the brief explicitly asked me to confirm no other factory owns this construction.
- `client_id`/`audit_id` are always present on the `item` dict passed to `put_started_once` (confirmed via `apps/backend/orchestrator/service.py::_started_item`).
- Raw-evidence S3 keys are always shaped `raw-results/{client_id}/{audit_id}/{run_id}/...` (confirmed via `RAW_RESULT_KEY_TEMPLATE`/`build_raw_result_key`, the sole producer) — used to derive `client_id`/`audit_id` for the S3 hold-state read without changing `write_raw_results_once`'s two-parameter signature (avoiding any change to its one call site, `apps/backend/orchestrator/service.py`).

## 10. Validation Plan

- Targeted pytest runs per affected/new test file.
- Full canonical suite: `uv run pytest -q`.
- `uv run ruff check` on all changed/new files, plus a before/after full-repo ruff diff to confirm zero new lint issues against a pre-existing 69-error baseline.
