# Test Report

Branch under validation: `feature/a1-lh3-phase123-production-path-correction` (based on `main@1bf666b8d587de18e91440ac2b68e25b51734e4e`), working tree, uncommitted. Independent QA validation pass — no application code modified by QA.

## 1. Execution Summary

- Full canonical suite: **1692 passed, 2 skipped** — matches implementation report's claim exactly.
- Targeted A1.LH3-affected suites: 225 passed (packaging, wiring, and all `evidence_retention/` unit tests).
- `ruff check` on all changed/new files: **All checks passed!**
- `ruff check .` (full repo) on branch: **69 errors**, byte-identical (via sorted-diff) to a `git stash`-restored `main` baseline run — **zero new issues**.
- 12/12 required QA focus items: **PASS**, with one item (6) carrying a **CONCERN** (evidence is strong but composed from two tests rather than one literal end-to-end trace through the specific handler).
- 4/4 additional required checks: **PASS**.

## 2. Detailed Results — 12 Required QA Focus Items

**1. Both handlers construct `HoldRepository` and `transact_dynamodb_client` — PASS**
`git diff main -- apps/backend/handlers/orchestrator_handler.py`: adds `hold_repository = HoldRepository(os.environ["METADATA_TABLE"], table.meta.client)`; `DynamoDBMetadataClient(os.environ["METADATA_TABLE"], table, hold_repository, table.meta.client)`. Identical pattern in `scheduled_execution_handler.py` (line 291–294). Both diffs read in full; no other construction site exists in either file.

**2. One shared `HoldRepository` instance per handler — PASS**
Both diffs construct `hold_repository` exactly once and pass the same local variable into both `S3StorageClient(...)` and `DynamoDBMetadataClient(...)`. Proven at runtime, not just by inspection, by `tests/unit/test_lambda_handler_hold_repository_wiring.py::test_orchestrator_handler_constructs_one_hold_repository_shared_by_both_clients` and its scheduled-handler counterpart: `assert metadata_storage._hold_repository is s3_storage._hold_repository` (identity check, both pass).

**3. `table.meta.client` supplied, not the `Table` resource — PASS**
Confirmed in both handler diffs (`table.meta.client` passed to `HoldRepository(...)` and as `DynamoDBMetadataClient`'s 4th positional arg). Independently verified this is *required*, not cosmetic: `HoldRepository._call` (`src/release_confidence_platform/evidence_retention/hold_repository.py:416-419`) invokes `method(TableName=self.table_name, **kwargs)` — a `boto3.resource("dynamodb").Table` method does not accept a `TableName` kwarg (it's implicit in the resource). `HoldCoordinatedTransactionRunner.run` (`hold_coordination.py:199`) calls `self._dynamodb_client.transact_write_items(...)`, a method that does not exist on a `Table` resource at all. Both wiring tests assert `metadata_storage._hold_repository.dynamodb_client is low_level_client` and `metadata_storage.dynamodb_client is fake_boto3.table` (the Table resource) in the same test — proving the split is correct, not accidental.

**4. No unrelated runtime behavior change in either handler — PASS**
Full `git diff main` read for both files. `orchestrator_handler.py`: 22 lines changed total — one new import, one new comment block, and the `s3_storage`/`table`/`metadata` construction block. `scheduled_execution_handler.py`: 22 lines changed — same shape. No other line in either file (imports, other handler logic, error handling, logging) is touched.

**5. Missing hold coordination fails closed — PASS**
`dynamodb_client.py::put_started_once`: `if self._hold_coordination_runner is None or self._hold_repository is None: raise StorageError(..., "HOLD_COORDINATION_NOT_CONFIGURED")`. `s3_client.py::write_raw_results_once`: `if self._hold_repository is None: raise StorageError(..., "HOLD_COORDINATION_NOT_CONFIGURED")`. Both proven by passing tests: `test_put_started_once_fails_closed_when_hold_repository_not_configured` (`tests/unit/test_run_metadata_custody_fields.py:577`) and `test_write_raw_results_once_fails_closed_when_hold_repository_not_configured` (`tests/unit/test_raw_evidence_s3_tagging.py:249`) — both read in full, both assert the exact error code and assert no write side effect occurred (`low_level.transact_write_items_calls == []` / `api.put_object_calls == []`).

**6. Scheduled repeated execution remains functional when correctly wired — PASS, with CONCERN**
No single test drives an actual write end-to-end through `scheduled_execution_handler.handler()` itself (its own wiring test, `test_scheduled_execution_handler_constructs_one_hold_repository_shared_by_both_clients`, monkeypatches `CoreEngineOrchestrator` out entirely and never exercises a real write). Functional completion is instead proven by composing two independently-verified facts: (a) the wiring test proves `scheduled_execution_handler.handler()` constructs an identical `CoreEngineOrchestrator(s3_storage=S3StorageClient(...), metadata_storage=DynamoDBMetadataClient(...))` pattern to `orchestrator_handler.py`, correctly hold-repository-wired; (b) `tests/integration/test_phase1_orchestrator_integration.py::test_orchestrator_completes_with_mocked_aws_and_http` proves that exact `CoreEngineOrchestrator` construction (same classes, same constructor signature, an unheld `HoldRepository` stand-in) completes a full run end-to-end through the real `put_started_once`/`write_raw_results_once` hold-coordinated code paths. This is sound inferential evidence, not a gap in the implementation, but it is a gap in direct test coverage — recommend (non-blocking) a follow-up test that drives `scheduled_execution_handler.handler()` itself through a completed run, for the same reason `test_lambda_handler_hold_repository_wiring.py` exists for wiring in isolation.

**7. No silent fallback to an ungoverned write in the scheduled path — PASS**
Full read of `scheduled_execution_handler.py::handler()` (lines 274–302): a single, unconditional construction path — `hold_repository` is always built and always passed to both storage clients; there is no branch, default, or optional path that constructs either client without it. Storage-client-level fail-closed checks (item 5) provide a second independent backstop even if a future change to the handler ever regressed this.

**8. `orchestrator_handler.py`'s other invocation modes remain compatible — PASS**
Same diff evidence as item 4 — the only signature/behavior change is additive optional constructor parameters (`hold_repository`, `transact_dynamodb_client`) on `DynamoDBMetadataClient`/`S3StorageClient`; every other production and test call site either supplies them or is unaffected (read-only methods: `metadata_exists`, `object_exists`, `write_json`, `read_json`, `list_raw_evidence_keys`). Confirmed via `grep -rn "DynamoDBMetadataClient(\|S3StorageClient("` — no other construction site in the diff footprint besides the two handlers and the test-fixture updates.

**9. Lambda packaging covers all newly-imported modules — PASS**
`infra/serverless.yml` `package.patterns` (read directly, lines 127-151) includes `'../packages/storage/**'`, `'../src/release_confidence_platform/evidence_retention/**'`, `'../src/release_confidence_platform/storage/**'`, `'../src/release_confidence_platform/core/**'` — all present, unmodified by this branch (`git diff main -- infra/serverless.yml` is empty). Independently confirmed `dynamodb_codec.py` physically exists at `src/release_confidence_platform/storage/dynamodb_codec.py` (covered by the `storage/**` pattern) and is the module `dynamodb_client.py` now imports (`from release_confidence_platform.storage.dynamodb_codec import encode_item`). New regression test `tests/unit/test_evidence_governance_a1_lh3_packaging.py` makes this durable (parses the YAML directly, asserts each required pattern is present, asserts no per-function override exists) — 4/4 tests pass.

**10. No third production construction path reaches the governed writes — PASS**
Independently re-derived, not trusted from the report: `grep -rn ".put_started_once(\|.write_raw_results_once(" apps/ packages/ src/` returns exactly two matches, both in `apps/backend/orchestrator/service.py` (`service.py:102` and `service.py:222`), both inside `CoreEngineOrchestrator`. Separately traced all other `DynamoDBMetadataClient`/`S3StorageClient` construction sites:
- `apps/backend/handlers/aggregation_handler.py:16,56` — imports `release_confidence_platform.storage.s3_client.S3StorageClient` (the divergent `src/` mirror class, confirmed by import path, not `packages.storage.s3_client`), and the file contains no call to `write_raw_results_once` (grepped for `s3_storage\.` — only usage is in the `AggregationOrchestrator` which reads, per its own docstring purpose).
- `apps/backend/handlers/audit_finalization_handler.py:29,614` — imports `packages.storage.s3_client.S3StorageClient` (the class this subphase modified) but the only method call found via `grep -n "s3_storage\."` is `list_raw_evidence_keys` (line 261) — never `write_raw_results_once`.
- `packages/storage/aws_client_factory.py` and `src/release_confidence_platform/storage/aws_client_factory.py` — both read in full; `s3_storage()` is a factory method returning an `S3StorageClient`, but neither file, nor any CLI command reachable from it, calls `write_raw_results_once` or `put_started_once` (consistent with the earlier exhaustive 2-call-site grep, which covers the whole repo including any CLI call sites).

**11. Hold-race/retry/consistent-read/terminal-immutability tests remain valid — PASS**
Full bodies read, not just names counted, for:
- `test_put_started_once_retries_and_resolves_when_place_races_creation` / `..._release_races_creation` / `..._stale_hold_version_forces_retry_even_when_status_unchanged` (`test_run_metadata_custody_fields.py:397-463`) — each uses a realistic wire-format DynamoDB double (`_LowLevelClient.transact_write_items`) with a `before_transact` hook that injects a real race between the read and the commit of a given attempt, then asserts both the persisted `ttl_disposal_at` state and the exact retry-attempt count. These are genuine race simulations, not name-only stubs.
- `test_put_started_once_fails_closed_on_bounded_retry_exhaustion` (line 466) — perpetual race, asserts `HOLD_STATE_CONCURRENCY_EXCEEDED`, exact attempt count equals `MAX_HOLD_COORDINATION_RETRY_ATTEMPTS`, and zero partial writes (`_stored_run_metadata(store) is None`).
- `test_put_started_once_governed_condition_failure_wins_over_concurrent_hold_race` (line 490) — proves the documented precedence rule directly by attempt-count assertion, not just by exception type.
- `test_get_legal_hold_default_does_not_send_consistent_read_kwarg` / `..._consistent_read_true_sends_consistent_read_kwarg` / `..._still_returns_decoded_item` (`tests/unit/evidence_retention/test_hold_repository.py`, new) — a capturing low-level-client double asserting the exact kwargs sent to `get_item`, both default (byte-identical to pre-A1.LH3) and `consistent_read=True` cases.
- `test_write_raw_results_once_does_not_reuse_stale_module_level_hold_state` / `..._place_racing_creation_is_observed_by_a_later_write` / `..._release_racing...` (`test_raw_evidence_s3_tagging.py:168-221`) — two writes through one client instance with hold state mutated between them; asserts the tag actually differs, the direct regression test for the defect this subphase fixes.
- `test_update_terminal_never_touches_custody_fields` (`test_run_metadata_custody_fields.py:592`) — read in full; exercises `update_terminal` after a `put_started_once` and asserts custody fields are absent from the update payload.
All of the above, plus the full `evidence_retention/` suite (225 tests total including A1.LH1's own unmodified `test_hold_coordination.py`, 15 tests, untouched by this diff), executed and passed: `uv run pytest -q tests/unit/test_evidence_governance_a1_lh3_packaging.py tests/unit/test_lambda_handler_hold_repository_wiring.py tests/unit/evidence_retention/` → **225 passed in 0.55s**.

**12. Issue #112 remains untouched — PASS**
`git diff main --quiet -- apps/backend/orchestrator/service.py` → exit code confirms **zero diff** on the entire file, i.e. both `_failure_response` and `update_terminal`'s call site are byte-identical to `main`. `packages/storage/dynamodb_client.py::update_terminal`'s body (lines 281-306) contains no reference to `_hold_repository`, `_hold_coordination_runner`, custody, or hold fields — confirmed by direct read; the diff hunk for this file ends before `update_terminal` and does not touch it. Repo-wide grep for `#112`/`issue_112`/`issue #112` across every changed and new file in this branch (tracked and untracked) returns zero matches — no test or code change claims to address that issue.

## 3. Failed Tests

None. No test failures encountered during this validation pass.

## 4. Failure Classification

Not applicable — no failures.

## 5. Observations

- No flakiness observed; full suite (1692 tests) and all targeted reruns were deterministic across repeated invocation.
- The implementation report's §0 Scope Amendment and its entry-point inventory table were independently re-derived from primary evidence (grep, diff, direct file reads) rather than trusted — all claims in that table checked out exactly as stated.
- Item 6 (see above) is the only item where evidence, while sound, is inferential/composed rather than a single direct end-to-end test. This does not block sign-off — the underlying construction code is identical and independently proven correct at both the wiring level and the write-path level — but is flagged as a minor coverage gap for the implementing team's awareness.
- Cross-package exception re-wrapping (`_HoldCoordinationStorageError` → local `StorageError`, both `dynamodb_client.py` and `s3_client.py`) is a genuine, correctly-tested addition beyond the original task briefing — verified via `test_write_raw_results_once_hold_read_storage_error_is_reraised_with_original_code` and equivalent DynamoDB-path coverage; without it, TD §19.15's distinguishable error codes would not survive the orchestrator's `except EngineError` boundary.

## 6. Regression Check

- Full canonical suite: 1692 passed, 2 skipped — matches implementation report's claim exactly; no regression in any unrelated area of the codebase.
- `uv run ruff check .` full-repo output is byte-identical (sorted diff, zero lines) between the branch and a `git stash`-restored `main` baseline — zero new lint issues.
- `git diff main --stat` confirms only 5 production files, 8 modified test files, and 2 new test files changed — no infra, config, or unrelated-module changes.
- `git diff main -- infra/serverless.yml` and `git diff main --stat -- infra/` are both empty — zero infra changes, confirming no custody-duration, environment-variable, or deployment changes were introduced.
- `apps/backend/orchestrator/service.py` has zero diff — Issue #112's code (`_failure_response`, `update_terminal` call site) is fully unaffected.
- `packages/storage/dynamodb_client.py::update_terminal` body confirmed unchanged and still never references custody/hold fields (TD §19.7 row 2 invariant preserved).
- A1.LH1's own test suite (`test_hold_coordination.py`, 15 tests) and the rest of `evidence_retention/` (`test_custody_sweep_client.py`, `test_disposal_repository.py`, `test_hold_transitions.py`, `test_marker_store.py`, `test_models.py`, `test_retention_service.py`) all pass unmodified — A1.LH1/A1.LH2 mechanisms are consumed, not altered.

## 7. QA Decision

All 12 required focus items independently verified PASS (one with a non-blocking CONCERN noted for follow-up, not a defect). All 4 additional required checks PASS. Full canonical suite matches the claimed 1692 passed / 2 skipped. Ruff shows zero new issues on changed files and zero new issues repo-wide against the `main` baseline. No infra, custody, or environment scope leakage. Issue #112 confirmed untouched. Test evidence for hold-race/retry/precedence/consistent-read/fail-closed/terminal-immutability behavior was read in full (not just counted) and is genuine, realistic coverage, not superficial.

No blocking defects. No unresolved failures. No regressions.

[QA SIGN-OFF APPROVED]
