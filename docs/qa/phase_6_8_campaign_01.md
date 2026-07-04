# Phase 6.8 Validation Campaign 01

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 01 |
| **Date** | *(to fill in)* |
| **Stage** | dev |
| **Purpose** | End-to-end Phase 6 report pipeline validation against Audit 1 (composite_score = 1.000) |

## Target Audit

| Field | Value |
|---|---|
| `client_id` | `client_lineage_issue_verification_1_a6eab2b8` |
| `audit_id` | `audit_20260626_6f433adc` |
| `audit_execution_id` | `audexec_b146ca56faa44b7581686a0f1d5e11c7` |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |

## Phase 5 Baseline (from Phase 5.8 Campaign 01)

| Field | Value |
|---|---|
| `intelligence_job_id` | `intjob_1356942a5393419a86a6b277a828d802` |
| `composite_score` | `1.000` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `intelligence/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/agg_v1/intel_v1/intjob_1356942a5393419a86a6b277a828d802/artifact.json` |

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Command:**
```bash
rcp retrieve intelligence-status \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
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
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
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
| `composite_score = 1.000` | [ ] PASS / [ ] FAIL |
| `score_label = HIGH_CONFIDENCE` | [ ] PASS / [ ] FAIL |
| `endpoint_count = 5` | [ ] PASS / [ ] FAIL |
| `report_job_id` has prefix `rptjob_` | [ ] PASS / [ ] FAIL |
| `report_id` has prefix `report_` | [ ] PASS / [ ] FAIL |

---

## Step 3 — DynamoDB State Verification

**Command:**
```bash
rcp retrieve report-status \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
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
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Result:** *(paste full JSON or key excerpts)*

### Phase 5 → Phase 6 Fidelity Checks

| Section | Field | Expected | Actual | Result |
|---|---|---|---|---|
| `intelligence_provenance` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `intelligence_job_id` | `intjob_1356942a5393419a86a6b277a828d802` | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `audit_id` | `audit_20260626_6f433adc` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `composite_score_value` | `1.0` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label` | `HIGH_CONFIDENCE` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `endpoint_count` | `5` | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label_description` | non-empty string | | [ ] PASS / [ ] FAIL |
| `composite_score` | `value` | `1.0` | | [ ] PASS / [ ] FAIL |
| `audit_reliability_overview` | `endpoint_count` | `5` | | [ ] PASS / [ ] FAIL |
| `endpoints` | count | `5` | | [ ] PASS / [ ] FAIL |
| `input_lineage` | `aggregate_set_hash` | `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` | | [ ] PASS / [ ] FAIL |
| `input_lineage` | `source_raw_result_count` | `955` | | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `identity` | `report_version` | `report_v1` | | [ ] PASS / [ ] FAIL |

**No-mutation check:** Phase 5 artifact at original S3 key is unchanged.

| Check | Result |
|---|---|
| Phase 5 `intelligence_job_id` unchanged | [ ] PASS / [ ] FAIL |
| Phase 5 `composite_score` unchanged | [ ] PASS / [ ] FAIL |

---

## Step 5 — Executive Summary CLI

**Command:**
```bash
rcp retrieve report-summary \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Score Label: HIGH_CONFIDENCE` | [ ] PASS / [ ] FAIL |
| `Composite Score: 1.000` | [ ] PASS / [ ] FAIL |
| `Endpoint Count: 5` | [ ] PASS / [ ] FAIL |
| `Score Label Description` non-empty | [ ] PASS / [ ] FAIL |

---

## Step 6 — Per-Endpoint CLI

**Command:**
```bash
rcp retrieve report-endpoints \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| All 5 endpoints present | [ ] PASS / [ ] FAIL |
| Score columns populated | [ ] PASS / [ ] FAIL |

---

## Step 7 — Methodology CLI

**Command:**
```bash
rcp retrieve report-methodology \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Intelligence Version: intel_v1` | [ ] PASS / [ ] FAIL |
| Limitations list present | [ ] PASS / [ ] FAIL |
| JSON blocks present | [ ] PASS / [ ] FAIL |

---

## Step 8 — Evidence Lineage CLI

**Command:**
```bash
rcp retrieve report-lineage \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Aggregate Set Hash` matches Phase 5 | [ ] PASS / [ ] FAIL |
| `Aggregation Job ID` present | [ ] PASS / [ ] FAIL |
| `Source Raw Result Count: 955` | [ ] PASS / [ ] FAIL |

---

## Step 9 — Markdown Report

**Command:**
```bash
rcp retrieve report-markdown \
  --client-id client_lineage_issue_verification_1_a6eab2b8 \
  --audit-id audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:** *(paste first 20 lines and section headings)*

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [ ] PASS / [ ] FAIL |
| `## Executive Summary` present | [ ] PASS / [ ] FAIL |
| `## Release Confidence Score` present | [ ] PASS / [ ] FAIL |
| `## Audit Reliability Overview` present | [ ] PASS / [ ] FAIL |
| `## Per-Endpoint Analysis` present | [ ] PASS / [ ] FAIL |
| `## Methodology Disclosure` present | [ ] PASS / [ ] FAIL |
| `## Evidence Lineage` present | [ ] PASS / [ ] FAIL |
| `## Report Provenance` present | [ ] PASS / [ ] FAIL |
| All 5 endpoint IDs in output | [ ] PASS / [ ] FAIL |
| Score label and value correct | [ ] PASS / [ ] FAIL |

---

## Step 10 — PDF Report

**Script:**
```python
import json, boto3
from release_confidence_platform.deterministic_reporting.formatters.pdf import PdfFormatter
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport

s3 = boto3.client("s3", region_name="us-east-1")
# Replace <config_bucket> and <s3_artifact_ref> with actual values from Step 2
artifact = json.loads(s3.get_object(Bucket="<config_bucket>", Key="<s3_artifact_ref>")["Body"].read())
report = ReleaseConfidenceReport.model_validate(artifact)
pdf_bytes = PdfFormatter().render(report)
with open("report_campaign_01.pdf", "wb") as f:
    f.write(pdf_bytes)
print(f"PDF size: {len(pdf_bytes)} bytes")
print(f"Magic bytes: {pdf_bytes[:5]}")
```

| Field | Value |
|---|---|
| PDF file size (bytes) | |
| Magic bytes | |

| Check | Result |
|---|---|
| Non-empty file | [ ] PASS / [ ] FAIL |
| Begins with `%PDF-` | [ ] PASS / [ ] FAIL |
| Size in valid range (100B – 10MB) | [ ] PASS / [ ] FAIL |
| PDF opens and is readable | [ ] PASS / [ ] FAIL |

---

## Step 11 — Idempotency Check

**Command:** Same as Step 2 (no `--force`)

**Result:**
```json
(paste output here)
```

| Check | Result |
|---|---|
| `status = ALREADY_COMPLETE` | [ ] PASS / [ ] FAIL |
| `report_job_id` unchanged from Step 2 | [ ] PASS / [ ] FAIL |

---

## Step 12 — Deterministic Regeneration

**Run A** (`--force`):
```
(paste output — record report_job_id_A)
```

**Run B** (`--force`):
```
(paste output — record report_job_id_B)
```

| Field | Run A | Run B |
|---|---|---|
| `report_job_id` | | |
| `composite_score` | | |
| `score_label` | | |
| `endpoint_count` | | |
| `generation_count` | | |

| Check | Result |
|---|---|
| Both `status = COMPLETE` | [ ] PASS / [ ] FAIL |
| `report_job_id` differs between runs | [ ] PASS / [ ] FAIL |
| `composite_score` identical | [ ] PASS / [ ] FAIL |
| `score_label` identical | [ ] PASS / [ ] FAIL |
| `generation_count` incremented correctly (3 after Run B) | [ ] PASS / [ ] FAIL |
| `executive_summary` byte-identical across both artifacts | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` byte-identical | [ ] PASS / [ ] FAIL |
| `input_lineage` byte-identical | [ ] PASS / [ ] FAIL |

---

## Step 13 — Phase 5 → Phase 6 Consumer Contract

| Invariant | Result |
|---|---|
| Phase 5 prerequisite gate enforced before any Phase 6 DynamoDB write | [ ] PASS / [ ] FAIL |
| No new Phase 5 DynamoDB records after campaign (same `intelligence_job_id`) | [ ] PASS / [ ] FAIL |
| `composite_score` unchanged from Phase 5 baseline | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` verbatim pass-through | [ ] PASS / [ ] FAIL |
| `input_lineage` verbatim pass-through | [ ] PASS / [ ] FAIL |
| `score_label_description` absent from Phase 5 artifact (Phase 6-only field) | [ ] PASS / [ ] FAIL |

---

## Step 14 — Phase 6 → Phase 7 Consumer Contract

| Field | Value | Result |
|---|---|---|
| `status = COMPLETE` | | [ ] PASS / [ ] FAIL |
| `report_version = report_v1` | | [ ] PASS / [ ] FAIL |
| `report_id` present with `report_` prefix | | [ ] PASS / [ ] FAIL |
| `report_job_id` present with `rptjob_` prefix | | [ ] PASS / [ ] FAIL |
| `composite_score` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `score_label` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `endpoint_count = 5` | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` begins with `reports/` | | [ ] PASS / [ ] FAIL |
| `aggregate_set_hash` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` is navigable (artifact readable) | | [ ] PASS / [ ] FAIL |

---

## Campaign 01 Result

**Overall result:** [ ] PASS / [ ] FAIL

**Notes:**

*(any observations, deviations, or issues)*

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 01
```
