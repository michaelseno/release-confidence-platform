# Test Plan

## 1. Feature Overview

Evidence Governance Workstream A1.3e (issue #95, the final closure item of
A1.3's cross-cutting write-path integration effort) adds negative
regression-test coverage proving that Category 3 (operational coordination
metadata), Category 5 (configuration/input artifacts), and Category 6
(explicitly-excluded audit-anchor records) write paths never receive
custody/legal-hold governance fields — per Technical Design §18.1 (six-way
governed-record classification) and §18.3 ("Structural Exclusion —
Enforceable in Code, Not Convention"). §18.3 explains why this is
test-level enforcement rather than a runtime guard: these are existing,
locked Phase 1–7 write methods this workstream has no other reason to
touch, and their Category 3/5/6 semantics already prevent the invariant by
simple omission — the only prior runtime enforcement anywhere in this
mechanism is `AggregationRepository.update_job`'s narrow, already-merged
2-field denylist guard (§18.7), which this task's tests extend the
regression *proof* of (not the guard itself) to the full 4-element
governance-field set.

This is declared, and independently confirmed by this QA pass, to be a
**test-only change**: zero production, configuration, or infrastructure
files are touched. This QA pass does not trust the implementer's
self-report (`docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_report.md`)
at face value — every claim below was independently re-derived from the
actual diff, the actual test bodies, actual production source reads, and
actual command execution, including a fault-injection sanity check proving
the new assertions are not vacuously true.

Branch under validation: `feature/a1-3e-category3-5-6-negative-test-closure`
(base `main@d8e08452da0da4b0df882cd2fee88e2762b0b3e8`).

## 2. Acceptance Criteria Mapping

- Technical Design §18.1 — six-category governed-record classification
  (Category 3: `AggregationJob`/`AggregationJobIntent`/`ScheduleOccurrenceClaim`;
  Category 5: `configs/*`; Category 6: `AuditMetadata`/`AuditExecutionIdentity`).
- Technical Design §18.3 — structural exclusion is test-level, not
  runtime-level, for Categories 3/5/6; the negative-test list is this
  precondition's actual enforcement mechanism for `CustodySweepClient`'s
  existing allowlist-free sweep design.
- Technical Design §18.5 — dual-tree hazard: `AuditMetadataRepository`
  exists as two independently-maintained implementations
  (`packages/storage/audit_metadata_client.py`,
  `src/release_confidence_platform/storage/audit_metadata_client.py`);
  both must be covered.
- Technical Design §18.6 — `configs/*` (Category 5) scope boundary;
  `S3StorageClient.write_json` must never emit `rcp-legal-hold`/
  `rcp-evidence-class` S3 tags.
- Technical Design §18.7 — `AggregationRepository.update_job`'s existing
  2-field runtime denylist guard; this task extends its regression *proof*
  to the full 4-field governance set without modifying the guard itself.
- Technical Design §18.9 — the explicit Category 3/5/6 negative-test scope
  list this task implements.
- Reference pattern: `tests/unit/aggregation/test_update_job_custody_guard.py`
  (already-merged) — recording-double methodology and the
  `_REAL_UPDATE_JOB_CALL_FIELD_SETS` fixture reused via cross-module import.

## 3. Test Scenarios (Requirement-to-Test Traceability)

| # | Requirement | Test evidence |
|---|---|---|
| 1 | Scope containment: zero `src/`, `packages/`, `apps/`, `config/custody_periods.json`, `infra/` diff vs. `main` | `git diff main -- <path>` × 5, all empty |
| 2 | File inventory: exactly 7 authorized files total (2 new test files + 1 modified test file + 2 backend docs + 2 QA docs), `AGENTS.md` untouched and excluded from the count | `git status --short` |
| 3 | `AuditMetadataRepository` Category 6 coverage: 7 methods × 2 trees = 14 tests, real repository classes from both `packages/` and `src/` trees, recording double, inspects actual `put_item`/`update_item` kwargs | Direct read of `tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py`; `uv run pytest -q` on the file |
| 4 | `AuditMetadataRepository` Category 3 coverage: 4 methods × 2 trees = 8 tests | Same file, same execution |
| 5 | Dual-tree encoding-difference claim (`src/`'s `_call` runs `encode_dynamodb_call_kwargs`, `packages/`'s does not; `encode_item` preserves top-level keys, only wraps values) is accurate | Direct read of both repository `_call` implementations and `dynamodb_codec.py::encode_dynamodb_call_kwargs`/`encode_item`/`encode_value` |
| 6 | `AggregationRepository` coverage: `put_job_once` (Category 3), `put_audit_execution_identity_once` (Category 6), `update_job` extension (4 parametrized cases, real caller field sets) — 6 tests total, purely additive to `test_update_job_custody_guard.py` | Direct read of `tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py`; `git diff main -- tests/unit/aggregation/test_update_job_custody_guard.py` (must be empty) |
| 7 | `S3StorageClient.write_json` 2 new tests use the narrowed assertion (absence of governance tag keys only if `Tagging` present, not outright `Tagging` absence) | Direct read of the 2 new tests and `_assert_write_json_put_object_carries_no_governance_tagging` in `tests/unit/test_backend_s3_storage_client.py` |
| 8 | Mandatory stop-condition: every new test genuinely exercises the real production method and would fail if a governance field leaked (not vacuously true) | Fault-injection sanity check: monkeypatch the real `sanitize()` used by `audit_metadata_client.py` to inject `ttl_disposal_at`, confirm the mirrored assertion trips |
| 9 | Category 3 preservation: 5 named pre-existing test files unmodified and still pass with unchanged counts | `git diff main -- <5 files>` (empty) + `uv run pytest -q <5 files>` |
| 10 | Full canonical suite: 2145 collected / 2143 passed / 2 skipped, net +30/+30/+0 vs. independently-confirmed `main` baseline of 2115/2113/2 | `uv run pytest --collect-only -q`, `uv run pytest -q`, plus an independent baseline re-derivation via stash + `main` checkout |
| 11 | Lint/format: zero findings on the 3 touched/created files | `uv run ruff check`, `uv run ruff format --check` |
| 12 | `git diff --check main` clean | Direct execution |

## 4. Edge Cases

- `append_lifecycle_transition`'s entirely-hardcoded `UpdateExpression`
  (no dynamic `ExpressionAttributeNames` at all) requires checking the
  literal `UpdateExpression` string itself for a governance field name, not
  only `ExpressionAttributeValues` keys — `ExpressionAttributeValues`' keys
  are always placeholder-style value names (`:next_state`, etc.), never
  real attribute names, so a regression hardcoding e.g.
  `"SET ttl_disposal_at = :ttl, ..."` directly into the expression string
  would silently escape a check that only inspected
  `ExpressionAttributeValues`. **Correction (post-initial-sign-off):** the
  first version of this test file's `test_append_lifecycle_transition_carries_no_governance_fields`
  checked only `ExpressionAttributeValues` keys and missed this gap;
  Product Strategy identified it, dev-backend added
  `_assert_update_expression_carries_no_governance_field_names` and now
  also asserts on `kwargs.get("UpdateExpression", "")`, and this QA pass
  independently fault-injection-verified the fix in both trees (§8 test
  report, "Fault-Injection Proof — `append_lifecycle_transition`").
- `S3StorageClient.write_json`'s `overwrite=False` path requires
  `head_object` to report not-found (`RecordingPutS3.head_object` raises a
  404 `ClientError`) so the call reaches `put_object` without raising
  `CONFIG_OBJECT_EXISTS` first — both the create and force-overwrite paths
  are exercised.
- Cross-module fixture reuse (`_REAL_UPDATE_JOB_CALL_FIELD_SETS` imported
  from `test_update_job_custody_guard.py`) has a `try/except ImportError`
  fallback with a locally duplicated copy — confirmed the primary import
  path actually succeeds today (fallback is dead code on this branch, not
  silently masking a broken import).
- `AggregationRepository` has no `packages/` dual-tree counterpart
  (confirmed: no `packages/aggregation/repository.py` exists) — the 6 new
  tests in file 2 correctly exercise only the single `src/`-tree class,
  not artificially parametrized across a nonexistent second tree.
- Fault-injection sanity check (not part of the shipped test suite, QA-only
  scratch verification, removed after use) — proves the "key present in
  captured kwargs" assertion style is a genuine regression tripwire, not a
  test that would pass regardless of production behavior.

## 5. Test Types Covered

- **Functional / negative regression**: all 30 new tests are negative
  assertions (field/tag absence) against real repository/client classes
  driven through recording doubles — this is the entire scope of this
  task, per §18.3's test-level-enforcement design.
- **Dual-tree regression**: `AuditMetadataRepository` parametrized across
  both `packages/` and `src/` implementations for all 11 covered methods.
- **Extension-of-existing-guard regression**: the `update_job` 4-case
  parametrized extension, reusing the existing guard test's own real
  caller field-set fixture rather than inventing new ones.
- **Methodology verification (QA-only)**: fault-injection sanity check
  confirming the new tests are not vacuously passing.
- **Regression (unchanged behavior)**: 5 named pre-existing test files
  confirmed byte-identical to `main` and passing with unchanged counts;
  full canonical suite reconciled against an independently re-derived
  `main` baseline.
- **Static analysis**: `ruff check`/`ruff format --check` on the 3
  touched/created files; `git diff --check` for whitespace/EOL hygiene.

## 6. Focused and Canonical Test Commands

Focused (this task's own new/modified surface):
```
uv run pytest -q tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py
uv run pytest -q tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py
uv run pytest -q tests/unit/test_backend_s3_storage_client.py
```

Category 3 preservation (must be unmodified and pass with unchanged
counts):
```
uv run pytest -q tests/unit/aggregation/test_update_job_custody_guard.py \
  tests/unit/reliability_intelligence/test_hold_coordination.py \
  tests/unit/deterministic_reporting/test_repository.py \
  tests/unit/audit_platform_integrity/test_repository.py \
  tests/unit/audit_platform_integrity/test_engine.py
```

Canonical (full-suite regression gate):
```
uv run pytest --collect-only -q
uv run pytest -q
```

Lint / format / diff hygiene, against the exact 3 touched/created files:
```
uv run ruff check tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py \
  tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py \
  tests/unit/test_backend_s3_storage_client.py

uv run ruff format --check <same 3 files>

git diff --check main
```

Scope-containment commands:
```
git status --short
git diff main -- src/
git diff main -- packages/
git diff main -- apps/
git diff main -- config/custody_periods.json
git diff main -- infra/
```

## 7. Scope-Containment Checks

- Working tree must show exactly the 7 authorized files, once this QA
  pass's own two documents exist:
  1. `tests/unit/test_backend_s3_storage_client.py` (modified)
  2. `tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py` (new)
  3. `tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py` (new)
  4. `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_plan.md` (new)
  5. `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_report.md` (new)
  6. `docs/qa/a1_3e_category3_5_6_negative_test_closure_test_plan.md` (new — this document)
  7. `docs/qa/a1_3e_category3_5_6_negative_test_closure_test_report.md` (new)

  `AGENTS.md` must remain untracked and untouched throughout, and is not
  one of the 7 — it is a pre-existing, unrelated file.
- `src/`, `packages/`, `apps/`, `config/custody_periods.json`, `infra/`:
  zero diff against `main` — this is the hard scope boundary of this task.
- The 5 named Category 3 preservation files: zero diff against `main`.
- `update_job`'s existing `_RETENTION_GOVERNED_FIELD_NAMES` denylist guard
  in `aggregation/repository.py`: untouched (covered by the `src/` empty
  diff above).

## 8. Baseline Reconciliation Method

This QA pass does not accept the report's "2115/2113/2 baseline" claim at
face value. It independently re-derives the baseline in-place: stash the
uncommitted branch changes (`git stash -u`), check out `main`'s tree,
run `uv run pytest --collect-only -q`, record the count, restore the
branch's uncommitted state (`git checkout <branch> -- .` + `git stash
pop`), and confirm the working tree and collection count are both
restored intact before proceeding.

## 9. Acceptance and Rejection Criteria

**Blocking (would withhold sign-off):**
- Any full-suite test failure, or any collected/passed/skipped count
  deviating from the expected 2145/2143/2 (net +30/+30/+0 vs. an
  independently re-derived 2115/2113/2 `main` baseline) without an
  explicit, reconciled explanation.
- Any non-empty diff under `src/`, `packages/`, `apps/`,
  `config/custody_periods.json`, `infra/`, or any of the 5 named Category
  3 preservation files.
- Any test that does not construct the real production repository/client
  class, or that would pass regardless of production behavior (vacuous
  test), confirmed via fault-injection sanity check.
- A `S3StorageClient.write_json` test asserting `Tagging` must be absent
  outright (the over-broad, incorrectly-designed version) instead of the
  narrowed "absent only if present" check.
- Any `ruff check`/`ruff format --check` finding on the 3 touched/created
  files, or any `git diff --check` whitespace/EOL error.
- Any modification to `AGENTS.md`, `test_update_job_custody_guard.py`, or
  `update_job`'s production runtime guard.

**Non-blocking (documented as observation, does not withhold sign-off):**
- Minor documentation-citation drift that does not affect the underlying
  mechanism's independently-verified correctness.
