# Phase 6.8 Validation Campaign 03

## Campaign Overview

| Field | Value |
|---|---|
| **Campaign** | Phase 6.8 Validation Campaign 03 |
| **Date** | 2026-07-04 |
| **Stage** | dev |
| **Purpose** | End-to-end Phase 6 report pipeline validation against the third Phase 4A.7 Campaign 3 audit |

## Audit Identification (Pre-flight)

The Phase 4A.7 Campaign 3 document acknowledged that the specific audit IDs for the third audit were not captured. The following identification procedure was executed:

1. `rcp client list --stage dev` → identified `client_lineage_issue_verification_3_e830d130` as the third lineage verification client (alongside `_1_` and `_2_` already used in Campaigns 01/02)
2. `rcp audit list --client client_lineage_issue_verification_3_e830d130 --stage dev` → one audit found: `audit_20260626_73ba3612 / lifecycle_state: COMPLETED`
3. DynamoDB query on `PK=CLIENT#client_lineage_issue_verification_3_e830d130` → revealed `audit_execution_id = audexec_1b8179a796a442488f6f27ae5bbc2194`; SK `...#INTEL#intel_v1#META` showed `status = COMPLETE`
4. `rcp retrieve intelligence-status` confirmed Phase 5 COMPLETE, `composite_score = 0.940`, 5 endpoints

## Target Audit

| Field | Value |
|---|---|
| `client_id` | `client_lineage_issue_verification_3_e830d130` |
| `audit_id` | `audit_20260626_73ba3612` |
| `audit_execution_id` | `audexec_1b8179a796a442488f6f27ae5bbc2194` |
| `config_version` | `v1` |
| `aggregation_version` | `agg_v1` |
| `intelligence_version` | `intel_v1` |
| `report_version` | `report_v1` |

## Phase 5 Baseline (confirmed at pre-flight)

| Field | Value |
|---|---|
| `intelligence_job_id` | `intjob_1dbe9f189f2140e48d1ac3bfd556749f` |
| `composite_score` | `0.940` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |
| `s3_artifact_ref` | `intelligence/client_lineage_issue_verification_3_e830d130/audit_20260626_73ba3612/audexec_1b8179a796a442488f6f27ae5bbc2194/agg_v1/intel_v1/intjob_1dbe9f189f2140e48d1ac3bfd556749f/artifact.json` |

---

## Step 1 — Pre-Flight: Phase 5 Gate Verification

**Result:**
```
status: COMPLETE
composite_score: 0.940
intelligence_job_id: intjob_1dbe9f189f2140e48d1ac3bfd556749f
score_label: HIGH_CONFIDENCE
endpoint_count: 5
completed_at: 2026-07-03T14:56:26.817116Z
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
 "endpoint_count": 5, "report_id": "report_8aab5bd443a642c6a681a03f719dab2c",
 "report_job_id": "rptjob_93ecd807018145f7a6761d240b8deb87", "report_version": "report_v1",
 "s3_artifact_ref": "reports/client_lineage_issue_verification_3_e830d130/audit_20260626_73ba3612/audexec_1b8179a796a442488f6f27ae5bbc2194/agg_v1/intel_v1/report_v1/rptjob_93ecd807018145f7a6761d240b8deb87/artifact.json"}
```

| Field | Value Recorded |
|---|---|
| `status` | `COMPLETE` |
| `report_job_id` | `rptjob_93ecd807018145f7a6761d240b8deb87` |
| `report_id` | `report_8aab5bd443a642c6a681a03f719dab2c` |
| `composite_score` | `0.94` |
| `score_label` | `HIGH_CONFIDENCE` |
| `endpoint_count` | `5` |

| Check | Result |
|---|---|
| `status = COMPLETE` | [x] PASS |
| `composite_score` matches Phase 5 baseline | [x] PASS |
| `score_label` matches Phase 5 baseline | [x] PASS |
| `endpoint_count` matches Phase 5 baseline | [x] PASS |
| `report_job_id` has prefix `rptjob_` | [x] PASS |
| `report_id` has prefix `report_` | [x] PASS |

---

## Step 3 — DynamoDB State Verification

**Result:**
```
Report ID:             report_8aab5bd443a642c6a681a03f719dab2c
Report Version:        report_v1
Intelligence Version:  intel_v1
Audit ID:              audit_20260626_73ba3612
Generated At:          2026-07-04T11:41:16.153096Z

Status:        COMPLETE
Score Label:   HIGH_CONFIDENCE
Report Job ID: rptjob_93ecd807018145f7a6761d240b8deb87
Report ID:     report_8aab5bd443a642c6a681a03f719dab2c
Completed At:  2026-07-04T11:41:16.153096Z
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
| `intelligence_provenance` | `intelligence_job_id` | `intjob_1dbe9f189f2140e48d1ac3bfd556749f` | `intjob_1dbe9f189f2140e48d1ac3bfd556749f` | [x] PASS |
| `intelligence_provenance` | `audit_id` | `audit_20260626_73ba3612` | `audit_20260626_73ba3612` | [x] PASS |
| `executive_summary` | `composite_score_value` | `0.94` | `0.94` | [x] PASS |
| `executive_summary` | `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` | [x] PASS |
| `executive_summary` | `endpoint_count` | `5` | `5` | [x] PASS |
| `executive_summary` | `score_label_description` | non-empty string | present | [x] PASS |
| `composite_score` | `value` | `0.94` | `0.94` | [x] PASS |
| `endpoints` | count | `5` | `5` | [x] PASS |
| `input_lineage` | `aggregate_set_hash` | `dc5ad22083efeed5b986fa19c3ebf832fd707087da2b79aab6ad3e1536d1dc83` | matches | [x] PASS |
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
| `Score Label` matches Phase 5 | [x] PASS |
| `Composite Score` matches Phase 5 | [x] PASS |
| `Endpoint Count` matches Phase 5 | [x] PASS |

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
| All endpoints present | [x] PASS |
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
Aggregate Set Hash:     dc5ad22083efeed5b986fa19c3ebf832fd707087da2b79aab6ad3e1536d1dc83
Aggregation Job ID:    aggjob_8f918974122b4898ad06e608272cde5c
Source Raw Result Count: 960
Lineage page count: 5
```

| Check | Result |
|---|---|
| Provenance envelope present | [x] PASS |
| `Aggregate Set Hash` matches Phase 5 | [x] PASS |
| `Aggregation Job ID` present | [x] PASS |
| `Source Raw Result Count` matches Phase 5 | [x] PASS |

---

## Step 9 — Markdown Report

| Check | Result |
|---|---|
| Begins with `# Release Confidence Report` | [x] PASS |
| All 7 section headings present | [x] PASS |
| All endpoint IDs in output | [x] PASS |
| Score label and value correct | [x] PASS |

---

## Step 10 — PDF Report

| Field | Value |
|---|---|
| PDF file size (bytes) | 22,997 |
| Magic bytes | `b'%PDF-'` |

| Check | Result |
|---|---|
| Non-empty file | [x] PASS |
| Begins with `%PDF-` | [x] PASS |
| Size in valid range | [x] PASS |

---

## Step 11 — Idempotency Check

**Result:** `status = ALREADY_COMPLETE`, `report_id = report_8aab5bd443a642c6a681a03f719dab2c` (unchanged)

| Check | Result |
|---|---|
| `status = ALREADY_COMPLETE` | [x] PASS |
| `report_job_id` unchanged | [x] PASS |

---

## Step 12 — Deterministic Regeneration

| Field | Run A | Run B |
|---|---|---|
| `report_job_id` | `rptjob_d12e4c822f4d4d6da7d1e685670c19a3` | `rptjob_f8060485a08648f0a5f188b384c6622b` |
| `report_id` | `report_d70c7d61dc734bb385f2397b537f6458` | `report_202b0a82072a4d9dab1e04bb5f94624f` |
| `composite_score` | `0.94` | `0.94` |
| `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` |

| Check | Result |
|---|---|
| Both `status = COMPLETE` | [x] PASS |
| `report_job_id` differs between runs | [x] PASS |
| `composite_score` identical across runs | [x] PASS |
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
| `report_id` with `report_` prefix | `report_8aab5bd443a642c6a681a03f719dab2c` | [x] PASS |
| `report_job_id` with `rptjob_` prefix | `rptjob_93ecd807018145f7a6761d240b8deb87` | [x] PASS |
| `composite_score` matches Phase 5 | `0.94` (numeric match) | [x] PASS |
| `score_label` matches Phase 5 | `HIGH_CONFIDENCE` | [x] PASS |
| `endpoint_count` matches Phase 5 | `5` | [x] PASS |
| `s3_artifact_ref` begins with `reports/` | confirmed | [x] PASS |
| `aggregate_set_hash` matches Phase 5 | `dc5ad22...dc83` | [x] PASS |
| `s3_artifact_ref` is navigable | confirmed via S3 download | [x] PASS |

---

## Campaign 03 Result

**Overall result:** [x] PASS

**Notes:**

- **Audit identification successful.** The third Phase 4A.7 Campaign 3 audit was identified at pre-flight via `rcp client list` and DynamoDB query as `client_lineage_issue_verification_3_e830d130 / audit_20260626_73ba3612 / audexec_1b8179a796a442488f6f27ae5bbc2194`. Phase 5 intelligence was already COMPLETE (generated 2026-07-03T14:56:26). No Phase 5 generation was required.
- Phase 5 `intelligence_job_id` is `intjob_1dbe9f189f2140e48d1ac3bfd556749f` — unique and distinct from Campaigns 01 and 02.
- `aggregate_set_hash = dc5ad22083efeed5b986fa19c3ebf832fd707087da2b79aab6ad3e1536d1dc83` — unique to this audit's Phase 4 aggregation; distinct from both Campaigns 01 and 02.
- Endpoint score pattern identical to Campaign 02: `health_fast`, `health_flaky`, `health_inconsistent_variant_a` score `0.900`; `health_inconsistent_variant_b` and `health_slow` score `1.000`. Composite `0.940`. This reflects shared endpoint behavior characteristics between the second and third audits.
- Same known Phase 5→6 Decimal-to-float type conversion as Campaigns 01/02 — numeric equivalence confirmed.

**Sign-off:**
```
[QA SIGN-OFF APPROVED] — Phase 6.8 Campaign 03
```
