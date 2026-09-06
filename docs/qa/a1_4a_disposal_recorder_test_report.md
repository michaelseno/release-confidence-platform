# Test Report

## 1. Execution Summary

Independent QA validation of the A1.4a `evidenceDisposalRecorder` implementation
(branch `feature/a1_4a-disposal-recorder`), against `docs/qa/a1_4a_disposal_recorder_test_plan.md`
(the approved acceptance criteria) and `docs/backend/a1_4a_disposal_recorder_implementation_plan.md`
(the approved contract). This is Gate 6 (Post-Implementation QA Sign-off Gate) validation only —
scoped to the offline/unit/static-testable subset of the TD §22.13 matrix, per the companion plan's
§8. Gate 7 (staging behavioral validation) is explicitly out of scope here and remains separately
required before activation.

**Independent test execution (reproduced directly, not accepted from the implementation report):**

```
$ pytest tests/unit/ -q
2212 passed, 2 skipped in 43.96s
```

Matches the implementation report's claimed `2212 passed, 2 skipped` exactly.

```
$ pytest tests/unit/test_infra_configuration.py -v
48 passed, 2 skipped in 30.45s
```

```
$ pytest tests/unit/evidence_retention/test_disposal_recorder.py -v
72 passed in 0.32s
```

```
$ pytest tests/unit/evidence_retention/test_disposal_recorder_redrive.py -v
15 passed in 0.19s
```

```
$ pytest tests/unit/config/test_stage_config.py -v
35 passed in 0.03s
```

All four targeted runs match the implementation report's per-suite claims exactly (48/2 skipped,
72, 15, 35 respectively — the report's combined "146 passed" figure for
`test_models.py + test_disposal_repository.py + test_disposal_recorder.py` and "151 passed" figure
for the Increment-2 suite bundle are consistent with these individually-verified counts). **All tests
that exist, pass. This is not the basis for withholding sign-off — the basis is described in §3/§4
below: required acceptance-criteria test cases that do not exist at all.**

**QA Decision: NOT APPROVED. Blocking findings below. `[QA SIGN-OFF APPROVED]` is NOT issued.**

## 2. Detailed Results — TC-* Spot-Check Against QA Plan Specification

19 TC-* IDs across areas (c) identity, (d) duplicate-conflict, (e) provenance, (f) taxonomy,
(g) redrive, (h) batch/retry, (i) IAM, (j) Invariant 49 were independently opened in source and their
actual assertions compared line-by-line against the QA plan's own table/prose for that ID — not
merely confirmed to exist by name.

| TC | File | Verified Against Plan | Result |
| --- | --- | --- | --- |
| TC-C1 | `test_disposal_recorder.py::test_tc_c1_...` | Exact canonical-JSON byte string (`sort_keys=True, separators=(",",":")`, fields `source_kind/disposal_id_scheme/stream_identity/event_id`) asserted byte-for-byte, not "hash exists" | Match |
| TC-C2 | same file | Exact S3-path canonical JSON (`bucket/key/version_id/reason/deletion_type`, raw undecoded key) asserted byte-for-byte | Match |
| TC-C4 | same file | Two fixtures differing only in envelope `id` produce identical `disposal_id` | Match |
| TC-C5 | same file | Raw-space key vs. percent-encoded key assert **different** IDs (never percent-decoded before hashing) | Match |
| TC-D1 | same file | `ConditionalCheckFailedException` → consistent read-back → exact-match-except-`recorded_at` → confirmed duplicate; asserts `consistent_read is True` on the read-back call | Match |
| TC-D2 | same file | Two variants: disposal-fact mismatch AND **source-identity-only** mismatch with matching disposal facts, both → integrity failure, both assert the specific mismatched field name in `mismatched_fields` | Match |
| TC-D3 | same file | Comparison explicitly includes `source_stream_identity` (a source-identity field), not disposal facts alone | Match |
| TC-D4 | same file | `recorded_at` is the *only* field excluded — differing `recorded_at` alone → confirmed duplicate | Match |
| TC-E10 | same file | Two variants: `requester` wrong AND `requester` **missing** (`None`) — both → unknown/incompatible; a `reason`-only match never sufficient | Match |
| TC-E12 | same file | Three-way parametrized: `"Permanently Deleted"` → recordable, `"Delete Marker Created"` → valid-but-irrelevant, unrecognized → unknown/incompatible | Match |
| TC-F3 | same file | Unrecognized prefix → `PREFIX_CLASS_UNRECOGNIZED`, distinct return value from `PREFIX_CLASS_RETENTION_MARKER` (TC-F2) — dispositions distinguishable, not folded together | Match |
| TC-F6 | same file | Fixture ambiguous between malformed (missing version-id) and unknown (wrong bucket) resolves to unknown/incompatible per fixed precedence — precedence order asserted, not implementation-arbitrary | Match |
| TC-G2 | `test_disposal_recorder_redrive.py` | Simulated recovery-bucket body → redrive reads via `stage_config`-resolved bucket → same shared `process_dynamodb_stream_record` produces correct record | Match |
| TC-G3 | same file | Selective-conflict fake repository: one record pre-recorded, one new, in the same redriven batch; asserts the pre-recorded one resolves via duplicate-verification (`get_calls` count, not a second write) | Match |
| TC-G4 | same file | `_FakeS3Client.delete_object` raises `AssertionError` if ever called, **plus** an independent AST-level structural proof that `delete_object` is not an executable identifier anywhere in the redrive module | Match — stronger than plan requires |
| TC-G9 (checks 1–6) | same file | One negative fixture per numbered check (ESM-UUID prefix, function ARN, envelope version, stream ARN, payload shape ×2, per-record `eventSourceARN`); the check-4-passes/check-6-fails edge case (§4 Edge Cases) is explicitly present | Match |
| TC-I1/I2/I3/I5 | `infra/resources/evidence-disposal-recorder-iam.yml` (read directly, not via test) | Dedicated role; positive grants (Logs, 3 Streams actions, `ListStreams` as own `Resource:"*"` statement, `PutItem`/`GetItem` on table, `sqs:SendMessage` to DLQ, `s3:PutObject`+`s3:ListBucket` on recovery bucket with `s3:ResourceAccount` condition) all present; **no** `s3:GetObject`/`DeleteObject` anywhere in the file, **no** grant on any evidence-class prefix, **no** `Query`/`UpdateItem`/`DeleteItem` on the table; DLQ `QueuePolicy` (read directly) scoped to exactly two rule ARNs (plane i + plane v), never a blanket grant | Match |
| TC-J8a/b/c, TC-J9a/b | `test_models.py` | Each forbidden cross-source field tested as its own independent sub-ID (not merged) — DynamoDB-path record with each S3-only field individually populated, and the symmetric S3-path case — all assert `ValidationError` | Match |

No mismatch found among these 19 spot-checked IDs — where implemented, test assertions genuinely
match the QA plan's specification, several exceeding it (TC-G4's AST-level structural proof).

## 3. Failed Tests

None — every test that exists and executes, passes. The defect found by this review is an
**absence** of required tests, not a failing test. See §4.

## 4. Failure Classification — Coverage Gaps Against the Approved QA Plan

### 4.1 BLOCKING — TC-H2 through TC-H6 do not exist anywhere in the repository

**Classification: Application/Test-Suite Bug (undisclosed test-coverage gap against approved
acceptance criteria).**

**Evidence:** `grep -rniE "tc_h[2-6]\b" tests/` returns zero matches, repository-wide. Only
`test_tc_h1_dynamodb_stream_event_explicit_parameter_selection` and
`test_tc_h7_eventbridge_and_lambda_async_retry_parameters` exist in
`tests/unit/test_infra_configuration.py` — both are static-parameter infra-configuration checks
(`StartingPosition: LATEST`, batch size, `MaximumRetryAttempts`, etc., and the plane i/ii retry
constants respectively). Neither is TC-H2, TC-H3, TC-H4, TC-H5, or TC-H6.

Per the QA plan's own §2 table, item 13 ("Partial-batch/bisection contract — 5 sub-assertions (a)–(e)
… plus … same-batch redelivery") maps to `TC-H2–TC-H6`, Validation Method **"Unit, simulated
event-source-mapping behavior"** — i.e., these are unit-testable, in-scope for Gate 6 (they are not
one of the staging-behavioral-firing exclusions the plan carves out; only item 9's *behavioral-firing*
component is carved out to Gate 7, and item 13 is a wholly separate item). Per §3.8 of the plan, the
five required assertions are:

- TC-H2: the function's own returned lowest-failed-sequence-number **is** the checkpoint boundary
  directly (a simulated-ESM assertion).
- TC-H3: the next invocation's actual remaining-payload content (record identities/sequence numbers,
  not a count) matches exactly, using a **multi**-poison-record fixture.
- TC-H4: same-shard blocking, **both** resolution paths (checkpoint-advance and retry-exhaustion→
  recovery-bucket) independently asserted.
- TC-H5: cross-shard independence.
- TC-H6: same-batch redelivery of an already-successful record resolves via duplicate-verification.

`apps/backend/handlers/evidence_disposal_recorder_handler.py` itself candidly documents this gap in
its own module docstring (lines 39–52): *"Full TC-H* batch/retry-bisection coverage (Technical Design
Section 22.10/22.13 item 13) is out of this increment's own required scope … and remains a
Increment 3 / future QA closure item."* Increment 3 (infrastructure) subsequently added only the two
static-configuration checks (TC-H1/TC-H7) and never returned to close this gap. **The implementation
report does not disclose this anywhere** — §13 "Known Limitations / Follow-Ups" lists three items
(operator IAM policy template, the `test_custody_period_config.py` deviation, the pre-existing
`s3.yml` defect); the TC-H2–TC-H6 gap is not among them, and §12 "Requirement Traceability" states
*"All 22 items of TD §22.13's Future QA Acceptance Matrix have corresponding implementation code and
passing tests, per the QA plan's own 109+ TC-* mapping (Areas a–j)"* — a claim this finding shows to
be inaccurate for item 13.

**Root cause hypothesis:** the batch/retry-bisection unit-simulation work was correctly scoped out of
Increment 1/2 (both explicitly disclaim it) on the expectation Increment 3 would close it, but
Increment 3's own dispatch only implemented the infra-configuration half (TC-H1/TC-H7) and the
unit-level simulated-ESM half (TC-H2–TC-H6) was never picked up by any increment.

**Reproduction:** `grep -rniE "tc_h[2-6]\b|tc-h[2-6]\b" tests/` → no output.
`grep -rniE "bisect|lowest.failed|checkpoint|same.shard|cross.shard" tests/unit/ src/.../evidence_retention/ apps/backend/handlers/`
→ only the infra-config assertion on `bisectBatchOnFunctionError is True` and the handler's own
`batch_item_failures` construction; no simulated-ESM-behavior test exists.

**Impact/Severity: Blocking.** Item 13 is one of the corrected, load-bearing behavioral contracts of
this subphase (TD §22.10's "corrected interaction" between `ReportBatchItemFailures` and
`BisectBatchOnFunctionError" — specifically the reason this contract needed correcting in the first
place across multiple ADR rounds). Direct code inspection of
`EvidenceDisposalRecorderHandler._handle_dynamodb_streams_batch` shows the handler *does* iterate every
record in the batch and return every retry-worthy record's `SequenceNumber` in `batchItemFailures`,
which is structurally consistent with AWS's own bisection contract — but this is an unverified,
untested inference, not a QA-proven fact, and precisely the kind of claim TC-H3's own "actual
remaining-payload content, not a simplified single-poison-record model" requirement exists to force
into evidence rather than leave as code-reading confidence.

**This must be routed back to implementation** (not fixed by this QA review) to add the five missing
unit-level simulated-ESM-behavior test cases, or, if a considered decision is made that this is
infeasible to simulate without a moto/LocalStack-based harness, to explicitly flag that decision in
the test report per the QA plan's own §7 ambiguity-disclosure convention (the plan does not currently
grant this fallback for item 13 the way it grants the automation/manual-review fallback for TC-I4).

### 4.2 Non-blocking, but must be disclosed — TC-G11 has no dedicated test

**Classification: Test-Suite Bug (undisclosed coverage gap), lower severity than §4.1.**

TC-G11 ("Recursion isolation … an infra-configuration assertion confirming a recovery-bucket `Object
Created` deletion event is rejected by the EventBridge rule's own bucket-name constraint") has no
matching test. `grep -rn "TC-G11\|tc_g11" tests/` returns nothing.
`test_tc_q15b_recovery_bucket_object_deletion_never_reaches_s3_handler` in
`test_disposal_recorder.py` covers the related **application-level** defense-in-depth check (the
handler rejects a recovery-bucket-sourced event if one ever reached it), but TC-G11 specifically asks
for the **infra-configuration** proof that the plane-(i) `EventBridgeRule`'s own `EventPattern.detail
.bucket.name` is scoped to `RawResultsBucket` only, never the recovery bucket — this is the primary
enforcement layer TC-Q15b's own comment describes as "defense-in-depth; primary enforcement is the
EventBridge rule's own bucket-name constraint (infra scope)." No test in `test_infra_configuration.py`
asserts this. Direct read of `infra/resources/evidence-disposal-recorder-outputs.yml` confirms the
rule's `EventPattern.detail.bucket.name` is in fact correctly scoped to
`${self:custom.rawResultsBucketName}` only — so the underlying infrastructure is correct — but this is
QA-verified by direct file read in this review, not by any test in the delivered suite.

### 4.3 Minor, traceability-only — TC-Q4-a..e not present under that label

**Classification: Test-Suite Bug (labeling/traceability gap), informational severity.**

`grep -rn "tc_q4\|TC-Q4" tests/` returns no test-function hits. §2 item 4 of the QA plan
("Real S3 EventBridge fixtures … account, `detail["event-version"]`, `detail.requester`; semver
MAJOR/MINOR positive/negative; combined `reason`+`requester` negative") maps to `TC-Q4-a..e`.
`test_disposal_recorder.py`'s own module docstring lists which §2 acceptance-matrix rows it covers
("items 1-8, 15, 16, 17") but its own enumerated `TC-Q*` list skips `TC-Q4` entirely — an internal
inconsistency in the file's own header claim. The **substance** of item 4 is functionally covered
under different IDs: `test_tc_e7_mismatched_account_is_unknown_incompatible`,
`test_tc_e8_major_version_mismatch_is_unknown_incompatible` (+3 more `TC-E8` variants), and
`test_tc_e10_reason_correct_requester_wrong_is_unknown_incompatible` (+1 `TC-E10` variant) exercise
the identical account/semver/reason+requester assertions item 4 requires. Unlike TC-Q12's explicit,
documented cross-reference to TC-G10, no equivalent cross-reference statement exists in the plan or
report tying TC-Q4 to TC-E7/E8/E10 — so while the functional gap is effectively closed, the
traceability gap is real and should be corrected (either by adding the cross-reference note to the
plan, consistent with its own Option-B convention, or by renaming/aliasing).

## 5. Custody-Duration Hardcode Check (Task Item 3)

**Verified — no violation.** `git diff -- infra/ config/` filtered for any line containing
`Days:`/`NoncurrentDays`/`custody`/`retention`/`expir`/`disposal_recovery` shows every duration
reference is a variable/file lookup, never a literal:

- `config/custody_periods.json`: only `"disposal_recovery": {}` added — an empty object, no value.
- `evidence-disposal-recovery-bucket.yml`'s `Expiration.Days` resolves to
  `${self:custom.custodyPeriodDays.disposal_recovery.${self:provider.stage}}` — a variable reference
  chain terminating at the still-empty JSON key above; if unset, Serverless Framework variable
  resolution fails closed at package time (confirmed by
  `test_serverless_print_fails_on_unresolved_custody_period_config_file_references`, which passed in
  this review's independent run).
- `infra/serverless.yml`'s new `custom.custodyPeriodDays.disposal_recovery` entry is itself the same
  `${file(...)}` lookup, not a literal.

No numeric custody-duration value is introduced. **Pass.**

## 6. Least-Privilege IAM Check (Task Item 4)

**Verified — no violation**, via direct read of `infra/resources/evidence-disposal-recorder-iam.yml`
(reproduced in full in this review). Contains exactly the grants TC-I1/I2/I3/I5 specify: dedicated
role, the six documented positive-grant statements (Logs; 3 Streams-read actions scoped to the stream
ARN; `ListStreams` as its own `Resource:"*"` statement; `PutItem`/`GetItem` scoped to the table;
`sqs:SendMessage` scoped to the DLQ ARN; `s3:PutObject`+`s3:ListBucket` scoped to the recovery bucket
with the `s3:ResourceAccount` condition) — and nothing else. No `s3:GetObject`, no `DeleteObject`, no
grant referencing any evidence-class prefix (`raw-results/`, `intelligence/`, `reports/`,
`integrity/`), no `Query`/`UpdateItem`/`DeleteItem` on the table anywhere in the file. **Pass.**

## 7. Five Failure-Plane Wiring Check (Task Item 5, Invariant 44)

**Verified — no violation**, via direct read of `infra/serverless.yml`'s `evidenceDisposalRecorder`
function block, `infra/resources/evidence-disposal-recorder-outputs.yml`, and
`infra/resources/evidence-retention-dlq.yml`:

- Plane (ii) (Lambda async-invoke failure): `serverless.yml`'s function-level
  `destinations.onFailure` → `evidenceDisposalRecorderDLQ`. Never the recovery bucket.
- Plane (i) (EventBridge→Lambda delivery failure): the hand-authored
  `EvidenceDisposalRecorderEventBridgeRule`'s `Targets[0].DeadLetterConfig`/`RetryPolicy` →
  `evidenceDisposalRecorderDLQ`. Never the recovery bucket.
- Plane (iii) (DynamoDB ESM processing failure): `resources.extensions` on
  `EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable` sets
  `DestinationConfig.OnFailure.Destination` → `Fn::GetAtt: [EvidenceDisposalRecoveryBucket, Arn]`.
  **Never** `evidenceDisposalRecorderDLQ` — confirmed both by direct file read and independently by
  the actual rendered-template assertion in
  `test_isolated_render_harness_confirms_plane_i_and_plane_iii_wiring` (reproduced in this review,
  passing — see §9).
- `evidence-retention-dlq.yml`'s `QueuePolicy` is scoped to `ArnEquals: aws:SourceArn` naming exactly
  two rule ARNs — the plane-(i) rule and the plane-(v) recovery-bucket notification rule — never a
  blanket grant, and never the recovery bucket's own bucket policy admitting anything back to the DLQ.

Plane (iii) routes only to the recovery bucket, never the DLQ; planes (i)/(ii) route only to the DLQ,
never the recovery bucket. Invariant 44's core requirement is genuinely, independently satisfied.
**Pass.**

## 8. Scope-Deviation Review (Task Item 6)

**`tests/unit/test_operator_cli_rcp.py`** — diff reproduced directly: 10 lines added to one existing
`StageConfig(...)` fixture, adding the four new required fields with realistic placeholder values.
Nothing else in the file is touched. Genuinely minimal and mechanical, matching the report's
characterization; pre-authorized per the report. **No concern.**

**`tests/unit/config/test_custody_period_config.py`** — diff reproduced directly. Two changes: (1) one
existing assertion (`payload["operational_durations"] == {"retention_marker": {}}`) extended to
include the new, still-empty `disposal_recovery` key — a direct, unavoidable consequence of
`config/custody_periods.json` gaining that key, which is itself item 4 of §5.1's inventory of modified
production/configuration/infrastructure files; (2) one new test,
`test_disposal_recovery_is_rejected_as_evidence_class`, that exactly mirrors the pre-existing,
unmodified `test_retention_marker_is_rejected_as_evidence_class` test one key over, asserting the
identical `CustodyPeriodConfigLoader` rejection behavior for the new key. Neither change introduces new
functional scope, a new code path, a new fixture pattern, or touches anything outside this one file.

**Correction (this validation pass):** this document's original text above characterized this file's
inventory status as uncertain — describing it as something that "should ideally have been listed in the
original 33-file inventory" and treating its inclusion as "an oversight in the original inventory." That
characterization was itself the error, not the file's status. `tests/unit/config/test_custody_period_config.py`
**was already listed in the original 33-file inventory from the very beginning** — implementation plan
§5.3, item 3, "Modified tests." There was never any ambiguity, missing authorization, or process gap
regarding this file; it required no separate authorization because it was in-scope from the original
plan. This is a genuinely different situation from `tests/unit/test_operator_cli_rcp.py` and
`tests/unit/test_evidence_disposal_recorder_handler.py` (§11 and §15.6 below), which are outside the
original 33-file inventory and required individual post-hoc authorization. **Independent judgment: this
file's modification is unavoidable, mechanical test-fixture maintenance consequential to the always-
authorized `config/custody_periods.json` schema change — not scope creep, and not a deviation of any
kind.** No concern.

## 9. Render-Confirmation Check (Task Item 7)

**Independently reproduced.** `infra/node_modules/.bin/serverless --version` confirms `serverless
3.40.0` is present locally (matching `infra/package-lock.json`'s pin). Re-running
`pytest tests/unit/test_infra_configuration.py -v` in this environment executed the full isolated
render harness (real `npm ci` + real `serverless package --stage dev` into a temp directory, sentinel
injected into a throwaway copy of `config/custody_periods.json`, real file provably untouched) and both
render-confirmation tests **passed** (not skipped):

- `test_isolated_render_harness_confirms_disposal_recorder_outputs` — asserts
  `EvidenceDisposalRecorderFunctionArn`'s `Fn::GetAtt` target equals the literal string
  `"EvidenceDisposalRecorderLambdaFunction"`, present in `Resources:` with
  `Type: AWS::Lambda::Function`; and `EvidenceDisposalRecorderEventSourceMappingUuid`'s `Ref` target
  is present with `Type: AWS::Lambda::EventSourceMapping`.
- `test_isolated_render_harness_confirms_plane_i_and_plane_iii_wiring` — asserts, against the same
  real render, that the ESM's `DestinationConfig.OnFailure.Destination` is
  `{"Fn::GetAtt": ["EvidenceDisposalRecoveryBucket", "Arn"]}`.

This independently confirms the implementation report's Assumption 4 claim — the two logical IDs are
genuinely render-confirmed in this reviewer's own environment, not merely reported. **Confirmed, not
merely trusted.**

## 10. Assumptions Review (Task Item 8)

All 8 assumptions in the implementation report's §9 were checked for (a) reasonableness, (b) whether
they narrow or violate an ADR invariant, and (c) whether they are genuinely labeled in code, not only
in the report.

| # | Reasonable | Violates an Invariant | Labeled in code |
| --- | --- | --- | --- |
| 1 (`created_at` field name) | Yes — TD leaves the exact key unnamed | No | Yes — `disposal_recorder.py` lines ~250–269, "Assumption requiring confirmation" comment |
| 2 (`S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION`) | Yes — reasoned directly from the two-action Lifecycle rule shape | No | Yes — inline comment at the assignment site |
| 3 (`decode_item` reuse) | Yes — reuses an established codec | No | Yes — docstring cites the helper explicitly |
| 4 (render-confirmed logical IDs) | Yes | No | Yes, and independently reproduced — see §9 |
| 5 (hand-authored EventBridge rule) | Yes — a genuine, render-proven Serverless Framework limitation, not a preference | No | Yes — extensive comment in both `serverless.yml` and `evidence-disposal-recorder-outputs.yml` |
| 6 (`resources.extensions` for `MetricsConfig`/`OnFailure`) | Yes — documented TD fallback for a confirmed framework gap | No | Yes — comment block in `serverless.yml`'s event definition and in the `extensions:` block itself |
| 7 (`Fn::Sub: "${AWS::AccountId}"` over `${aws:accountId}`) | Yes — avoids a local-credential dependency during render | No | Yes — extensive comment in `evidence-disposal-recorder-iam.yml` |
| 8 (pre-existing `s3.yml` double-stage-reference defect, not fixed) | Yes — correctly scoped out of this subphase; found and disclosed rather than silently worked around | No — explicitly not this subphase's invariant to enforce | Yes — report §9 item 8; the harness's own neutralization is scoped to its disposable temp copy only, confirmed by the file's own `_neutralize_preexisting_double_stage_suffix_defect` helper in `test_infra_configuration.py` |

All 8 pass review. **No concern.**

## 11. Inventory Confirmation (Task Item 9)

`git status --porcelain` reproduced (see raw output above, Bash history) shows 21 modified + 9 new
tracked files, plus `AGENTS.md` (pre-existing untracked, unrelated). Cross-checked against the
implementation plan's §5 33-file inventory: 20 of the 21 modified files match §5.1 items 1–11 (with the
three `config/stages/*.json` files correctly not double-counted against the plan's file-count
convention) and §5.3 items 1–7; all 9 new production/test files match §5.2/§5.4; and the 4 docs items
match §5.5 (2 already-produced planning docs + this implementation report + this test report).

The 21st modified file, `tests/unit/test_operator_cli_rcp.py`, is **outside** the original 33-file
inventory — its `StageConfig(...)` fixture required a minimal, mechanical 4-field update as a direct
consequence of the authorized `StageConfig` schema change (§8 above). At the time of this original
review, it was already disclosed as a reviewed deviation (§8) but had not yet been formally
individually authorized as an inventory addition — that formal authorization is recorded later, see
implementation plan §5.6.

**No file outside the original 33-file inventory or this one disclosed/reviewed deviation was touched.
Pass**, with the deviation itself carrying no concern per §8's independent review above.

## 12. Observations

- Every test that exists passes; there is no flakiness, no regression, and no failing test anywhere in
  the delivered suite. The defect this review identifies is a **completeness** defect — required
  acceptance-criteria coverage that was never written — not a correctness defect in what was written.
- The implementation code itself, where independently read (handler dispatch, IAM role, failure-plane
  wiring, custody-duration sourcing, redrive envelope checks), appears structurally sound and consistent
  with the approved design in every area this review inspected. The TC-H2–TC-H6 gap in particular means
  this confidence is not yet QA-proven for the batch/retry-bisection contract specifically — the design
  reads correctly, but the QA plan's own required simulated-ESM proof does not exist to confirm it.
- The implementation report is otherwise highly accurate: every reproduced test count, the ruff
  baseline, the render-confirmation claim, and the custody-duration-hardcode claim all independently
  verified exactly as reported. The one place the report overstates its own coverage is §12's traceability
  claim, addressed in §4.1.

## 13. Regression Check

Full suite: `2212 passed, 2 skipped` — independently reproduced exactly matching the implementation
report's claimed figures and its claimed baseline delta (+88 over the 2124/2-skipped pre-branch
baseline). No regression found in any pre-existing test. `ruff check` on the touched/new production and
test files (20 files, checked directly, excluding the pre-existing `operator_cli/main.py`
import-sort/line-length findings independently confirmed pre-existing via `git stash` baseline
comparison) shows zero new findings.

## 14. QA Decision

Two of the three necessary conditions for `[QA SIGN-OFF APPROVED]` are met: every automated test
passes, and no regression was found. The third — **complete acceptance-criteria coverage** — is not
met. §22.13 item 13 (TC-H2 through TC-H6, five of the plan's 109 approved TC-* IDs, covering the
partial-batch/bisection contract's core corrected behavior) has zero implementing tests anywhere in
this repository, is not disclosed as a known limitation in the implementation report, and directly
contradicts that report's own §12 traceability claim. A secondary, lower-severity gap (TC-G11) and a
traceability-only gap (TC-Q4 labeling) are also identified in §4.2/§4.3 and should be closed in the
same pass.

This is a blocking finding under this project's QA Gate: acceptance criteria this document itself
established as Gate-6, offline/unit/static-testable, in-scope requirements are not met. Per this
review's own constraints, these gaps are not fixed here — they are routed back to implementation
(`dev-backend`) to add the missing TC-H2–TC-H6 and TC-G11 test cases (or, for TC-H2–H6, to make and
explicitly document a considered infeasible-to-automate determination, consistent with the QA plan's
own §7 disclosure convention, if that is the genuine outcome), and to add the TC-Q4 cross-reference
note. Re-validation of the newly-added tests (not a full re-run of everything already independently
verified in this pass) is the required next QA step once that work lands.

**No sign-off is issued. `[QA SIGN-OFF APPROVED]` is NOT recorded by this report at this point in
the review.**

---

## 15. Follow-Up Re-Validation (Increment 4 — Closure of §4.1/§4.2/§4.3 Gaps)

Targeted re-validation of the delta only (`tests/unit/test_evidence_disposal_recorder_handler.py`
new, `tests/unit/test_infra_configuration.py` TC-G11 addition, `tests/unit/evidence_retention/
test_disposal_recorder.py` TC-Q4 labeling). The rest of this document's original validation (§1–§14)
stands and was not repeated.

### 15.1 Independent test execution (reproduced directly in this pass)

```
$ pytest tests/unit/test_evidence_disposal_recorder_handler.py -v
5 passed in 0.40s
```
All 5 (TC-H2, TC-H3, TC-H4, TC-H5, TC-H6) pass.

```
$ pytest tests/unit/test_infra_configuration.py -q
49 passed, 2 skipped in 34.03s
```
+1 vs. the §9 baseline of 48 passed — consistent with the single new TC-G11 test.

```
$ pytest tests/unit/ -q
2218 passed, 2 skipped in 47.92s
```
+6 vs. the §1 baseline of 2212 passed — consistent exactly with 5 new handler tests (TC-H2–H6) + 1
new infra test (TC-G11); TC-Q4's closure added no new test (docstring/comment-only, confirmed §15.4).
No regression: 0 failures, skip count unchanged at 2.

### 15.2 TC-H2–TC-H6 — assertion-match findings against QA plan §3.8

Each test's actual body and assertions were read in full and compared against the plan's own §3.8
table row for that ID (not merely confirmed to exist).

| TC | Plan requirement (§3.8) | Test as implemented | Verdict |
| --- | --- | --- | --- |
| TC-H2 | Returned lowest-failed-sequence-number **is** the checkpoint boundary directly, not a single-poison simplification | 4-record batch, 2 poison at seq 200 and 150 (150 numerically lower but later in iteration order) — asserts returned failure-identifier set is exactly `{"200","150"}`, good records never reported, and `min(failed_ids, key=int) == "150"` — proves the boundary is a genuine minimum computation, not "first encountered" | **Match** |
| TC-H3 | Multi-poison-record fixture; next invocation's actual remaining-payload content (identities, not count) matches boundary-onward exactly | 6-record batch, 3 poison (20/40/50) interleaved with good records — asserts exact failing-identity set + length (rules out a folded/counted result), computes boundary=20, and asserts the reconstructed next-batch event-ID sequence equals `["evt-20","evt-30","evt-40","evt-50","evt-60"]` exactly | **Match** |
| TC-H4 | Same-shard blocking, **both** resolution paths: (i) checkpoint-advance via well-formed subsequent response, (ii) retry-budget exhaustion → routes to recovery bucket — assert both | See §15.3 below — **not a clean match to the plan's literal two named paths**, but not a fabricated or absent test either. Classified as a minor, non-blocking documentation/traceability gap, not a coverage gap — see §15.3 for the reasoning. |
| TC-H5 | Cross-shard independence | See §15.3 — **honestly self-scoped**, not overclaiming | **Match, honestly scoped** |
| TC-H6 | Same-batch/next-invocation redelivery of an already-successful (later-sequence) record resolves via duplicate-verification, never a duplicate write/error | Prior invocation succeeds on seq 500 only; subsequent batch redelivers seq 500 (good) alongside a newly-failing seq 300 (poison, earlier in sequence) — asserts only seq 300 reported as failure, `successful_put_count` stays at 1 (no re-write), and the duplicate-verification read-back genuinely occurred (`consistent_read is True`) | **Match** |

### 15.3 TC-H5 honesty judgment (specifically requested) and the related TC-H4 finding

**TC-H5 verdict: honestly scoped, not oversold, not undersold.** The test's docstring explicitly and
correctly states what a unit test can and cannot prove for cross-shard independence: DynamoDB
Streams' per-record payload shape carries no field naming which shard a record originated from, and
shard fan-out is entirely the ESM's own runtime behavior (`ParallelizationFactor`), not something
`handler.handle()` can be made to exercise. The test then asserts exactly the narrower, genuinely
unit-testable property it says it will (an unrelated, independently-succeeding record's outcome is
never altered, dropped, or folded into a failing record's `batchItemFailures` entry merely by batch
co-membership) and its own body backs this precisely: 1 poison + 1 unrelated good record in a single
batch, asserting the good record's `successful_put_count`/`put_calls` entry is genuinely present and
untouched by the poison record's failure. It correctly labels this a "necessary but not sufficient"
precondition for the real cross-shard claim and defers the full claim to Gate 7. This is the same
disclosure discipline this document's own §4.1 finding demanded — applied correctly here.

**TC-H4, by contrast, does not apply the same disclosure discipline, though the underlying gap is
non-blocking.** Read independently against §3.2 of this plan (Area (b), plane (iii)), the "(ii) …
routes to the recovery bucket" resolution path named in TC-H4's row is **not actually TC-H4's proof
obligation** — it is explicitly, separately assigned to `TC-P3-pos`/`TC-P3-neg`
(`test_tc_p3_plane_iii_dynamodb_esm_failure_routes_to_recovery_bucket_never_dlq`, a pre-existing,
already-passing Increment 3 infra-configuration test), with the real behavioral proof of routing
under a genuine retry-exhaustion condition explicitly deferred to Gate 7 per §3.2(A)/(B) — this
document's own established split for exactly this kind of AWS-runtime-only behavior. TC-H4's own
docstring, however, does not state this cross-reference; instead it silently redefines "both
resolution paths" as "(a) already-succeeded record resolves via duplicate-verification on
redelivery" and "(b) a still-failing record is reported again on retry," and its closing line —
"Both resolution paths … proven" — reads as a stronger claim than what is actually shown, since
neither assertion demonstrates the *blocking record itself* resolving via either of the plan's two
literal named paths. Substantively, (b)'s "fails a second time, still reported" is a legitimate,
necessary unit-level precondition for the real retry-exhaustion→recovery-bucket path (the record
must continue failing consistently for AWS to ever exhaust its retry budget), and the plan's own
existing TC-P3 + Gate 7 already supply the rest of that specific proof chain — so the underlying
behavior is genuinely proven end-to-end by the combination of TC-H4 + TC-P3 (already independently
verified passing, §9) + the Gate 7 requirement already on record in this document (§3.2(B)) — it is
not a coverage absence. What is missing is the explicit cross-reference statement TC-H5 provides and
this plan's own convention elsewhere requires (e.g. `TC-Q12`'s explicit cross-reference to `TC-G10`
rather than silently duplicating or silently narrowing scope).

**Classification: minor, non-blocking, traceability/disclosure gap — same severity class as the
original §4.3 TC-Q4 finding, not the same severity as the original §4.1 TC-H2–H6 absence finding.**
Recommended (not required for sign-off): tighten TC-H4's docstring to explicitly cross-reference
`TC-P3` + Gate 7 for path (ii), mirroring TC-H5's own disclosure, and soften "Both resolution paths …
proven" to state precisely what is and is not proven at the unit level — consistent with this
project's "explainable by default … no unverifiable conclusions" principle. This does not block
sign-off because the underlying behavior is not actually unproven; it is proven elsewhere in this
plan's own already-approved structure, and the gap is a documentation-accuracy issue, not a
functional-coverage absence.

### 15.4 TC-G11 finding

`test_tc_g11_eventbridge_rule_bucket_name_constraint_never_names_recovery_bucket`
(`tests/unit/test_infra_configuration.py:1070`) reads `infra/resources/
evidence-disposal-recorder-outputs.yml` directly and asserts
`Resources.EvidenceDisposalRecorderEventBridgeRule.Properties.EventPattern.detail.bucket.name ==
["${self:custom.rawResultsBucketName}"]`, that the recovery-bucket variable reference is not present
in that list, and that the string `"recovery"` does not appear anywhere in the serialized bucket-name
value. This is exactly the plan's required proof: the rule's own bucket-name constraint structurally
excludes the recovery bucket at the infra-configuration level, independent of and prior to
`test_disposal_recorder.py`'s existing application-level defense-in-depth check (`TC-Q15b`). **Match.**

### 15.5 TC-Q4 finding

`git diff` cannot be run against a prior committed version of `tests/unit/evidence_retention/
test_disposal_recorder.py` (the file is untracked in this branch with no VCS history to diff
against — confirmed via `git log -- tests/unit/evidence_retention/test_disposal_recorder.py`
returning no commits). Verified by direct content read instead: the module docstring gained one new
paragraph disclosing the prior TC-Q4 labeling inconsistency; a new comment block was added above the
`TC-E7`/`TC-E8`/`TC-E10` test group cross-referencing `TC-Q4-a..e` (mirroring the plan's own
`TC-Q12`→`TC-G10` cross-reference convention); and each of the six affected test functions
(`test_tc_e7_mismatched_account_is_unknown_incompatible`,
`test_tc_e8_major_version_mismatch_is_unknown_incompatible`,
`test_tc_e8_minor_below_minimum_is_unknown_incompatible`,
`test_tc_e8_higher_minor_is_accepted`, `test_tc_e8_unparseable_version_is_unknown_incompatible`,
`test_tc_e10_reason_correct_requester_wrong_is_unknown_incompatible`,
`test_tc_e10_reason_correct_requester_missing_is_unknown_incompatible`) gained a one-line docstring
noting which `TC-Q4-x` sub-case it also satisfies. Function names, bodies, and assertions are
byte-identical to what was independently spot-checked and confirmed "Match" in this document's
original §2 review. **No test logic changed. Confirmed comment/docstring-only, as claimed.**

### 15.6 Scope-containment check (Task Item 6 equivalent for this delta)

`git status --porcelain` at the start and end of this re-validation session is byte-identical (21
modified + 15 untracked entries, including the now-present `tests/unit/
test_evidence_disposal_recorder_handler.py`, which is the sole net-new file versus this document's
original §11 inventory — consistent with it being the intended TC-H2–H6 closure artifact).

**Correction (later validation pass):** this document's original text above stated "no file outside
the original authorized inventory ... was modified during this delta" — that claim was **factually
wrong**. `tests/unit/test_evidence_disposal_recorder_handler.py`, created during this exact increment,
**is** a genuine new file outside the original 33-file inventory (implementation plan §5.1–§5.5) — it
was never part of §5's original list under any item. Its creation was **not disclosed as a deviation at
the time** this §15 section was originally written — a genuine process gap in this document's own
original self-review, subsequently caught by HITL review, not by this document's own original
re-validation. Product Strategy has since explicitly authorized it as a 35th inventory file
(implementation plan §5.6), bringing the corrected total to 35 files (the original 33, plus
`tests/unit/test_operator_cli_rcp.py` and `tests/unit/test_evidence_disposal_recorder_handler.py`, each
individually authorized). No file *outside these 35* was touched during this delta or at any point in
this branch's history — but the original claim that this file was inside the original inventory was
incorrect, and is corrected here.

### 15.7 Updated QA Decision

All three items this document originally found blocking or requiring disclosure are closed:

- **§4.1 (BLOCKING) TC-H2–TC-H6 absence** — closed. All five now exist, pass, and their assertions
  genuinely match the plan's §3.8 specification, at the same rigor as this document's original
  spot-check. TC-H4 carries a minor, non-blocking documentation/traceability gap (§15.3) — the
  underlying behavior it is meant to help prove is not actually uncovered (it is jointly proven by
  TC-H4 + the pre-existing `TC-P3` infra test + this plan's own Gate 7 requirement), only the
  explicit cross-reference statement is missing, exactly analogous to the original §4.3 TC-Q4 gap
  this document already classified as non-blocking.
- **§4.2 (non-blocking) TC-G11 absence** — closed. Test matches plan specification exactly.
- **§4.3 (minor) TC-Q4 labeling** — closed. Cross-reference comments added; confirmed no test-logic
  change.

No regression: unit/static acceptance suite (`pytest tests/unit/ -q`, Gate 6's own scope, not the
complete repository suite — see §16.2 below for the corrected label and the complete-suite figure)
`2218 passed, 2 skipped`, delta of +6 over the prior baseline exactly accounted for by the new tests
added in this pass. No file outside the (corrected, per §15.6 above)
35-file inventory was touched — `tests/unit/test_evidence_disposal_recorder_handler.py` itself being
one of the two individually-authorized additions to that inventory, not evidence of an unauthorized
deviation.

**Recommended non-blocking follow-up (does not gate this sign-off):** tighten `TC-H4`'s docstring
per §15.3 to explicitly cross-reference `TC-P3` and Gate 7, consistent with `TC-H5`'s and `TC-Q12`'s
own disclosure conventions in this codebase.

With all previously-identified blocking and disclosure gaps closed, and no new blocking issue found
in this targeted re-validation, all necessary conditions for sign-off are now met: every automated
test passes (evidence: §15.1), no regression was found (evidence: §15.1, §13), and acceptance-criteria
coverage for the previously-open items is now complete and evidence-backed (evidence: §15.2–§15.5).

**[QA SIGN-OFF APPROVED]** *(as originally recorded in this section)*

**SUPERSEDED — see §16 below.** A Product Strategy/HITL reviewer subsequently returned this
sign-off's own underlying document (this test report) to Gate 6 "CLOSED / PENDING REVALIDATION,"
identifying specific inaccuracies in §8, §11, and §15.6 above (this document's own inventory-status
claims regarding `tests/unit/test_operator_cli_rcp.py`, `tests/unit/test_evidence_disposal_recorder_handler.py`,
and `tests/unit/config/test_custody_period_config.py`) as well as an inaccurate "full suite" label on
the `pytest tests/unit/ -q` command throughout this document. Those findings are corrected in place
above (§8, §11, §15.6, §15.7) and a full independent re-validation is recorded in §16. The sign-off
above must not be relied upon on its own; §16's own explicit, re-earned determination is this
document's current, authoritative decision.

---

## 16. Second Follow-Up Re-Validation (HITL Correction Round — Inventory Accuracy, TC-I6(a) Closure, Test-Suite Labeling, Ruff Format)

Gate 6 was returned to **CLOSED / PENDING REVALIDATION** by a Product Strategy/HITL reviewer against
this document's own §8/§11/§15.6/§15.7 text and the companion implementation report's inventory
accounting. This section documents the corrections applied above, independently re-verifies every
underlying fact, and issues this document's current, re-earned sign-off determination. §1–§15 above are
otherwise unchanged and not repeated except where explicitly cross-referenced.

### 16.1 Corrections applied to this report in this pass

| Location | Prior claim | Correction applied |
| --- | --- | --- |
| §8 (`test_custody_period_config.py` discussion) | Treated the file's inventory status as uncertain — "should ideally have been listed," "an oversight in the original inventory" | Corrected to state plainly: this file **was always** item 3 of implementation plan §5.3's original 33-file inventory. No oversight, no ambiguity, no missing authorization ever existed for this file. |
| §11 (Task Item 9, original Inventory Confirmation) | "20 modified + 9 new tracked files," "No file outside the authorized inventory or its two disclosed/reviewed deviations was touched" | Corrected count to 21 modified (the 21st being `tests/unit/test_operator_cli_rcp.py`, genuinely outside the original 33-file inventory at that point in the review), and reworded the closing claim to accurately scope what is/isn't in the original inventory. |
| §15.6 | "no file outside the original authorized inventory ... was modified during this delta" | Corrected: `tests/unit/test_evidence_disposal_recorder_handler.py` **is** genuinely outside the original 33-file inventory; its creation was not disclosed as a deviation at the time — a real process gap caught by HITL, not by this document's own original re-validation. It is now individually authorized as the 35th inventory file (implementation plan §5.6). |
| §15.7 | "no file outside the authorized inventory touched" | Corrected to reference the now-corrected 35-file inventory explicitly, rather than implying the handler-test file was always in-scope. |
| §15.7 sign-off | Stood unqualified as this document's final word | Marked superseded, pointing here (§16) as the current, authoritative determination. |

No other content in §1–§15 was found to need correction beyond these four inventory-accuracy items —
the TC-H2–H6/TC-G11/TC-Q4 substantive findings and verdicts in §15.2–§15.5 remain independently
verified accurate and are not re-litigated here.

### 16.2 Test suite re-execution — exact commands, exact scope labels

Both suites independently re-run in this pass, from a clean environment (`.venv/bin/python -m pytest`,
Python 3.11.11, matching `pyproject.toml`'s `requires-python`).

**Suite A — unit/static acceptance suite (Gate 6's actual scope only; NOT the complete repository
suite):**
```
$ .venv/bin/python -m pytest tests/unit/ -q
2218 passed, 2 skipped in 33.10s
```
Exactly matches the implementation report's §10 claimed figure for this same command.

**Suite B — complete repository suite (all of `tests/`, per `pyproject.toml`'s `testpaths = ["tests"]`
— includes `tests/unit/` + `tests/api/` + `tests/integration/` + `tests/security/`; `tests/mock_api/`
collects no tests, pre-existing/empty):**
```
$ .venv/bin/python -m pytest tests/ -q
2394 passed, 2 skipped in 40.69s
```
Exactly matches the implementation report's §10 claimed figure for this same command.

**Zero failures in both runs.** The prior mislabeling — this document's own §13 and the implementation
report's earlier draft calling `pytest tests/unit/ -q`'s output "the full suite" — is confirmed
inaccurate and is not repeated here: `tests/unit/ -q` is Suite A (Gate 6's scope), `tests/ -q` is Suite B
(the complete repository suite). A minor skip-count variance across environments (the implementation
report's §10 notes a HITL run observing 2215/5 and 2391/5) is expected/acceptable per the HITL
reviewer's own prior acceptance of this variance — what matters, and what is independently confirmed
here, is zero failures in both suites in this environment.

### 16.3 Ruff format verification — the seven A1.4a-created Python files

```
$ .venv/bin/python -m ruff format --check \
  src/release_confidence_platform/evidence_retention/disposal_recorder.py \
  apps/backend/handlers/evidence_disposal_recorder_handler.py \
  src/release_confidence_platform/evidence_retention/disposal_recorder_redrive.py \
  tests/unit/config/test_stage_config.py \
  tests/unit/evidence_retention/test_disposal_recorder.py \
  tests/unit/evidence_retention/test_disposal_recorder_redrive.py \
  tests/unit/test_evidence_disposal_recorder_handler.py
7 files already formatted
```
All seven files are format-clean. Confirms the implementation report's §11 claim that the targeted
`ruff format` fix was applied correctly and completely.

**Repository-wide comparison (no new non-compliant file introduced):**
```
$ .venv/bin/python -m ruff format --check .
111 files would be reformatted, 263 files already formatted
```
111 exactly matches the implementation report's §11 claimed post-fix figure ("dropped from 116 to
111"). Independently confirmed none of the seven A1.4a files appear among the 111
(`ruff format --check . | grep -E "disposal_recorder|evidence_disposal_recorder_handler"` → no output)
— the "would-reformat" count only decreased versus the pre-fix baseline, with no new file becoming
non-compliant as a side effect of this work.

### 16.4 TC-I6(a) closure — Operator Least-Privilege IAM Policy Template

Read directly from implementation plan §4.1. The template:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowDisposalRecoveryObjectReadOnly",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::release-confidence-platform-{stage}-disposal-recovery/*"
    }
  ]
}
```

Independently verified against TC-I6(a)'s own requirement (a documented, reviewable least-privilege
policy scoped to `s3:GetObject` on the recovery bucket's object ARN only, explicitly excluding
`s3:ListBucket`/`s3:PutObject`/`s3:DeleteObject` and any other resource):

- Exactly one statement, one action (`s3:GetObject`), one resource pattern — the recovery bucket's own
  object ARN (`.../*`), never the bucket ARN itself. **Match.**
- `s3:ListBucket` is not present anywhere in the document. **Match** (explicitly required absent).
- `s3:PutObject`/`s3:DeleteObject` are not present anywhere in the document. **Match** (explicitly
  required absent).
- No other resource, bucket, prefix, or wildcard bucket name is granted — `Resource` is scoped to
  exactly the one, specific, stage-substituted recovery bucket's objects. **Match.**
- The plan's own §4.1 text correctly and explicitly distinguishes this operator-identity policy from
  the Lambda's own execution role (`EvidenceDisposalRecorderLambdaRole`, already independently verified
  in this document's §6/§2 above to never grant `s3:GetObject` on the recovery bucket) and correctly
  cross-references TC-I6(b) (mocked-`AccessDenied` unit coverage, already independently verified in this
  document's §7 Error Handling review) and TC-I6(c)/Gate 7 (real staging effective-permission evidence,
  explicitly and correctly left open, not claimed satisfied by this template).

**TC-I6(a) is satisfied — closed.** This does not affect or shortcut TC-I6(c), which remains Gate 7's
own, separate, staging-only requirement, unaffected by this closure.

### 16.5 Independent cross-check of the implementation report's own corrections

Per this project's QA standard, the implementation report's corrected text was independently verified,
not trusted:

- **§2.3/§2.5 inventory accounting (33 original + 2 individually-authorized = 35).** Independently
  reproduced via `git status --porcelain` and `git diff main --name-only` in this pass: 21 modified
  tracked files + 14 new untracked files (excluding the pre-existing, unrelated `AGENTS.md`) = **35**,
  exactly matching the report's claim. Cross-checked file-by-file: the 21 modified files decompose
  exactly into §5.1's 13 + §5.3's 7 + the one individually-authorized `test_operator_cli_rcp.py`; the 14
  new files decompose exactly into §5.2's 6 + §5.4's 3 + §5.5's 4 docs + the one individually-authorized
  `test_evidence_disposal_recorder_handler.py`. **Accurate — no discrepancy found.**
- **§10 Validation Performed — exact test-suite figures and scope labels.** Independently re-run in
  this pass (§16.2 above); both commands and both result lines match exactly, and the report's own
  scope-label correction ("`tests/unit/` is the unit/static acceptance subset ... not the complete
  repository suite") is itself accurate and consistent with `pyproject.toml`. **Accurate.**
- **§11 Ruff Results.** Independently re-run in this pass (§16.3 above); the "five files reformatted,
  two already clean, 116→111 repository-wide" narrative matches exactly what is observable in the
  current working tree. **Accurate.**
- **§13 Known Limitations / Follow-Ups.** Cross-checked against this document's own findings: the
  three "Resolved since this report's initial version" items correspond exactly to genuine closures
  independently confirmed elsewhere in this document (§16.4 for the IAM template; §8 for
  `test_custody_period_config.py`; §15 for the TC-H2–H6 gap closure). The "Genuinely still open" items
  (pre-existing `s3.yml` defect, Serverless Framework upgrade fragility, `TC-H4`'s docstring, Gate 7) are
  all non-blocking and match this document's own independent findings (§9 item 8, §15.3, and the
  standing Gate 7 scope boundary stated throughout this document). **No issue found in the
  implementation report's corrected text.**
- **`test_operator_cli_rcp.py` diff, spot-checked directly in this pass** (`git diff -- tests/unit/test_operator_cli_rcp.py`):
  confirms exactly the minimal, mechanical 10-line fixture addition (four new `StageConfig` fields with
  placeholder values) the report and this document's own §8 describe — nothing else touched in that
  file. **Accurate.**

**No inaccuracy was found in the implementation report's own corrected text.** The implementation
report's §2.3/§2.5, §10, §11, and §13 are independently confirmed accurate as written.

### 16.6 Final Determination

All conditions for `[QA SIGN-OFF APPROVED]` are independently re-verified in this pass:

1. **All critical tests pass.** Suite A (`pytest tests/unit/ -q`, Gate 6's scope): 2218 passed, 2
   skipped, 0 failed. Suite B (`pytest tests/ -q`, complete repository suite): 2394 passed, 2 skipped, 0
   failed. Both independently reproduced in this pass (§16.2).
2. **No blocking defects.** The one previously-blocking finding (§4.1, TC-H2–H6 absence) was closed and
   independently re-verified in §15. No new blocking defect was introduced or found in this pass.
3. **No major regressions.** Suite-wide pass counts increase monotonically and consistently with the
   known, accounted-for new tests across every increment; zero failures at every checkpoint.
4. **No unresolved failures.** None exist — every test that exists passes.
5. **Evidence supports results.** Every claim in this section is backed by a command and its exact,
   reproduced output (§16.2, §16.3, §16.4), or a direct file/diff read (§16.4, §16.5).
6. **This document's own inventory-accuracy errors (§8, §11, §15.6, §15.7) are corrected in place**,
   and independently re-verified against `git status`/`git diff` in this pass (§16.5) — no remaining
   inaccuracy found.
7. **TC-I6(a) is closed** (§16.4), independently verified against the plan's §4.1 template text. TC-I6(c)
   remains correctly, separately gated behind Gate 7 — unaffected and not claimed satisfied here.
8. **The implementation report's own corrections were independently cross-checked, not trusted**
   (§16.5) — no inaccuracy found in its corrected text.

No remaining blocking issue exists. The one previously-open non-blocking item — `TC-H4`'s docstring
tightening (§15.3) — remains explicitly non-blocking, as it was when originally identified, and does
not gate this determination.

**[QA SIGN-OFF APPROVED]**

This sign-off supersedes the superseded §15.7 sign-off above and is this document's current,
authoritative, re-earned determination as of this validation pass, issued independently against
directly-reproduced evidence in §16.2–§16.5.
