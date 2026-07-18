# QA / Test Strategy

## Evidence Governance Workstream A — A1 Evidence Retention Enforcement, A2 Report Issuance Governance Enforcement

**Status:** Planning only. No implementation, code change, test file, or PR exists yet. No test execution has occurred. This document defines what "QA validated" will mean once A1/A2 are implemented, and is the artifact against which a future `[QA SIGN-OFF APPROVED]` decision will be issued.

**Companion documents:**
- Product Specification: `docs/product/evidence_governance_workstream_a_product_spec.md`
- ADR A1: `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
- Technical Design A1: `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
- ADR A2: `docs/architecture/adr_report_issuance_certification_gate.md`
- Technical Design A2: `docs/architecture/evidence_governance_workstream_a2_issuance_governance_technical_design.md`
- ADR — Certification Independence (six invariants A2 must never violate): `docs/architecture/adr_phase7_certification_independence.md`

---

## 1. Test Scope

### 1.1 What This Document Is

This is a **pre-implementation test strategy**, not a test report. Workstream A (A1 and A2) is approved through Technical Design with Architecture and Security Review observations; no code exists under `evidence_retention/`, `report_issuance_governance/`, or any modified `operator_cli/main.py`. No test can be executed against a system that does not exist. This document instead:

- Establishes complete traceability from every acceptance criterion to at least one planned test case.
- Specifies the test level (unit / integration / static-structural / manual-staged) each test case will run at, and — critically for A1 — how tests will validate AWS-native, non-triggerable mechanisms (S3 Lifecycle, DynamoDB TTL) without live AWS execution in CI.
- Defines the fixtures QA will need built once implementation begins.
- Defines exit criteria for a future `[QA SIGN-OFF APPROVED]` decision.

No test in this document has been run. No pass/fail status is asserted anywhere below. When implementation begins, this document is the input to a `docs/qa/evidence_governance_workstream_a_test_report.md`, which will carry actual execution evidence.

### 1.2 In Scope (once implemented)

**A1:**
- `evidence_retention/` package: `HoldRepository`, `DisposalRepository`, `RetentionService`, `disposal_recorder.py` (Lambda handler), `commands.py` (`rcp retention hold place|release|status`)
- `infra/resources/s3.yml` `LifecycleConfiguration` + `NotificationConfiguration` additions
- `infra/resources/dynamodb.yml` `TimeToLiveSpecification` + `StreamSpecification` additions
- `evidenceDisposalRecorder` Lambda, its DLQ, and its CloudWatch alarm
- Additive `custody_expires_at` / `ttl_disposal_at` fields and `rcp-legal-hold` / `rcp-evidence-class` tags on every Phase 1–7 write call site enumerated in Technical Design A1 §11

**A2:**
- `report_issuance_governance/` package: `checkpoint.py` (`evaluate_issuance_checkpoint`), `repository.py`, `service.py` (`IssuanceGovernanceService`), `commands.py` (`rcp issuance disclose|status`)
- `operator_cli/main.py` modification: checkpoint invocation before six `report-*` retrieve commands
- All six non-negotiable invariants from `adr_phase7_certification_independence.md` as continuous regression coverage

### 1.3 Out of Scope

See Section 6 (Explicit Non-Goals).

---

## 2. Traceability Matrix

Every acceptance criterion in Product Spec §8 maps to at least one test case below. No AC is left uncovered. Full test case detail (purpose / input / expected output / validation logic) for architecturally significant cases follows in Section 3; this matrix is the completeness proof.

### 2.1 A1 — Evidence Retention Enforcement

| AC | Requirement (condensed) | Test Case ID(s) | Level |
| --- | --- | --- | --- |
| AC-A1-1 | S3 object past custody, no hold → auto-expired | TC-A1-01, TC-A1-02 | Static-structural (rule spec) + Manual-staged (synthetic custody) |
| AC-A1-2 | DynamoDB record past custody, no hold → auto-removed | TC-A1-03, TC-A1-04 | Unit + Manual-staged |
| AC-A1-3 | Active legal hold suspends disposal | TC-A1-05, TC-A1-06 | Unit |
| AC-A1-4 | Hold release resumes disposal for already-elapsed evidence | TC-A1-07, TC-A1-08 | Unit |
| AC-A1-5 | Custody period is external config, never hardcoded | TC-A1-09 | Static-structural |
| AC-A1-6 | Disposal produces a durable, queryable record | TC-A1-10, TC-A1-11, TC-A1-12 | Unit + Integration |
| AC-A1-7 | Noncurrent S3 versions also expire | TC-A1-13, TC-A1-14 | Static-structural + Unit |
| AC-A1-8 | Design explicitly states backlog handling | TC-A1-15 | Static-structural (doc conformance) + Unit (backfill command) |

Supplementary coverage (invariants, risks, and edge cases flagged in ADR/TD but not independently AC-numbered — see Section 3.3): TC-A1-16 through TC-A1-26.

### 2.2 A2 — Report Issuance Governance Enforcement

| AC | Requirement (condensed) | Test Case ID(s) | Level |
| --- | --- | --- | --- |
| AC-A2-1 | No `CertificationMetadata` + no disclosure → blocked | TC-A2-01, TC-A2-02 | Unit |
| AC-A2-2 | `CERTIFIED` + matching `report_id` → allowed, no disclosure needed | TC-A2-03 | Unit |
| AC-A2-3 | `CERTIFICATION_FAILED`/`BLOCKED`, no disclosure → blocked, structured distinguishable error | TC-A2-04 | Unit |
| AC-A2-4 | `CERTIFICATION_FAILED`/`BLOCKED` + valid disclosure → allowed, disclosure retrievable | TC-A2-05 | Unit + Integration |
| AC-A2-5 | Force re-certification → checkpoint uses new record; prior artifact preserved | TC-A2-06, TC-A2-07 | Unit + Integration |
| AC-A2-6 | Design doesn't violate Phase 6/7 independence invariants | TC-A2-08, TC-A2-09, TC-A2-10 | Static-structural + Unit |
| AC-A2-7 | Force report regeneration — explicit, unambiguous evaluation rule | TC-A2-11, TC-A2-12 | Unit |

Supplementary coverage (six-command gating scope, disclosure integrity, concurrency, fail-closed behavior, SK guard, non-negotiable invariant regression — see Section 3.4): TC-A2-13 through TC-A2-21.

**Traceability confirmation:** all 8 A1 ACs and all 7 A2 ACs (15 total) have at least one mapped test case; 12 of 15 have two or more, reflecting that most ACs require both a unit-level correctness test and either a static-structural or manual-staged test to account for AWS-mechanism constraints (A1) or a cross-cutting regression assertion (A2).

---

## 3. Test Approach Per Workstream

### 3.1 A1 Unit-Level Approach

Unit tests run against mocked DynamoDB (`moto`/`MagicMock`) and mocked S3 clients, following the existing Phase 7 fixture-based pattern (`docs/qa/phase_7_audit_platform_integrity_test_plan.md` §2, "Fixture mutation pattern"). Unit level owns:

- `RetentionService.place_legal_hold`/`release_legal_hold` orchestration logic (tag values written, `ttl_disposal_at` removed/restored, `LegalHoldEvent` counts)
- `_assert_retention_sk()` / `_assert_disposal_sk()` guard behavior (Section 3.3)
- `evidenceDisposalRecorder`'s event-parsing and filtering logic (`userIdentity.principalId` check, `s3:LifecycleExpiration:*` event-name check) using synthetic DynamoDB Streams / EventBridge event payloads
- `custody_expires_at` / `ttl_disposal_at` computation at write time across all seven enumerated write call sites (TD A1 §11)

### 3.2 A1 Integration-Level Approach — the AWS-Lifecycle Constraint, Stated Concretely

**Constraint:** S3 Lifecycle rule evaluation runs once per day, server-side, on AWS's own schedule — it cannot be invoked on demand. DynamoDB TTL deletion is best-effort within ~48 hours of `ttl_disposal_at` — also not synchronously triggerable. Neither mechanism can be exercised end-to-end inside a CI pipeline in a way that produces a pass/fail result within a normal test run. A test plan that says "test the S3 lifecycle rule" without addressing this is not executable. This strategy specifies three concrete, non-hand-wavy validation layers instead of one:

1. **Rule-specification unit tests (primary, CI-runnable).** The `LifecycleConfiguration`/`TimeToLiveSpecification` CloudFormation resource definitions in `infra/resources/s3.yml`/`dynamodb.yml` are tested as *data*, not as live behavior: parse the rendered CFN template (or the `serverless.yml` custom config it's built from) and assert structurally — `Filter.Tag = {Key: rcp-legal-hold, Value: "false"}` is present on both `Expiration` and `NoncurrentVersionExpiration` actions; `Days`/`NoncurrentDays` resolve to the `custom.custodyPeriodDays` config value, not a literal; `TimeToLiveSpecification.AttributeName == "ttl_disposal_at"`; `StreamSpecification.StreamViewType == "NEW_AND_OLD_IMAGES"`. This validates AC-A1-1, AC-A1-2, AC-A1-5, AC-A1-7's *specification correctness* without requiring AWS execution, and runs in every CI build.

2. **LocalStack synthetic-custody-period integration tests (secondary, CI or nightly).** LocalStack's S3/DynamoDB emulation does not run AWS's real Lifecycle/TTL background sweeps (this is a documented LocalStack limitation for both services in the open-source tier), so this layer validates the *write path and event-consumer path* — object tagging at write time, `evidenceDisposalRecorder` correctly processing a manually-injected DynamoDB Streams `REMOVE` record or a manually-injected EventBridge `LifecycleExpiration` event — not the AWS sweep itself. This is explicitly scoped as testing "everything except the AWS-managed deletion trigger," which is the only part that cannot be emulated.

3. **Manual staged-environment verification with a short-lived synthetic custody period (tertiary, pre-release gate, not CI-automated).** Before Workstream A ships to any stage, QA will run a bounded, time-boxed manual verification in `dev` or `staging`: configure `custom.custodyPeriodDays` to a deliberately short test value (e.g., 1 day for S3 current-version `Expiration`, and for DynamoDB TTL a `ttl_disposal_at` set a few minutes in the future — DynamoDB TTL sweeps checked-in-the-past items opportunistically and is commonly observed to act faster than the documented 48-hour upper bound for small item counts, though this is not a guarantee QA will rely on for a pass/fail threshold), write synthetic evidence, and observe across a bounded real-time window (up to 48h for the DynamoDB leg per AWS's own documented ceiling) whether disposal occurs and a `DisposalRecord` is produced. This is the only layer that proves the actual AWS mechanism fires end-to-end, and it is explicitly manual and time-boxed, not part of the automated regression suite, precisely because AWS does not guarantee a tighter SLA that CI can assert against.

This three-layer approach is the concrete answer to "how will S3 Lifecycle be validated": specification correctness in CI (layer 1), consumer/write-path correctness in CI/nightly via LocalStack (layer 2), and one bounded manual real-AWS confirmation per release candidate (layer 3) — not a claim that the daily AWS sweep itself is unit-testable, because it is not.

### 3.3 A1 — Detailed Test Cases (Architecturally Significant / Non-AC-Numbered)

**TC-A1-16 — `HoldRepository` cannot construct a `#DISPOSAL#`-shaped write**
- **Purpose:** Prove the SK-write guard `_assert_retention_sk()` is a real, exercised negative control, not a theoretical one. This is the QA coverage item required by the Architecture Review observation that the guard is code-level, not IAM-enforced.
- **Input:** Call `HoldRepository`'s internal write path with an SK string containing `#DISPOSAL#` (constructed directly in the test to bypass normal call sites, simulating a future programming error).
- **Expected output:** `AssertionError` raised before any `PutItem`/`UpdateItem` call reaches the mocked DynamoDB client; the mocked client's write method asserts zero invocations.
- **Validation logic:** `pytest.raises(AssertionError)`; assert mock write call count == 0.

**TC-A1-17 — `DisposalRepository` cannot construct a `#LEGALHOLD#`-shaped write**
- **Purpose:** Symmetric negative control for `_assert_disposal_sk()`.
- **Input:** Call `DisposalRepository`'s write path with an SK string containing `#LEGALHOLD#`.
- **Expected output:** `AssertionError` raised; zero writes reach the mocked client.
- **Validation logic:** Same pattern as TC-A1-16, mirrored.

**TC-A1-18 — DLQ exercised with a deliberately malformed event on both event sources**
- **Purpose:** Per Technical Design A1 §17 implementation-complete criterion ("a DLQ that has never been exercised is not a verified failure destination"), prove the failure destination actually receives a message when the Lambda handler throws.
- **Input:** (a) A syntactically invalid/incomplete DynamoDB Streams `REMOVE` record (e.g., missing `OLD_IMAGE`) fed to `disposal_recorder.py`'s handler under test, with a bounded retry configuration in the test harness; (b) a malformed EventBridge S3 `LifecycleExpiration` payload (e.g., missing `s3.object.key`).
- **Expected output:** The handler raises after exhausting the exception path; in a LocalStack or moto-based SQS emulation, the failed event lands on `evidenceDisposalRecorderDLQ`; `BisectBatchOnFunctionError` behavior (for the DynamoDB Streams path specifically) is validated separately — a batch containing one malformed record alongside valid records does not silently drop the valid records.
- **Validation logic:** Assert DLQ receives exactly one message matching the malformed payload; assert no `DisposalRecord` was written for the malformed event; assert valid records in the same batch (bisection sub-case) still produce their `DisposalRecord`.
- **QA-blocking note:** Per the orchestrator's framing, this is treated as an implementation-complete gate, not merely a nice-to-have — QA will not approve A1 without evidence this test was run. The DLQ's own encryption-at-rest / message-retention configuration is flagged as a still-open design item (not present in TD A1 §6/§13); QA records this as a **tracked follow-up for Architecture**, not a QA blocker in itself, since the DLQ's functional failure-destination behavior (this test) is independent of its encryption/retention configuration. QA sign-off for A1 will explicitly note this follow-up as unresolved rather than silently accepting it.

**TC-A1-19 — S3 per-version re-tagging TOCTOU race (documented approach, not fully automatable pre-implementation)**
- **Purpose:** Cover the race documented in TD A1 §16: `LegalHold.status` flips to `ACTIVE` atomically, but the S3 re-tagging sweep across all object versions is not atomic; a version whose custody already elapsed could theoretically be swept by the next daily Lifecycle evaluation before re-tagging reaches it.
- **Test approach:** This is **not** unit-testable in the sense of provoking a real AWS Lifecycle sweep mid-sweep — it is an integration/staged-environment scenario. Planned approach: (1) unit-level, assert the re-tagging sweep is ordered to prioritize versions closest to their custody expiry first (if TD is amended to specify an ordering; currently TD does not specify sweep ordering — **this is flagged as a residual design gap for Architecture in Section 7 of this document, not silently resolved by QA**); (2) staged-environment, construct an audit with synthetic evidence whose custody period is set to expire imminently, trigger `hold place` concurrently with the approaching Lifecycle window, and manually confirm via CloudTrail/S3 access logs whether the race window was empirically observed. This is documented as best-effort, low-probability verification, consistent with TD's own characterization ("small but not zero").
- **Exit expectation:** A documented test log (staged-environment run) rather than a deterministic pass/fail unit test, since the race is fundamentally timing-dependent on an AWS-controlled daily sweep.

**TC-A1-20 — DynamoDB `Query`+`UpdateItem REMOVE ttl_disposal_at` loop TOCTOU race**
- **Purpose:** Symmetric coverage for the DynamoDB-side race in TD A1 §16.
- **Test approach:** Unit-level, assert the `Query` + per-item `UpdateItem` loop processes items in a bounded, observable order (test asserts the loop does not skip items and completes for a realistic item count within a test-configurable time budget); staged-environment, same construction as TC-A1-19 but on the DynamoDB TTL leg, with a `ttl_disposal_at` set to elapse within the loop's expected execution window.
- **Exit expectation:** Same as TC-A1-19 — documented staged-environment observation, not a deterministic CI assertion.

**TC-A1-14 — `NoncurrentVersionExpiration.NoncurrentDays` clock divergence within accepted bounds**
- **Purpose:** TD A1 Decision 2 states `NoncurrentDays` is clocked from "when a version became noncurrent," not from the object's original `created_at` — a documented, accepted divergence from the primary `custody_expires_at` clock. AC-A1-7 requires this divergence be within documented/accepted bounds, not silently wrong.
- **Input:** Simulate a `write_json(..., overwrite=True)` call producing a second version of an existing key (the one identified noncurrent-version source per TD A1 Decision 2 rationale) at a known interval after the original write.
- **Expected output:** The noncurrent version's guaranteed expiration is `NoncurrentDays` days after it *became* noncurrent, not after its own original write — confirmed to always terminate (no indefinite retention) but explicitly *not* asserted to align with `custody_expires_at` to the day.
- **Validation logic:** Assert the noncurrent version is provably bounded (expires within `NoncurrentDays` of becoming noncurrent); assert the test explicitly documents the delta between this and `custody_expires_at`-based expectations as an accepted, non-defect divergence (a documentation/assertion-of-understanding test, not a tolerance-threshold numeric test, since TD does not define a numeric bound to test against — **this absence of a numeric bound is flagged in Section 7**).

**TC-A1-26 — Uniform enforcement across all Phase 1–7 write paths (FR-A1-6 regression)**
- **Purpose:** Prevent silent scope-narrowing — a future code change to any phase's write path must not omit the tag/TTL fields.
- **Input:** A parameterized test iterating over the seven confirmed write call sites in TD A1 §11 (`write_raw_results_once`, `put_started_once`, `aggregation/repository.py`, `reliability_intelligence/repository.py`, `deterministic_reporting/repository.py`/`publisher.py`, `audit_platform_integrity/repository.py`).
- **Expected output:** Every call site's write includes `custody_expires_at`, `ttl_disposal_at` (DynamoDB) or the `rcp-legal-hold`/`rcp-evidence-class` tags (S3).
- **Validation logic:** Assert presence and correct format of all four fields/tags at every enumerated call site; this test is intentionally a regression trip-wire — failing it signals either a missed write path or a future refactor that dropped the fields.

**Remaining A1 test cases (TC-A1-01/02/03/04/05/06/07/08/09/10/11/12/13/15/21/22/23/24/25)** are specified at matrix-level detail (purpose implicit in AC text, standard unit/integration pattern) and will receive full four-field specification during implementation planning, following the same template as the cases above. Their AC/edge-case anchor and level are fully enumerated in Section 2.1 and below:

| TC ID | Anchor | One-line purpose | Level |
| --- | --- | --- | --- |
| TC-A1-01 | AC-A1-1 | `LifecycleConfiguration.Expiration` rule spec correctness | Static-structural |
| TC-A1-02 | AC-A1-1 | Synthetic short custody period, staged, current-version object disposed | Manual-staged |
| TC-A1-03 | AC-A1-2 | `ttl_disposal_at` computed and set correctly at write time | Unit |
| TC-A1-04 | AC-A1-2 | Synthetic short custody period, staged, DynamoDB item removed within 48h ceiling | Manual-staged |
| TC-A1-05 | AC-A1-3 | Object tagged `rcp-legal-hold=true` excluded from Lifecycle tag-filter match | Unit (filter-logic simulation) |
| TC-A1-06 | AC-A1-3 | `ttl_disposal_at` removed on hold placement; item has no TTL candidate | Unit |
| TC-A1-07 | AC-A1-4 | Release restores `ttl_disposal_at = MAX(custody_expires_at, now)` | Unit |
| TC-A1-08 | AC-A1-4 | Current-version S3 object needs no recomputation on release; next daily sweep picks it up | Unit (assert no re-tag needed for current version's `Expiration.Days` clock) |
| TC-A1-09 | AC-A1-5 | `custody_expires_at` computation reads from config/env, not a literal; grep-level static check on `s3.yml`/`dynamodb.yml`/application code for hardcoded day values | Static-structural |
| TC-A1-10 | AC-A1-6 | `DisposalRecord` written correctly from a synthetic DynamoDB Streams `REMOVE` (TTL principal) event | Unit |
| TC-A1-11 | AC-A1-6 | `DisposalRecord` written correctly from a synthetic S3 `LifecycleExpiration` EventBridge event | Unit |
| TC-A1-12 | AC-A1-6 | `DisposalRecord` queryable post-write (`PK`/`SK` lookup), never carries `ttl_disposal_at` | Unit + Integration |
| TC-A1-13 | AC-A1-7 | `NoncurrentVersionExpiration` present and tag-filtered identically to `Expiration` | Static-structural |
| TC-A1-15 | AC-A1-8 | `rcp retention backfill-custody` clocks from backfill-execution time, not original `created_at`; requires explicit operator confirmation | Unit |
| TC-A1-21 | Edge case (TD §17) | `hold place`/`hold release` idempotent re-invocation; `hold_count` increments; no duplicate `LegalHoldEvent` corruption | Unit |
| TC-A1-22 | Edge case (TD §10.5) | Partial-sweep interruption (simulated mid-sweep S3 API failure) is safely resumable via re-invocation | Unit |
| TC-A1-23 | Product Spec §9 edge case | Hold placed after evidence already disposed has no retroactive effect; no code path attempts restoration | Unit (negative — assert no restoration API exists / is invoked) |
| TC-A1-24 | Product Spec §9 edge case | Phase 4 aggregate and Phase 6/7 records under the same audit identity compute independent `custody_expires_at` values per evidence class | Unit |
| TC-A1-25 | Product Spec §9 edge case | Multiple force-regenerated report artifacts (each a distinct S3 key) are each independently tagged and independently expire; disposal enumerates all historical keys, not only the latest | Unit + Integration |

### 3.4 A2 Unit-Level and Regression Approach

A2 introduces no asynchronous infrastructure (TD A2 §13), so nearly all A2 coverage is unit- and structural-level, run against fixture `CertificationMetadata`/`ReportMetadata`/`DisclosureRecord` payloads — directly following the Phase 7 fixture-mutation pattern already established in `docs/qa/phase_7_audit_platform_integrity_test_plan.md` §2.

**TC-A2-06 / TC-A2-07 — Force re-certification (AC-A2-5)**
- **Purpose:** Confirm the checkpoint requires no additional logic beyond reading the current `CertificationMetadata` record, and that the prior certificate artifact is untouched.
- **Input:** A fixture sequence: (1) `CertificationMetadata` with `certificate_id=cert_1`, `terminal_state=CERTIFIED`; (2) simulate `--force` producing `certificate_id=cert_2` at the same identity-tuple SK (unconditional `PutItem`, per TD A2 §5's `write_cert_metadata_complete` behavior); (3) evaluate checkpoint.
- **Expected output:** Checkpoint reads `cert_2`; the S3 object at `cert_1`'s original key is asserted unmodified (checksum/ETag comparison in the fixture harness) and still present.
- **Validation logic:** Assert `evaluate_issuance_checkpoint` returns allowed using `cert_2`'s fields; assert no write/delete call was made against `cert_1`'s S3 key.

**TC-A2-11 / TC-A2-12 — Force report regeneration (AC-A2-7)**
- **Purpose:** This is explicitly called out by the Product Spec as "must not be left ambiguous" — the highest-priority A2 test given the residual-risk framing.
- **Input (TC-A2-11):** `CertificationMetadata.terminal_state=CERTIFIED`, `CertificationMetadata.report_id=report_A`; `ReportMetadata.report_id=report_B` (post force-regeneration, in-place update per `phase_6_report_schema.md` §5.2); no disclosure recorded.
- **Expected output (TC-A2-11):** `IssuanceBlockedSupersededReportError` raised; `report_id` mismatch treated identically to non-`CERTIFIED`.
- **Input (TC-A2-12):** Same starting state as TC-A2-11, plus a `DisclosureRecord` with `disclosure_reason=CERTIFIED_BUT_SUPERSEDED_REPORT`, `governing_certificate_id` matching `cert.certificate_id`, `governing_report_id` matching `report_B` (the *current* report).
- **Expected output (TC-A2-12):** Checkpoint returns allowed.
- **Validation logic:** Exact exception type assertion for TC-A2-11; no-exception assertion plus disclosure-match field-by-field comparison for TC-A2-12. This pair is the direct verification of ADR A2 Decision 5's resolution rule and must not be treated as adequately covered by AC-A2-5 alone, since the two ACs test opposite directions of "which record governs."

**TC-A2-08/09/10 — Structural regression on the six non-negotiable invariants (AC-A2-6)**
- **Purpose:** Prove, not merely assert in a design doc, that A2 does not violate `adr_phase7_certification_independence.md`.
- **Input/approach:** (a) AST/import-graph static check: `deterministic_reporting/` source contains no import of `report_issuance_governance/` or `audit_platform_integrity/repository.py` write methods; (b) AST/import-graph static check: `audit_platform_integrity/` source contains no import of `deterministic_reporting/repository.py` write methods or `report_issuance_governance/`; (c) diff-based check: `git diff` against the pre-A2 baseline shows zero changed lines under `deterministic_reporting/` and `audit_platform_integrity/` (per TD A2 §17's own explicit request: "a regression test asserting `deterministic_reporting/` and `audit_platform_integrity/` source trees are unmodified by this workstream").
- **Expected output:** All three checks pass; any future PR that touches either phase's source alongside A2 changes fails this regression test by construction.
- **Validation logic:** File-tree diff assertion + import-graph assertion, run in CI on every subsequent PR touching `report_issuance_governance/`, not only at initial implementation.

**TC-A2-13/14 — Six-command gating scope**
- **Purpose:** TD A2 §5.2 corrected an earlier draft that gated only two commands; the current design gates all six full-artifact-backed commands and exempts only `report-status`. This scoping correction is itself high-risk (an under-scoped gate defeats the entire workstream) and needs direct, per-command test coverage, not an inference from one command's test passing.
- **Input:** For each of `report-json`, `report-markdown`, `report-summary`, `report-endpoints`, `report-methodology`, `report-lineage` — invoke with a fixture identity tuple in a blocked state (no `CertificationMetadata`).
- **Expected output:** All six raise `IssuanceBlockedNoCertificationError` before `dispatch_report_retrieve` executes.
- **Input (TC-A2-14):** `report-status` invoked with the same blocked-state fixture.
- **Expected output (TC-A2-14):** `report-status` succeeds and returns `ReportMetadata`-only content; `evaluate_issuance_checkpoint` is never called on this path.
- **Validation logic:** Per-command exception assertion (six cases) plus a negative assertion that the checkpoint function was not invoked for `report-status` (mock call-count == 0).

**TC-A2-15 — Disclosure completeness is structurally, not just procedurally, enforced**
- **Purpose:** Product Spec edge case: "a disclosed-limitation record that only partially covers the `disclosed_failures` list... must not satisfy the disclosure requirement." TD A2 §10.3 states `acknowledged_failures` is server-computed, never operator-supplied, making partial disclosure "structurally impossible rather than merely validated against." This claim needs a test that actually attempts to construct a partial disclosure and confirms there is no code path to do so.
- **Input:** Attempt to call `IssuanceGovernanceService.record_disclosure` with an (if the implementation exposes one at all) operator-supplied `acknowledged_failures` argument that differs from `CertificationMetadata.disclosed_failures`.
- **Expected output:** Either the argument does not exist in the method signature (structural proof) or, if present for any reason, is silently overridden by the server-computed value (behavioral proof) — TD states the former; the test should assert the method signature has no such parameter, which is the stronger claim.
- **Validation logic:** Signature inspection (`inspect.signature`) asserting no `acknowledged_failures`/`disclosure_reason` parameter exists on `record_disclosure`; if TD's intended design changes before implementation, this test must be updated to match, and QA will flag if implementation diverges from TD's "structurally impossible" claim into a merely-validated one.

**TC-A2-16 — Concurrent issuance during in-progress force re-certification**
- **Purpose:** ADR A2 Decision 5 asserts `DynamoDB GetItem is atomic per item, so no torn or partial read is possible" — this is an assertion about DynamoDB's own guarantees, not about this codebase's logic, but QA should still verify the checkpoint code does not introduce its own inconsistency (e.g., reading `CertificationMetadata` twice with a stale-cache layer in between).
- **Input:** Two sequential `evaluate_issuance_checkpoint` calls in a test simulating a `PutItem` to `CertificationMetadata` occurring between them (new terminal state written mid-test).
- **Expected output:** The first call reflects the pre-write state; the second call reflects the post-write state; no intermediate/torn value is ever observed by either call.
- **Validation logic:** Assert `evaluate_issuance_checkpoint` performs no caching of `CertificationMetadata` reads across invocations (each call issues a fresh `GetItem`); this is a code-inspection-backed unit assertion, not a true concurrency/threading test, since DynamoDB's own atomicity guarantee is out of this codebase's control to test.

**TC-A2-17 — Fail-closed on `StorageError`**
- **Purpose:** TD A2 §10.5/§13 states a `StorageError` during any of the three reads (`ReportMetadata`, `CertificationMetadata`, `DisclosureRecord`) must propagate as a hard failure, never default to "allowed."
- **Input:** Mock each of the three repository read calls in turn to raise `StorageError`.
- **Expected output:** For all three injection points, `evaluate_issuance_checkpoint` propagates the error (or a wrapping error) and no report content is returned; `dispatch_report_retrieve` is never called.
- **Validation logic:** Three parameterized sub-tests, one per read call; assert exception propagation and zero downstream dispatch calls in each.

**TC-A2-18 — `_assert_issuance_sk()` negative control**
- **Purpose:** TD A2 §12 states this repository "should carry forward the same style of write-target assertion (`_assert_issuance_sk`)... guaranteeing at the code level... that Issuance Governance can never write to a Phase 6 or Phase 7 sort key." This is phrased as a recommendation in TD, not yet a committed decision — **flagged in Section 7 as needing explicit confirmation that this guard will actually be implemented**, since unlike A1's `_assert_retention_sk`/`_assert_disposal_sk` (committed in ADR A1 Non-Negotiable Invariant 6), A2's equivalent is not listed as a non-negotiable invariant in ADR A2.
- **Input (contingent on the guard being implemented):** Attempt a write with an SK containing `#CERT#`, `#RPTJOB#`, or `#RPT#`.
- **Expected output:** `AssertionError`, mirroring TC-A1-16/17's pattern.
- **Validation logic:** Same as TC-A1-16/17. **This test case cannot be finalized until Architecture confirms whether `_assert_issuance_sk` is committed or remains a recommendation** — see Section 7.

**TC-A2-19 — `DISCLOSURE_NOT_REQUIRED` no-op error**
- **Purpose:** TD A2 §8 defines this as a hard error (not silently accepted) when an operator attempts to disclose against an already-`CERTIFIED`-and-matching state, "since inviting an unnecessary disclosure could mask a future real gap."
- **Input:** `rcp issuance disclose` invoked when `CertificationMetadata.terminal_state=CERTIFIED` and `report_id` matches current `ReportMetadata.report_id`.
- **Expected output:** `DISCLOSURE_NOT_REQUIRED` error; no `DisclosureRecord`/`DisclosureEvent` written.
- **Validation logic:** Assert error code and zero write calls.

**TC-A2-20 — `disclosure_reason` never accepted as CLI/operator input**
- **Purpose:** Structural proof that `rcp issuance disclose`'s parser does not expose a `--disclosure-reason` or `--acknowledged-failures` flag.
- **Validation logic:** Inspect the argparse parser definition for `commands.py`; assert no such argument exists.

**TC-A2-21 — Full six-invariant regression suite**
- **Purpose:** A single consolidated regression test file that asserts, in one place, all six invariants from `adr_phase7_certification_independence.md` §"Non-Negotiable Invariants," each as an independently failing assertion (not one combined boolean), so a future violation is immediately attributable to the specific invariant broken.
- **Validation logic:** Six discrete assertions: (1) no Phase 5 re-derivation call from `report_issuance_governance/`; (2) no Phase 5 artifact read; (3) no Phase 4 artifact read; (4) `ReportMetadata.status=COMPLETE` remains the sole Phase 7 prerequisite (no alternative signal introduced); (5) zero writes from `report_issuance_governance/` to any Phase 6/Phase 7 SK; (6) no event-driven trigger (no DynamoDB Streams / EventBridge subscription registered by A2 code, confirmed via `serverless.yml` diff — A2 introduces no new Lambda per TD A2 §13). This overlaps intentionally with TC-A2-08/09/10 but is organized around the ADR's own invariant numbering for direct auditability by a Compliance Reviewer, per Product Spec §4's "Compliance / Governance Reviewer" persona.

---

## 4. Test Data / Fixtures Needed

### 4.1 A1 Fixtures

| Fixture | Purpose |
| --- | --- |
| `CertificationMetadata`/`ReportMetadata`/generic DynamoDB record fixtures at varying `created_at` offsets relative to a test custody period (`custody_period_seconds`) — pre-elapsed, at-boundary, not-yet-elapsed | Drives TC-A1-01–04, TC-A1-24 |
| Synthetic `LegalHold` fixtures: `NEVER_HELD`, `ACTIVE`, `RELEASED` (single cycle), `RELEASED` (multi-cycle, `hold_count > 1`) | Drives TC-A1-05–08, TC-A1-21 |
| Synthetic S3 object-version sets: single-version objects, multi-version objects (via simulated `write_json(overwrite=True)`), each with `rcp-legal-hold` tag in both states | Drives TC-A1-05, TC-A1-13, TC-A1-14, TC-A1-25 |
| Synthetic DynamoDB Streams `REMOVE` event payloads: valid TTL-principal, valid application-delete-principal (negative control — must NOT produce a `DisposalRecord`), malformed/missing-`OLD_IMAGE` | Drives TC-A1-10, TC-A1-18 |
| Synthetic EventBridge S3 `LifecycleExpiration` event payloads: `Delete`, `DeleteMarkerCreated`, malformed | Drives TC-A1-11, TC-A1-18 |
| A rendered/parsed copy of `infra/resources/s3.yml`/`dynamodb.yml` (post-implementation) for static-structural CFN assertions | Drives TC-A1-01, TC-A1-09, TC-A1-13 |
| Multi-evidence-class fixture set under one audit identity (`raw_evidence`, `aggregate_metadata`, `intelligence`, `report`, `certificate`) with independently computed `custody_expires_at` per class | Drives TC-A1-24, FR-A1-6 regression (TC-A1-26) |

### 4.2 A2 Fixtures

| Fixture | Purpose |
| --- | --- |
| `CertificationMetadata` fixtures in each `terminal_state`: `CERTIFIED`, `CERTIFICATION_FAILED`, `CERTIFICATION_BLOCKED`, and **absent (no record)** | Drives TC-A2-01–04 |
| `CertificationMetadata` fixture pair simulating force re-certification (`cert_1` → `cert_2`, same identity tuple, different `certificate_id`) | Drives TC-A2-06, TC-A2-07 |
| `ReportMetadata` fixture pair simulating force report regeneration (in-place update, `report_id` change, `report_job_id` change) per `phase_6_report_schema.md` §5.2 | Drives TC-A2-11, TC-A2-12 |
| `DisclosureRecord` fixtures for all three `disclosure_reason` values (`NO_CERTIFICATION_RECORD`, `NON_CERTIFIED_TERMINAL_STATE`, `CERTIFIED_BUT_SUPERSEDED_REPORT`), including complete and deliberately-partial `acknowledged_failures` variants (the partial variant used only to prove it's unconstructable — TC-A2-15) | Drives TC-A2-01, TC-A2-04, TC-A2-05, TC-A2-11, TC-A2-12, TC-A2-15 |
| Full report DTO fixture reused from the Phase 7 base fixture (`docs/qa/phase_7_audit_platform_integrity_test_plan.md` §2) — A2 does not need a new report-content fixture, only identity-tuple and status-field variants layered on the existing Phase 6/7 fixture convention | Drives TC-A2-13, TC-A2-14 |
| Six-command CLI dispatch table fixture (`report-json` … `report-lineage`, `report-status`) with mocked `dispatch_report_retrieve` to assert call/no-call | Drives TC-A2-13, TC-A2-14 |

---

## 5. Non-Functional / Operational Validation

### 5.1 DLQ Exercise (A1)

Covered in detail as TC-A1-18. Restated here as an operational gate: **QA will not sign off A1 without evidence both event source mappings (DynamoDB Streams and the EventBridge S3-notification rule) were exercised with a deliberately malformed event and confirmed to land on `evidenceDisposalRecorderDLQ`, and that the DLQ-depth CloudWatch alarm fired.** This is per Technical Design A1 §17's own implementation-complete criterion, elevated here to an explicit QA exit condition (Section 7).

### 5.2 Disposal-Record Durability Check (A1)

Beyond TC-A1-12's unit-level query test, QA will perform one staged-environment durability check per release candidate: after the manual synthetic-custody-period run (Section 3.2, layer 3), confirm the resulting `DisposalRecord` remains queryable after a subsequent, unrelated write burst against `MetadataTable` (i.e., it was not itself accidentally subject to TTL or overwritten by a colliding SK — the latter already structurally prevented per TC-A1-17, but worth confirming end-to-end once).

### 5.3 Eventual-Consistency Window Documentation and False-Failure Avoidance

Both AWS mechanisms are asynchronous and not instantaneous:
- DynamoDB TTL: best-effort, typically within ~48 hours of `ttl_disposal_at`.
- S3 Lifecycle: daily batch evaluation, up to ~24 hours latency from crossing the threshold.

**QA policy to avoid false-failure flakiness:** No automated CI test will assert "disposal has occurred" as a hard pass/fail condition tied to a wall-clock deadline shorter than these documented windows. Specifically:
- Unit and LocalStack integration tests (Section 3.2, layers 1–2) never assert on actual AWS deletion timing — they assert on rule *specification* and event-consumer *logic*, both of which are deterministic and CI-safe.
- The manual staged-environment test (layer 3) is explicitly time-boxed to the documented ceiling (up to 48h for DynamoDB, up to ~24h+object-age for S3) and is run as a bounded, human-observed verification, not a CI assertion with a timeout that could flake.
- `DisposalRecord.recorded_at` vs `disposed_at` is treated as approximate by design (per ADR A1 Consequences) — no test will assert numeric equality between the two, only that `recorded_at >= disposed_at` and both fall within the documented window when observed.

This policy directly prevents the two most likely sources of QA flakiness in this workstream: a CI test racing against a background AWS sweep, and a staged-environment test with an unrealistically tight timeout.

### 5.4 A2 — No New Eventual-Consistency Surface

A2 introduces no asynchronous infrastructure (TD A2 §13 explicitly states this); every `evaluate_issuance_checkpoint` read is a synchronous, immediately-consistent `GetItem`. No eventual-consistency test policy is needed for A2 beyond TC-A2-16's atomicity check.

---

## 6. Explicit Non-Goals

This QA strategy does **not** cover:

- **Workstream B/C/D/E** in any form — terminology reconciliation (B2), custody-scope-by-contract decisions, legal hold authorization policy, or any future customer-facing delivery mechanism that would need to independently invoke `evaluate_issuance_checkpoint()`. These are out of scope per Product Spec §6.2/§11 and are not QA's responsibility to test until they exist.
- **The exact custody-period duration value(s).** A1's mechanism is validated against a *test* custody-period value throughout this strategy (per ADR A1 Decision 5 / AC-A1-5, the real value is an unset Product Strategy decision). QA validates the mechanism is correctly *parameterized*, not that any specific number of days is "correct" — there is no correctness criterion for a value that has not been set.
- **Legal hold authorization policy** (who may place/release a hold). Only the technical override mechanism (already covered above) is in QA's scope; the business process governing who is permitted to invoke `rcp retention hold place` is explicitly out of scope per Product Spec §6.2.
- **Direct AWS API bypass of the A2 CLI-layer checkpoint** (`aws s3 cp`, raw DynamoDB `GetItem`/`Scan` using the same operator credentials). This is documented in ADR A2 Consequences and TD A2 §12 as an accepted, undesigned-around characteristic of RCP's operator-only trust model — not a gap this workstream closes. **QA treats this explicitly as an out-of-scope test boundary, not as an untested gap**: no test will attempt to "catch" this bypass, and its absence from the test suite must not be read as an oversight. If a future workstream introduces a server-side authorization boundary, that would be the point at which this becomes testable and in-scope.
- **Automated DLQ redrive.** TD A1 §13 states DLQ contents require manual operator investigation/redrive; this is out of scope for A1's automated test suite (the DLQ *arrival* is tested per TC-A1-18; automated recovery from the DLQ is not designed and therefore not tested).
- **Phase 7's eight certification domains, terminal-state determination logic, or `cert_v1` schema.** A2 consumes `CertificationMetadata` as-is; any correctness question about how Phase 7 arrives at a terminal state is Phase 7's own test plan's responsibility (`docs/qa/phase_7_audit_platform_integrity_test_plan.md`), not this document's.
- **Phase 6 report-generation correctness.** Out of scope per the same boundary logic — A2 never re-derives or re-validates report content, only reads identity/status fields.
- **Load, performance, or scale testing of the S3 re-tagging sweep** beyond the qualitative "not instantaneous for large evidence sets" characterization already documented in TD A1 §13/§16. No specific throughput SLA exists to test against.

---

## 7. Coverage Gaps Flagged for Architecture / Product Strategy (Not Silently Filled)

QA does not have authority to invent acceptance criteria or resolve open design questions. The following items surfaced while building this traceability matrix are flagged back rather than assumed:

1. **A2 — `_assert_issuance_sk()` is a Technical Design recommendation, not a committed ADR invariant.** Unlike A1's `_assert_retention_sk`/`_assert_disposal_sk`, which are Non-Negotiable Invariant 6 in ADR A1, ADR A2's "Non-Negotiable Invariants" section (carried forward from `adr_phase7_certification_independence.md`) does not list an equivalent SK-write guard as mandatory — TD A2 §12 only says the design "should carry forward the same style." TC-A2-18 cannot be finalized as a required (vs. best-effort) test until Architecture confirms this guard is committed, not optional. **Recommendation: promote this to an explicit ADR A2 invariant before implementation, given A1 treats the symmetric guard as non-negotiable.**
2. **A1 — no sweep-ordering specification for the S3 re-tagging TOCTOU race (TD A1 §16).** The race is documented as accepted/low-probability, but no ordering strategy (e.g., "re-tag versions nearest their custody expiry first") is specified that would narrow the window. QA cannot test for a mitigation that doesn't exist in the design. Flagged for Architecture as an optional hardening, not a blocker — TD already characterizes this as accepted risk.
3. **A1 — no numeric bound is defined for the `NoncurrentDays` clock divergence (TD A1 Decision 2).** The design states the divergence from `custody_expires_at` is "accepted" but does not give QA a threshold to test against (e.g., "divergence must not exceed N days"). TC-A1-14 can only assert the divergence is bounded and non-indefinite, not that it is within any specific accepted range, because no range was specified. Flagged for Architecture/Product Strategy — if a numeric bound is ever desired, it needs to be added to the ADR before QA can test against it.
4. **A1 TD §15 (Assumption) — Phase 4/5 S3 footprint was explicitly not independently verified during Technical Design** ("`aggregation/` and `reliability_intelligence/` source was not read"). This means TC-A1-26 (uniform enforcement across all phase write paths) cannot be fully specified today for the Phase 4/5 legs — QA's fixture/call-site list in Section 4.1 is only confirmed for Phase 1/2/3/6/7. This is not a QA gap; it is an inherited, already-flagged TD gap (TD's own "Assumption requiring confirmation") that blocks full A1 test-case finalization until Architecture confirms the Phase 4/5 write-path call sites.
5. **A1 — `DisposalRecord`'s own retention policy is an open question (TD A1 §16), not yet resolved.** QA's position: `DisposalRecord` is treated as permanent/untested-for-expiry for this workstream (consistent with Non-Negotiable Invariant 1 — it must never carry `ttl_disposal_at`), but if Product Strategy later defines an independent compliance-record retention policy for `DisposalRecord`, that would require new test coverage not in scope here.
6. **A2 — `REPORT_NOT_FOUND` on `rcp issuance disclose` when no `ReportMetadata` exists is a documented error path (TD A2 §8) with no corresponding AC.** This is a reasonable API-contract-level test QA will still write (not a spec gap requiring escalation), but it is worth noting explicitly that traceability here comes from the Technical Design's API contract, not from Product Spec §8 — flagged for completeness, not as a defect.

None of the above block this test strategy from being complete against the stated ACs (all 15 ACs are covered per Section 2). They are flagged because implementation cannot fully finalize the test cases they touch (TC-A2-18, TC-A1-14, TC-A1-19/20 ordering assertions, TC-A1-26's Phase 4/5 legs) until Architecture responds.

---

## 8. Exit Criteria for QA Sign-Off

`[QA SIGN-OFF APPROVED]` for Workstream A will be issued only when **all** of the following are true:

1. **All 15 acceptance criteria (AC-A1-1–8, AC-A2-1–7) have executed, passing test cases** with captured evidence (execution output, logs), not merely code review confidence.
2. **Every negative/invariant-protecting test case passes:** both SK-write guard negative tests (TC-A1-16/17, and TC-A2-18 if promoted to a committed invariant per Section 7 item 1), the six-invariant regression suite (TC-A2-21), and the structural non-modification checks (TC-A2-08/09/10).
3. **The DLQ exercise (TC-A1-18) has been run against both event source mappings** with evidence the DLQ received the malformed event and the alarm fired. This is treated as implementation-complete-blocking per Section 5.1, not optional.
4. **The manual staged-environment disposal verification (Section 3.2, layer 3) has been run at least once per release candidate** with a documented outcome (disposal observed within the documented AWS window, or a documented, escalated anomaly if not).
5. **Both documented TOCTOU races (TC-A1-19/20) have at least the staged-environment observation evidence described**, even if the outcome is "race window not empirically triggered in this run" — the requirement is that the test was attempted and documented, not that a race was necessarily reproduced (it is characterized as low-probability by design).
6. **No unresolved item from Section 7 remains a hard blocker to a specific test case's pass/fail determination.** Items 2, 3, and 6 in Section 7 are non-blocking by nature (documented accepted risk / non-AC test). Items 1, 4, and 5 must be resolved by Architecture (even if the resolution is "confirmed as designed, no change needed") before the corresponding test cases (TC-A2-18, TC-A1-26 Phase 4/5 legs, TC-A1-14's bound assertion) can be marked complete rather than partial.
7. **No blocking defect classified as Application Bug remains open** against any A1 or A2 acceptance criterion.
8. **No major regression is detected** in the six-invariant regression suite (TC-A2-21) or the Phase 6/Phase 7 unmodified-source-tree check — any regression here is automatically a release blocker regardless of severity classification elsewhere, given this workstream's entire purpose is closing a constitutional-rule enforcement gap without reopening ratified architecture.
9. **Evidence for every "Manual-staged" level test case (Section 2/3 tables) is attached to the eventual test report** as either a captured terminal transcript, CloudWatch/CloudTrail log excerpt, or equivalent — code review alone is not evidence for these cases.

Until implementation exists, none of the above can be satisfied, and no sign-off decision — positive or negative — is possible. This document's completion represents readiness to begin implementation with a fully specified validation target, not a QA verdict on work that has not been done.

---

## 9. Traceability

- Product Specification: `docs/product/evidence_governance_workstream_a_product_spec.md` (FR-A1-1–6, AC-A1-1–8; FR-A2-1–7, AC-A2-1–7)
- ADR A1: `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
- Technical Design A1: `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
- ADR A2: `docs/architecture/adr_report_issuance_certification_gate.md`
- Technical Design A2: `docs/architecture/evidence_governance_workstream_a2_issuance_governance_technical_design.md`
- ADR — Certification Independence: `docs/architecture/adr_phase7_certification_independence.md`
- Phase 7 QA precedent (fixture-mutation convention reused here): `docs/qa/phase_7_audit_platform_integrity_test_plan.md`
- Product Constitution: `RCP_Product_Strategy.md`
