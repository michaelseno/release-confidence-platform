# Implementation Report

## 1. Summary of Changes

Implemented A1.4b: the Operator CLI and `RetentionService` contract
correction authorized by companion ADR Decision 12 / Non-Negotiable
Invariants 32-37 and Technical Design §21. This is the first
`rcp retention hold place|release|status` CLI implementation in the
repository (no `commands.py` previously existed under `evidence_retention/`
and `operator_cli/main.py` never imported `RetentionService`), and it
corrects a genuine pre-existing defect: `RetentionService.place_legal_hold`/
`release_legal_hold` previously returned the pre-sweep `HoldTransitionOutcome`
snapshot instead of the audit identity's authoritative, currently-persisted
hold state.

**Corrective update (post-QA release-readiness review):** Product Strategy's
release-readiness review identified one blocking behavioral defect before
this could ship: invalid `client_id`/`audit_id` was surfacing as error code
`INVALID_EVENT` (leaked, unwrapped, from the codebase-wide
`validate_identifier` helper) instead of TD §21.5's required
`INVALID_IDENTIFIER`. This has been corrected with a narrow, A1.4b-local
`_validate_hold_identifier` translation boundary added to `commands.py` —
see §2/§5/§7/§9 below for the fix and §10 for the 18 added regression tests
and updated validation evidence. `core/validators.py` was not modified. No
other implementation or QA finding from the original pass changed.

## 2. Files Modified

- `src/release_confidence_platform/evidence_retention/hold_transitions.py` —
  `HoldTransitionOutcome` gains `is_resumption: bool`, set at all five
  existing branch points.
- `src/release_confidence_platform/evidence_retention/retention_service.py` —
  new `HoldOperationResult` dataclass, new `get_hold_status` method, new
  `_build_result` helper, `place_legal_hold`/`release_legal_hold` return-type
  change to `HoldOperationResult`, stale `HoldStateConcurrencyExceededError`
  docstring claims corrected.
- `src/release_confidence_platform/operator_cli/main.py` — new `retention`
  argparse group registration, new dispatch branch constructing
  `HoldRepository`/`CustodySweepClient`/`MarkerStore`/`HoldTransitions`/
  `RetentionService` once per invocation and calling `dispatch_retention_hold`,
  `_command_name` updated for the new group.
- `src/release_confidence_platform/operator_cli/result.py` — text-rendering
  helper `_append_hold_operation_fields` for the nine `HoldOperationResult`
  fields, wired into `render()`; three new `_error_next_step` branches
  (`HOLD_NOT_ACTIVE`, `HOLD_MARKER_ESTABLISHMENT_FAILED`,
  `HOLD_MARKER_INTEGRITY_VIOLATION`).
- `src/release_confidence_platform/evidence_retention/commands.py` (new,
  subsequently corrected in a post-QA release-readiness pass) —
  `build_retention_hold_parser`/`dispatch_retention_hold`, the parser and
  dispatch layer for the three commands. **Correction:** added
  `_validate_hold_identifier`, a narrow, A1.4b-local translation boundary
  that reuses `core.validators.validate_identifier`'s identifier-format
  rules unchanged but catches its `INVALID_EVENT` failure and re-raises a
  sanitized `ValidationError` with error code `INVALID_IDENTIFIER` — TD
  §21.5's exact, authoritative requirement for this command group. Applies
  identically to `client_id`/`audit_id` and to `place`/`release`/`status`;
  `core/validators.py` itself is unmodified. See §5/§7/§9 below.
- `tests/unit/evidence_retention/test_hold_transitions.py` — `is_resumption`
  assertions added to the five relevant existing tests, plus one consolidated
  regression test covering all five branches directly.
- `tests/unit/evidence_retention/test_retention_service.py` — fake
  `HoldRepository.get_legal_hold` updated to accept `consistent_read`;
  `outcome.is_noop`-based assertions replaced with `outcome.disposition`;
  new section covering `get_hold_status` (`NEVER_HELD`, all four
  `fully_enforced` permutations, strongly consistent reads, zero-mutation
  guarantee) and the no-fabricated-count-fields / exact-field-set structural
  tests.
- `tests/unit/test_operator_cli_result.py` — new tests for the three new
  `_error_next_step` branches, a negative test proving `HOLD_ALREADY_ACTIVE`
  has no dedicated guidance, a negative test proving
  `HOLD_STATE_CONCURRENCY_EXCEEDED`'s existing branch gained no
  retention-specific wording, and rendering tests for `HoldOperationResult`
  fields (text and JSON, including the `NEVER_HELD` case and the
  forbidden-field leak check).
- `tests/unit/test_operator_cli_retention.py` (new, subsequently extended in
  the same corrective pass) — `dispatch_retention_hold` unit tests (reason
  validation, correct single-method dispatch per subcommand,
  internally-generated timestamp, exact return field set), an AST-based
  structural test proving `commands.py` never references
  `HoldRepository`/`CustodySweepClient`/`MarkerStore`/`HoldTransitions`, and
  `main()`-level composition/end-to-end tests (construction wiring, JSON/text
  output, error propagation, missing/empty `--reason` never reaching the
  service). **Correction — 18 new tests added** covering the
  `INVALID_IDENTIFIER` translation boundary: 6 direct
  `dispatch_retention_hold` tests (`test_dispatch_{place,release,status}_invalid_{client,audit}_id_raises_invalid_identifier_no_service_call`)
  proving each of `place`/`release`/`status` raises `ValidationError` with
  `error_type == "INVALID_IDENTIFIER"` for an invalid `client_id` or
  `audit_id`, with zero calls recorded on the fake `RetentionService`
  double; plus a 12-case parametrized end-to-end test
  (`test_main_invalid_identifier_renders_invalid_identifier_not_invalid_event`,
  parametrized over the 3 commands x 2 output formats x 2 identifier fields)
  proving `INVALID_EVENT` never appears anywhere in rendered `retention
  hold` output (text or JSON), `INVALID_IDENTIFIER` is the rendered code in
  both formats, no raw invalid identifier value/exception detail/
  traceback/DynamoDB storage key/AWS-specific detail leaks into the output,
  and `RetentionService` is constructed but none of its
  place/release/status methods are ever called.
- `docs/backend/a1_4b_operator_cli_retention_service_implementation_plan.md`
  (new).

## 3. API Contract Implementation

Three new CLI commands, exactly as specified in Technical Design §21.5, no
others:

- `rcp retention hold place --client-id --audit-id --stage --actor --reason`
- `rcp retention hold release --client-id --audit-id --stage --actor --reason`
- `rcp retention hold status --client-id --audit-id --stage`

All three return `HoldOperationResult`, rendered through the unmodified
`sanitize()`/`render()`/`render_error()` pipeline.

## 4. Data / Persistence Implementation

No data model or storage changes. `HoldOperationResult` is a pure in-memory,
operator-facing result contract, never persisted. No new DynamoDB fields, no
new S3 objects, no schema changes.

## 5. Key Logic Implemented

- **`is_resumption` (hold_transitions.py):** set `False` on fresh PLACE,
  `True` on resumed PLACE, `False` on completed-PLACE no-op, `False` on
  fresh RELEASE, `True` on resumed RELEASE — exactly TD §21.4.1 item 4's
  five assignments.
- **`HoldOperationResult` (retention_service.py):** exact eleven-field
  contract (`client_id`, `audit_id`, `hold_id`, `hold_version`, `status`,
  `sweep_status`, `fully_enforced`, `placed_at`, `released_at`, `hold_count`,
  `disposition`) — no additional field.
- **`_build_result`:** re-reads `HoldRepository.get_legal_hold(...,
  consistent_read=True)`, maps to `HoldOperationResult`, including the
  `NEVER_HELD` branch (`status="NEVER_HELD"`, all other fields per §21.4).
  Shared by `place_legal_hold`/`release_legal_hold`'s success paths (with
  disposition derived from `outcome.is_noop`/`outcome.is_resumption` in the
  documented precedence order: no_op → resumed → completed) and
  `get_hold_status` (disposition always `None`).
- **`get_hold_status`:** one `get_legal_hold(consistent_read=True)` call, zero
  mutation, no marker/sweep/DynamoDB-write/S3-call of any kind.
- **`commands.py` dispatch:** validates `client_id`/`audit_id` via
  `_validate_hold_identifier` — a narrow, A1.4b-local translation boundary
  that calls `validate_identifier` (reusing its identifier-format rules
  unchanged) and, on failure, re-raises a sanitized `ValidationError` with
  error code `INVALID_IDENTIFIER` (TD §21.5's exact requirement for this
  command group; `validate_identifier`'s own `INVALID_EVENT` code is never
  allowed to reach operator-facing output for this command group). The
  replacement message references only the identifier name (`"client_id"` or
  `"audit_id"`), never the raw invalid value or any detail from the original
  exception; the original exception is chained via `from` for internal
  traceback visibility only. For place/release, rejects a
  missing-or-whitespace `--reason` via a dedicated `_require_non_empty_reason`
  check *before* any `RetentionService` method is called; generates `now`
  internally via `core.time.utc_now_iso()` — no `--now` CLI argument exists
  anywhere.
- **`main.py` composition:** constructs exactly one `HoldRepository`,
  `CustodySweepClient`, `MarkerStore`, `HoldTransitions` per invocation, wires
  them into exactly one `RetentionService`, and calls only
  `dispatch_retention_hold(args, service)` — `commands.py` never touches
  `HoldRepository` directly (verified structurally, see §6/§10).

## 6. Security / Authorization Implemented

- `RetentionService` remains the sole boundary between the CLI and
  hold-state storage for all three operations, including the read-only
  STATUS path (TD §21.2, ADR Invariant 32). `commands.py` constructs no AWS
  client and no repository/publisher of its own.
- `--reason` is required and non-empty for both PLACE and RELEASE, rejected
  before any `RetentionService` call; no synthetic/default reason is ever
  substituted.
- No `--now`/`--timestamp` CLI argument exists; the operator can never
  supply a hold-transition timestamp.
- Rendering exclusively reuses the existing `sanitize()` boundary — no
  parallel rendering path was introduced.
- `HoldOperationResult` structurally cannot carry `placed_by`, `released_by`,
  `reason`, `marker_s3_key`, `marker_confirmed_last_modified`,
  `s3_versions_retagged_count`, or `dynamodb_items_updated_count` — proven by
  a dataclass-field-set equality test, not merely a rendering-time scrub.

## 7. Error Handling Implemented

- `INVALID_IDENTIFIER` — corrected in a post-QA release-readiness pass. An
  invalid `client_id`/`audit_id` now surfaces as `INVALID_IDENTIFIER`
  (TD §21.5's exact requirement) through `commands.py`'s
  `_validate_hold_identifier` translation boundary, for all of
  `place`/`release`/`status`, in both text and JSON output, with no
  `RetentionService` method ever called for a request that fails identifier
  validation. `core/validators.py::validate_identifier` itself is unchanged
  and continues to raise `INVALID_EVENT` for every other caller in the
  codebase — only this command group's own boundary translates the code.
- `HOLD_NOT_ACTIVE`, `HOLD_MARKER_ESTABLISHMENT_FAILED`,
  `HOLD_MARKER_INTEGRITY_VIOLATION` each gained a dedicated,
  sanitization-safe `_error_next_step` branch (none existed before this
  subphase — confirmed by inspection before writing).
- `HOLD_ALREADY_ACTIVE` is not raised anywhere, not rendered, and has no
  `_error_next_step` branch — proven by a negative test comparing its
  guidance text to the generic fallback's.
- `HOLD_STATE_CONCURRENCY_EXCEEDED`'s existing branch (governing Category
  1/2 write paths) is untouched; a negative test proves it gained no
  retention-hold-specific wording.

## 8. Observability / Logging

No new logging was added or required by TD §21; this subphase does not
specify structured logging changes, and none of the touched files' existing
logging behavior was altered.

## 9. Assumptions Made

**Correction (post-QA release-readiness review):** this section previously
carried an "assumption requiring confirmation" characterizing this module's
inheritance of `INVALID_EVENT` (the codebase-wide `validate_identifier`
helper's own hardcoded error code) instead of TD §21.5's specified
`INVALID_IDENTIFIER` as an acceptable, precedented pattern mirroring
`audit_platform_integrity/commands.py`. Product Strategy's release-readiness
review correctly identified this as a genuine, blocking behavioral defect,
not an accepted pre-existing pattern: TD §21.5 is this command group's own
authoritative contract, and it explicitly requires `INVALID_IDENTIFIER`
specifically for `retention hold place|release|status`. That mirrored
precedent governs a different command (`certify audit`) with no documented
`INVALID_IDENTIFIER` requirement of its own, so it did not license silently
letting the wrong code leak through here. This has been corrected: see
§2/§5/§7 above for the `_validate_hold_identifier` translation boundary now
implemented, and §10 below for the added regression coverage and updated
validation evidence. `core/validators.py` itself remains unmodified — its
codebase-wide `INVALID_EVENT` behavior is correct, pre-existing, and
unchanged for every other caller.

Remaining item, reclassified (not an open assumption — see below), and one
assumption still requiring confirmation:

- `CommandResult.data`'s `"status"` key (the `HoldOperationResult` field,
  e.g. `"ACTIVE"`) overwrites `CommandResult`'s own `"status"` field
  (`"success"`) in the merged JSON payload produced by `render()`, because
  dict-literal construction spreads `**result.data` after the `"status"`
  key. **This is an explicit compatibility consequence already reviewed and
  accepted by Product Strategy for this subphase**, not an open assumption:
  TD §21 locks the domain field name as `status` on `HoldOperationResult`,
  and the existing CLI rendering pipeline already uses this identical
  flattened-`data` shape for `generate intelligence`/`generate report`/
  `certify audit`, whose `data` dicts also carry a domain-specific
  `"status"` value that collides with `CommandResult.status` the same way.
  This implementation follows that same established, accepted pattern
  rather than renaming the field — output schema is unchanged by this
  corrective pass.
- `--stage`/`--output` argument shape is not fully specified by TD §21.5
  beyond "required" for `--stage`. This implementation used
  `choices=("dev","staging","prod")` for `--stage` and
  `choices=("text","json")`/`default="text"` for `--output`, matching the
  majority CLI convention (`client`/`audit`/`config` groups) rather than
  `certify audit`'s `("json","human")` variant, since retention commands flow
  through the standard `render()`/`render_error()` dispatch which only
  special-cases the literal string `"json"`. (Separately confirmed accepted
  as proposed; no correction needed.)

## 10. Validation Performed

**Post-correction results (current, exact — reflects the `INVALID_IDENTIFIER`
translation boundary and its 18 new regression tests):**

Targeted suites:

```
uv run pytest -q tests/unit/evidence_retention/test_hold_transitions.py
19 passed

uv run pytest -q tests/unit/evidence_retention/test_retention_service.py
26 passed

uv run pytest -q tests/unit/test_operator_cli_result.py
38 passed

uv run pytest -q tests/unit/test_operator_cli_retention.py
39 passed
```

(`test_operator_cli_retention.py` grew from 21 to 39 tests — the 18 added
tests are enumerated in §2 above.) Combined targeted total: 19 + 26 + 38 +
39 = 122 passed.

Full suite:

```
uv run pytest -q
2207 passed, 2 skipped in 6.02s
```

(Previously 2189 passed — the 18-test increase matches exactly:
2189 + 18 = 2207.) The 2 skips are pre-existing and unrelated to this work
(`tests/unit/test_infra_configuration.py:115` and `:181` — serverless
packaging/CLI-toolchain environmental skips, confirmed unrelated by file
path and skip reason).

Ruff, both touched files:

```
uv run ruff check src/release_confidence_platform/evidence_retention/commands.py
All checks passed!

uv run ruff check tests/unit/test_operator_cli_retention.py
All checks passed!

uv run ruff format --check src/release_confidence_platform/evidence_retention/commands.py
1 file already formatted

uv run ruff format --check tests/unit/test_operator_cli_retention.py
1 file already formatted

git diff --check
(exit 0, no output)
```

Spot-checked every pre-existing test that imports `HoldTransitionOutcome` or
`RetentionService` by name outside the four authorized modified test files —
confirmed via `grep -rln` that no other production or test file imports or
calls either type; all other repository references are docstring/comment
mentions only (`hold_repository.py`, `custody_sweep_client.py`,
`marker_store.py`, `disposal_repository.py`).

## 11. Ruff Results

`ruff check` on every touched/new file: zero new findings. The seven
pre-existing findings in `operator_cli/main.py` (import-sort/line-length,
all in code untouched by this subphase — verified via `git stash` diff
against the pre-existing baseline before any edits) are unchanged by this
work.

`ruff format --check`: `commands.py` (new file) and three of the four
modified test files (`test_hold_transitions.py`,
`tests/unit/test_operator_cli_result.py`, and the new
`test_operator_cli_retention.py`) pass cleanly (reformatted in place where
the linter flagged the lines this subphase added). Three files —
`main.py`, `retention_service.py`, and `test_retention_service.py` — have
pre-existing format non-conformance in code this subphase did not touch:
confirmed via `git stash` diff against the pre-branch `main` baseline that
all three files fail `ruff format --check` identically on both the current
branch state and the pre-existing baseline; left unchanged per the "avoid
unrelated formatting churn" scope-control rule. No new format finding was
introduced by this subphase's own edits in any file.

## 12. Requirement Traceability (all 20 behavioral requirements)

1. `RetentionService` exclusive PLACE/RELEASE/STATUS boundary —
   `commands.py` constructs no repository/client of its own;
   `operator_cli/main.py`'s `retention` dispatch branch constructs exactly
   one `RetentionService` and calls only `dispatch_retention_hold(args,
   service)`.
2. CLI never calls `HoldRepository` methods directly — enforced by
   `test_commands_module_never_references_hold_repository_directly`
   (AST-based, `tests/unit/test_operator_cli_retention.py`).
3. `is_resumption` five branch assignments — `hold_transitions.py`'s five
   `HoldTransitionOutcome(...)` construction sites; regression-proven in
   `test_is_resumption_all_five_branch_assignments`
   (`test_hold_transitions.py`).
4. `HoldOperationResult` exact §21.4 field contract, no extra field —
   `retention_service.py`'s dataclass definition; structurally proven by
   `test_hold_operation_result_field_set_is_exactly_decision_2s_list`
   (`test_retention_service.py`).
5. PLACE/RELEASE return strongly consistent post-operation state via
   `_build_result` (`retention_service.py`); regression-proven by
   `test_place_legal_hold_establishes_marker_runs_sweep_and_reconciliation_then_completes`'s
   `outcome.sweep_status == "COMPLETE"` assertion.
6. STATUS uses `consistent_read=True`, zero mutation —
   `get_hold_status`/`_build_result` in `retention_service.py`; proven by
   `test_get_hold_status_uses_strongly_consistent_read`,
   `test_get_hold_status_performs_zero_mutation`,
   `test_get_hold_status_zero_mutation_for_never_held_case_too`.
7. RELEASE requires non-empty `--reason` (new CLI requirement) —
   `commands.py`'s `_require_non_empty_reason`, called before
   `release_legal_hold`; proven by
   `test_release_requires_non_empty_reason_before_any_service_call`.
8. PLACE retains required non-empty `--reason` — `commands.py`'s
   `place.add_argument("--reason", required=True, ...)` plus the same
   `_require_non_empty_reason` gate; proven by
   `test_place_requires_non_empty_reason_before_any_service_call`.
9. `now` generated internally via `core.time.utc_now_iso()`, no
   `--now`/`--timestamp` CLI argument — `commands.py`'s
   `dispatch_retention_hold`; proven by
   `test_place_calls_only_place_legal_hold_with_generated_timestamp` and
   `test_status_command_does_not_require_reason_or_actor_arguments`
   (absence of any timestamp-related argument on the parser).
10. Completed PLACE no-op: `disposition="no_op"`, zero mutation —
    unchanged `HoldTransitions.place()` no-op gate; `RetentionService`
    returns via `_build_result(..., disposition="no_op")`; proven by
    `test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e`.
11. Interrupted PLACE/RELEASE resumption returns `disposition="resumed"` —
    `place_legal_hold`/`release_legal_hold`'s
    `"resumed" if outcome.is_resumption else "completed"` derivation; proven
    by `test_resumed_place_after_marker_failed_reestablishes_marker` and
    `test_resume_after_sweep_interruption_reuses_marker_and_reaches_complete`.
12. Fresh transitions return `disposition="completed"`; precedence order
    (`is_noop` → `is_resumption` → default `"completed"`) — implemented
    exactly in `place_legal_hold`/`release_legal_hold`; proven by
    `test_place_legal_hold_establishes_marker_runs_sweep_and_reconciliation_then_completes`
    and `test_release_legal_hold_uses_inverse_sweep_methods_and_legal_hold_false`.
13. `HOLD_ALREADY_ACTIVE` not an operative error path — proven by
    `test_hold_already_active_is_not_a_recognized_error_code` and
    `test_hold_already_active_never_appears_in_commands_module`.
14. `HOLD_STATE_CONCURRENCY_EXCEEDED` not presented as reachable from these
    three commands, no new guidance added for it — proven by
    `test_hold_state_concurrency_exceeded_guidance_unchanged_no_retention_wording`;
    its existing branch in `result.py` is byte-for-byte unchanged.
15. Stale `HoldStateConcurrencyExceededError` docstring claims corrected —
    both `place_legal_hold`/`release_legal_hold` docstrings in
    `retention_service.py` rewritten to state the exception is not reachable
    from this path.
16. No unsubstantiated count fields — `HoldOperationResult` has no such
    field (structural); proven by
    `test_hold_operation_result_never_carries_fabricated_count_fields` and
    `test_main_place_json_output_has_no_fabricated_count_fields`.
17. Existing sanitization boundary reused, no parallel rendering path —
    `result.py`'s `render()`/`render_error()` unmodified except for the new
    field-rendering helper and three new guidance branches, both routed
    through the existing `sanitize()` call.
18. `_error_next_step` guidance added for `HOLD_NOT_ACTIVE`,
    `HOLD_MARKER_ESTABLISHMENT_FAILED`, `HOLD_MARKER_INTEGRITY_VIOLATION` —
    `result.py`; confirmed no branch existed before writing (direct
    inspection); proven by
    `test_error_next_step_hold_not_active`,
    `test_error_next_step_hold_marker_establishment_failed`,
    `test_error_next_step_hold_marker_integrity_violation`.
19. No `CustodyPeriodConfigLoader`/`custody_period_days` for these three
    commands — `RetentionService`/`HoldTransitions`/`CustodySweepClient`
    constructors are unchanged by this subphase (verified: no new parameter
    added to any of the three); `main.py`'s `retention` dispatch branch does
    not import or call `CustodyPeriodConfigLoader`.
20. No infrastructure/IAM/deployment/activation change — no file under
    `infra/`, no Lambda handler, `config/custody_periods.json`, or
    `disposal_repository.py` was touched (confirmed by `git status --short`
    below).

## 13. Known Limitations / Follow-Ups

None identified beyond the two assumptions flagged in §9, both of which are
pre-existing codebase conventions this subphase deliberately followed rather
than deviated from.

## 14. Commit Status

Not committed — implementation and self-verification only, per instructions.
QA is dispatched separately.

**Post-correction, exact, literal reconciliation** (after the
`INVALID_IDENTIFIER` translation-boundary corrective pass; the original
implementation and its QA sign-off preceded this and are otherwise
unchanged):

```
$ git status --short
 M src/release_confidence_platform/evidence_retention/hold_transitions.py
 M src/release_confidence_platform/evidence_retention/retention_service.py
 M src/release_confidence_platform/operator_cli/main.py
 M src/release_confidence_platform/operator_cli/result.py
 M tests/unit/evidence_retention/test_hold_transitions.py
 M tests/unit/evidence_retention/test_retention_service.py
 M tests/unit/test_operator_cli_result.py
?? AGENTS.md
?? docs/backend/a1_4b_operator_cli_retention_service_implementation_plan.md
?? docs/backend/a1_4b_operator_cli_retention_service_implementation_report.md
?? docs/qa/a1_4b_operator_cli_retention_service_test_plan.md
?? docs/qa/a1_4b_operator_cli_retention_service_test_report.md
?? src/release_confidence_platform/evidence_retention/commands.py
?? tests/unit/test_operator_cli_retention.py
```

`commands.py` and `test_operator_cli_retention.py` are new, untracked files
(no prior commit exists to diff against on this branch), so `git diff
--stat` reports nothing for them; the corrective change to each is
documented directly in §2 above (the `_validate_hold_identifier` boundary
in `commands.py`; the 18 added tests in `test_operator_cli_retention.py`,
which grew from 21 to 39 tests). The 7 pre-existing modified production/test
files are unchanged by this corrective pass — only `commands.py` and
`test_operator_cli_retention.py` were touched to resolve the
`INVALID_IDENTIFIER` defect, plus these four release-record docs.

`AGENTS.md` is the pre-existing, unrelated untracked file confirmed present
at branch creation (per the task briefing) — not created or modified by this
subphase. The four `docs/backend/`/`docs/qa/` files listed are this
subphase's own implementation/QA plan and report artifacts, all four updated
in this corrective pass with the exact counts and characterizations above.
