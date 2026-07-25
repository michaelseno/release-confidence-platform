# Implementation Report

## 0b. Correction Addendum 2 — A1.3b.1 Evidence-Class Persistence (2026-07-25, GitHub Issue #95)

A second, narrowly-scoped correction round, distinct from and subsequent to
the §0 packaging-gap addendum below. This round closes the gap that TD
§18.1's Category 2 table itself disclosed as left open by the original
A1.3b round: `RunMetadata`'s CREATE path persisted `custody_expires_at`/
`ttl_disposal_at` but not `evidence_class`, even though TD §18.1 requires
`evidence_class` to be persisted explicitly, as a plain DynamoDB attribute,
on every Category 2 record.

**What changed in this round, and nothing else:**

- `packages/storage/dynamodb_client.py::_run_metadata_custody_fields()` now
  also returns `"evidence_class": "raw_evidence"` in the dict it computes,
  alongside the existing `custody_expires_at`/`ttl_disposal_at` keys. The
  value is a fixed module-level constant (`_RUN_METADATA_EVIDENCE_CLASS`),
  guarded at import time by `assert _RUN_METADATA_EVIDENCE_CLASS in
  EVIDENCE_CLASSES` (imported from `evidence_retention/constants.py`) — not
  a parameter, not derived from the caller's `item` dict, not overridable by
  any caller. Because `put_started_once`'s existing merge order was already
  `{**item, **_run_metadata_custody_fields()}` (custody-fields dict second),
  the fixed value already wins over any same-named key in a caller-supplied
  `item` without any further code change — verified by a new test, not
  assumed.
- `update_terminal`'s existing code comment (previously naming only
  `custody_expires_at`/`ttl_disposal_at`) was extended to also name
  `evidence_class` as a field this method must never reference. No
  behavioral change to `update_terminal` — it already never referenced
  `evidence_class`, since it only ever writes fields explicitly present in
  the caller's `updates` dict.
- No new retry/conflict-handling logic was added. A new test
  (`test_put_started_once_repeated_call_raises_duplicate_run_id_error`)
  verifies, rather than assumes, that the existing conditional-put +
  `DuplicateRunIdError`-on-`ConditionalCheckFailedException` behavior is
  unchanged: a second `put_started_once` call for the same `run_id` is
  rejected outright, and the first-written record (including its
  `evidence_class`) is unaffected by the rejected second attempt.
- `tests/unit/test_run_metadata_custody_fields.py` gained 4 new tests
  (14 total, up from 10): `evidence_class == "raw_evidence"` on CREATE;
  `evidence_class` is a member of `EVIDENCE_CLASSES`; a caller-supplied
  `item` containing a different `evidence_class` key cannot override the
  hardcoded value; repeated CREATE raises `DuplicateRunIdError` and leaves
  the first record's `evidence_class` unaffected. The existing
  `test_update_terminal_never_touches_custody_fields` test and the existing
  fail-closed tests were extended in place (not duplicated) to also assert
  on `evidence_class`.
- `packages/storage/s3_client.py` was **not modified**. The existing
  `tests/unit/test_raw_evidence_s3_tagging.py` (3 tests) was run unmodified
  and passes, confirming the existing raw-evidence S3 tagging is unaffected
  by this round.
- No custody-period values or defaults, no environment-variable wiring
  changes, no deployment, no retroactive update or backfill/migration of any
  pre-existing `RunMetadata` record, no `AggregationRepository.update_job`
  change, no A1.3c/A1.3d (Phase 4–7) write-path work, and no change to the
  bounded `EVIDENCE_CLASSES` set — all explicitly out of scope for this
  round and confirmed untouched by `git diff --stat` (see §10-equivalent
  validation below).

**DynamoDB attribute name used: the literal string `"evidence_class"`.**
No distinct named constant for this DynamoDB attribute existed in
`evidence_retention/constants.py` prior to this round (only
`EVIDENCE_CLASS_TAG_KEY = "rcp-evidence-class"`, which is the *S3 tag key*
name used by `write_raw_results_once`'s tagging, not a DynamoDB attribute
name). `"evidence_class"` is used directly as a dict key in
`_run_metadata_custody_fields()`, matching TD §18.1's own table (which
calls the attribute `evidence_class`, not a prefixed or namespaced variant)
and matching `DisposalRecord.evidence_class`'s field name exactly in
`evidence_retention/models.py`. No new constant was added to
`evidence_retention/constants.py` for this — the existing `EVIDENCE_CLASSES`
bounded set is reused for the import-time membership assertion, but the
attribute-name literal itself was kept local to
`packages/storage/dynamodb_client.py` to avoid touching
`evidence_retention/constants.py` at all for a single-write-path,
single-value use, consistent with this round's minimal-footprint scope.

**Files touched by this round:** `packages/storage/dynamodb_client.py`
(+37/-9 lines) and `tests/unit/test_run_metadata_custody_fields.py`
(+110/-2 lines). No other file. No commit was made — the working tree is
left as-is for QA/human review, per instruction.

**Validation for this round:**

```
$ uv run pytest -q tests/unit/test_run_metadata_custody_fields.py -v
14 passed in 0.04s

$ uv run pytest -q tests/unit/test_raw_evidence_s3_tagging.py -v
3 passed in 0.02s

$ uv run pytest -q
1543 passed, 2 skipped in 2.63s
(1539 passed / 2 skipped after the prior §0 correction round; +4 new tests
= 1543. Zero regressions.)

$ uv run ruff check packages/storage/dynamodb_client.py tests/unit/test_run_metadata_custody_fields.py
All checks passed!

$ git diff --stat
 packages/storage/dynamodb_client.py            |  72 +++++++++++-----
 tests/unit/test_run_metadata_custody_fields.py | 110 +++++++++++++++++++++++--
 2 files changed, 155 insertions(+), 27 deletions(-)
```

No pre-existing `RunMetadata` record was mutated by this round: the change
is confined to `_run_metadata_custody_fields()`, called only from
`put_started_once` (the CREATE path, gated by
`ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"`);
`update_terminal` (the only other write path touching an existing record)
was not modified in behavior, only in its documenting comment. No
migration, backfill, or scan-and-update script was written or run.

## 0. Correction Addendum (2026-07-25, GitHub Issue #95)

Product Strategy authorized a narrow, precisely-bounded correction to this
subphase: the Lambda-packaging gap flagged below in §9/§11 item 2 (the
original text calling it "explicitly out of this subphase's authorized
scope") is **superseded**. That framing described the state as of the
original A1.3b round only; it does not reflect current authorization.

What changed in this correction round, and nothing else:

- `infra/serverless.yml`'s global `package.patterns` list now includes
  `'../src/release_confidence_platform/evidence_retention/**'`, alongside
  the existing `aggregation/**`, `storage/**`, `core/**`,
  `audit_lifecycle/**`, `sanitization/**` entries for the same tree. This is
  a single global list applied to all 4 Lambda functions (`coreEngineOrchestrator`,
  `scheduledExecution`, `auditFinalization`, `auditAggregation`) — there is
  no per-function packaging override in this file — so this one addition
  makes the module available to all of them.
- A new static/structural test,
  `test_serverless_package_patterns_include_evidence_retention_module` in
  `tests/unit/test_infra_configuration.py`, asserts the pattern is present
  by parsing `infra/serverless.yml` with `yaml.safe_load()` (the same
  YAML-parsing pattern A1.2 established in that file) and checking
  `package.patterns`. It does not invoke the Serverless CLI.

Traced import chain (read directly from the four handler files, not
assumed) confirming which Lambdas actually need this module:

- **`coreEngineOrchestrator`** (`apps/backend/handlers/orchestrator_handler.py`)
  — directly imports both `packages.storage.dynamodb_client.DynamoDBMetadataClient`
  and `packages.storage.s3_client.S3StorageClient` (the two files this
  subphase modified). **Needs the module.**
- **`scheduledExecution`** (`apps/backend/handlers/scheduled_execution_handler.py`)
  — directly imports both `packages.storage.dynamodb_client.DynamoDBMetadataClient`
  and `packages.storage.s3_client.S3StorageClient`, and additionally
  constructs `CoreEngineOrchestrator`. **Needs the module.**
- **`auditFinalization`** (`apps/backend/handlers/audit_finalization_handler.py`)
  — directly imports `packages.storage.s3_client.S3StorageClient` (does not
  import `packages.storage.dynamodb_client`; uses
  `packages.storage.audit_metadata_client.AuditMetadataRepository` instead,
  which does not import `evidence_retention`). **Needs the module**, via the
  `s3_client` import alone.
- **`auditAggregation`** (`apps/backend/handlers/aggregation_handler.py`)
  — imports `release_confidence_platform.storage.s3_client.S3StorageClient`
  (a distinct, unmodified file under `src/release_confidence_platform/storage/`
  — confirmed by direct comparison, not the same module as
  `packages/storage/s3_client.py`) and
  `release_confidence_platform.aggregation.repository.AggregationRepository`
  (which imports `release_confidence_platform.storage.dynamodb_codec`, not
  `packages.storage.dynamodb_client`). Grepped the full
  `release_confidence_platform/aggregation/` tree and this handler file for
  `packages.storage` imports: zero matches. **Does not need the module** —
  it only incidentally receives it because `package.patterns` is a single
  global list, exactly as `aggregation/**` is already globally included
  today even though not every function uses it (the same pre-existing
  pattern this fix follows, not a new one).

So 3 of 4 functions (`coreEngineOrchestrator`, `scheduledExecution`,
`auditFinalization`) genuinely need this module today; `auditAggregation`
gets it as an accepted incidental consequence of the existing global-list
design, not a new architectural decision introduced by this fix.

Explicitly reconfirmed untouched by this correction: no custody-period
value was introduced anywhere; `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` was not
added to `provider.environment` (§9/§11 item 1's env-var-wiring gap remains
separate, still-unauthorized, and unchanged); no other part of
`infra/serverless.yml` (functions, IAM, custom config, resources list) was
modified; `infra/resources/*.yml` was not touched; none of
`packages/storage/dynamodb_client.py`, `packages/storage/s3_client.py`, or
`src/release_confidence_platform/aggregation/repository.py` (the prior
round's already-QA-approved production code) was modified; no deployment
was performed. `git diff --stat` for this correction round shows exactly
two files changed: `infra/serverless.yml` (+1 line) and
`tests/unit/test_infra_configuration.py` (+21 lines new test).

The rest of this document (§1–§12) is the original A1.3b implementation
report, preserved as-is except where a specific statement is called out
below as superseded by this addendum.

## 1. Summary of Changes

Implemented Workstream A1.3b (GitHub Issue #95, first subphase): Category
1/2 write-path integration for Phase 1/2/3 raw execution evidence
(`RunMetadata` CREATE + raw-evidence S3 write), plus the
`AggregationRepository.update_job` retention-governed-field denylist guard
(TD §18.7). `RunMetadata`'s FINALIZATION method (`update_terminal`) is
verified and documented as never touching either custody field, per TD §11
row 2 / §18.1.

This is a code-complete, **not deployed** subphase: no infra file was
touched, `custody_period_days.raw_evidence.${stage}` remains unset in
`infra/serverless.yml`, and no CLI/`RetentionService`/Lambda handler work was
done (all out of scope, unchanged from A1.1/A1.2 status). No commit was
made; the working tree is left for QA/human review.

**A blocking operational gap is flagged below (§9/§11) — read before
merge.** As implemented, the fail-closed behavior explicitly required by
this subphase's dispatch instructions means `put_started_once` (and
therefore every ordinary orchestrator run) will raise
`CUSTODY_PERIOD_CONFIG_MISSING` in every real environment today, because no
infra change wires `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` into any Lambda's
environment. This is a deliberate, literal implementation of an explicit
instruction, not an oversight — but it needs an explicit decision before
this subphase can ship to any stage.

## 2. Files Modified

**Authorized production files (items 1/2/3 + §18.7 guard):**

- `packages/storage/dynamodb_client.py` — `put_started_once` now computes
  and merges `custody_expires_at`/`ttl_disposal_at` into a **copy** of the
  caller-supplied item (caller's own dict is never mutated) before the
  conditional `PutItem`. New module-level helpers
  `_resolve_custody_period_days_env()` and `_run_metadata_custody_fields()`,
  and the new constant `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR`.
  `update_terminal` is unchanged in behavior; a comment block was added
  documenting that it must never reference either field, per the task's
  "verify and, if necessary, add a comment" instruction.
- `packages/storage/s3_client.py` — `write_raw_results_once` now passes
  `Tagging=_RAW_EVIDENCE_TAGGING` (`rcp-legal-hold=false&rcp-evidence-class=raw_evidence`,
  URL-encoded) to `put_object`. `rcp-evidence-class` is a hardcoded module
  constant, per the task's explicit confirmation that every call site writes
  raw evidence.
- `src/release_confidence_platform/aggregation/repository.py` — `update_job`
  gains a pre-write rejection guard (`_RETENTION_GOVERNED_FIELD_NAMES`,
  `{"ttl_disposal_at", "custody_expires_at"}`) raising `AssertionError`
  before its existing `UpdateExpression` construction, exactly matching the
  TD §18.7 pseudocode shape. No existing field, caller, or behavior changed.

**New/updated test files (required coverage + regression prevention — see
§9 for why the non-authorized-file additions were necessary):**

- `tests/unit/test_run_metadata_custody_fields.py` (new) — 8 tests: custody
  fields present/correctly computed on `put_started_once`, caller's item
  dict not mutated, fields scale with configured days (not hardcoded),
  fail-closed on unset/invalid config, and a negative test proving
  `update_terminal`'s actual `ExpressionAttributeNames` never names either
  field.
- `tests/unit/test_raw_evidence_s3_tagging.py` (new) — 3 tests: correct tag
  key/value pairs on `write_raw_results_once`, evidence-class tag is fixed
  regardless of key, existing `PutObject` shape (Body/ContentType)
  preserved.
- `tests/unit/aggregation/test_update_job_custody_guard.py` (new) — 8 tests
  (5 parametrized cases + 3 direct): guard raises for each forbidden field
  individually and together, raises before any DynamoDB call, and does
  **not** raise for the four real field sets `aggregation/orchestrator.py`'s
  callers use today (read directly from that file, not guessed — job-claim/
  STARTED, execution-identity attach, the failure path, and `_complete_job`'s
  9-field call).
- `tests/conftest.py` (**new file, not one of the two authorized production
  files** — flagged explicitly, see §9) — one autouse fixture defaulting
  `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE=90` (test-only placeholder, no product
  meaning) for the whole suite, so the ~1500 pre-existing tests that
  exercise `put_started_once` indirectly (via `CoreEngineOrchestrator.run()`)
  continue to pass under the new fail-closed requirement.
- Six pre-existing test files updated **only** to add a `Tagging=None`
  parameter to fixed-signature `put_object` test doubles that would
  otherwise raise `TypeError` on the new `Tagging` kwarg — no test
  assertion or behavior in these files was changed:
  `tests/unit/test_phase1_core_engine.py`,
  `tests/integration/test_phase1_orchestrator_integration.py`,
  `tests/integration/test_phase2_orchestrator_payloads.py`,
  `tests/integration/test_phase4a7_aggregation_envelope_compatibility.py`,
  `tests/api/test_audit_run_orchestrator_observability.py`,
  `tests/security/test_phase1_qa_contracts.py`.

**Files explicitly not touched** (per dispatch scope): any Phase 4/5/6/7
write path; `evidence_retention/{hold_repository,disposal_repository,
custody_sweep_client,models,constants}.py`; `src/release_confidence_platform/storage/{dynamodb_client,s3_client}.py`
(confirmed dead-tree copies for this write path); `apps/backend/orchestrator/service.py`
and any Lambda handler. **`infra/serverless.yml` was subsequently touched by
the correction round documented in §0 above** (a single `package.patterns`
line addition, plus a new static test in `tests/unit/test_infra_configuration.py`)
— this original statement that it and "all other infra files" were
untouched applied to the original A1.3b round only and is superseded for
`infra/serverless.yml` specifically; all other infra files (`infra/resources/*.yml`,
IAM, functions, custom config) remain untouched by both rounds.

## 3. API Contract Implementation

No API contract changes. No CLI command, HTTP endpoint, or Lambda handler
signature was added or changed.

## 4. Data / Persistence Implementation

- **`RunMetadata` CREATE (`put_started_once`)**: additive fields
  `custody_expires_at` (epoch seconds, `now + custody_period_days * 86400`)
  and `ttl_disposal_at` (always equal to `custody_expires_at` on this
  unconditional CREATE path — no hold-conditional branch, since RunMetadata
  has no regeneration path per TD §18.1). Computed independently at this
  write's own time from `custody_period_days.raw_evidence.${stage}`, never
  copied from the sibling S3 write, never hardcoded.
- **`RunMetadata` FINALIZATION (`update_terminal`)**: unchanged. Verified by
  direct inspection and by a negative test that inspects the actual
  `ExpressionAttributeNames` sent to `update_item` — neither field is ever
  named.
- **Raw evidence S3 object (`write_raw_results_once`)**: additive tags only
  (`rcp-legal-hold=false`, `rcp-evidence-class=raw_evidence`); no change to
  the object body, key, or `ConditionExpression`-equivalent existence check.
- **`AggregationJob` (`update_job`)**: no field/schema change; a pre-write
  guard only.

## 5. Key Logic Implemented

- `_resolve_custody_period_days_env()` reads `os.environ.get(env_var)` fresh
  on every call (never cached, never a module-level default), requires a
  positive integer, and raises `StorageError("CUSTODY_PERIOD_CONFIG_MISSING")`
  otherwise.
- `_run_metadata_custody_fields()` computes `custody_expires_at` from
  `int(datetime.now(UTC).timestamp())` at call time — not from the item's
  own `started_at` field, to be maximally literal about "this write's own
  time" independent of the caller's dict shape.
- `put_started_once` builds `item_with_custody = {**item, **_run_metadata_custody_fields()}`
  — a new dict — rather than mutating the caller's `item` in place, since
  `apps/backend/orchestrator/service.py` retains its own reference to
  `started_item` for failure-path bookkeeping.
- `_RAW_EVIDENCE_TAGGING` is computed once at module import time via
  `urllib.parse.urlencode(...)`, matching the S3 `PutObject` `Tagging`
  parameter's documented URL-encoded-string shape (distinct from
  `put_object_tagging`'s `TagSet` list shape used by `CustodySweepClient`).
- `update_job`'s guard is a set-intersection check
  (`_RETENTION_GOVERNED_FIELD_NAMES & updates.keys()`) executed before any
  `UpdateExpression` construction, matching TD §18.7's pseudocode exactly.

## 6. Security / Authorization Implemented

No auth/authz change. Custody-period configuration is sourced exclusively
from environment at runtime (ADR Non-Negotiable Invariant 3) — no fallback
number is defined anywhere in this change. `sanitize()` is not applied to
the custody fields or tag values, consistent with `adr_sanitization_boundary.md`
(these are not client-controlled free text). The `update_job` guard is a
defense-in-depth, code-level `AssertionError` guard (not a security
boundary), mirroring the existing `_assert_phase7_sk`/`_assert_retention_sk`/
`_assert_disposal_sk` pattern.

## 7. Error Handling Implemented

- `put_started_once` raises `StorageError("CUSTODY_PERIOD_CONFIG_MISSING")`
  before any DynamoDB call when the custody-period config is unset, empty,
  non-numeric, zero, negative, or non-integer — verified the write is never
  attempted in that case (`stub.put_item_calls == []` in tests).
- `update_job` raises `AssertionError` (not `StorageError`) for a forbidden
  field, matching TD §18.7's exact pseudocode and the existing
  `_assert_*_sk`-guard convention elsewhere in this codebase (programming-
  error guards use `AssertionError`, not the domain `EngineError` hierarchy).
- No existing error path, error code, or exception type was changed.

## 8. Observability / Logging

No new structured logging was added or required by this subphase's scope
(items 1/2/3 + §18.7 guard only — `RetentionService`/CLI/Lambda logging is
out of scope). The `StorageError` message for the new fail-closed path is
descriptive and does not include client_id/audit_id/secrets.

## 9. Assumptions Made

- **Fail-closed scope, taken literally.** The dispatch instructions
  explicitly named "local/test invocation with no config" as a fail-closed
  scenario for `put_started_once`. Implemented literally: the RunMetadata
  CREATE write is refused, not degraded, when custody config is
  unresolvable. **This is a real deviation from what the companion ADR/TD
  text itself describes** — Decision 5 and the ADR's Consequences section
  describe only the S3 Lifecycle *deployment* step as gated on config
  ("Deployment of the S3 lifecycle rules is consequently gated..."); neither
  document states that the ordinary `RunMetadata`/raw-evidence write path
  should become inoperable without it. I implemented the literal dispatch
  instruction rather than silently substituting my own reading of the ADR's
  intent, and I am flagging the conflict explicitly here rather than
  resolving it unilaterally, per this role's escalation duty. **Concrete
  consequence: because no infra change wires `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE`
  into any Lambda's environment (see next bullet), every orchestrator run in
  every deployed stage will fail at the `put_started_once` call if this
  subphase is merged and deployed as-is.** This needs an explicit decision
  before merge — either accept this as an intentional gate (and sequence a
  companion infra change before deploy), or revisit the fail-closed
  requirement with Product Strategy.
- **`CUSTODY_PERIOD_DAYS_RAW_EVIDENCE` env var name and non-wiring.** No
  existing pattern was found for application code (as opposed to a Lambda
  handler at construction time) to consume a `custom.*` serverless value —
  the established pattern is handler reads `os.environ["X"]` → passes into
  a client constructor (confirmed in `orchestrator_handler.py`,
  `aggregation_handler.py`, `audit_finalization_handler.py`,
  `scheduled_execution_handler.py`). Per the task's explicit instruction not
  to invent a new wiring mechanism, I did **not** modify
  `infra/serverless.yml`'s `provider.environment` block or any handler.
  Instead, `put_started_once` reads `os.environ.get("CUSTODY_PERIOD_DAYS_RAW_EVIDENCE")`
  directly at call time — a self-contained, minimal read that requires no
  constructor or handler change, and will pick up the value automatically
  once a future, separately authorized infra change wires it in. **This is
  the flagged gap the task anticipated** — reported here rather than
  silently worked around.
- **Newly-exposed Lambda packaging gap (found during implementation, not
  anticipated in the dispatch instructions). SUPERSEDED — see §0.** Reusing
  `evidence_retention.constants` from `packages/storage/*.py` (as
  instructed) introduces the first cross-tree import from `packages/` into
  `src/release_confidence_platform/evidence_retention/`. `infra/serverless.yml`'s
  `package.patterns` allowlist previously included
  `src/release_confidence_platform/{aggregation,storage,core,audit_lifecycle,sanitization}/**`
  but **not** `evidence_retention/**`, which would have raised
  `ModuleNotFoundError` at cold start for any Lambda that packages the
  modified `packages/storage/*.py` files if deployed. **This gap is now
  fixed** — Product Strategy authorized a narrow correction (§0 above) that
  added `'../src/release_confidence_platform/evidence_retention/**'` to
  `package.patterns`. The original framing here ("an infra change,
  explicitly out of this subphase's authorized scope") applied only to the
  original A1.3b round and no longer reflects current authorization.
- **`tests/conftest.py` addition.** Not one of the two authorized production
  files. Necessary because ~66 existing call sites across 7 test files
  construct the real `DynamoDBMetadataClient`/`S3StorageClient` classes
  (not fakes of them), and the fail-closed requirement above would
  otherwise break the entire pre-existing orchestrator test suite. A single
  autouse fixture was the minimal way to satisfy "no regressions" without
  touching production handler/orchestrator files (also out of scope) to
  thread a config value through 66 call sites. The fixture's placeholder
  value (90 days) is explicitly documented as having no product meaning.
- **Six existing test files' `put_object` fakes updated.** Fixed-signature
  fakes (`def put_object(self, Bucket, Key, Body, ContentType)`) would raise
  `TypeError` on the new `Tagging` kwarg; each was given a `Tagging=None`
  default. No test assertion, fixture data, or behavior was otherwise
  changed in these files.

## 10. Validation Performed

**§0 correction round validation (2026-07-25):**

New test, standalone:

```
$ uv run pytest -q tests/unit/test_infra_configuration.py::test_serverless_package_patterns_include_evidence_retention_module -v
tests/unit/test_infra_configuration.py .                                 [100%]
1 passed in 1.87s
```

Existing focused A1.3b tests, unaffected:

```
$ uv run pytest -q tests/unit/test_run_metadata_custody_fields.py tests/unit/test_raw_evidence_s3_tagging.py tests/unit/aggregation/test_update_job_custody_guard.py -v
tests/unit/test_run_metadata_custody_fields.py ..........                [ 47%]
tests/unit/test_raw_evidence_s3_tagging.py ...                           [ 61%]
tests/unit/aggregation/test_update_job_custody_guard.py ........         [100%]
21 passed in 0.21s
```

Full suite (excluding the pre-existing PDF formatter exclusion):

```
$ uv run pytest -q --ignore=tests/unit/deterministic_reporting/test_formatters_pdf.py
1527 passed, 2 skipped in 2.32s
```

Full suite without exclusion, confirming the 12-test delta is exactly the
excluded PDF formatter file and there are zero regressions elsewhere:

```
$ uv run pytest -q
1539 passed, 2 skipped in 2.50s
```

(1538 passed / 2 skipped after the original A1.3b round; +1 new test =
1539. Zero regressions from this correction.)

`ruff check` on every file touched by this correction round:

```
$ uv run ruff check tests/unit/test_infra_configuration.py
All checks passed!
```

(`infra/serverless.yml` is not a Python file and is not a `ruff check`
target; validated separately below.)

YAML syntax validation on `infra/serverless.yml`, mirroring A1.2's
`yaml.safe_load()` pattern:

```
$ uv run python -c "import yaml; yaml.safe_load(open('infra/serverless.yml')); print('OK: infra/serverless.yml parses as valid YAML')"
OK: infra/serverless.yml parses as valid YAML
```

Scope verification for this correction round:

```
$ git diff --stat
 infra/serverless.yml                   | 1 +
 tests/unit/test_infra_configuration.py | 21 +++++++++++++++++++++
 (plus the unrelated, pre-existing uncommitted A1.3b files from the prior
 round, unchanged by this correction)
```

**Original A1.3b round validation (preserved below, unchanged):**

Full suite, after all changes (from repo root, via `uv run pytest -q`):

```
1538 passed, 2 skipped in 2.64s
```

(1517 passed / 2 skipped prior to this change; +21 new tests = 1538. Zero
regressions.)

New tests only, verbose:

```
$ uv run pytest -q tests/unit/test_run_metadata_custody_fields.py tests/unit/test_raw_evidence_s3_tagging.py tests/unit/aggregation/test_update_job_custody_guard.py -v
tests/unit/test_run_metadata_custody_fields.py ..........      [ 47%]
tests/unit/test_raw_evidence_s3_tagging.py ...                 [ 61%]
tests/unit/aggregation/test_update_job_custody_guard.py ........ [100%]
21 passed in 0.21s
```

Lint, scoped to every changed file:

```
$ uv run ruff check packages/storage/dynamodb_client.py packages/storage/s3_client.py \
    src/release_confidence_platform/aggregation/repository.py tests/conftest.py \
    tests/unit/test_run_metadata_custody_fields.py tests/unit/test_raw_evidence_s3_tagging.py \
    tests/unit/aggregation/test_update_job_custody_guard.py tests/unit/test_phase1_core_engine.py \
    tests/integration/test_phase1_orchestrator_integration.py tests/integration/test_phase2_orchestrator_payloads.py \
    tests/integration/test_phase4a7_aggregation_envelope_compatibility.py \
    tests/api/test_audit_run_orchestrator_observability.py tests/security/test_phase1_qa_contracts.py
All checks passed!
```

Repo-wide `ruff check .` reports 69 pre-existing errors, none in any file
touched by this change (confirmed by grepping the output for this change's
file list — zero matches). Not introduced by, or fixed by, this subphase.

Scope verification:

```
$ git diff --stat infra/ src/release_confidence_platform/evidence_retention/ src/release_confidence_platform/storage/
(empty — confirmed no changes to infra, evidence_retention/, or the dead-tree storage copies)
```

`update_job` real-caller-field-set verification: read
`src/release_confidence_platform/aggregation/orchestrator.py` directly
(not guessed) and confirmed the 4 call sites (job-claim/STARTED at
~L114-121, execution-identity attach at ~L144-147, failure path at
~L363-378, `_complete_job`'s 9-field call at ~L752-764) use none of
`ttl_disposal_at`/`custody_expires_at`.

## 11. Known Limitations / Follow-Ups

1. **Blocking, must resolve before deploy**: `CUSTODY_PERIOD_DAYS_RAW_EVIDENCE`
   is not wired into any Lambda's environment. Deploying this subphase as-is
   would break every orchestrator run in every stage. Requires either a
   companion infra change (out of this subphase's scope) before deploy, or a
   Product Strategy decision to soften the fail-closed requirement for this
   specific write path.
2. **RESOLVED by the §0 correction round.** `infra/serverless.yml`'s
   `package.patterns` previously did not include
   `src/release_confidence_platform/evidence_retention/**`, so the
   orchestrator, scheduled-execution, and finalization Lambdas' deployment
   packages would have been missing a module this change imports
   transitively (`ModuleNotFoundError` at cold start). The pattern has been
   added; see §0 for the traced per-Lambda need and the new static test
   guarding against regression.
3. `update_terminal` was not given a runtime `AssertionError` guard (only a
   documentation comment) since the TD does not require one for this
   specific method (only `update_job` is called out in §18.7); flagged here
   in case reviewers want parity with `update_job`'s guard.
4. No infra, `RetentionService`, CLI, or Phase 4–7 work was done — all
   correctly deferred to A1.3c/A1.3d per TD §18.9's sequencing.

## 12. Commit Status

No commit was made. The working tree is left as-is for QA/human review, per
explicit instruction.
