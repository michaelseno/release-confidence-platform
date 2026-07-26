# Implementation Report

## A1.LH1 — Authoritative Hold State and DynamoDB Coordination

*Formerly identified in the corrective architecture sequence as “Legal-Hold Correction B1.”*

**Branch:** `feature/legal-hold-b1-authoritative-hold-state-dynamodb-coordination`
**Base commit:** `62e265e7db11f9bb419745435b3e5530ccd07e1f` (`main`,
"docs(evidence-retention): define legal-hold temporal-coverage architecture")
**Status:** Implementation complete, uncommitted, working tree clean of
anything outside this scope. Not committed, not pushed, no PR opened — per
instruction, this is a separate QA/HITL gate.

---

## 0. Traceability Matrix — Required Behaviors and Authorized-Scope Bullets

### 0.1 The 13 Required Behaviors

| # | Required behavior | Code | Test |
| --- | --- | --- | --- |
| 1 | Every PLACE/RELEASE increments `hold_version` by exactly 1 | `hold_transitions.py::HoldTransitions.place`/`release` (new-episode/new-release branches only) | `test_hold_transitions.py::test_place_then_release_share_hold_id_and_increment_version_by_exactly_one`, `::test_full_cycle_place_release_place_yields_three_strictly_increasing_versions` |
| 2 | Same `hold_id` identifies one PLACE→RELEASE episode | `hold_transitions.py::place` (generates `hold_id` only on new episode); `release` (reuses `current["hold_id"]`, never generates) | `test_hold_transitions.py::test_place_then_release_share_hold_id_and_increment_version_by_exactly_one` |
| 3 | A later, independent episode gets a new `hold_id` | `hold_transitions.py::place`'s new-episode branch (`generate_hold_id()` called fresh) | `test_hold_transitions.py::test_new_episode_after_release_receives_a_different_hold_id` (asserts inequality only, not the mechanism, per TD §19.11 item 18's note) |
| 4 | `LegalHoldEvent` keys (`hold_id`+`hold_version`) never alias across versions | `hold_repository.py::legal_hold_event_key` (SK now includes `hold_version`) | `test_hold_repository.py::test_legal_hold_event_key_distinct_for_place_and_release_of_same_episode`, `::test_write_hold_event_place_and_release_of_same_episode_use_distinct_keys`; `test_models.py::test_legal_hold_event_place_and_release_of_same_hold_id_have_distinct_hold_version` |
| 5 | Stale re-invocation after `sweep_status=COMPLETE` is a terminal no-op (no `upsert_hold`, no `LegalHoldEvent` write, immediate return) | `hold_transitions.py::place`'s `sweep_status == SWEEP_STATUS_COMPLETE` branch | `test_hold_transitions.py::test_place_reinvocation_after_sweep_complete_is_pure_noop` (asserts call counts unchanged) |
| 6 | Interrupted transitions (`sweep_status != COMPLETE`) resume safely, no duplicate event write | `hold_transitions.py::place`'s resume branch; `release`'s new second-case resume branch | `test_hold_transitions.py::test_place_resumes_interrupted_episode_without_new_write`, `::test_release_resumes_interrupted_episode_without_new_write` (parametrized over PENDING/IN_PROGRESS/FAILED) |
| 7 | `status`/`sweep_status` remain independent, never conflated/derived | `models.py::LegalHold` (two separate fields, two separate validators); `hold_repository.py::upsert_hold` (both passed explicitly, no default) | `test_hold_repository.py::test_upsert_hold_persists_sweep_status_independent_of_status`; `test_models.py::test_legal_hold_status_and_sweep_status_are_independent_fields`; `test_hold_transitions.py::test_outcome_reports_status_and_sweep_status_independently` |
| 8 | `status=ACTIVE` alone is never proof of completed protection | `hold_transitions.py::is_hold_fully_enforced` (explicit conjunction) | `test_hold_transitions.py::test_is_hold_fully_enforced_requires_both_active_and_complete` |
| 9 | Stale hold versions cause transactional rejection | `hold_coordination.py::build_hold_version_condition_check_item` + `HoldCoordinatedTransactionRunner.run` | `test_hold_coordination.py::test_condition_check_pins_exact_hold_version_when_hold_exists`, `::test_run_retries_when_only_hold_condition_fails_then_succeeds` |
| 10 | Retries bounded (3) and deterministic | `hold_coordination.py::HoldCoordinatedTransactionRunner` (`max_attempts` default `MAX_HOLD_COORDINATION_RETRY_ATTEMPTS=3`) | `test_hold_coordination.py::test_run_raises_hold_state_concurrency_exceeded_after_max_attempts`, `::test_run_respects_custom_max_attempts` |
| 11 | Retry exhaustion fails closed (`HOLD_STATE_CONCURRENCY_EXCEEDED`), never unconditioned fallback | `hold_coordination.py::HoldCoordinatedTransactionRunner.run` (raises on exhaustion; every attempt includes the `ConditionCheck`) | `test_hold_coordination.py::test_run_raises_hold_state_concurrency_exceeded_after_max_attempts` (asserts every attempt's transact-items include a `ConditionCheck`) |
| 12 | Dual-failure precedence: governed record's own failure wins | `hold_coordination.py::HoldCoordinatedTransactionRunner.run` (inspects governed items' `CancellationReasons` before the hold condition's) | `test_hold_coordination.py::test_governed_condition_failure_takes_precedence_over_hold_condition_failure`, `::test_governed_condition_failure_without_callback_reraises_raw_client_error`, `::test_governed_condition_failure_with_multi_item_governed_write_still_takes_precedence` |
| 13 | Existing A1.1 namespace guards remain intact (`_assert_retention_sk` still rejects `#DISPOSAL#`) | `hold_repository.py::_assert_retention_sk` (unmodified) | `test_hold_repository.py::test_assert_retention_sk_rejects_disposal_sk`, `::test_assert_retention_sk_rejects_disposal_sk_even_with_hold_version_shape` (new, proves the guard still rejects `#DISPOSAL#` under the corrected SK shape) |

### 0.2 Authorized-Scope Bullets

| Bullet | Code | Test |
| --- | --- | --- |
| `hold_version` field | `models.py::LegalHold.hold_version`; `hold_repository.py::upsert_hold` | `test_models.py::test_legal_hold_rejects_hold_version_below_one`; `test_hold_repository.py::test_upsert_hold_calls_put_item` |
| `sweep_status` field | `models.py::LegalHold.sweep_status`; `constants.py::SWEEP_STATUSES` | `test_models.py::test_legal_hold_accepts_all_bounded_sweep_statuses`, `::test_legal_hold_rejects_unknown_sweep_status` |
| Authoritative PLACE/RELEASE transitions (§19.2/§19.3), incl. corrected resumability | `hold_transitions.py::HoldTransitions` | `test_hold_transitions.py` (full file) |
| Episode-scoped `hold_id` | `hold_transitions.py::place`/`release` | `test_hold_transitions.py::test_place_then_release_share_hold_id_and_increment_version_by_exactly_one` |
| Immutable transition identity via `hold_version`+`transition`, not `hold_id` | `hold_repository.py::legal_hold_event_key` (keys on `hold_id`+`hold_version`; `action` field records the transition) | `test_hold_repository.py::test_legal_hold_event_key_distinct_for_place_and_release_of_same_episode` |
| Transition-safe `LegalHoldEvent` persistence (the required fix) | `hold_repository.py::legal_hold_event_key`/`get_legal_hold_event`/`write_hold_event` (all three gain `hold_version`) | `test_hold_repository.py` (full `write_hold_event`/`get_legal_hold_event`/key-shape sections) |
| Authoritative marker-status persistence interfaces (plumbing only) | `models.py::LegalHold`/`LegalHoldEvent` marker fields; `hold_repository.py::write_hold_event`/`upsert_hold` marker parameters | `test_hold_repository.py::test_write_hold_event_defaults_marker_fields_to_pending_plumbing_state`, `::test_upsert_hold_calls_put_item` (marker fields default None); `test_models.py::test_legal_hold_marker_fields_default_to_none`, `::test_legal_hold_event_marker_status_defaults_to_pending` |
| DynamoDB hold-state lookup / `ConsistentRead` reasoning re-checked | `hold_repository.py::get_legal_hold` unchanged (no `ConsistentRead` added — confirmed correct per TD §19.4/§19.5.4's own reasoning: harmless on this path since `TransactWriteItems`' `ConditionCheck` re-verifies at commit) | N/A — a deliberate non-change; reasoning recorded in this report and in code comments in `hold_coordination.py` |
| Reusable `TransactWriteItems`/`ConditionCheck` coordination mechanism | `hold_coordination.py::HoldCoordinatedTransactionRunner`, `build_hold_version_condition_check_item` | `test_hold_coordination.py` (full file) |
| Bounded retry behavior | `hold_coordination.py::HoldCoordinatedTransactionRunner` (`max_attempts`) | `test_hold_coordination.py::test_run_raises_hold_state_concurrency_exceeded_after_max_attempts` |
| Explicit dual-failure precedence | `hold_coordination.py::HoldCoordinatedTransactionRunner.run` | `test_hold_coordination.py::test_governed_condition_failure_takes_precedence_over_hold_condition_failure` |
| Fail-closed retry exhaustion (`HOLD_STATE_CONCURRENCY_EXCEEDED`) | `hold_coordination.py::HoldStateConcurrencyExceededError`; `constants.py::HOLD_STATE_CONCURRENCY_EXCEEDED_CODE` | `test_hold_coordination.py::test_run_raises_hold_state_concurrency_exceeded_after_max_attempts` |
| New error subcodes per §19.15 (incl. `HOLD_MARKER_ESTABLISHMENT_FAILED` defined-but-unraised) | `constants.py::HOLD_STATE_CONCURRENCY_EXCEEDED_CODE`, `HOLD_MARKER_ESTABLISHMENT_FAILED_CODE` | Confirmed by inspection — `HOLD_MARKER_ESTABLISHMENT_FAILED_CODE` has zero raise sites anywhere in this subphase's code (grep-verified) |

---

## 1. Summary of Changes

Implemented the DynamoDB-side coordination foundation for legal hold
(Technical Design §19.1–§19.4, §19.5.1's "Required consequence", §19.5.2;
ADR Decision 9, Non-Negotiable Invariants 11, 12, 14, 21, 23, 24, 25):

1. Added `hold_version`/`sweep_status` to `LegalHold`, and the required
   `hold_version` SK discriminator plus canary-marker plumbing fields to
   `LegalHoldEvent` (and matching plumbing on `LegalHold`).
2. Corrected `HoldRepository.legal_hold_event_key`/`get_legal_hold_event`/
   `write_hold_event`/`upsert_hold` signatures accordingly, updating every
   existing caller/test (confirmed via repo-wide grep: only this module's
   own test file constructed these keys — no production caller existed to
   break).
3. Added `hold_transitions.py` (`HoldTransitions`), implementing the
   corrected PLACE (§19.2 steps 1–4) and RELEASE (§19.3 steps 1–3) sequences
   — new-episode / resume / stale-no-op (PLACE) / rejection (RELEASE) — over
   `HoldRepository`'s existing guarded CRUD, with no S3 dependency.
4. Added `hold_coordination.py` (`HoldCoordinatedTransactionRunner`), a
   reusable `TransactWriteItems`/`ConditionCheck` mechanism (§19.4) with
   bounded retry, the dual-failure precedence rule, and fail-closed retry
   exhaustion — proven with test-double governed items, wired to no real
   write path.
5. Completed §19.15's error classification: `HOLD_STATE_CONCURRENCY_EXCEEDED`
   (raised) and `HOLD_MARKER_ESTABLISHMENT_FAILED` (defined only, reserved
   for B2).

No contradiction was found between the architecture documents and the
repository's current state; no escalation was required.

## 2. Files Modified

| File | Why |
| --- | --- |
| `src/release_confidence_platform/evidence_retention/constants.py` | Added `SWEEP_STATUSES`/`MARKER_STATUSES` bounded sets, `MAX_HOLD_COORDINATION_RETRY_ATTEMPTS`, and the two new `StorageError` subcodes. |
| `src/release_confidence_platform/evidence_retention/models.py` | Added `hold_version`/`sweep_status`/`marker_*` to `LegalHold`; `hold_version`/`marker_*` to `LegalHoldEvent`, with bounded-set and `>=1` validators. |
| `src/release_confidence_platform/evidence_retention/hold_repository.py` | `legal_hold_event_key`/`get_legal_hold_event`/`write_hold_event` gain a required `hold_version` parameter (SK now `...#LEGALHOLD#{hold_id}#{hold_version}`); `upsert_hold` gains required `hold_version`/`sweep_status` and optional marker-plumbing parameters. Docstrings updated to record the A1.LH1 scope addition. `_assert_retention_sk` itself is untouched. |
| `src/release_confidence_platform/evidence_retention/hold_transitions.py` (new) | `HoldTransitions.place()`/`release()`, `HoldNotActiveError`, `HoldTransitionOutcome`, `is_hold_fully_enforced()` — the authoritative transition sequencing. |
| `src/release_confidence_platform/evidence_retention/hold_coordination.py` (new) | `HoldCoordinatedTransactionRunner`, `build_hold_version_condition_check_item`, `compute_ttl_disposal_at`, `HoldStateConcurrencyExceededError` — the reusable DynamoDB coordination mechanism. |
| `tests/unit/evidence_retention/test_hold_repository.py` | Updated every existing call site for the new required parameters; added SK-collision, marker-default, and independence tests. |
| `tests/unit/evidence_retention/test_models.py` | Updated fixtures for the new required fields; added bounded-set/validation tests for `hold_version`/`sweep_status`/`marker_status`. |
| `tests/unit/evidence_retention/test_hold_transitions.py` (new) | Full PLACE/RELEASE sequencing coverage, including the critical stale-reinvocation regression and a real-`HoldRepository` integration check. |
| `tests/unit/evidence_retention/test_hold_coordination.py` (new) | Full `TransactWriteItems` coordination coverage: retry, precedence, exhaustion. |

## 3. API Contract Implementation

No API contract changes. Confirmed: no HTTP endpoint exists in this
platform; no CLI command was added or modified (`rcp retention hold
place|release|status` remains unimplemented, deferred to whichever
subphase builds `RetentionService` and wires it to a CLI parser).

## 4. Data / Persistence Implementation

- `LegalHold` item shape gains four additive fields (`hold_version`,
  `sweep_status`, `marker_s3_key`, `marker_confirmed_last_modified`); no
  existing field's meaning or presence changed.
- `LegalHoldEvent`'s SK changes shape (`hold_id` alone →
  `hold_id`+`hold_version`) and its item gains `hold_version` plus three
  marker-plumbing fields. This is the one genuine key-shape change in this
  subphase; it carries no backfill/migration implication because
  `LegalHoldEvent` has never been written by any production code path (A1.1
  built the repository method; no `RetentionService` or CLI command calling
  it has ever existed) — confirmed by repo-wide grep before making the
  change.
- No S3 object shape changes. No other DynamoDB record type is touched.

## 5. Key Logic Implemented

- **Episode identity (`hold_id` constant across PLACE/RELEASE, ADR Invariant
  21):** `HoldTransitions.place()` generates `hold_id` only when starting a
  genuinely new episode (no record, or `status=RELEASED`); `release()`
  never generates a new `hold_id`, always reusing the current record's.
- **`hold_version` monotonicity (ADR Invariant 12):** incremented by exactly
  1 in both the new-episode branch of `place()` and the new-release branch
  of `release()`; never touched on a resume or no-op branch.
- **PLACE stale-no-op gate (ADR Invariant 23, TD §19.2 step 4):**
  `sweep_status == COMPLETE` short-circuits before any write; `sweep_status
  != COMPLETE` resumes using the existing `hold_id`/`hold_version`.
- **RELEASE's new three-case branch (TD §19.3 step 2):** genuine release
  (`status=ACTIVE`) → new write; interrupted release resume
  (`status=RELEASED`, `sweep_status != COMPLETE`) → reuse, no write; stale/
  never-held (`status=RELEASED` + `COMPLETE`, or no record) →
  `HoldNotActiveError`.
- **`LegalHoldEvent` SK collision fix (ADR Invariant 25):** SK now
  `AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}`; a PLACE
  (`hold_version=N`) and its paired RELEASE (`hold_version=N+1`) share
  `hold_id` but always differ in `hold_version`, so they never collide at
  the identical key — proven directly in
  `test_write_hold_event_place_and_release_of_same_episode_use_distinct_keys`.
- **`TransactWriteItems` coordination (TD §19.4):**
  `HoldCoordinatedTransactionRunner.run()` re-reads `LegalHold` fresh on
  every attempt, builds the governed record's own items plus a
  `ConditionCheck` (`attribute_not_exists(PK)` or `hold_version = :expected`)
  via the caller-supplied builder, and retries up to `max_attempts` (default
  3) on a detected hold-state race or an unrelated transient cancellation.
- **Dual-failure precedence (TD §19.4 step 4):** the governed item's own
  `CancellationReasons` entries are inspected first; if any failed, the
  caller's `on_governed_condition_failed` callback (or the raw
  `ClientError`, absent a callback) surfaces immediately — no retry, never
  masked behind a hold-version race.
- **Fail-closed exhaustion (TD §19.4 step 5):** after `max_attempts`,
  `HoldStateConcurrencyExceededError` (`HOLD_STATE_CONCURRENCY_EXCEEDED`) is
  raised; every attempt, including the last, always included the hold
  `ConditionCheck` — never an unconditioned fallback write.

## 6. Security / Authorization Implemented

No new authentication/authorization surface. The existing `_assert_retention_sk()`
guard is unchanged and re-verified (new test:
`test_assert_retention_sk_rejects_disposal_sk_even_with_hold_version_shape`)
to still reject any `#DISPOSAL#`-shaped SK, including one that happens to
carry a trailing numeric segment resembling the new `hold_version` suffix.
No secret, token, or credential is introduced, logged, or handled anywhere
in this change.

## 7. Error Handling Implemented

- `HoldNotActiveError` (`HOLD_NOT_ACTIVE`) — release rejection, matching
  the existing §8 idempotency contract.
- `HoldStateConcurrencyExceededError` (`HOLD_STATE_CONCURRENCY_EXCEEDED`) —
  retry exhaustion on the coordination mechanism.
- `HOLD_MARKER_ESTABLISHMENT_FAILED` — defined in `constants.py` for
  classification-table completeness (TD §19.15); never raised by any A1.LH1 code
  path, since A1.LH1 has no S3 client dependency.
- Non-condition DynamoDB failures (e.g. `ResourceNotFoundException`)
  continue to route through the existing
  `storage_error_from_dynamodb_client_error` path, unchanged.

## 8. Observability / Logging

No new logging was added or required — A1.LH1 introduces no new operational
event a caller needs visibility into beyond the exceptions above (which
already carry a distinguishable `error_type`/message per the existing
`StorageError` convention). No sensitive data is present in any new field.

## 9. Assumptions Made

1. `hold_count` increments only on a genuine new PLACE episode (not on
   RELEASE, not on a resumed/no-op PLACE). Non-blocking: `hold_count` is
   display-only and never gates a correctness decision. See the
   implementation plan's §9 for full reasoning.
2. The PLACE/RELEASE transition sequencing lives in a new
   `hold_transitions.py` module (composition over `HoldRepository`) rather
   than as additional `HoldRepository` methods, preserving `HoldRepository`'s
   existing "strict CRUD only" scope statement. Implementation-shape choice
   only; does not change persisted data shape or external behavior.

Neither assumption affects external behavior, security, data shape, or the
governed correctness invariants (`hold_version` monotonicity, SK
non-collision, fail-closed retry) — both are documented per the assumption
policy and did not require escalation.

## 10. Validation Performed

**Focused suite** (`tests/unit/evidence_retention/`):

```
.venv/bin/python -m pytest tests/unit/evidence_retention/ -q
145 passed in 0.39s
```

Breakdown of new/updated test files: `test_hold_repository.py` — 23 tests
(updated signatures + 4 new); `test_models.py` — 40 tests (updated fixtures
+ 9 new); `test_hold_transitions.py` — 18 tests (new file); `test_hold_coordination.py`
— 14 tests (new file, after removing one unused helper found during lint).

**Full canonical regression suite** (per `pyproject.toml`
`[tool.pytest.ini_options]`, `testpaths = ["tests"]`; no exclusion flags
used):

```
.venv/bin/python -m pytest -q
1592 passed, 2 skipped in 2.92s
```

The 2 skips are pre-existing and unrelated to this change (not introduced or
modified by this subphase).

**Lint:**

```
.venv/bin/python -m ruff check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/
All checks passed!
```

One `E501` (line too long) was found and fixed during this pass, in a new
test file this subphase added.

**Format:**

```
.venv/bin/python -m ruff format --check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/
```

The two wholly new source/test module pairs
(`hold_coordination.py`/`hold_transitions.py` and their test files) are
fully `ruff format`-compliant (applied via `ruff format` on those four files
only, confirmed by re-running `--check`). The five pre-existing files this
subphase modified (`constants.py`, `hold_repository.py`, `models.py`,
`test_hold_repository.py`'s pre-existing portions, and — confirmed via
`git stash` before any edit — `custody_sweep_client.py`/`disposal_repository.py`,
which this subphase does not touch at all) already diverge from the
formatter's current output *before* this subphase's changes. Per the
scope-control rule against unrelated formatting churn, these pre-existing
files were left as-is rather than wholesale-reformatted; `test_hold_repository.py`
and `test_models.py` were confirmed formatter-clean both before and after
this subphase's edits (they were not in the `--check` failure list either
time).

## 11. Known Limitations / Follow-Ups

- No Category 1/2 write path is wired to `HoldCoordinatedTransactionRunner`
  yet — by design (subphases C+D/E/F).
- The S3 canary marker itself is not implemented — by design (subphase B2).
  The plumbing fields this subphase adds (`marker_s3_key`, `marker_status`,
  `marker_confirmed_last_modified`) have no writer other than their declared
  defaults until B2 lands.
- `RetentionService` does not exist yet; `HoldTransitions` is the
  `HoldRepository`-level building block a future `RetentionService` will
  call, per the orchestrator's explicit scope note.
- Pre-existing `ruff format` drift on `constants.py`, `hold_repository.py`,
  `models.py`, and two files this subphase does not touch
  (`custody_sweep_client.py`, `disposal_repository.py`) is a carried-forward,
  pre-existing condition (confirmed via `git stash` before editing) — not
  introduced or worsened by this subphase, and not fixed here to avoid
  unrelated formatting churn. Flagged for whoever next touches those files,
  or for a dedicated formatting pass if the team wants one.

## 12. Commit Status

**Not committed.** Per instruction, this subphase stops after producing a
clean, complete diff and this report; `git commit`/`git push`/`gh pr create`
are explicitly deferred to the separate QA/HITL gate. The working tree
currently contains exactly the files listed in §2 above (modified) plus the
four new files (two source, two test) and this pair of `docs/backend/`
documents — nothing else.
