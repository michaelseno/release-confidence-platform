# Phase 6.8 Validation Campaign 02

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 02 |
| **Date** | 2026-07-04 |
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

## Phase 5 Baseline (from Phase 5.8 Campaign 02 — confirmed live)

| Field | Value |
|---|---|
| `intelligence_job_id` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` |
| `composite_score` | `0.940` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `intelligence/client_lineage_issue_verification_2_1b5e3d6e/audit_20260626_c3927ce1/audexec_00294bb91dc74d499e46c9788718b86a/agg_v1/intel_v1/intjob_ab4e177fcf0e40288e30a9d1a3bbb992/artifact.json` |

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Result:**
```
status: COMPLETE
composite_score: 0.940
intelligence_job_id: intjob_ab4e177fcf0e40288e30a9d1a3bbb992
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
{"status": "COMPLETE", "composite_score": "0.94", "score_label": "HIGH_CONFIDENCE",
 "endpoint_count": 5, "report_id": "report_505e9cc28708479ca70abeac73b68c3f",
 "report_job_id": "rptjob_09f613ddde4748639894595b715161cf", "report_version": "report_v1"}
```

| Field | Value Recorded |
|---|---|
| `status` | `COMPLETE` |
| `report_job_id` | `rptjob_09f613ddde4748639894595b715161cf` |
| `report_id` | `report_505e9cc28708479ca70abeac73b68c3f` |
| `composite_score` | `0.94` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |

| Check | Result |
|---|---|
| `status = COMPLETE` | [x] PASS |
| `composite_score = 0.940` | [x] PASS |
| `score_label = HIGH_CONFIDENCE` | [x] PASS |
| `endpoint_count = 5` | [x] PASS |
| `report_job_id` has prefix `rptjob_` | [x] PASS |
| `report_id` has prefix `report_` | [x] PASS |

---

## Step 3 — DynamoDB State Verification

**Result:**
```
Report ID:             report_505e9cc28708479ca70abeac73b68c3f
Report Version:        report_v1
Intelligence Version:  intel_v1
Audit ID:              audit_20260626_c3927ce1
Generated At:          2026-07-04T11:37:21.628008Z

Status:        COMPLETE
Score Label:   HIGH_CONFIDENCE
Report Job ID: rptjob_09f613ddde4748639894595b715161cf
Report ID:     report_505e9cc28708479ca70abeac73b68c3f
Completed At:  2026-07-04T11:37:21.628008Z
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
| `intelligence_provenance` | `intelligence_job_id` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` | [x] PASS |
| `intelligence_provenance` | `audit_id` | `audit_20260626_c3927ce1` | `audit_20260626_c3927ce1` | [x] PASS |
| `executive_summary` | `composite_score_value` | `0.94` | `0.94` | [x] PASS |
| `executive_summary` | `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` | [x] PASS |
| `executive_summary` | `endpoint_count` | `5` | `5` | [x] PASS |
| `executive_summary` | `score_label_description` | non-empty string | present | [x] PASS |
| `composite_score` | `value` | `0.94` | `0.94` | [x] PASS |
| `audit_reliability_overview` | `endpoint_count` | `5` | `5` | [x] PASS |
| `endpoints` | count | `5` | `5` | [x] PASS |
| `input_lineage` | `aggregate_set_hash` | `7bafd96232b0825cc7e0e6a4c0b843e9ecf079e82b1007e7efc87694dd4cf4fc` | matches | [x] PASS |
| `input_lineage` | `source_raw_result_count` | `960` | `960` | [x] PASS |
| `methodology_disclosure` | `intelligence_version` | `intel_v1` | `intel_v1` | [x] PASS |
| `identity` | `report_version` | `report_v1` | `report_v1` | [x] PASS |

| Check | Result |
|---|---|
| Phase 5 `intelligence_job_id` unchanged | [x] PASS |
| Phase 5 `composite_score` unchanged | [x] PASS |

---

## Step 5 — Executive Summary CLI

**Result:**
```
Score Label:              HIGH_CONFIDENCE
Composite Score:          0.940
Endpoint Count:           5
Audit Success Rate:       1.000
Total Executions:         960
Score Label Description:  Reliability indicators across all assessed endpoints are strong. The observed evidence does not indicate material reliability concerns for the audited release scope.
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Score Label: HIGH_CONFIDENCE` | [x] PASS |
| `Composite Score: 0.940` | [x] PASS |
| `Endpoint Count: 5` | [x] PASS |

---

## Step 6 — Per-Endpoint CLI

**Result:**
```
Endpoint ID                                 Composite  Reliability  Stability    Burst  Consistency
---------------------------------------------------------------------------------------------------
health_fast                                     0.900        1.000      0.500    1.000        1.000
health_flaky                                    0.900        1.000      0.500    1.000        1.000
health_inconsistent_variant_a                   0.900        1.000      0.500    1.000        1.000
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
| JSON blocks present | [x] PASS |

---

## Step 8 — Evidence Lineage CLI

**Result:**
```
Aggregate Set Hash:     7bafd96232b0825cc7e0e6a4c0b843e9ecf079e82b1007e7efc87694dd4cf4fc
Aggregation Job ID:    aggjob_b88a256834654551b7e2a5b66ad2a75f
Source Raw Result Count: 960
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Aggregate Set Hash` matches Phase 5 | [x] PASS |
| `Aggregation Job ID` present | [x] PASS |
| `Source Raw Result Count: 960` | [x] PASS |

---

## Step 9 — Markdown Report

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [x] PASS |
| All 7 section headings present | [x] PASS |
| All 5 endpoint IDs in output | [x] PASS |
| `composite_score = 0.940` present | [x] PASS |

---

## Step 10 — PDF Report

| Field | Value |
|---|---|
| PDF file size (bytes) | 23,044 |
| Magic bytes | `b'%PDF-'` |

| Check | Result |
|---|---|
| Non-empty file | [x] PASS |
| Begins with `%PDF-` | [x] PASS |
| Size in valid range | [x] PASS |

---

## Step 11 — Idempotency Check

**Result:** `status = ALREADY_COMPLETE`, `report_id = report_505e9cc28708479ca70abeac73b68c3f` (unchanged)

| Check | Result |
|---|---|
| `status = ALREADY_COMPLETE` | [x] PASS |
| `report_job_id` unchanged | [x] PASS |

---

## Step 12 — Deterministic Regeneration

| Field | Run A | Run B |
|---|---|---|
| `report_job_id` | `rptjob_10510fa1423649c783485207f439d8fc` | `rptjob_4360759cda6b4f4f8b70800f5f2e64b9` |
| `report_id` | `report_9093d271f5e74984b18caa77fcc37c42` | `report_8579e72820f3457ca223cb55fc84e9fa` |
| `composite_score` | `0.94` | `0.94` |
| `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` |

| Check | Result |
|---|---|
| Both `status = COMPLETE` | [x] PASS |
| `report_job_id` differs between runs | [x] PASS |
| `composite_score` identical (`0.940`) | [x] PASS |
| `generation_count` incremented correctly | [x] PASS |
| All 6 content sections byte-identical across artifacts | [x] PASS |

---

## Step 13 — Phase 5 → Phase 6 Consumer Contract

| Invariant | Result |
|---|---|
| Phase 5 prerequisite gate enforced | [x] PASS |
| No new Phase 5 DynamoDB records post-campaign | [x] PASS |
| `composite_score` unchanged from Phase 5 baseline (`0.940`) | [x] PASS |
| `methodology_disclosure` verbatim pass-through | [x] PASS |
| `input_lineage` verbatim pass-through | [x] PASS |
| `score_label_description` absent from Phase 5 artifact | [x] PASS |

---

## Step 14 — Phase 6 → Phase 7 Consumer Contract

| Field | Value | Result |
|---|---|---|
| `status = COMPLETE` | `COMPLETE` | [x] PASS |
| `report_version = report_v1` | `report_v1` | [x] PASS |
| `report_id` with `report_` prefix | `report_505e9cc28708479ca70abeac73b68c3f` | [x] PASS |
| `report_job_id` with `rptjob_` prefix | `rptjob_09f613ddde4748639894595b715161cf` | [x] PASS |
| `composite_score = 0.940` | `0.94` (numeric match) | [x] PASS |
| `score_label = HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` | [x] PASS |
| `endpoint_count = 5` | `5` | [x] PASS |
| `s3_artifact_ref` begins with `reports/` | confirmed | [x] PASS |
| `aggregate_set_hash` matches Phase 5 | `7bafd96...4fc` | [x] PASS |
| `s3_artifact_ref` is navigable | confirmed via S3 download | [x] PASS |

---

## Campaign 02 Result

**Overall result:** [x] PASS

**Notes:**

- Phase 5 baseline `intelligence_job_id` matches documentation exactly — no force-regeneration occurred for this audit.
- `composite_score.value` type difference: Phase 5 stores `"0.940"` (string), Phase 6 DTO stores `0.94` (float). Numeric equivalence confirmed: `float('0.940') == float('0.94')`. Same known Phase 5→6 Decimal-to-float conversion as Campaign 01.
- Endpoint differentiation observed: `health_fast`, `health_flaky`, and `health_inconsistent_variant_a` score `0.900` (stability degraded); `health_inconsistent_variant_b` and `health_slow` score `1.000`. This produces a composite of `0.940`, correctly differing from Campaign 01's `1.000`.

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 02
```
