# Implementation Report

## 1. Summary of Changes

Implemented Subphase A1.3d.2: wired Phase 5 (Reliability Intelligence) to
A1.LH1 legal-hold coordination and custody-field computation. Both
`IntelligenceMetadata` write methods
(`put_intelligence_metadata_once`/`update_intelligence_metadata`) are now
hold-coordinated `TransactWriteItems` calls via the already-proven,
unmodified `HoldCoordinatedTransactionRunner`. `IntelligencePublisher.write_artifact`
gains a `ConsistentRead: true` hold-state read immediately before
`put_object` and writes `rcp-legal-hold`/`rcp-evidence-class` object tags.
`operator_cli/main.py`'s `generate intelligence` dispatch block resolves
`custody_period_days` exactly once via `CustodyPeriodConfigLoader`, before
any AWS-client construction, and constructs one `HoldRepository` shared by
the repository and publisher. `retrieve intelligence-*` and `--dry-run`
remain fully unaffected — both construct these classes with
`hold_repository`/`custody_period_days` at their `None` default.
`IntelligenceJob` (Category 3) is untouched. `engine.py` is byte-identical
to `main` (confirmed, Section 10).

## 2. Files Modified

Production (3, exactly the authorized scope):
- `src/release_confidence_platform/reliability_intelligence/repository.py`
  — constructor gains optional `hold_repository`/keyword-only
  `custody_period_days`; new `_governance_preflight`,
  `_parse_phase5_metadata_identity`, `_intelligence_governance_fields`;
  `put_intelligence_metadata_once`/`update_intelligence_metadata` rewritten
  as hold-coordinated transactions. 184 additions, 15 deletions, net +169.
- `src/release_confidence_platform/reliability_intelligence/publisher.py`
  — constructor gains optional `hold_repository`; new
  `_parse_intelligence_key_identity`, `_intelligence_tagging`;
  `write_artifact` rewritten with hold-state read and S3 tagging. 90
  additions, 3 deletions, net +87.
- `src/release_confidence_platform/operator_cli/main.py` — `generate
  intelligence` dispatch block only: custody-period resolution and
  three-mode construction (dry-run / write-capable). 40 additions, 4
  deletions, net +36.

Tests, modified (4):
- `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`
  — added `_assert_no_intelligence_job_governance_elements` helper and
  calls from the three existing scenario functions.
- `tests/unit/reliability_intelligence/test_engine_idempotency.py` — added
  3 dry-run write-free assertions.
- `tests/unit/reliability_intelligence/test_engine_gate.py` — added 3 new
  test functions (zero-metadata-writes restated explicitly, zero-artifact-writes,
  structural no-hold-coordination-reference proof).
- `tests/unit/test_reliability_intelligence_retrieval.py` — added a new
  `TestRetrieveIntelligenceCustodyConfigIndependence` class (2 tests × 3
  custody-config fixture variants = 6 parametrized cases) exercising the
  real `operator_cli.main.dispatch()`/`main()` path.

Tests, new (2):
- `tests/unit/reliability_intelligence/test_hold_coordination.py` (940
  lines, 60 tests) — the full contract matrix described in Section 3.
- `tests/unit/test_operator_cli_generate_intelligence.py` (402 lines, 19
  tests) — CLI dispatch ordering, injection, identity, and
  rendering/sanitization coverage.

Docs (4, this subphase):
- `docs/backend/a1_3d2_phase5_intelligence_hold_coordination_implementation_plan.md`
- `docs/backend/a1_3d2_phase5_intelligence_hold_coordination_implementation_report.md` (this file)
- `docs/qa/a1_3d2_phase5_intelligence_hold_coordination_test_plan.md`
- `docs/qa/a1_3d2_phase5_intelligence_hold_coordination_test_report.md` (skeleton, left for QA)

## 3. API Contract Implementation

No CLI argument, output shape, or exit-code contract change. Three
new-reachable, previously-unreachable failure reason codes on `rcp generate
intelligence` only: `CUSTODY_PERIOD_CONFIG_MISSING`,
`HOLD_COORDINATION_NOT_CONFIGURED`, `HOLD_STATE_CONCURRENCY_EXCEEDED`. All
route through the existing, unmodified `render()`/`render_error()`
sanitization boundary (`operator_cli/result.py`) — confirmed by
`test_operator_cli_generate_intelligence.py`'s rendering/sanitization
tests. `_error_next_step()` has no phase-specific branch for these codes
yet (falls through to the generic guidance) — a documented, temporary
operator-usability limitation per Technical Design Section 20.11, not a
safety gap (reason code, sanitization, and non-zero exit code are all
preserved regardless).

## 4. Data / Persistence Implementation

`IntelligenceMetadata` (DynamoDB): CREATE and regeneration both now
compute `custody_expires_at` (always) and `ttl_disposal_at` (present
unless an active hold is observed at that attempt's fresh hold-state
read) and a fixed `evidence_class = "intelligence"`, atomically verified
against `LegalHold.hold_version` via `TransactWriteItems`. CREATE
preserves its existing `attribute_not_exists(PK) AND
attribute_not_exists(SK)` condition; regeneration's Put remains
unconditioned (full-item replacement, force-regeneration semantics
preserved).

`intelligence/` S3 artifacts: gain `rcp-legal-hold`/`rcp-evidence-class`
object tags, computed from a `ConsistentRead: true` hold-state read
immediately before `put_object`.

`IntelligenceJob`: **no change** — confirmed via
`test_intelligence_job_writes_never_receive_hold_coordination` (zero
`transact_write_items` calls, zero legal-hold `get_item` reads, zero
governance elements in the persisted item, even with a fully
write-capable repository instance).

## 5. Key Logic Implemented

- **Write-entry governance preflight** (`_governance_preflight`): checks,
  in order, hold-repository presence → custody-duration presence →
  custody-duration validity (Boolean rejected before the `int` check,
  since `bool` is an `int` subclass). First action of both governed write
  methods.
- **`_parse_phase5_metadata_identity`**: parses `(client_id, audit_id)`
  from a trusted, internally-constructed item's PK/SK; raises
  `StorageError(..., "STORAGE_ERROR")` on shape mismatch (defensive —
  unreachable in correct operation since `_assert_phase5_sk` already ran).
- **`_intelligence_governance_fields`**: mirrors
  `aggregation/repository.py::_aggregate_governance_fields` exactly,
  `evidence_class` fixed to `"intelligence"`; uses `from datetime import
  UTC, datetime` at module level (exact import style required for
  clock-patching via `monkeypatch.setattr(repository_module, "datetime",
  ...)`).
- **No `sanitize()` call** on any item bound for DynamoDB persistence in
  either write method — the one deliberate, explicitly-required correction
  from Phase 4's textually-mirrored pattern (`STRUCTURAL_IDENTIFIER_KEYS`
  does not cover `PK`/`SK`).
- **Publisher**: `_parse_intelligence_key_identity` validates the 8-segment
  `intelligence/{client_id}/{audit_id}/.../artifact.json` shape;
  `_intelligence_tagging` computes the exact `rcp-legal-hold=true|false&rcp-evidence-class=intelligence`
  string via `urlencode`, preserving insertion order.
- **CLI**: custody-period resolution happens before `AwsClientFactory`
  construction (locked resolution sequence, Technical Design Section
  20.4); dry-run skips resolution entirely and constructs both classes
  with `None` governance dependencies, identical to the retrieval path.

## 6. Security / Authorization Implemented

Fail-closed governance preflight is the first executable action of every
governed write method — verified for all 8 invalid-dependency conditions
on both repository write methods, plus the publisher's
`HOLD_COORDINATION_NOT_CONFIGURED` fail-closed path. `ConsistentRead:
true` is used only for the S3-write-path hold read (no transactional
backstop exists on that leg); the DynamoDB write path's pre-transaction
read remains at default consistency (harmless staleness, per
`TransactWriteItems`' own re-verification at commit). All new reason codes
pass through the existing sanitization boundary with no raw
exception/AWS-request-ID/DynamoDB-key/S3-key/client_id/audit_id leakage
(verified with sentinel identifiers as actual CLI `--client`/`--audit`
arguments, since `render_error()`'s payload structurally excludes them —
`{command, stage, code, message}` only).

## 7. Error Handling Implemented

- `HOLD_COORDINATION_NOT_CONFIGURED` — missing `hold_repository`.
- `CUSTODY_PERIOD_CONFIG_MISSING` — missing or invalid `custody_period_days`
  (repository preflight; separately, `CustodyPeriodConfigLoader.resolve`'s
  own `ConfigError` at the CLI-resolution layer).
- `CONDITIONAL_WRITE_FAILED` (`ConditionalWriteError`) — CREATE's own
  condition failure, never masked behind a hold-version retry (proven even
  when the hold `ConditionCheck` also fails in the same attempt).
- `HOLD_STATE_CONCURRENCY_EXCEEDED` — bounded retry exhaustion (3
  attempts) on a sustained hold-version race.
- `STORAGE_ERROR` — a non-condition `ClientError` (e.g.
  `ValidationException`) on any attempt, immediately surfaced, never
  retried; also the publisher's hold-read failure mapping for a
  non-`StorageError` exception.
- `S3_WRITE_FAILED` — unchanged, existing `put_object` failure mapping.

No exception is silently swallowed; no internal stack trace or sensitive
detail is exposed to the CLI operator (Section 6).

## 8. Observability / Logging

No new logging added. `engine.py`'s existing structured-log events are
unaffected (byte-identical file). No governance-field value or hold state
is logged by the repository/publisher changes themselves — this mirrors
Phase 4's existing (silent, non-logging) governance-field computation.

## 9. Assumptions Made

- **Assumption**: the task brief's instruction to import
  `CustodyPeriodConfigLoader`/`HoldRepository` "at the top of main.py" is
  interpreted as "at the top of the `generate intelligence` dispatch
  block's relevant branch," consistent with this file's established,
  unbroken convention of lazy, per-command-scoped, `# noqa: PLC0415`-marked
  local imports (every other repository/publisher/engine/`AwsClientFactory`
  import in `dispatch()` follows this pattern). A module-level import would
  be the one stylistic outlier in the file and would change import-time
  behavior for every CLI invocation, not only `generate intelligence`.
  Does not affect external behavior, API contract, or Invariant 30's
  resolution-ordering requirement (verified: custody resolution still
  happens before `AwsClientFactory` construction).

Neither assumption affects external behavior, data shape, security,
billing, permissions, or API contracts.

## 10. Validation Performed

- `git diff main -- src/release_confidence_platform/reliability_intelligence/engine.py`
  — **zero output**, confirming byte-identical preservation.
- Scoped suite: `pytest tests/unit/reliability_intelligence/
  tests/unit/test_reliability_intelligence_retrieval.py
  tests/unit/test_operator_cli_generate_intelligence.py -q` — **158
  passed**, 0 failed, 0 skipped.
- Full suite: `pytest -q` — **1901 passed, 2 skipped** (same 2
  pre-existing, unrelated skips as the `main` baseline). Zero regressions.
- `ruff check` (lint): all changed/new files pass — `operator_cli/main.py`,
  `reliability_intelligence/repository.py`, `reliability_intelligence/publisher.py`,
  and all 6 test files (4 modified + 2 new) — except the 7 pre-existing
  findings in `operator_cli/main.py` (`I001`×4, `E501`×3). Those 7 findings
  are baseline-identical to `main` (confirmed via `git show main:<path> |
  ruff check -`, same codes, same relative locations) and were not
  introduced by A1.3d.2.
- `ruff format --check`: reports existing formatting drift in
  `operator_cli/main.py`, `reliability_intelligence/repository.py`,
  `tests/unit/reliability_intelligence/test_engine_gate.py`,
  `tests/unit/reliability_intelligence/test_engine_idempotency.py`, and
  `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`
  (5 files flagged). `reliability_intelligence/publisher.py`,
  `tests/unit/test_reliability_intelligence_retrieval.py`,
  `tests/unit/reliability_intelligence/test_hold_coordination.py`, and
  `tests/unit/test_operator_cli_generate_intelligence.py` are already
  formatted (4 files clean). Baseline comparison against each flagged
  file's `main`-branch version confirms the reported formatting hunks
  pre-exist on `main` and lie outside A1.3d.2's changed hunks (verified by
  cross-referencing each `ruff format --diff` hunk's line range against the
  actual `git diff main` hunk ranges for that file). A1.3d.2 introduces no
  new lint or formatting regression.
- `git status --short` / `git diff --stat main` — changed-file set is
  exactly the 13 authorized files (3 production + 4 modified tests + 2 new
  tests + 4 new docs). `config/custody_periods.json`, `infra/serverless.yml`,
  every Phase 6/7 file, and `AGENTS.md` show zero diff / remain untracked.
- No custody duration value was added anywhere (confirmed:
  `config/custody_periods.json` diff is empty).

## 11. Known Limitations / Follow-Ups

- `_error_next_step()` has no phase-specific guidance for the three new
  reason codes (falls through to the generic "correct the error and
  retry" hint) — deferred to A1.3d.4 per the locked Technical Design
  Section 20.11 sequencing; not a safety gap.
- Issue #118 (Phase 5-7 persistence partial-success and stale Job-state
  hardening) is explicitly out of this subphase's scope and was not
  touched, tested as passing, or otherwise addressed.
- Pre-existing `ruff format`/import-order drift in `main.py` and
  `repository.py` (present on `main` before this change, in code regions
  this subphase did not modify) was left as-is per scope-control
  discipline (no unrelated formatting churn).

## 12. Commit Status

Not committed. Per explicit instruction, all changes are left
uncommitted on branch
`feature/a1-3d2-phase5-intelligence-hold-coordination` for independent QA
review. No push, no PR.

## 13. Requirement-to-Test Traceability

| # | Requirement | Test function(s) |
|---|---|---|
| 1 | `IntelligenceJob` never carries governance elements (CREATE/force-regen/failed-retry) | `test_engine_no_phase4_mutation.py::test_no_phase4_writes_on_first_generation`, `::test_no_phase4_writes_on_force_regeneration`, `::test_no_phase4_writes_on_failed_retry` (via `_assert_no_intelligence_job_governance_elements`) |
| 2 | `IntelligenceJob` write methods never transact/read hold state, even write-capable | `test_hold_coordination.py::test_intelligence_job_writes_never_receive_hold_coordination` |
| 3 | Dry-run: zero repository writes | `test_engine_idempotency.py::test_dry_run_performs_zero_repository_writes` |
| 4 | Dry-run: zero publisher writes | `test_engine_idempotency.py::test_dry_run_performs_zero_publisher_writes` |
| 5 | Dry-run: zero writes even with existing COMPLETE metadata | `test_engine_idempotency.py::test_dry_run_with_existing_complete_metadata_performs_zero_writes` |
| 6 | Dry-run: zero `CustodyPeriodConfigLoader` calls, zero `HoldRepository` construction, `None`-governed construction | `test_operator_cli_generate_intelligence.py::test_dry_run_zero_custody_resolve_calls`, `::test_dry_run_zero_hold_repository_construction`, `::test_dry_run_repository_and_publisher_constructed_with_none_governance` |
| 7 | Dry-run: AWS clients still constructed for existing read-only query | `test_operator_cli_generate_intelligence.py::test_dry_run_still_constructs_aws_clients_for_existing_read_only_query` |
| 8 | Dry-run: output shape/exit code unaffected | `test_operator_cli_generate_intelligence.py::test_dry_run_output_shape_and_exit_code_unaffected` |
| 9 | Gate denial: zero `IntelligenceMetadata` writes (missing/incomplete) | `test_engine_gate.py::test_no_phase5_records_written_when_gate_fails_missing`, `::test_no_phase5_records_written_when_gate_fails_incomplete` |
| 10 | Gate denial: zero artifact writes | `test_engine_gate.py::test_zero_artifact_writes_when_gate_fails` |
| 11 | Gate-denial code path has no hold-coordination reference (structural) | `test_engine_gate.py::test_gate_denial_code_path_has_no_hold_coordination_reference` |
| 12 | `retrieve intelligence-*` succeeds under 3 custody-config variants, zero resolve calls, zero `HoldRepository` construction | `test_reliability_intelligence_retrieval.py::TestRetrieveIntelligenceCustodyConfigIndependence::test_retrieve_intelligence_status_succeeds_regardless_of_custody_config`, `::test_retrieve_intelligence_summary_succeeds_regardless_of_custody_config` (each ×3 parametrized variants) |
| 13 | Repository preflight matrix — 8 conditions × 2 write methods | `test_hold_coordination.py::test_put_intelligence_metadata_once_preflight_invalid_duration`, `::test_update_intelligence_metadata_preflight_invalid_duration` (×7 params each), `::test_put_intelligence_metadata_once_preflight_missing_hold_repository`, `::test_update_intelligence_metadata_preflight_missing_hold_repository` |
| 14 | Hold-before-duration precedence | `test_hold_coordination.py::test_put_intelligence_metadata_once_hold_before_duration_precedence`, `::test_update_intelligence_metadata_hold_before_duration_precedence` |
| 15 | No `CustodyPeriodConfigLoader` reference in repository.py | `test_hold_coordination.py::test_repository_source_never_references_custody_period_config_loader` |
| 16 | No `os.environ`/`os.getenv` reference in repository.py | `test_hold_coordination.py::test_repository_source_never_references_environment_variables` |
| 17 | CREATE unheld/active/released — `ttl_disposal_at`, `evidence_class`, condition preserved | `test_hold_coordination.py::test_create_unheld_includes_ttl_disposal_at_and_evidence_class`, `::test_create_active_hold_omits_ttl_disposal_at`, `::test_create_released_hold_includes_ttl_disposal_at`, `::test_create_preserves_existing_condition_expression` |
| 18 | Duplicate CREATE → `ConditionalWriteError`, not concurrency, zero retries | `test_hold_coordination.py::test_create_duplicate_key_governed_failure_wins_over_hold_check_failure` |
| 19 | Regeneration unheld/active/released — `ttl_disposal_at`, no condition on Put | `test_hold_coordination.py::test_regenerate_unheld_includes_ttl_disposal_at`, `::test_regenerate_active_hold_omits_ttl_disposal_at`, `::test_regenerate_released_hold_includes_ttl_disposal_at`, `::test_regenerate_put_has_no_condition_expression_and_succeeds_on_existing_key` |
| 20 | PLACE race (CREATE) | `test_hold_coordination.py::test_put_intelligence_metadata_once_no_hold_to_active_race_bounded_success` |
| 21 | RELEASE race (CREATE) | `test_hold_coordination.py::test_put_intelligence_metadata_once_active_to_released_race_bounded_success` |
| 22 | RELEASE race (regeneration) | `test_hold_coordination.py::test_update_intelligence_metadata_release_race_bounded_success` |
| 23 | Bounded retry exhaustion (CREATE, regeneration) | `test_hold_coordination.py::test_put_intelligence_metadata_once_hold_race_retry_exhaustion_fails_closed`, `::test_update_intelligence_metadata_hold_race_retry_exhaustion_fails_closed` |
| 24 | Deterministic clock | `test_hold_coordination.py::test_custody_expires_at_uses_deterministic_clock` |
| 25 | Byte-boundary: generic `ClientError` not retried, `StorageError` not concurrency | `test_hold_coordination.py::test_generic_client_error_on_create_raises_storage_error_not_retried`, `::test_generic_client_error_on_regeneration_raises_storage_error_not_retried` |
| 26 | Immutability (success + retry exhaustion, both write methods) | `test_hold_coordination.py::test_put_intelligence_metadata_once_does_not_mutate_caller_item_on_success`, `::test_update_intelligence_metadata_does_not_mutate_caller_item_on_success`, `::test_put_intelligence_metadata_once_does_not_mutate_caller_item_on_retry_exhaustion`, `::test_update_intelligence_metadata_does_not_mutate_caller_item_on_retry_exhaustion` |
| 27 | Sanitizer-safety (digit-sequence PK/SK survives byte-identical) | `test_hold_coordination.py::test_sanitize_never_reaches_persistence_path_for_phone_pattern_digit_sequences` |
| 28 | Publisher identity parsing (valid + 5 malformed variants) | `test_hold_coordination.py::test_parse_intelligence_key_identity_valid`, `::test_parse_intelligence_key_identity_malformed` (×5 params) |
| 29 | Publisher call-order + exact tagging per state | `test_hold_coordination.py::test_intelligence_tagging_exact_string_per_state`, `::test_write_artifact_call_order_and_tagging_per_state` |
| 30 | Publisher `StorageError` propagation / unexpected-exception mapping | `test_hold_coordination.py::test_write_artifact_storage_error_from_hold_read_propagates_unchanged`, `::test_write_artifact_unexpected_exception_maps_to_storage_error` |
| 31 | Publisher fail-closed when `hold_repository` is `None` | `test_hold_coordination.py::test_write_artifact_fails_closed_when_hold_repository_not_configured` |
| 32 | Publisher artifact immutability | `test_hold_coordination.py::test_write_artifact_does_not_mutate_caller_artifact` |
| 33 | Publisher static source check (no marker/reconciliation/sweep/disposal reference) | `test_hold_coordination.py::test_publisher_source_has_no_marker_reconciliation_sweep_disposal_references` |
| 34 | CLI: resolve exactly once | `test_operator_cli_generate_intelligence.py::test_generate_resolves_custody_period_exactly_once` |
| 35 | CLI: resolve before `AwsClientFactory` construction | `test_operator_cli_generate_intelligence.py::test_generate_resolves_custody_period_before_aws_client_factory_construction` |
| 36 | CLI: resolved integer injected into repository | `test_operator_cli_generate_intelligence.py::test_generate_injects_resolved_custody_period_into_repository` |
| 37 | CLI: same `HoldRepository` instance into both | `test_operator_cli_generate_intelligence.py::test_generate_injects_same_hold_repository_instance_into_both` |
| 38 | CLI: publisher receives no duration argument | `test_operator_cli_generate_intelligence.py::test_generate_publisher_receives_no_duration_argument` |
| 39 | CLI: resolution failure → zero AWS construction | `test_operator_cli_generate_intelligence.py::test_generate_custody_resolution_failure_zero_aws_construction` |
| 40 | CLI: rendering/sanitization for all 4 reason codes, both output formats | `test_operator_cli_generate_intelligence.py::test_error_rendering_preserves_code_nonzero_exit_and_leaks_nothing` (×8 params) |
| 41 | `engine.py` byte-identical to `main` | `git diff main -- .../engine.py` (Section 10); no dedicated test function needed for a file-diff assertion |
