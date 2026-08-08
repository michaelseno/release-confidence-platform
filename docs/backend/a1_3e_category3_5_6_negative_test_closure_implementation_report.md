# Implementation Report

## 1. Summary of Changes

Implemented Evidence Governance Workstream A1.3e: added negative
regression-test coverage proving that Category 3 (operational coordination
metadata) and Category 5/6 (configuration artifacts / explicitly-excluded
audit-anchor records) write paths never receive custody/legal-hold
governance fields, per Technical Design §18.1/§18.3. This closes the last
open item in A1.3's cross-cutting write-path integration effort (issue
#95). Investigation confirmed, via direct source read of every method
under test, that none of them currently sets any governance field; this
task is a pure regression-coverage addition, not a fix — no production,
configuration, application, or infrastructure file was modified.

Test-level enforcement (not a runtime guard) is the correct mechanism here
per §18.3: these are existing, locked write methods this workstream has no
other reason to touch, and their Category 3/5/6 semantics already prevent
the governed invariant by simple omission. A regression that started
setting one of the four governance fields on any covered method would now
fail the corresponding test immediately.

## 2. Files Modified

New (2):
- `tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py`
  (22 collected tests) — `AuditMetadataRepository` (both
  `packages/`/`src/` trees), Category 6 (`AuditMetadata`, items 4a-4g, 7
  methods × 2 trees = 14 tests) and Category 3
  (`AggregationJobIntent`/`ScheduleOccurrenceClaim`, items 4h-4k, 4 methods
  × 2 trees = 8 tests).
- `tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py`
  (6 collected tests) — `AggregationRepository.put_job_once` (Category 3,
  item 6, 1 test), `put_audit_execution_identity_once` (Category 6, item
  9, 1 test), and an extension of `update_job`'s existing denylist-guard
  regression proof (§18.7) to the full 4-element governance-field set,
  parametrized over the same 4 real caller field sets
  `test_update_job_custody_guard.py` already derived from
  `aggregation/orchestrator.py` (4 tests).

Modified (1):
- `tests/unit/test_backend_s3_storage_client.py` (+57 lines; 12 → 14
  collected tests) — added `RecordingPutS3` double and 2 tests covering
  `S3StorageClient.write_json` (Category 5, `configs/*`) for both the
  create (`overwrite=False`) and force-overwrite (`overwrite=True`) paths.

Documentation, new (2, this pass):
- `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_plan.md`
- `docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_report.md`

No `src/`, `packages/`, `apps/`, `config/custody_periods.json`, or
`infra/` file was touched — confirmed by five empty `git diff main --
<path>` checks (§10 below).

## 3. API Contract Implementation

No API contract changes. No production method signature, return shape, or
externally-visible behavior was modified by this task.

## 4. Data / Persistence Implementation

No data model or storage changes. This task adds test-level verification
that the following existing write paths continue to construct
`put_item`/`update_item`/`put_object` requests that never carry
`custody_expires_at`, `ttl_disposal_at`, `evidence_class`, `hold_version`
(DynamoDB) or `rcp-legal-hold`, `rcp-evidence-class` (S3 object tags).

## 5. Key Logic Implemented

**Recording-double methodology (all three files):** each test constructs
a plain Python stub standing in for the low-level `dynamodb_client` /
`s3_client` (`put_item`/`update_item`/`put_object` methods that append
their `**kwargs` to a list and return `{}`), constructs the REAL
repository class against that stub, calls the real method under test with
a realistic, minimal argument set derived directly from reading each
method's own source, then asserts on the captured kwargs — never on the
caller's input.

**What each assertion actually inspects, precisely:**

- **PutItem-shaped calls** (`put_audit_metadata_once`,
  `put_aggregation_job_intent_once`, `claim_occurrence`, `put_job_once`,
  `put_audit_execution_identity_once`): asserts none of the four
  governance field names are keys in the captured `kwargs["Item"]`. This
  is a repository-boundary check, not a raw-wire check: `src/`'s `_call`
  additionally runs `Item` through `dynamodb_codec.encode_dynamodb_call_kwargs`
  before invoking the client (transforming each value into a low-level
  DynamoDB AttributeValue wrapper, e.g. `{"S": "..."}`), while `packages/`'s
  `_call` does not encode at all and passes the plain Python dict through
  unchanged. `encode_item` preserves top-level keys exactly — it only
  wraps each key's *value* — so a plain "is this key present" check on
  `Item` is valid and behaves identically across both trees without
  decoding. This was verified directly by reading
  `dynamodb_codec.encode_dynamodb_call_kwargs`/`encode_item`/`encode_value`,
  not assumed.
- **UpdateItem-shaped calls via `#f{i}`/`:v{i}` placeholders**
  (`set_schedules`, `update_execution_counters`, `record_finalization`,
  `record_cleanup_errors` via `_set_fields`; `update_aggregation_job_intent`,
  `update_occurrence` via inline placeholder construction;
  `update_for_force_recreate`'s dynamic optional-field block;
  `update_job`'s existing construction): asserts none of the four (or, for
  the `update_job` extension, two of the four —
  `evidence_class`/`hold_version`) governance field names appear as
  *values* in the captured `kwargs["ExpressionAttributeNames"]` dict —
  i.e. as the real attribute name a synthetic placeholder like `#f0` maps
  to. `ExpressionAttributeNames` is never touched by
  `encode_dynamodb_call_kwargs` in either tree, so this dict is identical,
  unencoded, and directly comparable across both trees.
- **`append_lifecycle_transition`**: this method's `UpdateExpression` and
  `ExpressionAttributeValues` are entirely hardcoded
  (`:next_state`/`:updated_at`/`:empty`/`:entry`/`:expected_state`) — it
  builds no `ExpressionAttributeNames` dict at all, and has no dynamic
  field-name construction of any kind. The test's assertion has two parts:
  it retains a check that none of the four governance field names appear
  as *keys* in `kwargs["ExpressionAttributeValues"]` (harmless, but on its
  own low-value here — the five hardcoded value-keys can never collide
  with a governance field name, so this half is necessarily satisfied
  regardless of the method's actual behavior), and — because this method
  has no `ExpressionAttributeNames` dict, the values-map check alone
  cannot see a governance field name hardcoded directly into the literal
  `UpdateExpression` string (e.g. a hypothetical
  `"SET ttl_disposal_at = :ttl, ..."`) — it separately captures
  `kwargs["UpdateExpression"]` and asserts none of the four governance
  field names (`custody_expires_at`, `ttl_disposal_at`, `evidence_class`,
  `hold_version`) appear anywhere in that string. This runs for both
  parametrized tree cases (`packages/` and `src/`). The `UpdateExpression`
  check, not the values-map check, is the one that actually inspects the
  sole place a governance field name could appear in this method's
  hardcoded request shape, and it was proven non-vacuous by direct fault
  injection: a hardcoded governance-field assignment was temporarily
  injected into the real production `UpdateExpression` (independently, by
  both the coordinator and QA's own official proof — QA injected
  `ttl_disposal_at` into `src/` and `hold_version` into `packages/`),
  confirmed to fail the test with the expected assertion message in both
  cases, then fully reverted.
- **`S3StorageClient.write_json`** (both new tests): captures
  `put_object(**kwargs)`. Per the task's locked, exact assertion design —
  not a broader one — the test checks `"Tagging" in kwargs` first; only if
  present does it `urllib.parse.parse_qs(kwargs["Tagging"])` and assert
  `"rcp-legal-hold"`/`"rcp-evidence-class"` are absent from the parsed
  keys. Absence of `Tagging` entirely is treated as trivially compliant,
  with no further assertion — `write_json` today never sets `Tagging` at
  all (confirmed by direct read of both `src/` and `packages/` copies,
  byte-identical for this method), so both tests currently exercise the
  "absent" branch. The test deliberately does not assert `Tagging` must be
  absent outright, per the task's explicit instruction not to
  over-constrain the method against legitimate future unrelated tagging.

**Dual-tree coverage (`AuditMetadataRepository` only):** both
`packages.storage.audit_metadata_client.AuditMetadataRepository` and
`release_confidence_platform.storage.audit_metadata_client.AuditMetadataRepository`
are exercised for every one of the 11 covered methods, via
`pytest.mark.parametrize("repo_cls", [PkgRepo, SrcRepo], ids=["packages", "src"])`
— confirmed structurally identical method sets by direct `diff` of the two
files before writing tests (the only differences are import paths, one
`preserve_client_error_codes`/exception-mapping refinement in `src/`'s
`_call`, and `src/`'s additional `encode_dynamodb_call_kwargs`/
`decode_dynamodb_response` wrapping — none of which affects the governed
key-presence assertions above). `AggregationRepository` has no equivalent
dual-tree duplication (confirmed: no `packages/aggregation/repository.py`
exists), so file 2's tests exercise the single `src/`-tree class only.

**`update_job` extension, precisely scoped:** the new parametrized test in
file 2 does not modify, weaken, or duplicate the existing
`_RETENTION_GOVERNED_FIELD_NAMES` denylist guard in
`aggregation/repository.py` (`ttl_disposal_at`/`custody_expires_at`,
raised as `AssertionError` before any DynamoDB call). It exercises the
same real `update_job` method, over the same 4 real caller field sets
`test_update_job_custody_guard.py`'s own
`test_update_job_does_not_raise_for_real_caller_field_sets` already proves
do not raise, and additionally asserts the captured
`ExpressionAttributeNames` values never include `evidence_class` or
`hold_version` — the two elements of the full four-element governance set
the existing guard does not explicitly check. The fixture itself
(`_REAL_UPDATE_JOB_CALL_FIELD_SETS`) is imported directly from
`test_update_job_custody_guard.py` (confirmed working under this repo's
`pythonpath = ["src", "."]` pytest config, verified with a standalone
`PYTHONPATH="src:." python -c` import check before relying on it in the
test file), with a locally-defined, comment-flagged fallback guarded by
`try/except ImportError` should that cross-module import path ever break.

## 6. Security / Authorization Implemented

No authentication/authorization surface is touched. This task's security
relevance is that it is the actual enforcement mechanism for the
precondition `CustodySweepClient`'s existing allowlist-free sweep design
depends on (§18.3): that Category 3/5/6 records structurally never carry
`ttl_disposal_at`/`custody_expires_at`. No test weakens, mocks around, or
disables a production security/authorization control. No secrets, tokens,
or credentials are referenced in any test fixture.

## 7. Error Handling Implemented

Not applicable — no new error-handling behavior was added or exercised
beyond the pre-existing methods' own (unchanged) error paths. All new
tests exercise only the success path of each method under test (no
`ConditionalCheckFailedException`/`ClientError` triggering was needed,
since none of the double's stub methods raise).

## 8. Observability / Logging

No logging or observability changes. No test asserts on log output.

## 9. Assumptions Made

- Per-file test counts were derived by writing the tests per the exact
  method inventory in the task brief, then letting `pytest --collect-only`
  report the true collected count rather than forcing it to a pre-stated
  target — consistent with the task's own explicit instruction to "report
  the true number." File 2 (`AggregationRepository`) collected 6 tests
  (1 + 1 + 4 parametrized cases for the `update_job` extension), not the
  task brief's initially-floated "aim for 5" — the brief explicitly
  authorized this outcome.
- `append_lifecycle_transition`'s assertion is two-part, distinct from
  every other UpdateItem-shaped assertion in this file (which checks only
  `ExpressionAttributeNames` values): it checks `ExpressionAttributeValues`
  keys (retained, but on its own insufficient — this method builds no
  `ExpressionAttributeNames` dict at all, so a governance field name
  hardcoded directly into the literal `UpdateExpression` string would
  escape a values-map-only check) and additionally checks the literal
  `UpdateExpression` string itself for all four governance field names.
  This two-part shape reflects this method's genuinely different,
  fully-hardcoded request shape, not an inconsistency with the rest of the
  file. The `UpdateExpression` check was added as a correction after an
  initial implementation pass shipped with only the values-map check;
  Product Strategy identified the gap, and the fix was proven non-vacuous
  by direct fault injection into the real production code (by both the
  coordinator and QA, independently, in both trees), confirmed to fail as
  expected, then reverted — see §5 above for the full account.
- Argument shapes passed to each method under test (e.g.
  `update_for_force_recreate`'s dependency on `item["force_history_entry"]`/
  `item["lifecycle_state"]`/`item["updated_at"]`, `append_lifecycle_transition`'s
  five required keyword-only parameters) were derived by reading each
  method's source directly, not guessed — no assumption affecting external
  behavior, data shape, security, or API contracts was required.
- No mandatory-stop-condition trigger occurred: every test passed on first
  run against the real, unmodified production methods — no method's actual
  constructed request contained a prohibited governance element. No
  production-behavior finding requiring escalation was discovered.

## 10. Validation Performed

```
uv run pytest -q tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py
22 passed in 0.20s
```

```
uv run pytest -q tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py
6 passed in 0.22s
```

```
uv run pytest -q tests/unit/test_backend_s3_storage_client.py
14 passed in 0.54s
```

```
uv run pytest -q tests/unit/aggregation/test_update_job_custody_guard.py tests/unit/reliability_intelligence/test_hold_coordination.py tests/unit/deterministic_reporting/test_repository.py tests/unit/audit_platform_integrity/test_repository.py tests/unit/audit_platform_integrity/test_engine.py
174 passed in 0.40s
```

```
uv run pytest --collect-only -q
2145 tests collected in 0.84s
```

```
uv run pytest -q
2143 passed, 2 skipped in 5.96s
```

Baseline before this change (confirmed on `main@d8e08452da0da4b0df882cd2fee88e2762b0b3e8`):
2115 collected, 2113 passed, 2 skipped. Net: **+30 collected, +30 passed,
0 skipped delta, zero regressions** — matches the sum of the three new/
modified files' own deltas exactly (22 + 6 + 2 = 30).

```
uv run ruff check tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py tests/unit/test_backend_s3_storage_client.py
All checks passed!
```

```
uv run ruff format --check tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py tests/unit/test_backend_s3_storage_client.py
3 files already formatted
```
(`test_audit_metadata_repository_no_governance_fields.py` was reformatted
once during implementation — a single line-wrap in
`_assert_expression_attribute_values_carries_no_governance_keys` — via
`uv run ruff format` before this final check; re-run after that fix
confirms all 3 files are clean.)

```
git diff --check main
(no output, exit 0 — no whitespace errors)
```

```
git status --short
 M tests/unit/test_backend_s3_storage_client.py
?? AGENTS.md
?? docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_plan.md
?? docs/backend/a1_3e_category3_5_6_negative_test_closure_implementation_report.md
?? tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py
?? tests/unit/storage/
```
(`AGENTS.md` is pre-existing, untracked, unrelated to this task — untouched.)

```
git diff --stat main
 tests/unit/test_backend_s3_storage_client.py | 57 ++++++++++++++++++++++++++++
 1 file changed, 57 insertions(+)
```
(New untracked files — the 2 new test files and the 2 new docs files — do
not appear in `git diff --stat main` since they are not yet added to the
index; this is expected and matches the equivalent A1.3d.4 report's own
documented behavior for new files.)

**All five hard-boundary scope checks confirmed empty:**

```
git diff main -- src/
(no output, exit 0)

git diff main -- packages/
(no output, exit 0)

git diff main -- apps/
(no output, exit 0)

git diff main -- config/custody_periods.json
(no output, exit 0)

git diff main -- infra/
(no output, exit 0)
```

### Test counts per file

| File | Collected tests |
|---|---|
| `tests/unit/storage/test_audit_metadata_repository_no_governance_fields.py` (new) | 22 |
| `tests/unit/aggregation/test_aggregation_repository_category3_6_no_governance_fields.py` (new) | 6 |
| `tests/unit/test_backend_s3_storage_client.py` (modified: 12 → 14) | +2 |

Total new collected test cases: **30**, matching the full-suite delta
(2145 − 2115 = 30) exactly.

## 11. Known Limitations / Follow-Ups

- Whether Category 6 (`AuditMetadata`, `AuditExecutionIdentity`) should
  ever receive a disposal mechanism of its own remains explicitly
  unresolved per Technical Design §18.1/§18.11 — this task adds no
  position on that question, only regression coverage for the current,
  governed exclusion.
- Category 4 (`LegalHold`/`LegalHoldEvent`/`DisposalRecord`) is already
  structurally excluded by method signature (no `ttl_disposal_at`
  parameter exists at all) per §18.3, confirmed by prior direct re-read —
  not re-verified or re-tested by this task, which is scoped strictly to
  Category 3/5/6.
- The `AuditMetadataRepository` dual-tree duplication itself (§18.5) —
  two independently-maintained near-duplicate implementations — remains a
  tracked, unresolved technical-debt risk, unaffected by this task; this
  task's dual-tree test coverage mitigates the narrow risk of the two
  trees *diverging on this specific governance-exclusion invariant*, not
  the broader duplication risk itself.
- Per §18.9, this negative-test coverage was originally scoped to run "in
  parallel with 18.3b-d, closing incrementally" rather than as one final
  subphase; A1.3e as executed here closes the remaining Category 3/5/6
  gap as a single trailing pass, per the task's own framing as issue #95's
  final closure item.

## 12. Commit Status

No commit was created. Per the task's explicit instructions, all changes
remain uncommitted on branch `feature/a1-3e-category3-5-6-negative-test-closure`.
Commit/push/PR are separate, later authorizations not granted in this
task.

## Explicit Exclusion Confirmation

- **No production code change**: `src/`, `packages/`, `apps/` all confirmed
  empty `git diff main`.
- **No configuration change**: `config/custody_periods.json` confirmed
  empty `git diff main`.
- **No infrastructure change**: `infra/` confirmed empty `git diff main`.
- **No runtime guard added or modified**: `update_job`'s existing
  `_RETENTION_GOVERNED_FIELD_NAMES` denylist guard is untouched — verified
  by the empty `git diff main -- src/` check above.
- **No mandatory-stop-condition trigger**: every method under test
  produced a request free of all four governance fields on first run — no
  production-behavior finding was surfaced requiring separate Product
  Strategy review.
- **QA documents owned by the independent QA pass, not this one**:
  `docs/qa/a1_3e_category3_5_6_negative_test_closure_test_plan.md` and
  `..._test_report.md` were not created by this backend implementation
  pass, per the task's explicit instruction — they were subsequently
  produced by the separate, independent QA pass and now exist as part of
  the final, completed 7-file release-readiness package for this subphase
  (3 test files + 2 backend docs + 2 QA docs). This backend pass did not
  create, modify, or otherwise touch either QA document.
- **No opportunistic refactor**: no pre-existing test file other than
  `tests/unit/test_backend_s3_storage_client.py` was modified, and that
  file's modification is purely additive (57 new lines, 0 deletions) —
  confirmed by `git diff --stat main` above.
- **No commit, no push, no PR.**
