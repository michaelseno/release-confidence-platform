# Phase 6.8 Validation Campaign 01

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 01 |
| **Date** | 2026-07-04 |
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

## Phase 5 Baseline (Live — from C0.4)

| Field | Value |
|---|---|
| `intelligence_job_id` | `intjob_243ebb6a7e444e4bb46e3ae47a907161` |
| `composite_score` | `1.000` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `intelligence/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/agg_v1/intel_v1/intjob_243ebb6a7e444e4bb46e3ae47a907161/artifact.json` |

> **Note:** `intelligence_job_id` differs from the Phase 5.8 Campaign 01 documentation value (`intjob_1356942a5393419a86a6b277a828d802`). Live query confirms a force-regeneration occurred between Phase 5.8 documentation and this campaign. Scores are unchanged: `1.000 / HIGH_CONFIDENCE / 5 endpoints`.

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Result:**
```
status: COMPLETE
composite_score: 1.000
intelligence_job_id: intjob_243ebb6a7e444e4bb46e3ae47a907161
score_label: HIGH_CONFIDENCE
endpoint_count: 5
```

| Check | Result |
|---|---|
| `status = COMPLETE` | [x] PASS |
| `s3_artifact_ref` present | [x] PASS |

---

## Step 2 — Generate Report (Initial)

**Result:**
```json
{"status": "COMPLETE", "composite_score": "1.0", "score_label": "HIGH_CONFIDENCE",
 "endpoint_count": 5, "report_id": "report_bf0df63ec1334bf29948cb1a0cca97e1",
 "report_job_id": "rptjob_4508490641de485199084c644a7b80d6", "report_version": "report_v1",
 "s3_artifact_ref": "reports/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/agg_v1/intel_v1/report_v1/rptjob_4508490641de485199084c644a7b80d6/artifact.json"}
```

| Field | Value Recorded |
|---|---|
| `status` | `COMPLETE` |
| `report_job_id` | `rptjob_4508490641de485199084c644a7b80d6` |
| `report_id` | `report_bf0df63ec1334bf29948cb1a0cca97e1` |
| `composite_score` | `1.0` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `reports/.../rptjob_4508490641de485199084c644a7b80d6/artifact.json` |

| Check | Result |
|---|---|
| `status = COMPLETE` | [x] PASS |
| `composite_score = 1.000` | [x] PASS |
| `score_label = HIGH_CONFIDENCE` | [x] PASS |
| `endpoint_count = 5` | [x] PASS |
| `report_job_id` has prefix `rptjob_` | [x] PASS |
| `report_id` has prefix `report_` | [x] PASS |

---

## Step 3 — DynamoDB State Verification

**Result:**
```
Report ID:             report_bf0df63ec1334bf29948cb1a0cca97e1
Report Version:        report_v1
Intelligence Version:  intel_v1
Audit ID:              audit_20260626_6f433adc
Generated At:          2026-07-04T11:33:13.863137Z

Status:        COMPLETE
Score Label:   HIGH_CONFIDENCE
Report Job ID: rptjob_4508490641de485199084c644a7b80d6
Report ID:     report_bf0df63ec1334bf29948cb1a0cca97e1
Completed At:  2026-07-04T11:33:13.863137Z
```

| Check | Result |
|---|---|
| `Status: COMPLETE` | [x] PASS |
| `Report Job ID` matches Step 2 | [x] PASS |
| `Report ID` matches Step 2 | [x] PASS |
| Provenance envelope present | [x] PASS |

---

## Step 4 — JSON Artifact Fidelity Check

### Phase 5 → Phase 6 Fidelity Checks

| Section | Field | Expected | Actual | Result |
|---|---|---|---|---|
| `intelligence_provenance` | `intelligence_version` | `intel_v1` | `intel_v1` | [x] PASS |
| `intelligence_provenance` | `intelligence_job_id` | `intjob_243ebb6a7e444e4bb46e3ae47a907161` | `intjob_243ebb6a7e444e4bb46e3ae47a907161` | [x] PASS |
| `intelligence_provenance` | `audit_id` | `audit_20260626_6f433adc` | `audit_20260626_6f433adc` | [x] PASS |
| `executive_summary` | `composite_score_value` | `1.0` | `1.0` | [x] PASS |
| `executive_summary` | `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` | [x] PASS |
| `executive_summary` | `endpoint_count` | `5` | `5` | [x] PASS |
| `executive_summary` | `score_label_description` | non-empty string | present | [x] PASS |
| `composite_score` | `value` | `1.0` | `1.0` | [x] PASS |
| `audit_reliability_overview` | `endpoint_count` | `5` | `5` | [x] PASS |
| `endpoints` | count | `5` | `5` | [x] PASS |
| `input_lineage` | `aggregate_set_hash` | `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` | matches | [x] PASS |
| `input_lineage` | `source_raw_result_count` | `955` | `955` | [x] PASS |
| `methodology_disclosure` | `intelligence_version` | `intel_v1` | `intel_v1` | [x] PASS |
| `identity` | `report_version` | `report_v1` | `report_v1` | [x] PASS |

**No-mutation check:** Phase 5 artifact read from S3 — `intelligence_job_id` and `composite_score.value` match live Phase 5 DynamoDB record.

| Check | Result |
|---|---|
| Phase 5 `intelligence_job_id` unchanged | [x] PASS |
| Phase 5 `composite_score` unchanged | [x] PASS |

---

## Step 5 — Executive Summary CLI

**Result:**
```
Report ID:             report_bf0df63ec1334bf29948cb1a0cca97e1
Report Version:        report_v1
Intelligence Version:  intel_v1
Audit ID:              audit_20260626_6f433adc
Generated At:          2026-07-04T11:33:13.183841Z

Score Label:              HIGH_CONFIDENCE
Composite Score:          1.000
Endpoint Count:           5
Audit Success Rate:       1.000
Total Executions:         955
Score Label Description:  Reliability indicators across all assessed endpoints are strong. The observed evidence does not indicate material reliability concerns for the audited release scope.
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Score Label: HIGH_CONFIDENCE` | [x] PASS |
| `Composite Score: 1.000` | [x] PASS |
| `Endpoint Count: 5` | [x] PASS |
| `Score Label Description` non-empty | [x] PASS |

---

## Step 6 — Per-Endpoint CLI

**Result:**
```
Endpoint ID                                 Composite  Reliability  Stability    Burst  Consistency
---------------------------------------------------------------------------------------------------
health_fast                                     1.000        1.000      1.000    1.000        1.000
health_flaky                                    1.000        1.000      1.000    1.000        1.000
health_inconsistent_variant_a                   1.000        1.000      1.000    1.000        1.000
health_inconsistent_variant_b                   1.000        1.000      1.000    1.000        1.000
health_slow                                     1.000        1.000      1.000    1.000        1.000
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| All 5 endpoints present | [x] PASS |
| Score columns populated | [x] PASS |

---

## Step 7 — Methodology CLI

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Intelligence Version: intel_v1` | [x] PASS |
| Limitations list present (5 items) | [x] PASS |
| JSON blocks present (Scoring, Stability, Burst, Consistency, Label mapping) | [x] PASS |

---

## Step 8 — Evidence Lineage CLI

**Result:**
```
Aggregate Set Hash:   e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee
Aggregation Job ID:   aggjob_8e905bd72a3c42a4a8beb02629501cbc
Source Raw Result Count: 955
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Aggregate Set Hash` matches Phase 5 | [x] PASS |
| `Aggregation Job ID` present | [x] PASS |
| `Source Raw Result Count: 955` | [x] PASS |

---

## Step 9 — Markdown Report

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [x] PASS |
| `## Executive Summary` present | [x] PASS |
| `## Release Confidence Score` present | [x] PASS |
| `## Audit Reliability Overview` present | [x] PASS |
| `## Per-Endpoint Analysis` present | [x] PASS |
| `## Methodology Disclosure` present | [x] PASS |
| `## Evidence Lineage` present | [x] PASS |
| `## Report Provenance` present | [x] PASS |
| All 5 endpoint IDs in output | [x] PASS |
| Score label and value correct | [x] PASS |

---

## Step 10 — PDF Report

| Field | Value |
|---|---|
| PDF file size (bytes) | 23,049 |
| Magic bytes | `b'%PDF-'` |

| Check | Result |
|---|---|
| Non-empty file | [x] PASS |
| Begins with `%PDF-` | [x] PASS |
| Size in valid range (100B – 10MB) | [x] PASS |

---

## Step 11 — Idempotency Check

**Result:** `status = ALREADY_COMPLETE`, `report_id = report_bf0df63ec1334bf29948cb1a0cca97e1` (unchanged)

| Check | Result |
|---|---|
| `status = ALREADY_COMPLETE` | [x] PASS |
| `report_job_id` unchanged from Step 2 | [x] PASS |

---

## Step 12 — Deterministic Regeneration

| Field | Run A | Run B |
|---|---|---|
| `report_job_id` | `rptjob_4013a87ee2f540b9ac85ecd18ce036e2` | `rptjob_275495f110d2405c8b37345e1051a921` |
| `report_id` | `report_fb441d32c7d04e04886c676c1382f9dd` | `report_68e143213f96496eb5fb517afde86942` |
| `composite_score` | `1.0` | `1.0` |
| `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` |

| Check | Result |
|---|---|
| Both `status = COMPLETE` | [x] PASS |
| `report_job_id` differs between runs | [x] PASS |
| `composite_score` identical | [x] PASS |
| `score_label` identical | [x] PASS |
| `executive_summary` byte-identical across artifacts | [x] PASS |
| `composite_score` section byte-identical | [x] PASS |
| `audit_reliability_overview` byte-identical | [x] PASS |
| `endpoints` byte-identical | [x] PASS |
| `input_lineage` byte-identical | [x] PASS |
| `methodology_disclosure` byte-identical | [x] PASS |

---

## Step 13 — Phase 5 → Phase 6 Consumer Contract

| Invariant | Result |
|---|---|
| Phase 5 prerequisite gate enforced before any Phase 6 DynamoDB write | [x] PASS |
| No new Phase 5 DynamoDB records after campaign (same `intelligence_job_id`) | [x] PASS |
| `composite_score` unchanged from Phase 5 baseline (`1.000`) | [x] PASS |
| `methodology_disclosure` verbatim pass-through | [x] PASS |
| `input_lineage` verbatim pass-through | [x] PASS |
| `score_label_description` absent from Phase 5 artifact (Phase 6-only field) | [x] PASS |

---

## Step 14 — Phase 6 → Phase 7 Consumer Contract

| Field | Value | Result |
|---|---|---|
| `status = COMPLETE` | `COMPLETE` | [x] PASS |
| `report_version = report_v1` | `report_v1` | [x] PASS |
| `report_id` present with `report_` prefix | `report_bf0df63ec1334bf29948cb1a0cca97e1` | [x] PASS |
| `report_job_id` present with `rptjob_` prefix | `rptjob_4508490641de485199084c644a7b80d6` | [x] PASS |
| `composite_score` matches Phase 5 | `1.0` (numeric match) | [x] PASS |
| `score_label` matches Phase 5 | `HIGH_CONFIDENCE` | [x] PASS |
| `endpoint_count = 5` | `5` | [x] PASS |
| `s3_artifact_ref` begins with `reports/` | confirmed | [x] PASS |
| `aggregate_set_hash` matches Phase 5 | `e91c00...acee` | [x] PASS |
| `s3_artifact_ref` is navigable (artifact readable) | confirmed via S3 download | [x] PASS |

---

## Campaign 01 Result

**Overall result:** [x] PASS

**Notes:**

- `intelligence_job_id` differs from Phase 5.8 Campaign 01 documentation (`intjob_1356942a5393...` → `intjob_243ebb6a7e44...`). Live DynamoDB confirms a Phase 5 force-regeneration occurred between Phase 5.8 documentation and this campaign. Scores unchanged: `1.000 / HIGH_CONFIDENCE / 5 endpoints`. No impact on Phase 6 validation.
- `composite_score.value` type difference noted: Phase 5 artifact stores `"1.000"` (string), Phase 6 DTO stores `1.0` (float). Numeric equivalence confirmed. Known Decimal-to-float conversion at the Phase 5→6 DTO boundary.
- All 5 endpoints score `1.000` across all components — confirmed perfect composite.
- No `--report-version` option on `generate report` command (uses internal default `report_v1`); `--report-version` is a `retrieve` argument only.

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 01
```
