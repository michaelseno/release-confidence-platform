# Phase 6.8 Validation Campaign 02

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 02 |
| **Date** | *(to fill in)* |
| **Stage** | dev |
| **Purpose** | End-to-end Phase 6 report pipeline validation against Audit 2 (composite_score = 0.940, score differentiation case) |

## Target Audit

| Field | Value |
|---|---|
| `client_id` | `client_lineage_issue_verification_2_1b5e3d6e` |
| `audit_id` | `audit_20260626_c3927ce1` |
| `audit_execution_id` | `audexec_00294bb91dc74d499e46c9788718b86a` |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |

## Phase 5 Baseline (from Phase 5.8 Campaign 02)

| Field | Value |
|---|---|
| `intelligence_job_id` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` |
| `composite_score` | `0.940` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `intelligence/client_lineage_issue_verification_2_1b5e3d6e/audit_20260626_c3927ce1/audexec_00294bb91dc74d499e46c9788718b86a/agg_v1/intel_v1/intjob_ab4e177fcf0e40288e30a9d1a3bbb992/artifact.json` |

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Command:**
```bash
rcp retrieve intelligence-status \
  --client-id client_lineage_issue_verification_2_1b5e3d6e \
  --audit-id audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| `status = COMPLETE` | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` present | [ ] PASS / [ ] FAIL |

---

## Step 2 — Generate Report (Initial)

**Command:**
```bash
rcp generate report \
  --client-id client_lineage_issue_verification_2_1b5e3d6e \
  --audit-id audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev \
  --output json
```

**Result:**
```json
(paste output here)
```

| Field | Value Recorded |
|---|---|
| `status` | |
| `report_job_id` | |
| `report_id` | |
| `composite_score` | |
| `score_label` | |
| `endpoint_count` | |
| `s3_artifact_ref` | |

| Check | Result |
|---|---|
| `status = COMPLETE` | [ ] PASS / [ ] FAIL |
| `composite_score = 0.940` | [ ] PASS / [ ] FAIL |
| `score_label = HIGH_CONFIDENCE` | [ ] PASS / [ ] FAIL |
| `endpoint_count = 5` | [ ] PASS / [ ] FAIL |
| `report_job_id` has prefix `rptjob_` | [ ] PASS / [ ] FAIL |
| `report_id` has prefix `report_` | [ ] PASS / [ ] FAIL |

---

## Step 3 — DynamoDB State Verification

**Command:**
```bash
rcp retrieve report-status \
  --client-id client_lineage_issue_verification_2_1b5e3d6e \
  --audit-id audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| `Status: COMPLETE` | [ ] PASS / [ ] FAIL |
| `Report Job ID` matches Step 2 | [ ] PASS / [ ] FAIL |
| `Report ID` matches Step 2 | [ ] PASS / [ ] FAIL |
| Provenance envelope present | [ ] PASS / [ ] FAIL |

---

## Step 4 — JSON Artifact Fidelity Check

**Command:**
```bash
rcp retrieve report-json \
  --client-id client_lineage_issue_verification_2_1b5e3d6e \
  --audit-id audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:** *(paste full JSON or key excerpts)*

### Phase 5 → Phase 6 Fidelity Checks

| Section | Field | Expected | Actual | Result |
|---|---|---|---|---|
| `intelligence_provenance` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `intelligence_job_id` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `audit_id` | `audit_20260626_c3927ce1` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `composite_score_value` | `0.94` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label` | `HIGH_CONFIDENCE` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `endpoint_count` | `5` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label_description` | non-empty string | | [ ] PASS / [ ] FAIL |
| `composite_score` | `value` | `0.94` | | [ ] PASS / [ ] FAIL |
| `audit_reliability_overview` | `endpoint_count` | `5` | | [ ] PASS / [ ] FAIL |
| `endpoints` | count | `5` | | [ ] PASS / [ ] FAIL |
| `input_lineage` | `aggregate_set_hash` | `7bafd96232b0825cc7e0e6a4c0b843e9ecf079e82b1007e7efc87694dd4cf4fc` | | [ ] PASS / [ ] FAIL |
| `input_lineage` | `source_raw_result_count` | `960` | | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `identity` | `report_version` | `report_v1` | | [ ] PASS / [ ] FAIL |

**No-mutation check:**

| Check | Result |
|---|---|
| Phase 5 `intelligence_job_id` unchanged | [ ] PASS / [ ] FAIL |
| Phase 5 `composite_score` unchanged | [ ] PASS / [ ] FAIL |

---

## Steps 5–12

*(Follow identical procedure as Campaign 01, substituting Campaign 02 identifiers. Record all CLI outputs and check results below.)*

### Step 5 — Executive Summary CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Score Label: HIGH_CONFIDENCE` | [ ] PASS / [ ] FAIL |
| `Composite Score: 0.940` | [ ] PASS / [ ] FAIL |
| `Endpoint Count: 5` | [ ] PASS / [ ] FAIL |

### Step 6 — Per-Endpoint CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| All 5 endpoints present | [ ] PASS / [ ] FAIL |
| Score columns populated | [ ] PASS / [ ] FAIL |

### Step 7 — Methodology CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Intelligence Version: intel_v1` | [ ] PASS / [ ] FAIL |
| Limitations list present | [ ] PASS / [ ] FAIL |

### Step 8 — Evidence Lineage CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Aggregate Set Hash` matches Phase 5 | [ ] PASS / [ ] FAIL |
| `Source Raw Result Count: 960` | [ ] PASS / [ ] FAIL |

### Step 9 — Markdown Report

**Result:** *(paste first 20 lines and section headings)*

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [ ] PASS / [ ] FAIL |
| All 8 section headings present | [ ] PASS / [ ] FAIL |
| All 5 endpoint IDs in output | [ ] PASS / [ ] FAIL |
| `composite_score = 0.940` present | [ ] PASS / [ ] FAIL |

### Step 10 — PDF Report

| Field | Value |
|---|---|
| PDF file size (bytes) | |
| Magic bytes | |

| Check | Result |
|---|---|
| Non-empty file | [ ] PASS / [ ] FAIL |
| Begins with `%PDF-` | [ ] PASS / [ ] FAIL |
| Size in valid range | [ ] PASS / [ ] FAIL |

### Step 11 — Idempotency Check

**Result:**
```json
(paste output here)
```

| Check | Result |
|---|---|
| `status = ALREADY_COMPLETE` | [ ] PASS / [ ] FAIL |
| `report_job_id` unchanged | [ ] PASS / [ ] FAIL |

### Step 12 — Deterministic Regeneration

| Field | Run A | Run B |
|---|---|---|
| `report_job_id` | | |
| `composite_score` | | |
| `score_label` | | |
| `generation_count` | | |

| Check | Result |
|---|---|
| Both `status = COMPLETE` | [ ] PASS / [ ] FAIL |
| `report_job_id` differs between runs | [ ] PASS / [ ] FAIL |
| `composite_score` identical (`0.940`) | [ ] PASS / [ ] FAIL |
| `generation_count` incremented correctly | [ ] PASS / [ ] FAIL |
| Key report sections byte-identical across artifacts | [ ] PASS / [ ] FAIL |

---

## Step 13 — Phase 5 → Phase 6 Consumer Contract

| Invariant | Result |
|---|---|
| Phase 5 prerequisite gate enforced | [ ] PASS / [ ] FAIL |
| No new Phase 5 DynamoDB records post-campaign | [ ] PASS / [ ] FAIL |
| `composite_score` unchanged from Phase 5 baseline | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` verbatim pass-through | [ ] PASS / [ ] FAIL |
| `input_lineage` verbatim pass-through | [ ] PASS / [ ] FAIL |
| `score_label_description` absent from Phase 5 artifact | [ ] PASS / [ ] FAIL |

---

## Step 14 — Phase 6 → Phase 7 Consumer Contract

| Field | Value | Result |
|---|---|---|
| `status = COMPLETE` | | [ ] PASS / [ ] FAIL |
| `report_version = report_v1` | | [ ] PASS / [ ] FAIL |
| `report_id` with `report_` prefix | | [ ] PASS / [ ] FAIL |
| `report_job_id` with `rptjob_` prefix | | [ ] PASS / [ ] FAIL |
| `composite_score = 0.940` | | [ ] PASS / [ ] FAIL |
| `score_label = HIGH_CONFIDENCE` | | [ ] PASS / [ ] FAIL |
| `endpoint_count = 5` | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` begins with `reports/` | | [ ] PASS / [ ] FAIL |
| `aggregate_set_hash` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` is navigable | | [ ] PASS / [ ] FAIL |

---

## Campaign 02 Result

**Overall result:** [ ] PASS / [ ] FAIL

**Notes:**

*(any observations, deviations, or issues)*

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 02
```
