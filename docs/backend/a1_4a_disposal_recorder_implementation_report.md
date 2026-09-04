# Implementation Report

## 1. Summary of Changes

Implements A1.4a `evidenceDisposalRecorder`: an event-driven Lambda that consumes DynamoDB Streams
`REMOVE` events (TTL-driven disposal of `MetadataTable` governed records) and S3 EventBridge
`Object Deleted` notifications (Lifecycle permanent-deletion of `RawResultsBucket` evidence
objects), and durably records each as a `DisposalRecord` — the compliance-facing evidence-disposal
audit trail FR-A1-5/AC-A1-6 require. Implements the full corrected architecture: ADR Decision 13
(Non-Negotiable Invariants 38–51) and Technical Design §22, as consolidated in
`docs/backend/a1_4a_disposal_recorder_implementation_plan.md` and tested per
`docs/qa/a1_4a_disposal_recorder_test_plan.md`.

Authorized by Product Strategy's Gate 5 "IMPLEMENTATION AUTHORIZED" decision. Implemented
incrementally across four dispatches on branch `feature/a1_4a-disposal-recorder`:

- **Increment 1 — core domain layer:** deterministic identity, duplicate-conflict verification,
  provenance rules, evidence-prefix restriction, six-category disposition taxonomy, `DisposalRecord`
  schema amendment (Invariant 49).
- **Increment 2 — handler + redrive CLI:** thin Lambda entrypoint, `rcp retention disposal-recorder
  redrive` command, `StageConfig` deployment-to-CLI identity configuration and validation.
- **Increment 3 — infrastructure:** dedicated IAM role, dedicated recovery bucket, CloudFormation
  Outputs, the seven-step two-pass render sequence, and the five failure planes' wiring.
- **Increment 4 — QA-gap closure:** independent QA validation found one blocking gap (missing
  TC-H2–TC-H6 batch/bisection-contract coverage) and two minor gaps (missing TC-G11, unlabeled TC-Q4);
  all three closed, independently re-verified, `[QA SIGN-OFF APPROVED]` recorded (§10, §13).

No custody-duration value was selected or introduced at any point. No deployment, AWS mutation, or
production activation occurred. Nothing has been committed.

## 2. Files Modified

### 2.1 New production/infrastructure (6 authorized + render-sequence detail)

| File | Lines | Increment |
| --- | --- | --- |
| `src/release_confidence_platform/evidence_retention/disposal_recorder.py` | 885 | 1 |
| `apps/backend/handlers/evidence_disposal_recorder_handler.py` | 176 | 2 |
| `src/release_confidence_platform/evidence_retention/disposal_recorder_redrive.py` | 316 | 2 |
| `infra/resources/evidence-disposal-recorder-iam.yml` | 150 | 3 |
| `infra/resources/evidence-disposal-recovery-bucket.yml` | 178 | 3 |
| `infra/resources/evidence-disposal-recorder-outputs.yml` | 155 | 3 |

### 2.2 Modified production/configuration/infrastructure (13 authorized)

| File | Delta | Increment |
| --- | --- | --- |
| `src/release_confidence_platform/evidence_retention/models.py` | +106 | 1 |
| `src/release_confidence_platform/evidence_retention/disposal_repository.py` | +60 | 1 |
| `infra/serverless.yml` | +166 | 3 |
| `config/custody_periods.json` | +1 key (`{}`) | 3 |
| `infra/resources/dynamodb.yml` | +20 | 3 |
| `src/release_confidence_platform/config/stage_config.py` | +188 | 2 |
| `config/stages/dev.json`, `staging.json`, `prod.json` | +6 each | 2 |
| `src/release_confidence_platform/evidence_retention/commands.py` | +103 | 2 |
| `src/release_confidence_platform/operator_cli/main.py` | +70 | 2 |
| `src/release_confidence_platform/operator_cli/result.py` | +47 | 2 |
| `infra/resources/evidence-retention-dlq.yml` | +61 | 3 |

### 2.3 New/modified tests (7 modified + 3 new, authorized — 33-file inventory)

| File | Status | Increment |
| --- | --- | --- |
| `tests/unit/evidence_retention/test_models.py` | Modified (+172) | 1 |
| `tests/unit/evidence_retention/test_disposal_repository.py` | Modified (+176) | 1 |
| `tests/unit/evidence_retention/test_disposal_recorder.py` | New (973, 72 tests) | 1 |
| `tests/unit/config/test_stage_config.py` | New (344, 35 tests) | 2 |
| `tests/unit/evidence_retention/test_disposal_recorder_redrive.py` | New (552, 15 tests) | 2 |
| `tests/unit/test_operator_cli_retention.py` | Modified (+404) | 2 |
| `tests/unit/test_operator_cli_result.py` | Modified (+142) | 2 |
| `tests/unit/test_handler_import_smoke.py` | Modified (+11) | 2 |
| `tests/unit/test_infra_configuration.py` | Modified (1479 total, +TC-G11 in Increment 4) | 3, 4 |
| `tests/unit/config/test_custody_period_config.py` | Modified (one-line schema-shape update + one new test) | 3 |

**`test_custody_period_config.py` was always part of the original 33-file inventory** (implementation
plan §5.3 item 3, "Modified tests"). It was previously and incorrectly described in this report (and
in the QA test report) as an out-of-inventory deviation — that was a mistake, corrected in this
revision. Its one-line schema-shape update plus one new test
(`test_disposal_recovery_is_rejected_as_evidence_class`) is an ordinary, authorized, in-scope
modification, not a scope exception.

### 2.4 Docs (promoted, not new)

- `docs/backend/a1_4a_disposal_recorder_implementation_plan.md` — promoted from the execution
  package (Gate 5 authorization), not a 34th inventory file.
- `docs/backend/a1_4a_disposal_recorder_implementation_report.md` — this document.
- `docs/qa/a1_4a_disposal_recorder_test_report.md` — QA sign-off record (§10).

### 2.5 Individually-authorized files beyond the original 33-file inventory (2 files, 35 total)

Exactly two files genuinely fall outside the original 33-file inventory. Both are now individually
authorized by Product Strategy — neither reflects new functional scope:

- **`tests/unit/test_operator_cli_rcp.py`** (Increment 2) — its `StageConfig(...)` fixture predated
  the four new required fields; `StageConfigLoader.load()` now correctly rejects it as incomplete.
  Fixed by adding the four fields, mirroring the identical pattern already applied in the authorized
  `test_operator_cli_retention.py`. **Explicitly authorized by Product Strategy before the edit was
  made.**
- **`tests/unit/test_evidence_disposal_recorder_handler.py`** (Increment 4, NEW file, 415 lines, 5
  tests — TC-H2 through TC-H6) — tests `EvidenceDisposalRecorderHandler`'s batch/orchestration
  behavior (the DynamoDB Streams `ReportBatchItemFailures` checkpoint-boundary contract) directly.
  This is distinct in purpose from `test_disposal_recorder.py` (the shared per-record processing
  module's own tests) and from `test_handler_import_smoke.py` (narrowly scoped to import-smoke only,
  per its own established convention across all five handlers). **This file was created during the
  QA-gap-closure increment without being disclosed as an inventory deviation at the time — a genuine
  process gap, caught by HITL review, not by this implementation's own self-report.** Product Strategy
  has since explicitly authorized it as a 35th inventory file (see the companion implementation
  plan's §5.6).

**Corrected running total: 35 files** (the original 33-file inventory, unchanged, plus these two
individually-authorized additions). No other file outside these 35 was touched.

## 3. API Contract Implementation

No new public HTTP API. New CLI surface: `rcp retention disposal-recorder redrive
--recovery-object-key <key>`, added to `operator_cli/main.py`'s existing subcommand tree, following
the identical dispatch/validation-ordering convention as the existing `retention hold` commands.
`validate_disposal_recorder_config()` is called before `AwsClientFactory` construction, per Invariant
51 (TC-G5/TC-G5-pos).

New Lambda entrypoint: `apps/backend/handlers/evidence_disposal_recorder_handler.py`, registered as
the `evidenceDisposalRecorder` function in `infra/serverless.yml`, consuming both a DynamoDB Streams
event source and an S3-Lifecycle-via-EventBridge event source.

## 4. Data / Persistence Implementation

`DisposalRecord` (`models.py`) gains seven new fields — `disposal_id_scheme`, `source_kind`,
`source_stream_identity`, `source_event_id`, `source_bucket`, `source_object_key`,
`source_object_version_id` — governed by a source-kind-conditional `model_validator` (Invariant 49):
required/forbidden fields enforced per `source_kind`, exhaustively tested per field (TC-J1–J7,
TC-J8a–c, TC-J9a–b).

`DisposalRepository.get_disposal_record`/`_get_item` gain `consistent_read: bool = False`, mirroring
`HoldRepository`'s existing pattern exactly (default `False`; `ConsistentRead=True` only when
`evidenceDisposalRecorder`'s own duplicate-conflict verification requests it). `put_disposal_record`
persists the seven new fields verbatim.

`MetadataTable`'s DynamoDB Streams ARN is now also exposed via a reinstated `MetadataTableStreamArn`
CloudFormation Output, for the operator CLI's own `StageConfig.metadata_table_stream_arn` — a
categorically distinct, external (non-CloudFormation) consumer from any same-stack reference.

## 5. Key Logic Implemented

- **Deterministic identity (Invariant 38, §22.2):** `disposal_id = "disp_v1_" + sha256(canonical_json)`
  for both source paths, computed via dedicated logic in `disposal_recorder.py` — `identity.py`'s
  existing `generate_disposal_id()` is untouched and unused by this path. Canonical JSON:
  `sort_keys=True, separators=(",", ":")`. S3-path key is hashed raw, never percent-decoded; the
  EventBridge envelope `id` is excluded from the hash input (redelivery-safe).
- **Duplicate-conflict verification (Invariant 39, §22.3):** on `ConditionalCheckFailedException`, a
  strongly-consistent read-back compares every field except `recorded_at`. An exact match resolves as
  a confirmed idempotent duplicate; any mismatch (including a source-identity-only mismatch) resolves
  as an integrity failure (disposition category f) — never a silent accept, never an overwriting
  second `PutItem`.
- **DynamoDB provenance (Invariant 40, §22.4):** five-element exact-match rule (stream identity,
  `eventName == REMOVE`, service-origin `userIdentity`, `OLD_IMAGE` presence, `OLD_IMAGE` validity).
- **S3 EventBridge provenance (Invariant 41, §22.5):** envelope/account/semver-compatibility checks,
  combined `reason`+`requester` corroboration (a `reason`-only match is never sufficient), exact
  `deletion-type` literal handling.
- **Evidence-prefix restriction and six-category disposition taxonomy (Invariants 42/43, §22.6/§22.7):**
  four recordable prefixes; `retention-markers/` excluded (valid-but-irrelevant); unrecognized prefix
  fails closed (unknown/incompatible) — never folded into the same category as an intentional
  exclusion.
- **Redrive (Invariant 45/51, §22.9.3/§22.9.5):** construction-time guarantee (recovery-bucket name
  never a CLI argument) plus six numbered runtime envelope/provenance checks, all fail-closed before
  shared processing runs; reuses the same shared per-record processing the live handler uses.
- **Five failure planes (Invariant 44, §22.8):** genuinely independently wired — plane (iii) (DynamoDB
  ESM processing failure) routes to the dedicated recovery bucket, never the DLQ; planes (i)/(ii)
  route to the DLQ; plane (v) (recovery-bucket notification failure) has its own dedicated alarm,
  distinct from plane (i)'s.
- **Least-privilege IAM (Invariant 47, §22.11):** dedicated `EvidenceDisposalRecorderLambdaRole`,
  every grant and every explicit non-grant per the approved plan, `s3:ResourceAccount` (not
  `aws:ResourceAccount`) condition, `dynamodb:ListStreams` as its own unscoped statement (AWS does not
  support narrower scoping for this action).

## 6. Security / Authorization Implemented

- Dedicated, least-privilege IAM role for the Lambda (never the shared `provider.iam.role.statements`
  block) — see §5 above and `infra/resources/evidence-disposal-recorder-iam.yml`.
- Redrive command uses the operator's own pre-existing, resolved CLI credentials exclusively — never a
  new deployable IAM role, never the Lambda's execution role (TC-I4).
- Recovery bucket: `PublicAccessBlockConfiguration` (all four flags), `aws:SecureTransport`-deny bucket
  policy, default SSE-S3 (`BucketEncryption`/`AES256`), no `VersioningConfiguration` (TC-G10).
- Operator effective-permission least-privilege policy template for `s3:GetObject` scoping (TC-I6(a))
  — **produced**, in `docs/backend/a1_4a_disposal_recorder_implementation_plan.md` §4.1, scoped to
  `s3:GetObject` on the recovery bucket's object ARN only. The REAL staging effective-permission
  evidence (TC-I6(c)) remains Gate 7's own, separately-required deliverable.
- No custody-duration numeric value introduced (grep-verified: `config/custody_periods.json`'s
  `operational_durations.disposal_recovery` remains `{}`).

## 7. Error Handling Implemented

All nine `validate_disposal_recorder_config()` checks are collected (never short-circuited) into one
`DISPOSAL_RECORDER_CONFIG_ERROR`. All six redrive runtime checks reject fail-closed before shared
processing runs. A simulated `AccessDenied`/`ClientError` on the redrive command's `GetObject` call
surfaces as an explicit, fail-closed `DisposalRedriveResult` rejection — never a silent partial
success, never an unhandled crash (TC-I6(b)).

## 8. Observability / Logging

Named CloudWatch metrics/alarms per failure plane, per the approved five-plane table: EventBridge
`InvocationsFailedToBeSentToDlq` + `evidenceDisposalRecorderDLQAlarm` (plane i);
`DestinationDeliveryFailures` (plane ii); `OnFailureDestinationDeliveredEventCount`, requiring the
`MetricsConfig: {Metrics: ["EventCount"]}` opt-in applied via `resources.extensions` (plane iii,
positive-path); `DroppedEventCount` (plane iv, silent-loss signal); dedicated
`EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm` on the recovery bucket's own
`FailedInvocations` (plane v) — explicitly distinct from plane (i)'s alarm.

## 9. Assumptions Made

Labeled clearly, none blocking, none affecting API contracts, security, or persistence shape beyond
what ADR Decision 13 / TD §22 already specify:

1. **`OLD_IMAGE` creation-timestamp field name** — TD §22.4 requires "a usable creation-timestamp-
   equivalent field" without naming one key across four heterogeneous governed record shapes.
   Standardized on `created_at` (documented inline in `disposal_recorder.py`).
2. **S3-path `disposal_mechanism` selection** — reasoned directly from TD §22.5.1: under this design's
   two-action Lifecycle rule shape, a `"Permanently Deleted"` event can only be produced by
   `NoncurrentVersionExpiration` (`Expiration` only ever produces a delete marker). Set unconditionally
   to `S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION`.
3. **DynamoDB Streams `OLD_IMAGE` decode contract** — treated as the genuine AWS Lambda
   event-source-mapping AttributeValue-wrapped shape, decoded via the existing
   `storage/dynamodb_codec.py::decode_item` helper (reuses an established codebase pattern).
4. **Lambda function/ESM logical IDs (Increment 3)** — **render-confirmed, not assumed.**
   `EvidenceDisposalRecorderLambdaFunction` and
   `EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable`, both confirmed via an actual
   local `serverless package` render against the isolated sentinel-injected harness (see §10).
5. **EventBridge rule for the S3 path (plane i) hand-authored, not framework-shorthand** — a genuine
   finding: Serverless Framework 3.40.0's native `events: - eventBridge:` shorthand derives the
   auto-generated `AWS::Events::Rule` logical ID from the function's fully-resolved, **stage-baked**
   Lambda function name (render-confirmed via a two-stage `dev`/`staging` comparison producing two
   different logical IDs for identical source). `evidence-retention-dlq.yml`'s `QueuePolicy` needs a
   single, stage-invariant `Fn::GetAtt` target across every stage — incompatible with a stage-variant
   ID. The rule and its resource-based `AWS::Lambda::Permission` are hand-authored instead
   (`EvidenceDisposalRecorderEventBridgeRule`, in `evidence-disposal-recorder-outputs.yml`), confirmed
   stage-invariant by the same two-stage render comparison, matching this codebase's own existing
   convention (`scheduler.yml`, `phase4-aggregation-iam.yml`) of hand-authoring resource-based
   permissions.
6. **`MetricsConfig`/`DestinationConfig.OnFailure` applied via `resources.extensions`, not native
   `stream`-event keys** — Serverless Framework 3.40.0 has no first-class `metricsConfig` stream-event
   key, and its `destinations.onFailure` key both restricts destination `type` to `sns`/`sqs` only and
   would incorrectly append an SQS-shaped statement to the *shared* `IamRoleLambdaExecution` role for
   any function using a dedicated role. Both properties are instead patched directly onto the rendered
   `AWS::Lambda::EventSourceMapping` resource via `resources.extensions`, using the render-confirmed
   logical ID — this is TD §22.9.5/§22.10's own documented fallback for exactly this gap.
7. **`${aws:accountId}` avoided in the IAM role's `s3:ResourceAccount` condition** — this Serverless
   Framework variable resolves against real local AWS credentials even during local `sls package`.
   Replaced with the CloudFormation intrinsic `Fn::Sub: "${AWS::AccountId}"`, which resolves natively
   without any credential dependency, is deploy-time-correct, and requires no local AWS access to
   render.
8. **A pre-existing, unrelated `s3.yml`/`custody_periods.json` interaction, found and *not* fixed** —
   `s3.yml`'s five existing Lifecycle rules already double-reference `${self:provider.stage}` (once in
   `custom.custodyPeriodDays.<class>` itself, again in the consuming expression), which is dormant only
   because every class ships `{}` today. Confirmed pre-existing (present on `main` before this branch);
   outside this increment's authorized file list; not touched. The render harness neutralizes this only
   inside its own disposable temp copy so the harness can complete a render; the real `s3.yml` is
   unmodified. **Flagged for a separate, future correction — not this subphase's scope.**

## 10. Validation Performed

Independently re-run and verified by the orchestrating session at every stage (not solely trusted from
agent self-reports). **Test-suite scope is stated precisely below — `tests/unit/` is the unit/static
acceptance subset (Gate 6's scope), not the complete repository suite; the complete suite additionally
includes `tests/api/`, `tests/integration/`, and `tests/security/` (`pyproject.toml`'s
`testpaths = ["tests"]`).**

**Unit/static acceptance suite (`pytest tests/unit/ -q`, Gate 6's own scope):**
```
2218 passed, 2 skipped, 0 failed
```
(baseline before this branch: 2124 passed, 2 skipped — net +94 passed across all four increments, 0
regressions, 0 failures)

**Complete repository suite (`pytest tests/ -q`, all of `tests/unit/` + `tests/api/` +
`tests/integration/` + `tests/security/`):**
```
2394 passed, 2 skipped, 0 failed
```
(`tests/unit/`: 2218 passed; `tests/api/`: 72 passed; `tests/integration/`: 95 passed;
`tests/security/`: 9 passed; `tests/mock_api/`: no tests collected — pre-existing, empty)

A HITL re-verification pass independently reproduced these commands and reported minor
environment-dependent skip-count variance (2215/5 and 2391/5 respectively) — acknowledged as
environment-dependent, not a discrepancy in the substantive result: zero failures in both runs, both
before and after this revision's corrections.

Increment-1-specific subset (identity/repository/domain-layer tests only):
```
pytest tests/unit/evidence_retention/test_models.py tests/unit/evidence_retention/test_disposal_repository.py \
  tests/unit/evidence_retention/test_disposal_recorder.py -q
→ 146 passed
```

Two-pass CloudFormation render: **actually executed**, not simulated. `serverless` 3.40.0 (pinned in
`infra/package-lock.json`) invoked against an isolated temp-directory copy with integer-only sentinel
values injected into a copy of `config/custody_periods.json` only — the real file is provably untouched
(`test_isolated_render_harness_never_leaks_into_real_custody_periods_json`), and a regression test
confirms packaging against the real, unmodified `config/custody_periods.json` still fails closed
exactly as before this change.

## 11. Ruff Results

**Lint (`ruff check`):** on every file touched by this implementation — **all checks passed, zero new
findings.** The repository's pre-existing 67 findings (confirmed identical count on `main` before this
branch, via direct `git stash` comparison) are unrelated to this work and untouched.

**Format (`ruff format --check`):** a HITL review found this had never been run separately from
`ruff check` (lint and format are distinct checks). Five of the seven newly-created A1.4a Python files
initially failed the repository's format check
(`disposal_recorder.py`, `disposal_recorder_redrive.py`, `test_stage_config.py`,
`test_disposal_recorder.py`, `test_disposal_recorder_redrive.py`); two did not
(`evidence_disposal_recorder_handler.py`, `test_evidence_disposal_recorder_handler.py`). Corrected via
`ruff format` targeted at exactly those five files — no unrelated baseline file was reformatted
(repository-wide `would-reformat` count dropped from 116 to 111, exactly the five files fixed, of the
pre-existing, unrelated baseline). All seven A1.4a Python files are now format-clean. Full suite
re-run after the format fix: no change in pass/fail counts (§10).

## 12. Requirement Traceability

All 22 items of TD §22.13's Future QA Acceptance Matrix have corresponding implementation code and
passing tests, per the QA plan's own 109+ TC-* mapping (Areas a–j). All 14 ADR Non-Negotiable
Invariants (38–51) are implemented and independently test-covered. Full item-by-item and invariant-by-
invariant traceability is the QA plan's own responsibility (`docs/qa/a1_4a_disposal_recorder_test_plan.md`
§2/§3) — this report does not duplicate that table. Independent QA validation against it has since been
completed: `docs/qa/a1_4a_disposal_recorder_test_report.md` records `[QA SIGN-OFF APPROVED]` (§16.6).

## 13. Known Limitations / Follow-Ups

**Resolved since this report's initial version (superseded, kept for the historical record):**
- ~~Operator least-privilege IAM policy template not yet produced~~ — produced, §6/§2.5, implementation
  plan §4.1.
- ~~`test_custody_period_config.py`'s edit not individually pre-authorized~~ — this was based on a
  factual error: the file was always part of the original 33-file inventory (§2.3) and required no
  separate authorization in the first place.
- ~~Gate 6 remains CLOSED, no `[QA SIGN-OFF APPROVED]` claim~~ — superseded. Gate 6 is now **SATISFIED**
  (`docs/qa/a1_4a_disposal_recorder_test_report.md` §16.6 — the current, authoritative sign-off; it
  supersedes an earlier §15 sign-off that was returned to CLOSED/PENDING REVALIDATION during HITL
  review and explicitly re-earned, not carried over, in §16), after one blocking finding (missing
  TC-H2–TC-H6) was caught, routed back to implementation (Increment 4), closed, and independently
  re-validated.

**Genuinely still open:**
- **Pre-existing `s3.yml`/`custody_periods.json` double-stage-reference defect** (§9, item 8) — found,
  documented, not fixed; out of this subphase's authorized scope; recommend a separate, future
  correction. Confirmed pre-existing on `main` (empty `git diff main -- infra/resources/s3.yml`).
- **Serverless Framework upgrade fragility** (§9, items 5/6) — the hand-authored `EventBridgeRule`/
  `Permission` and the `resources.extensions`-based `MetricsConfig`/`DestinationConfig.OnFailure`
  patches both depend on Serverless Framework 3.40.0's specific, documented current behavior; flagged
  by implemented architecture/security review as a non-blocking tracking item for the next framework
  version bump.
- **TC-H4's docstring** — QA's re-validation of Increment 4 found its docstring overclaims which of
  the plan's two named resolution paths it proves for the blocking record itself; the underlying
  behavior is fully proven by TC-H4 + the pre-existing TC-P3 + Gate 7 combined, but the docstring
  should be tightened to cross-reference that explicitly. Non-blocking documentation-accuracy item.
- Gate 7 (Pre-Activation Validation — real staging evidence: implemented-security re-validation,
  staging failure-plane behavioral proof, operator effective-permission evidence) remains CLOSED. No
  deployment, AWS credential use, or production activation has occurred or is authorized by this
  report.

## 14. Commit Status

**Nothing committed.** All work exists as uncommitted working-tree changes on branch
`feature/a1_4a-disposal-recorder`, off `main@dea3c191424fa67708df1d20654de5392621f3d9`. No push, no
pull request. Gate 6 is already SATISFIED (`[QA SIGN-OFF APPROVED]`, §12 above,
`docs/qa/a1_4a_disposal_recorder_test_report.md` §16.6) — the only remaining precondition for commit,
push, and PR preparation is the separate HITL release-approval gate.
