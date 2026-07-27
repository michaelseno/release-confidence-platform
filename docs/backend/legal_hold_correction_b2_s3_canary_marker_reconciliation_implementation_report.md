# Implementation Report

## A1.LH2 — S3 Canary-Marker and Symmetric Reconciliation Foundation

*Formerly identified in the corrective architecture sequence as "Legal-Hold
Correction B2."*

## 1. Summary of Changes

Built the S3-side coordination mechanism (the canary marker) for Evidence
Governance Workstream A1's legal-hold mechanism and wired it together with
A1.LH1's already-merged DynamoDB-authoritative hold-state transitions
(`HoldTransitions`) and the already-merged existing-object sweep
(`CustodySweepClient`) via a new, minimal, real internal `RetentionService`
orchestrator — not a test double standing in for orchestration, an actual
implementation other code (a future CLI subphase) can call.

Five components, all traceable to companion ADR Decision 9 / Technical
Design §19:

1. **`marker_store.py`** — atomic, first-write-wins canary-marker creation
   (`PutObject` + `If-None-Match: "*"`), never a `HeadObject`-then-
   `PutObject` check-then-write. On conflict (`412 PreconditionFailed`),
   reads back and validates the existing marker's content against the
   current transition's expected identity before ever trusting it.
   Authoritative `LastModified` is captured via a dedicated `HeadObject`
   read-back — `PutObject`'s own response is never trusted for this. Both
   phases (creation/reuse, and the `HeadObject` read-back) share one
   wall-clock deadline plus independent retry-count caps.
2. **Deterministic marker JSON content** — `client_id`, `audit_id`,
   `hold_id`, `hold_version`, `transition`, a combined `transition_id`
   identity field, and `schema_version`.
3. **`_assert_marker_key()`** — a structural guard, called before every S3
   operation `MarkerStore` performs, mirroring
   `_assert_retention_sk`/`_assert_disposal_sk`/
   `_assert_custody_field_only_update`.
4. **Marker-anchored reconciliation** — new `reconcile_versions()` public
   method on `CustodySweepClient`, reusing only the three already-
   allowlisted S3 operations (`list_object_versions`/`get_object_tagging`/
   `put_object_tagging`) — no new S3 API surface. Directionally symmetric:
   PLACE retags any in-window version not yet tagged `true`; RELEASE retags
   any in-window version still tagged `true` (the inverse filter
   direction).
5. **`RetentionService`** — orchestrates `HoldTransitions` → marker
   establishment → `CustodySweepClient`'s existing sweep methods →
   reconciliation → status confirmation, for both `place_legal_hold()` and
   `release_legal_hold()`.

A sixth, narrowly-scoped addition was required and made: `HoldRepository`
gained `update_hold_event_marker_fields()`, since `write_hold_event()` is
write-once (conditional `PutItem`) and cannot itself record a marker's
later confirmation/failure outcome. `upsert_hold()`'s existing full-
overwrite semantics were confirmed sufficient for `LegalHold`'s own
`sweep_status`/marker-field updates — no analogous new method was needed
there.

## 2. Files Modified

New:
- `src/release_confidence_platform/evidence_retention/marker_store.py`
- `src/release_confidence_platform/evidence_retention/retention_service.py`
- `tests/unit/evidence_retention/test_marker_store.py` (36 tests)
- `tests/unit/evidence_retention/test_retention_service.py` (14 tests)

Modified:
- `src/release_confidence_platform/evidence_retention/constants.py` — added
  `RETENTION_MARKER_KEY_PREFIX`, `MARKER_SCHEMA_VERSION`,
  `RECONCILIATION_BUFFER_SECONDS`,
  `MARKER_ESTABLISHMENT_WALL_CLOCK_BUDGET_SECONDS` (aliased to the same
  value as the buffer, per Technical Design §19.5.6's "reused rather than
  independently justified a second time"), and
  `HOLD_MARKER_INTEGRITY_VIOLATION_CODE` (new — see §9 below).
- `src/release_confidence_platform/evidence_retention/custody_sweep_client.py`
  — added `reconcile_versions()`, `_list_object_versions_with_last_modified()`,
  `_get_object_version_legal_hold_tag()`. `_ALLOWED_S3_METHODS`/
  `_ALLOWED_DYNAMODB_METHODS` unchanged; `_list_object_versions()`/
  `_retag_object_version()` untouched (existing tests for both still pass
  unmodified).
- `src/release_confidence_platform/evidence_retention/hold_repository.py` —
  added `update_hold_event_marker_fields()`. No existing method's behavior
  changed.
- `tests/unit/evidence_retention/test_custody_sweep_client.py` — 20 new
  tests for the reconciliation pass and allowlist-preservation proofs.
- `tests/unit/evidence_retention/test_hold_repository.py` — 4 new tests for
  `update_hold_event_marker_fields()`.
- `infra/resources/s3.yml` — added the fifth, untagged
  `retention-marker-disposal` Lifecycle rule (§11, added after this report
  was first drafted, by the orchestrator, resolving the contradiction the
  implementer flagged below).
- `infra/serverless.yml` — added `custom.custodyPeriodDays.retention_marker: {}`
  (§11).
- `tests/unit/test_infra_configuration.py` — two pre-existing tests updated
  to correctly scope to the four tag-filtered evidence-class rules; one new
  test added for the fifth rule's structurally distinct properties (§11).

## 3. API Contract Implementation

No API contract changes. `RetentionService` exposes exactly two public
methods (`place_legal_hold`, `release_legal_hold`) as a plain Python class
— no CLI command, no customer-facing endpoint, consistent with this
subphase's explicit exclusion of `rcp retention hold place|release|status`
CLI wiring.

## 4. Data / Persistence Implementation

- No DynamoDB schema change. `LegalHoldEvent`/`LegalHold`'s
  `marker_s3_key`/`marker_status`/`marker_confirmed_last_modified` fields
  already existed as additive plumbing from A1.LH1 — this subphase is the
  first to set non-default values into them.
- New S3 key namespace: `retention-markers/{client_id}/{audit_id}/{hold_id}/{hold_version}-{transition}.marker`
  — governance metadata (Category 4), never one of the four evidence-class
  prefixes, never enumerated by `CustodySweepClient`'s evidence-retagging
  sweep (`S3_EVIDENCE_CLASS_PREFIXES` unchanged).
- `update_hold_event_marker_fields()` is a narrow `UpdateItem` (`SET
  #mk = :mk, #ms = :ms, #mlm = :mlm`) touching exactly the three marker
  fields — never `action`/`actor`/`reason`/`timestamp`/counts — proven by
  `test_update_hold_event_marker_fields_does_not_touch_write_once_fields`.

## 5. Key Logic Implemented

**Marker establishment (`MarkerStore.establish_marker`):** two phases
sharing one wall-clock deadline (`MARKER_ESTABLISHMENT_WALL_CLOCK_BUDGET_SECONDS`
= 5, aliased to the reconciliation buffer per §19.5.6) plus independent
retry-count caps (`MAX_HOLD_COORDINATION_RETRY_ATTEMPTS` = 3, reused
unchanged from A1.LH1):
1. Atomic conditional `PutObject`. On `412`, validate the existing marker's
   content against the five identity fields
   (`client_id`/`audit_id`/`hold_id`/`hold_version`/`transition`) — exact
   match reuses it; any mismatch raises `MarkerIntegrityError` immediately
   (never retried).
2. Dedicated `HeadObject` read-back for the authoritative `LastModified`.

**Reconciliation (`CustodySweepClient.reconcile_versions`):** filter is
`LastModified >= (marker_confirmed_last_modified - 5s)` AND a
direction-dependent tag mismatch (PLACE: `!= true`; RELEASE: `== true`).
Confirmed independently tested for both directions (`test_reconcile_versions_place_*`
and `test_reconcile_versions_release_*`), not inferred from one direction's
coverage.

**RetentionService orchestration:**
- `outcome.is_noop` (from `HoldTransitions`) short-circuits before touching
  the marker store, `CustodySweepClient`, or `LegalHoldEvent`/`LegalHold`
  in any way — proven at the full-orchestration layer, not just at
  `HoldTransitions`' own layer (A1.LH1's existing coverage).
- Marker confirmation is checked on `LegalHoldEvent.marker_status` *before*
  ever calling `MarkerStore` (ADR Invariant 24): `CONFIRMED` reuses the
  durably-recorded value directly, regardless of whether the marker object
  still exists in S3; `PENDING`/`FAILED` triggers a fresh
  `establish_marker()` attempt.
- On marker failure: `marker_status → FAILED` (with the deterministically
  computable key preserved for operator traceability), `sweep_status →
  FAILED`, error propagated, `CustodySweepClient` never reached.
- On sweep/reconciliation failure *after* marker confirmation:
  `sweep_status` remains `IN_PROGRESS` (§19.6's always-safe, always-
  resumable branch) rather than `FAILED` — this module does not attempt to
  positively distinguish transient-vs-non-retriable AWS failures (out of
  authorized scope); documented as a technically safe implementation
  choice under §19.6's own permitted branch, not a silent gap.

## 6. Security / Authorization Implemented

- `MarkerStore` has its own S3 method allowlist (`put_object`/
  `head_object`/`get_object` only), enforced in `_call_s3()` via
  `AssertionError` on any other method name — a second, code-level
  enforcement layer beyond "the method doesn't exist," mirroring
  `CustodySweepClient`'s discipline.
- `CustodySweepClient._ALLOWED_S3_METHODS`/`_ALLOWED_DYNAMODB_METHODS`
  verified unchanged (`test_allowed_s3_methods_unchanged_by_reconciliation_addition`)
  and the class still has no `put_object`/`head_object` method
  (`test_custody_sweep_client_still_has_no_put_object_or_head_object_method`).
- No new IAM statements anywhere — `infra/serverless.yml`'s
  `provider.iam.role.statements` and every file under `infra/resources/`
  are untouched (see §11 for the one flagged exception this subphase
  considered and declined).
- No secrets, tokens, or customer operational evidence in the marker
  payload — only identifiers already used as S3 key components elsewhere
  in this codebase.

## 7. Error Handling Implemented

Two error types added, both `StorageError` subclasses following this
codebase's existing subcode pattern:
- `MarkerEstablishmentFailedError` (`HOLD_MARKER_ESTABLISHMENT_FAILED`,
  already reserved as a constant by A1.LH1) — retry/wall-clock budget
  exhaustion in either phase of `establish_marker()`.
- `MarkerIntegrityError` (`HOLD_MARKER_INTEGRITY_VIOLATION` — new code
  added by this subphase; not itself enumerated in Technical Design
  §19.15's retry-exhaustion table, since it is a distinct, never-retried
  failure mode, not a retry-exhaustion classification — added following
  the same established `StorageError`-subcode pattern rather than
  inventing new error-handling machinery).

Both propagate through `RetentionService` without being silently
swallowed; both trigger `marker_status=FAILED`/`sweep_status=FAILED`
persistence before propagating.

## 8. Observability / Logging

No new structured logging was added — this subphase's failure modes are
already fully observable via the raised, distinguishable `StorageError`
subcodes (consistent with this codebase's existing pattern for
`HOLD_STATE_CONCURRENCY_EXCEEDED_CODE` etc.) and via the durably-persisted
`marker_status`/`sweep_status` fields on `LegalHoldEvent`/`LegalHold`,
queryable independent of any log retention window. No tokens, secrets, or
sensitive request bodies are logged or included in any exception message.

## 9. Assumptions Made

- **`upsert_hold()`'s full-overwrite semantics are sufficient for
  `LegalHold`'s `sweep_status`/marker-field updates** — confirmed by
  reading the actual code (its docstring already states "PutItem
  overwrites any existing record for the same audit identity"); no new
  `LegalHold`-specific update method was added. This is a re-examination
  outcome, not a guess: `LegalHoldEvent`, being write-once, genuinely
  needed a new method (`update_hold_event_marker_fields`); `LegalHold` did
  not.
- **Post-marker-confirmation sweep/reconciliation failures leave
  `sweep_status = IN_PROGRESS`, never `FAILED`** — Technical Design §19.6
  explicitly permits this as the safe branch ("or transitions to FAILED
  for a detected non-retriable error" is the narrower, positive-detection
  branch this subphase does not implement, since that classification
  machinery is out of authorized scope). This does not change external
  behavior in a way requiring escalation: every `CustodySweepClient`
  operation and `reconcile_versions()` are already idempotent, so
  `IN_PROGRESS` is always safely resumable.
- **Marker JSON field name `transition`, not `action`** — Technical Design
  §19.5.1's own worked example uses `action`; this implementation uses
  `transition` for consistency with the parameter name used throughout
  this module and the rest of the ADR/Technical Design's own prose
  (`{hold_version}-{transition}.marker`, "the transition supplied by the
  caller"). Documented per the task's own instruction to document this
  choice; semantically identical (`PLACE`|`RELEASE`).
- **`HOLD_MARKER_INTEGRITY_VIOLATION_CODE` is a new error code**, not
  present in Technical Design §19.15's table (which covers only retry-
  exhaustion classification, not the integrity/collision failure mode).
  Added following the established `StorageError`-subcode pattern, per the
  task's own explicit instruction that this subcode would be needed.

None of these assumptions affects external API contracts, security,
billing, or permissions in a way requiring escalation beyond what is
documented here.

## 10. Validation Performed

Focused test results:

```
tests/unit/evidence_retention/test_marker_store.py ........... 36 passed
tests/unit/evidence_retention/test_custody_sweep_client.py .... 53 passed
tests/unit/evidence_retention/test_hold_repository.py ......... 27 passed
tests/unit/evidence_retention/test_retention_service.py ....... 14 passed
tests/unit/evidence_retention/ (full directory) ............... 216 passed
```

Full canonical regression suite (`uv run pytest -q`, no exclusion flags), as
of this implementer's own work (before the §11 Lifecycle-rule addition):

```
1663 passed, 2 skipped in 2.58s
```

Re-confirmed after the §11 Lifecycle-rule addition and its two associated
pre-existing-test updates (one net new infra-configuration test added):

```
1664 passed, 2 skipped in 4.81s
```

The 2 skips are pre-existing, unrelated to this subphase
(`tests/unit/test_infra_configuration.py` — documented, intentional skips
for Serverless-CLI-dependent checks this Python suite does not execute;
confirmed present before this subphase's changes and untouched by them).

Template validation (`cd infra && sls print --stage dev`, a local, non-deploying
config-render command): the added `retention-markers/` Lifecycle rule and its
`custom.custodyPeriodDays.retention_marker` reference resolve and fail
**exactly** like the four pre-existing rules — `Cannot resolve variable at
"...Rules.4.Expiration.Days": Value not found at "self" source`, the same
error class and message shape as `Rules.0` through `Rules.3`. This proves the
template is syntactically valid CloudFormation/Serverless YAML (a structural
error would surface differently, earlier in variable/schema resolution) and
that the new rule participates in the identical, already-established
fail-closed gate — not a special case, not a placeholder value. Full detail:
§11.

Lint (`uv run ruff check`):

```
src/release_confidence_platform/evidence_retention/  -> All checks passed!
tests/unit/evidence_retention/                        -> All checks passed!
```

A repository-wide `uv run ruff check .` reports 69 pre-existing errors
elsewhere in the codebase (confirmed, by direct grep of the output, that
none are in any file this subphase touched — all are in files this
subphase did not modify, e.g. `tests/unit/audit_platform_integrity/test_constants.py`,
`tests/unit/test_reliability_intelligence_anomaly_flagging.py`). Out of
scope for this subphase; not introduced by it.

## 11. Known Limitations / Follow-Ups

**Flagged contradiction in this subphase's own task briefing — resolved by the
orchestrator (Claude Code) after independent review, not silently.** The
implementer correctly identified a direct contradiction between two sections
of its own task briefing:

- The "Marker Lifecycle configuration — `infra/resources/s3.yml`" section
  explicitly authorized adding the Lifecycle rule ("You MAY add the
  `retention-markers/` Lifecycle rule structure, but ONLY if you can do so
  without a hardcoded duration... If you cannot add this without inventing
  a placeholder/dummy duration value, DO NOT add the rule at all").
- The "IAM boundary" section stated, in blanket terms: "Do not add or
  modify anything in `infra/serverless.yml`'s `provider.iam.role.statements`
  **or any file under `infra/resources/`**." Read literally, this forbade
  touching `infra/resources/s3.yml` at all, for any reason — including the
  Lifecycle-rule addition the other section explicitly authorized.

The implementer's own task briefing was drafted by the orchestrator in this
same session — the contradiction was a genuine drafting error (the IAM
boundary's scope was written too broadly, conflating "no new IAM permission"
with "no file under `infra/resources/`," when the two are unrelated for a
Lifecycle-rule addition that touches no IAM statement at all), not an
ambiguity in Product Strategy's own authorization, which was unambiguous:
Product Strategy's original message explicitly detailed the exact conditions
under which the rule should be added. The implementer correctly stopped and
flagged this rather than guessing.

**Resolved: the `retention-markers/` S3 Lifecycle rule was added**, by the
orchestrator, directly, after the implementer's report was received —
`infra/resources/s3.yml` gains a fifth rule (`retention-marker-disposal`),
structurally simpler than the four evidence-class rules (no tag-filter
condition, since a marker is never itself subject to legal hold), sourcing
`Days` from `custom.custodyPeriodDays.retention_marker.${self:provider.stage}`
— a new key added to `infra/serverless.yml`'s existing `custom.custodyPeriodDays`
block, left as an empty mapping for every stage, identical in pattern to the
four existing evidence-class keys. No `provider.iam` statement was touched.

**Validation performed on this addition:**
- `cd infra && sls print --stage dev` — confirmed the template resolves and
  fails **exactly** like the four pre-existing rules (`Cannot resolve
  variable... Value not found at "self" source`, for `Rules.4` alongside
  `Rules.0`-`Rules.3`) — proving this is a genuine, local (non-deploying)
  fail-closed gate, not a YAML/CloudFormation syntax error, and not a special
  case relative to the existing four rules.
- Two pre-existing tests in `tests/unit/test_infra_configuration.py` broke as
  a direct, expected consequence of adding a fifth rule and a fifth
  `custodyPeriodDays` key
  (`test_s3_lifecycle_configuration_has_one_tag_filtered_rule_per_evidence_class`,
  `test_custody_period_days_config_defines_no_value_for_any_stage`) — both
  were updated to correctly scope their existing assertions to the four
  tag-filtered evidence-class rules (unchanged in what they guarantee) and a
  new test (`test_s3_lifecycle_configuration_has_untagged_retention_marker_rule`)
  was added asserting the fifth rule's own, structurally distinct properties.
  Full suite reconfirmed green after this fix: 1664 passed, 2 skipped.

**Classification: added-and-fail-closed.**

Other limitations, none blocking:

- No CLI wiring for `rcp retention hold place|release|status` — explicitly
  out of scope for this subphase, per the task briefing.
- No positive transient-vs-non-retriable AWS error classification for the
  post-marker-confirmation sweep/reconciliation failure path — documented
  in §9 as an accepted, technically safe default (the always-resumable
  `IN_PROGRESS` branch), not a gap requiring escalation.
- `evidence_retention/marker_store.py`'s IAM logical scope
  (`s3:PutObject`/`s3:HeadObject`/`s3:GetObject` on `retention-markers/`
  only) is not enforced by a dedicated IAM role under this codebase's
  shared-role architecture — consistent with the identical, already-
  accepted caveat Technical Design §19.5.9/§12 states for
  `HoldRepository`/`CustodySweepClient`; not a new gap this subphase
  introduces.

## 12. Commit Status

Not committed, per explicit instruction. Working tree left in a clean,
complete, uncommitted state:

```
 M src/release_confidence_platform/evidence_retention/constants.py
 M src/release_confidence_platform/evidence_retention/custody_sweep_client.py
 M src/release_confidence_platform/evidence_retention/hold_repository.py
 M tests/unit/evidence_retention/test_custody_sweep_client.py
 M tests/unit/evidence_retention/test_hold_repository.py
?? src/release_confidence_platform/evidence_retention/marker_store.py
?? src/release_confidence_platform/evidence_retention/retention_service.py
?? tests/unit/evidence_retention/test_marker_store.py
?? tests/unit/evidence_retention/test_retention_service.py
?? docs/backend/legal_hold_correction_b2_s3_canary_marker_reconciliation_implementation_plan.md
?? docs/backend/legal_hold_correction_b2_s3_canary_marker_reconciliation_implementation_report.md
```

Branch: `feature/a1-lh2-s3-marker-reconciliation`, based on `main` commit
`462cf7725f5562cd122fef469d4c9a6fc4c3290b`.

---

## 0. Requirement-to-Code-and-Test Traceability

| Required behavior/component | Code | Tests |
| --- | --- | --- |
| Atomic first marker creation | `marker_store.py::MarkerStore.establish_marker` / `_attempt_put_or_reuse` (`IfNoneMatch="*"`) | `test_establish_marker_atomic_first_write_uses_if_none_match_star`, `test_establish_marker_never_calls_head_object_then_put_object_check_then_write` |
| Idempotent replay, identical content | `_validate_existing_marker` | `test_establish_marker_reuses_existing_matching_marker_on_precondition_failure`, `test_establish_marker_two_overlapping_attempts_neither_overwrites_the_other` |
| Rejection of conflicting content | `MarkerIntegrityError` in `_validate_existing_marker` | `test_establish_marker_raises_integrity_error_on_mismatched_existing_content`, `test_establish_marker_integrity_error_is_not_retried` |
| PLACE/RELEASE non-collision | `build_marker_key` (hold_version-discriminated) | `test_build_marker_key_matches_technical_design_worked_example`, `test_place_and_release_markers_of_same_episode_do_not_collide` |
| PLACE→RELEASE→PLACE episodes | `RetentionService` (reuses `HoldTransitions`' hold_id/hold_version bookkeeping) | `test_place_release_place_three_generations_no_aliasing`, `test_full_episode_place_release_place_three_distinct_markers_no_aliasing` |
| Authoritative LastModified via read-back | `establish_marker`'s dedicated `head_object` phase | `test_establish_marker_reads_back_last_modified_via_head_object_never_trusting_put_response` |
| Marker establishment timeout/failure | Bounded retry + wall-clock cap; `MarkerEstablishmentFailedError` | `test_establish_marker_raises_on_put_object_retry_exhaustion`, `test_establish_marker_raises_on_head_object_retry_exhaustion`, `test_establish_marker_fails_closed_on_wall_clock_budget_even_with_attempts_remaining`, `test_establish_marker_wall_clock_budget_shared_across_put_and_head_phases` |
| Marker status confirmation/failure persisted via HoldRepository | `RetentionService._ensure_marker_confirmed` / `_mark_event_marker_failed`; `HoldRepository.update_hold_event_marker_fields` | `test_marker_confirmed_persists_key_status_and_last_modified_on_event_and_hold`, `test_place_legal_hold_marker_establishment_failure_sets_failed_states_and_propagates`, `test_update_hold_event_marker_fields_*` (4 tests) |
| Stale re-invocation after marker disposal (no-op all the way through) | `RetentionService.place_legal_hold`/`release_legal_hold`'s `is_noop` short-circuit; `_ensure_marker_confirmed`'s CONFIRMED-reuse path | `test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e`, `test_release_legal_hold_reinvocation_after_complete_raises_and_never_touches_marker_or_sweep`, `test_resumed_place_with_confirmed_marker_never_calls_marker_store_again` |
| PLACE reconciliation racing object creation | `CustodySweepClient.reconcile_versions(legal_hold=True)` | `test_reconcile_versions_place_retags_in_window_version_not_yet_true`, `test_reconcile_versions_place_skips_version_already_tagged_true` |
| RELEASE reconciliation racing object creation (independent) | `CustodySweepClient.reconcile_versions(legal_hold=False)` | `test_reconcile_versions_release_retags_in_window_version_still_true`, `test_reconcile_versions_release_skips_version_already_false` |
| Clock-boundary / buffer defense-in-depth | Buffer filter in `reconcile_versions` | `test_reconcile_versions_just_inside_buffer_window_is_included`, `test_reconcile_versions_just_outside_buffer_window_is_excluded`, `test_reconcile_versions_skips_version_outside_buffer_window` |
| Pagination in reconciliation pass | `_list_object_versions_with_last_modified` | `test_list_object_versions_with_last_modified_yields_triples_and_paginates`, `test_list_object_versions_with_last_modified_skips_delete_markers` |
| Sweep interruption and retry | `RetentionService._run_sweep_sequence`'s `except Exception: raise` (leaves `IN_PROGRESS`) | `test_sweep_failure_after_marker_confirmed_leaves_sweep_status_in_progress`, `test_resume_after_sweep_interruption_reuses_marker_and_reaches_complete` |
| Terminal no-op at full orchestration layer | `RetentionService.place_legal_hold`/`release_legal_hold` | `test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e`, `test_release_legal_hold_reinvocation_after_complete_raises_and_never_touches_marker_or_sweep` |
| `CustodySweepClient` allowlist preservation | `_ALLOWED_S3_METHODS`/`_ALLOWED_DYNAMODB_METHODS` unchanged | `test_allowed_s3_methods_unchanged_by_reconciliation_addition`, `test_custody_sweep_client_still_has_no_put_object_or_head_object_method`, `test_call_s3_still_rejects_put_object_and_head_object` |
| Absence of unconditioned marker overwrite | No unconditional `put_object` call path exists in `marker_store.py` | `test_establish_marker_never_attempts_unconditioned_overwrite` |
| `_assert_marker_key` structural guard (positive + all required negative cases) | `marker_store.py::_assert_marker_key` | 12 tests: `test_assert_marker_key_accepts_*` (2), `test_assert_marker_key_rejects_*` (9), covering wrong prefix, missing components, mismatched client_id/audit_id/hold_id/hold_version, PLACE↔RELEASE mismatch (both directions), extra path segment, traversal-like component |

## 0.1 Marker Identity and Payload — Concrete Worked Example

Matches the companion Technical Design §19.5.1's own worked example
exactly (verified by `test_build_marker_key_matches_technical_design_worked_example`):

```
PLACE  (1st transition, hold_version=1):
  Key:  retention-markers/client_abc/audit_xyz/hold_4f5a/1-PLACE.marker
  Body: {
    "schema_version": 1,
    "client_id": "client_abc",
    "audit_id": "audit_xyz",
    "hold_id": "hold_4f5a",
    "hold_version": 1,
    "transition": "PLACE",
    "transition_id": "hold_4f5a#1#PLACE"
  }

RELEASE (2nd transition, hold_version=2, same hold_id/episode):
  Key:  retention-markers/client_abc/audit_xyz/hold_4f5a/2-RELEASE.marker
  Body: {
    "schema_version": 1,
    "client_id": "client_abc",
    "audit_id": "audit_xyz",
    "hold_id": "hold_4f5a",
    "hold_version": 2,
    "transition": "RELEASE",
    "transition_id": "hold_4f5a#2#RELEASE"
  }
```
