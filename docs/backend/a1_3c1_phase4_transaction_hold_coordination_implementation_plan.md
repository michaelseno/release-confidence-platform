# Implementation Plan

## 1. Feature Overview

Evidence Governance Workstream A1, subphase A1.3c.1: wire Phase 4's two governed DynamoDB write methods (`AggregationRepository.put_records_once`, `AggregationRepository.put_lineage_page_once`) to the already-merged A1.LH1 legal-hold coordination mechanism (`HoldCoordinatedTransactionRunner`), add hold-aware custody fields (`custody_expires_at`, `ttl_disposal_at`, `evidence_class`) to every governed Phase 4 record, and enforce the corrected `4 + 3N` + 1 transaction item/byte budget.

## 2. Technical Scope

- `AggregationRepository` gains an optional `hold_repository` dependency; both governed write methods fail closed when it is absent.
- Both methods resolve `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` from the environment, failing closed (`CUSTODY_PERIOD_CONFIG_MISSING`) before any hold read.
- Both methods merge governance fields onto every record (fixed values always win over caller-supplied conflicts), encode, and submit a `TransactWriteItems` call with an appended `LegalHold.hold_version` `ConditionCheck` as the final item.
- `MAX_AGGREGATE_RECORDS` corrected from 100 to 99 (one slot reserved for the appended `ConditionCheck`).
- Post-augmentation per-item and whole-transaction byte guards, evaluated after governance-field merge and encoding.
- `AggregationOrchestrator.run()`/`_write_lineage_pages` updated to pass `client_id`/`audit_id` through to the two governed write methods.
- `apps/backend/handlers/aggregation_handler.py` wires a single DynamoDB client to both `HoldRepository` and `AggregationRepository`, and corrects the HTTP status-code classification to treat hold-coordination/custody-configuration gaps as server-side (500) failures.
- `infra/serverless.yml` gains the `aggregate_metadata` custody-period configuration key and the `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` environment binding on `auditAggregation` only.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` — Decision 5 (as amended for A1.3c.1) and Non-Negotiable Invariant 26.
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md` §19.4 (DynamoDB concurrency protocol), §19.14 (uniform fail-closed rule), §19.16 (Phase 4 transaction item/byte budget, including §19.16.5/§19.16.6).
- Already-merged A1.LH3 implementation (`packages/storage/dynamodb_client.py`, `src/release_confidence_platform/evidence_retention/hold_coordination.py`, `hold_repository.py`) as the pattern to mirror.
- Orchestrator prompt from the parent agent, which pre-verified the current code state and enumerated the affected test call sites.

## 4. API Contracts Affected

`AggregationRepository.put_records_once`/`put_lineage_page_once` gain required keyword-only `client_id`/`audit_id` parameters (internal repository API, not an external HTTP contract). The `auditAggregation` Lambda's HTTP-shaped response status-code classification changes: `HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED`, and (new) `CUSTODY_PERIOD_CONFIG_MISSING` now map to 500 instead of the prior blanket 400-unless-`STORAGE_ERROR` rule. `AGGREGATE_SET_TOO_LARGE`/`CONDITIONAL_WRITE_FAILED` remain 400. Response body shape unchanged.

## 5. Data Models / Storage Affected

Every Phase 4 governed DynamoDB record (`4 + 3N` items from `put_records_once`, one item from `put_lineage_page_once`) now carries `custody_expires_at` (always), `evidence_class = "aggregate_metadata"` (always), and `ttl_disposal_at` (present unless the audit identity is under an active legal hold at write time). No schema-breaking change — additive fields only, following the established RunMetadata pattern.

## 6. Files Expected to Change

- `src/release_confidence_platform/aggregation/repository.py`
- `src/release_confidence_platform/aggregation/constants.py`
- `src/release_confidence_platform/aggregation/orchestrator.py`
- `src/release_confidence_platform/evidence_retention/hold_coordination.py` (docstring only)
- `apps/backend/handlers/aggregation_handler.py`
- `infra/serverless.yml`
- Test files: the Category A/B affected-call-site inventory the parent agent enumerated, plus new dedicated test files.

## 7. Security / Authorization Considerations

No new authentication/authorization surface. Legal-hold coordination is a data-integrity/evidence-governance control, not an access-control boundary. Failure responses must not leak internal exception detail, AWS error codes, table names, or key material — verified by dedicated handler-level tests.

## 8. Dependencies / Constraints

No new third-party dependencies. Reuses `HoldCoordinatedTransactionRunner`, `HoldRepository`, `build_hold_version_condition_check_item`, `compute_ttl_disposal_at` (all already merged, A1.LH1/A1.LH2/A1.LH3). `MAX_AGGREGATE_TRANSACTION_BYTES`/`MAX_AGGREGATE_ITEM_BYTES` numeric values unchanged. No numeric custody-duration value introduced (`aggregate_metadata` config key stays an empty mapping).

## 9. Assumptions

- **`CUSTODY_PERIOD_CONFIG_MISSING` classified as server-side (500) in the handler** — not explicitly enumerated in the earlier handler-classification correction round; inferred by the same "server-side wiring/configuration gap, not caller validation error" reasoning already applied to `HOLD_COORDINATION_NOT_CONFIGURED`/`HOLD_STATE_CONCURRENCY_EXCEEDED`. Flagged per the task's explicit instruction to surface this inference rather than treat it as self-evidently correct.
- Test-double `RecordingHoldAwareClient` reuses A1.LH3's established wire-format `TransactWriteItems`/`CancellationReasons` pattern rather than a new shape, per the task's explicit instruction.
- `tests/integration/test_phase4a7_aggregation_envelope_compatibility.py`'s `AggregationRepository` construction was updated to include a `HoldRepository` for wiring fidelity with production, even though that specific test file only exercises read paths (`list_completed_runs`/`_load_records`) and never actually invokes the governed write methods — flagged as a no-op-but-harmless alignment change, not a functional requirement of that file's own test bodies.

## 10. Validation Plan

- `uv run pytest -q` (full canonical suite).
- Focused runs of every Category A/B affected file plus all new dedicated test files.
- `uv run ruff check <changed files>` and a full-repo `uv run ruff check .` before/after comparison via `git stash`.
- `cd infra && npx sls print --stage dev`, asserting the new `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` unresolved-variable failure appears alongside the pre-existing eight S3-side failures.
