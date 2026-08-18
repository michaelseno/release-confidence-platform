# Test Plan

## 1. Feature Overview

A1.4b implements the first `rcp retention hold place|release|status` operator CLI commands
(Evidence Governance Workstream A1, Evidence Retention Enforcement) and corrects a genuine
pre-existing return-contract defect in `RetentionService.place_legal_hold`/`release_legal_hold`
(they previously returned the pre-sweep `HoldTransitionOutcome` snapshot instead of the audit
identity's authoritative, currently-persisted `LegalHold` state). The correction is authorized by
companion ADR `docs/architecture/adr_evidence_retention_disposal_enforcement.md` Decision 12 and
Non-Negotiable Invariants 32-37, and specified exactly by Technical Design
`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
§21 (all of §21.1-§21.11), whose §21.10 defines the 19-item required QA scenario checklist this
plan implements one-to-one.

Files under test: `evidence_retention/hold_transitions.py`, `evidence_retention/retention_service.py`,
`operator_cli/main.py`, `operator_cli/result.py` (modified); `evidence_retention/commands.py` (new,
first implementation); `tests/unit/evidence_retention/test_hold_transitions.py`,
`tests/unit/evidence_retention/test_retention_service.py`, `tests/unit/test_operator_cli_result.py`
(modified); `tests/unit/test_operator_cli_retention.py` (new).

## 2. Acceptance Criteria Mapping

| TD §21.10 Item | Acceptance Criterion | Validation Method |
| --- | --- | --- |
| 1 / 1a | `HoldTransitionOutcome.is_resumption` — all 5 branches correctly assigned, both at the consolidated regression test and the individual PLACE/RELEASE test level | Direct read of `hold_transitions.py`'s 5 construction sites + `test_hold_transitions.py` assertions |
| 2/3 | Fresh/resumed/no-op PLACE — disposition, `hold_count`/`hold_version`, zero activity on no-op | Read `retention_service.py`/`hold_transitions.py` + `test_retention_service.py`/`test_hold_transitions.py` |
| 4/6 | Fresh/resumed RELEASE, `HOLD_NOT_ACTIVE` (both sub-cases) | Read `hold_transitions.py::release` + existing `test_hold_transitions.py` tests |
| 7-11 | All 5 STATUS states and `fully_enforced` correctness in each | Read `retention_service.py::get_hold_status`/`is_hold_fully_enforced` + `test_retention_service.py` |
| 12/19 | STATUS `consistent_read=True` on every call incl. `NEVER_HELD`; zero AWS mutation | Read + fake-repository call-log assertions in `test_retention_service.py` |
| 13 | Final persisted `COMPLETE` vs. stale pre-sweep state (§21.4.1 defect) | Read `_build_result`/`place_legal_hold`/`release_legal_hold` + regression assertions |
| 14 | Mandatory non-empty `--reason` (PLACE+RELEASE), incl. whitespace-only, rejected pre-service-call | Read `commands.py::_require_non_empty_reason` + `test_operator_cli_retention.py` |
| 8/9 (task) | `main.py` constructs exactly one of each dependency, exactly one `RetentionService` | Read `main.py` dispatch branch + construction-count/identity test |
| 16 | `commands.py` never calls `HoldRepository` methods directly — structural, not superficial | AST-based source inspection test + independent manual source read |
| 17 | Sanitized text/JSON — no PK/SK/S3 key/marker fields/`placed_by`/`released_by`/`reason` | Read `HoldOperationResult` dataclass + `result.py` rendering + rendering tests |
| 11 (task) | Exact `HoldOperationResult` 11-field contract | Structural field-set equality test + manual dataclass read |
| 18 | No `s3_versions_retagged_count`/`dynamodb_items_updated_count` anywhere | grep across touched production files + structural tests |
| 15 | `HOLD_ALREADY_ACTIVE` not an operative error path (production code, not just tests) | grep across `src/` + negative tests |
| 14 (task) | `HOLD_STATE_CONCURRENCY_EXCEEDED` not reachable from these 3 commands; existing usage elsewhere untouched | grep across repo + diff review + negative test |
| 15 (task) | Full regression suite — exact pass/skip/fail counts, zero unexpected regression on `HoldTransitionOutcome`/`RetentionService` references | `uv run pytest -q` + targeted suite reruns + `grep -rln` |
| 16 (task) | `ruff check`/`ruff format --check` vs. independently reproduced pre-branch baseline | `git stash`-based baseline reproduction, not report-trusted |
| 17 (task) | `git diff --check` | Direct command run |
| 18 (task) | Changed file set is exactly the 9 files listed, nothing else | `git status --porcelain` |
| 19 (task) | Both flagged judgment calls accurately described, consistent with pre-existing precedent | Direct source read of `validate_identifier`, `audit_platform_integrity/commands.py`, `result.py::render` |
| 20 (corrective) | Invalid `client_id`/`audit_id` surfaces as `INVALID_IDENTIFIER` (TD §21.5), never `INVALID_EVENT`, for `place`/`release`/`status`, in text and JSON, with zero `RetentionService` method calls and no leaked raw value/exception detail/traceback/DynamoDB key/AWS detail | Direct read of `commands.py::_validate_hold_identifier` + 18 new tests in `test_operator_cli_retention.py` (6 direct-dispatch, 12 parametrized end-to-end) |

## 3. Test Scenarios

1. Read ADR Decision 12 / Invariants 32-37 and Technical Design §21.1-§21.11 in full before touching code.
2. Read the full `git diff` for all 7 modified files and the full content of both new files.
3. Independently verify all 5 `is_resumption` branch assignments against `hold_transitions.py` source and both the consolidated and per-test assertions in `test_hold_transitions.py`.
4. Independently verify `HoldOperationResult`'s field set (11 fields, no more/fewer) against `retention_service.py` and the structural test in `test_retention_service.py`.
5. Independently verify `_build_result`'s `NEVER_HELD` branch and the 4 `ACTIVE`/`RELEASED` × complete/incomplete permutations against `is_hold_fully_enforced` and `test_retention_service.py`'s 5 STATUS tests.
6. Independently verify `get_hold_status` issues `consistent_read=True` unconditionally, including for the `NEVER_HELD` path, and confirm zero mutation via fake-repository call-log assertions.
7. Independently verify the §21.4.1 defect correction: `place_legal_hold`/`release_legal_hold` return a freshly re-read `HoldOperationResult`, not the pre-sweep `HoldTransitionOutcome`.
8. Independently verify `commands.py::_require_non_empty_reason` rejects missing and whitespace-only `--reason` for both PLACE and RELEASE, before any `RetentionService` call.
9. Independently verify `main.py`'s `retention` dispatch branch constructs exactly one of each dependency and exactly one `RetentionService`, via the construction-count/identity test in `test_operator_cli_retention.py`.
10. Independently verify the AST-based structural test in `test_operator_cli_retention.py` genuinely proves `commands.py` never references `HoldRepository`/`get_legal_hold`/`upsert_hold`/`write_hold_event`, by reading both the test's AST-walk logic and `commands.py`'s actual source.
11. Independently verify sanitized rendering — no forbidden field ever appears in text or JSON output, for both success and error paths.
12. Independently verify the exact `HoldOperationResult` field set matches TD §21.4's 11-field list, and that no count field exists anywhere in the dataclass, `CommandResult.data`, or rendered output.
13. grep `src/` for `HOLD_ALREADY_ACTIVE` to confirm it is not an operative production error path.
14. grep the repository for `HOLD_STATE_CONCURRENCY_EXCEEDED` usage and diff-review every file that references it to confirm none were touched by this branch except the confirmed-unchanged `result.py` branch.
15. Run `uv run pytest -q` and the 4 targeted suites individually; compare counts to the implementation report's claims.
16. Run `uv run ruff check`/`ruff format --check` on all touched files; for any finding, reproduce it against a `git stash`-derived pre-branch baseline using the real file paths (not copies, to preserve per-file-ignore fidelity) to confirm pre-existence.
17. Run `git diff --check`.
18. Run `git status --porcelain` and diff the result against the required 9-file (7 modified + 2 new production/test) set, ignoring the pre-existing unrelated `AGENTS.md` and the 2 doc files this subphase itself adds.
19. Read `core/validators.py::validate_identifier` and `audit_platform_integrity/commands.py::dispatch_certify_audit` directly to confirm the `INVALID_EVENT` vs. `INVALID_IDENTIFIER` claim; read `result.py::render`'s dict-spread order directly to confirm the `CommandResult.data["status"]` collision claim; confirm the `status` collision is pre-existing, unmodified-by-this-branch, accepted behavior.
20. **Corrective (post-QA release-readiness review):** independently verify `commands.py::_validate_hold_identifier` — reuses `validate_identifier`'s rules unchanged, catches its `INVALID_EVENT` failure, re-raises `ValidationError` with `error_type == "INVALID_IDENTIFIER"`, references only the identifier name (never the raw value or original exception detail) in its message. Run the 6 direct-dispatch tests and the 12-case parametrized end-to-end test in `test_operator_cli_retention.py` covering all 3 commands x both output formats x both identifier fields; confirm `INVALID_EVENT` is asserted absent from every rendered output and `INVALID_IDENTIFIER` is asserted present; confirm `core/validators.py` is unmodified.

## 4. Edge Cases

- Whitespace-only (not just empty-string) `--reason` for both PLACE and RELEASE.
- STATUS queried for an audit identity that was never held (`NEVER_HELD`), including confirming the strongly consistent read still happens on this path (no early-return that skips `consistent_read=True`).
- A completed PLACE no-op (`sweep_status=COMPLETE` already) must trigger zero marker/sweep/`LegalHoldEvent`/`LegalHold` write activity — not merely a "did not raise" check.
- RELEASE's structurally equivalent no-op case does not exist as a no-op; it must raise `HOLD_NOT_ACTIVE` instead, and this must not regress to a silent no-op.
- The disposition-precedence order (`is_noop` → `is_resumption` → `"completed"`) must be exercised in a case where `is_resumption` could be misread if checked first (the no-op branch, which also has `is_resumption=False` for internal-consistency reasons only).
- A `commands.py` structural check that only inspects call-site tokens could be defeated by dynamic dispatch (e.g., `getattr(x, "get_legal_hold")`); confirm the actual `commands.py` source contains no such pattern independent of what the AST test happens to catch.
- Ruff findings reproduced against a copied-out baseline file (rather than the real path via `git stash`) risk false negatives from per-file-ignore path matching; the baseline reproduction in this campaign uses `git stash` on the real paths specifically to avoid this.
- An invalid `client_id`/`audit_id` supplied to `place`/`release`/`status` — the `INVALID_IDENTIFIER` translation must fire identically for both identifier fields and all three commands, must never call any `RetentionService` method, and the rendered error (text and JSON) must contain no raw invalid value, no internal exception detail/traceback, no DynamoDB storage key, and no AWS-specific detail — verified as a real, executable negative assertion that `INVALID_EVENT` never appears anywhere in `retention hold` command output, not merely an absent test for the old behavior.

## 5. Test Types Covered

- Unit test independent verification (existing + new tests in the 4 test files)
- Structural/static verification (AST-based prohibition test, field-set equality tests, source grep)
- Regression verification (full suite re-run, targeted `HoldTransitionOutcome`/`RetentionService` reference audit)
- Static analysis (`ruff check`, `ruff format --check`, both independently re-baselined)
- Repository hygiene verification (`git diff --check`, exact changed-file-set confirmation)
- Documentation-consistency verification (implementation report's flagged assumptions cross-checked against actual codebase precedent)

## 6. Coverage Justification

Technical Design §21.10 defines a closed, 19-item required QA scenario checklist for this exact
subphase; this plan maps to it item-for-item, with two additional task-specific items (main.py
composition construction-count assertion; assumption/precedent verification) not separately
numbered in §21.10 but explicitly required by the QA dispatch. No test file is out of scope: all
4 touched/new test files, all 5 touched/new production files, and the full pre-existing regression
suite are covered. Coverage is complete for this subphase's stated scope — infrastructure,
deployment, and numeric custody-duration concerns remain explicitly out of scope per the ADR/TD's
own "documentation-only correction, does not authorize deployment" framing, and are not tested here
as this is CLI/service-contract logic with no AWS-integration or deployment surface.
