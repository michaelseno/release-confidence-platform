# Phase 7.8 Validation Campaign 02

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 7.8 Validation Campaign 02 — Failure Injection (CERTIFICATION_FAILED) |
| **Date** | 2026-07-08 |
| **Stage** | dev |
| **Purpose** | Controlled failure injection → `CERTIFICATION_FAILED` with `disclosed_failures` non-empty |
| **GitHub Issue** | #83 |

## Failure Injection Strategy

Per Risk R6 in `docs/release/phase_7_release_planning.md`, Campaign 02 uses a test copy of a Phase 6.8 artifact with a targeted mutation to produce `CERTIFICATION_FAILED`. The original Phase 6.8 artifacts are not modified.

**Injection method:** `aggregate_set_hash` tampered in the S3 artifact only. The `ReportMetadata` DynamoDB record retains the original correct hash. This produces a cross-record mismatch:
- Triggers `EVIDENCE_LINEAGE` EL-2: lineage hash mismatch between artifact and `ReportMetadata`
- Triggers `EVIDENCE_INTEGRITY` EI-1: `intelligence_provenance.aggregate_set_hash` mismatch

**Source artifact:** Phase 6.8 Campaign 01 report artifact (composite_score = 1.000, HIGH_CONFIDENCE)
**Mutation applied:** `intelligence_provenance.aggregate_set_hash` and `input_lineage.aggregate_set_hash` replaced with `p78c02_tampered_hash_for_failure_injection_phase78_campaign02`
**Original artifact:** Untouched. Only a copy at the test-specific path is mutated.

## Test Identity

| Field | Value |
|---|---|
| `client_id` | `client_lineage_issue_verification_1_a6eab2b8` |
| `audit_id` | `audit_p78c02_failure_injection` (test-only) |
| `audit_execution_id` | `audexec_b146ca56faa44b7581686a0f1d5e11c7` |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |

## Test Artifacts Written

| Artifact | Location | Notes |
|---|---|---|
| Mutated S3 artifact | `reports/.../audit_p78c02_failure_injection/.../rptjob_p78c02_failure_injection_test/artifact.json` | Test copy; `aggregate_set_hash` tampered |
| Fake `ReportMetadata` | DynamoDB SK `AUDIT#audit_p78c02_failure_injection#...#META` | `aggregate_set_hash` = original (correct) hash; `status = COMPLETE` |

Both records are tagged with `campaign_note: "Phase 7.8 Campaign 02 failure injection test record — EVIDENCE_LINEAGE EL-2"`.

---

## Step 1 — Campaign 02: `rcp certify audit`

**Command:**
```
rcp certify audit \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_p78c02_failure_injection \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --stage dev \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --output json
```

**Result:**
```json
{
  "terminal_state": "CERTIFICATION_FAILED",
  "certificate_id": "cert_0b6888ab5ad94f4980fbb894dc6513d9",
  "disclosed_failures": ["EVIDENCE_INTEGRITY", "EVIDENCE_LINEAGE"],
  "s3_cert_ref": "integrity/.../audit_p78c02_failure_injection/.../certjob_1008bcb7e3c7436f87cc6e9ee7ae592b/artifact.json"
}
```

**Certification identity:**

| Field | Value |
|---|---|
| `certificate_id` | `cert_0b6888ab5ad94f4980fbb894dc6513d9` |
| `certjob_id` | `certjob_1008bcb7e3c7436f87cc6e9ee7ae592b` |
| `terminal_state` | `CERTIFICATION_FAILED` |
| `certification_summary` | `INTEGRITY_FAILED` |
| `disclosed_failures` | `["EVIDENCE_INTEGRITY", "EVIDENCE_LINEAGE"]` |

**Domain Results:**

| Domain | Status | Checks Performed | Checks Passed | Failure Details |
|---|---|---|---|---|
| `RUNNER_HEALTH` | PASSED | 4 | 4 | — |
| `EVIDENCE_COMPLETENESS` | PASSED | 4 | 4 | — |
| `EVIDENCE_INTEGRITY` | FAILED | 5 | 3 | EI-1: aggregate_set_hash mismatch (artifact vs ReportMetadata); EI-2: report_id mismatch |
| `EVIDENCE_LINEAGE` | FAILED | 5 | 4 | EL-2: lineage hash mismatch (artifact vs ReportMetadata) |
| `OBSERVATION_COVERAGE` | PASSED | 5 | 5 | — |
| `SCHEDULER_INTEGRITY` | PASSED | 3 | 3 | — |
| `METHODOLOGY_COMPLIANCE` | PASSED | 5 | 5 | — |
| `REPORT_INTEGRITY` | PASSED | 9 | 9 | — |

**EVIDENCE_INTEGRITY failure details:**
- `EI-1: intelligence_provenance.aggregate_set_hash mismatch: artifact='p78c02_tampered_hash_for_failure_injection_phase78_campaign02', ReportMetadata='e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee'`
- `EI-2: identity.report_id mismatch: artifact='report_9c772956a98d44fd9337f454ad9571b2', ReportMetadata='report_p78c02_failure_injection_test'`

**EVIDENCE_LINEAGE failure details:**
- `EL-2: lineage hash mismatch: intelligence_provenance.aggregate_set_hash='p78c02_tampered_hash_for_failure_injection_phase78_campaign02', ReportMetadata.aggregate_set_hash='e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee'`

| Check | Result |
|---|---|
| `terminal_state = CERTIFICATION_FAILED` | [x] PASS |
| `disclosed_failures` non-empty | [x] PASS |
| `EVIDENCE_INTEGRITY` in `disclosed_failures` | [x] PASS |
| `EVIDENCE_LINEAGE` in `disclosed_failures` | [x] PASS |
| All 8 domain identifiers present in `domain_results[]` | [x] PASS |
| `failure_details` non-empty for failed domains | [x] PASS |
| Certificate artifact written to S3 under `integrity/` prefix | [x] PASS |

---

## Step 2 — Phase 6 Artifact Non-Mutation Verification

Verified the original Phase 6.8 Campaign 01 S3 artifact and `ReportMetadata` record are unchanged after Campaign 02 certification:

| Check | Result |
|---|---|
| Original S3 artifact `intelligence_provenance.aggregate_set_hash` unchanged | [x] PASS — `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` |
| Original S3 artifact `input_lineage.aggregate_set_hash` unchanged | [x] PASS — same value |
| Original `ReportMetadata.status` unchanged | [x] PASS — `COMPLETE` |
| Original `ReportMetadata.aggregate_set_hash` unchanged | [x] PASS — same value |
| Original `ReportMetadata.audit_id` unchanged | [x] PASS — `audit_20260626_6f433adc` |
| Campaign 02 test artifact written to new key only | [x] PASS — `audit_p78c02_failure_injection` path |

---

## Acceptance Criteria Coverage

| Acceptance Criterion | Result |
|---|---|
| Campaign 02: `CERTIFICATION_FAILED` on controlled failure injection | [x] PASS |
| `disclosed_failures` non-empty | [x] PASS |
| All 8 domain identifiers present in `domain_results[]` | [x] PASS |
| Phase 6 artifact non-mutation verified across all campaigns | [x] PASS |
