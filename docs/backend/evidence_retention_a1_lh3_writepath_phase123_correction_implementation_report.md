# Implementation Report

## 0. Scope Amendment — Corrected Entry-Point Inventory (Product Strategy Approved)

**Original conclusion, and why it was incomplete**: the task briefing traced `put_started_once`/`write_raw_results_once`'s one known caller (`CoreEngineOrchestrator`) back to `orchestrator_handler.py` and named that as "likely" the sole Lambda construction point. That trace was accurate as far as it went; it did not separately verify whether a second handler also constructs `CoreEngineOrchestrator` and reaches it through a different entry point.

**Corrected, exhaustive inventory** (verified by exhaustive grep for the actual call sites, not just constructor sites): `put_started_once`/`write_raw_results_once` have exactly two call sites in the entire codebase, both inside `apps/backend/orchestrator/service.py::CoreEngineOrchestrator.run`, constructed from exactly two Lambda handlers:

| Entry point | Reaches governed writes? | Disposition |
| --- | --- | --- |
| `apps/backend/handlers/orchestrator_handler.py` | Yes | Wired (originally authorized) |
| `apps/backend/handlers/scheduled_execution_handler.py` | Yes (`SCHEDULE_TYPE_REPEATED` path) | Wired (Product Strategy scope amendment, approved) |
| `apps/backend/handlers/aggregation_handler.py` | No — constructs the unrelated `release_confidence_platform.storage.s3_client.S3StorageClient` (divergent `src/` mirror, no legal-hold logic), and only calls `read_json` | Correctly out of scope, unmodified |
| `apps/backend/handlers/audit_finalization_handler.py` | No — constructs `packages.storage.s3_client.S3StorageClient` (the class this subphase modified) but only calls `list_raw_evidence_keys` | Correctly out of scope, unmodified |
| `packages/storage/aws_client_factory.py` / `src/.../storage/aws_client_factory.py` (operator CLI) | No — no CLI command reaches either governed write method (confirmed in the A1.LH3 read-only investigation) | Correctly out of scope, unmodified |

**Product Strategy disposition**: `scheduled_execution_handler.py`'s wiring is approved as required, behaviorally-complete A1.LH3 integration — not new product behavior, not scope expansion. It is the identical, already-authorized fail-closed correction applied to the second (and, per the exhaustive inventory above, final) real entry point into the same governed write paths. Leaving it unwired would have broken every scheduled/repeated execution outright, since both write methods now fail closed (`HOLD_COORDINATION_NOT_CONFIGURED`) without a configured `HoldRepository`.

## 1. Summary of Changes

Wired the two already-merged, pre-legal-hold production write paths to the already-merged A1.LH1 hold-coordination mechanism:

- **`packages/storage/dynamodb_client.py::put_started_once`** now executes as a `TransactWriteItems` call (governed `Put` + `LegalHold.hold_version` `ConditionCheck`, via `HoldCoordinatedTransactionRunner`) instead of a plain conditional `put_item`. `ttl_disposal_at` is omitted if and only if the read observed an ACTIVE hold. Bounded retry (3 attempts) on a detected hold-version race; fails closed (`HOLD_STATE_CONCURRENCY_EXCEEDED`) on exhaustion; the governed record's own duplicate-write condition always wins over a concurrent hold race (precedence rule).
- **`packages/storage/s3_client.py::write_raw_results_once`** now reads current hold state fresh, via a `ConsistentRead=True` `HoldRepository.get_legal_hold` call, immediately before every `put_object`, computing `rcp-legal-hold`/`rcp-evidence-class` tags per call. The old module-level `_RAW_EVIDENCE_TAGGING` constant (computed once at import time) is removed entirely.
- **`HoldRepository.get_legal_hold`** gained an opt-in `consistent_read: bool = False` parameter, plumbed through `_get_item`/`_call` as `ConsistentRead=True` only when requested — default calls are byte-identical to pre-existing behavior (no `ConsistentRead` kwarg sent at all).
- **`apps/backend/handlers/orchestrator_handler.py`** and **`apps/backend/handlers/scheduled_execution_handler.py`** (a second, independently discovered production writer — see §9) now construct one `HoldRepository` per invocation (backed by `table.meta.client`, the low-level accessor) and inject it into both `DynamoDBMetadataClient` and `S3StorageClient`.

## 2. Files Modified

| File | Why |
| --- | --- |
| `packages/storage/dynamodb_client.py` | `_run_metadata_custody_fields` now hold-state-aware; `put_started_once` rewritten to use `HoldCoordinatedTransactionRunner`; constructor gains `hold_repository`/`transact_dynamodb_client`; cross-package exception re-wrapping. |
| `packages/storage/s3_client.py` | Removed module-level tagging constant; added per-call `_raw_evidence_tagging`/`_parse_raw_evidence_key_identity`; `write_raw_results_once` rewritten; constructor gains `hold_repository`. |
| `src/release_confidence_platform/evidence_retention/hold_repository.py` | Added `consistent_read` support to `get_legal_hold`/`_get_item`. |
| `apps/backend/handlers/orchestrator_handler.py` | Constructs and injects the shared `HoldRepository`. |
| `apps/backend/handlers/scheduled_execution_handler.py` | Same fix — second production writer, discovered this session. |
| `tests/unit/test_run_metadata_custody_fields.py` | Rewritten: full hold-race/retry/exhaustion/precedence coverage against a realistic wire-format DynamoDB double. |
| `tests/unit/test_raw_evidence_s3_tagging.py` | Rewritten: per-call tag correctness, consistent-read enforcement, fail-closed, staleness regression. |
| `tests/unit/evidence_retention/test_hold_repository.py` | Added (not modified) 3 new tests for `consistent_read`; all pre-existing tests untouched and still pass. |
| `tests/unit/test_lambda_handler_hold_repository_wiring.py` | New — proves shared-instance wiring for both handlers. |
| `tests/unit/test_evidence_governance_a1_lh3_packaging.py` | New — packaging-sufficiency structural regression. |
| `tests/unit/test_phase1_core_engine.py`, `tests/unit/test_execution_identity_dynamodb.py`, `tests/api/test_audit_run_orchestrator_observability.py`, `tests/integration/test_phase1_orchestrator_integration.py`, `tests/integration/test_phase2_orchestrator_payloads.py`, `tests/integration/test_phase4a7_aggregation_envelope_compatibility.py`, `tests/security/test_phase1_qa_contracts.py` | Mechanical fixture updates: added `transact_write_items` support to existing DynamoDB fakes and a `HoldRepository` no-hold-ever stand-in, required because `put_started_once`'s write mechanism changed from `put_item` to `TransactWriteItems`. No test assertions changed in substance. |

`tests/api/test_dynamodb_storage_error_guidance.py`, `tests/api/test_s3_storage_error_guidance.py`, `tests/unit/test_operator_cli_discovery.py`, `tests/unit/test_operator_cli_rcp.py` were investigated and confirmed **not** affected — they import the unrelated legacy `release_confidence_platform.storage.{dynamodb_client,s3_client}` modules (parallel, pre-A1.3b copies with no legal-hold logic at all — outside this workstream's scope, unmodified).

## 3. API Contract Implementation

No external API contract change. Internal constructor signatures gained additive, optional parameters (`hold_repository`, `transact_dynamodb_client`) — every existing production and test call site either supplies them (where the write path is exercised) or is unaffected (read-only call sites: `metadata_exists`, `update_terminal`, `object_exists`, `write_json`, `read_json`, `list_raw_evidence_keys`).

## 4. Data / Persistence Implementation

- RunMetadata: `ttl_disposal_at` conditionally present, computed via the already-merged `compute_ttl_disposal_at` (`hold_coordination.py`) — no local reimplementation.
- LegalHold: read-only from this subphase's own code (`get_legal_hold`); no write path here touches it.
- Raw-evidence S3 objects: `Tagging` string computed per call from `_raw_evidence_tagging(hold_state)`.

## 5. Key Logic Implemented

- **DynamoDB governed write**: `put_started_once` builds a `TransactItemsBuilder` closure capturing a shallow copy of the caller's item (never mutating the original); on each attempt, `HoldCoordinatedTransactionRunner` supplies the freshly-read `hold_state`, from which custody fields are recomputed and the governed `Put` + `LegalHold` `ConditionCheck` are built. `on_governed_condition_failed` raises `DuplicateRunIdError` directly, honoring the precedence rule (duplicate-write always wins over a same-attempt hold race) already enforced by the reused, unmodified `HoldCoordinatedTransactionRunner.run()`.
- **S3 governed write**: `write_raw_results_once` preserves the existing `object_exists` → `DuplicateRunIdError` check first (unchanged ordering), then requires a configured `hold_repository`, parses `client_id`/`audit_id` from the key (the locked `raw-results/{client_id}/{audit_id}/{run_id}/...` shape — avoids any signature/call-site change), performs a `ConsistentRead=True` read, computes tags, and only then calls `put_object`.
- **Cross-package exception translation**: `HoldCoordinatedTransactionRunner`/`HoldRepository` raise `release_confidence_platform.core.exceptions.StorageError` subclasses — a **different exception hierarchy** than this module's own `packages.core.exceptions.StorageError`, which `apps/backend/orchestrator/service.py`'s `except EngineError` boundary actually catches. Both `dynamodb_client.py` and `s3_client.py` now explicitly catch the foreign hierarchy and re-raise the local one, preserving `error_type`/`message` verbatim — this was a genuine gap I found and closed; without it, TD §19.15's distinguishable error codes (`HOLD_STATE_CONCURRENCY_EXCEEDED`, etc.) would have silently degraded into a generic `ORCHESTRATION_ERROR` at the orchestrator boundary.

## 6. Security / Authorization Implemented

- Uniform fail-closed (TD §19.14): both write paths refuse to proceed to completion — including refusing to attempt the write at all — whenever hold state cannot be deterministically resolved, whether because no `HoldRepository` was configured, the DynamoDB transaction's retry budget was exhausted, or the S3-side consistent read itself failed.
- No sensitive data logged; error messages follow the existing sanitized-context convention (`aws_error_code=...; operation=...`), never raw exception text from arbitrary caller-supplied hold-repository doubles.

## 7. Error Handling Implemented

| Code | Raised by | Meaning |
| --- | --- | --- |
| `HOLD_COORDINATION_NOT_CONFIGURED` | Both write paths | Constructed without a `hold_repository` — cannot resolve hold state at all. |
| `HOLD_STATE_CONCURRENCY_EXCEEDED` | DynamoDB path (re-surfaced from `hold_coordination.py`, unmodified) | Bounded retry exhausted against a genuine, sustained hold-version race. |
| `HOLD_STATE_UNRESOLVABLE` | S3 path | An unexpected (non-`StorageError`) failure resolving hold state — new code, distinct from the two TD §19.15 codes (which cover retry-exhaustion specifically), for the S3 leg's own "the read itself blew up" case. |
| (existing, unchanged) `DuplicateRunIdError` | Both | Existing duplicate-write contract, explicitly proven to win over a concurrent hold race in the same attempt. |
| (existing, unchanged) `CUSTODY_PERIOD_CONFIG_MISSING` | DynamoDB path | Unaffected — still raised before any write attempt. |

## 8. Observability / Logging

No new logging added beyond what `apps/backend/orchestrator/service.py`'s existing milestone-logging framework already captures around `put_started_once`/`write_raw_results_once` call sites (`metadata_started_write_failed`, `raw_result_write_failed`, etc.) — unchanged, and now correctly receives the translated local `StorageError` (see §5) so those log records carry the real `error_type` instead of a generic one.

## 9. Assumptions Made

- **`scheduled_execution_handler.py` requires the identical fix — resolved, see §0.** Not named in the original task brief. Flagged for review rather than silently included; Product Strategy has since reviewed the corrected, exhaustive entry-point inventory (§0) and explicitly approved this wiring as required, in-scope A1.LH3 work. No longer an open item.
- Raw-evidence S3 key shape is locked and single-producer (`build_raw_result_key`) — used to derive identity without touching `write_raw_results_once`'s signature or its one call site.
- `item["client_id"]`/`item["audit_id"]` are always present on `put_started_once`'s input (confirmed via `_started_item`).

No assumption here affects external behavior, security, billing, or permissions beyond what's already documented in the Technical Design.

## 10. Validation Performed

Targeted runs (all passing), full commands and counts:

```
uv run pytest -q tests/unit/test_run_metadata_custody_fields.py           # 23 passed
uv run pytest -q tests/unit/test_raw_evidence_s3_tagging.py               # 13 passed
uv run pytest -q tests/unit/evidence_retention/test_hold_repository.py    # 30 passed
uv run pytest -q tests/unit/test_lambda_handler_hold_repository_wiring.py # 2 passed
uv run pytest -q tests/unit/test_evidence_governance_a1_lh3_packaging.py  # 4 passed
uv run pytest -q tests/unit/test_phase1_core_engine.py                    # 58 passed
uv run pytest -q tests/unit/test_execution_identity_dynamodb.py           # 2 passed
uv run pytest -q tests/api/test_audit_run_orchestrator_observability.py   # 7 passed
uv run pytest -q tests/integration/test_phase1_orchestrator_integration.py    # 1 passed
uv run pytest -q tests/integration/test_phase2_orchestrator_payloads.py       # 2 passed
uv run pytest -q tests/integration/test_phase4a7_aggregation_envelope_compatibility.py # 2 passed
uv run pytest -q tests/security/test_phase1_qa_contracts.py               # 5 passed
```

Full canonical suite:

```
uv run pytest -q
# 1692 passed, 2 skipped (pre-existing, unrelated skips)
```

Lint:

```
uv run ruff check <all changed/new files>   # All checks passed!
uv run ruff check .                          # 69 errors — identical count/content to the
                                              # pre-change baseline (verified via git stash),
                                              # zero new issues introduced by this subphase.
```

## 11. Known Limitations / Follow-Ups

- The separate S3-succeeds-then-terminal-update-fails partial-failure defect (GitHub issue #112) is untouched, per explicit exclusion.
- A1.LH2's canary-marker mechanism is not invoked by this subphase (correctly, per scope) — the S3 leg's residual "read observed pre-race state" window remains closed by A1.LH2's reconciliation pass, not by anything added here.
- `scheduled_execution_handler.py`'s fix (see §9) was not explicitly pre-authorized by name; flagged for your review rather than silently included as obviously-in-scope.

## 12. Commit Status

**Not committed**, per explicit instruction. Working tree contains the changes described above, uncommitted, on branch `feature/a1-lh3-phase123-production-path-correction`.
