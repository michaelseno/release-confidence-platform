# Test Plan

## 1. Feature Overview

Evidence Governance Workstream A1, subphase A1.LH3 wires two already-merged production write paths — `packages/storage/dynamodb_client.py::put_started_once` and `packages/storage/s3_client.py::write_raw_results_once` — to the already-merged A1.LH1 hold-coordination mechanism, at **two** independent production entry points: `apps/backend/handlers/orchestrator_handler.py` (originally scoped) and `apps/backend/handlers/scheduled_execution_handler.py` (discovered second production writer, Product-Strategy-approved scope amendment). Full spec: `docs/architecture/adr_evidence_retention_disposal_enforcement.md` (Decision 3 amendment, Decision 9); `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md` §19.4/§19.5.4/§19.7/§19.8/§19.9/§19.14/§19.15.

This is an **independent QA validation pass** over implementation already completed and self-tested by the implementing dev agent (see `docs/backend/evidence_retention_a1_lh3_writepath_phase123_correction_implementation_report.md`). Scope: re-derive every material claim in that report from primary evidence (diffs, greps, test bodies, command output), not from the report's own narrative.

## 2. Acceptance Criteria Mapping

The 12 QA focus items supplied by the orchestrator constitute the acceptance criteria for this validation pass; each maps 1:1 to a scenario in Section 3.

| # | Acceptance criterion |
|---|---|
| 1 | Both handlers construct `HoldRepository` + `transact_dynamodb_client` |
| 2 | One shared `HoldRepository` instance per handler across both storage clients |
| 3 | `table.meta.client` (low-level), not the `Table` resource, supplied for transact capability |
| 4 | No unrelated runtime behavior change in either handler |
| 5 | Missing hold coordination fails closed (`HOLD_COORDINATION_NOT_CONFIGURED`) |
| 6 | Scheduled repeated execution remains functional when correctly wired |
| 7 | No silent fallback to an ungoverned write in the scheduled path |
| 8 | `orchestrator_handler.py`'s other invocation modes remain compatible |
| 9 | `infra/serverless.yml` packaging covers all newly-imported modules |
| 10 | No third production construction path reaches the governed writes |
| 11 | Hold-race/retry/consistent-read/terminal-immutability tests are real and pass |
| 12 | Issue #112 (S3-succeeds/terminal-update-fails defect) is untouched |

Plus: full canonical suite count, ruff (changed files + full-repo diff vs. `main` baseline), zero infra/custody/env changes, `update_terminal` byte-identity.

## 3. Test Scenarios

Executed as read/grep/diff/test-execution evidence gathering (no new test code authored — the implementing agent's existing/rewritten suite is the object under validation):

- Full `git diff main` review of both handler files, `dynamodb_client.py`, `s3_client.py`, `hold_repository.py`.
- Exhaustive `grep -rn` for `.put_started_once(` / `.write_raw_results_once(` across `apps/`, `packages/`, `src/`.
- Manual trace of the three claimed out-of-scope construction sites (`aggregation_handler.py`, `audit_finalization_handler.py`, both `aws_client_factory.py`).
- Read of `HoldRepository._call` / `HoldCoordinatedTransactionRunner.run` to independently confirm the low-level-client requirement (`TableName=` kwarg / `transact_write_items` are absent from a `Table` resource).
- Full-body read of every hold-race/retry/exhaustion/precedence/consistent-read/fail-closed test in `test_run_metadata_custody_fields.py`, `test_raw_evidence_s3_tagging.py`, `test_hold_repository.py`, `test_lambda_handler_hold_repository_wiring.py`, `test_evidence_governance_a1_lh3_packaging.py`.
- `uv run pytest -q` (full suite), targeted reruns of the affected/new test files.
- `uv run ruff check` on changed/new files; full-repo `uv run ruff check .` diffed against a `git stash`-restored `main` baseline.
- `git diff main --stat -- infra/` and full-repo `--stat` for infra/env/custody scope leakage.
- Direct read of `update_terminal`'s body and a full-repo diff check on `apps/backend/orchestrator/service.py` for Issue #112 non-interference.

## 4. Edge Cases

- Concurrent PLACE/RELEASE racing a RunMetadata CREATE (both directions), including a hold_version bump with unchanged status (aliasing risk).
- Bounded retry exhaustion under a perpetual hold-version race (fail-closed, zero partial writes).
- Governed record's own duplicate-write condition failing in the same attempt as a hold-version race (precedence rule).
- S3 tagging staleness (module-level constant regression) proven via two writes through one client instance with hold state mutated in between.
- Hold-repository read failure (both the cross-package `StorageError` re-wrap path and an arbitrary non-`StorageError` exception) before any `put_object`.
- Missing `hold_repository` on both storage clients (constructor-level fail-closed).

## 5. Test Types Covered

- Static/structural (diff review, grep-based call-site inventory, packaging pattern-list assertions).
- Unit (hold-race/retry/precedence/fail-closed/consistent-read, run via `pytest`).
- Integration (`test_phase1_orchestrator_integration.py`'s unheld end-to-end `CoreEngineOrchestrator.run()`, wiring tests for both Lambda `handler()` entry points).
- Regression (full canonical suite, ruff full-repo diff, service.py/`update_terminal` byte-identity).

## 6. Coverage Justification

All 12 required items plus the 4 additional required checks map to at least one concrete, independently-reproduced piece of evidence (file:line diff, grep output, test body read, command output) in the corresponding test report. No item was accepted on the implementation report's narrative alone — every claim was re-derived. One item (scenario 6) has evidence gathered from two composed tests rather than a single literal end-to-end test through `scheduled_execution_handler.handler()`; flagged as a CONCERN in the report rather than silently treated as fully covered.
