# Phase 6.8 Validation Campaign 03

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 03 |
| **Date** | *(to fill in)* |
| **Stage** | dev |
| **Purpose** | End-to-end Phase 6 report pipeline validation against the third Phase 4A.7 Campaign 3 audit |

## Pre-Flight Note — Audit Identification Required

The Phase 4A.7 Campaign 3 document acknowledged that the specific audit IDs for the third audit were not captured (§6.3 documentary gap). Before beginning this campaign:

1. Query DynamoDB to identify the third audit from Phase 4A.7 Campaign 3 that is not covered by Campaigns 01 and 02:
   ```bash
   rcp client list --stage dev
   rcp audit list --client-id <candidate_client_id> --stage dev
   ```
2. Confirm the audit has `lifecycle_state = COMPLETED` and `audit_window.duration_hours = 48`.
3. Confirm Phase 5 intelligence exists (`IntelligenceMetadata.status = COMPLETE`) or run `rcp generate intelligence` if not yet present.

## Target Audit

| Field | Value |
|---|---|
| `client_id` | *(to confirm via pre-flight)* |
| `audit_id` | *(to confirm via pre-flight)* |
| `audit_execution_id` | *(to confirm via pre-flight)* |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |

## Phase 5 Baseline

| Field | Value |
|---|---|
| `intelligence_job_id` | *(to record from pre-flight or Phase 5 generation)* |
| `composite_score` | *(to record)* |
| `score_label` | *(to record)* |
| `endpoint_count` | *(to record)* |
| `s3_artifact_ref` | *(to record)* |

---

## Phase 5 Pre-Flight (if intelligence not yet generated)

If `IntelligenceMetadata.status` is not COMPLETE for the third audit, run Phase 5 intelligence generation first:

```bash
rcp generate intelligence \
  --client <client_id> \
  --audit <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --stage dev \
  --output json
```

Record the result and confirm `status = COMPLETE` before proceeding.

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Command:**
```bash
rcp retrieve intelligence-status \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
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
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
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
| `composite_score` matches Phase 5 baseline | [ ] PASS / [ ] FAIL |
| `score_label` matches Phase 5 baseline | [ ] PASS / [ ] FAIL |
| `endpoint_count` matches Phase 5 baseline | [ ] PASS / [ ] FAIL |
| `report_job_id` has prefix `rptjob_` | [ ] PASS / [ ] FAIL |
| `report_id` has prefix `report_` | [ ] PASS / [ ] FAIL |

---

## Step 3 — DynamoDB State Verification

**Command:**
```bash
rcp retrieve report-status \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
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
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 --aggregation-version agg_v1 --intelligence-version intel_v1 \
  --report-version report_v1 --stage dev
```

**Result:** *(paste full JSON or key excerpts)*

### Phase 5 → Phase 6 Fidelity Checks

| Section | Field | Expected | Actual | Result |
|---|---|---|---|---|
| `intelligence_provenance` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `intelligence_job_id` | *(Phase 5 baseline value)* | | [ ] PASS / [ ] FAIL |
| `intelligence_provenance` | `audit_id` | *(target audit_id)* | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `composite_score_value` | *(Phase 5 baseline)* | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label` | *(Phase 5 baseline)* | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `endpoint_count` | *(Phase 5 baseline)* | | [ ] PASS / [ ] FAIL |
| `executive_summary` | `score_label_description` | non-empty string | | [ ] PASS / [ ] FAIL |
| `composite_score` | `value` | *(Phase 5 baseline)* | | [ ] PASS / [ ] FAIL |
| `endpoints` | count | *(Phase 5 endpoint_count)* | | [ ] PASS / [ ] FAIL |
| `input_lineage` | `aggregate_set_hash` | *(Phase 5 baseline hash)* | | [ ] PASS / [ ] FAIL |
| `methodology_disclosure` | `intelligence_version` | `intel_v1` | | [ ] PASS / [ ] FAIL |
| `identity` | `report_version` | `report_v1` | | [ ] PASS / [ ] FAIL |

**No-mutation check:**

| Check | Result |
|---|---|
| Phase 5 `intelligence_job_id` unchanged | [ ] PASS / [ ] FAIL |
| Phase 5 `composite_score` unchanged | [ ] PASS / [ ] FAIL |

---

## Steps 5–12

*(Follow identical procedure as Campaign 01, substituting Campaign 03 identifiers.)*

### Step 5 — Executive Summary CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| `Score Label` matches Phase 5 | [ ] PASS / [ ] FAIL |
| `Composite Score` matches Phase 5 | [ ] PASS / [ ] FAIL |
| `Endpoint Count` matches Phase 5 | [ ] PASS / [ ] FAIL |

### Step 6 — Per-Endpoint CLI

**Result:**
```
(paste output here)
```

| Check | Result |
|---|---|
| Provenance envelope present | [ ] PASS / [ ] FAIL |
| All endpoints present | [ ] PASS / [ ] FAIL |
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
| `Aggregation Job ID` present | [ ] PASS / [ ] FAIL |
| `Source Raw Result Count` matches Phase 5 | [ ] PASS / [ ] FAIL |

### Step 9 — Markdown Report

**Result:** *(paste first 20 lines and section headings)*

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [ ] PASS / [ ] FAIL |
| All 8 section headings present | [ ] PASS / [ ] FAIL |
| All endpoint IDs in output | [ ] PASS / [ ] FAIL |
| Score label and value correct | [ ] PASS / [ ] FAIL |

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
| `composite_score` identical across runs | [ ] PASS / [ ] FAIL |
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
| `composite_score` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `score_label` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `endpoint_count` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` begins with `reports/` | | [ ] PASS / [ ] FAIL |
| `aggregate_set_hash` matches Phase 5 | | [ ] PASS / [ ] FAIL |
| `s3_artifact_ref` is navigable | | [ ] PASS / [ ] FAIL |

---

## Campaign 03 Result

**Overall result:** [ ] PASS / [ ] FAIL

**Notes:**

*(any observations, deviations, or issues — including third audit identification findings)*

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 03
```
