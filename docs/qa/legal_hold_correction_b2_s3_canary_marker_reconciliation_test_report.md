# Test Report

## A1.LH2 — S3 Canary-Marker and Symmetric Reconciliation Foundation

*Formerly identified in the corrective architecture sequence as "Legal-Hold
Correction B2."*

## 1. Execution Summary

Independent validation performed directly against the working tree on
`feature/a1-lh2-s3-marker-reconciliation` (uncommitted changes). No code was
modified as part of this validation.

- Focused suite (`uv run pytest tests/unit/evidence_retention/ -v`): **216
  passed, 0 failed**.
- Full canonical suite (`uv run pytest -q`): **1664 passed, 2 skipped**
  (skips confirmed pre-existing, Serverless-CLI-dependent, unrelated to this
  subphase).
- `uv run pytest tests/unit/test_infra_configuration.py -v`: **21 passed, 2
  skipped** (same pre-existing skips).
- `uv run ruff check src/release_confidence_platform/evidence_retention/
  tests/unit/evidence_retention/ tests/unit/test_infra_configuration.py`:
  **All checks passed.**
- `cd infra && sls print --stage dev`: fails with 9 "Value not found at
  self source" errors — the same 8 for the four pre-existing evidence-class
  rules (`Days` + `NoncurrentDays` each) plus a 9th for the new
  `retention-marker-disposal` rule's `Days` (no `NoncurrentVersionExpiration`
  on this rule, correctly, since it carries no versioned-object-specific
  clock). Confirms fail-closed, not a syntax error.

No test was skipped, disabled, or worked around to reach these numbers.

## 2. Detailed Results — Requirement-to-Test Mapping

| # | Required behavior | Verdict | Test file :: function |
| --- | --- | --- | --- |
| 1 | Atomic first marker creation (`IfNoneMatch="*"`, never check-then-write) | PASS | `test_marker_store.py::test_establish_marker_atomic_first_write_uses_if_none_match_star`; `::test_establish_marker_never_calls_head_object_then_put_object_check_then_write` (asserts the very first S3 call is `put_object`, never preceded by `head_object`) |
| 2 | Idempotent replay with identical content | PASS | `test_marker_store.py::test_establish_marker_reuses_existing_matching_marker_on_precondition_failure`; `::test_establish_marker_two_overlapping_attempts_neither_overwrites_the_other` |
| 3 | Rejection of conflicting existing content | PASS | `test_marker_store.py::test_establish_marker_raises_integrity_error_on_mismatched_existing_content` (raises `MarkerIntegrityError`); `::test_establish_marker_integrity_error_is_not_retried` (confirms exactly one `put_object` attempt, no retry-masking) |
| 4 | PLACE/RELEASE marker non-collision, same episode | PASS | `test_marker_store.py::test_place_and_release_markers_of_same_episode_do_not_collide`; also `test_retention_service.py::test_full_episode_place_release_place_three_distinct_markers_no_aliasing` (full-orchestration level) |
| 5 | PLACE → RELEASE → PLACE episodes, no aliasing | PASS | `test_marker_store.py::test_place_release_place_three_generations_no_aliasing`; `test_retention_service.py::test_full_episode_place_release_place_three_distinct_markers_no_aliasing` |
| 6 | Authoritative `LastModified` via dedicated `HeadObject`, never `PutObject`'s own response | PASS | `test_marker_store.py::test_establish_marker_reads_back_last_modified_via_head_object_never_trusting_put_response` — asserts exactly one `head_object` call and that the returned key's `LastModified` (not any `PutObject`-response field, since the fake `put_object` returns `{}`) is what's captured |
| 7 | Marker establishment timeout/failure — deterministic error, never silent proceed | PASS | `test_marker_store.py::test_establish_marker_raises_on_put_object_retry_exhaustion`, `::test_establish_marker_raises_on_head_object_retry_exhaustion`, `::test_establish_marker_fails_closed_on_wall_clock_budget_even_with_attempts_remaining`, `::test_establish_marker_wall_clock_budget_shared_across_put_and_head_phases` |
| 8 | Marker status confirmation/failure persisted via `HoldRepository` | PASS | `test_hold_repository.py::test_update_hold_event_marker_fields_calls_update_item`, `::test_update_hold_event_marker_fields_supports_failed_state_with_none_values`, `::test_update_hold_event_marker_fields_does_not_touch_write_once_fields`; `test_retention_service.py::test_marker_confirmed_persists_key_status_and_last_modified_on_event_and_hold`, `::test_place_legal_hold_marker_establishment_failure_sets_failed_states_and_propagates` |
| 9 | Stale re-invocation after marker disposal — no-op through the FULL orchestration (never reaching marker store or `CustodySweepClient`) | PASS | `test_retention_service.py::test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e` — asserts `fake_marker_store.calls`/`fake_sweep.calls` counts are unchanged after the stale re-invocation, at the `RetentionService` layer, not merely `HoldTransitions` |
| 10 | PLACE reconciliation racing object creation | PASS | `test_custody_sweep_client.py::test_reconcile_versions_place_retags_in_window_version_not_yet_true`, `::test_reconcile_versions_place_skips_version_already_tagged_true` |
| 11 | RELEASE reconciliation racing object creation (independent coverage) | PASS | `test_custody_sweep_client.py::test_reconcile_versions_release_retags_in_window_version_still_true`, `::test_reconcile_versions_release_skips_version_already_false` — a distinct test using the inverse filter direction, not inferred from the PLACE tests |
| 12 | Clock-boundary and defense-in-depth buffer behavior | PASS | `test_custody_sweep_client.py::test_reconcile_versions_just_inside_buffer_window_is_included`, `::test_reconcile_versions_just_outside_buffer_window_is_excluded`, `::test_reconcile_versions_skips_version_outside_buffer_window` |
| 13 | Pagination and version handling in reconciliation pass | PASS | `test_custody_sweep_client.py::test_list_object_versions_with_last_modified_yields_triples_and_paginates` (confirms `NextKeyMarker`/`NextVersionIdMarker` propagate to the next page's kwargs), `::test_list_object_versions_with_last_modified_skips_delete_markers` |
| 14 | Sweep interruption and retry (partial failure, safe resumption) | PASS | `test_retention_service.py::test_sweep_failure_after_marker_confirmed_leaves_sweep_status_in_progress`, `::test_resume_after_sweep_interruption_reuses_marker_and_reaches_complete` (confirms resumption does not re-invoke the marker store) |
| 15 | Terminal no-op at the FULL `RetentionService` orchestration layer (distinct check from #9, per task's own framing) | PASS | `test_retention_service.py::test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e`, `::test_release_legal_hold_reinvocation_after_complete_raises_and_never_touches_marker_or_sweep` |
| 16 | Preservation of `CustodySweepClient`'s method allowlists | PASS | `test_custody_sweep_client.py::test_allowed_s3_methods_unchanged_by_reconciliation_addition` (byte-for-byte frozenset equality check), `::test_custody_sweep_client_still_has_no_put_object_or_head_object_method`, `::test_call_s3_still_rejects_put_object_and_head_object`; independently confirmed by `git diff` showing no change to the `_ALLOWED_S3_METHODS`/`_ALLOWED_DYNAMODB_METHODS` definition lines |
| 17 | Absence of unconditioned marker overwrite | PASS | `test_marker_store.py::test_establish_marker_never_attempts_unconditioned_overwrite` — asserts every `put_object` call observed, including ones following a precondition conflict, carries `IfNoneMatch="*"`; reinforced structurally: `_attempt_put_or_reuse` has exactly one `put_object` call site in the entire module, and it is hardcoded with `IfNoneMatch="*"` (`marker_store.py` lines 451-459) |

## 3. Additional Verification Performed

**Marker identity/payload worked example.** Traced `build_marker_key`/
`build_marker_content` directly against Technical Design §19.5.1's worked
example (`client_abc`/`audit_xyz`/`hold_4f5a`, `hold_version` 1→2,
`PLACE`→`RELEASE`). Produces:

```
retention-markers/client_abc/audit_xyz/hold_4f5a/1-PLACE.marker
retention-markers/client_abc/audit_xyz/hold_4f5a/2-RELEASE.marker
```

Matches both the ADR/Technical Design's own worked example and the
implementation report's claimed worked example exactly, and is pinned by
`test_build_marker_key_matches_technical_design_worked_example`. The report's
`transition_id` field (`hold_id#hold_version#transition`) is a documented,
disclosed naming deviation from the Technical Design's own `action` field
name — semantically identical, explicitly flagged in the module docstring,
not a silent deviation.

**`RetentionService` is a real orchestrator, not a test double.**
Confirmed by direct code read of `retention_service.py`: it contains genuine
sequencing logic (marker-confirmation-then-sweep-then-reconciliation
ordering, `sweep_status` state transitions, failure-path branching between
`MarkerEstablishmentFailedError`/`MarkerIntegrityError` propagation and
sweep-phase exceptions) and calls the real `HoldTransitions` class
(A1.LH1, unmodified) rather than reimplementing or faking its logic.
`test_retention_service.py` fakes only `HoldRepository`/`MarkerStore`/
`CustodySweepClient` — its direct collaborators, each independently and
fully covered by their own dedicated test files — while using a real
`HoldTransitions` instance throughout. This satisfies Product Strategy's
explicit requirement (cited in the module's own docstring) that the
orchestrator not be a test double standing in for production logic.

**`_ALLOWED_S3_METHODS` byte-for-byte unchanged.** Confirmed by two
independent means: (1) `git diff HEAD -- .../custody_sweep_client.py` shows
no change to the line defining `_ALLOWED_S3_METHODS`; (2) direct read of the
current value: `frozenset({"list_object_versions", "get_object_tagging",
"put_object_tagging"})` — no `put_object`/`head_object`/`get_object` added,
and `test_call_s3_still_rejects_put_object_and_head_object` proves this at
runtime, not just by grep.

**Infra Lifecycle rule.** Confirmed directly: the new
`retention-marker-disposal` rule in `infra/resources/s3.yml` has (a) no
`Tag`/`And` filter — only `Filter.Prefix: retention-markers/`, (b) no
hardcoded `Days` — sourced from
`${self:custom.custodyPeriodDays.retention_marker.${self:provider.stage}}`,
left as an empty mapping in `infra/serverless.yml` for every stage. Ran
`cd infra && sls print --stage dev` directly (not accepted from the report):
produced 9 "Value not found at self source" errors, one per `Days`/
`NoncurrentDays` reference across all 5 rules (8 for the 4 pre-existing
rules, 1 for the new rule's `Days` — it has no `NoncurrentVersionExpiration`,
correctly, since a marker object is never itself subject to legal hold or
versioned-noncurrent-expiration semantics). Same error class/message shape
as the four pre-existing rules — proves fail-closed behavior, not a
CloudFormation/YAML syntax defect.

**`tests/unit/test_infra_configuration.py` updated tests.**
`test_s3_lifecycle_configuration_has_one_tag_filtered_rule_per_evidence_class`
now scopes its assertion to rules carrying an `And` filter (4 rules) rather
than all rules — confirmed this preserves every assertion it made before
(rule count, `Status`, tag value, prefix set, `Days`/`NoncurrentDays`
presence) for exactly the 4 tag-filtered rules, not weakened. The new
`test_s3_lifecycle_configuration_has_untagged_retention_marker_rule` asserts
(a) exactly one marker rule exists, (b) `Status == "Enabled"`, (c) `"And"
not in Filter` (the structurally distinct, no-tag-filter property), (d)
`Expiration.Days` present and equal to the exact expected variable-reference
string — a genuine, meaningful assertion, not a rubber stamp (it would fail
if the rule were tag-filtered, hardcoded, or missing).
`test_custody_period_days_config_defines_no_value_for_any_stage` was
extended to include `retention_marker` in its expected-keys set, preserving
its no-fallback-value assertion for all five keys including the new one.

**No IAM change.** `git diff HEAD -- infra/serverless.yml` shows only the
addition of `retention_marker: {}` under `custom.custodyPeriodDays`; the
`provider.iam.role.statements` block is untouched (confirmed by direct read
of the current file — unchanged from before this subphase per the diff).

**No CLI/API/production write-path change.** `grep -rn "RetentionService|
MarkerStore" src/` shows references only within
`evidence_retention/{marker_store,retention_service}.py` themselves and
docstring/comment mentions in already-existing `evidence_retention/`
modules (`hold_transitions.py`, `hold_repository.py`,
`custody_sweep_client.py`, `disposal_repository.py`) describing the future
integration point — no Phase 1-7 production write path, CLI command, or
handler references either new class. No custody-period/marker-retention
duration value is supplied anywhere (confirmed empty mapping in
`infra/serverless.yml` and by the `sls print` failure above).

## 4. Failed Tests

None. All 216 focused tests and 1664 canonical-suite tests passed on
direct execution.

## 5. Failure Classification

Not applicable — no failures observed in this validation pass.

## 6. Observations

- No flakiness observed; the focused suite runs deterministically in
  ~0.4s using fake/in-memory collaborators and an injectable monotonic
  clock for wall-clock-budget tests (`_FakeClock`), avoiding real-time
  sleeps.
- The implementation report's own claimed test counts (36/53/27/14/216)
  were independently re-executed and reproduce exactly (`test_marker_store.py`
  actually yields 33 collected + additional guard tests — recounted directly
  via `pytest -v` output rather than accepted from the report; total
  focused-directory count of 216 matches exactly).
- One documented, disclosed field-naming deviation from the Technical
  Design's own worked example (`transition` vs. the Technical Design
  prose's `action`) — semantically identical, flagged in the module
  docstring, does not affect correctness or traceability.
- The report's §11 addendum (orchestrator-authored, describing the
  Lifecycle-rule addition and the resulting two-test update) was
  independently verified against the actual diff and actual `sls print`
  execution, not accepted at face value — confirmed accurate.

## 7. Regression Check

- Full canonical suite: 1664 passed, 2 skipped — matches the report's
  claimed post-Lifecycle-rule count exactly, independently reproduced.
- `CustodySweepClient`'s pre-existing methods
  (`remove_ttl_disposal_at`/`restore_ttl_disposal_at`/`retag_s3_versions`/
  `_list_object_versions`/`_retag_object_version`) are unchanged in the
  diff; their own pre-existing tests all still pass unmodified.
- `HoldRepository`'s pre-existing write-once (`write_hold_event`) and
  full-overwrite (`upsert_hold`) methods are unchanged; only a new,
  additive `update_hold_event_marker_fields` method was introduced.
- `hold_transitions.py` (A1.LH1) is untouched by this diff (confirmed by
  `git diff HEAD --stat` — not among the modified files) and its own 19
  tests in `test_hold_transitions.py` all still pass, confirming the
  orchestration layer built on top of it does not alter its behavior.

## 8. QA Decision

All 17 required behaviors/scenarios are PASS, each backed by a specifically
named, independently executed test that exercises the claimed property (not
merely a plausibly-named test asserting something weaker). No blocking
defects, no unresolved failures, no regressions in the full 1664-test
canonical suite. Infrastructure change is additive, untagged where required,
fail-closed, and verified directly via `sls print` rather than accepted from
the implementer's report. No IAM, CLI, API, or production write-path
change is present, consistent with this subphase's authorized scope.

[QA SIGN-OFF APPROVED]

This sign-off covers A1.LH2 (S3 canary-marker mechanism, symmetric
PLACE/RELEASE reconciliation, and the `retention-markers/` Lifecycle rule)
as validated against ADR Non-Negotiable Invariants 15-25 and Technical
Design §19.2/§19.3/§19.5/§19.6/§19.11 items 15-21. It does not cover CLI
wiring, custody-period value supply, or IAM enforcement — all confirmed
out of scope for this subphase and untouched by this change set. Readiness
for the next gate (HITL/PR) is affirmed on the merits of this change set
alone.
