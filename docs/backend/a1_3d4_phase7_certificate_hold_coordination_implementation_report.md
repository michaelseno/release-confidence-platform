# Implementation Report

## 1. Summary of Changes

Implemented Evidence Governance Workstream A1.3d.4: wired Phase 7 (Audit
Platform Integrity / Certificate) `CertificationMetadata` writes, and the
Phase 7 certificate S3 artifact write, to legal-hold coordination and
custody-field computation, mirroring the already-merged A1.3d.2 (Phase 5)
and A1.3d.3 (Phase 6) implementations. `write_cert_metadata_complete`
became a hold-coordinated `TransactWriteItems` call whose `Put` carries no
`ConditionExpression` of its own — the unconditional-replacement contract
(forced recertification must always succeed) is preserved exactly, with
only the appended `LegalHold.hold_version` `ConditionCheck` as the
transaction's condition. `CertificationPublisher.write_artifact` gained a
strongly-consistent hold-state read, write-time
`rcp-legal-hold`/`rcp-evidence-class=certificate` S3 tagging, and a new
canonical 11-segment key parser (`_parse_cert_key_identity`) that replaces
the prior prefix-only `assert` as the authoritative structural validation.
`operator_cli/main.py`'s `certify audit` construction block now resolves
`certificate`'s custody-period duration and constructs/injects a shared
`HoldRepository`. `operator_cli/result.py` gained three new, shared,
phase-neutral `_error_next_step` branches, reused identically by
`generate intelligence`/`generate report`/`certify audit`.
`CertificationJob` (Category 3) remains structurally untouched and
unconditioned across all four of its write methods. `engine.py` and
`identity.py` are byte-identical to the base commit.

## 2. Files Modified

Production (4):
- `src/release_confidence_platform/audit_platform_integrity/repository.py`
  (+122/-7) — hold-coordinated unconditional `Put`, governance-field
  helper, governance preflight, constructor gains
  `hold_repository`/`custody_period_days`.
- `src/release_confidence_platform/audit_platform_integrity/publisher.py`
  (+105/-9) — hold-state read, S3 object tagging, 11-segment key parser
  replacing the prior prefix-only `assert` in `write_artifact`.
- `src/release_confidence_platform/operator_cli/main.py` (+20/-1) —
  `certify audit` construction block: custody resolution, `HoldRepository`
  construction/injection.
- `src/release_confidence_platform/operator_cli/result.py` (+20/-0) —
  three new shared `_error_next_step` branches.

Tests, modified (5):
- `tests/unit/audit_platform_integrity/test_repository.py` (+423/-49)
- `tests/unit/audit_platform_integrity/test_engine.py` (+164/-0)
- `tests/unit/audit_platform_integrity/test_publisher.py` (+219/-18)
- `tests/unit/test_operator_cli_certify.py` (+327/-1)
- `tests/unit/test_operator_cli_result.py` (+94/-0)

Tests, new (1):
- `tests/unit/audit_platform_integrity/test_hold_coordination.py`
  (334 lines)

Documentation, new (2, this pass):
- `docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_plan.md`
- `docs/backend/a1_3d4_phase7_certificate_hold_coordination_implementation_report.md`

Unchanged, behavior-preservation targets (confirmed byte-identical to
`main`, verified through tests, not modified):
- `src/release_confidence_platform/audit_platform_integrity/engine.py`
- `src/release_confidence_platform/audit_platform_integrity/identity.py`
- `tests/unit/audit_platform_integrity/test_engine_no_phase6_mutation.py`

## 3. API Contract Implementation

`rcp certify audit`: `certificate`'s custody-period duration is resolved
via `CustodyPeriodConfigLoader().resolve("certificate", args.stage)`
exactly once, before `AwsClientFactory` construction, fail-closed on any
missing/invalid value. A single `HoldRepository` instance is constructed
and injected — by identity, not by value — into both
`CertificationRepository` (positional, plus keyword-only
`custody_period_days`) and `CertificationPublisher` (positional, receiving
no duration argument). On resolution failure, zero AWS clients, zero
`HoldRepository`, and zero `CertificationRepository`/`CertificationPublisher`
instances are constructed. `rcp retrieve cert-*` (all four variants) is
unchanged: `CertificationRepository`/`CertificationPublisher` are
constructed dependency-free (both governance params at their `None`
default), `CustodyPeriodConfigLoader` is never imported by the retrieval
path, and no `HoldRepository` is ever constructed there — verified by a
spy repository/publisher double recording zero write calls of any kind
during `retrieve cert-status`.

## 4. Data / Persistence Implementation

- `write_cert_metadata_complete`: governance preflight (first action) →
  compute SK → `_assert_phase7_sk` → build `base_item` via literal dict
  construction (never `sanitize()`d) → resolve `hold_key` via
  `HoldRepository.legal_hold_key(client_id, audit_id)` (client_id/audit_id
  already passed as explicit kwargs, no item-dict parsing needed) → within
  each `HoldCoordinatedTransactionRunner` attempt, merge fresh governance
  fields last (`{**base_item, **governance_fields}`), build a `Put` with
  **no** `ConditionExpression` key at all, and append the hold
  `hold_version` `ConditionCheck` → run via
  `HoldCoordinatedTransactionRunner.run(...)` with **no**
  `on_governed_condition_failed` callback (the `Put` carries no condition
  of its own and can never itself fail a condition check). Every attempt
  — including a hold-version retry — computes fresh
  `custody_expires_at`/`ttl_disposal_at`/`evidence_class` from that
  attempt's own clock and hold-state read.
- `CertificationJob` (`write_certjob_pending`/`update_certjob_in_progress`/
  `update_certjob_complete`/`update_certjob_failed`): entirely unchanged —
  no governance preflight, no hold-state read, no `TransactWriteItems`.
  Proven by dedicated per-method negative tests plus a full-flow test that
  runs all four via the real `CertificationEngine.certify()` pipeline.

## 5. Key Logic Implemented

- `_cert_governance_fields`: mirrors `_report_governance_fields`/
  `_intelligence_governance_fields` exactly, `evidence_class` fixed to
  `"certificate"`.
- `_parse_cert_key_identity` (publisher): a genuinely new 11-segment
  parser (not a copy of Phase 5's 8-segment or Phase 6's 9-segment
  parser) — validates `len(parts) == 11`, `parts[0] == "integrity"`,
  `parts[10] == "artifact.json"`, non-empty `client_id`/`audit_id`; raises
  `StorageError(..., "STORAGE_ERROR")` with a fixed message that never
  echoes the key or any derived identifier. This function replaces the
  existing `assert key.startswith("integrity/")` guard as `write_artifact`'s
  authoritative structural validation; `read_artifact`'s prefix-only guard
  is untouched.
- `write_artifact` precedence (locked, verified by a dedicated test): (1)
  hold-configuration check, (2) key parsing via `_parse_cert_key_identity`,
  (3) `get_legal_hold(consistent_read=True)`, (4) tag computation, (5)
  `put_object`. A missing `HoldRepository` is reported even for a
  simultaneously malformed key.
- `_cert_tagging`: mirrors `_report_tagging` exactly, `evidence_class`
  fixed to `"certificate"` in the `urlencode(...)` call.
- `CertificationEngine.certify()` and `identity.build_cert_s3_key()`: not
  modified. Confirmed via `test_certify_engine_receives_no_custody_or_hold_dependency`
  (constructor signature unchanged) and
  `test_certify_existing_call_shapes_unchanged` (exact kwargs to
  `write_cert_metadata_complete`/`write_artifact` unchanged).

## 6. Security / Authorization Implemented

- Fail-closed governance preflight (`HOLD_COORDINATION_NOT_CONFIGURED`
  then `CUSTODY_PERIOD_CONFIG_MISSING`, Boolean rejected before the `int`
  check) on `write_cert_metadata_complete`; hold-configuration-only
  preflight on `write_artifact` (publishers never receive a duration).
- `CertificationPublisher.write_artifact` performs a strongly-consistent
  (`consistent_read=True`) hold-state read immediately before
  `put_object`, per Invariant 17; hold-error identity is preserved (an
  already-raised `StorageError` is never re-wrapped).
- `sanitize()` is never called on the full persistence-bound
  `CertificationMetadata` item — the item is built via literal dict
  construction, never derived from or merged through a sanitizing helper.
- No new IAM permissions required.
- No secrets, tokens, or credentials touched.

## 7. Error Handling Implemented

All reason codes reused, no new code introduced:
`HOLD_COORDINATION_NOT_CONFIGURED`, `CUSTODY_PERIOD_CONFIG_MISSING`,
`HOLD_STATE_CONCURRENCY_EXCEEDED`, `STORAGE_ERROR` (malformed key /
hold-read failure), `S3_CERTIFICATE_WRITE_FAILURE`. All map through
`render_error()` with reason-code preservation, non-zero exit, no
traceback, no AWS request detail, no DynamoDB/S3 key, no client/audit
identifier leakage — verified directly in `test_operator_cli_result.py`.
`_error_next_step` gained three new branches (§20.11.1): a
policy-configuration-gap framing for `CUSTODY_PERIOD_CONFIG_MISSING`
(directs the operator to `config/custody_periods.json`'s
`evidentiary_classes.<class>.<stage>` entry, names no specific class/stage
in the string itself); a runtime-wiring-defect framing for
`HOLD_COORDINATION_NOT_CONFIGURED` (directs escalation, not retry); and an
honest, bounded-retry framing for `HOLD_STATE_CONCURRENCY_EXCEEDED` (retry
may help, persistent recurrence should be investigated). All three are
proven identical regardless of which of `generate intelligence`/
`generate report`/`certify audit` triggered them, and proven to leak no
identifier/key fragment from a representative triggering message.

## 8. Observability / Logging

No new logging added or required by this change — existing
`CertificationEngine` structured-log events (`CERT_INVOKED`,
`CERT_PENDING`, `CERT_IN_PROGRESS`, `CERT_COMPLETE`, `CERT_FAILED`, etc.)
are unaffected since `engine.py` is byte-identical to `main`;
hold-coordination failures surface as exceptions through the existing CLI
error-rendering path, consistent with the Phase 5/6 precedent.

## 9. Assumptions Made

- Several pre-existing test functions in `test_repository.py` and
  `test_publisher.py` that previously exercised the now-removed
  unconditional `_put_item` call and the now-replaced prefix-only `assert`
  guard were adapted to remain meaningful against the new hold-coordinated/
  parser-based contract. Full accounting, corrected below (an earlier
  version of this report undercounted the `test_publisher.py` figure as 3
  when the true figure, confirmed by direct diff review, is 9):

  - `test_repository.py` (2 tests adapted):
    `test_write_cert_metadata_complete_asserts_phase7_sk`,
    `test_write_cert_metadata_complete_uses_correct_sk` — both constructed
    a hold-aware repository (`_make_hold_aware_repo()`) in place of the
    plain `_make_repo()` + `patch.object(repo, "_put_item", ...)` pattern,
    since `_put_item` no longer exists on this write path. Assertions
    (SK correctness, field values) are unchanged in substance.
  - `test_publisher.py` (9 tests adapted, not 3):
    - **6 received only the mechanically required fixture-constructor
      swap** (`_make_publisher()` → `_make_hold_aware_publisher()`), with
      **no assertion or behavioral change** — forced purely because
      `write_artifact` now requires hold configuration to reach the S3
      call at all, and these 6 tests' own subject matter (bucket/key
      correctness, JSON serialization, `ContentType`, S3-failure mapping,
      key-prefix propagation, byte-determinism) does not otherwise
      interact with hold coordination:
      `test_write_artifact_calls_put_object_with_correct_bucket_and_key`,
      `test_write_artifact_serializes_with_sort_keys`,
      `test_write_artifact_sets_content_type_json`,
      `test_write_artifact_raises_storage_error_on_s3_failure`,
      `test_write_artifact_uses_integrity_prefix`,
      `test_write_artifact_determinism`.
    - **3 required the governed exception-type change**
      (`AssertionError` → `StorageError` with `error_type == "STORAGE_ERROR"`),
      the only behavioral-expectation change made to any pre-existing
      test in this pass, and an intentional, Technical-Design-mandated
      change (§20.8.1: the canonical 11-segment key parser replaces the
      prior prefix-only `assert` as `write_artifact`'s authoritative
      structural validation, so a malformed key now fails via the parser's
      `StorageError`, not the old `assert`):
      `test_write_artifact_raises_assertion_error_on_non_integrity_prefix`,
      `test_write_artifact_raises_assertion_error_on_intelligence_prefix`,
      `test_write_artifact_raises_assertion_error_on_raw_results_prefix`.

  No assertion or behavioral expectation in any pre-existing test was
  weakened beyond that single, explicitly governed exception-boundary
  change (`AssertionError` → `StorageError`) — every other adaptation is a
  pure fixture/constructor substitution with zero effect on what the test
  actually verifies. This mirrors the identical, precedented adaptation
  already made to Phase 6's `test_repository.py`/`test_publisher.py`
  during A1.3d.3 — confirmed by direct comparison against that commit's
  diff before making the equivalent Phase 7 change. Test count and
  collection totals were unaffected (16/12 existing tests remain 16/12
  collected items in each file; `read_artifact`'s 3 tests in
  `test_publisher.py` are untouched, confirmed by an empty diff on those
  functions).
- No other assumption required escalation.

## 10. Validation Performed

```
uv run pytest -q tests/unit/audit_platform_integrity/
275 passed in 0.46s
```

```
uv run pytest -q tests/unit/test_operator_cli_certify.py
21 passed in 0.39s
```

```
uv run pytest -q tests/unit/test_operator_cli_result.py
26 passed in 0.04s
```

```
uv run pytest --collect-only -q
2115 tests collected
```

```
uv run pytest -q
2113 passed, 2 skipped in 5.92s
```
(Baseline before this change: 2047 passed, 2 skipped — net +66 test cases,
all new, zero regressions, exactly matching the 66-test inventory in the
task brief.)

### Corrective note (post-QA-handoff, applied on the same uncommitted branch)

An initial pass of this section claimed all 13 `ruff check` findings across
the 10 touched/created files "exactly matched the pre-implementation
baseline, no new finding introduced." Independent verification (Product
Strategy) confirmed 12 of the 13 were genuinely baseline-identical, but
found the 13th — `test_operator_cli_certify.py`'s `I001` finding — was
**not** the same violation as the baseline's `I001`. The base commit's
`test_operator_cli_certify.py` had a pre-existing `I001` (its
`from __future__ import annotations` import block was already un-sorted)
plus a pre-existing `E501`. This subphase's own import-block expansion
(adding 8 new imports needed for the composition-contract mocks) happened
to leave those imports in correctly sorted order — which incidentally
resolved the *original* `I001` — but left one extra blank line after the
import block, which triggered a **new**, differently-caused `I001` finding
at the same rule code, same file, and coincidentally the same total count
(2), masking the substitution when only totals were compared. This was not
caught during the original implementation pass because the check compared
finding *counts* per file rather than each finding's underlying cause.

**Fix applied**: removed the one extra blank line after the import block
in `tests/unit/test_operator_cli_certify.py`. No test behavior, assertion,
fixture, mocking behavior, or production code was altered. As a side
effect of the original (unchanged) import reorganization, the file's true
current finding count for this rule is now 0 (not merely "back to
baseline") — the pre-existing `E501` (line-too-long on
`test_cert_status_missing_stage_exits_nonzero`, a test this subphase does
not touch) remains, unchanged, at its shifted line number.

```
uv run ruff check <10 touched/created files>
Found 12 errors.
```
Distribution: 7 in `main.py` (4 `I001` + 3 `E501`). All four `I001`
findings are baseline-pre-existing — none is new. Three sit in import
blocks this subphase does not touch (module-level, line 3; the
`retrieve report-*` block, line 244; the `retrieve cert-*` block, line
276). The fourth, at line 462, sits in the `certify` block's own import
group — and that block **was** modified by A1.3d.4 (the new
`CustodyPeriodConfigLoader`/`HoldRepository` imports required for
custody/hold-dependency wiring were added directly into it, confirmed by
`git diff main -- src/.../operator_cli/main.py`). That block's `I001`
violation already existed on the authorized baseline before this change
(confirmed via `git stash` against the base commit); this subphase's
modification of that same block introduced no new Ruff finding. The three
`E501` findings in `main.py` are likewise all pre-existing, in lines this
subphase does not touch. 1 in
`test_repository.py`, 2 in `test_publisher.py`, 1 in
`test_operator_cli_certify.py` (the pre-existing `E501` only — the
newly-introduced `I001` from the corrective note above is now fixed), 1 in
`test_engine.py`, 0 elsewhere. Relative to the *authorized* baseline (the
true pre-implementation state of each file on `main`, not the miscounted
figure from the original pass): `main.py`, `test_repository.py`,
`test_publisher.py`, and `test_engine.py` are unchanged at 7/1/2/1
respectively; `test_operator_cli_certify.py` is at 1, one fewer than its
true baseline of 2, because the necessary import-block reorganization
(performed during the original A1.3d.4 implementation pass, not by this
corrective fix) incidentally also resolved that file's pre-existing
`I001`. Zero new findings exist relative to the authorized baseline.

```
uv run ruff format --check <10 touched/created files>
6 files would be reformatted, 4 files already formatted.
```
The 6 flagged (`repository.py`, `main.py`, `test_engine.py`,
`test_publisher.py`, `test_repository.py`, `test_operator_cli_certify.py`)
are exactly the 6 files already needing reformatting before this change
(confirmed by re-running the identical command against the base commit),
for pre-existing, unrelated lines this subphase does not touch — left
untouched per the no-unrelated-reformatting exclusion.
`test_operator_cli_certify.py` remains in this set post-fix solely because
of its own pre-existing, untouched `E501` line
(`test_cert_status_missing_stage_exits_nonzero`) — no new formatting drift
was introduced by the corrective blank-line removal, confirmed by
`ruff format --diff` showing only that one pre-existing hunk. The 4 clean
(`publisher.py`, `result.py`, `test_operator_cli_result.py`, and the new
`test_hold_coordination.py`) are correctly formatted; any format-diff
introduced by newly-added code in this pass (one line each in
`test_publisher.py`, `test_hold_coordination.py`, and
`test_operator_cli_result.py`) was fixed at the line level before this
validation run.

```
git diff main -- src/release_confidence_platform/audit_platform_integrity/engine.py
(no output, exit 0)

git diff main -- src/release_confidence_platform/audit_platform_integrity/identity.py
(no output, exit 0)

git diff main -- tests/unit/audit_platform_integrity/test_engine_no_phase6_mutation.py
(no output, exit 0)

git diff main -- config/custody_periods.json
(no output, exit 0)

git diff main -- infra/
(no output, exit 0)
```

```
git status --short
 M src/release_confidence_platform/audit_platform_integrity/publisher.py
 M src/release_confidence_platform/audit_platform_integrity/repository.py
 M src/release_confidence_platform/operator_cli/main.py
 M src/release_confidence_platform/operator_cli/result.py
 M tests/unit/audit_platform_integrity/test_engine.py
 M tests/unit/audit_platform_integrity/test_publisher.py
 M tests/unit/audit_platform_integrity/test_repository.py
 M tests/unit/test_operator_cli_certify.py
 M tests/unit/test_operator_cli_result.py
?? AGENTS.md   (pre-existing, untracked, unrelated -- untouched)
?? tests/unit/audit_platform_integrity/test_hold_coordination.py
```

```
git diff --stat main
 .../audit_platform_integrity/publisher.py          | 114 ++++-
 .../audit_platform_integrity/repository.py         | 129 +++++-
 .../operator_cli/main.py                           |  21 +-
 .../operator_cli/result.py                         |  20 +
 tests/unit/audit_platform_integrity/test_engine.py | 164 +++++++
 .../audit_platform_integrity/test_publisher.py     | 237 ++++++++++-
 .../audit_platform_integrity/test_repository.py    | 472 ++++++++++++++++++---
 tests/unit/test_operator_cli_certify.py            | 328 +++++++++++++-
 tests/unit/test_operator_cli_result.py             |  94 ++++
 9 files changed, 1494 insertions(+), 85 deletions(-)
```

Additionally confirmed:
`tests/unit/audit_platform_integrity/test_engine_no_phase6_mutation.py`
passes unmodified as part of the full-suite run above — this file's own,
unrelated Phase 6 SK-namespace non-mutation invariant is unaffected;
Category 3 `CertificationJob` governance-field-exclusion coverage was
correctly placed in `test_repository.py`/`test_engine.py` per the
technical design's explicit scope-precision correction, not in this file.

### Test counts added per file

| File | Before | After | Delta |
|---|---|---|---|
| `test_repository.py` | 16 collected | 33 collected | +17 |
| `test_engine.py` | 20 collected | 27 collected | +7 |
| `test_publisher.py` | 12 collected | 30 collected | +18 |
| `test_operator_cli_certify.py` | 13 collected | 21 collected | +8 |
| `test_operator_cli_result.py` | 19 collected | 26 collected | +7 |
| `test_hold_coordination.py` (new) | — | 9 collected | +9 |

Total new collected test cases: 66, matching the full-suite delta
(2113 − 2047 = 66) exactly, and matching the task brief's 66-test
inventory exactly.

## 11. Known Limitations / Follow-Ups

- The known persistence partial-success/stale-Job-state defects
  (issue #118 — an S3 artifact written without a completed Metadata
  pointer, Job/Metadata status divergence, a Job stuck at PENDING/
  IN_PROGRESS, a partially-failed FAILED-transition update, and Phase 7's
  own best-effort, silently-swallowed final `update_certjob_complete`/
  `update_certjob_failed` call at `engine.py`'s end) are unchanged and
  out of this subphase's scope, per Technical Design §20.10 — no test
  added by this change asserts any of these as expected/correct behavior.
- Per Technical Design §20.8.1, no client/audit identity parameter was
  added to `write_artifact` — identity is derived exclusively from the
  key via `_parse_cert_key_identity`, matching the locked "one identity
  source only" rule already established for Phase 5/6.
- This subphase closes A1.3d (Phase 5/6/7 hold coordination) as a whole —
  no further Phase 5/6/7 custody/hold-coordination work is anticipated
  under this workstream; any future numeric duration activation, S3
  Lifecycle rule change, or infrastructure deployment remains a
  separately authorized action.

## 12. Commit Status

No commit was created. Per the task's explicit instructions, this
implementation ends with the report only; commit/push/PR are separate,
later authorizations not granted in this task.

## Explicit Exclusion Confirmation

- **No custody value**: `config/custody_periods.json`'s `certificate`
  entry remains an empty object `{}` — not modified by this change.
- **No infrastructure change**: no `infra/serverless.yml`,
  `infra/resources/s3.yml`, or `infra/resources/dynamodb.yml` change.
- **No deployment/activation**: no deployment action taken.
- **No `engine.py`/`identity.py` change**: both confirmed byte-identical
  to `main` (§10 above, empty `git diff`).
- **No documentation change beyond the two new backend `.md` files**: no
  other `docs/` file was created or modified by this implementation.
- **No commit, no push, no PR.**
- **No QA documents created**:
  `docs/qa/a1_3d4_phase7_certificate_hold_coordination_test_plan.md` and
  `..._test_report.md` were not created — reserved for the independent QA
  pass, per the task's explicit instruction.
- **No opportunistic refactor**: `read_artifact` in `publisher.py` is
  byte-identical to before; `retrieve cert-*` block in `main.py`
  (unchanged lines) is byte-identical to before; the four
  `CertificationJob` write methods in `repository.py` are byte-identical
  to before.
