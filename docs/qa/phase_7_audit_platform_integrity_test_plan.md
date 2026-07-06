# QA / Test Plan

## Phase 7 — Audit Platform Integrity

---

## 1. Test Scope

### In Scope

- Prerequisite gate enforcement: `ReportMetadata.status = COMPLETE` is required before any certification activity; absent or non-COMPLETE records abort with `REPORT_NOT_COMPLETE` and no `CertificationJob` is created
- Idempotency gate enforcement: prior `CERTIFIED` record blocks re-certification without `--force`; prior `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` does not block
- All eight certification domain executions, individually and in combination:
  - `RUNNER_HEALTH`
  - `EVIDENCE_COMPLETENESS`
  - `EVIDENCE_INTEGRITY`
  - `EVIDENCE_LINEAGE`
  - `OBSERVATION_COVERAGE`
  - `SCHEDULER_INTEGRITY`
  - `METHODOLOGY_COMPLIANCE`
  - `REPORT_INTEGRITY`
- Terminal state determination (`CERTIFIED`, `CERTIFICATION_FAILED`, `CERTIFICATION_BLOCKED`) and `BLOCKED` precedence over `FAILED`
- `disclosed_failures` enumeration completeness and accuracy for all non-CERTIFIED terminal states
- `certification_summary` bounded mapping correctness (`INTEGRITY_VERIFIED`, `INTEGRITY_FAILED`, `INTEGRITY_BLOCKED`)
- `PlatformIntegrityCertificate` schema correctness — `cert_v1` compatibility gate
- Certificate persistence: S3 artifact write under `integrity/` prefix; `CertificationJob` and `CertificationMetadata` DynamoDB records written for all terminal states
- Certificate immutability: force re-runs produce a new S3 key; prior certificate artifacts preserved unmodified
- `CertificationJob` lifecycle: `PENDING → IN_PROGRESS → COMPLETE | FAILED`
- Non-mutation invariant: Phase 6, Phase 5, Phase 4, and earlier-phase records must not be written, updated, or deleted by any Phase 7 code path
- Operator CLI certification execution: `rcp certify audit`
- Operator CLI retrieval: `rcp retrieve cert-status`, `cert-summary`, `cert-domains`, `cert-json` — all read-only with provenance envelopes
- Error code correctness: `REPORT_NOT_COMPLETE`, `CERTIFICATION_ALREADY_CERTIFIED`, `S3_REPORT_ARTIFACT_READ_FAILURE`, `CERTIFICATION_NOT_FOUND`
- Determinism: identical Phase 6 inputs produce identical `domain_results[]`, `terminal_state`, and `disclosed_failures` within `cert_v1`
- `cert_v1` schema compatibility gate: structural backwards-compatibility guard blocking schema regressions

### Explicitly Out of Scope

- Re-computation or verification of Phase 5 reliability scores, composite scores, or labels — Phase 5 owns these
- Correctness of Phase 6 report generation — Phase 6 test plan governs this
- Direct reads of Phase 5 intelligence artifacts, Phase 4 aggregation artifacts, or Phase 1/2/3 raw evidence records — Phase 7 must never do any of these; static analysis confirms the boundary
- CI/CD integrations of any kind
- Customer portal, web interface, or dashboard
- Certification trend analysis or historical certification comparison
- Phase 8 Commercialization consumer contract implementation
- Phase 7.8 campaign fixture seeding from Phase 5 — the campaign consumes Phase 6.8 completed report artifacts

---

## 2. Test Environment

### Execution Environments

| Layer | Environment | Infrastructure |
| --- | --- | --- |
| Unit tests | Local / CI | Mocked DynamoDB (`moto` or `MagicMock`), mocked S3 client, in-memory fixtures |
| Integration tests | Local / CI | Localstack S3 + DynamoDB (`dev` stage) |
| Phase 7.8 Validation Campaign | `dev` or `staging` stage | Real AWS S3 + DynamoDB; Phase 6.8 campaign artifacts pre-seeded |

### Phase 6 Artifact Simulation Strategy

Unit and integration tests do not require live Phase 6 infrastructure. The simulation approach is:

1. **Base fixture**: A single canonical Phase 6 report artifact JSON fixture derived from the Phase 6.8 validation campaign artifact. This fixture contains all fields defined in `phase7_consumer_contract_v1` Section 3.2 with well-formed, internally consistent values.

2. **Fixture mutation pattern**: All negative-scenario and boundary fixtures are produced by applying a single targeted mutation to the base fixture. This ensures each failure is caused by the specific injected defect and not incidental fixture gaps.

3. **ReportMetadata fixture**: A DynamoDB record fixture mirroring all stable fields defined in `phase7_consumer_contract_v1` Section 3.1, with `status = COMPLETE` and all identity fields consistent with the base S3 artifact fixture.

4. **Mutation isolation rule**: Each negative test uses a distinct fixture file or a parameterized mutation function so that a given test case exercises exactly one injected defect.

5. **Distinct-value requirement**: The base fixture must ensure all score values across endpoints are distinct (no two sibling score values share the same value). `aggregate_set_hash` must be a realistic non-trivial string (e.g., a 64-character hex digest). `endpoint_id` values must be lexicographically distinct and pre-sorted.

See Section 8 for the complete fixture file enumeration.

---

## 3. Positive Scenarios

### TP-01: Successful certification — all eight domains PASS → `CERTIFIED`

**Purpose:** Verify the happy path: a clean Phase 6 report artifact with all integrity checks passing produces `CERTIFIED` terminal state with a correctly structured certificate.

**Input:**
- `ReportMetadata` with `status = COMPLETE`; all stable fields populated and consistent with the S3 artifact
- Phase 6 S3 artifact with all eight domain checks passable: all fields valid, counts consistent, hashes matching, `score_label` valid, `endpoints[]` lexicographically sorted, `methodology_disclosure` complete

**Expected output:**
- All eight `domain_results[]` entries have `status = PASSED`
- `terminal_state = CERTIFIED`
- `certification_summary = INTEGRITY_VERIFIED`
- `disclosed_failures = []`
- `domain_results[]` contains exactly eight entries in canonical order: `RUNNER_HEALTH`, `EVIDENCE_COMPLETENESS`, `EVIDENCE_INTEGRITY`, `EVIDENCE_LINEAGE`, `OBSERVATION_COVERAGE`, `SCHEDULER_INTEGRITY`, `METHODOLOGY_COMPLIANCE`, `REPORT_INTEGRITY`
- Platform Integrity Certificate written to S3 under `integrity/` prefix with correct key structure including `certjob_id` segment
- `CertificationMetadata` DynamoDB record written with `terminal_state = CERTIFIED`
- `CertificationJob` transitions `PENDING → IN_PROGRESS → COMPLETE`

**Validation logic:**
- Assert `len(domain_results) == 8`
- Assert all domain statuses are `PASSED`
- Assert `terminal_state == CERTIFIED`
- Assert `certification_summary == INTEGRITY_VERIFIED`
- Assert `disclosed_failures == []`
- Assert certificate artifact is deserializable and contains all required `cert_v1` fields
- Assert `CertificationJob.status == COMPLETE`
- Assert S3 key follows `integrity/{client_id}/{audit_id}/.../{certjob_id}/artifact.json` structure

**Acceptance criteria covered:** AC-3, AC-7, AC-8, AC-18, AC-22, AC-23, AC-26

---

### TP-02: Successful certification with multiple endpoints (`endpoint_count > 1`)

**Purpose:** Verify that `CERTIFIED` terminal state is produced correctly when `endpoint_count > 1`, exercising per-endpoint iteration in all domain checks.

**Input:**
- Clean Phase 6 report artifact fixture with three endpoints; all fields valid; `endpoints[]` lexicographically sorted; all per-endpoint analysis sub-sections present and non-null
- `ReportMetadata.endpoint_count = 3`; `executive_summary.endpoint_count = 3`; `len(endpoints[]) = 3`

**Expected output:**
- `terminal_state = CERTIFIED`
- All eight domain results `PASSED`
- Per-endpoint iteration completes without error across all domains that iterate `endpoints[]`

**Validation logic:**
- Assert `terminal_state == CERTIFIED`
- Assert all domain statuses are `PASSED`
- Assert `checks_passed == checks_performed` for every domain result

**Acceptance criteria covered:** AC-7, AC-8, AC-18

---

### TP-03: Idempotency — re-certifying a `CERTIFIED` audit without `--force` returns existing certificate

**Purpose:** Verify the idempotency gate: a second invocation without `--force` on a `CERTIFIED` audit identity tuple returns the existing `certificate_id` and S3 reference without creating a new `CertificationJob`.

**Input:**
- `CertificationMetadata` DynamoDB record with `terminal_state = CERTIFIED`, `certificate_id = cert_original`, `s3_certificate_ref = integrity/.../original/artifact.json`
- `rcp certify audit` invoked without `--force`

**Expected output:**
- Structured error `CERTIFICATION_ALREADY_CERTIFIED` returned to caller
- Existing `certificate_id = cert_original` returned
- No new `CertificationJob` record written
- No new S3 certificate artifact written

**Validation logic:**
- Assert error code is `CERTIFICATION_ALREADY_CERTIFIED`
- Assert returned `certificate_id == cert_original`
- Assert DynamoDB `#CERTJOB#` SK record count unchanged before and after invocation
- Assert no new object appears under `integrity/` S3 prefix

**Acceptance criteria covered:** AC-4

---

### TP-04: `--force` override re-certifies a `CERTIFIED` audit and produces a new certificate

**Purpose:** Verify that `--force` bypasses the idempotency gate, produces a new certification event with a new `certificate_id`, and preserves the prior certificate artifact at its original S3 key unmodified.

**Input:**
- `CertificationMetadata` record with `terminal_state = CERTIFIED`, `certificate_id = cert_original`, S3 artifact at its original key
- Clean Phase 6 report artifact (same as TP-01 fixture)
- `rcp certify audit` invoked with `--force`

**Expected output:**
- New `certificate_id` generated (`cert_new != cert_original`)
- New S3 artifact written at a new key (different `certjob_id` segment)
- Prior S3 artifact at original key still present and byte-identical to its original content
- `CertificationMetadata` updated with `certificate_id = cert_new` and new `completed_at`
- Both runs produce identical `domain_results[]`, `terminal_state`, and `disclosed_failures` (determinism)

**Validation logic:**
- Assert `certificate_id != cert_original`
- Assert S3 `GetObject` on the original key succeeds and content is unchanged
- Assert `terminal_state == CERTIFIED` on the new run
- Assert `domain_results[]` content is identical between first and second run, excluding `certificate_id` and `generated_at`

**Acceptance criteria covered:** AC-5, AC-21

---

## 4. Negative Scenarios

### TN-01: `ReportMetadata` absent → `REPORT_NOT_COMPLETE` error, no job created

**Purpose:** Verify the prerequisite gate aborts with `REPORT_NOT_COMPLETE` when no `ReportMetadata` record exists for the identity tuple, and no `CertificationJob` record is created.

**Input:**
- DynamoDB returns no item for the `ReportMetadata` GetItem lookup (record absent)

**Expected output:**
- Structured error `REPORT_NOT_COMPLETE` surfaced to caller
- No `CertificationJob` record written
- Pipeline terminates before domain execution

**Validation logic:**
- Assert error code is `REPORT_NOT_COMPLETE`
- Assert zero `CertificationJob` records exist for this identity

**Acceptance criteria covered:** AC-1

---

### TN-02: `ReportMetadata.status != COMPLETE` → `REPORT_NOT_COMPLETE` error

**Purpose:** Verify the prerequisite gate aborts with `REPORT_NOT_COMPLETE` when `ReportMetadata` exists but `status` is not `COMPLETE`, regardless of the specific non-COMPLETE status value.

**Parameterized sub-cases:**

| Sub-case | `ReportMetadata.status` value |
| --- | --- |
| TN-02a | `PENDING` |
| TN-02b | `IN_PROGRESS` |
| TN-02c | `FAILED` |
| TN-02d | `GENERATING` (any non-COMPLETE value) |

**Expected output (all sub-cases):**
- Structured error `REPORT_NOT_COMPLETE` surfaced to caller
- No `CertificationJob` record written

**Validation logic:**
- Assert error code is `REPORT_NOT_COMPLETE` for each sub-case
- Assert zero `CertificationJob` records for this identity

**Acceptance criteria covered:** AC-2

---

### TN-03: `EVIDENCE_COMPLETENESS` failure (missing required reliability metrics field) → `CERTIFICATION_FAILED`

**Purpose:** Verify that a null required `reliability_metrics` field on one endpoint causes `EVIDENCE_COMPLETENESS` domain to fail (violates EC-3) and produces `CERTIFICATION_FAILED`.

**Input:**
- Base fixture mutated: one endpoint has `reliability_metrics.total_executions = null`
- `ReportMetadata.status = COMPLETE`

**Expected output:**
- `EVIDENCE_COMPLETENESS` domain result: `status = FAILED`, `failure_details` non-empty, `checks_passed < checks_performed`
- All other seven domains: `status = PASSED`
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures = ["EVIDENCE_COMPLETENESS"]`
- Certificate written to S3; `CertificationMetadata` written with `terminal_state = CERTIFICATION_FAILED`

**Validation logic:**
- Assert `EVIDENCE_COMPLETENESS` domain `status == FAILED`
- Assert `len(failure_details) > 0` for that domain result
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert `EVIDENCE_COMPLETENESS` is in `disclosed_failures`
- Assert certificate artifact is persisted to S3

**Acceptance criteria covered:** AC-19, AC-22, AC-27

---

### TN-04: `EVIDENCE_LINEAGE` failure (broken `aggregate_set_hash`) → `CERTIFICATION_FAILED`

**Purpose:** Verify that a mismatch between `intelligence_provenance.aggregate_set_hash` in the S3 artifact and `ReportMetadata.aggregate_set_hash` causes `EVIDENCE_LINEAGE` domain to fail (violates EL-2).

**Input:**
- Base fixture mutated: `intelligence_provenance.aggregate_set_hash = "tampered_hash_value"` while `ReportMetadata.aggregate_set_hash` retains the correct original value

**Expected output:**
- `EVIDENCE_LINEAGE` domain result: `status = FAILED`, `failure_details` non-empty
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `EVIDENCE_LINEAGE`

**Validation logic:**
- Assert `EVIDENCE_LINEAGE` domain `status == FAILED`
- Assert `failure_details` references the hash mismatch
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert `EVIDENCE_LINEAGE` in `disclosed_failures`

**Acceptance criteria covered:** AC-12, AC-19, AC-27

---

### TN-05: `OBSERVATION_COVERAGE` failure (endpoint_count mismatch) → `CERTIFICATION_FAILED`

**Purpose:** Verify that a mismatch between `executive_summary.endpoint_count` and the actual count of elements in `endpoints[]` causes `OBSERVATION_COVERAGE` domain to fail (violates OC-2).

**Input:**
- Base fixture mutated: `executive_summary.endpoint_count = 3` but `endpoints[]` contains only 2 elements

**Expected output:**
- `OBSERVATION_COVERAGE` domain result: `status = FAILED`, `failure_details` describing the actual vs expected count
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `OBSERVATION_COVERAGE`

**Validation logic:**
- Assert `OBSERVATION_COVERAGE` domain `status == FAILED`
- Assert `failure_details` non-empty and references the count discrepancy
- Assert `terminal_state == CERTIFICATION_FAILED`

**Acceptance criteria covered:** AC-11, AC-19, AC-27

---

### TN-06: `RUNNER_HEALTH` failure (total_executions out of range) → `CERTIFICATION_FAILED`

**Purpose:** Verify that `executive_summary.total_executions = 0` causes `RUNNER_HEALTH` domain to fail (violates RH-1: execution count must be greater than zero).

**Input:**
- Base fixture mutated: `executive_summary.total_executions = 0`

**Expected output:**
- `RUNNER_HEALTH` domain result: `status = FAILED`, `failure_details` non-empty
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `RUNNER_HEALTH`

**Validation logic:**
- Assert `RUNNER_HEALTH` domain `status == FAILED`
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert `RUNNER_HEALTH` in `disclosed_failures`

**Acceptance criteria covered:** AC-19, AC-27

---

### TN-07: `SCHEDULER_INTEGRITY` failure (execution density anomaly) → `CERTIFICATION_FAILED`

**Purpose:** Verify that a large discrepancy in per-endpoint execution counts exceeding the allowed variance causes `SCHEDULER_INTEGRITY` domain to fail (violates SI-2).

**Input:**
- Base fixture (three endpoints) mutated: one endpoint `reliability_metrics.total_executions = 100`; other two endpoints `reliability_metrics.total_executions = 10`; producing an execution density variance that exceeds the `methodology_disclosure` allowed variance

**Expected output:**
- `SCHEDULER_INTEGRITY` domain result: `status = FAILED`, `failure_details` describing the density anomaly
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `SCHEDULER_INTEGRITY`

**Validation logic:**
- Assert `SCHEDULER_INTEGRITY` domain `status == FAILED`
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert `SCHEDULER_INTEGRITY` in `disclosed_failures`

**Acceptance criteria covered:** AC-19, AC-27

---

### TN-08: `METHODOLOGY_COMPLIANCE` failure (missing `methodology_trace`) → `CERTIFICATION_FAILED`

**Purpose:** Verify that a null `methodology_trace` on one endpoint's `stability_analysis` sub-section causes `METHODOLOGY_COMPLIANCE` domain to fail (violates MC-4).

**Input:**
- Base fixture mutated: one endpoint has `stability_analysis.methodology_trace = null`

**Expected output:**
- `METHODOLOGY_COMPLIANCE` domain result: `status = FAILED`, `failure_details` referencing the specific sub-section and endpoint
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `METHODOLOGY_COMPLIANCE`

**Validation logic:**
- Assert `METHODOLOGY_COMPLIANCE` domain `status == FAILED`
- Assert `failure_details` non-empty and references the affected sub-section
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert `METHODOLOGY_COMPLIANCE` in `disclosed_failures`

**Acceptance criteria covered:** AC-9, AC-16, AC-19, AC-27

---

### TN-09: `REPORT_INTEGRITY` failure (invalid `score_label` value) → `CERTIFICATION_FAILED`

**Purpose:** Verify that an invalid `executive_summary.score_label` value causes `REPORT_INTEGRITY` domain to fail (violates RI-3: `score_label` must be a member of `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}`).

**Input:**
- Base fixture mutated: `executive_summary.score_label = "VERY_HIGH_CONFIDENCE"`

**Expected output:**
- `REPORT_INTEGRITY` domain result: `status = FAILED`, `failure_details` naming the invalid value
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains `REPORT_INTEGRITY`

**Validation logic:**
- Assert `REPORT_INTEGRITY` domain `status == FAILED`
- Assert `failure_details` references the invalid `score_label` value
- Assert `terminal_state == CERTIFICATION_FAILED`

**Acceptance criteria covered:** AC-14, AC-19, AC-27

---

### TN-10: `EVIDENCE_INTEGRITY` failure (`aggregate_set_hash` mismatch between `ReportMetadata` and S3 artifact) → `CERTIFICATION_FAILED`

**Purpose:** Verify that `intelligence_provenance.aggregate_set_hash` in the S3 artifact not matching `ReportMetadata.aggregate_set_hash` causes `EVIDENCE_INTEGRITY` domain to fail (violates EI-1).

**Note on domain overlap:** The same hash mismatch also triggers `EVIDENCE_LINEAGE` EL-2. This is by design — both domains independently verify hash consistency. This test confirms `EVIDENCE_INTEGRITY` produces its own `FAILED` result and that both domain identifiers appear in `disclosed_failures`.

**Input:**
- `ReportMetadata.aggregate_set_hash = "correct_hash_abc123"`
- Base fixture mutated: `intelligence_provenance.aggregate_set_hash = "different_hash_xyz789"`

**Expected output:**
- `EVIDENCE_INTEGRITY` domain result: `status = FAILED`
- `EVIDENCE_LINEAGE` domain result: `status = FAILED` (EL-2 triggered by same mismatch)
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains both `EVIDENCE_INTEGRITY` and `EVIDENCE_LINEAGE`

**Validation logic:**
- Assert `EVIDENCE_INTEGRITY` domain `status == FAILED`
- Assert `EVIDENCE_LINEAGE` domain `status == FAILED`
- Assert `terminal_state == CERTIFICATION_FAILED`
- Assert both domain identifiers are in `disclosed_failures`

**Acceptance criteria covered:** AC-19, AC-27

---

### TN-11: Multiple domains fail simultaneously → `CERTIFICATION_FAILED`; all failed domains in `disclosed_failures`

**Purpose:** Verify that when multiple domains fail simultaneously, `CERTIFICATION_FAILED` is produced and all failed domain identifiers appear in `disclosed_failures`, with non-empty `failure_details` for each.

**Input:**
- Base fixture with three simultaneous mutations:
  1. `executive_summary.score_label = "INVALID_LABEL"` — triggers `REPORT_INTEGRITY` FAILED (RI-3)
  2. `methodology_disclosure.limitations` key absent entirely — triggers `METHODOLOGY_COMPLIANCE` FAILED (MC-3)
  3. `executive_summary.endpoint_count = 99` while `len(endpoints[]) = 2` — triggers `OBSERVATION_COVERAGE` FAILED (OC-2)

**Expected output:**
- `REPORT_INTEGRITY` domain: `status = FAILED`
- `METHODOLOGY_COMPLIANCE` domain: `status = FAILED`
- `OBSERVATION_COVERAGE` domain: `status = FAILED`
- Remaining five domains: `status = PASSED`
- `terminal_state = CERTIFICATION_FAILED`
- `disclosed_failures` contains all three failed domain identifiers
- Each failed domain result has at least one entry in `failure_details`

**Validation logic:**
- Assert three domain results with `status == FAILED`
- Assert five domain results with `status == PASSED`
- Assert `len(disclosed_failures) == 3`
- Assert `disclosed_failures` contains `REPORT_INTEGRITY`, `METHODOLOGY_COMPLIANCE`, and `OBSERVATION_COVERAGE`
- Assert each failed domain `failure_details` is non-empty

**Acceptance criteria covered:** AC-19, AC-27

---

### TN-12: S3 artifact unreadable → `CERTIFICATION_BLOCKED`

**Purpose:** Verify that an S3 `GetObject` failure on the Phase 6 report artifact produces `CERTIFICATION_BLOCKED` terminal state, a `CERTIFICATION_BLOCKED` certificate is written where possible, and `CertificationJob` transitions to `FAILED`.

**Input:**
- `ReportMetadata.status = COMPLETE` and `s3_artifact_ref` points to a key that does not exist (simulated via mocked S3 returning `NoSuchKey`)

**Expected output:**
- All eight domain results: `status = BLOCKED` (S3 read failure prevents all domain inputs from loading)
- `terminal_state = CERTIFICATION_BLOCKED`
- `certification_summary = INTEGRITY_BLOCKED`
- `disclosed_failures` contains all eight domain identifiers
- `CERTIFICATION_BLOCKED` certificate written to S3 under `integrity/` prefix (populated from `ReportMetadata` fields)
- `CertificationMetadata` DynamoDB record written with `terminal_state = CERTIFICATION_BLOCKED`
- `CertificationJob` transitions to `FAILED` with `failure_stage` and `failure_reason` populated

**Validation logic:**
- Assert `terminal_state == CERTIFICATION_BLOCKED`
- Assert `certification_summary == INTEGRITY_BLOCKED`
- Assert all eight domain results have `status == BLOCKED`
- Assert `len(disclosed_failures) == 8`
- Assert `CertificationJob.status == FAILED`
- Assert `CertificationJob.failure_stage` and `failure_reason` are non-null

**Acceptance criteria covered:** AC-20, AC-22, AC-28

---

## 5. Boundary and Edge Cases

### TB-01: `endpoint_count = 1` (minimum valid)

**Purpose:** Verify that a single-endpoint audit certifies correctly without array-handling errors in any domain.

**Input:**
- Base fixture with exactly one endpoint; all fields valid; `executive_summary.endpoint_count = 1`; `ReportMetadata.endpoint_count = 1`; `len(endpoints[]) = 1`

**Expected output:**
- `terminal_state = CERTIFIED`
- All eight domain results `PASSED`
- No per-endpoint iteration errors; domains that iterate `endpoints[]` handle length-one arrays correctly

**Validation logic:**
- Assert `terminal_state == CERTIFIED`
- Assert all domain statuses are `PASSED`

**Acceptance criteria covered:** AC-8, AC-18

---

### TB-02: `composite_score = 0.000` (minimum valid — must certify if all structural checks pass)

**Purpose:** Verify that a `composite_score_value` of `0.000` does not trigger a `REPORT_INTEGRITY` failure. Phase 7 must not impose reliability thresholds; `0.000` is a valid value within the defined range `[0.0, 1.0]` (RI-4).

**Input:**
- Base fixture with `executive_summary.composite_score_value = 0.000` and `executive_summary.score_label = "LOW_CONFIDENCE"`

**Expected output:**
- `REPORT_INTEGRITY` domain: `status = PASSED` (RI-4 permits 0.0)
- `terminal_state = CERTIFIED`

**Validation logic:**
- Assert `REPORT_INTEGRITY` domain `checks_passed == checks_performed`
- Assert `terminal_state == CERTIFIED`

**Acceptance criteria covered:** AC-8, AC-18

---

### TB-03: `composite_score = 1.000` (maximum valid)

**Purpose:** Verify that a `composite_score_value` of `1.000` passes `REPORT_INTEGRITY` domain check RI-4.

**Input:**
- Base fixture with `executive_summary.composite_score_value = 1.000` and `executive_summary.score_label = "HIGH_CONFIDENCE"`

**Expected output:**
- `REPORT_INTEGRITY` domain: `status = PASSED`
- `terminal_state = CERTIFIED`

**Validation logic:**
- Assert `REPORT_INTEGRITY` domain `checks_passed == checks_performed`
- Assert `terminal_state == CERTIFIED`

**Acceptance criteria covered:** AC-8, AC-18

---

### TB-04: `disclosed_failures = []` (empty array, not null) on `CERTIFIED` certificate

**Purpose:** Verify that the `disclosed_failures` field is exactly an empty array — not null, not absent — when `terminal_state = CERTIFIED`.

**Input:** Clean base fixture (same as TP-01)

**Expected output:**
- `disclosed_failures` is an empty list `[]`
- `type(disclosed_failures) == list`
- `terminal_state == CERTIFIED`

**Validation logic:**
- Assert `isinstance(disclosed_failures, list)`
- Assert `len(disclosed_failures) == 0`

**Acceptance criteria covered:** AC-18

---

### TB-05: `CERTIFICATION_BLOCKED` takes precedence over `CERTIFICATION_FAILED` when both would apply

**Purpose:** Verify terminal state precedence (TA-1 in validation spec): when one domain is `BLOCKED` and another is `FAILED`, `CERTIFICATION_BLOCKED` is the terminal state.

**Test approach:** This scenario is verified at the `determine_terminal_state()` unit test level in `test_engine.py`, using a fabricated `domain_results[]` list with one entry having `status = BLOCKED` and one entry having `status = FAILED` as direct input to the terminal state determination function. This approach provides deterministic coverage without requiring a partially-parseable S3 artifact.

**Input:**
- `domain_results = [DomainResult(domain=RUNNER_HEALTH, status=BLOCKED, ...), DomainResult(domain=REPORT_INTEGRITY, status=FAILED, ...), ...]` (six remaining domains PASSED)

**Expected output:**
- `determine_terminal_state(domain_results) == CERTIFICATION_BLOCKED`
- `disclosed_failures` contains both the `BLOCKED` domain identifier and the `FAILED` domain identifier

**Validation logic:**
- Assert `terminal_state == CERTIFICATION_BLOCKED` (not `CERTIFICATION_FAILED`)
- Assert both identifiers present in `disclosed_failures`

**Acceptance criteria covered:** AC-20; TA-1 (validation spec)

---

## 6. Non-Mutation Verification

Phase 7 is prohibited from writing, updating, or deleting any Phase 6, Phase 5, Phase 4, or earlier-phase artifact or DynamoDB record. The following test approach enforces non-mutation rules NM-1 through NM-6 in the validation spec.

### 6.1 Repository Write Path Assertions

**Test location:** `tests/unit/audit_platform_integrity/test_repository.py`

All DynamoDB `put_item` and `update_item` call sites in `repository.py` are exercised via mocked client assertions. The test asserts on the SK values produced by each write method.

| Assertion | Pass Criterion |
| --- | --- |
| All `put_item` SK values start with `AUDIT#...#CERTJOB#` or contain `#CERT#` | No write SK contains `#RPTJOB#`, `#RPT#...#META`, `#INTEL#`, `#INTJOB#`, `#AGG#`, `#AGGJOB#`, `#SET`, or `#MANIFEST#` |
| All `update_item` SK values target `CertificationJob` records only | Lifecycle updates confined to `#CERTJOB#` SK prefix |
| `CertificationMetadata` write SK contains `#CERT#{cert_version}#META` | Confirms correct Phase 7 namespace |
| No `delete_item` calls in any Phase 7 code path | `repository.py` has no delete method; assertion confirms this statically |
| `ReportMetadata` GetItem is read-only | No `update_item` or `put_item` call targeting the `ReportMetadata` SK exists in any Phase 7 code path |

### 6.2 Publisher Write Path Assertions

**Test location:** `tests/unit/audit_platform_integrity/test_publisher.py`

All S3 operations in `publisher.py` are exercised via mocked S3 client assertions.

| Assertion | Pass Criterion |
| --- | --- |
| All `put_object` S3 keys start with `integrity/` | No key with `reports/`, `intelligence/`, or `raw-results/` prefix |
| No `delete_object` calls in `publisher.py` | Publisher is write-once for certificates; no delete path exists |
| S3 `GetObject` for Phase 6 artifact uses key from `ReportMetadata.s3_artifact_ref` verbatim | No independent S3 key construction for Phase 6 artifact |
| Certificate key structure correct | Key matches `integrity/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{report_version}/{cert_version}/{certjob_id}/artifact.json` |

### 6.3 Integration Non-Mutation Assertion

**Test location:** `tests/integration/audit_platform_integrity/test_certification_pipeline_integration.py`

| Step | Assertion |
| --- | --- |
| Before Phase 7 invocation | Snapshot `ReportMetadata` DynamoDB record (all attributes and values) |
| After Phase 7 completion | Re-read `ReportMetadata`; assert all attributes byte-identical to pre-invocation snapshot |
| Before Phase 7 invocation | Record S3 `ETag` of Phase 6 report artifact at `s3_artifact_ref` |
| After Phase 7 completion | Assert S3 `ETag` unchanged; artifact bytes identical |
| Phase 5/Phase 4 records | DynamoDB scan on `#INTEL#`, `#INTJOB#`, `#AGG#` SK prefixes shows no new records for this client/audit identity |

**Acceptance criteria covered:** AC-24, AC-25; NM-1 through NM-6 (validation spec)

---

## 7. Acceptance Criteria Coverage Matrix

| AC | Description (abbreviated) | Covered By |
| --- | --- | --- |
| AC-1 | `ReportMetadata` absent → `REPORT_NOT_COMPLETE`; no `CertificationJob` | TN-01 |
| AC-2 | `status != COMPLETE` → `REPORT_NOT_COMPLETE`; no `CertificationJob` | TN-02 |
| AC-3 | Gate passes → proceed with certification | TP-01 |
| AC-4 | Prior `CERTIFIED`, no `--force` → return existing cert; no new job | TP-03 |
| AC-5 | Prior `CERTIFIED`, `--force` → new cert; prior artifact preserved | TP-04 |
| AC-6 | Prior `CERTIFICATION_FAILED` → proceed without `--force` | Unit test: `test_engine.py` idempotency cases |
| AC-7 | `domain_results[]` contains exactly eight entries | TP-01, TP-02; `test_phase7_cert_schema.py` |
| AC-8 | All eight PASSED → `CERTIFIED` | TP-01 |
| AC-9 | `methodology_disclosure` absent → `METHODOLOGY_COMPLIANCE` FAILED | TN-08 |
| AC-10 | `composite_score_value` outside `[0.0, 1.0]` → `REPORT_INTEGRITY` FAILED | Unit test: `test_report_integrity.py` RI-4 case |
| AC-11 | `endpoint_count` mismatch → `OBSERVATION_COVERAGE` FAILED | TN-05 |
| AC-12 | `aggregate_set_hash` mismatch → `EVIDENCE_LINEAGE` FAILED | TN-04 |
| AC-13 | Duplicate `endpoint_id` values → `REPORT_INTEGRITY` FAILED | Unit test: `test_report_integrity.py` RI-6 case |
| AC-14 | Invalid `score_label` → `REPORT_INTEGRITY` FAILED | TN-09 |
| AC-15 | `endpoints[]` unsorted → `REPORT_INTEGRITY` FAILED | Unit test: `test_report_integrity.py` RI-5 case |
| AC-16 | Missing endpoint sub-section → `METHODOLOGY_COMPLIANCE` FAILED | TN-08 |
| AC-17 | `ReportMetadata.endpoint_count != executive_summary.endpoint_count` → `EVIDENCE_INTEGRITY` FAILED | Unit test: `test_evidence_integrity.py` EI-5 case |
| AC-18 | All eight PASSED → `CERTIFIED`; `disclosed_failures = []` | TP-01, TB-04 |
| AC-19 | One+ FAILED → `CERTIFICATION_FAILED`; all failed domains in `disclosed_failures` | TN-03 through TN-11 |
| AC-20 | Infrastructure failure → `CERTIFICATION_BLOCKED` | TN-12, TB-05 |
| AC-21 | Identical inputs → identical `domain_results[]` and `terminal_state` | TP-04 (determinism check) |
| AC-22 | Certificate written to S3; `CertificationMetadata` written for all terminal states | TP-01 (`CERTIFIED`); TN-03 (`CERTIFICATION_FAILED`); TN-12 (`CERTIFICATION_BLOCKED`) |
| AC-23 | Certificate contains all required `cert_v1` fields | TP-01; `test_phase7_cert_schema.py` |
| AC-24 | No Phase 5 conclusions re-derived in certificate | Section 6.1 non-mutation tests; `test_phase7_cert_schema.py` |
| AC-25 | No Phase 6 record mutations | Section 6.2–6.3 non-mutation tests |
| AC-26 | `CertificationJob` transitions `PENDING → COMPLETE` | TP-01; integration pipeline test |
| AC-27 | `CERTIFICATION_FAILED`: `disclosed_failures` complete; `failure_details` non-empty per domain | TN-03 through TN-11 |
| AC-28 | `CERTIFICATION_BLOCKED`: `disclosed_failures` complete; `certification_summary = INTEGRITY_BLOCKED` | TN-12 |
| AC-29 | `cert-status` returns required fields; no writes | TR-01 |
| AC-30 | `cert-json` returns full certificate JSON with provenance envelope | TR-04 |
| AC-31 | No `CertificationMetadata` → `CERTIFICATION_NOT_FOUND`; no writes | TR-05 |
| AC-32 | `cert-summary` with `CERTIFICATION_FAILED` shows domain statuses and `disclosed_failures` | TR-03 |

---

## 8. Test Data Requirements

### 8.1 Fixture Strategy

All test fixtures are derived from the Phase 6.8 validation campaign artifact as the canonical baseline. The base fixture is the authoritative clean-state reference. All mutation fixtures derive from the base by applying a single targeted field change unless multiple simultaneous mutations are explicitly required by the test scenario.

### 8.2 Base Fixture Requirements

The base fixture must satisfy all of the following before any mutation is applied:

- `ReportMetadata.status = COMPLETE`
- All identity fields consistent between `ReportMetadata` and the S3 artifact (`report_id`, `report_version`, `intelligence_version`, `aggregate_set_hash`, `endpoint_count`)
- `aggregate_set_hash` present and matching in both records; value is a non-trivial 64-character hex string
- `executive_summary.endpoint_count` matches `len(endpoints[])` and `ReportMetadata.endpoint_count`
- All required `reliability_metrics`, `stability_analysis`, `burst_analysis`, `consistency_analysis`, and `endpoint_score` sub-sections present and non-null for all endpoints
- All `methodology_trace` fields non-null on all endpoints
- `methodology_disclosure` section present and complete, including `limitations` array (may be empty but key must be present)
- `endpoints[]` lexicographically sorted by `endpoint_id`; all `endpoint_id` values distinct and non-null
- `executive_summary.score_label` is a valid bounded-set member
- `executive_summary.composite_score_value` in `[0.0, 1.0]` with 3 decimal places
- `identity.report_version = "report_v1"` and `intelligence_provenance.intelligence_version = "intel_v1"`
- All per-endpoint score fields distinct (no two sibling score values share the same value)

### 8.3 Required Fixture Files

| Fixture File | Used By | Mutation Applied |
| --- | --- | --- |
| `base_report_metadata.json` | TP-01, TP-02, TP-03, TP-04, TB-01–TB-04, TN-03–TN-12 | None (clean state) |
| `base_report_artifact.json` | TP-01, TP-02, TP-04, TB-02, TB-03, TB-04 | None (clean state) |
| `base_report_artifact_single_endpoint.json` | TB-01 | Single endpoint; all fields valid |
| `report_artifact_zero_composite_score.json` | TB-02 | `composite_score_value = 0.000`; `score_label = "LOW_CONFIDENCE"` |
| `report_artifact_max_composite_score.json` | TB-03 | `composite_score_value = 1.000`; `score_label = "HIGH_CONFIDENCE"` |
| `report_artifact_missing_reliability_metrics.json` | TN-03 | One endpoint: `reliability_metrics.total_executions = null` |
| `report_artifact_lineage_hash_mismatch.json` | TN-04 | `intelligence_provenance.aggregate_set_hash = "tampered_hash_value"` |
| `report_artifact_endpoint_count_mismatch.json` | TN-05 | `executive_summary.endpoint_count = 3`; `len(endpoints[]) = 2` |
| `report_artifact_zero_total_executions.json` | TN-06 | `executive_summary.total_executions = 0` |
| `report_artifact_density_anomaly.json` | TN-07 | One endpoint `reliability_metrics.total_executions = 100`; others `= 10` |
| `report_artifact_missing_methodology_trace.json` | TN-08 | One endpoint `stability_analysis.methodology_trace = null` |
| `report_artifact_invalid_score_label.json` | TN-09 | `executive_summary.score_label = "VERY_HIGH_CONFIDENCE"` |
| `report_artifact_integrity_hash_mismatch.json` | TN-10 | `intelligence_provenance.aggregate_set_hash = "different_hash_xyz789"` with `ReportMetadata.aggregate_set_hash = "correct_hash_abc123"` |
| `report_artifact_multi_domain_failure.json` | TN-11 | Three simultaneous mutations: invalid `score_label`, absent `limitations` key, `endpoint_count` mismatch |
| `certification_metadata_certified.json` | TP-03, TP-04 | `CertificationMetadata` DynamoDB fixture with `terminal_state = CERTIFIED` |
| `certification_metadata_failed.json` | TR-03; `test_engine.py` idempotency case | `CertificationMetadata` fixture with `terminal_state = CERTIFICATION_FAILED` |

### 8.4 Fixture Storage Location

All fixtures reside under `tests/fixtures/phase7/`. The `base_report_artifact.json` fixture is the single authoritative source; all mutation files are separate files (not runtime-generated modifications) to ensure test isolation and deterministic execution.

---

## 9. Unit vs Integration vs Live Validation

### 9.1 Test Suite Structure

```
tests/
├── unit/
│   ├── test_phase7_cert_schema.py             # cert_v1 compatibility gate test (BLOCKING)
│   └── audit_platform_integrity/
│       ├── test_models.py                     # Pydantic schema validation
│       ├── test_engine.py                     # Pipeline gate, idempotency, terminal state
│       ├── test_repository.py                 # DynamoDB record construction + non-mutation
│       ├── test_publisher.py                  # S3 serialization + non-mutation
│       ├── test_commands.py                   # CLI argument validation and output format
│       ├── test_identity.py                   # certjob_id and certificate_id generation
│       └── domains/
│           ├── test_runner_health.py          # RH-1 through RH-4
│           ├── test_evidence_completeness.py  # EC-1 through EC-4
│           ├── test_evidence_integrity.py     # EI-1 through EI-5
│           ├── test_evidence_lineage.py       # EL-1 through EL-5
│           ├── test_observation_coverage.py   # OC-1 through OC-5
│           ├── test_scheduler_integrity.py    # SI-1 through SI-3
│           ├── test_methodology_compliance.py # MC-1 through MC-5
│           └── test_report_integrity.py       # RI-1 through RI-9
└── integration/
    └── audit_platform_integrity/
        ├── test_certification_pipeline_integration.py
        └── test_cli_certification_commands.py
```

### 9.2 Unit Test Coverage

#### `test_phase7_cert_schema.py` — `cert_v1` Compatibility Gate Test

This is the blocking gate test for Phase 7 schema changes. It validates the `PlatformIntegrityCertificate` Pydantic model against the `cert_v1` schema definition.

| Test Case | Description |
| --- | --- |
| All required `cert_v1` fields present | Pydantic model instantiates without error for a complete fixture |
| `certificate_version = cert_v1` enforced | Any other value raises `ValidationError` |
| `CERTIFICATION_SUMMARY_MAP` correct | `CERTIFIED → INTEGRITY_VERIFIED`, `CERTIFICATION_FAILED → INTEGRITY_FAILED`, `CERTIFICATION_BLOCKED → INTEGRITY_BLOCKED` |
| `domain_results[]` exactly eight entries | Fewer or more than eight raises `ValidationError` |
| `certificate_id` carries `cert_` prefix | Identity generation produces correct prefix |
| JSON serialization byte-identical for identical inputs | `sort_keys=True` produces deterministic output |
| Missing required field | `ValidationError` raised for each required field individually |

**Failure of this test blocks Phase 7 implementation changes.**

---

#### `test_models.py` — Pydantic Schema Validation

| Test Case | Description |
| --- | --- |
| Valid certificate from complete fixture | No Pydantic `ValidationError` |
| Missing `certificate_id` | `ValidationError` |
| Missing `domain_results` | `ValidationError` |
| Missing `disclosed_failures` | `ValidationError` |
| `terminal_state` not in bounded set | `ValidationError` if validator enforces bounded set |
| `certificate_version != cert_v1` | `ValidationError` |
| `domain_results[]` with 7 entries | `ValidationError` or assertion error |
| `domain_results[]` with 9 entries | `ValidationError` or assertion error |
| `disclosed_failures` is null | `ValidationError` |

---

#### `test_engine.py` — Certification Pipeline Logic

| Test Case | Description |
| --- | --- |
| Happy path: gate passes, all domains PASSED | `terminal_state = CERTIFIED`; `CertificationJob.status = COMPLETE` |
| Gate failure: `ReportMetadata` absent | `REPORT_NOT_COMPLETE`; no `CertificationJob` written |
| Gate failure: `status = PENDING` | `REPORT_NOT_COMPLETE`; no `CertificationJob` written |
| Gate failure: `status = IN_PROGRESS` | `REPORT_NOT_COMPLETE`; no job written |
| Gate failure: `status = FAILED` | `REPORT_NOT_COMPLETE`; no job written |
| Idempotency: `CERTIFIED`, no `--force` | `CERTIFICATION_ALREADY_CERTIFIED`; no new job |
| Idempotency: `CERTIFIED`, `--force` | New certification event; new `certjob_id` |
| Idempotency: `CERTIFICATION_FAILED`, no `--force` | Proceeds with new certification attempt |
| Idempotency: `CERTIFICATION_BLOCKED`, no `--force` | Proceeds with new certification attempt |
| One domain FAILED | `terminal_state = CERTIFICATION_FAILED` |
| One domain BLOCKED | `terminal_state = CERTIFICATION_BLOCKED` |
| One BLOCKED, one FAILED | `terminal_state = CERTIFICATION_BLOCKED` (BLOCKED takes precedence) |
| All domains PASSED | `terminal_state = CERTIFIED` |
| `disclosed_failures` populated correctly for FAILED | Domain identifiers of all failed domains; no omissions |
| `disclosed_failures` empty for CERTIFIED | `disclosed_failures = []` |
| `CertificationJob` happy path lifecycle | `PENDING → IN_PROGRESS → COMPLETE` |
| `CertificationJob` failure transition | `PENDING → IN_PROGRESS → FAILED` on S3 read error |
| `generated_at` sourced from `engine.py` entry | Domain modules do not call `datetime.now()` |
| `domain_results[]` ordered by canonical set | Array order matches bounded set sequence |

---

#### `test_repository.py` — DynamoDB Records

| Test Case | Description |
| --- | --- |
| `CertificationJob` PK/SK construction | PK = `CLIENT#{client_id}`; SK = `AUDIT#{audit_id}#CERTJOB#{certjob_id}` |
| `CertificationMetadata` PK/SK construction | Correct full SK with all version components including `#CERT#{cert_version}#META` |
| `record_type = certification_job` | Correct value on `CertificationJob` record |
| `record_type = certification_metadata` | Correct value on `CertificationMetadata` record |
| Status transitions write correct fields | `COMPLETE` write includes `certificate_id`, `s3_certificate_ref`, `completed_at` |
| `FAILED` transition writes `failure_stage` and `failure_reason` | Both fields non-null on FAILED job |
| No Phase 6 SK written | No `put_item` or `update_item` call targets a SK containing `#RPTJOB#` or `#RPT#...#META` |
| No Phase 5 SK written | No write targets a SK containing `#INTEL#` or `#INTJOB#` |
| No Phase 4 SK written | No write targets a SK containing `#AGG#`, `#AGGJOB#`, `#SET`, or `#MANIFEST#` |
| No `delete_item` calls | No delete path exists in `repository.py` |
| `ReportMetadata` GetItem is read-only | No `update_item` or `put_item` targeting the `ReportMetadata` SK |

---

#### Domain Unit Tests (one module per domain)

Each domain test module must cover PASS, FAIL, and BLOCKED conditions for all checks in the domain. The table below enumerates representative coverage per domain.

| Domain | Test File | Checks and Conditions Covered |
| --- | --- | --- |
| `RUNNER_HEALTH` | `test_runner_health.py` | RH-1 pass / fail (`total_executions=0`); RH-2 fail (endpoint `total_executions=0`); RH-3 fail (error rate exceeds threshold); RH-4 fail (`methodology_trace` null); BLOCKED (`endpoints[]` absent); all four checks pass |
| `EVIDENCE_COMPLETENESS` | `test_evidence_completeness.py` | EC-1 pass / fail (executions out of range); EC-2 fail (endpoint below minimum); EC-3 fail (required field null); EC-4 fail (`endpoint_count=0`); BLOCKED (`executive_summary` absent); all four checks pass |
| `EVIDENCE_INTEGRITY` | `test_evidence_integrity.py` | EI-1 fail (hash mismatch); EI-2 fail (`report_id` mismatch); EI-3 fail (`report_version` mismatch); EI-4 fail (`intelligence_version` mismatch); EI-5 fail (endpoint_count mismatch); BLOCKED (required field absent); all five checks pass |
| `EVIDENCE_LINEAGE` | `test_evidence_lineage.py` | EL-1 fail (`aggregate_set_hash` empty); EL-2 fail (hash mismatch); EL-3 fail (`intelligence_job_id` absent); EL-4 fail (required `input_lineage` field missing); EL-5 fail (invalid timestamp); BLOCKED (`intelligence_provenance` absent); all five checks pass |
| `OBSERVATION_COVERAGE` | `test_observation_coverage.py` | OC-1 fail (sub-section null); OC-2 fail (`endpoint_count` mismatch); OC-3 fail (`ReportMetadata.endpoint_count` mismatch); OC-4 fail (`audit_success_rate` out of range); OC-5 fail (`total_executions` inconsistent); BLOCKED (`endpoints[]` absent); all five checks pass |
| `SCHEDULER_INTEGRITY` | `test_scheduler_integrity.py` | SI-1 fail (`total_executions=0`); SI-2 fail (density variance exceeded); SI-3 fail (undisclosed scheduler anomaly in `methodology_disclosure`); BLOCKED (`methodology_disclosure` absent); all three checks pass (uniform density) |
| `METHODOLOGY_COMPLIANCE` | `test_methodology_compliance.py` | MC-1 fail (`methodology_disclosure` empty object); MC-2 fail (required disclosure field absent); MC-3 fail (`limitations` key absent); MC-4 fail (`methodology_trace` null on one endpoint sub-section); MC-5 fail (`score_derivation` null); BLOCKED (`methodology_disclosure` section absent); all five checks pass |
| `REPORT_INTEGRITY` | `test_report_integrity.py` | RI-1 fail (`report_version` wrong); RI-2 fail (`intelligence_version` wrong); RI-3 fail (`score_label` invalid); RI-4 fail (`composite_score_value` outside range); RI-5 fail (`endpoints[]` unsorted); RI-6 fail (duplicate `endpoint_id`); RI-7 fail (null `endpoint_id`); RI-8 fail (endpoint numeric score out of range); RI-9 fail (`score_label_description` invalid); BLOCKED (`identity` section absent); all nine checks pass |

Each domain test module must additionally assert:
- `DomainResult.domain` matches the expected domain identifier constant
- `DomainResult.checks_performed` matches the documented check count (RH=4, EC=4, EI=5, EL=5, OC=5, SI=3, MC=5, RI=9)
- `DomainResult.evidence_refs` matches the documented evidence refs list for the domain
- `DomainResult.failure_details` is an empty array for PASS and non-empty for FAIL or BLOCKED
- The domain module function has no DynamoDB write interface and no S3 write interface

---

### 9.3 Integration Test Coverage

#### `test_certification_pipeline_integration.py` (Localstack S3 + DynamoDB)

| Test Case | Description |
| --- | --- |
| Full pipeline: Phase 6 fixture → complete certification | `CertificationMetadata.terminal_state = CERTIFIED`; S3 certificate artifact exists and is valid |
| Certificate artifact deserializable | JSON deserializes back to `PlatformIntegrityCertificate` model without error |
| `terminal_state` on metadata matches artifact | DynamoDB `terminal_state` field matches S3 artifact value |
| `s3_certificate_ref` points to readable S3 object | Key navigable; certificate content structurally consistent |
| Force re-certification produces new artifact | New `certjob_id` in S3 key; original artifact preserved at original key |
| `ReportMetadata` unchanged after certification | All DynamoDB attributes byte-identical before/after Phase 7 invocation |
| Phase 6 S3 artifact unchanged after certification | S3 artifact bytes unchanged; ETag matches before/after |
| `CertificationJob` lifecycle transitions | `PENDING → IN_PROGRESS → COMPLETE` observable in DynamoDB |

---

#### `test_cli_certification_commands.py` (CLI command integration)

| Command | Test Case |
| --- | --- |
| `rcp certify audit` | Happy path; `CertificationMetadata.terminal_state = CERTIFIED` |
| `rcp certify audit` (gate fail) | Correct error message and exit code for `REPORT_NOT_COMPLETE` |
| `rcp certify audit` (idempotent, no `--force`) | `CERTIFICATION_ALREADY_CERTIFIED` message; no new job created |
| `rcp certify audit --force` | New certification event; new `certificate_id` in output |
| `rcp retrieve cert-status` | Displays `terminal_state`, `certificate_id`, `generated_at`, `report_id`; write count unchanged |
| `rcp retrieve cert-summary` | Displays terminal state, all eight domain statuses, `disclosed_failures`, provenance envelope |
| `rcp retrieve cert-domains` | All eight domains displayed with `checks_performed`, `checks_passed`, `failure_details`, `evidence_refs` |
| `rcp retrieve cert-json` | Full certificate JSON returned; parseable; provenance envelope present |
| Retrieval on absent `CertificationMetadata` | `CERTIFICATION_NOT_FOUND` error; no write operations |
| Provenance envelope on all retrieval commands | `certificate_version`, `certificate_id`, `report_id`, `report_version`, `generated_at` present in all four commands |

---

### 9.4 Retrieval CLI Scenarios (TR)

These scenarios are covered at the integration CLI test level in `test_cli_certification_commands.py`.

**TR-01: `cert-status` returns required fields with no write operations**

- Input: `CertificationMetadata` record with `terminal_state = CERTIFIED`
- Expected: `terminal_state`, `certificate_id`, `generated_at`, `report_id` all displayed; DynamoDB write count unchanged before and after command
- Acceptance criteria covered: AC-29

---

**TR-02: `cert-domains` returns full per-domain results with provenance envelope**

- Input: Existing `CERTIFIED` certificate S3 artifact with all eight domain results
- Expected: All eight domains displayed with `checks_performed`, `checks_passed`, `failure_details`, and `evidence_refs`; provenance envelope present at top of output
- Acceptance criteria covered: AC-30 (partial; full artifact retrieval)

---

**TR-03: `cert-summary` with `CERTIFICATION_FAILED` displays domain statuses and `disclosed_failures`**

- Input: `CertificationMetadata` with `terminal_state = CERTIFICATION_FAILED`; certificate S3 artifact with three failed domains from TN-11 fixture
- Expected: `CERTIFICATION_FAILED` terminal state displayed; three failed domain identifiers in `disclosed_failures`; all eight domain statuses visible; provenance envelope present
- Acceptance criteria covered: AC-32

---

**TR-04: `cert-json` returns full certificate JSON with provenance envelope**

- Input: Existing `CERTIFIED` certificate S3 artifact
- Expected: Full `PlatformIntegrityCertificate` JSON artifact output; parseable; all `cert_v1` fields present; provenance envelope present
- Acceptance criteria covered: AC-30

---

**TR-05: `CERTIFICATION_NOT_FOUND` on absent `CertificationMetadata`**

- Input: No `CertificationMetadata` record for the given identity tuple
- Expected: All four `cert-*` retrieval commands return structured error `CERTIFICATION_NOT_FOUND`; no DynamoDB or S3 write operations occur
- Acceptance criteria covered: AC-31

---

### 9.5 Phase 7.8 Validation Campaign

The Phase 7.8 Validation Campaign is a live end-to-end validation against Phase 6.8 report artifacts already persisted from the Phase 6.8 validation campaign.

**Campaign Objectives:**

1. Confirm `rcp certify audit` runs to completion against a real Phase 6 report artifact (`ReportMetadata.status = COMPLETE` in `dev` or `staging`).
2. Confirm the Platform Integrity Certificate JSON artifact is present and valid in S3 under the `integrity/` prefix.
3. Confirm all eight domain results are present with `status = PASSED`.
4. Confirm `terminal_state = CERTIFIED` in both the S3 artifact and the `CertificationMetadata` DynamoDB record.
5. Confirm all four `retrieve cert-*` commands return correct data with complete provenance envelopes.
6. Confirm force re-certification produces a new `certificate_id` at a new S3 key while preserving the original certificate artifact at its original key.
7. Confirm the Phase 6 `ReportMetadata` DynamoDB record is unchanged after Phase 7 certification.
8. Confirm failure injection against a mutated artifact fixture (from the fixture set in Section 8) produces `CERTIFICATION_FAILED` with correct `disclosed_failures` enumeration.

**Campaign Prerequisites:**

- Phase 6.8 validation artifacts must be accessible (`ReportMetadata.status = COMPLETE` in `dev` or `staging` stage)
- Platform S3 bucket and DynamoDB table accessible
- AWS credentials with write access to `integrity/` S3 prefix and `#CERTJOB#`/`#CERT#` DynamoDB namespaces

**Campaign Acceptance Criteria:**

All eight campaign objectives satisfied without error. Evidence recorded in the Phase 7.8 validation campaign document.

---

## 10. Exit Criteria

Phase 7 QA sign-off requires all of the following conditions to be met:

1. **`test_phase7_cert_schema.py` passes**: the `cert_v1` compatibility gate test confirms schema correctness, `CERTIFICATION_SUMMARY_MAP` bounded mapping, exactly eight domain results, and byte-identical JSON serialization for identical inputs.

2. **All eight domain unit test files pass**: `test_runner_health.py`, `test_evidence_completeness.py`, `test_evidence_integrity.py`, `test_evidence_lineage.py`, `test_observation_coverage.py`, `test_scheduler_integrity.py`, `test_methodology_compliance.py`, `test_report_integrity.py` — all PASS, FAIL, and BLOCKED conditions confirmed for each defined validation rule.

3. **`test_engine.py` passes**: prerequisite gate enforcement, idempotency gate behavior for all prior-state combinations, terminal state determination including `BLOCKED` precedence over `FAILED`, and `CertificationJob` lifecycle transitions confirmed.

4. **`test_repository.py` passes**: non-mutation invariant confirmed — no write path in `repository.py` targets Phase 6, Phase 5, or Phase 4 sort key namespaces; no delete operations exist.

5. **`test_publisher.py` passes**: all S3 write paths target `integrity/` prefix only; no write, delete, or copy operations target `reports/`, `intelligence/`, or `raw-results/` prefixes.

6. **`test_certification_pipeline_integration.py` passes**: full end-to-end certification pipeline confirmed with localstack, including non-mutation assertion on `ReportMetadata` DynamoDB record and Phase 6 S3 artifact.

7. **`test_cli_certification_commands.py` passes**: all five retrieval CLI scenarios (TR-01 through TR-05) and all certification execution CLI scenarios confirmed; provenance envelopes present on all retrieval commands.

8. **All positive scenarios pass**: TP-01 through TP-04.

9. **All negative scenarios pass**: TN-01 through TN-12.

10. **All boundary and edge cases pass**: TB-01 through TB-05.

11. **Phase 7.8 Validation Campaign completes**: all eight campaign objectives satisfied with evidence recorded in the campaign document.

12. **All 32 acceptance criteria covered**: AC-1 through AC-32 each covered by at least one passing test as confirmed by the coverage matrix in Section 7.

13. **No blocking defects remain open.**

---

## 11. Traceability

- Product Spec: `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Technical Design: `docs/architecture/phase_7_audit_platform_integrity_technical_design.md`
- Validation Spec: `docs/qa/phase_7_audit_platform_integrity_validation_spec.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 Test Plan (format reference): `docs/qa/phase_6_deterministic_reporting_test_plan.md`
- Compatibility gate test: `tests/unit/test_phase7_cert_schema.py`
- Non-mutation test: `tests/unit/audit_platform_integrity/test_repository.py`
- Product Constitution: `RCP_Product_Strategy.md`
