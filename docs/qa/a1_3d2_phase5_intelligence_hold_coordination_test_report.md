# QA Test Report — A1.3d.2 Phase 5 Intelligence Hold Coordination

**Status: VALIDATED by independent QA.**

This report records an independent QA pass against
`docs/qa/a1_3d2_phase5_intelligence_hold_coordination_test_plan.md`, the
implementer's own implementation report
(`docs/backend/a1_3d2_phase5_intelligence_hold_coordination_implementation_report.md`),
and — as the authoritative source — `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
(Decisions 5/8/10/11, Invariants 27-31) and
`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
§20 (20.4-20.6, 20.9-20.12). Every claim in the implementation report was
independently re-derived from the literal code and from directly executed
test runs, not accepted on the report's word.

## 1. Scope Validated

Confirmed via `git status --short` and `git diff --stat main`:

- 7 modified files: `src/release_confidence_platform/operator_cli/main.py`,
  `src/release_confidence_platform/reliability_intelligence/publisher.py`,
  `src/release_confidence_platform/reliability_intelligence/repository.py`,
  `tests/unit/reliability_intelligence/test_engine_gate.py`,
  `tests/unit/reliability_intelligence/test_engine_idempotency.py`,
  `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`,
  `tests/unit/test_reliability_intelligence_retrieval.py`.
- 6 untracked new files: `tests/unit/reliability_intelligence/test_hold_coordination.py`,
  `tests/unit/test_operator_cli_generate_intelligence.py`, and the 4
  `docs/backend/a1_3d2_*`/`docs/qa/a1_3d2_*` documents.
- The authorized A1.3d.2 feature scope contains exactly 13 files. The
  working tree additionally contains the pre-existing untracked
  `AGENTS.md`, which is unrelated, excluded, and must not be staged or
  committed.
- Zero diff confirmed on all explicitly out-of-scope paths in one combined
  check: `config/custody_periods.json`, `infra/serverless.yml`,
  `infra/resources/s3.yml`, `deterministic_reporting/`,
  `audit_platform_integrity/`, `evidence_retention/` (0 lines of diff
  output).
- `git diff main -- .../reliability_intelligence/engine.py` produces **zero
  output** — byte-identical to `main`, independently confirmed.

**PASS.**

## 2. Test Execution Summary

Targeted suite (independently run):
```
uv run pytest tests/unit/reliability_intelligence/test_hold_coordination.py \
  tests/unit/test_operator_cli_generate_intelligence.py \
  tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py \
  tests/unit/reliability_intelligence/test_engine_idempotency.py \
  tests/unit/reliability_intelligence/test_engine_gate.py \
  tests/unit/test_reliability_intelligence_retrieval.py -v
```
Result: **158 passed, 0 failed, 0 skipped** — matches the implementation
report's claim exactly.

Full suite (independently run):
```
uv run pytest -q
```
Result: **1901 passed, 2 skipped** — matches the pre-dispatch baseline
exactly (1901 passed, 2 skipped). **Zero regressions.**

`ruff check` (lint) — 3 production files + 6 test files:
- `repository.py`, `publisher.py`: 0 errors.
- `main.py`: 7 errors, all `I001`/`E501`, confined to the `retrieve
  report-*`, `retrieve cert-*`, and `certify audit` dispatch blocks (none
  in the `generate intelligence` block this subphase touched).
- All 6 test files (4 modified + 2 new): 0 errors (`ruff check` reports
  "All checks passed!").

`ruff format --check`:
- `repository.py`, `main.py`: "Would reformat" — see Section 5 for
  independent pre-existing-baseline confirmation.
- Of the 4 modified test files, 3 would be reformatted:
  `test_engine_gate.py`, `test_engine_idempotency.py`,
  `test_engine_no_phase4_mutation.py` — see Section 5. The fourth,
  `test_reliability_intelligence_retrieval.py`, is formatted cleanly.
- 2 new test files (`test_hold_coordination.py`,
  `test_operator_cli_generate_intelligence.py`): clean, already formatted.

**PASS** (evidence detailed further in Section 5).

## 3. Coverage-Checklist Verification

Walking `test_plan.md` §3 item by item, each independently verified against
the literal code and by direct test execution (not the implementer's
narrative):

| Checklist item | Verified | Evidence |
|---|---|---|
| `IntelligenceJob` never carries governance elements (3 scenarios) | PASS | `test_engine_no_phase4_mutation.py::test_no_phase4_writes_on_first_generation/_force_regeneration/_failed_retry`, all passing; `_assert_no_intelligence_job_governance_elements` checks all 6 governance-element names |
| `put_intelligence_job_once`/`update_intelligence_job` zero-transaction/zero-hold-read, fully write-capable instance | PASS | `test_hold_coordination.py::test_intelligence_job_writes_never_receive_hold_coordination` — uses `_make_repo()` (hold_repository present, custody_period_days=90); asserts `client.transact_calls == []` and filters `get_item_calls` for `#LEGALHOLD`-suffixed SK, found none |
| Dry-run zero repo/publisher writes, with/without existing COMPLETE | PASS | `test_engine_idempotency.py::test_dry_run_performs_zero_repository_writes/_publisher_writes/_with_existing_complete_metadata_performs_zero_writes` |
| Dry-run zero loader calls, zero `HoldRepository`, None-governed construction, output shape unaffected | PASS | `test_operator_cli_generate_intelligence.py::test_dry_run_zero_custody_resolve_calls/_zero_hold_repository_construction/_repository_and_publisher_constructed_with_none_governance/_still_constructs_aws_clients_for_existing_read_only_query/_output_shape_and_exit_code_unaffected` |
| Gate denial: zero metadata writes, zero artifact writes, structural no-hold-reference | PASS | `test_engine_gate.py::test_no_phase5_records_written_when_gate_fails_missing/_incomplete`, `::test_zero_artifact_writes_when_gate_fails`, `::test_gate_denial_code_path_has_no_hold_coordination_reference` (source-slices the actual gate block and greps for 6 forbidden identifiers) |
| Retrieval succeeds under 3 custody-config shapes, zero resolve/construction | **PASS with a test-quality concern** — see Finding 1 below | `test_reliability_intelligence_retrieval.py::TestRetrieveIntelligenceCustodyConfigIndependence` (6 parametrized cases, all pass) |
| Repository preflight: 8 conditions × 2 write methods | PASS | `test_hold_coordination.py::test_put/update_intelligence_metadata_once_preflight_invalid_duration` (×7 params each) + `_preflight_missing_hold_repository` (×2) |
| Hold-before-duration precedence | PASS | `test_hold_coordination.py::test_put/update_intelligence_metadata_once_hold_before_duration_precedence` — both dependencies invalid simultaneously, `HOLD_COORDINATION_NOT_CONFIGURED` wins |
| Repository source: no `CustodyPeriodConfigLoader`, no env vars | PASS | `test_hold_coordination.py::test_repository_source_never_references_*` (2 tests) + independently confirmed by direct read of `repository.py`'s imports (no such references exist) |
| Publisher source: no marker/reconciliation/sweep/disposal reference | PASS | `test_hold_coordination.py::test_publisher_source_has_no_marker_reconciliation_sweep_disposal_references` |
| CREATE unheld/active/released, condition preserved | PASS | `test_hold_coordination.py::test_create_unheld_*/_active_hold_*/_released_hold_*/_preserves_existing_condition_expression` |
| Duplicate CREATE → `ConditionalWriteError`, zero retries, wins over hold failure | PASS | `test_hold_coordination.py::test_create_duplicate_key_governed_failure_wins_over_hold_check_failure` — asserts `len(client.transact_calls) == 1` |
| Regeneration unheld/active/released, no condition on Put | PASS | `test_hold_coordination.py::test_regenerate_unheld_*/_active_hold_*/_released_hold_*/_put_has_no_condition_expression_and_succeeds_on_existing_key` |
| PLACE/RELEASE races (CREATE + regen) | PASS | `test_hold_coordination.py::test_put_intelligence_metadata_once_no_hold_to_active_race_bounded_success`, `::_active_to_released_race_bounded_success`, `::test_update_intelligence_metadata_release_race_bounded_success` |
| Bounded retry exhaustion, both methods | PASS | `test_hold_coordination.py::test_put/update_intelligence_metadata_once_hold_race_retry_exhaustion_fails_closed` — 3 forced failures, `HoldStateConcurrencyExceededError`, `error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"` |
| Deterministic clock | PASS | `test_hold_coordination.py::test_custody_expires_at_uses_deterministic_clock` — monkeypatches `repository_module.datetime`, asserts exact epoch value |
| Generic `ClientError` not retried, not treated as concurrency | PASS | `test_hold_coordination.py::test_generic_client_error_on_create/_regeneration_raises_storage_error_not_retried` — `ValidationException`-style error, `len(transact_calls) == 1` |
| Immutability (success + retry exhaustion, both methods) | PASS | 4 dedicated tests, `copy.deepcopy` comparison before/after |
| Caller-supplied governance-field override | PASS | `test_put/update_intelligence_metadata_once_does_not_mutate_caller_item_on_success` embeds stale `custody_expires_at=1`/`ttl_disposal_at=2`/`evidence_class="not_intelligence"` in the caller item and confirms the persisted values differ — proves governance fields are merged last and win |
| Sanitizer-safety regression (digit-sequence PK/SK/identifier) | PASS | `test_sanitize_never_reaches_persistence_path_for_phone_pattern_digit_sequences` — embeds `2475004829` in audit_id and `some_identifier`, confirms byte-identical persistence on both write methods |
| Publisher identity parsing (valid + 5 malformed) | PASS | `test_parse_intelligence_key_identity_valid` + `::_malformed` ×5 (wrong prefix, missing segment, wrong suffix, empty client_id, empty audit_id) |
| Publisher call-order + exact tagging per state | PASS | `test_write_artifact_call_order_and_tagging_per_state` — explicit `order` list proves `get_legal_hold(consistent_read=True)` precedes `put_object`, exact `Tagging` string asserted for unheld/active/released |
| Publisher `StorageError` propagation, zero `put_object` | PASS | `test_write_artifact_storage_error_from_hold_read_propagates_unchanged` — `s3.calls == []` |
| Publisher unexpected-exception → `STORAGE_ERROR` | PASS | `test_write_artifact_unexpected_exception_maps_to_storage_error` |
| Publisher fail-closed, `hold_repository=None` | PASS | `test_write_artifact_fails_closed_when_hold_repository_not_configured` |
| Publisher artifact immutability | PASS | `test_write_artifact_does_not_mutate_caller_artifact` |
| CLI: resolve exactly once, before `AwsClientFactory` | PASS | `test_generate_resolves_custody_period_exactly_once`, `::_before_aws_client_factory_construction` (explicit `_CALL_ORDER` index comparison) |
| CLI: resolved integer → repository; same `HoldRepository` object (identity) shared | PASS | `test_generate_injects_resolved_custody_period_into_repository`, `::_injects_same_hold_repository_instance_into_both` (uses `is`, not `==`) |
| CLI: publisher receives no duration | PASS | `test_generate_publisher_receives_no_duration_argument` |
| CLI: resolution failure → zero AWS construction | PASS | `test_generate_custody_resolution_failure_zero_aws_construction` — `_FakeAwsClientFactory.instances == []`, `_HOLD_REPOSITORY_INIT_CALLS == []` |
| CLI: rendering/sanitization, 4 codes × 2 formats, no leakage | PASS | `test_error_rendering_preserves_code_nonzero_exit_and_leaks_nothing` — 8 parametrized cases; leak probes include sentinel client/audit IDs, AWS request ID, DynamoDB key, S3 key — none found in output |

**Overall: PASS**, with one test-quality finding (non-blocking) recorded below.

## 4. Independent Findings

### Finding 1 — Decorative parametrization in the retrieval-independence test (test-quality, non-blocking)

**File:** `tests/unit/test_reliability_intelligence_retrieval.py`, lines
782-793 (`_CUSTODY_FIXTURE_VARIANTS`), 914-956 and 958-989
(`test_retrieve_intelligence_status_succeeds_regardless_of_custody_config`,
`test_retrieve_intelligence_summary_succeeds_regardless_of_custody_config`).

The three fixture dicts are genuinely distinct in shape (empty class,
class present with only an unrelated stage, class key entirely absent),
satisfying the letter of the QA dispatch's "must be genuinely distinct, not
three copies of the same fixture" requirement. However, each test
immediately does `del custody_config` and never wires the fixture's content
into `config/custody_periods.json`, the fake `CustodyPeriodConfigLoader`,
or any other part of the exercised code path. `_FakeCustodyPeriodConfigLoaderMustNotBeCalled`
raises `AssertionError` unconditionally on any `resolve()` call, regardless
of `custody_config`'s content — so all 6 parametrized cases execute an
identical code path and would pass or fail identically regardless of what
`_CUSTODY_FIXTURE_VARIANTS` contained. The parametrization is decorative:
it does not verify "succeeds regardless of custody-config shape" in any way
beyond what a single unparametrized case would already prove (that
`retrieve intelligence-*` never calls the loader at all, which is
independently and correctly proven).

This is not a correctness defect — the underlying claim (`retrieve
intelligence-*` is independent of `intelligence`'s custody configuration)
is true and is proven, just not by the mechanism the test's own docstring
and parametrization implies. It does not block sign-off but should be
routed back to the implementing agent as a test-quality cleanup: either
wire the fixture into a real `config/custody_periods.json`-shaped read path
(if one is later introduced) or collapse the parametrization and say
plainly that retrieval never reads this file's content in any shape.

**Classification:** Test Bug (assertion/test-design gap, not an application
defect). **Severity:** Low — no false confidence about production
behavior, only about *why* that behavior holds.

**Resolution:** Routed back to the implementing agent and fixed on this same
branch, same file, prior to release-readiness packaging.
`_FakeCustodyPeriodConfigLoaderMustNotBeCalled` was removed;
`_apply_patches` now writes each `custody_config` fixture variant to a real,
temporary `config/custody_periods.json` (via `tmp_path`), monkeypatches
`CustodyPeriodConfigLoader._default_root` to resolve there, and wraps the
*real* `CustodyPeriodConfigLoader.resolve` with a call-recording spy
(mirroring the existing `HoldRepository.__init__` spy already in this
class) rather than replacing the class with a raising stub. The three
fixture variants are now genuinely, independently exercised — a future
regression that added a `resolve()` call to the retrieve path would run the
real loader against each on-disk shape, including raising `ConfigError` for
the absent-key/absent-stage variants, rather than silently passing.
Independently re-verified: `tests/unit/test_reliability_intelligence_retrieval.py`
51 passed; full suite 1901 passed, 2 skipped (unchanged); `ruff check`/`ruff
format --check` clean on this file; changed-file scope unchanged (same 13
files, no new file added). **Finding 1 is now closed.**

### No other independent findings.

All other items in the QA dispatch's verification checklist were confirmed
directly against the code:

- `put_intelligence_metadata_once`/`update_intelligence_metadata` use
  `dict(item)` shallow copies (`repository.py:365`, `:428`) — no
  `sanitize()` call anywhere on a persistence-bound item; confirmed by
  reading the full file, not merely grepping.
- Preflight order in `_governance_preflight` (`repository.py:144-169`) is
  hold-repository presence → duration presence → Boolean-before-int
  validity, and it is the literal first statement of both governed write
  methods (`repository.py:362`, `:425`), before `_assert_phase5_sk`,
  identity parsing, or any hold read.
- Exact exception contract confirmed byte-for-byte against
  `repository.py:153-169`: `StorageError("Hold coordination is not
  configured", "HOLD_COORDINATION_NOT_CONFIGURED")`;
  `StorageError("Custody period configuration was not provided to this
  repository instance", "CUSTODY_PERIOD_CONFIG_MISSING")`;
  `StorageError("Custody period configuration is invalid",
  "CUSTODY_PERIOD_CONFIG_MISSING")`. `grep -rn HOLD_STATE_UNRESOLVABLE`
  across `publisher.py`/`repository.py` (and the whole `src/` tree)
  returned zero matches.
- CREATE contract (`repository.py:340-399`): governed `Put` retains
  `ConditionExpression="attribute_not_exists(PK) AND
  attribute_not_exists(SK)"`; `on_governed_condition_failed` raises the
  existing `ConditionalWriteError`; `build_transact_items` recomputes
  `_intelligence_governance_fields(hold_state, ...)` fresh from the
  `hold_state` parameter on every call (the closure captures no stale
  state).
- Regeneration contract (`repository.py:401-450`): governed `Put` has no
  `ConditionExpression`; no `on_governed_condition_failed` callback passed
  to `runner.run(...)`.
- Governance fields: `custody_expires_at` computed from
  `datetime.now(UTC)` inside `_intelligence_governance_fields` on every
  call (not cached); `ttl_disposal_at` via the imported (not reimplemented)
  `compute_ttl_disposal_at`; `evidence_class` hardcoded `"intelligence"`;
  merge order `{**base_item, **_intelligence_governance_fields(...)}` —
  governance fields spread last, confirmed to override caller-supplied
  same-named keys by direct test evidence (Section 3 above).
- Publisher (`publisher.py:90-140`): constructor gains optional
  `hold_repository: HoldRepository | None = None` only; `write_artifact`
  performs the fail-closed check, then `_parse_intelligence_key_identity`,
  then `get_legal_hold(client_id, audit_id, consistent_read=True)`, then
  `_intelligence_tagging`, then `put_object(..., Tagging=tagging)`; a
  `StorageError` from the hold read is re-raised unchanged (`except
  StorageError: raise`); any other exception is wrapped as
  `StorageError(..., "STORAGE_ERROR")`; both paths confirmed to make zero
  `put_object` calls by direct test evidence.
- CLI (`main.py:328-374`): `generate intelligence`'s non-dry-run branch
  resolves `CustodyPeriodConfigLoader().resolve("intelligence", args.stage)`
  strictly before `factory = AwsClientFactory(stage_config)`; constructs
  exactly one `HoldRepository`, shared by identity between
  `IntelligenceRepository` and `IntelligencePublisher`; the dry-run branch
  and the separate `retrieve intelligence-*` branch (`main.py:212-241`)
  contain no reference to `CustodyPeriodConfigLoader` or `HoldRepository`
  construction.
- `put_intelligence_job_once`/`update_intelligence_job`: `git diff main --
  repository.py` shows these two methods entirely outside every changed
  hunk — zero textual modification, confirmed by inspecting the diff's 4
  hunk headers directly (none overlap these methods' line ranges).
- `engine.py`: `git diff main -- .../engine.py` produces literally zero
  output.

## 5. Regression Evidence

- Full suite: **1901 passed, 2 skipped**, run directly by QA — identical to
  the documented pre-dispatch baseline. Zero regressions.
- `engine.py` diff: zero output, independently run.
- `ruff check` on `main.py`: 7 errors (`I001`×3, `E501`×3, one more `I001`
  — 7 total), all inside the `retrieve report-*`/`retrieve
  cert-*`/`certify audit` blocks, none inside `generate intelligence`.
  Independently compared against `git show main:.../main.py | ruff check
  -`: **identical 7 errors, identical rule codes, identical relative
  locations** (line numbers shift only because of this subphase's net
  insertions above them) — confirms these are pre-existing, not introduced.
- `ruff format --check` flagged `repository.py` and `main.py` as needing
  reformatting. Independently re-ran `ruff format --check` against the
  `main`-branch versions of both files: **both also fail identically on
  `main`** (exit code 1 in both cases). For `repository.py` specifically,
  `ruff format --diff` was inspected line-by-line: every flagged hunk
  (`intelligence_job_keys`, `intelligence_metadata_keys`'s SK
  f-string, `update_intelligence_job`, and the `_call` exception-mapping
  block) falls in code this subphase's diff hunks do not touch — confirmed
  by cross-referencing the 4 diff hunk line ranges against the format-diff
  hunk line ranges. This is pre-existing formatting drift, not introduced
  by this subphase.
- Three modified test files are reported by `ruff format --check`:
  `test_engine_gate.py`, `test_engine_idempotency.py`, and
  `test_engine_no_phase4_mutation.py`. `test_reliability_intelligence_retrieval.py`
  is formatted cleanly. Baseline comparison confirms the reported drift
  pre-exists on `main` and lies outside the A1.3d.2 changed hunks: each of
  the three flagged files also fails `ruff format --check` identically on
  its `main`-branch baseline (independently confirmed, exit code 1 in all
  three cases). Spot-checked the two files with the most format-diff hunks
  (`test_engine_no_phase4_mutation.py`, `test_engine_idempotency.py`)
  line-by-line: every flagged hunk falls in pre-existing test
  bodies/fixtures this subphase did not touch (e.g. the module-docstring
  blank-line convention, pre-existing multi-line `assert` statements,
  pre-existing dict literals) — none fall inside the newly added
  dry-run/governance-assertion test code. No new format issue was
  introduced by this subphase's additions.
- `ruff check` (lint, not format) is **fully clean** on all 6 test files
  (4 modified + 2 new) — "All checks passed!", confirming the two lint
  fixes made immediately before QA dispatch (the quoted-annotation issue in
  `test_engine_no_phase4_mutation.py` and the over-length line in
  `test_engine_idempotency.py`) are in fact clean now, and no other lint
  issue exists in any of the 6 test files.
- Changed-file-set: exactly the 13 authorized files (Section 1).
- `config/custody_periods.json`: zero diff, confirmed as part of the
  combined excluded-paths check.

**Documentation-accuracy note (resolved):** the implementation report
originally stated "58 tests" in `test_hold_coordination.py`; independent
collection (`pytest --collect-only -q`) counted **60**. This was corrected
in the implementation report to read 60. Never affected pass/fail outcome
or coverage — all 60 collected tests pass.

## 6. QA Sign-Off

**[QA SIGN-OFF APPROVED]**

Rationale: every critical correctness property in the QA dispatch (§1-9 of
the dispatch brief) was independently re-derived from the literal code and
confirmed, not merely accepted from the implementation report. The targeted
suite (158 tests) and full suite (1901 passed, 2 skipped) both pass with
zero regressions, independently executed. Scope is exactly the 13
authorized files with zero diff on every explicitly excluded path.
`engine.py` is confirmed byte-identical. All `ruff check` lint errors are
either zero (new files, `repository.py`, `publisher.py`) or independently
confirmed identical to the pre-existing `main`-branch baseline
(`main.py`'s 7 errors). All `ruff format --check` findings are
independently confirmed pre-existing on `main` and confined to code this
subphase did not touch.

One test-quality finding was recorded (Finding 1, Section 4): the original
three-fixture parametrization in `test_reliability_intelligence_retrieval.py`'s
`TestRetrieveIntelligenceCustodyConfigIndependence` class was decorative —
it proved the correct underlying claim, but not via the mechanism its own
naming/docstring implied. This was routed back to the implementing agent,
corrected, and independently reverified (Section 4). **Finding 1 is closed
and requires no remaining action.** It never affected the correctness of
the shipped behavior and was never a blocking defect.
