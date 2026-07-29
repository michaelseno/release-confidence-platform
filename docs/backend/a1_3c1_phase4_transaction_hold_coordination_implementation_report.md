# Implementation Report

## 1. Summary of Changes

Wired Phase 4's two governed DynamoDB write methods (`AggregationRepository.put_records_once`, `put_lineage_page_once`) to the already-merged A1.LH1 legal-hold coordination mechanism (`HoldCoordinatedTransactionRunner`), added hold-aware custody fields (`custody_expires_at`, `ttl_disposal_at`, `evidence_class = "aggregate_metadata"`) to every governed Phase 4 record, corrected `MAX_AGGREGATE_RECORDS` from 100 to 99 to reserve one transaction slot for the appended `LegalHold.hold_version` `ConditionCheck`, added post-augmentation per-item and whole-transaction byte guards, updated the orchestrator call sites and the Lambda handler's single-client wiring and error-classification, and added the `aggregate_metadata` custody-period configuration channel (env var + `infra/serverless.yml` binding on `auditAggregation` only, no numeric value).

## 2. Files Modified

- `src/release_confidence_platform/aggregation/repository.py` — constructor gains optional `hold_repository`; `put_records_once`/`put_lineage_page_once` rewritten as hold-coordinated `TransactWriteItems` calls with custody-period resolution, item-count/byte-budget guards, and governance-field merge. Added `_resolve_aggregate_metadata_custody_period_days`, `_aggregate_governance_fields`, `_measure_item_bytes`, `_measure_transaction_bytes`.
- `src/release_confidence_platform/aggregation/constants.py` — `MAX_AGGREGATE_RECORDS` now derived (`100 - HOLD_CHECK_RESERVED_TRANSACTION_ITEMS = 99`); added `HOLD_CHECK_RESERVED_TRANSACTION_ITEMS`, `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA_ENV_VAR`. `MAX_AGGREGATE_ITEM_BYTES`/`MAX_AGGREGATE_TRANSACTION_BYTES` values unchanged.
- `src/release_confidence_platform/aggregation/orchestrator.py` — `run()` and `_write_lineage_pages` pass `client_id`/`audit_id` through to the two governed write methods.
- `src/release_confidence_platform/evidence_retention/hold_coordination.py` — docstring-only fix (stale "5-item set" reference corrected to the variable-length `4 + 3N` description).
- `apps/backend/handlers/aggregation_handler.py` — `handler()` constructs one DynamoDB client, wires the same client to both `HoldRepository` and `AggregationRepository`; `AggregationHandler.handle()`'s status-code classification corrected to a `_SERVER_SIDE_FAILURE_REASON_CODES` frozenset (`STORAGE_ERROR`, `HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED`, `CUSTODY_PERIOD_CONFIG_MISSING`) → 500; everything else → 400.
- `infra/serverless.yml` — `custom.custodyPeriodDays.aggregate_metadata: {}` added; `functions.auditAggregation.environment.CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` binding added (no fallback, no provider-wide binding, no other function).
- `tests/conftest.py` — new autouse fixture `_default_custody_period_days_aggregate_metadata` (mirrors the existing `raw_evidence` pattern), placeholder value `"90"`, no product meaning.
- Category A fakes (signature-only additions, `*, client_id="", audit_id=""` / `**equivalent`): `tests/unit/aggregation/test_phase4_orchestrator.py`, `test_phase4a4_persistence.py`, `test_orchestrator_lineage_pagination.py`, `tests/unit/test_phase5_consumer_contract.py`, `tests/unit/test_structured_logging_retrieval.py`, `tests/integration/test_phase4a5_retrieval_integration.py`, `tests/integration/test_phase4a4_aggregation_persistence_integration.py`.
- `tests/integration/test_phase4a7_aggregation_envelope_compatibility.py` — `AggregationRepository` construction updated to include a `HoldRepository`, for wiring fidelity with production (see Assumptions — this file's own test bodies never invoke the governed write methods).
- `tests/unit/test_handler_import_smoke.py` — `capturing_repo` fake updated to accept the new third positional constructor argument.
- `tests/unit/test_infra_configuration.py` — `test_custody_period_days_config_defines_no_value_for_any_stage` updated to include `aggregate_metadata`; four new tests added (env-binding scoping, no-fallback shape, negative-binding check, `sls print` render-failure proof).
- Two additional pre-existing direct-repository-level tests fixed beyond the original inventory (found via full-suite run, not pre-enumerated): `test_phase4_orchestrator.py::test_repository_writes_complete_aggregate_set_as_single_transaction`, `test_phase4a4_persistence.py::test_agg_p4_conditional_write_prevents_overwrite`.

New files:
- `tests/unit/aggregation/_hold_coordination_double.py` — shared `RecordingHoldAwareClient` test double (reuses A1.LH3's wire-format `TransactWriteItems`/`CancellationReasons` pattern) plus `place_hold`/`release_hold` helpers.
- `tests/unit/aggregation/test_a1_3c1_hold_coordination.py` — 44 tests (repository-level).
- `tests/integration/test_a1_3c1_orchestrator_hold_coordination.py` — 8 tests (real-orchestrator-path).
- `tests/unit/test_a1_3c1_aggregation_handler.py` — 16 tests (handler-level).

## 3. API Contract Implementation

`AggregationRepository.put_records_once`/`put_lineage_page_once` gain required keyword-only `client_id`/`audit_id` parameters (internal repository API). `AggregationHandler.handle()`'s HTTP status-code mapping corrected per Technical Design §19.15's server-side-vs-caller-facing distinction (see §12 of the ADR-referenced classification note in the task, and Assumptions below for `CUSTODY_PERIOD_CONFIG_MISSING`). Response body shape (`{"status": "FAILED", "reason_code": ...}` / sanitized success body) unchanged.

## 4. Data / Persistence Implementation

Every Phase 4 governed DynamoDB item (all `4 + 3N` items from `put_records_once`; the one item from `put_lineage_page_once`) now carries `custody_expires_at` (always, computed fresh per write attempt), `evidence_class = "aggregate_metadata"` (fixed constant, always wins over caller-supplied conflicts), and `ttl_disposal_at` (present unless the audit identity is observed `ACTIVE`-held at that attempt's own hold-state read). The transaction submitted to `TransactWriteItems` is the `4 + 3N` governed `Put`s plus one appended `LegalHold.hold_version` `ConditionCheck` — `100` items total at the `N = 31` ceiling. `MAX_AGGREGATE_RECORDS` corrected to `99` to reserve that slot.

## 5. Key Logic Implemented

- **Fail-closed ordering** (both methods, identical): `hold_repository is None` → `HOLD_COORDINATION_NOT_CONFIGURED` first; then `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` resolution → `CUSTODY_PERIOD_CONFIG_MISSING`; then (for `put_records_once` only) the item-count check → `AGGREGATE_SET_TOO_LARGE`, before any hold read. All three precede any AWS request.
- **Governance-field merge**: `{**item, **_aggregate_governance_fields(hold_state, custody_period_days)}` — fixed values always win, computed fresh from each attempt's own `hold_state` read, never carried across retries, never mutates the caller's original dict.
- **Post-augmentation byte guards**: per-item (`MAX_AGGREGATE_ITEM_BYTES`) and whole-transaction (`MAX_AGGREGATE_TRANSACTION_BYTES`, including the appended `ConditionCheck`) measured after encoding, inside the `build_transact_items` closure the coordinated runner calls once per attempt.
- **Governed-vs-hold precedence**: unchanged, reused `HoldCoordinatedTransactionRunner.run()` — a governed record's own condition failure always raises `ConditionalWriteError` immediately (via `on_governed_condition_failed`), never retried as a hold race; a hold-only failure retries up to 3 attempts, each with a fresh hold read and freshly recomputed custody fields; exhaustion raises `HoldStateConcurrencyExceededError` (`HOLD_STATE_CONCURRENCY_EXCEEDED`).
- **Orchestrator wiring**: `run()` passes `client_id`/`audit_id` to `put_records_once` and to `_write_lineage_pages`, which now forwards them to `put_lineage_page_once` per page. The existing `page_hash`-comparison retry-safety in `_write_lineage_pages` is unchanged.

## 6. Security / Authorization Implemented

No new authentication/authorization surface — legal-hold coordination is an evidence-governance data-integrity control. Handler failure responses expose only `{"status": "FAILED", "reason_code": <bounded code>}` — verified directly by `test_failure_response_body_exposes_no_internal_detail`, which asserts a deliberately sensitive internal message (AWS error code, table name, partition key) never reaches the response body.

## 7. Error Handling Implemented

| Code | Source | HTTP status |
| --- | --- | --- |
| `HOLD_COORDINATION_NOT_CONFIGURED` | Both governed methods, `hold_repository is None` | 500 |
| `CUSTODY_PERIOD_CONFIG_MISSING` | Both governed methods, env var unresolvable | 500 (see Assumptions) |
| `HOLD_STATE_CONCURRENCY_EXCEEDED` | `HoldCoordinatedTransactionRunner` retry exhaustion | 500 |
| `AGGREGATE_SET_TOO_LARGE` | Item-count / per-item-byte / transaction-byte rejection | 400 (unchanged) |
| `CONDITIONAL_WRITE_FAILED` | Governed record's own condition failure | 400 (unchanged) |
| `LINEAGE_PAGE_HASH_MISMATCH` | Orchestrator's own reconciliation (`_write_lineage_pages`) | 400 (unchanged, via generic `ValidationError` path) |

No 503 status code introduced anywhere.

## 8. Observability / Logging

No new logging statements added beyond what `AggregationHandler.handle()` already emits (`aggregation_handler_failed`, unchanged shape — `reason_code`, `input_type`, no sensitive payload). No secrets, tokens, or raw hold-state details are logged.

## 9. Assumptions Made

- **`CUSTODY_PERIOD_CONFIG_MISSING` classified as server-side (500) in the handler.** Not explicitly enumerated in the earlier handler-classification correction round that established `HOLD_COORDINATION_NOT_CONFIGURED`/`HOLD_STATE_CONCURRENCY_EXCEEDED` as 500. Applied by the same reasoning (a server-side wiring/configuration gap, not a caller validation error) per the task's explicit instruction to flag this inference rather than treat it as self-evidently correct. If Product Strategy disagrees, this is a one-line change to `_SERVER_SIDE_FAILURE_REASON_CODES` in `apps/backend/handlers/aggregation_handler.py`.
- **`tests/integration/test_phase4a7_aggregation_envelope_compatibility.py`** — updated to construct a `HoldRepository` and pass it into `AggregationRepository` for wiring fidelity with the file's own stated goal of mirroring production wiring exactly. On direct inspection, this specific file's test bodies only exercise `list_completed_runs`/`_load_records` (read paths) and never call `put_records_once`/`put_lineage_page_once`, so this change is not functionally required by anything in the file today — flagged rather than silently assumed necessary.
- Test-double design (`RecordingHoldAwareClient`) reuses a real per-key typed-item store with genuine `attribute_not_exists`/`hold_version` condition evaluation (matching A1.LH3's established `_LowLevelClient` pattern in `test_phase4a7_aggregation_envelope_compatibility.py`), plus index-targeted forced-failure injection for cancellation-index tests — an extension of, not a departure from, the reused pattern.
- Placeholder custody-period test value (`"90"` days, via the new autouse `conftest.py` fixture) has no product meaning, mirroring the existing `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` precedent exactly.

## 10. Validation Performed

- **Focused suite** (166 tests across all affected + new files): `uv run pytest -q tests/unit/aggregation/test_a1_3c1_hold_coordination.py tests/integration/test_a1_3c1_orchestrator_hold_coordination.py tests/unit/test_a1_3c1_aggregation_handler.py tests/unit/test_infra_configuration.py tests/unit/test_handler_import_smoke.py tests/unit/aggregation/test_phase4_orchestrator.py tests/unit/aggregation/test_phase4a4_persistence.py tests/unit/aggregation/test_orchestrator_lineage_pagination.py tests/unit/test_phase5_consumer_contract.py tests/unit/test_structured_logging_retrieval.py tests/integration/test_phase4a5_retrieval_integration.py tests/integration/test_phase4a4_aggregation_persistence_integration.py tests/integration/test_phase4a7_aggregation_envelope_compatibility.py tests/unit/aggregation/test_update_job_custody_guard.py` → **166 passed, 2 skipped** (the 2 skips are the `sls`-CLI-availability guard in the render test, which itself passed when the CLI was available — see below).
- **Full canonical suite**: `uv run pytest -q` → **1766 passed, 2 skipped** (reflects the two additive `put_lineage_page_once` boundary tests added to close the QA-flagged coverage gap).
- **Lint, changed files**: `ruff check <20 changed/new .py files>` → **All checks passed!**
- **Lint, full-repo before/after**: `uv run ruff check .` on the working tree (**69 errors**) vs. on a `git stash`-restored baseline (**69 errors**) → `diff` of the two full outputs is **byte-identical** (confirmed via `diff` exit code 0). All 69 pre-existing errors are in unrelated files (e.g. `test_phase8_consumer_contract.py`, `test_reliability_intelligence_anomaly_flagging.py`) and are unchanged by this work.
- **`sls print --stage dev`** (Serverless Framework 3.40.0, Node 22.11.0, both available in this environment): failed at variable-resolution time with 9 unresolved-variable errors — the pre-existing 8 (4 `Days` + 4 `NoncurrentDays`, one pair per S3-backed evidence class) plus the new, required one:

  ```
  Cannot resolve variable at "functions.auditAggregation.environment.CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA": Value not found at "self" source,
  ```

  This is the intentional fail-closed proof (Technical Design §19.16.6) — no placeholder/dummy value was introduced to make rendering succeed. The static and render-proof assertions are additionally codified as `test_serverless_print_fails_on_unresolved_aggregate_metadata_custody_period` (skips gracefully, not silently passes, if the Serverless CLI/Node toolchain is unavailable — matching the existing `test_serverless_variable_resolution_requires_serverless_cli` documentation boundary).

### Requirement-to-test traceability

| Requirement | Test(s) |
| --- | --- |
| Custody-period resolution fail-closed, both methods | `test_put_records_once_custody_period_fails_closed`, `test_put_lineage_page_once_custody_period_fails_closed` (parametrized: unset/empty/non-numeric/zero/negative) |
| `hold_repository=None` fail-closed, both methods, zero AWS calls | `test_put_records_once_fails_closed_when_hold_repository_missing`, `test_put_lineage_page_once_fails_closed_when_hold_repository_missing` |
| Override terminology (silent override, caller-dict immutability) | `test_put_records_once_silently_overrides_caller_supplied_governance_fields`, `test_put_lineage_page_once_silently_overrides_caller_supplied_governance_fields` |
| Hold-transition races, both directions, both methods, bounded success | `test_put_records_once_no_hold_to_active_race_bounded_success`, `test_put_records_once_active_to_released_race_bounded_success`, `test_put_lineage_page_once_no_hold_to_active_race_bounded_success`, `test_put_lineage_page_once_active_to_released_race_bounded_success` |
| Hold-race bounded exhaustion, both methods | `test_put_records_once_hold_race_retry_exhaustion_fails_closed`, `test_put_lineage_page_once_hold_race_retry_exhaustion_fails_closed` |
| Governed-vs-hold precedence, N=1/10/31, first/middle/last/hold-alone/both | `test_governed_failure_wins_over_hold_check_regardless_of_position`, `test_hold_check_alone_failing_enters_bounded_retry` |
| 99/100-item repository-level boundary | `test_put_records_once_accepts_exactly_99_governed_records`, `test_put_records_once_rejects_100_governed_records_before_any_aws_call` |
| 31/32-endpoint real-orchestrator-path boundary | `test_31_endpoints_produces_98_item_transaction_and_succeeds`, `test_32_endpoints_rejected_before_any_aws_request` |
| Item/transaction byte boundaries, exact equality, real encode/measure, determinism, pre-safe→post-unsafe | `test_put_records_once_item_byte_boundary_exact_equality`, `test_put_lineage_page_once_item_byte_boundary_exact_equality`, `test_put_records_once_pre_merge_safe_item_becomes_post_merge_unsafe`, `test_put_records_once_transaction_byte_boundary_exact_equality`, `test_put_records_once_transaction_byte_rejection_reads_hold_exactly_once`, `test_transaction_byte_measurement_is_deterministic`, `test_transaction_byte_measurement_includes_condition_check_contribution` |
| Lineage-page reconciliation via `_write_lineage_pages` | `test_lineage_page_write_success_and_identical_hash_retry_is_idempotent`, `test_lineage_page_conflicting_hash_raises_hash_mismatch`, `test_lineage_page_hold_only_race_transparently_retried`, `test_lineage_page_retry_exhaustion_fails_closed`, `test_lineage_page_governed_conflict_raises_conditional_write_error_not_masked` |
| Handler object identity, status codes, no-leakage | `test_handler_wires_hold_repository_and_aggregation_repository_to_same_client`, `test_server_side_failure_reason_codes_map_to_500`, `test_caller_facing_reason_codes_remain_400`, `test_no_503_status_code_ever_used`, `test_successful_unheld_aggregation_returns_200`, `test_failure_response_body_exposes_no_internal_detail` |
| Static infra config + render fail-closed | `test_custody_period_days_config_defines_no_value_for_any_stage`, `test_aggregate_metadata_custody_period_env_binding_exists_on_aggregation_only`, `test_aggregate_metadata_custody_period_env_binding_has_no_fallback_or_literal`, `test_aggregate_metadata_custody_period_not_bound_on_other_functions`, `test_serverless_print_fails_on_unresolved_aggregate_metadata_custody_period` |

## 11. Known Limitations / Follow-Ups

- `CUSTODY_PERIOD_CONFIG_MISSING`'s server-side (500) classification is an inference, not an explicit prior decision — flagged above for Product Strategy confirmation.
- No numeric custody-duration value is selected for `aggregate_metadata` by this work (unchanged, out of scope per AC-A1-5).
- No deployment or activation performed or authorized.

## 12. Commit Status

Not committed — per the task instructions, this session stops after implementation and validation. Working tree contains the changes described above, uncommitted, on branch `feature/a1-3c1-phase4-transaction-hold-coordination`.
