# A1.4a Disposal-Recorder Implementation Plan

**Status: authoritative implementation plan. Gate 5 (Implementation Authorization Gate) is SATISFIED — Product Strategy's Gate 5 disposition, "IMPLEMENTATION AUTHORIZED," authorizes A1.4a implementation (branch creation, code, tests, infrastructure changes) against the 33-file inventory in §5 below. Gate 6 (Post-Implementation QA Sign-off) is now SATISFIED — `[QA SIGN-OFF APPROVED]` recorded in `docs/qa/a1_4a_disposal_recorder_test_report.md`, offline/unit/static subset only. Gate 7 (Pre-Activation Validation) remains CLOSED: deployment and production activation are NOT authorized by this plan.**

This document is the authoritative implementation plan for `evidenceDisposalRecorder` (ADR Decision 13; Technical Design §22). It consolidates the architecture correction into one implementation-ready reference and now serves as the basis from which authorized A1.4a implementation work proceeds. It reproduces, cites, and cross-indexes the merged text — it does not introduce new architecture.

### Required Implementation Controls (Gate 5 Authorization Conditions)

Product Strategy's Gate 5 "IMPLEMENTATION AUTHORIZED" disposition (§8 below) imposes the following controls on all A1.4a implementation work performed against this plan:

- Use the approved 109 test-case IDs and fixtures in the companion `docs/qa/a1_4a_disposal_recorder_test_plan.md` as the acceptance baseline.
- Preserve fail-closed behavior, deterministic identity, evidence provenance, least-privilege IAM, and the five distinct failure planes (§6 below) exactly as documented — no architectural deviation.
- Do not select or change any custody-duration value (§9 below remains binding).
- Do not create an additional operator-policy or staging-campaign document.
- Keep all Gate 7 evidence exclusively in `docs/qa/a1_4a_disposal_recorder_test_report.md`.
- Create or modify only the authorized 33-file inventory (§5 below) — no files outside that inventory, except the two additional files each individually authorized during implementation (§5.6 below; 35 files total as-implemented).
- No deployment or AWS environment mutation; no production activation.
- No A1.4c, A1.4d, A2, issue #118, or other unrelated work (§10 below).
- No push or PR until Gate 6 produces `[QA SIGN-OFF APPROVED]` and the separate HITL release gate is satisfied.

---

## 0. Revision and Traceability Note (Item i)

**Source documents, at current `main` (`dea3c19`):**
- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` — Decision 13 (lines 367–396), Non-Negotiable Invariants 38–51 (lines 440–456), Status-section governance notes (lines 36–124)
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md` — §22 in full (lines 2068–2788), §7.3 (lines 205–251)

**Merge commits:** `bb92a9d` (PR #130, "correct A1.4a disposal-recorder identity, event, recovery, and IAM contract") and `dea3c19` (PR #131, "correct A1.4a disposal-recorder resource-import wiring and QA plane coverage"). `git log` confirms these are the only two commits that have ever touched the Technical Design's §22 content — every correction round described below is encoded within these two commits.

**Product Strategy disposition history (summarized):** the A1.4a.0 correction was reviewed across eleven rounds. Round 1 carried "Approved with Concerns — High Risk"; Round 2 was rejected outright ("REJECT — High Risk"); Rounds 3 through 9 were each "RETURN FOR CORRECTION — High Risk"; Rounds 10 and 11 stepped down to "RETURN FOR TARGETED CORRECTION — Medium Risk" as the remaining defects narrowed from architectural gaps to wording, sequencing, and QA-coverage omissions. **No round — including Round 11, the last round present in the merged text — carries an unconditional "APPROVED" disposition.** Every one of the eleven recorded dispositions is either a rejection or a return-for-correction. This is verified directly: `grep -o 'Product Strategy disposition "[^"]*"' docs/architecture/adr_evidence_retention_disposal_enforcement.md` returns exactly eleven matches, none of which is "APPROVED."

### Round dispositions vs. PR/merge approval — two distinct facts, not one

This implementation plan previously framed the eleven rounds as if nothing about this correction was ever approved. That conflates two different things, which must be stated side by side, not as substitutes for each other:

1. **No individual round's own Product Strategy disposition was ever "APPROVED."** As stated immediately above, all eleven rounds recorded in the ADR's Status-section governance notes closed as either a rejection or a return-for-correction; Round 11 — the last round present in the merged text — closed "RETURN FOR TARGETED CORRECTION — Medium Risk," not "APPROVED." This fact is still true and still relevant: it shows the documentation kept evolving even after Round 11, and no round's own disposition should be read as a green light on its own terms.

2. **Separately, PR #130 (merge commit `bb92a9d`) and PR #131 (merge commit `dea3c19`) — which together carry this documentation correction through its full Round 1–11 history — were each independently reviewed and approved through this repository's normal PR process and merged into `main`.** That approval and merge constitute Product Strategy's acceptance of the corrected architecture DOCUMENTATION (ADR Decision 13 / TD §22 text) as the authoritative baseline. This is a genuine, completed approval — of the documentation text.

Fact 1 answers "did any single correction round, on its own terms, receive an unconditional 'APPROVED' disposition mid-cycle?" — no. Fact 2 answers "was the documentation correction, as a whole, ever approved and merged?" — yes, via ordinary PR review and merge (this is Gate 1, §8 below — SATISFIED). **Neither fact constitutes, nor was a substitute for, authorization to implement A1.4a.** Implementation authorization was a separate gate (Gate 5, Implementation Authorization Gate, §8 below) — at the time of these eleven rounds, still closed, and each round's own closing text states plainly that the correction is "documentation-only" and "does not authorize A1.4a implementation." Gate 5 has since been satisfied by Product Strategy's separate "IMPLEMENTATION AUTHORIZED" disposition (§8 below) — that later disposition, not anything within these eleven rounds, is what opened it.

### ⚠ Discrepancy vs. this task's framing

The task briefing this implementation plan to me described the merged state as "Round 1–6 corrections all merged" via PRs #130/#131. **Direct inspection shows this undercounts the actual merged state.** Both the ADR and the Technical Design contain corrections through **Round 11**, all within the same two commits:

- TD §22's own front-matter "Revision history" paragraph (§22, lines 2072–2079) narrates only Rounds 1–6.
- The ADR's Status-section governance notes (lines 36–124) — positioned well before Decision 13's own body text — separately narrate Rounds 1 through 11 in full, each with its own disposition, item count, and closing "this is a documentation-only correction" statement.
- TD §22.9.5, §22.10, §22.11, §22.13, and §22.14 contain inline corrections explicitly labeled through Round 11 (confirmed by direct grep: `Round 7` appears 23 times, `Round 8` 21 times, `Round 9` 14 times, `Round 10` 12 times, `Round 11` 18 times in the Technical Design alone; `Round 12` appears zero times, confirming Round 11 is the true final round).

In other words: **TD §22's own revision-history preamble is stale relative to its own body.** The body was corrected through Round 11; the summary paragraph at the top of the section was not updated past Round 6. This implementation plan treats **Round 11 as the authoritative final state** and cites Round 11 items throughout wherever they supersede earlier rounds. Every citation below that matters for a specific fact names the round that most recently corrected it, not merely "Round 1–6."

**Practical consequence:** this discrepancy does not change any conclusion in this implementation plan — Round 11 does not reopen anything Round 1–9 established, and Round 10/11's own corrections are wording, sequencing, and QA-coverage completions, not new architecture. But it does mean any reader treating "Round 1–6" as the complete correction history would be missing five additional, already-merged rounds of factual correction, including the entire two-pass render-harness contract (Rounds 8–9), the `-an` bucket-suffix rule (Round 9), the `StageConfig.region`-bound cross-field checks (Round 7), and the Pass-0 IAM/recovery-bucket import-line wiring (Round 11) — several of which are load-bearing for items (a), (b), (c), and (d) below.

---

## 1. Corrected Seven-Step Infrastructure-Render Sequence (Item a)

**Re-checked against the source (TD §22.9.5) directly: the introductory sentence below is a direct, verbatim quotation; the seven-item numbered list that follows it is a faithful restatement of TD §22.9.5's seven-step sequence, reformatted into a numbered list for clarity — not a byte-for-byte quotation of the source prose.** In the source, all seven steps appear inline within one continuous sentence, each step marked only by a bolded parenthetical number — e.g. "**(1)** add `infra/resources/evidence-disposal-recorder-iam.yml` and its `resources:` import line (Pass 0); **(2)** add ... (Pass 0); **(3)** add the function/event-source-mapping block ... (Pass 1); ..." — not as separate markdown list items. The wording of each step below matches the source; only the presentation (one list item per line, versus one inline sentence) differs. TD §22.9.5 (Round 11 renumbering) states the introductory sentence as follows:

> "Restated as seven discrete, ordered steps for unambiguous traceability (renumbered, A1.4a.0 Round 11, item 1 — inserts two new steps, (1) and (2) below, for the logical-ID-independent IAM and recovery-bucket fragment imports ahead of the five steps this subsection previously enumerated; the sequence remains a two-render 'two-pass' sequence — the two renders are steps (4) and (7) below, not one render per step)":

1. Add `infra/resources/evidence-disposal-recorder-iam.yml` and its `resources:` import line (**Pass 0**).
2. Add `infra/resources/evidence-disposal-recovery-bucket.yml` and its `resources:` import line (**Pass 0**).
3. Add the `evidenceDisposalRecorder` function/event-source-mapping block, referencing the now-imported role and bucket, without the Outputs fragment (**Pass 1**).
4. Render/package via the isolated harness (**Pass 1's render**).
5. Record the confirmed logical IDs from that render's `Resources:` section.
6. Add the Outputs fragment (`infra/resources/evidence-disposal-recorder-outputs.yml`) using those confirmed logical IDs, and its import line (**Pass 2**).
7. Render/package again via the identical isolated harness (**Pass 2's render**) and run the final, extended static-referential-integrity assertions against that second render.

**Source:** TD §22.9.5, "Required implementation sequence — two-pass logical-ID discovery via an isolated render harness" paragraph and its immediately following "Restated as seven discrete, ordered steps" paragraph (A1.4a.0 Round 8, item 4 for the original two-pass structure; A1.4a.0 Round 11, item 1 for the Pass-0 insertion and renumbering to seven steps).

**Why Pass 0 exists (steps 1–2), stated precisely:** neither the IAM fragment (`EvidenceDisposalRecorderLambdaRole`) nor the recovery-bucket fragment references any logical ID this render sequence exists to discover — both are complete, self-contained resource definitions the function block itself must reference (as its `role` property and its event-source mapping's `OnFailure` destination, respectively). Their import lines are therefore added **before** Pass 1, not deferred to Pass 2 alongside the Outputs fragment, whose own `Fn::GetAtt`/`Ref` targets genuinely cannot be known until Pass 1's render produces them. Omitting Pass 0 (i.e., never adding these two import lines at all) was itself a Round 11-corrected omission — see §2 below.

**What a render at steps 4 and 7 can prove, stated precisely (TD §22.9.5, Round 8 item 2; Round 9 item 5 wording fix):** a Serverless-Framework-rendered template is a *generated/merged* template — Serverless-level `${self:...}`/`${file(...)}` substitution and fragment merging applied — never a "fully resolved" CloudFormation template in the sense AWS's own intrinsic-function resolution provides at actual deploy time. The render proves only **static referential integrity**: that a `Ref`/`Fn::GetAtt` target names a logical ID genuinely present, of the expected type, in the rendered template's own `Resources:` section. It proves nothing about whether AWS would actually accept the template at deploy time.

**Render mechanism, stated precisely:** this is never a render against the real, checked-in repository. *At the time this section was originally written (pre-implementation), `config/custody_periods.json` defined six stage-value keys, all empty `{}` objects, and referencing any of them via `${file(...)}` failed Serverless Framework variable resolution before A1.4a implementation began (`evidentiary_classes.{raw_evidence,aggregate_metadata,intelligence,report,certificate}` and `operational_durations.retention_marker`, all `{}`). Implementation has since added a seventh key, `operational_durations.disposal_recovery`, still `{}` (unconfigured — no custody-duration value is introduced; §9 below) — present in the working tree on `feature/a1_4a-disposal-recorder`, not committed, not merged, not deployed.* Steps 4 and 7 both use an isolated, temporary-directory render harness with integer-only sentinel values injected into a *copy* of `config/custody_periods.json` — never the real file — per the full harness contract at TD §22.14's `test_infra_configuration.py` entry (Round 8 item 1, made concretely executable by Round 9 item 2, wording-corrected by Round 10).

---

## 2. Three CloudFormation Fragment Imports (Item b)

**The exact set of three, confirmed from the merged text, is the three NEW `resources:` import lines added to `infra/serverless.yml` — not a broader "three fragments touched" count.** TD §22.9.5 (Round 11, item 1) states this explicitly and corrects an under-count in the prior six rounds' own text:

> "`infra/serverless.yml`'s `resources:` import list therefore gains **three new lines in total** once A1.4a implementation completes — one for `evidence-disposal-recorder-iam.yml`, one for `evidence-disposal-recovery-bucket.yml`, and one for `evidence-disposal-recorder-outputs.yml` — never the single line this subsection's own text, and §22.14's inventory entry for `infra/serverless.yml`, stated through Round 10."

| # | Fragment file | New or modified | Import-line pass | Defines |
| --- | --- | --- | --- | --- |
| 1 | `infra/resources/evidence-disposal-recorder-iam.yml` | **New** | Pass 0 | `EvidenceDisposalRecorderLambdaRole` (dedicated execution role, §22.11) |
| 2 | `infra/resources/evidence-disposal-recovery-bucket.yml` | **New** | Pass 0 | Dedicated recovery bucket, its bucket policy, and its own `Object Created` notification rule (§22.9.1/§22.9.2) |
| 3 | `infra/resources/evidence-disposal-recorder-outputs.yml` | **New** | Pass 2 | `EvidenceDisposalRecorderFunctionArn`, `EvidenceDisposalRecorderEventSourceMappingUuid` (§22.9.5) |

**Source:** TD §22.9.5 (Round 6 item 3 for the Outputs fragment's own file-shape correction; Round 11 item 1 for the two additional fragments and the "three, not one" correction); §22.14's `infra/serverless.yml` entry (same Round 11 correction applied there).

### ⚠ Discrepancy / clarification vs. this task's framing

The task's item (b) instruction anticipated I would need to "confirm the exact set of three from the text, do not guess" and flagged the outputs fragment as one of them, "plus whichever existing fragments... are modified/newly imported." **The merged text does not describe three fragments that are each independently either new-or-modified; it describes exactly three *new* fragments, each requiring a *new* import line.** Separately from those three, **two already-imported, pre-existing fragments are modified in place, without gaining a new import line** (since they are already members of `infra/serverless.yml`'s six-fragment import list):

- `infra/resources/dynamodb.yml` — gains a reinstated `MetadataTableStreamArn` Output (§22.9.5's explicit supersession of Round 3 item 10(a), for the new external CLI consumer only; §22.14).
- `infra/resources/evidence-retention-dlq.yml` — gains a new `AWS::SQS::QueuePolicy` scoped to exactly two authorized rule ARNs, plus the observability alarms associated with planes (i)/(ii) (§22.11's resource-policy discipline; §22.14, corrected from "no structural change required" to modified, A1.4a.0 Round 3 item 10(d)/10(f)).

`infra/serverless.yml` itself is also modified (new function block, three new import lines, one new `custom.disposalRecoveryBucketName` entry, one new `custom.custodyPeriodDays.disposal_recovery` entry) but is not itself a `resources:`-imported fragment — it is the file that does the importing.

So the total count of infrastructure files touched by this correction is **six** (`infra/serverless.yml` [1] + three NEW `infra/resources/*.yml` fragments [`evidence-disposal-recorder-iam.yml`, `evidence-disposal-recovery-bucket.yml`, `evidence-disposal-recorder-outputs.yml`] + two pre-existing MODIFIED fragments [`infra/resources/dynamodb.yml`, `infra/resources/evidence-retention-dlq.yml`] = 1 + 3 + 2 = 6), while the count of **new `resources:` import lines** is exactly **three**. I am stating both counts explicitly rather than silently collapsing them, since the task's phrasing could be read either way and the merged text is precise about which of the two it means (the "three new lines" language, repeated verbatim at three separate locations: §22.9.5, §22.11, §22.14).

---

## 3. Logical-ID Discovery and Validation Approach (Item c)

Two structurally distinct mechanisms exist, serving two different consumers. They must not be conflated.

### 3.1 Deploy-time CloudFormation logical-ID discovery (serves the Outputs fragment itself)

Per the seven-step sequence above, two Serverless-Framework-auto-generated logical IDs are discovered by inspecting Pass 1's rendered template output, then hard-coded as the `Fn::GetAtt`/`Ref` targets in the Outputs fragment before Pass 2:

- **`AWS::Lambda::Function` logical ID** for the `evidenceDisposalRecorder` function — expected to follow Serverless Framework's own `{FunctionName}LambdaFunction` PascalCase convention (`EvidenceDisposalRecorderLambdaFunction`), but the render is what confirms the *actual* rendered ID, never a guessed or assumed name (TD §22.9.5, item 2, Round 7 item 5 / Round 10 item 1 wording corrections).
- **`AWS::Lambda::EventSourceMapping` logical ID** for the function's `stream` event source — no assumed naming convention at all; discovered from the same Pass-1 render (TD §22.9.5, item 3, same round corrections).

Final-render (Pass 2/step 7) static-referential-integrity assertions required (TD §22.14, `test_infra_configuration.py` entry, Round 8 items 2/3, Round 11 item 1's extensions (f)/(g)):
- (a) both Output keys exist in the rendered template's `Outputs:` section;
- (b) each Output's intrinsic names an exact logical ID present as a top-level key in `Resources:`;
- (c) the function-ARN Output's target has `Type: AWS::Lambda::Function`;
- (d) the ESM-UUID Output's target has `Type: AWS::Lambda::EventSourceMapping`;
- (e) no target logical ID is missing from `Resources:` (structurally guaranteed by (b), not a separate check);
- (f) **(Round 11, item 1)** `EvidenceDisposalRecorderLambdaRole` is present with `Type: AWS::IAM::Role`;
- (g) **(Round 11, item 1)** the recovery-bucket resource, logical ID `EvidenceDisposalRecoveryBucket`, is present with `Type: AWS::S3::Bucket`.

Plus a source-level (raw-YAML) assertion that all three new import lines are literally present in `infra/serverless.yml`'s `resources:` list (TD §22.14, Round 8 item 3 split, Round 11 item 1 extension).

### 3.2 Deployment-to-CLI identity configuration and runtime validation (serves the redrive command)

A structurally separate concern: after deployment, four AWS-assigned identifiers must reach the operator CLI's own `StageConfig` so the redrive command (§4 below) can validate a recovered object before trusting it. TD §22.9.5 defines four new `StageConfig` fields, their `ENV_OVERRIDES`, and the CloudFormation Outputs (or deterministic-naming source, for the bucket name) that produce each:

| `StageConfig` field | Source | `ENV_OVERRIDES` |
| --- | --- | --- |
| `disposal_recovery_bucket_name` | Deterministic, no Output — `custom.disposalRecoveryBucketName` in `infra/serverless.yml` (Round 7 item 3), transcribed into `config/stages/{stage}.json` | `RCP_DISPOSAL_RECOVERY_BUCKET_NAME` |
| `disposal_recorder_function_arn` | `EvidenceDisposalRecorderFunctionArn` Output | `RCP_DISPOSAL_RECORDER_FUNCTION_ARN` |
| `disposal_recorder_event_source_mapping_uuid` | `EvidenceDisposalRecorderEventSourceMappingUuid` Output | `RCP_DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID` |
| `metadata_table_stream_arn` | `MetadataTableStreamArn` Output (reinstated in `dynamodb.yml`) | `RCP_METADATA_TABLE_STREAM_ARN` |

**Validation — `validate_disposal_recorder_config()`, nine checks (count corrected Round 7→Round 8 item 5), mirroring `validate_scheduler_config`'s shape:**
1–4. Structural regex validity for each of the four fields (`DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN`, `DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN`, `DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN`, `METADATA_TABLE_STREAM_ARN_PATTERN` — four compiled regex constants total, reconfirmed at Round 8 item 6/Round 9);
5. ARN-vs-ARN region agreement;
6. ARN-vs-ARN account agreement;
7. function-ARN-region vs. `StageConfig.region` (Round 7 item 1, closes the "wrong-stage-region" gap);
8. stream-ARN-region vs. `StageConfig.region` (Round 7 item 1);
9. stream table-identity vs. `StageConfig.audit_metadata_table`.

All nine failures are **collected**, not short-circuited, into one `ConfigError(..., "DISPOSAL_RECORDER_CONFIG_ERROR")`, called before `AwsClientFactory` construction and before any AWS call (TD §22.9.5, "Ordering" paragraph).

**Runtime validation of the recovered object itself (redrive command, distinct six-check validator — never conflated with the nine checks above):** see §4.

**Source:** TD §22.9.5 in full; §22.9.3 for the redrive-side six checks; ADR Non-Negotiable Invariant 51 for the governing invariant.

---

## 4. Redrive Command's Six Envelope/Provenance Checks Plus Construction-Time Bucket Guarantee

Distinct from §3's *deployment configuration* validation, the `rcp retention disposal-recorder redrive` command performs its own runtime validation of a specific recovered S3 object before invoking shared per-record processing (TD §22.9.3, validation contract corrected Round 4 item 3, reconciled Round 6 item 1):

- **Construction-time guarantee (not a runtime check):** the bucket name passed to `GetObject` is always resolved from `StageConfig.disposal_recovery_bucket_name`, never a CLI argument (`--recovery-object-key` is the only CLI input). The actual enforcement boundary against a misconfigured bucket name is narrowly-scoped operator IAM (`s3:GetObject` scoped to the one recovery-bucket ARN) — a misconfiguration fails closed with `AccessDenied`, not silent success against the wrong bucket.
- **Six numbered runtime checks**, all required:
  1. Object key matches `aws/lambda/{event-source-mapping-uuid}/...`, UUID matched against configured `disposal_recorder_event_source_mapping_uuid`.
  2. Object body's `requestContext.functionArn` matches configured `disposal_recorder_function_arn`.
  3. Object's own envelope `version` field is a supported value.
  4. Object's `DDBStreamBatchInfo.streamArn` matches configured `metadata_table_stream_arn`.
  5. Object's `payload` field exists and parses as a genuine DynamoDB Streams event shape.
  6. Every recovered record's own `eventSourceARN` within `payload` matches the same expected stream ARN (per-record check, distinct from check 4's once-per-object check).

Any mismatch at construction time or any of the six checks is rejected fail-closed before shared processing runs, reported as a distinct `DisposalRedriveResult` outcome.

### 4.1 Operator Least-Privilege IAM Policy Template (TC-I6(a))

**This is a documentation/runbook deliverable for the OPERATOR's own IAM identity — never the Lambda's execution role.** The Lambda's dedicated execution role (`EvidenceDisposalRecorderLambdaRole`, `infra/resources/evidence-disposal-recorder-iam.yml`, §2 above) is already fully specified as deployable infrastructure and explicitly never grants `s3:GetObject` on the recovery bucket to that role (see that file's own inline commentary: "s3:GetObject is explicitly NEVER granted on the recovery bucket to this role, under any justification"). The template below is the separate, distinct artifact TC-I6(a) requires (companion QA plan §3.9's TC-I6 row and §7's TC-I6(a) three-way split): a reviewable, least-privilege IAM policy for the human operator's own pre-existing AWS credentials, under which the `rcp retention disposal-recorder redrive` command runs. **This template is not infrastructure this repository's `infra/*.yml` provisions or deploys.** It is not rendered by Serverless Framework, defines no CloudFormation resource, and is not created by any file in the file inventory (§5 below). It is a policy document the operator (or the team provisioning the operator's IAM identity) attaches manually, out-of-band, to that identity — a documentation artifact, per TC-I6(a)'s own text, which "lives in the implementation plan."

The recovery bucket's name is deterministic from stage — `infra/serverless.yml`'s `custom.disposalRecoveryBucketName: ${self:custom.resourcePrefix}-${self:provider.stage}-disposal-recovery` (§3.2 table above), i.e. `release-confidence-platform-{stage}-disposal-recovery` (for example, `release-confidence-platform-prod-disposal-recovery` for the `prod` stage). This is a real AWS IAM policy document, not a Serverless-Framework-templated file — it carries no `${self:...}`/`${file(...)}` variable syntax at attachment time. Substitute the literal, deployed-stage bucket name (available to the operator via the resolved `StageConfig.disposal_recovery_bucket_name` / `RCP_DISPOSAL_RECOVERY_BUCKET_NAME`, §3.2 above) for `{stage}` below:

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

**Explicitly, by design:**
- Exactly one statement, one action (`s3:GetObject`), one resource pattern — the recovery bucket's own object ARN (`.../*`), never the bucket ARN itself.
- `s3:ListBucket` is **NOT** granted — the operator supplies the exact object key via `--recovery-object-key`; the redrive command never lists the bucket.
- `s3:PutObject` and `s3:DeleteObject` are **NOT** granted — the operator's own role is read-only recovery, never write or delete.
- No other bucket, prefix, or resource ARN is granted — this statement's `Resource` is scoped to exactly the one, specific, configured recovery bucket's objects, never a wildcard bucket name, an evidentiary-class bucket/prefix, or any other resource.
- This template is the actual enforcement boundary §4's own "construction-time guarantee" above relies on: since the bucket name passed to `GetObject` is always resolved from `StageConfig.disposal_recovery_bucket_name` (never a CLI argument), a misconfigured or malicious bucket name fails closed with `AccessDenied` under this policy, never silent success against the wrong bucket.

**Cross-reference:** companion QA plan `docs/qa/a1_4a_disposal_recorder_test_plan.md`, §3.9's TC-I6 row and §7's three-way TC-I6 split — TC-I6(a) is this documentation/runbook deliverable (existence and reviewability, not execution); TC-I6(b) is the mocked-`AccessDenied` fail-closed application-level unit test (covered by §7 item 14 above); TC-I6(c) and Gate 7 item 3 ("Operator effective-permission evidence," §8 below) require REAL captured evidence from a real staging operator identity attached under a policy of this shape, proving both an allow outcome (intended recovery bucket) and a deny outcome (an unrelated/wrong bucket) — that staging evidence is gated behind Gate 7 and is not satisfied by this template's existence alone.

---

## 5. Corrected 33-File Anticipated Implementation Inventory (Item d)

**Verified: the ORIGINAL, planning-time inventory count is exactly 33, matching the merged text's own recount.** TD §22.9.5 (Round 11, item 1) states this directly: *"This correction does not change §22.14's own five inventory-category file counts (13 modified production/configuration/infrastructure files, 6 new production/infrastructure files, 7 modified tests, 3 new tests, 4 backend/QA records — 33 files total, independently reconfirmed by direct recount)."* I independently recounted every bullet under TD §22.14 below and confirm 13 + 6 + 7 + 3 + 4 = 33, with no double-counted or missing entries. **This 33-file count is the fixed, unchanged historical planning-time record.** It is not the final as-implemented count — see §5.6 below, which documents two additional, individually-authorized files identified during implementation and states the corrected final total of 35.

### 5.1 Modified production / configuration / infrastructure (13)

1. `src/release_confidence_platform/evidence_retention/models.py` — `DisposalRecord` gains seven new fields plus source-kind-conditional validator (§7.3, §22.2, §22.3).
2. `src/release_confidence_platform/evidence_retention/disposal_repository.py` — `consistent_read` param on `get_disposal_record`/`_get_item`; write path extended for seven new fields (§22.3).
3. `infra/serverless.yml` — new function block, three new `resources:` import lines, `custom.disposalRecoveryBucketName`, `custom.custodyPeriodDays.disposal_recovery` (§22.9.5, §22.10, §22.14).
4. `config/custody_periods.json` — new `operational_durations.disposal_recovery` key, still empty (§22.9.2 item 9). *At the time this section was originally written (pre-implementation), direct read confirmed the file defined only the pre-existing six keys and this key did not yet exist. It has since been implemented: `config/custody_periods.json` now defines seven keys, including `operational_durations.disposal_recovery` — still unconfigured (`{}`), consistent with §9 below (no custody-duration value is introduced). Present in the working tree on `feature/a1_4a-disposal-recorder`; not committed; not merged to `main`; not deployed.*
5. `infra/resources/dynamodb.yml` — reinstated `MetadataTableStreamArn` Output, for the new external CLI consumer only (§22.9.5, Round 5 item 1).
6. `src/release_confidence_platform/config/stage_config.py` — four new fields, `REQUIRED_FIELDS`/`ENV_OVERRIDES` entries, `validate_disposal_recorder_config`, four compiled regex constants (§22.9.5).
7. `config/stages/dev.json`, `config/stages/staging.json`, `config/stages/prod.json` — each gains the four new placeholder fields (§22.9.5, Round 5 item 1). *(Counted as three separate files within this one inventory bullet.)*
8. `src/release_confidence_platform/evidence_retention/commands.py` — new redrive parser/dispatch functions (§22.9.3, Round 3 item 11).
9. `src/release_confidence_platform/operator_cli/main.py` — new `disposal-recorder redrive` subcommand registration and dispatch branch (§22.9.5, Round 5 item 1's `validate_disposal_recorder_config()` call).
10. `src/release_confidence_platform/operator_cli/result.py` — `DisposalRedriveResult` rendering/sanitization (§22.9.3).
11. `infra/resources/evidence-retention-dlq.yml` — new `AWS::SQS::QueuePolicy` scoped to exactly two rule ARNs; corrected from "no structural change" (Round 3 item 10(d)/10(f)).

*(Items 7's three files bring the total to 13: 1,2,3,4,5,6,7a,7b,7c,8,9,10,11.)*

### 5.2 New production / infrastructure (6)

1. `src/release_confidence_platform/evidence_retention/disposal_recorder.py` — shared Lambda handler / per-record processing logic.
2. `apps/backend/handlers/evidence_disposal_recorder_handler.py` — thin Lambda entrypoint.
3. `src/release_confidence_platform/evidence_retention/disposal_recorder_redrive.py` — redrive command's own module.
4. `infra/resources/evidence-disposal-recorder-iam.yml` — `EvidenceDisposalRecorderLambdaRole` only.
5. `infra/resources/evidence-disposal-recovery-bucket.yml` — recovery bucket, bucket policy, notification rule, retry policy, notification-failure alarm.
6. `infra/resources/evidence-disposal-recorder-outputs.yml` — the two new Outputs.

*At the time this section was originally written (pre-implementation), direct filesystem check confirmed none of these six files existed in the repository (`ls` returned "No such file or directory" for all six). All six have since been implemented and are present in the working tree on `feature/a1_4a-disposal-recorder` — not committed, not merged to `main`, not deployed. See §11.2 below for the corrected current-state detail.*

### 5.3 Modified tests (7)

1. `tests/unit/evidence_retention/test_disposal_repository.py`
2. `tests/unit/evidence_retention/test_models.py`
3. `tests/unit/config/test_custody_period_config.py`
4. `tests/unit/test_operator_cli_retention.py`
5. `tests/unit/test_operator_cli_result.py`
6. `tests/unit/test_handler_import_smoke.py` — reclassified from "New" to "Modified" (Round 4 item 8; file already exists).
7. `tests/unit/test_infra_configuration.py` — reclassified from "New" to "Modified" (Round 4 item 8; file already exists, 603 lines confirmed).

### 5.4 New tests (3)

1. `tests/unit/config/test_stage_config.py`
2. `tests/unit/evidence_retention/test_disposal_recorder.py`
3. `tests/unit/evidence_retention/test_disposal_recorder_redrive.py`

### 5.5 Docs / QA records (4)

1. `docs/backend/a1_4a_disposal_recorder_implementation_plan.md`
2. `docs/backend/a1_4a_disposal_recorder_implementation_report.md`
3. `docs/qa/a1_4a_disposal_recorder_test_plan.md`
4. `docs/qa/a1_4a_disposal_recorder_test_report.md`

*(This document has been promoted to `docs/backend/a1_4a_disposal_recorder_implementation_plan.md`, fulfilling item 1 of this inventory directly — it is not a separate, additional fifth-and-then-some documentation artifact outside this four-file inventory. A1.4a implementation has since been authorized (Gate 5, §8 below) and is now complete. It does not count as a 34th file against the 33-file total, and it does not substitute for the implementation report or test report the remaining two files above name.*

*All four docs/QA-records items now exist. Item 1 (this document) fulfills the implementation-plan role. Item 2, `docs/backend/a1_4a_disposal_recorder_implementation_report.md`, documents what was built (Increments 1–4). Item 3, `docs/qa/a1_4a_disposal_recorder_test_plan.md`, is the QA acceptance-criteria plan. Item 4, `docs/qa/a1_4a_disposal_recorder_test_report.md`, records `[QA SIGN-OFF APPROVED]` (§16.6 of that document). None of the four has been committed, merged to `main`, or deployed — all exist only in the working tree on `feature/a1_4a-disposal-recorder`.)*

**Source:** TD §22.14 in full, cross-checked against ADR-side Round 11 governance note (line 120) confirming the recount.

### 5.6 Post-Implementation Addition — Two Individually-Authorized Files Beyond the Original 33 (35 Total)

The 33-file count in §5.1–§5.5 above (13 + 6 + 7 + 3 + 4 = 33) is the **ORIGINAL planning-time inventory**, fixed before implementation began. It is preserved unchanged above as the historical planning record. During implementation, two additional files — each genuinely outside that original 33-file inventory — were required, and each has been individually authorized by Product Strategy:

1. **`tests/unit/test_operator_cli_rcp.py`** — pre-existing test file, modified. Its `StageConfig(...)` fixture predated the four new `StageConfig.REQUIRED_FIELDS` entries this correction adds (§3.2 above); `StageConfigLoader.load()` correctly rejects it as incomplete once those fields are required. Fixed by adding the four fields, mirroring the identical pattern already applied to the in-inventory `tests/unit/test_operator_cli_retention.py` (§5.3 item 4 above). A minimal, mechanical, unavoidable consequence of the authorized `StageConfig` schema change — never new functional scope. **Explicitly authorized by Product Strategy before the edit was made.**
2. **`tests/unit/test_evidence_disposal_recorder_handler.py`** — new test file, created during a QA-gap-closure increment. Tests `EvidenceDisposalRecorderHandler`'s own batch/orchestration behavior (TC-H2 through TC-H6, companion QA plan §3.8) — distinct from `disposal_recorder.py`'s shared per-record processing logic (already covered by the in-inventory `tests/unit/evidence_retention/test_disposal_recorder.py`, §5.4 item 2 above) and distinct from `tests/unit/test_handler_import_smoke.py`'s narrow import-smoke purpose (§5.3 item 6 above). **Explicitly authorized by Product Strategy as a 35th inventory file.**

**Corrected final as-implemented file count: 35** — the original 33-file inventory (§5.1–§5.5 above, unchanged as the historical planning-time record) plus these two individually-authorized additions. Both additions are documented here for the same reason the original 33 are documented above: full traceability of every file this implementation plan authorizes, or has separately authorized, touching. Neither addition introduces new architecture, new IAM scope, or a numeric custody-duration value (§9 below is unaffected).

**Clarification — `tests/unit/config/test_custody_period_config.py` (§5.3 item 3 above) was always in-inventory, never a deviation.** This file is, and always has been, one of the original 33 modified-test files. It required a one-line schema-shape update plus one new test as a direct, foreseeable consequence of `config/custody_periods.json` gaining the authorized `operational_durations.disposal_recovery` key (§5.1 item 4 above) — an in-inventory file requiring an edit consequential to another in-inventory change, not a file outside the inventory. It is called out here only for completeness, to forestall any reading of this subsection as implying it belongs alongside the two genuinely-outside-inventory files above; it does not.

---

## 6. Five Separate Failure Planes (Item e; ADR Invariant 44)

| Plane | Trigger | Destination | Named metric(s) / alarm |
| --- | --- | --- | --- |
| **(i)** EventBridge → Lambda delivery failure (S3 path) | EventBridge rule fails to invoke the Lambda (e.g., permissions failure, retry exhaustion) | `evidenceDisposalRecorderDLQ` (SQS), via the rule's own `DeadLetterConfig` | `InvocationsFailedToBeSentToDlq` (EventBridge-rule-scoped, dimensioned by `RuleName`/`EventBusName`); plus the pre-existing `evidenceDisposalRecorderDLQAlarm` (queue depth) |
| **(ii)** Lambda asynchronous-invocation failure (S3 path) | Lambda invoked but the invocation itself fails (unhandled exception, timeout, throttle) | `evidenceDisposalRecorderDLQ`, via the function's own `DestinationConfig.OnFailure` | `DestinationDeliveryFailures` (Lambda-function-scoped, dimensioned by `FunctionName`) — same metric *name* as plane (iii)'s but a distinct instance; plus `Errors`/`Throttles` as earlier plane-specific signals |
| **(iii)** DynamoDB Streams event-source-mapping processing failure (retry exhaustion) | Batch exhausts `MaximumRetryAttempts`/`MaximumRecordAgeInSeconds` | **Dedicated recovery bucket** (S3), via the event-source mapping's own `DestinationConfig.OnFailure` — never `evidenceDisposalRecorderDLQ` | `OnFailureDestinationDeliveredEventCount` (positive-path confirmation) — requires `MetricsConfig: { Metrics: ["EventCount"] }` explicit opt-in enablement (Round 4 item 1); no unprefixed alias exists |
| **(iv)** Failure while writing to the recovery-bucket destination itself | The event-source mapping's own attempt to deliver to the recovery bucket fails (batch neither processed nor delivered) | No further fallback in this design | `DroppedEventCount > 0` — the actual silent-loss signal; same `MetricsConfig` opt-in required |
| **(v)** Recovery-bucket notification-rule delivery failure | The recovery bucket's own `Object Created` → EventBridge → `evidenceDisposalRecorderDLQ` notification rule (`EvidenceDisposalRecoveryBucketObjectCreatedRule`) fails to deliver its notification message | `evidenceDisposalRecorderDLQ`, as a pure notification (distinguishable by shape/source from a genuine plane (i)/(ii) failure message) | `EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm`, on this rule's own `FailedInvocations` metric — explicitly distinct from plane (i)'s alarm (Round 4 item 7) |

**Corrections load-bearing to this table:**
- Plane (iii) was corrected off `evidenceDisposalRecorderDLQ` onto the dedicated recovery bucket in Round 2 (item 2) — a DynamoDB event-source mapping has exactly one `OnFailure` slot, and it is occupied by the S3 destination, not the SQS queue.
- Named metrics for every plane (replacing "no native metric is known" hedges) were added in Round 3 (item 2).
- The `EventCount`-category opt-in requirement for `OnFailureDestinationDeliveredEventCount`/`DroppedEventCount`, and removal of the fictitious unprefixed `DestinationDeliveredEventCount` alias, were corrected in Round 4 (item 1).
- Plane (v)'s own dedicated alarm (as opposed to relying solely on "an SQS message did or didn't show up") was added in Round 4 (item 7).
- **Plane (iv) was, through Round 10, missing its own dedicated QA-matrix test item** — §22.13 item 9 enumerated only (i)–(iii) plus a claimed "fifth" (the notification plane), silently skipping (iv) by name even though ADR Invariant 44 and TD §22.8 both already defined it. This was corrected in **Round 11 (item 2)** — see §7, item 9 below.

**Source:** TD §22.8 (plane definitions and metrics), §22.9.1–§22.9.4 (plane (iii)/(iv) mechanism), §22.9.2 (plane (v) mechanism); ADR Non-Negotiable Invariant 44/45.

---

## 7. Complete TD §22.13 Future QA Acceptance Matrix (Item f)

Reproduced in full below. No test file is created by the underlying correction or by this implementation plan; this is the required future-coverage list. Expected ownership: `tests/unit/evidence_retention/test_disposal_recorder.py` (new) and `tests/unit/evidence_retention/test_disposal_recorder_redrive.py` (new).

1. **Deterministic-ID retry (Round 3 item 6 correction):**
   - (a) Identical raw event redelivery is deterministic — bit-for-bit identical raw bytes produce the identical `disposal_id`.
   - (b) **Differently-encoded representations of a "same" key must NOT be asserted to collide.** Round 2's original test description incorrectly asserted two differently-encoded representations of what a human might consider "the same" key should produce the same `disposal_id`. This is wrong and was removed: different raw bytes are different hash inputs and are *expected and required* to produce *different* `disposal_id` values.
   - (c) Key-parsing/decoding (identity extraction) is tested entirely separately from identity-hash determinism — the two concerns must never be conflated in one test case.
2. **Unequal-collision:** two contrived source-identity inputs producing the same `disposal_id` — assert the integrity-failure disposition (category f), not silent duplicate-acceptance (category e); assert the mismatch is detected against the persisted source-identity fields, not disposal facts alone.
3. **DynamoDB provenance, every branch:** wrong stream identity (assert unknown/incompatible, category d — not valid-but-irrelevant); `eventName != REMOVE` (valid-but-irrelevant, b); non-service-origin `userIdentity` (valid-but-irrelevant, b); missing `OLD_IMAGE`; `OLD_IMAGE` missing/invalid `evidence_class`; and the full positive case.
4. **Real S3 EventBridge fixtures (Round 3 items 3/4):** built from the actual `Object Deleted` envelope, including `account`, `detail["event-version"]` (corrected field name), and `detail.requester`; positive/negative cases for MAJOR/MINOR semver compatibility; positive/negative cases for the combined `reason`+`requester` provenance rule; flagged for reconciliation against a real staging capture.
5. **Permanently-deleted vs. delete-marker:** `"Permanently Deleted"` produces a record; `"Delete Marker Created"` is valid-but-irrelevant (b); an unrecognized `deletion-type` fails closed as unknown/incompatible (d), not valid-but-irrelevant.
6. **Marker-prefix and unknown-prefix exclusion, distinguishable dispositions:** `retention-markers/` → valid-but-irrelevant (b); unrecognized prefix → unknown/incompatible (d) — assert these are distinguishable, not the same outcome reached two ways.
7. **EventBridge two-layer filtering:** an event that would fail the rule-level `EventPattern` is independently rejected by the handler's own defense-in-depth validation when constructed as a fixture bypassing the rule.
8. **Malformed-event failure:** unparseable fields or missing `version-id` → malformed target-provenance (c), routed for retry/recovery, never silently dropped as valid-but-irrelevant.
9. **Failure-plane wiring, one test per plane — five planes total, plane (iv) restored (Round 11 item 2):** (i) EventBridge `DeadLetterConfig` fires on simulated delivery failure → DLQ; (ii) Lambda async `OnFailure` fires on simulated S3-path invocation failure → DLQ; (iii) DynamoDB ESM `OnFailure` fires on simulated retry exhaustion → **recovery bucket**, never DLQ; **(iv) (new, Round 11) the ESM's own attempt to write to the recovery bucket itself failing — distinct from (iii) — asserting `DroppedEventCount > 0`**; a fifth, distinct plane — the recovery bucket's own notification-rule failure — asserted to fire `EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm`, distinct from plane (i)'s alarm. All five asserted independently, never inferred from one shared mock; (iii)/(iv) specifically asserted to be distinguishable.
10. **Recovery-bucket notification-rule wiring, consistently scoped:** an infra-configuration assertion confirming the rule's own `RetryPolicy`, its inclusion as one of exactly two authorized rule ARNs in the DLQ's `QueuePolicy`, and the notification alarm's scoping are all mutually consistent.
11. **Native payload-preserving destination and redrive:** a simulated failed batch delivered via the native `OnFailure` mechanism, read by a simulated redrive invocation, reprocessed via the shared processing function; a case where some records were already recorded before the original failure asserts duplicate-verification resolves them as confirmed duplicates, not re-writes.
12. **Recovery-bucket security configuration:** an infra-configuration test asserting `PublicAccessBlockConfiguration`, the `aws:SecureTransport`-deny bucket policy, and the Lifecycle rule structure (no numeric duration, no tag-filter) are present.
13. **Partial-batch behavior, same-batch redelivery, same-shard blocking (Round 4 item 2 restatement) — five assertions:**
    - (a) the function's own returned lowest-failed sequence number becomes the checkpoint boundary directly;
    - (b) the records from that boundary onward are exactly what the *next invocation's own batch* contains — never assumed to be a single cleanly-isolated poison record;
    - (c) the test validates the actual remaining-payload content of the next invocation directly (record identities/sequence numbers, not merely a count);
    - (d) same-shard records remain blocked until either the checkpoint advances or the sub-batch exhausts its retry budget and routes to the failure destination — assert both resolution paths;
    - (e) other shards remain completely unaffected and continue processing independently.
    And, unchanged: a simulated redelivery of an already-successfully-recorded later record resolves to a confirmed idempotent duplicate (e), never a duplicate write or error.
14. **IAM containment (Round 3/4 corrections):** negative assertions that `EvidenceDisposalRecorderLambdaRole` grants no `s3:GetObject`/`DeleteObject` on any evidence-class prefix or the recovery bucket; positive assertions that `s3:PutObject`/`s3:ListBucket` **are** granted on the recovery bucket with the `s3:ResourceAccount` condition; positive assertion that `dynamodb:ListStreams` **is** granted as its own `Resource: "*"` statement; a redrive-credential assertion confirming the redrive command constructs its S3 client from the operator's own resolved credentials, never from the recorder's execution role.
15. **Recursion prevention:** `DisposalRepository.put_disposal_record`'s own `PutItem` must never be misclassified as a new TTL `REMOVE` (structurally guaranteed, tested explicitly regardless); a recovery-bucket object deletion must never be delivered to the recorder's S3-path event source (asserted via the EventBridge rule's own bucket-name constraint).
16. **Duplicate deliveries, general case:** ordinary at-least-once redelivery of a single already-recorded event resolves to a confirmed idempotent duplicate (e).
17. **End-to-end happy path, both sources:** a genuine TTL disposal and a genuine S3 Lifecycle permanent-deletion disposal each produce exactly one correctly-populated `DisposalRecord`.
18. **Deployment-to-CLI configuration ordering:** `validate_disposal_recorder_config` resolves and passes **before** the redrive command's `GetObject` call is reached; a malformed/placeholder config short-circuits before `AwsClientFactory` construction.
19. **Structural validation, one positive + at least one negative per rule**, plus the Round 7–9 additional fixtures: commercial-partition-lock negative fixtures for both ARN fields; variable-precision stream-label positive fixtures (3-digit and non-3-digit/absent fractional seconds) plus a non-date/time-shaped negative fixture; **two independently-named reserved-suffix negative fixtures — `--x-s3` and `-an` — never merged into one test case** (Round 9 item 1).
20. **Cross-field region consistency, bound to `StageConfig.region` (Round 7 item 1 — three independently-named checks, not one pairwise check):** (a) positive, all three pass; (b) negative, ARN-vs-ARN mismatch; (c) negative, **"wrong-stage-region"** — both ARNs agree with each other but disagree with `StageConfig.region` (new, distinct defect class); (d) negative, account mismatch.
21. **Stream table-identity match against `StageConfig.audit_metadata_table`:** positive and negative (wrong-table) fixtures.
22. **Redrive identity-mismatch rejection, one test per configured identity check — four dedicated negative tests** (citation corrected from "item 19" to "item 22" at Round 7 item 6(b), after Round 6 inserted new items 18–21 ahead of these): (a) ESM-UUID mismatch in the key prefix; (b) `requestContext.functionArn` mismatch; (c) `DDBStreamBatchInfo.streamArn` mismatch; (d) per-record `eventSourceARN` mismatch within an otherwise-matching envelope.

**Source:** TD §22.13 in full (all Round 2–11 corrections applied in place, as cited inline above).

---

## 8. Gates (Item g)

**Gate 5 (Implementation Authorization Gate) is now SATISFIED — Product Strategy's "IMPLEMENTATION AUTHORIZED" disposition explicitly opens it, and downstream engineering work (branch creation, code, tests, infrastructure changes) against the authorized inventory in §5 above (33 files as originally planned, 35 as-implemented per §5.6) is authorized, subject to the Required Implementation Controls stated near the top of this document. Gate 6 (Post-Implementation QA Sign-off) is now also SATISFIED — see Gate 6 below. Separately, and unaffected by either Gate 5's or Gate 6's opening, no production activation should occur until Gate 7 (Pre-Activation Validation Gate) is explicitly opened by Product Strategy — Gate 7 remains CLOSED.** The seven gates below are independent checkpoints, not a single combined gate: satisfying one does not open any other. In particular, Gate 1's satisfaction did not, by itself, open Gates 2–7 — each gate's own disposition is what opened it, most recently Gate 5's "IMPLEMENTATION AUTHORIZED" disposition and Gate 6's own `[QA SIGN-OFF APPROVED]`. This document's purpose is now twofold: it consolidates what is already merged into the documentation baseline, and it serves as the authoritative implementation plan for the work Gate 5 has authorized. It performs no independent architecture or security review beyond what Gates 2/3 already recorded, and it grants no QA sign-off itself — Gate 6's own QA sign-off has since been separately obtained (`[QA SIGN-OFF APPROVED]`, recorded in `docs/qa/a1_4a_disposal_recorder_test_report.md`; see Gate 6 below) and Gate 7's pre-activation validation remains independently required and outstanding.

### Gate 1 — Product Strategy Gate — **SATISFIED**
**Governs:** the ADR Decision 13 / TD §22 architecture-correction TEXT itself — the eleven-round documentation correction cycle recorded in the ADR's Status-section governance notes (lines 36–124).
**Must be true before opening:** the documentation correction carrying the full Round 1–11 history reviewed and merged into `main` through this repository's normal PR process.
**Current state:** **SATISFIED.** PR #130 (merge commit `bb92a9d`) and PR #131 (merge commit `dea3c19`), which together carry this documentation correction through its full Round 1–11 history, were each independently reviewed and approved through this repository's normal PR process and merged into `main`. That approval and merge constitute Product Strategy's acceptance of the corrected architecture DOCUMENTATION as the authoritative baseline for ADR Decision 13 / TD §22. **This gate governs the documentation text only. Its satisfaction does NOT open any of the other six gates below** — including, specifically, Gate 5 (Implementation Authorization Gate) and Gate 7 (Pre-Activation Validation Gate).

### Gate 2 — Architecture Review Gate — **SATISFIED**
**Must be true before opening:** an independent `architecture-reviewer` review of the corrected design, per this project's Review Board Policy (architecture review is triggered by API contracts, persistence strategy, infrastructure, and ADR-worthy decisions — all present here), distinct from Product Strategy's own review cycle that satisfied Gate 1.
**Current state:** **SATISFIED.** Confirmed by the Round 13 review disposition ("Architecture Review — SATISFIED"), which explicitly states "No architecture or security blocker remains." This gate governs the corrected design only, distinct from Gate 1 (documentation-text approval) and Gate 5 (implementation authorization) — its satisfaction does not open either of those.

### Gate 3 — Security Design Review Gate — **SATISFIED**
**Governs:** the IAM/security ARCHITECTURE as documented — not an implementation. Consistent with this project's Review Board Policy (security review is triggered by authentication/authorization/secrets/credentials/permissions work — all present here) and consistent with the same SDLC sequencing Gate 2 (Architecture Review) already follows, this is a design-level review performed BEFORE implementation, not after.
**Must be true before opening:** an independent `security-reviewer` review of the corrected design as currently documented in ADR Decision 13 / TD §22 — the IAM role shape (`EvidenceDisposalRecorderLambdaRole`), the redrive-credential model, and the recovery bucket's access/encryption/notification design — since the documented shape has itself been corrected eleven times on exactly these dimensions (least-privilege scope, `s3:ResourceAccount` condition, redrive-credential separation).
**Current state:** **SATISFIED.** Confirmed by the Round 13 review disposition ("Security Design Review — SATISFIED"), which explicitly states "No architecture or security blocker remains."
**Note:** satisfying this gate reviews the DESIGN only. It does not substitute for, and is not substituted by, Gate 7's implemented-security re-validation below — design review and implementation-validated review are two distinct checkpoints. Gate 7 item 1's implemented-security re-validation is still required at pre-activation time regardless of this gate's satisfaction.

### Gate 4 — QA-Plan Approval Gate — **SATISFIED**
**Must be true before opening:** an explicit disposition approving `docs/qa/a1_4a_disposal_recorder_test_plan.md` itself as adequate pre-implementation acceptance criteria.
**Current state:** **SATISFIED.** The Round 14 Final Planning Disposition ("APPROVED") explicitly approved `docs/qa/a1_4a_disposal_recorder_test_plan.md` as adequate pre-implementation acceptance criteria — that disposition is this gate's approval evidence. **This gate's satisfaction is distinct from `[QA SIGN-OFF APPROVED]` (Gate 6), which still requires implementation to exist and the offline/unit/static suite to actually execute and pass — Gate 4 approves the test *plan*, not test *results*.**

### Gate 5 — Implementation Authorization Gate — **SATISFIED**
**Must be true before opening:** Product Strategy's explicit, separate authorization to begin A1.4a implementation (branch creation, code, tests, infrastructure), per the ADR's own repeated "This is a documentation-only correction... it does not authorize A1.4a implementation" statement, restated at the close of every one of the eleven rounds.
**Current state:** **SATISFIED.** Confirmed by the Gate 5 disposition ("IMPLEMENTATION AUTHORIZED"), which explicitly grants Product Strategy's authorization to begin A1.4a implementation — branch creation, code, tests, and infrastructure changes against the authorized inventory (§5 above: 33 files as originally planned, 35 as-implemented per §5.6, both individually authorized), subject to the Required Implementation Controls stated near the top of this document. **This is the gate that actually permits `dev-backend`/`dev-frontend` dispatch and branch creation — both are now authorized.** Satisfying Gates 1–4 did not, by itself, open this gate — Gate 5's own disposition is the evidence that opens it. **This gate's satisfaction authorized implementation only, and did not itself open Gate 6 or Gate 7. Gate 6 has since been separately satisfied (see Gate 6 below, `[QA SIGN-OFF APPROVED]`). Gate 7 (Pre-Activation Validation Gate) remains CLOSED and must be satisfied independently before deployment or production activation may proceed.**

### Gate 6 — Post-Implementation QA Sign-off Gate — **SATISFIED**
**Governs:** the **offline/unit/static-testable subset** of the §22.13 matrix (22 items, §7 above) only — every item executable without real deployed AWS infrastructure or real staging credentials. This corresponds to the companion QA plan's "(A) Static Implementation QA" category and its unit-test coverage areas (c) through (j). This subset explicitly **includes** item 9's own offline/static-configuration-wiring component (the simulated/mocked per-plane assertions in item 9 itself, plus the corresponding infra-configuration wiring checks — the companion QA plan's TC-P1 through TC-P5) but explicitly **excludes** item 9's staging-behavioral-firing proof — the "a real AWS-triggered failure condition actually fires the named metric/alarm/routing" component — which is not testable offline and is Gate 7's own job (its Staging Failure-Plane Validation Checkpoint, below), not this gate's.
**Must be true before opening:** actual test execution against real implemented code — the offline/unit/static-testable subset of the §22.13 matrix described above (all 22 items, item 9 scoped to its static-wiring component only) executed and passing in full — culminating in this project's `[QA SIGN-OFF APPROVED]` status, per project CLAUDE.md's QA Gate convention. **`[QA SIGN-OFF APPROVED]` under this gate attests to the offline/unit/static subset only. It does NOT attest to, and must not be read as covering, item 9's staging-behavioral-firing proof — that remains Gate 7's own, separately-evidenced requirement (see Gate 7 item 2 and "Full §22.13 Matrix Closure" below).**
**Current state:** **SATISFIED.** `docs/qa/a1_4a_disposal_recorder_test_report.md` records `[QA SIGN-OFF APPROVED]` (§16.6 — the current, authoritative sign-off section; it supersedes an earlier §15 sign-off that was returned to CLOSED/PENDING REVALIDATION during HITL review and then explicitly re-earned, not merely carried over, in §16). Full offline/unit/static suite: 2218 passed, 2 skipped, 0 regressions, 0 failures — independently re-run and confirmed by the orchestrating session, not accepted on report text alone. A combined implemented architecture/security review additionally returned "APPROVED WITH CONCERNS (non-blocking)" — no blocking finding, two advisory tracking recommendations (Serverless Framework upgrade fragility note; open the pre-existing, unfixed `s3.yml`/`custody_periods.json` double-stage-reference defect as its own tracked item). Neither review found any issue requiring a code change.

### Gate 7 — Pre-Activation Validation Gate — **CLOSED**
**Gated behind:** Gate 5 (Implementation Authorization) and Gate 6 (Post-Implementation QA Sign-off) — implementation and unit-level QA sign-off must both be complete before Gate 7's staging-based validation can even begin. Gate 5 and Gate 6 are now both SATISFIED; Gate 7 itself remains CLOSED — no staging deployment, no real AWS credentials, and no staging-based validation of any kind have been performed. Gate 7's own satisfaction is what actually permits production activation (see §10 below).
**Must be true before opening — all three required, each against the REAL, deployed-to-staging implementation:**
1. **Implemented-security re-validation:** a second `security-reviewer` pass against the actually-implemented IAM role, redrive-credential resolution, and recovery-bucket configuration in staging — confirming the real implementation matches the corrected design Gate 3 reviewed, and that no new gap was introduced during implementation. Gate 3's satisfaction does not substitute for this — design review and implementation-validated review are two distinct checkpoints, not one.
2. **Staging failure-plane behavioral validation (the "Staging Failure-Plane Validation Checkpoint"):** the five failure planes' (§6 above) real AWS-emitted CloudWatch metrics/alarms, DLQ/recovery-bucket routing, and the two AWS-fact ambiguities flagged in the companion QA plan's §7 must be behaviorally confirmed against a real deployed staging stack. This project's own static/offline infra-configuration checks — this implementation plan's own inventory-based verification (§11 above), and the companion QA plan's "Static Implementation QA" category — are necessary but are NOT behavioral proof; only a real triggered failure condition against real AWS infrastructure constitutes behavioral proof. **This checkpoint is specifically what supplies §22.13 item 9's staging-behavioral-firing proof — the component Gate 6 explicitly excludes from its own scope (see Gate 6 above).** Its passage, together with Gate 6's own passage, is what constitutes "Full §22.13 Matrix Closure" below.
3. **Operator effective-permission evidence:** documented, captured evidence (e.g. an IAM policy simulation or an actual `GetObject` call against the real staging operator identity) proving the real staging operator credentials can access the intended recovery bucket and are denied access to an unrelated/wrong bucket. Cross-reference the companion QA plan's TC-I6 for the mechanism, but this Gate requires REAL captured evidence from staging, not merely a passing unit test against a mocked `AccessDenied`.

**Current state:** **CLOSED** — not yet performed. Gate 5 and Gate 6 are now both SATISFIED, but Gate 7 requires its own three, separately-evidenced, staging-based requirements above — none of which has been attempted.

### Full §22.13 Matrix Closure — derived status, not an eighth gate
**This is not a separate gate.** It is a derived status that becomes true only once BOTH of the following have independently passed:
- Gate 6 (offline/unit/static-testable subset of the §22.13 matrix, including item 9's static-configuration-wiring component), **and**
- Gate 7's Staging Failure-Plane Validation Checkpoint (item 2 above — item 9's real staging-behavioral-firing proof).

**Current state:** **NOT ACHIEVED.** Gate 6 is now SATISFIED; Gate 7 remains CLOSED. `[QA SIGN-OFF APPROVED]` (this project's CLAUDE.md convention) attaches to Gate 6's own offline/unit/static scope only — it does not, by itself, mean Full §22.13 Matrix Closure has been reached. Full §22.13 Matrix Closure still requires Gate 7's Staging Failure-Plane Validation Checkpoint to separately and additionally pass. No new project-wide status label is introduced by this term; it is a bookkeeping description of "both Gate 6 and Gate 7's item 2 have independently passed," used to avoid ambiguity about what §22.13 item 9's closure actually requires.

---

## 9. Custody-Duration Confirmation (Item h)

**Confirmed: no custody-duration numeric value is selected or introduced anywhere in this implementation plan, its source ADR, or its source Technical Design section.**

This has been an explicit, recurring non-scope statement across every one of the eleven correction rounds — every round's closing paragraph in the ADR's Status section states, verbatim or near-verbatim, "No custody-duration numeric value is introduced by this amendment" (Rounds 2 through 11; Round 1's own closing statement is the earlier "no numeric value is assigned"). Concretely:

- `config/custody_periods.json`'s new `operational_durations.disposal_recovery` key (§5.1 item 4 above) remains unconfigured (`{}`) — confirmed by direct read of the file's current content, which now contains seven keys (the six pre-existing keys plus `operational_durations.disposal_recovery` itself, added by this implementation), none populated with a duration value.
- Every duration referenced in §22 (the recovery bucket's own Lifecycle `Days` value, `operational_durations.disposal_recovery`) is described only by its **configuration source and mechanism**, never by a selected number.
- This implementation plan selects, proposes, or implies no such number either.

---

## 10. Explicit Out-of-Scope Statement (Item j)

The following are **not authorized, addressed, or advanced** by this implementation plan:

- **A1.4c** — not addressed. Note: no subphase labeled "A1.4c" is defined anywhere in the current ADR or Technical Design (confirmed by direct search — zero occurrences of the string "A1.4c" in either document). It is listed here as explicitly out-of-scope per this implementation plan's own instructions, but readers should not infer from its presence in this list that A1.4c is an established, scoped subphase; if a future A1.4c title is defined, it is a separate, not-yet-authorized planning artifact.
- **A1.4d** — not addressed. This label *is* used in the source material, referring to a hypothetical, not-yet-authorized historical-backfill subphase (`StartingPosition: LATEST` vs. `TRIM_HORIZON` reasoning, TD §22.10 / ADR Decision 13). No such subphase is defined in scope or content beyond this one forward reference.
- **A2** — not addressed (referenced only as a boundary marker elsewhere in this workstream's governance notes, e.g. ADR line 32).
- **Issue #118** ("Phase 5–7 persistence partial-success and stale Job-state hardening") — not addressed; explicitly out of scope per TD lines 1756/1764/1766, unrelated to A1.4a's own subject matter.
- **Custody-duration value selection** — not addressed; see §9 above.
- **Deployment** — not addressed. No deployment action, AWS credential use, or AWS API call is authorized or performed by this implementation plan or its source corrections (every round's own closing statement: "documentation-only correction... does not authorize A1.4a implementation").
- **Activation** — not addressed. `evidenceDisposalRecorder` is now present as a function block in `infra/serverless.yml`, but only locally on branch `feature/a1_4a-disposal-recorder` — not committed, not merged to `main`, and not deployed to any AWS environment. Production activation additionally requires Gate 7 (Pre-Activation Validation Gate, §8 above) to be explicitly opened by Product Strategy — Gate 5 (Implementation Authorization) and Gate 6 (Post-Implementation QA Sign-off) together do not permit activation.

---

## 11. Repository State — Pre-Implementation Baseline (Historical) and Current Post-Implementation State

### 11.1 Pre-Implementation Baseline (Historical Record — Not the Current State)

The following facts, asserted throughout §22 as the "confirmed defect" baseline, were independently re-verified against the repository as it stood **at the time this section was originally written** (`main`, `dea3c191`, before any A1.4a implementation existed) as part of producing this implementation plan, and all confirmed the merged text's own assumptions held at that time. **This table is preserved here as the historical planning-time record. Implementation is now complete on branch `feature/a1_4a-disposal-recorder` (uncommitted, not merged to `main`, not deployed) — do not read the "Confirmed" column below as describing the current state of the repository. See §11.2 immediately below for the corrected, current-tense status of each row.**

| Assertion (pre-implementation) | Verified at the time this was written |
| --- | --- |
| `evidence_retention/disposal_recorder.py` does not exist | Confirmed — no such file |
| `evidence_retention/disposal_recorder_redrive.py` does not exist | Confirmed — no such file |
| `apps/backend/handlers/evidence_disposal_recorder_handler.py` does not exist | Confirmed — no such file |
| `infra/resources/evidence-disposal-recorder-iam.yml` does not exist | Confirmed — no such file |
| `infra/resources/evidence-disposal-recovery-bucket.yml` does not exist | Confirmed — no such file |
| `infra/resources/evidence-disposal-recorder-outputs.yml` does not exist | Confirmed — no such file |
| `infra/serverless.yml`'s `resources:` list has exactly the six pre-existing imports (`s3.yml`, `dynamodb.yml`, `iam.yml`, `phase4-aggregation-iam.yml`, `scheduler.yml`, `evidence-retention-dlq.yml`) | Confirmed |
| `infra/serverless.yml` defines exactly four functions (`coreEngineOrchestrator`, `scheduledExecution`, `auditFinalization`, `auditAggregation`) — no `evidenceDisposalRecorder` | Confirmed |
| `DisposalRepository.get_disposal_record`/`_get_item` have no `consistent_read` parameter | Confirmed — no occurrence of `consistent_read` in `disposal_repository.py` |
| `identity.py::generate_disposal_id()` is still `f"{DISPOSAL_ID_PREFIX}{uuid.uuid4().hex}"` | Confirmed |
| `StageConfig.REQUIRED_FIELDS` has ten entries (not the fourteen A1.4a would add) | Confirmed |
| `config/custody_periods.json` has exactly six keys, all empty, no `operational_durations.disposal_recovery` | Confirmed |

### 11.2 Current State (Post-Implementation, Branch `feature/a1_4a-disposal-recorder`)

A1.4a implementation is now complete on this branch. **None of the following has been committed, merged into `main`, or deployed to any AWS environment** — consistent with Gate 6 (§8 below), which is SATISFIED for the offline/unit/static-testable subset only, and Gate 7, which remains CLOSED (no staging deployment, no production activation). Corrected, current-tense status for each row above:

| Assertion (pre-implementation baseline, §11.1 above) | Current state |
| --- | --- |
| `evidence_retention/disposal_recorder.py` does not exist | Implemented; present in the working tree on `feature/a1_4a-disposal-recorder`. Not committed. Not merged to `main`. Not deployed. |
| `evidence_retention/disposal_recorder_redrive.py` does not exist | Implemented; present in the working tree. Not committed. Not merged to `main`. Not deployed. |
| `apps/backend/handlers/evidence_disposal_recorder_handler.py` does not exist | Implemented; present in the working tree. Not committed. Not merged to `main`. Not deployed. |
| `infra/resources/evidence-disposal-recorder-iam.yml` does not exist | Implemented; present in the working tree. Not committed. Not merged to `main`. Not deployed. |
| `infra/resources/evidence-disposal-recovery-bucket.yml` does not exist | Implemented; present in the working tree. Not committed. Not merged to `main`. Not deployed. |
| `infra/resources/evidence-disposal-recorder-outputs.yml` does not exist | Implemented; present in the working tree. Not committed. Not merged to `main`. Not deployed. |
| `infra/serverless.yml`'s `resources:` list has exactly the six pre-existing imports | Superseded — the list now has nine entries: the original six plus the three new Pass 0/Pass 2 import lines (§2 above). Uncommitted; not merged; not deployed. |
| `infra/serverless.yml` defines exactly four functions... no `evidenceDisposalRecorder` | Superseded — a fifth function block, `evidenceDisposalRecorder`, is now present (§1/§2 above). Uncommitted; not merged; not deployed. |
| `DisposalRepository.get_disposal_record`/`_get_item` have no `consistent_read` parameter | Superseded — both now accept a `consistent_read` parameter (§5.1 item 2 above). Uncommitted; not merged; not deployed. |
| `identity.py::generate_disposal_id()` is still `f"{DISPOSAL_ID_PREFIX}{uuid.uuid4().hex}"` | Still accurate — unchanged. `disposal_recorder.py`'s own in-file commentary confirms `generate_disposal_id()` is NOT reused or extended by A1.4a; disposal-ID generation for this workstream is a distinct mechanism, not a modification of `identity.py`. |
| `StageConfig.REQUIRED_FIELDS` has ten entries (not the fourteen A1.4a would add) | Superseded — now fourteen entries (ten original plus the four new disposal-recorder fields, §3.2 above). Uncommitted; not merged; not deployed. |
| `config/custody_periods.json` has exactly six keys, all empty, no `operational_durations.disposal_recovery` | Superseded — the file now has seven keys; `operational_durations.disposal_recovery` exists and remains unconfigured (`{}`) — no custody-duration value is introduced (§9 below still holds). Uncommitted; not merged; not deployed. |

---

## 12. Cross-Reference Index

| Plan item | Primary source |
| --- | --- |
| (a) Seven-step render sequence | TD §22.9.5, Round 8 item 4 / Round 11 item 1 |
| (b) Three fragment imports | TD §22.9.5, §22.11, §22.14, Round 6 item 3 / Round 11 item 1 |
| (c) Logical-ID discovery / validation | TD §22.9.5 in full; §22.9.3; ADR Invariant 51 |
| (d) 33-file inventory (35 as-implemented, §5.6) | TD §22.14 in full; ADR Round 11 governance note (line 120) |
| (e) Five failure planes | TD §22.8, §22.9.1–§22.9.4; ADR Invariants 44/45 |
| (f) QA acceptance matrix | TD §22.13 in full |
| (g) Gates | ADR Status-section governance notes (lines 36–124), all eleven dispositions |
| (h) No custody-duration value | ADR Status-section, every round's closing statement; `config/custody_periods.json` |
| (i) Revision/traceability | ADR lines 36–124; TD §22 lines 2072–2079 (stale) vs. §22.9.5/§22.10/§22.11/§22.13/§22.14 (current) |
| (j) Out-of-scope | TD lines 1756/1764/1766 (issue #118); TD §22.10 (A1.4d reference); ADR line 32 (A2 reference) |

**Companion identity/event/recovery/IAM contract:** ADR Decision 13 (lines 367–396); Non-Negotiable Invariants 38–51 (lines 440–456); `DisposalRecord` schema amendment at TD §7.3 (lines 205–251).
