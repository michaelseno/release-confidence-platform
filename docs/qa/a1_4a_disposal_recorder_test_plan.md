# Test Plan

> **STATUS: IMPLEMENTATION COMPLETE — GATE 6 SATISFIED. THIS DOCUMENT REMAINS THE ACCEPTANCE-CRITERIA
> PLAN; EXECUTED RESULTS LIVE IN THE TEST REPORT, NOT HERE.**
> A1.4a implementation is complete on branch `feature/a1_4a-disposal-recorder` (not yet committed, not
> merged, not deployed). `docs/qa/a1_4a_disposal_recorder_test_report.md` records `[QA SIGN-OFF
> APPROVED]` (§16.6 — the current, authoritative sign-off; supersedes an earlier §15 sign-off returned
> to CLOSED/PENDING REVALIDATION during HITL review and explicitly re-earned in §16, not carried over)
> — the unit/static acceptance suite (2218 passed, 2 skipped, 0 regressions) and the complete
> repository suite (2394 passed, 2 skipped, 0 regressions) both executed and passed against the real
> implementation files this document previously described as future. **This document itself remains a
> plan, not a report** — it is not retroactively
> converted into a record of execution; it continues to define the acceptance criteria the test report
> is checked against. **Gate 6 — Post-Implementation QA Sign-off Gate is now `SATISFIED`** (offline/
> unit/static subset only, item 9 scoped to its static-configuration-wiring component — item 9's
> staging-behavioral-firing proof remains **Gate 7**'s own Staging Failure-Plane Validation Checkpoint,
> not yet performed — see the companion implementation plan's §8 for the full seven-gate list).
> `[QA SIGN-OFF APPROVED]` attests to Gate 6's offline/unit/static scope only — it does not, by itself,
> constitute "Full §22.13 Matrix Closure" (a derived status, not an eighth gate, requiring both Gate 6
> and Gate 7's Staging Failure-Plane Validation Checkpoint to independently pass; see the companion
> implementation plan's §8). No deployment, AWS mutation, or production activation has occurred.

## 1. Feature Overview

**Gate cross-reference:** this document's own approval status is governed by **Gate 4 — QA-Plan
Approval Gate** (`SATISFIED` — approved by the Round 14 Final Planning Disposition, which
explicitly approved this document as adequate pre-implementation acceptance criteria; distinct from
`[QA SIGN-OFF APPROVED]`/Gate 6, which required implementation to exist and this document's
offline/unit/static suite to actually execute and pass — both now done) within the
seven-gate structure the companion
`docs/backend/a1_4a_disposal_recorder_implementation_plan.md` §8 defines and tracks
authoritatively (Gate 1 — Product Strategy Gate: `SATISFIED`; Gate 2 — Architecture Review Gate:
`SATISFIED` — confirmed by this round's Product Strategy disposition, which states "No architecture
or security blocker remains"; Gate 3 — Security Design Review Gate: `SATISFIED` — likewise confirmed
by this round's Product Strategy disposition ("No architecture or security blocker remains"); a
pre-implementation design-level review, mirroring Gate 2's own timing, not an "as-implemented"
review; Gate 4 — QA-Plan
Approval Gate: `SATISFIED` — approved by the Round 14 Final Planning Disposition; Gate 5 —
Implementation Authorization Gate: `SATISFIED` — Product Strategy's Gate 5 disposition, "IMPLEMENTATION
AUTHORIZED," satisfies this gate; Gate 6 —
Post-Implementation QA Sign-off Gate: `SATISFIED` — `[QA SIGN-OFF APPROVED]` recorded in
`docs/qa/a1_4a_disposal_recorder_test_report.md` §16.6 (the current, authoritative sign-off section;
supersedes an earlier §15 sign-off returned to CLOSED/PENDING REVALIDATION during HITL review and
explicitly re-earned, not carried over, in §16), for the
offline/unit/static-testable subset of the §22.13 matrix, item 9 scoped to its
static-configuration-wiring component only (item 9's staging-behavioral-firing proof is Gate 7's own
Staging Failure-Plane Validation Checkpoint, not this gate's, and remains not yet performed); Gate 7 — Pre-Activation Validation
Gate: `CLOSED` — bundles implemented-security re-validation, staging failure-plane
behavioral validation, and operator effective-permission evidence, all requiring real staging
evidence, gated behind Gates 5 and 6). This document does not restate that gate-by-gate breakdown;
§8 of the companion implementation plan is the single authoritative source for gate status.

A1.4a (implementation authorized by Gate 5, `SATISFIED`, per Product Strategy's "IMPLEMENTATION
AUTHORIZED" disposition, and now complete — Gate 6, `SATISFIED`, `[QA SIGN-OFF APPROVED]`; see the
gate cross-reference above) builds `evidenceDisposalRecorder`: an
event-driven Lambda that consumes DynamoDB Streams `REMOVE` events (TTL-driven disposal of
`MetadataTable` governed records) and S3 EventBridge `Object Deleted` notifications (Lifecycle
permanent-deletion of `RawResultsBucket` evidence objects), and durably records each as a
`DisposalRecord` — the compliance-facing evidence-disposal audit trail FR-A1-5 requires. This plan
covers the corrected target design established by:

- **ADR:** `docs/architecture/adr_evidence_retention_disposal_enforcement.md`, Decision 13
  ("Disposal-Recorder Identity, Event, Recovery, and IAM Architecture Correction"), Non-Negotiable
  Invariants 38–51.
- **Technical Design:** `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`,
  §22 (all of §22.1–§22.14), a documentation-only correction to the recorder's target behavior —
  authorizing no code, test, or infrastructure change itself, but defining the contract this plan
  tests against. **Correction currency note:** §22's own front-matter "Revision history" paragraph
  narrates only Rounds 1–6; the ADR's Status-section governance notes and §22's own body
  (§22.9.5/§22.10/§22.11/§22.13/§22.14) are corrected through **Round 11** — see the companion
  `docs/backend/a1_4a_disposal_recorder_implementation_plan.md` §0 for the full
  discrepancy record. **Two distinct facts about Round 11's status, stated side by side rather than
  collapsed into one (mirroring the companion implementation plan's own §0 correction):**
  1. **No individual round's own Product Strategy disposition was ever "APPROVED."** Round 11 — the
     last round present in the merged text — closed "RETURN FOR TARGETED CORRECTION — Medium Risk,"
     not "APPROVED." This shows the documentation kept evolving even after Round 11; no round's own
     disposition should be read as a standalone green light.
  2. **Separately, PR #130 (merge commit `bb92a9d`) and PR #131 (merge commit `dea3c19`) — which
     together carry this documentation correction through its full Round 1–11 history — were each
     independently reviewed and approved through this repository's normal PR process and merged into
     `main`.** That approval and merge constitute Product Strategy's acceptance of the corrected
     architecture DOCUMENTATION as the authoritative baseline — this is **Gate 1 (Product Strategy
     Gate) — SATISFIED**, per the companion implementation plan's §8.

  Neither fact, standing alone, constituted authorization to implement A1.4a — that authorization is
  the separate **Gate 5 (Implementation Authorization Gate)**, now `SATISFIED` per Product Strategy's
  Gate 5 disposition, "IMPLEMENTATION AUTHORIZED." This plan's test cases are
  written against the Round-11-corrected TD/ADR text, which **is** the approved, merged, authoritative
  baseline — not against Round 6.

**This is an Evidence Governance Workstream A1 artifact (A1.4a subphase) — a cross-cutting compliance
workstream, not gated by or associated with the platform's numbered Phase 0–8 roadmap.** ("Evidence
Governance Workstream A1," which contains A1.4a, is separate from the platform's Phase 0–8 roadmap
numbering; the TD's own front matter self-describes as "Proposed — Workstream A1 Planning
Deliverable," never as a numbered platform phase, and the platform's own "Phase 4A" — lineage-manifest
pagination, already completed — is an unrelated concept.)

**All four A1.4a docs/QA-records now exist** — this test plan, the companion
`docs/backend/a1_4a_disposal_recorder_implementation_plan.md`,
`docs/backend/a1_4a_disposal_recorder_implementation_report.md`, and
`docs/qa/a1_4a_disposal_recorder_test_report.md` (§16.6, `[QA SIGN-OFF APPROVED]`). **Implementation
is also now complete** — every file listed below (both subsections) exists in the working tree on
branch `feature/a1_4a-disposal-recorder`. None of it is committed, merged to `main`, or deployed.

**Files under test** — retained below in its original "New" vs. "Modified" planning-time split for
traceability to the approved 33/35-file inventory (`docs/backend/a1_4a_disposal_recorder_implementation_plan.md`
§5), even though the distinction is no longer about existence (all files now exist) but about
implementation history — full inventory at TD §22.14:

**New files at planning time (implemented; now present in the working tree, uncommitted):**

- `src/release_confidence_platform/evidence_retention/disposal_recorder.py` — shared
  event-classification/identity/provenance/disposition logic, called by both the live handler and
  the redrive command.
- `apps/backend/handlers/evidence_disposal_recorder_handler.py` — thin Lambda entrypoint.
- `src/release_confidence_platform/evidence_retention/disposal_recorder_redrive.py` —
  `rcp retention disposal-recorder redrive` command logic.
- `infra/resources/evidence-disposal-recorder-iam.yml`, `evidence-disposal-recovery-bucket.yml`,
  `evidence-disposal-recorder-outputs.yml`.
- `tests/unit/test_evidence_disposal_recorder_handler.py` — not part of the original 33-file
  inventory; created during QA-gap closure (TC-H2–TC-H6) and individually authorized by Product
  Strategy as the 35th inventory file (implementation plan §5.6).

**Modified files at planning time (already existed before A1.4a; now changed by the implementation):**

- `src/release_confidence_platform/evidence_retention/models.py` — `DisposalRecord` gains
  seven source-identity fields + a source-kind-conditional validator.
- `src/release_confidence_platform/evidence_retention/disposal_repository.py` —
  `consistent_read` parameter on `get_disposal_record`/`_get_item`; extended `put_disposal_record`.
- `src/release_confidence_platform/evidence_retention/commands.py`,
  `operator_cli/main.py`, `operator_cli/result.py` — redrive CLI wiring.
- `src/release_confidence_platform/config/stage_config.py` — four new `StageConfig`
  fields, `validate_disposal_recorder_config`.
- `infra/serverless.yml`, `infra/resources/dynamodb.yml`, `infra/resources/evidence-retention-dlq.yml`,
  `config/custody_periods.json`, `config/stages/{dev,staging,prod}.json`.

No numeric custody-duration value, deployment action, or AWS mutation is authorized or implied by
this plan, matching the ADR/TD's own documentation-only scope.

## 2. Acceptance Criteria Mapping — TD §22.13 Future QA Acceptance Matrix (Requirement Area a)

TD §22.13 defines 22 required test-category items for A1.4a implementation. Every item is mapped
below to concrete test case(s), the ADR invariant it enforces, and validation method. Test-case IDs
use the `TC-Q<n>` scheme (Q for "matrix").

| §22.13 Item | ADR Invariant | Acceptance Criterion | Test Case(s) | Validation Method |
| --- | --- | --- | --- | --- |
| 1(a) | 38 | Identical raw event redelivery (bit-for-bit identical raw key bytes) produces identical `disposal_id`, both DynamoDB and S3 paths | TC-Q1a-DDB, TC-Q1a-S3 | Unit: two invocations of shared processing on the same fixture event → assert `disposal_id` equality |
| 1(b) | 38, 50 | Differently-encoded representations of a "same" key must **not** collide — asserted as a required negative case, not a bug | TC-Q1b | Unit: one raw-space-containing key, one `%20`-containing key → assert **different** `disposal_id` values |
| 1(c) | 48 | Key-parsing/decoding (§22.12) tested independently of identity-hash determinism — never conflated | TC-Q1c | Unit: parser test suite is structurally separate from TC-Q1a/TC-Q1b; independent verification that no shared fixture/assertion couples the two |
| 2 | 39, 49 | Unequal-collision: two different source-identity inputs contrived to produce the same `disposal_id` resolve to integrity-failure (category f), not silent duplicate-acceptance (category e); mismatch detected against persisted source-identity fields, not disposal facts alone | TC-Q2 | Unit: monkeypatch/fixture-forced hash collision on `put_disposal_record`; assert category (f) disposition and that the detecting comparison includes `source_stream_identity`/`source_object_key` etc. |
| 3 | 40 | DynamoDB provenance — every branch: wrong stream identity (unknown/incompatible, category d — not valid-but-irrelevant); `eventName != REMOVE` (valid-but-irrelevant, b); non-service-origin `userIdentity` (valid-but-irrelevant, b); missing `OLD_IMAGE`; invalid/missing `evidence_class` in `OLD_IMAGE`; full positive case | TC-Q3-a..f | Unit: one fixture + assertion per branch against §22.4's 5-element exact-match rule |
| 4 | 41 | Real S3 EventBridge fixtures using corrected `detail["event-version"]` field name (not `detail.version`), `account`, `detail.requester`; semver MAJOR/MINOR positive+negative cases; combined `reason`+`requester` provenance negative case | TC-Q4-a..e | Unit: fixture-driven, explicitly flagged pending staging-capture reconciliation (see §22.5.1's own confirmation-required note) |
| 5 | 41 | `"Permanently Deleted"` → `DisposalRecord`; `"Delete Marker Created"` → valid-but-irrelevant (b); unrecognized `deletion-type` → unknown/incompatible (d), not valid-but-irrelevant | TC-Q5-a..c | Unit: three fixtures, one per `deletion-type` value class |
| 6 | 42, 43 | `retention-markers/` prefix → valid-but-irrelevant (b); unrecognized prefix → unknown/incompatible (d) — asserted as **distinguishable** dispositions | TC-Q6-a, TC-Q6-b | Unit: two fixtures, assert disposition category differs |
| 7 | 41 | EventBridge two-layer filtering: an event that would fail the rule-level `EventPattern` is independently rejected by handler-side defense-in-depth (§22.5.3) when constructed to bypass the rule | TC-Q7 | Unit: fixture bypasses simulated rule-level filter entirely; handler must still reject |
| 8 | 43 | Malformed event (recordable shape, unparseable fields / missing `version-id`) → malformed target-provenance (c), never silently dropped as valid-but-irrelevant | TC-Q8-a, TC-Q8-b | Unit |
| 9 | 44, 45 | Failure-plane wiring — five planes, each independently asserted, (iii)/(iv) distinguishable — **offline/static-wiring component only; see note below table** | TC-P1..TC-P5 (Requirement Area b, §3.2) | Infra-configuration + unit, per plane |
| 10 | 44, 45 | Recovery-bucket notification-rule wiring consistency: `RetryPolicy`, DLQ `QueuePolicy` 2-rule-ARN membership, alarm scoping — mutually consistent, not merely each present | TC-Q10 | Infra-configuration test |
| 11 | 45, 51 | Native payload-preserving destination + redrive: simulated failed batch → recovery bucket → redrive reprocesses correctly; partial-pre-recorded-records case resolves via duplicate-verification, not re-write | TC-G1..TC-G4 (Requirement Area g, §3.7) | Unit |
| 12 | 45 | Recovery-bucket security configuration: `PublicAccessBlockConfiguration`, `SecureTransport`-deny policy, Lifecycle rule shape (no numeric duration, no tag-filter) | TC-Q12 (cross-references TC-G10 as authoritative — see note below table), TC-G10 (§3.7 — also where the SSE-S3 encryption assertion specifically lives) | Infra-configuration test (`test_infra_configuration.py` convention) |
| 13 | 46 | Partial-batch/bisection contract — 5 sub-assertions (a)–(e) per §22.10's corrected contract, plus item 13's own trailing "And, unchanged:" sentence on same-batch redelivery of already-successful records | TC-H2–TC-H6 (Requirement Area h, §3.8) | Unit, simulated event-source-mapping behavior |
| 14 | 47 | IAM containment — negative assertions (no `s3:GetObject`/`DeleteObject` on evidence prefixes or recovery bucket) and positive assertions (`s3:PutObject`+`ListBucket`+`s3:ResourceAccount` condition; `dynamodb:ListStreams` restored as separate `Resource:"*"` statement); redrive-credential-source assertion | TC-I1..TC-I6 (Requirement Area i, §3.9 — corrected this round; TC-I6 was added last round but this row was never updated) | Infra-configuration test + documented manual-review fallback where automation is infeasible (TD's own stated either/or — see §7 Ambiguities) |
| 15 | — | Recursion prevention: (1) `DisposalRepository.put_disposal_record`'s own `PutItem` never misclassified as a new TTL `REMOVE`; (2) recovery-bucket object deletion never delivered to the recorder's S3-path event source | TC-Q15a, TC-Q15b | Unit |
| 16 | 39 | Duplicate deliveries, general case: ordinary at-least-once redelivery → confirmed idempotent duplicate (e) | TC-Q16 | Unit |
| 17 | 38, 39, 40, 41 | End-to-end happy path, both sources: exactly one correctly-populated `DisposalRecord`, no manual mocking of identity computation | TC-Q17-DDB, TC-Q17-S3 | Unit (integration-shaped, within `tests/unit/`) |
| 18 | 51 | `validate_disposal_recorder_config` resolves and fails closed **before** `AwsClientFactory` construction and before any AWS call, for both placeholder and structurally-malformed fixtures (negative path, TC-G5); AND, positively, a valid well-formed configuration passes validation and `AwsClientFactory` construction genuinely depends on/follows successful validation, not merely happens to run after it (TC-G5-pos, new this correction round) | TC-G5, TC-G5-pos (Requirement Area g) | Unit, ordering assertion |
| 19 | 51 | Structural validation: 1 positive + ≥1 negative fixture per each of 4 regex patterns, plus commercial-partition-lock, variable-precision stream-label, and two independently-named reserved-suffix (`--x-s3`, `-an`) fixtures | TC-G6 (single grouped ID per this document's Option B convention, §3.1 — full fixture enumeration at §3.7) | Unit |
| 20 | 51 | Cross-field region consistency — 4 cases: all-pass, ARN-vs-ARN mismatch, "wrong-stage-region" (ARNs agree, disagree with `StageConfig.region`), account mismatch | TC-G7 (single grouped ID; full fixture enumeration at §3.7) | Unit |
| 21 | 51 | Stream table-identity match against `StageConfig.audit_metadata_table` — positive + negative | TC-G8 (single grouped ID; full fixture enumeration at §3.7) | Unit |
| 22 | 51 | Redrive identity-mismatch rejection — one test per each of the 4 configured-identity checks (esm-uuid, function ARN, stream ARN, per-record `eventSourceARN`) | TC-G9 (single grouped ID; full fixture enumeration at §3.7) | Unit |

**Note on item 12's Test Case(s) column (this correction round):** `TC-Q12` (defined inline in this
table, §2's own definition location for the `TC-Q*` series) and `TC-G10` (§3.7) assert the identical
core recovery-bucket security posture — `PublicAccessBlockConfiguration`, the `SecureTransport`-deny
bucket policy, and the Lifecycle rule shape — but `TC-G10` is not an exact duplicate: it additionally
asserts the absence of `VersioningConfiguration` and the SSE-S3 `BucketEncryption` assertion added
last round, neither of which `TC-Q12`'s own definition above mentions. Rather than maintaining two
parallel, drifting definitions of largely the same check, `TC-Q12` is treated as a cross-reference to
`TC-G10` (§3.7) as the authoritative, more complete definition — `TC-Q12` is not implemented as a
second, separate test case; its row above exists only to preserve this table's §22.13-item-to-`TC-*`
mapping convention.

**Note on item 9's Test Case(s) column (this correction round — Gate 6/Gate 7 reconciliation):**
`TC-P1..TC-P5` (and `TC-P-wiring`, §3.2) constitute this document's own **offline/unit/static-testable**
coverage of item 9 — the component within the companion implementation plan's now-narrowed **Gate 6 —
Post-Implementation QA Sign-off Gate** scope. Item 9's own text additionally requires a
staging-behavioral-firing proof (a real AWS-triggered failure condition actually firing the named
metric/alarm/routing for each plane); that component is **not** testable offline, is **not** covered
by `TC-P1..TC-P5` or by Gate 6, and is instead **Gate 7**'s own Staging Failure-Plane Validation
Checkpoint (companion implementation plan §8). Item 9's row above, and this document generally, reflects only
this plan's (A) Static Implementation QA scope — see §3.2's Classification note for the full (A)/(B)
split. Item 9's full closure (part of "Full §22.13 Matrix Closure," a derived, non-gate status — see
companion implementation plan §8) requires both this document's own coverage **and** Gate 7's Staging
Failure-Plane Validation Checkpoint to independently pass; this document alone cannot claim it.

## 3. Test Scenarios — by Task Requirement Area

### 3.1 Area (a) — §22.13 Matrix Coverage

§2's table covers the **offline/unit/static-testable portion** of the §22.13 matrix — every item
this document's own pre-implementation scope can test without real deployed AWS infrastructure or
real staging credentials. Item 9's own staging-behavioral-firing proof is explicitly carved out of
that coverage: that component is not testable offline, is not covered by §2's table or by this
document at all, and remains **Gate 7**'s own responsibility (its Staging Failure-Plane Validation
Checkpoint — see §3.2(B) and the companion implementation plan's §8). §2's table is not, and must not be read as,
"covered in full" standing alone. **This correction round found and fixed an internal counting
inconsistency in this section, described below before restating the count.**

**The inconsistency (identified this correction round):** most series in this document — `TC-C*`,
`TC-D*`, `TC-E*`, `TC-F*`, `TC-H*`, and `TC-I*` (except `TC-I6`, addressed below) — enumerate one
distinct top-level ID per individual fixture (e.g. `TC-E1` through `TC-E13` are 13 separate IDs for 13
separate fixtures). `TC-G6` through `TC-G9`, however, do **not** follow this convention: each is
**one** top-level ID in its own §3.7 table row, yet its own assertion text bundles multiple distinct
fixtures under that single ID — `TC-G6` alone bundles **≥13** fixtures; `TC-G7` bundles **4** fixtures
(a)–(d); `TC-G8` bundles **2** fixtures (a)–(b); `TC-G9` bundles **≥6** fixtures (one per each of the
six numbered runtime checks its own §3.7 row defines — narrower than this, §2 item 22 maps
specifically to only 4 of these six, the identity-mismatch checks). This made the prior round's "96
distinct TC-* IDs" headline non-comparable across series — an ID-count that silently undercounts
`TC-G6`–`TC-G9`'s actual fixture volume relative to how `TC-E1`–`TC-E13`/`TC-H2`–`TC-H6`/etc. are
counted, while implying one uniform unit of coverage per ID.

**Resolution chosen — Approach B (keep grouped IDs; make every count explicit about fixture-count vs.
ID-count), not Approach A (exploding `TC-G6`–`TC-G9` into lettered sub-IDs):** exploding
`TC-G6`–`TC-G9` into `TC-G6a`–`TC-G6n`/`TC-G7a`–`TC-G7d`/etc. would force renumbering `TC-G10`/`TC-G11`
and every existing cross-reference to `TC-G7(b)`/`TC-G7(c)`/`TC-G9(c)`/`TC-G9(d)` elsewhere in this
document (§4 Edge Cases), for a benefit that is purely cosmetic — the underlying fixtures are already
fully enumerated in §3.7's own table cells either way. Approach B is chosen as lower-risk and equally
honest: `TC-G6`–`TC-G9` remain single grouped IDs, but every count claim below states both the
ID-count and the fixture-count explicitly, and the headline total is recalculated as a precise
**ID-count**, stated as such, never presented as directly comparable to a fixture-level count.

**Recalculated total: 22 §22.13 items → 109 distinct top-level `TC-*` IDs** (an ID-count, not a
fixture-count — see below; up from 106 last round, net +3 from this round's TC-J8/TC-J9
parameterization into per-field sub-cases — see §3.10 and the note below). Recalculated by direct
enumeration (not estimate) of every distinct top-level `TC-*` identifier appearing in §2's own table
(the `TC-Q*` series, which has no separate §3.x home — §2 **is** its authoritative definition) and in
each of §3.2 through §3.10's own tables (the authoritative definition location for
`TC-P*`/`TC-C*`/`TC-D*`/`TC-E*`/`TC-F*`/`TC-G*`/`TC-H*`/`TC-I*`/`TC-J*`), counting each ID exactly
once and never double-counting a §2 cross-reference (e.g., item 9 → `TC-P1..TC-P5`, item 11 →
`TC-G1..TC-G4`, item 12 → `TC-Q12`/`TC-G10` cross-reference — see §2's note below its table —
`TC-Q12` counted once under `TC-Q*`, `TC-G10` counted once at its own §3.7 home, never double-counted
as one check, item 13 → `TC-H2–TC-H6`, item 14 → `TC-I1..TC-I6`, item 18 → `TC-G5`/`TC-G5-pos`,
items 19–22 → `TC-G6..TC-G9`) against the same ID already counted at its §3.x home:

| Series | Home | ID-Count | Members | Fixture-count note |
| --- | --- | --- | --- | --- |
| `TC-Q*` | §2 (own definition; letter/number-suffixed ranges are the sole definition, so each suffix is a distinct ID) | 31 | Q1a-DDB, Q1a-S3, Q1b, Q1c, Q2, Q3-a..f (6), Q4-a..e (5), Q5-a..c (3), Q6-a/b (2), Q7, Q8-a/b (2), Q10, Q12*, Q15a/b (2), Q16, Q17-DDB/S3 (2) | *`Q12` cross-references `TC-G10` (§2's item-12 note) and is not separately implemented; counted once here per the identifier-counting convention, not double-counted at `TC-G10` |
| `TC-P*` | §3.2 | 11 | P1-pos/neg .. P5-pos/neg (10) + P-wiring (1) | 1 ID = 1 fixture throughout this series |
| `TC-C*` | §3.3 | 6 | C1–C6 | 1 ID = 1 fixture throughout this series |
| `TC-D*` | §3.4 | 5 | D1–D5 | 1 ID = 1 fixture throughout this series |
| `TC-E*` | §3.5 | 13 | E1–E13 | 1 ID = 1 fixture throughout this series |
| `TC-F*` | §3.6 | 6 | F1–F6 | 1 ID = 1 fixture throughout this series |
| `TC-G*` | §3.7 | 12 | G1–G4, G5, **G5-pos** (new, this correction round), G6, G7, G8, G9, G10, G11 | **Not 1:1** — `G6` = 1 ID, ≥13 fixtures; `G7` = 1 ID, 4 fixtures; `G8` = 1 ID, 2 fixtures; `G9` = 1 ID, ≥6 fixtures; every other `TC-G*` ID = 1 fixture |
| `TC-H*` | §3.8 | 7 | H1–H7 | 1 ID = 1 fixture throughout this series |
| `TC-I*` | §3.9 | 6 | I1–I6 (`I6` bundles 3 sub-parts — (a) documentation deliverable, (b) mocked-unit-test, (c) real-staging evidence (new, this correction round) — under 1 ID) | `I6` = 1 ID, 3 sub-parts (not fully comparable "fixtures" — (a)/(c) are not unit tests); every other `TC-I*` ID = 1 fixture |
| `TC-J*` | §3.10 (new last round — Invariant 49 model-validator coverage; **J8/J9 parameterized into per-field sub-cases this correction round**) | 12 | J1–J7 (7), J8a–J8c (3, one per forbidden S3-only field — `source_bucket`/`source_object_key`/`source_object_version_id`), J9a–J9b (2, one per forbidden DynamoDB-only field — `source_stream_identity`/`source_event_id`) | 1 ID = 1 fixture throughout this series (unlike `TC-G6`–`TC-G9`, `J8`/`J9` were genuinely exploded into distinct top-level sub-IDs this round, not merely enumerated within one ID — each forbidden field independently proven forbidden per Invariant 49's fail-closed requirement) |
| **Total** | | **109** | | ID-count; see fixture-count notes per series — not directly comparable across series |

**This total is an ID-count, not a fixture-count, and is not claimed to be apples-to-apples comparable
across series** — a fixture-level count would be strictly higher than 109, with `TC-G6` alone
contributing at least 13 fixtures under its single ID (and `TC-G7`/`TC-G8`/`TC-G9` contributing
4/2/≥6 respectively), a count this plan has never claimed is closed and does not close now (the prior
text's own "stated as 19a–n to allow implementation-time expansion" framing for `TC-G6` is preserved
in substance). Readers comparing series-to-series coverage volume should use the fixture-count notes
in the table above, not the raw per-series ID-count column alone.

### 3.2 Area (b) — Five Separate Failure Planes (ADR Decision 13, Invariant 44; TD §22.8/§22.9.2/§22.9.4)

Each plane requires independent configuration and its own automated observability signal per ADR
Invariant 44 — "a design that configures only one of the [planes] and asserts the others are covered
by it does not satisfy this invariant." No plane's test may be satisfied by another plane's mock.

| Plane | Trigger | Routing | Metric/Alarm | TC (Positive) | TC (Negative) |
| --- | --- | --- | --- | --- | --- |
| (i) EventBridge→Lambda delivery failure | EventBridge rule fails to invoke the Lambda (e.g. resource-policy denial, retry exhaustion) | `evidenceDisposalRecorderDLQ` via rule-level `DeadLetterConfig` | `InvocationsFailedToBeSentToDlq` (EventBridge) + `evidenceDisposalRecorderDLQAlarm` | TC-P1-pos: simulated delivery failure lands a message on the DLQ | TC-P1-neg: a successful delivery must **not** trigger this plane's alarm |
| (ii) Lambda async-invoke failure, S3 path | Lambda invoked, invocation itself fails (unhandled exception/timeout/throttle) | `evidenceDisposalRecorderDLQ` via `DestinationConfig.OnFailure` | `DestinationDeliveryFailures` (Lambda, async-invoke-destination instance) + `Errors`/`Throttles` | TC-P2-pos | TC-P2-neg: a successful async invocation must not populate this plane's DLQ path |
| (iii) DynamoDB event-source-mapping processing failure | Streams-path batch exhausts retry budget | **Dedicated recovery bucket** (never `evidenceDisposalRecorderDLQ`) via ESM `DestinationConfig.OnFailure` | `OnFailureDestinationDeliveredEventCount` (positive-path confirmation; requires `MetricsConfig: {Metrics:["EventCount"]}` enabled, TD §22.10) | TC-P3-pos: simulated retry exhaustion → object lands in recovery bucket, **not** the DLQ | TC-P3-neg: assert no message reaches `evidenceDisposalRecorderDLQ` via this plane under any circumstance — a design that lets plane (iii) fall back to the DLQ fails this invariant outright |
| (iv) Failure writing to the failure destination itself | ESM's own attempt to write to the recovery bucket fails | No further fallback destination in this design | `DroppedEventCount` (silent-loss signal) | TC-P4-pos: simulated destination-write failure → `DroppedEventCount` increments | TC-P4-neg: a batch that succeeds at recovery-bucket delivery must not register on `DroppedEventCount` |
| (v) Recovery-bucket notification delivery failure (new, Round 4 item 7 — distinct from (i)–(iv)) | Recovery bucket's own `Object Created` → EventBridge → DLQ notification rule (`EvidenceDisposalRecoveryBucketObjectCreatedRule`) fails to deliver | N/A (this is itself the notification path) | `EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm` on this rule's own `FailedInvocations`, **distinct** from plane (i)'s alarm | TC-P5-pos: simulated delivery failure of this specific rule fires its own dedicated alarm | TC-P5-neg: assert plane (i)'s alarm does **not** fire from this rule's failure — the two alarms must be independently scoped and never conflated |

**TC-P-wiring** (single consistency test, maps to §22.13 item 10): assert `RetryPolicy`
(`MaximumRetryAttempts: 10`, `MaximumEventAgeInSeconds: 3600`) on the plane-(v) rule, its inclusion
as one of exactly two authorized rule ARNs in `evidence-retention-dlq.yml`'s `QueuePolicy`, and its
alarm's `RuleName` scoping — asserted together, not merely each independently present.

**Classification note (flagged — see §7), corrected: two explicitly separate categories, not one
blended category.** Plane verification splits into (A) this document's own pre-implementation
sign-off scope, and (B) a distinct, later validation phase this document does not cover:

**(A) Static Implementation QA — this plan's actual pre-implementation-complete scope, unchanged in
substance.** TC-P1 through TC-P5 (and TC-P-wiring) are **infrastructure-configuration** assertions
(`tests/unit/test_infra_configuration.py` convention — asserting on rendered/raw
`infra/resources/*.yml` content), executable entirely offline with no AWS credentials, no AWS API
call, and no AWS mutation. Where TD §22.13 item 9 says "simulated," this plan interprets that as
configuration-correctness assertion (the destination/metric/alarm wiring is structurally correct)
plus, where the shared processing function's own code path is invoked (e.g., plane (iii)'s
recovery-bucket redrive path, which the recorder's application code does touch via redrive), a
genuine unit-level simulation. This is (A)'s full scope and is part of this document's own sign-off —
it corresponds exactly to the companion implementation plan's now-narrowed **Gate 6 — Post-Implementation QA
Sign-off Gate**, now `SATISFIED` (`[QA SIGN-OFF APPROVED]` recorded in
`docs/qa/a1_4a_disposal_recorder_test_report.md` §16.6), and is the entirety of what that sign-off
attests to.

**(B) Staging Failure-Plane Validation Checkpoint — a distinct, LATER validation phase, explicitly NOT
part of this document's pre-implementation sign-off scope, and explicitly required BEFORE any
production activation. This checkpoint is part of the companion implementation plan's §8 new Gate 7 —
Pre-Activation Validation Gate (renamed/reframed this correction round; formerly referenced only as
"Staging Operational Validation" gated behind Gate 5 alone) — and is specifically what supplies
§22.13 item 9's staging-behavioral-firing proof, the component Gate 6 explicitly excludes from its
own now-narrowed scope. Gate 6's passage together with this checkpoint's passage is what the
companion implementation plan's §8 terms "Full §22.13 Matrix Closure" — a derived status, not a separate gate,
that this document alone cannot achieve.** Stated plainly, near the top of this
subsection: **(A)'s static, offline infra-configuration assertions are necessary — they prove the
wiring is structurally correct — but they are NOT behavioral proof: only a real triggered failure
condition against real deployed AWS infrastructure, captured in this checkpoint, proves the failure
planes actually work.** Before `evidenceDisposalRecorder` is activated in any environment beyond
staging, the following must be verified against a real deployed staging stack, with real AWS
credentials:

- each of the five failure planes' real AWS-emitted CloudWatch metrics/alarms actually fires under a
  real triggered failure condition — not merely that the configuration exists (which is all (A)
  proves);
- the DLQ and recovery bucket actually receive real routed messages/objects under real AWS
  failure-destination behavior;
- the two flagged AWS-fact ambiguities from §7 (item 1: exact `deletion-type` string literals,
  percent-encoding behavior, etc.; item 2: plane (ii)/(iii) `DestinationDeliveryFailures`
  metric-instance distinguishability) are re-confirmed against real captured staging events before
  being treated as settled;
- **TC-I6(c) (new, this correction round; cross-ref §3.9's TC-I6 row):** actual captured
  effective-permission evidence from the REAL staging operator identity — e.g. an
  `aws iam simulate-principal-policy` result or an actual `GetObject`/`HeadObject` call against real
  staging infrastructure — proving (i) the real operator identity IS allowed `s3:GetObject` on the
  intended, correctly-configured recovery bucket, and (ii) the same real operator identity IS DENIED
  `s3:GetObject` on at least one unrelated/wrong bucket. This is a real-staging-evidence requirement,
  not a pre-implementation unit-test requirement, and is distinct from TC-I6(a)'s documentation
  deliverable (which lives in the companion implementation plan, §5.5 — not a new
  `docs/operator-cli/` artifact) and TC-I6(b)'s mocked-`AccessDenied` unit test —
  §3.9 and this bullet must not drift; both cross-reference the other. This captured evidence is
  recorded in **the test report** (`docs/qa/a1_4a_disposal_recorder_test_report.md`), the
  already-inventoried document (companion implementation plan §5.5) that is the eventual home for
  executed-test/captured-evidence artifacts.

This checkpoint requires real AWS credentials and a deployed staging stack, is gated behind **Gate 7
— Pre-Activation Validation Gate** (itself gated behind Gate 5 — Implementation Authorization Gate —
and Gate 6 — Post-Implementation QA Sign-off Gate, per the companion implementation plan's §8) and successful
completion of (A), and is itself a prerequisite before activation. (B)'s captured evidence belongs
exclusively to the existing `docs/qa/a1_4a_disposal_recorder_test_report.md` — the **sole, exclusive
destination** for all Gate 7 captured evidence (implemented-security re-validation findings, staging
failure-plane behavioral results, and operator effective-permission evidence alike). That report
already exists (§16.6 records this document's own Gate 6 `[QA SIGN-OFF APPROVED]`); future Gate 7
evidence will be appended to that existing report, not to a new document. No separate,
dedicated staging validation campaign document is authorized for this workstream — introducing one
would be an unauthorized artifact outside the companion implementation plan's §5.5/§5.6 35-file inventory, which
contains no such document.
This document's own scope is limited to (A); (B) is
out of scope here and must not be read as implied coverage. This document's own
`[QA SIGN-OFF APPROVED]` (Gate 6, already issued — §16.6) accordingly attests to (A) only, never to "Full §22.13 Matrix
Closure," which requires (B) — Gate 7's Staging Failure-Plane Validation Checkpoint — to separately
and additionally pass.

### 3.3 Area (c) — Deterministic Identity (ADR Invariant 38; TD §22.2)

| TC | Path | Assertion |
| --- | --- | --- |
| TC-C1 | DynamoDB TTL | Canonical JSON hash input = `{source_kind: "dynamodb_ttl_remove", disposal_id_scheme: "v1", stream_identity: <eventSourceARN>, event_id: <eventID>}`, `sort_keys=True, separators=(",", ":")` — assert exact serialized byte string for a fixed fixture, not merely "hash exists" |
| TC-C2 | S3 Lifecycle | Canonical JSON hash input = `{source_kind: "s3_lifecycle_delete", disposal_id_scheme: "v1", bucket, key, version_id, reason, deletion_type}`, raw undecoded `key` — assert exact serialized byte string for a fixed fixture |
| TC-C3 | Both paths | `disposal_id` format is exactly `disp_v1_{64-hex-char sha256}` |
| TC-C4 | Both paths | Envelope `id` (EventBridge delivery ID) is excluded from the S3-path hash input — assert two fixtures differing only in envelope `id` produce identical `disposal_id` |
| TC-C5 | S3 path | Raw key hashed **exactly as received** — no percent-decoding performed as part of identity computation (distinct from and never sharing code with §22.12's parser decode step, per TC-Q1c) |
| TC-C6 (redelivery, cross-ref TC-Q1a) | Both paths | Same source event, two invocations → identical `disposal_id` |

### 3.4 Area (d) — Duplicate-Conflict Verification (ADR Invariant 39; TD §22.3)

| TC | Case | Assertion |
| --- | --- | --- |
| TC-D1 | Confirmed idempotent duplicate | `ConditionalCheckFailedException` on `put_disposal_record` → strongly-consistent read-back via `get_disposal_record(..., consistent_read=True)` → every compared field matches (identity fields, seven source-identity fields, all immutable disposal facts) except `recorded_at` → acknowledge, no new write, no retry, no DLQ delivery (category e) |
| TC-D2 | `disposal_id` collision, unequal content | Read-back finds **any** single-field mismatch (including a source-identity-only mismatch with matching disposal facts) → integrity failure (category f) — never silently accepted, never resolved by a second overwriting `PutItem` |
| TC-D3 | Comparison scope | Assert the comparison explicitly includes `disposal_id_scheme`, `source_kind`, and the applicable source-identity fields — not disposal facts alone (the corrected Round 2 comparison surface); a test that only varies disposal facts and never source identity does not satisfy this invariant |
| TC-D4 | `recorded_at` exclusion | The **only** field excluded from comparison is `recorded_at`; assert a differing `recorded_at` alone does not trigger category (f) |
| TC-D5 | `get_disposal_record` contract | `consistent_read: bool = False` parameter added, default `False` preserved for existing callers (regression); recorder's own call passes `consistent_read=True` explicitly |

### 3.5 Area (e) — Provenance Rules (ADR Invariants 40, 41; TD §22.4, §22.5, §22.5.1–§22.5.3)

**DynamoDB TTL exact-match rule (5 elements, Invariant 40) — TC-E1..E5:**

| TC | Element | Positive | Negative |
| --- | --- | --- | --- |
| TC-E1 | 1. Expected stream identity | Correct `eventSourceARN` | Wrong stream/table ARN → **unknown/incompatible** (d), not valid-but-irrelevant |
| TC-E2 | 2. `eventName == "REMOVE"` | REMOVE | INSERT/MODIFY → valid-but-irrelevant (b) |
| TC-E3 | 3. Service-origin `userIdentity` | `type=="Service"`, `principalId=="dynamodb.amazonaws.com"` | Non-service-origin on genuine REMOVE → valid-but-irrelevant (b) |
| TC-E4 | 4. `OLD_IMAGE` present | Present | Absent, given 1–3 pass → malformed target-provenance (c) |
| TC-E5 | 5. `OLD_IMAGE` valid governed record | Category 1/2 `evidence_class`, PK/SK, creation-timestamp field present | Missing/invalid `evidence_class`, given 1–3 pass → malformed target-provenance (c) |

**S3 EventBridge envelope/provenance rule (Invariant 41) — TC-E6..E12:**

| TC | Check | Positive | Negative |
| --- | --- | --- | --- |
| TC-E6 | Envelope `source`/`detail-type` | `aws.s3`/`Object Deleted` | Wrong value → unknown/incompatible (d) |
| TC-E7 | `account` (both rule-level and handler-side) | Expected account | Mismatched account → unknown/incompatible (d) |
| TC-E8 | `detail["event-version"]` semver | MAJOR match + MINOR ≥ configured minimum (incl. a **higher**-minor fixture, accepted) | Wrong MAJOR; MINOR below minimum; unparseable version string → unknown/incompatible (d) |
| TC-E9 | `bucket.name` | Expected `RawResultsBucket` name | Wrong bucket → unknown/incompatible (d) |
| TC-E10 | Combined `reason`+`requester` corroboration | `reason=="Lifecycle Expiration"` **and** `requester=="s3.amazonaws.com"` together | `reason` correct but `requester` wrong/missing → unknown/incompatible (d) — a `reason`-only match must never be accepted as sufficient |
| TC-E11 | `object["version-id"]` presence | Present | Absent → malformed target-provenance (c) |
| TC-E12 | `deletion-type` (cross-ref TC-Q5) | `"Permanently Deleted"` exactly | `"Delete Marker Created"` → valid-but-irrelevant (b); any other value → unknown/incompatible (d) |
| TC-E13 | Two-layer defense-in-depth (cross-ref TC-Q7) | N/A | Handler independently re-validates every rule-level-filtered field even when a fixture is constructed to bypass the rule entirely |

### 3.6 Area (f) — Evidence-Prefix Restriction and Disposition Taxonomy (ADR Invariants 42, 43; TD §22.6, §22.7)

| TC | Requirement | Assertion |
| --- | --- | --- |
| TC-F1 | 4 evidence-class prefixes recordable | `raw-results/`, `intelligence/`, `reports/`, `integrity/` — each produces a `DisposalRecord` when otherwise valid |
| TC-F2 | `retention-markers/` excluded | Valid-but-irrelevant (b), never a `DisposalRecord`, never retry, never DLQ |
| TC-F3 | Unrecognized prefix | Unknown/incompatible (d) — **never** folded into valid-but-irrelevant (distinguishes from TC-F2; cross-ref TC-Q6) |
| TC-F4 | Recovery bucket structurally excluded | A recovery-bucket-originated event never reaches prefix evaluation at all — excluded at the EventBridge rule's own bucket-name constraint (cross-ref TC-Q15b) |
| TC-F5 | Six-disposition taxonomy exhaustiveness | Every one of the six dispositions (a–f) is independently reachable and distinguishable — no two dispositions may share one code path (e.g., (c) and (d) must not be collapsed; (e) and (f) must not be collapsed) |
| TC-F6 | Ordering is load-bearing | (a) only reached after (b)/(c)/(d) ruled out; (e)/(f) only reached from within (a)'s own write attempt — assert evaluation order via a fixture ambiguous between two categories resolves per the fixed precedence, not implementation-arbitrary order |

### 3.7 Area (g) — Payload-Preserving Recovery and Redrive (ADR Invariant 45, 51; TD §22.9–§22.9.5)

| TC | Requirement | Assertion |
| --- | --- | --- |
| TC-G1 | Native `OnFailure` S3 destination | ESM `DestinationConfig.OnFailure` targets the dedicated recovery bucket (infra-config test) — never `RawResultsBucket` |
| TC-G2 | Redrive reprocessing success | Simulated failed batch delivered to recovery bucket → `rcp retention disposal-recorder redrive` reads it → shared processing function produces correct `DisposalRecord`(s) — same function the live handler uses, not a parallel path |
| TC-G3 | Partial-pre-recorded redrive | Some records in the redriven batch already succeeded before the original failure → duplicate-verification path (§3.4) resolves them as confirmed duplicates, never re-writes |
| TC-G4 | Post-redrive retention | Recovery object is **not** deleted by the redrive command on success (operator credentials hold no `s3:DeleteObject`); left for the bucket's own Lifecycle rule |
| TC-G5 | Config validation ordering, negative/failure path (cross-ref §22.13 item 18) | `validate_disposal_recorder_config()` raises `DISPOSAL_RECORDER_CONFIG_ERROR` before `AwsClientFactory` construction, for both placeholder-shaped and structurally-malformed fixtures |
| TC-G5-pos | Config validation ordering, POSITIVE path (new, this correction round; cross-ref §22.13 item 18) | A valid, well-formed configuration fixture passes `validate_disposal_recorder_config()` successfully, AND `AwsClientFactory` construction is proven to genuinely depend on/follow successful validation — not merely happen to run after it by incidental code order — e.g. via an ordering-sensitive test double (a fake validator/factory pair recording call order, or an assertion that `AwsClientFactory` construction is unreachable/never invoked when validation is monkeypatched to raise) — proving dependency, not just observed sequence |
| TC-G6 | Structural regex validation (cross-ref §22.13 item 19) | 1 positive + ≥1 negative per pattern: `DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN` (incl. IPv4-shape, consecutive-periods, 3 reserved prefixes, 5 reserved suffixes, and the independently-documented `-an` suffix — 2 distinct fixtures, never merged into one test case), `DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN`, `DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN` (incl. commercial-partition lock — `aws-us-gov`/`aws-cn` rejected), `METADATA_TABLE_STREAM_ARN_PATTERN` (incl. variable-precision stream-label: 3-digit fixture, non-3-digit/no-fraction fixture, both accepted; non-date-shaped fixture rejected) |
| TC-G7 | Cross-field region consistency (cross-ref §22.13 item 20) | (a) all-agree positive; (b) ARN-vs-ARN mismatch; (c) "wrong-stage-region" — ARNs agree with each other but disagree with `StageConfig.region` (must name **both** region-vs-`StageConfig.region` rules, must **not** name the ARN-vs-ARN rule); (d) account mismatch |
| TC-G8 | Stream table-identity (cross-ref §22.13 item 21) | Positive: stream ARN's `table_name` == `StageConfig.audit_metadata_table`; negative: otherwise-valid, same-account/region stream ARN naming a different table |
| TC-G9 | Redrive envelope/provenance validation — construction-time guarantee + 6 runtime checks | Bucket name is never a CLI argument (construction-time; no `--bucket` flag exists in `disposal_recorder_redrive.py`'s argument parser — structural/AST-level check); 6 runtime checks: (1) `aws/lambda/{esm-uuid}/...` key-prefix match against configured UUID; (2) `requestContext.functionArn` match; (3) envelope `version` supported; (4) `DDBStreamBatchInfo.streamArn` match; (5) `payload` exists and parses as genuine DynamoDB Streams shape; (6) per-record `eventSourceARN` match — one negative fixture per check (cross-ref §22.13 item 22), asserting fail-closed rejection **before** shared record processing is invoked |
| TC-G10 | Recovery-bucket security config (cross-ref §22.13 item 12) | `PublicAccessBlockConfiguration` all 4 flags true; `aws:SecureTransport`-deny bucket policy; Lifecycle rule with no numeric duration and no tag-filter; no `VersioningConfiguration`; **default server-side encryption — `BucketEncryption` with `SSEAlgorithm: AES256` (SSE-S3) — TD §22.9.2 already specifies this explicitly ("Server-side encryption: `BucketEncryption` with SSE-S3 (`AES256`) enabled by default, mirroring the platform's general default-encryption posture for S3 resources"); this was an omission in this plan's prior test coverage, not a TD gap** |
| TC-G11 | Recursion isolation (cross-ref §22.13 item 15b) | A recovery-bucket `Object Created` deletion event is rejected by the EventBridge rule's own bucket-name constraint — never delivered to the S3-path handler |

### 3.8 Area (h) — Batch/Retry/Bisection Contract (ADR Invariant 46; TD §22.10)

| TC | Parameter/Behavior | Assertion |
| --- | --- | --- |
| TC-H1 | Explicit parameter selection | `StartingPosition: LATEST` (never `TRIM_HORIZON`); `FilterCriteria` scoped to `eventName == "REMOVE"`; batch size 25; `MaximumRetryAttempts: 3`; `MaximumRecordAgeInSeconds: 72000`; `ParallelizationFactor: 1`; `MetricsConfig: {Metrics: ["EventCount"]}` — all present as explicit, non-default configuration (infra-config test) |
| TC-H2 | `ReportBatchItemFailures`/`BisectBatchOnFunctionError` corrected interaction | The function's own returned lowest-failed-sequence-number **is** the checkpoint/retry boundary directly — assert the simulated ESM checkpoints at that exact sequence number, not a separately-engaged bisection mechanism (§22.13 item 13(a)) |
| TC-H3 | Actual remaining-payload content | The next invocation's batch content (record identities/sequence numbers, not merely a count) matches the boundary-onward records exactly — multi-poison-record fixture, not a simplified single-poison-record model (§22.13 item 13(b)/(c)) |
| TC-H4 | Same-shard blocking, both resolution paths | Later records on the **same** shard remain blocked until either (i) checkpoint advances via a well-formed subsequent response, or (ii) the sub-batch exhausts its retry budget and routes to the recovery bucket — assert both paths (§22.13 item 13(d)) |
| TC-H5 | Cross-shard independence | A record on a **different** shard processes and checkpoints independently of the first shard's stalled state (§22.13 item 13(e)) |
| TC-H6 | Same-batch redelivery of already-successful records | A later, already-successfully-processed record in the same batch, redelivered due to checkpoint-at-lowest-failed-sequence, resolves via duplicate-verification (category e), never a duplicate write or error |
| TC-H7 | EventBridge/Lambda-async retry params, planes (i)/(ii) | Plane (i): `RetryPolicy.MaximumRetryAttempts: 10`, `MaximumEventAgeInSeconds: 3600`; Plane (ii): `RetryAttempts: 2`, `MaximumEventAgeInSeconds: 21600` — both present as explicit configuration (infra-config test) |

### 3.9 Area (i) — IAM Least-Privilege Boundaries (ADR Invariant 47; TD §22.11) — Security-Adjacent QA Check

**Scope note:** this is an existence/scope-of-grants check appropriate to QA sign-off gating, **not**
a substitute for a dedicated Security Review. Per this project's Review Board Policy, this is
**Gate 3 — Security Design Review Gate** (currently `SATISFIED` — confirmed by this round's Product
Strategy disposition, which states "No architecture or security blocker remains") — a
**pre-implementation, design-level** review of the IAM/security
architecture as currently documented in ADR Decision 13 / TD §22, performed BEFORE implementation,
mirroring Gate 2 (Architecture Review)'s own timing — **not** an "as-implemented" review, and not
gated on implementation existing. Gate 3's satisfaction does not substitute for the companion
package's §8 **Gate 7 — Pre-Activation Validation Gate**, whose own implemented-security
re-validation element separately re-reviews the actually-implemented IAM role, redrive-credential
resolution, and recovery-bucket configuration in staging. Implementation already exists locally on
branch `feature/a1_4a-disposal-recorder` (uncommitted, unmerged, undeployed); the outstanding
prerequisites for this re-validation are Gate 7's own authorization and a deployed staging
implementation to re-validate against — design review
and implementation-validated review are two distinct checkpoints, neither substituting for the
other. Gate 3 is separately triggered for A1.4a (the design touches IAM roles, dedicated-role
least-privilege boundaries, and a new credential-resolution path for redrive) and explicitly **out of
scope for this QA plan**.

| TC | Requirement | Assertion |
| --- | --- | --- |
| TC-I1 | Dedicated role, not shared block | `EvidenceDisposalRecorderLambdaRole` defined in its own `AWS::IAM::Role`, following the `AuditFinalizationLambdaRole`/`AuditAggregationLambdaRole` shape — never an expansion of `provider.iam.role.statements` |
| TC-I2 | Positive grants present | CloudWatch Logs scoped to own log group; `dynamodb:GetRecords`/`GetShardIterator`/`DescribeStream` scoped to `MetadataTable`'s stream ARN; `dynamodb:ListStreams` as its **own separate** statement, `Resource: "*"` (restored per Round 4 item 4 — must not be omitted); `DisposalRecord` `PutItem`/`GetItem` scoped to `MetadataTable`; `sqs:SendMessage` to `evidenceDisposalRecorderDLQ` (planes i/ii only); `s3:PutObject` scoped to the recovery-bucket object ARN **and** `s3:ListBucket` scoped to the recovery-bucket ARN, both carrying an `s3:ResourceAccount` (not `aws:ResourceAccount`) same-account condition |
| TC-I3 | Negative grants — never present, under any justification | No `s3:GetObject`/`DeleteObject` on the recovery bucket for this role; no `s3:GetObject`/`PutObject`/`DeleteObject` on any of the four evidence-class prefixes (`raw-results/*`, `intelligence/*`, `reports/*`, `integrity/*`) for this role; no `Query`/`UpdateItem`/`DeleteItem` on `MetadataTable` |
| TC-I4 | Redrive credential-source assertion | The redrive command's own construction path (`operator_cli/main.py`'s `disposal-recorder redrive` dispatch) constructs its S3 client from the operator's own resolved `AwsClientFactory` credentials — never from `EvidenceDisposalRecorderLambdaRole` and never a second, dedicated IAM role (this design provisions none) |
| TC-I5 | Resource-based mechanisms kept structurally separate | EventBridge's `lambda:InvokeFunction` permission is a resource-based `AWS::Lambda::Permission`, not a role-policy statement; the DLQ `QueuePolicy` scopes `sqs:SendMessage` to exactly two named rule ARNs, never a blanket grant |
| TC-I6 | Operator recovery-bucket read scoping — least-privilege template (documentation) + application-level fail-closed behavior (unit-testable) + real-staging effective-permission evidence (pre-activation), per §22.9.3/§22.9.5/§22.11 | **(a) Documentation/runbook deliverable, not IaC:** a documented, reviewable least-privilege IAM policy template/example for the operator's own CLI credentials — scoped to `s3:GetObject` on the specific configured recovery-bucket ARN only. **This deliverable lives in the companion implementation plan (`docs/backend/a1_4a_disposal_recorder_implementation_plan.md`, per that document's own §5.5 resolution) — never a new `docs/operator-cli/` artifact; the companion implementation plan is not a new addition to its own §5.5 33-file inventory, and a credential policy specification is a design/implementation artifact, not test-evidence, so it does not belong in this test plan or in the test report either.** This is required precisely because the redrive command uses the operator's own pre-existing CLI credentials, never a new deployable IAM role, so this policy is not part of this repository's provisioned infrastructure (`infra/*.yml` provisions `EvidenceDisposalRecorderLambdaRole` for the Lambda, not for the operator). **(b) Application-level fail-closed test (unit-testable):** when the redrive command's `GetObject` call raises a simulated `AccessDenied`/`ClientError` (e.g., because the operator's credentials don't have access to the actually-configured bucket, simulating a misconfiguration), the redrive command must surface this as an explicit, fail-closed `DisposalRedriveResult` rejection — never a silent partial success, never a crash with an unhandled exception, and never a fallback to a different bucket. **(c) Real-staging effective-permission evidence (new, this correction round — NOT a pre-implementation unit test; cross-ref §3.2(B)'s Staging Failure-Plane Validation Checkpoint / Gate 7 — Pre-Activation Validation Gate):** actual captured effective-permission evidence from the REAL staging operator identity — e.g. an `aws iam simulate-principal-policy` result or an actual `GetObject`/`HeadObject` call against real staging infrastructure — proving (i) the real operator identity IS allowed `s3:GetObject` on the intended, correctly-configured recovery bucket, and (ii) the same real operator identity IS DENIED `s3:GetObject` on at least one unrelated/wrong bucket. Requires real AWS credentials and a real deployed staging stack; gated behind Gate 7, not part of this document's own pre-implementation sign-off scope. **This captured evidence is recorded in `docs/qa/a1_4a_disposal_recorder_test_report.md`** — the test report is the eventual home for executed-test/captured-evidence artifacts, consistent with this document's own repeated framing (§1's STATUS banner; §3.2(B)) |

**Automation note (flagged — see §7):** TD §22.13 item 14 itself states IAM containment may be
"a policy-scope assertion test **or**, if infeasible to automate, a documented manual-review
requirement." This plan requires TC-I1–TC-I3, TC-I5 as automated infra-configuration assertions
(these inspect static YAML/rendered-template content, which is automatable per the established
`test_infra_configuration.py` convention) and accepts TC-I4 as a candidate for a documented
manual-review requirement if the operator-credential-resolution assertion proves infeasible to
automate against a fake `AwsClientFactory` — this fallback must be explicitly justified in the test
report, not silently substituted. **TC-I6 now splits across three explicitly distinct categories, not
two (corrected this round):** TC-I6(a) (the least-privilege IAM policy template for the operator's
own credentials) is a documentation/runbook deliverable, not an automatable test — it lives in **the
companion implementation plan** (`docs/backend/a1_4a_disposal_recorder_implementation_plan.md`),
never a new `docs/operator-cli/` artifact, and is checked for
existence and reviewability there, not executed; TC-I6(b) (the fail-closed `AccessDenied` rejection
behavior) is a genuine, automatable application-level unit test, mocking the redrive command's
`GetObject` call to raise a simulated `ClientError`; **TC-I6(c) (new, this correction round) is
neither** — it is real captured staging effective-permission evidence, gated behind **Gate 7 —
Pre-Activation Validation Gate** (companion implementation plan §8), out of scope for this document's own
pre-implementation QA sign-off, tracked in §3.2(B)'s Staging Failure-Plane Validation Checkpoint, and
recorded in **the test report** (`docs/qa/a1_4a_disposal_recorder_test_report.md`) once captured —
not executed as part of this plan's own unit-test suite.

### 3.10 Area (j) — Invariant 49 Model-Validator Coverage (new, this correction round; ADR Non-Negotiable Invariant 49; TD §7.3, §22.3)

Dedicated coverage for `DisposalRecord`'s seven new source-identity fields (`disposal_id_scheme`,
`source_kind`, `source_stream_identity`, `source_event_id`, `source_bucket`, `source_object_key`,
`source_object_version_id`) and the source-kind-conditional `model_validator(mode="after")` rule ADR
Invariant 49 (lines 440–456, specifically the "Source-kind-conditional validation" sentence at line
451) and TD §7.3 (lines 205–251, "Source-kind-dependent field validation" note) require: fields are
**required** when `source_kind` matches the relevant path, and must be **absent/forbidden** otherwise.
TD §22.3's "Required change to `DisposalRepository`" paragraph (line 2162) confirms `models.py`'s
`DisposalRecord` gains these seven fields and `disposal_repository.py`'s `put_disposal_record` write
path is extended to persist them. Not previously broken out as its own dedicated test-case
subsection — added this correction round.

| TC | Case | Assertion |
| --- | --- | --- |
| TC-J1 | Valid shape, DynamoDB path | `source_kind="dynamodb_ttl_remove"` with exactly `source_stream_identity` + `source_event_id` populated (non-`None`, non-empty) and all three S3-only fields (`source_bucket`, `source_object_key`, `source_object_version_id`) absent (`None`) → validation passes |
| TC-J2 | Valid shape, S3 path | `source_kind="s3_lifecycle_delete"` with exactly `source_bucket` + `source_object_key` + `source_object_version_id` populated and both DynamoDB-only fields (`source_stream_identity`, `source_event_id`) absent → validation passes |
| TC-J3 | Missing required field, DynamoDB path | `source_kind="dynamodb_ttl_remove"`, `source_stream_identity` absent, `source_event_id` present → validation fails |
| TC-J4 | Missing required field, DynamoDB path | `source_kind="dynamodb_ttl_remove"`, `source_event_id` absent, `source_stream_identity` present → validation fails |
| TC-J5 | Missing required field, S3 path | `source_kind="s3_lifecycle_delete"`, `source_bucket` absent, other two S3 fields present → validation fails |
| TC-J6 | Missing required field, S3 path | `source_kind="s3_lifecycle_delete"`, `source_object_key` absent, other two S3 fields present → validation fails |
| TC-J7 | Missing required field, S3 path | `source_kind="s3_lifecycle_delete"`, `source_object_version_id` absent, other two S3 fields present → validation fails |
| TC-J8a | Forbidden cross-source field, DynamoDB path — `source_bucket` | `source_kind="dynamodb_ttl_remove"`, both required DynamoDB fields present and correctly shaped, but forbidden S3-only field `source_bucket` is ALSO populated → validation fails |
| TC-J8b | Forbidden cross-source field, DynamoDB path — `source_object_key` | `source_kind="dynamodb_ttl_remove"`, both required DynamoDB fields present and correctly shaped, but forbidden S3-only field `source_object_key` is ALSO populated → validation fails |
| TC-J8c | Forbidden cross-source field, DynamoDB path — `source_object_version_id` | `source_kind="dynamodb_ttl_remove"`, both required DynamoDB fields present and correctly shaped, but forbidden S3-only field `source_object_version_id` is ALSO populated → validation fails |
| TC-J9a | Forbidden cross-source field, S3 path — `source_stream_identity` (symmetric case) | `source_kind="s3_lifecycle_delete"`, all three required S3 fields present, but forbidden DynamoDB-only field `source_stream_identity` is ALSO populated → validation fails |
| TC-J9b | Forbidden cross-source field, S3 path — `source_event_id` (symmetric case) | `source_kind="s3_lifecycle_delete"`, all three required S3 fields present, but forbidden DynamoDB-only field `source_event_id` is ALSO populated → validation fails |

**Source:** ADR Non-Negotiable Invariant 49 (lines 440–456); TD §7.3 field table (lines 205–251) and
its "Source-kind-dependent field validation" note; TD §22.3's "Required change to `DisposalRepository`"
paragraph (line 2162).

## 4. Edge Cases

- Bit-identical raw-key redelivery versus differently-percent-encoded "same" key (must NOT collide) — the single most consequential correctness distinction in this design (§22.2's Round 2 correction exists specifically because Round 1 got this backwards).
- A single Lifecycle evaluation cycle producing two EventBridge notifications in short succession for one object — one `"Delete Marker Created"` (not recordable) and, on a later cycle, one `"Permanently Deleted"` (recordable) for the same underlying object — assert no `DisposalRecord` is ever produced from the marker-creation notification, even under rapid succession.
- A DynamoDB Streams batch containing **multiple** genuinely poison records, not a single isolated one — the redelivery/checkpoint-boundary assertions (TC-H3) must be tested against this multi-record case, not simplified to one bad record.
- A `disposal_id` collision detected where **only** the source-identity fields differ and every disposal fact happens to match (TC-D3) — the scenario Round 2's comparison-surface correction exists specifically to catch; a test suite that only varies disposal facts would pass under both the pre- and post-correction comparison logic and would not actually prove the correction.
- An S3 EventBridge fixture with `reason == "Lifecycle Expiration"` and a **missing** `requester` field (not merely a wrong value) — both are required to fail the corroboration check identically (TC-E10).
- A redrive-validation fixture where `DDBStreamBatchInfo.streamArn` matches (check 4 passes) but a single per-record `eventSourceARN` within `payload` does not (check 6 fails) — proving these two checks are independent and neither subsumes the other (TC-G9(c) vs TC-G9(d)).
- A stage-configuration fixture where the two ARN fields agree with each other but both disagree with `StageConfig.region` — must be distinguished from an ARN-vs-ARN disagreement (TC-G7(b) vs TC-G7(c)); a validator that conflates these two failure modes into one error message does not satisfy Invariant 51's corrected cross-field contract.
- Recovery-bucket bucket-name resolution: a `StageConfig.disposal_recovery_bucket_name` misconfigured to point at some other bucket must fail closed, mandatorily covered across **three** distinct parts (TC-I6, cross-ref TC-I2/TC-I4), not punted as untestable — **(a) documentation layer:** a checked-in, least-privilege operator IAM policy template/example scoping `s3:GetObject` to the single, specific configured recovery-bucket ARN, living in the companion implementation plan (`docs/backend/a1_4a_disposal_recorder_implementation_plan.md`, per that document's own §5.5 resolution) — per §22.9.3/§22.9.5/§22.11's construction-time-guarantee correction, this is the actual enforcement boundary, since the redrive command uses the operator's own pre-existing credentials, never a new deployable IAM role this repository's `infra/*.yml` provisions; **(b) mocked fail-closed application-level unit test:** when the redrive command's `GetObject` call raises a simulated `AccessDenied`/`ClientError` — simulating exactly this misconfiguration — the command must reject fail-closed via an explicit `DisposalRedriveResult` outcome, never a silent partial success, an unhandled crash, or a fallback to a different bucket; **(c) real staging effective-permission evidence:** actual captured evidence from the REAL staging operator identity — proving the identity IS allowed `s3:GetObject` on the intended, correctly-configured recovery bucket and IS DENIED `s3:GetObject` on at least one unrelated/wrong bucket — captured against real deployed staging infrastructure and recorded in `docs/qa/a1_4a_disposal_recorder_test_report.md`, gated behind **Gate 7 — Pre-Activation Validation Gate** and explicitly out of scope for this document's own pre-implementation sign-off.
- A recovery bucket name ending in `-an` versus one ending in `--x-s3` — two independently-documented AWS reserved-suffix rules that must never share a single test fixture or assertion (TC-G6).

## 5. Test Types Covered

- **Unit tests** (`tests/unit/evidence_retention/test_disposal_recorder.py`,
  `test_disposal_recorder_redrive.py`, `tests/unit/config/test_stage_config.py`,
  `tests/unit/evidence_retention/test_disposal_repository.py`,
  `tests/unit/evidence_retention/test_models.py`) — the bulk of this plan's coverage: identity
  determinism, duplicate-conflict verification, provenance rules, disposition taxonomy, redrive
  envelope/provenance validation, structural configuration validation.
- **Infrastructure-configuration tests** (`tests/unit/test_infra_configuration.py`, extended) —
  failure-plane wiring, IAM role/policy shape, recovery-bucket security posture, the isolated
  render-harness-based static-referential-integrity assertions for the two new CloudFormation
  Outputs (TD §22.14's fully-specified two-pass render contract).
- **CLI-composition tests** (`tests/unit/test_operator_cli_retention.py`,
  `test_operator_cli_result.py`, extended) — redrive command dispatch, dependency construction,
  sanitized rendering of `DisposalRedriveResult` including the envelope/provenance-rejection outcome.
- **Regression tests** — full existing suite re-run; `DisposalRecord`/`disposal_repository.py`
  callers unaffected by the new fields' `None`-safe defaults where applicable; `retention_marker`'s
  continued exclusion from `CustodyPeriodConfigLoader.resolve()`.
- **Security-adjacent QA check** (Area i) — IAM scope existence/negative-grant verification, explicitly
  not a substitute for the separate Security Review gate this project's Review Board Policy triggers
  for IAM/credential-boundary work.
- **Handler import-smoke test** (`test_handler_import_smoke.py`, extended) — fail-fast import
  validation for `evidence_disposal_recorder_handler`, mirroring the other four handlers.

No end-to-end AWS-deployed test, load test, or chaos test is in scope for A1.4a per the ADR/TD's own
stated scope; TD §22.14 explicitly defers "no integration-test-category equivalent... beyond what
`tests/integration/` may already establish."

## 6. Coverage Justification

This plan maps 1:1 to TD §22.13's 22-item Future QA Acceptance Matrix (Requirement Area a, §2/§3.1),
and additionally structures dedicated coverage for the nine requirement areas TD §22.13 itself
cross-references but does not fully enumerate as standalone categories: the five failure planes
(Invariant 44, area b — §3.2), deterministic identity (Invariant 38, area c — §3.3), duplicate-conflict
verification (Invariant 39, area d — §3.4), the two provenance rules (Invariants 40/41, area e — §3.5),
prefix restriction and disposition taxonomy (Invariants 42/43, area f — §3.6), payload-preserving
recovery and redrive (Invariant 45/51, area g — §3.7), the batch/retry/bisection contract (Invariant
46, area h — §3.8), IAM least-privilege boundaries as a QA-appropriate existence/scope check
(Invariant 47, area i — §3.9), and `DisposalRecord`'s source-kind-conditional model-validator coverage
(Invariant 49, area j — §3.10, new this correction round). Every ADR Non-Negotiable Invariant from 38
through 51 is cited against at least one test case above; none is left uncovered — **Invariant 49
specifically** is covered both by TC-Q2/TC-D3's duplicate-conflict comparison-surface assertions (§2
item 2, §3.4) and, more directly and completely, by area (j)'s dedicated TC-J1–TC-J7, TC-J8a–TC-J8c,
TC-J9a–TC-J9b model-validator test cases (§3.10).

**Coverage is scoped exactly to A1.4a's own corrected design (ADR Decision 13 / TD §22) and no
further.** The following are
explicitly **out of scope** for this test plan and must not be treated as implied coverage gaps:

- **A1.4c, A1.4d** — any subsequent Workstream A1 subphase, including a possible future historical
  backfill subphase (TD §22.10 explicitly notes `StartingPosition: LATEST`, not `TRIM_HORIZON`,
  precisely to avoid needing this now).
- **A2** — any Workstream A2 (a distinct, not-yet-scoped workstream).
- **Issue #118** — not addressed by this plan; no cross-reference to that issue exists anywhere in
  the ADR Decision 13 / TD §22 material this plan is derived from.
- **Custody-value selection** — no numeric custody-duration value (including
  `operational_durations.disposal_recovery`) is assigned or tested by this plan, consistent with the
  ADR/TD's own explicit "no numeric custody-duration value... introduced" framing at every round.
- **Deployment and activation** — no actual AWS deployment, stack creation, or production activation
  is tested. The infra-configuration tests in this plan validate static/rendered CloudFormation
  template content via a local, isolated render harness (TD §22.14's fully-specified two-pass
  sequence) with **no AWS credentials, no AWS API call, and no AWS mutation** — this is stated as an
  unconditional harness property in the TD itself and is preserved unchanged by this plan.
- **Full Security Review** of the IAM/credential design (Area i's own scope note, §3.9) — this is
  **Gate 3 — Security Design Review Gate** (currently `SATISFIED` — confirmed by this round's Product
  Strategy disposition, which states "No architecture or security blocker remains"; per the companion
  package's §8) — a pre-implementation, design-level review mirroring Gate 2's own timing, not an "as-implemented"
  review — a separate, independently-triggered gate per this project's Review Board Policy, not
  subsumed by this QA plan's existence/scope-of-grants check. The companion implementation plan's §8 **Gate 7 —
  Pre-Activation Validation Gate** separately covers implemented-security re-validation once A1.4a
  exists in staging — neither gate substitutes for the other.

## 7. Ambiguities and Under-Specified Items Flagged for Confirmation

The following items were identified while mapping ADR Decision 13 / TD §22 to concrete test design.
None was silently resolved by guessing; each is either already flagged by the ADR/TD itself as
requiring staging-time or implementation-time confirmation (restated here for test-design visibility)
or is a genuine QA-test-design judgment call this plan makes explicit rather than leaving implicit.

1. **AWS platform facts, split into two tiers by confidence — corrected this round from one blended
   "unconfirmed-pending-staging-capture" framing that lumped documented AWS contract facts together
   with genuinely uncertain implementation-specific unknowns:**

   **Tier 1 (AWS-documented contract, high confidence).** The S3 Lifecycle→EventBridge `Object
   Deleted` notification's `deletion-type` literal values — `"Permanently Deleted"` and `"Delete
   Marker Created"` (§22.5.1) — are AWS's own publicly documented literal values for this event
   schema; this is documented AWS behavior, not a guess. TC-E12/TC-Q5 are built against these two
   literals with high confidence. Staging-capture verification is **retained** for these fixtures as
   confirmatory, defense-in-depth evidence — not because their correctness is genuinely in doubt, but
   because a real staging capture independently confirms the deployed system's actual behavior agrees
   with the documented contract (consistent with §3.2(B)'s Staging Failure-Plane Validation
   Checkpoint discipline).

   **Tier 2 (genuinely unconfirmed, implementation/environment-specific) — unchanged "must be
   confirmed before treating as settled" framing.** Whether a third `deletion-type` value exists
   beyond the two Tier-1 literals (a forward-looking schema-evolution question AWS's current public
   documentation does not resolve); whether `detail.object.key` arrives percent-encoded in practice
   (§22.2); the exact remaining path structure of the native `OnFailure`-destination object key beyond
   the confirmed `aws/lambda/{esm-uuid}/...` prefix (§22.9.3); whether `requestContext.functionArn` in
   that object is genuinely unqualified (§22.9.5 item 2); and whether Serverless Framework's
   function-level `stream` event syntax exposes a first-class `metricsConfig` key or requires a
   `resources.extensions` patch (§22.10). These are genuinely implementation/environment-specific
   unknowns not resolved by AWS's public API documentation for this event type. TC-Q4, TC-E8, TC-G9,
   and TC-H1 are implemented and passed under Gate 6 against these fixtures as specified in the TD
   (part of the full offline/unit/static suite, 2218 passed —
   `docs/qa/a1_4a_disposal_recorder_test_report.md` §16.2), but their underlying AWS-behavior
   assumptions still require Gate 7's real staging-environment event capture before their passing
   status can be treated as proof of production correctness — a passing unit test against an
   unconfirmed AWS-fact fixture is evidence of code-matches-documented-contract, not evidence of
   code-matches-real-AWS-behavior. This remains a genuine, still-open Gate 7 concern, not a Gate 6
   coverage gap.

2. **Plane-(ii)/(iii) `DestinationDeliveryFailures` metric-instance distinguishability (TD §22.8):**
   the TD honestly states it "could not confirm" whether AWS exposes an additional CloudWatch
   dimension distinguishing an async-invoke-destination failure (plane ii) from an event-source-mapping-
   destination failure (plane iii) for the same `FunctionName`, since both emit the identically-named
   `DestinationDeliveryFailures` metric. **Corrected, this round:** the prior text of this item
   incorrectly stated that "TC-P2/TC-P3 rely on `DroppedEventCount`" as a mitigating signal for this
   ambiguity. Per §3.2's own plane table, `DroppedEventCount` is plane **(iv)**'s signal — the
   silent-loss signal for failure while writing to the recovery-bucket destination itself — asserted
   by **TC-P4**, not TC-P2/TC-P3; plane (iii)'s own signal is the distinct
   `OnFailureDestinationDeliveredEventCount` metric. `DroppedEventCount`/TC-P4 has no bearing on the
   plane-(ii)/(iii) `DestinationDeliveryFailures` distinguishability question at all — it is a
   distinct, unambiguous signal specifically for plane (iv), not a mitigation for a different plane's
   ambiguity. The plane-(ii)/(iii) ambiguity itself remains genuinely unresolved: a test asserting
   plane (ii) versus plane (iii) via `DestinationDeliveryFailures` alone would be building on an
   unconfirmed AWS behavior. Flagged rather than assumed resolved.

3. **IAM containment automation-vs-manual-review fallback (§22.13 item 14, restated in §3.9) — RESOLVED,
   historical planning note.** The TD itself left this as an explicit either/or ("a policy-scope
   assertion test **or**, if infeasible to automate, a documented manual-review requirement"), rather
   than mandating automation. This plan required automation for TC-I1–TC-I3/TC-I5 (static
   YAML/rendered-template inspection, automatable per existing convention) and flagged TC-I4 (redrive
   credential-source assertion against a live `AwsClientFactory` construction path) as a candidate for
   the manual-review fallback if automated interception of the CLI's credential-resolution call proved
   impractical. **Implemented disposition: full automation, not the manual-review fallback.** TC-I4 is
   implemented as two automated tests, both present in the repository and passing as part of the full
   offline/unit/static suite (2218 passed, `docs/qa/a1_4a_disposal_recorder_test_report.md` §16.2):
   `test_tc_i4_redrive_module_never_constructs_its_own_aws_client`
   (`tests/unit/evidence_retention/test_disposal_recorder_redrive.py:492`), a structural assertion that
   the redrive module never constructs its own AWS client; and
   `test_main_disposal_recorder_redrive_constructs_s3_client_from_aws_client_factory`
   (`tests/unit/test_operator_cli_retention.py:1283`), an end-to-end assertion through `main()`'s
   actual dispatch path. **Correction:** an earlier revision of this note claimed TC-I4 was
   independently spot-checked in the QA test report's §2 IAM table — that table's own row (line 76)
   covers TC-I1/I2/I3/I5 only and does not mention TC-I4; that earlier claim was inaccurate and is
   withdrawn. This item now relies solely on the two cited test definitions and their passing status
   in the full suite, not on a QA-report cross-reference that was never actually made.

4. **Canonicalization contract's exact field list/order — RESOLVED, historical planning note.** At
   planning time, the TD flagged the exact canonical-JSON field list/order (and the choice of
   canonical-JSON encoding over a length-prefixed alternative) as a judgment call, "flagged for
   confirmation before A1.4a implementation adopts it verbatim" (TD §22.2, §22.14's closing "Judgment
   calls" paragraph) — no revision was made before implementation. **Implemented disposition: adopted
   verbatim, as originally specified, no revision.** `disposal_recorder.py` implements the
   canonical-JSON encoding exactly as this plan's TC-C1 (DynamoDB path: `source_kind`,
   `disposal_id_scheme`, `stream_identity`, `event_id`) and TC-C2 (S3 path: `bucket`, `key`,
   `version_id`, `reason`, `deletion_type`, raw undecoded key) specify. Evidence:
   `docs/qa/a1_4a_disposal_recorder_test_report.md` records both as an exact, byte-for-byte "Match"
   against this plan's own specification — no fixture update was required.

5. **§22.13's own item-9 "simulated" framing versus this plan's infra-configuration-test
   classification (§3.2's Classification note):** TD §22.13 item 9 describes failure-plane tests as
   asserting behavior "on simulated" failure conditions, which could be read as requiring live
   AWS-behavior simulation (e.g., a moto-based or LocalStack-based harness actually exercising ESM
   failure-destination routing) rather than static configuration-correctness assertion. This plan
   interprets "simulated" as configuration-correctness assertion, consistent with how the TD's own
   §22.13 item 12 and the existing `test_infra_configuration.py` convention already treat comparable
   AWS-infrastructure-behavior claims elsewhere in this workstream (no prior subphase in this
   workstream has introduced a moto/LocalStack-based AWS-behavior-simulation harness). This
   interpretation is stated explicitly rather than left for implementation to discover ambiguously; if
   Product Strategy intends genuine AWS-behavior simulation, that is a materially larger testing-
   infrastructure investment this plan does not currently scope and would require its own review.
