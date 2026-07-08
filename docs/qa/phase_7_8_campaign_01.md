# Phase 7.8 Validation Campaign 01

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 7.8 Validation Campaign 01 — Happy Path (CERTIFIED) |
| **Date** | 2026-07-08 |
| **Stage** | dev |
| **Purpose** | Live certification of known-good Phase 6.8 report → `CERTIFIED` terminal state |
| **GitHub Issue** | #83 |

## Target Audit (Phase 6.8 Campaign 01)

| Field | Value |
|---|---|
| `client_id` | `client_lineage_issue_verification_1_a6eab2b8` |
| `audit_id` | `audit_20260626_6f433adc` |
| `audit_execution_id` | `audexec_b146ca56faa44b7581686a0f1d5e11c7` |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |
| `composite_score` | `1.000` |
| `score_label` | `HIGH_CONFIDENCE` |

---

## Pre-Campaign Finding: Phase 6 Consumer Contract Gap

Before Campaign 01 could succeed, a Phase 6 implementation gap was discovered:

**Finding:** The Phase 6 `ReportingEngine` did not include `aggregate_set_hash` in `ReportMetadata` DynamoDB writes on COMPLETE, despite this field being defined as a stable consumer contract field in `docs/architecture/phase_6_phase7_consumer_contract.md` Section 3.1.

**Impact:** Phase 7 `EVIDENCE_INTEGRITY` (EI-1) and `EVIDENCE_LINEAGE` (EL-2) domains require `aggregate_set_hash` from `ReportMetadata` for cross-record lineage verification. Without it, both domains returned `BLOCKED` (not `FAILED`) — producing `CERTIFICATION_BLOCKED` on what should be a clean certification.

**Fix applied (same branch):**
- `src/release_confidence_platform/deterministic_reporting/engine.py`: Added `"aggregate_set_hash": report.intelligence_provenance.aggregate_set_hash` to `meta_complete_updates` at Step 14 (COMPLETE transition).
- `tests/unit/deterministic_reporting/test_engine.py`: Added `test_report_metadata_complete_includes_aggregate_set_hash` regression test.
- Phase 6.8 Campaign 01 report re-generated with `--force` to update the existing `ReportMetadata` record.

**New `report_id` after force re-run:** `report_9c772956a98d44fd9337f454ad9571b2`
**New `report_job_id`:** `rptjob_46e5881af29b4e52845c6c157e2b80b8`
**S3 artifact:** `reports/.../rptjob_46e5881af29b4e52845c6c157e2b80b8/artifact.json`

The composite score, score_label, and endpoint_count are unchanged from the original Phase 6.8 Campaign 01 report.

---

## Step 1 — Pre-Flight: Phase 6 ReportMetadata Gate Verification

Verified `ReportMetadata.status = COMPLETE` and `aggregate_set_hash` populated after Phase 6 fix:

| Field | Value |
|---|---|
| `status` | `COMPLETE` |
| `aggregate_set_hash` | `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` |
| `composite_score` | `1.0` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `report_id` | `report_9c772956a98d44fd9337f454ad9571b2` |

| Check | Result |
|---|---|
| `status = COMPLETE` | [x] PASS |
| `aggregate_set_hash` present | [x] PASS |
| `s3_artifact_ref` present | [x] PASS |

---

## Step 2 — Campaign 01: `rcp certify audit`

**Command:**
```
rcp certify audit \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
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
  "terminal_state": "CERTIFIED",
  "certificate_id": "cert_dee446d63c70483a9dc1259090a1054e",
  "disclosed_failures": [],
  "s3_cert_ref": "integrity/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_680c6c9f2d2640028ecb5a25e5d4a1b3/artifact.json"
}
```

**Certification identity:**

| Field | Value |
|---|---|
| `certificate_id` | `cert_dee446d63c70483a9dc1259090a1054e` |
| `certjob_id` | `certjob_680c6c9f2d2640028ecb5a25e5d4a1b3` |
| `terminal_state` | `CERTIFIED` |
| `certification_summary` | `INTEGRITY_VERIFIED` |
| `disclosed_failures` | `[]` |

**Domain Results:**

| Domain | Status | Checks Performed | Checks Passed |
|---|---|---|---|
| `RUNNER_HEALTH` | PASSED | 4 | 4 |
| `EVIDENCE_COMPLETENESS` | PASSED | 4 | 4 |
| `EVIDENCE_INTEGRITY` | PASSED | 5 | 5 |
| `EVIDENCE_LINEAGE` | PASSED | 5 | 5 |
| `OBSERVATION_COVERAGE` | PASSED | 5 | 5 |
| `SCHEDULER_INTEGRITY` | PASSED | 3 | 3 |
| `METHODOLOGY_COMPLIANCE` | PASSED | 5 | 5 |
| `REPORT_INTEGRITY` | PASSED | 9 | 9 |

**Total:** 8 domains, 40 checks performed, 40 checks passed.

| Check | Result |
|---|---|
| `terminal_state = CERTIFIED` | [x] PASS |
| `disclosed_failures = []` | [x] PASS |
| All 8 domain identifiers present | [x] PASS |
| All 8 domains status `PASSED` | [x] PASS |
| `certjob_id` populated | [x] PASS |
| Certificate artifact written to S3 under `integrity/` prefix | [x] PASS |

---

## Step 3 — Idempotency Verification

Re-ran `rcp certify audit` (same identity, no `--force`):

**Result:** `CERTIFICATION_ALREADY_CERTIFIED`

```json
{
  "code": "CERTIFICATION_ALREADY_CERTIFIED",
  "message": "Audit already certified: certificate_id='cert_dee446d63c70483a9dc1259090a1054e', s3_certificate_ref='...certjob_680c6c9f2d2640028ecb5a25e5d4a1b3/artifact.json'. Use --force to re-certify."
}
```

| Check | Result |
|---|---|
| `CERTIFICATION_ALREADY_CERTIFIED` returned | [x] PASS |
| Existing `certificate_id` returned | [x] PASS |
| No new `CertificationJob` written | [x] PASS |

---

## Step 4 — Retrieve Commands Verification

### `cert-status`

```
Certificate ID:      cert_dee446d63c70483a9dc1259090a1054e
Certificate Version: cert_v1
Terminal State:      CERTIFIED
Report ID:           report_9c772956a98d44fd9337f454ad9571b2
Generated At:        2026-07-08T15:35:36.689948Z
```

| Check | Result |
|---|---|
| `terminal_state` present | [x] PASS |
| `certificate_id` present | [x] PASS |
| `report_id` present | [x] PASS |
| `generated_at` present | [x] PASS |
| Provenance envelope present | [x] PASS |

### `cert-summary`

Full provenance envelope with all identity fields, `aggregate_set_hash`, `terminal_state = CERTIFIED`, `certjob_id`, `s3_cert_ref`, and `s3_report_artifact_ref` displayed correctly.

| Check | Result |
|---|---|
| All identity fields present | [x] PASS |
| `aggregate_set_hash` displayed | [x] PASS |
| `terminal_state = CERTIFIED` | [x] PASS |
| Provenance envelope present | [x] PASS |

### `cert-domains`

All 8 domains displayed with `checks_performed`, `checks_passed`, and `failure_details: (none)` for each.

| Check | Result |
|---|---|
| All 8 domains displayed | [x] PASS |
| Per-domain `checks_performed` / `checks_passed` correct | [x] PASS |
| `failure_details` empty for all domains | [x] PASS |
| Provenance envelope present | [x] PASS |

---

## Step 5 — Phase 6 Artifact Non-Mutation Verification

Verified the original Phase 6.8 Campaign 01 S3 artifact (`rptjob_46e5881af29b4e52845c6c157e2b80b8/artifact.json`) and `ReportMetadata` DynamoDB record are unchanged after Phase 7 certification:

| Check | Result |
|---|---|
| S3 artifact `intelligence_provenance.aggregate_set_hash` unchanged | [x] PASS — `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` |
| S3 artifact `input_lineage.aggregate_set_hash` unchanged | [x] PASS — same value |
| `ReportMetadata.status` unchanged | [x] PASS — `COMPLETE` |
| `ReportMetadata.aggregate_set_hash` unchanged | [x] PASS — same value |
| `ReportMetadata.audit_id` unchanged | [x] PASS — `audit_20260626_6f433adc` |

---

## Acceptance Criteria Coverage

| Acceptance Criterion | Result |
|---|---|
| Campaign 01: `CERTIFIED` terminal state on known-good Phase 6.8 report | [x] PASS |
| All 8 domain identifiers present in `domain_results[]` | [x] PASS |
| `disclosed_failures = []` on `CERTIFIED` output | [x] PASS |
| Idempotency: re-run without `--force` returns existing certificate | [x] PASS |
| Phase 6 artifact non-mutation verified | [x] PASS |
| Unit test suite: 0 failures at campaign time | [x] PASS (1399 tests) |
