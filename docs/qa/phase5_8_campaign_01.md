# Phase 5.8 Validation Campaign 01

## Campaign Overview

**Campaign**: Phase 5.8 Validation Campaign 01
**Date**: 2026-07-01
**Stage**: dev
**Branch**: feature/phase-5-8-validation-campaign
**Purpose**: Operational live validation of Phase 5 intelligence generation against Phase 4A audit data in DynamoDB

---

## Target Audit

| Field | Value |
|-------|-------|
| client_id | `client_lineage_issue_verification_1_a6eab2b8` |
| audit_id | `audit_20260626_6f433adc` |
| audit_execution_id | `audexec_b146ca56faa44b7581686a0f1d5e11c7` |
| config_version | `v1` |
| aggregation_version | `agg_v1` |
| aggregation_job_id | `aggjob_8e905bd72a3c42a4a8beb02629501cbc` |
| aggregate_set_hash | `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` |
| endpoint_aggregate_count | 5 |
| source_raw_result_count | 955 |
| aggregate_set_completion_created_at | `2026-06-28T15:05:38.601548Z` |

---

## Run 1 — Initial Generation (COMPLETE)

**Command**:
```bash
rcp generate intelligence \
  --client client_lineage_issue_verification_1_a6eab2b8 \
  --audit audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --stage dev \
  --output json
```

**Result**:
```json
{
  "aggregation_version": "agg_v1",
  "audit_execution_id": "audexec_b146ca56faa44b7581686a0f1d5e11c7",
  "audit_id": "audit_20260626_6f433adc",
  "client_id": "client_lineage_issue_verification_1_a6eab2b8",
  "command": "generate intelligence",
  "composite_score": "1.000",
  "config_version": "v1",
  "endpoint_count": 5,
  "intelligence_job_id": "intjob_1356942a5393419a86a6b277a828d802",
  "intelligence_version": "intel_v1",
  "s3_artifact_ref": "intelligence/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/agg_v1/intel_v1/intjob_1356942a5393419a86a6b277a828d802/artifact.json",
  "score_label": "HIGH_CONFIDENCE",
  "stage": "dev",
  "status": "COMPLETE",
  "summary": "Intelligence generation complete for audit_20260626_6f433adc"
}
```

| Field | Value |
|-------|-------|
| intelligence_job_id | `intjob_1356942a5393419a86a6b277a828d802` |
| composite_score | `1.000` |
| score_label | `HIGH_CONFIDENCE` |
| endpoint_count | 5 |
| status | `COMPLETE` |

---

## Run 2 — Idempotency Check (ALREADY_COMPLETE)

**Command**: Same as Run 1 (no `--force`)

**Result**:
```json
{
  "intelligence_job_id": "intjob_1356942a5393419a86a6b277a828d802",
  "composite_score": "1.000",
  "score_label": "HIGH_CONFIDENCE",
  "status": "ALREADY_COMPLETE"
}
```

**Idempotency gate**: PASSED — same `intelligence_job_id` returned, no new S3 write.

---

## Run 3 — Force Re-Generation (Determinism Check)

**Command**: Same as Run 1 with `--force`

**Result**:
```json
{
  "intelligence_job_id": "intjob_243ebb6a7e444e4bb46e3ae47a907161",
  "composite_score": "1.000",
  "score_label": "HIGH_CONFIDENCE",
  "status": "COMPLETE"
}
```

**Determinism check**: PASSED
- New `intelligence_job_id` generated: `intjob_243ebb6a7e444e4bb46e3ae47a907161`
- `composite_score` identical: `1.000` (byte-identical computation)

---

## S3 Artifact Verification

**Artifact key**: `intelligence/client_lineage_issue_verification_1_a6eab2b8/audit_20260626_6f433adc/audexec_b146ca56faa44b7581686a0f1d5e11c7/agg_v1/intel_v1/intjob_1356942a5393419a86a6b277a828d802/artifact.json`

**Top-level keys present**: `aggregation_version`, `audit_execution_id`, `audit_id`, `audit_reliability_summary`, `client_id`, `composite_score`, `config_version`, `endpoints`, `generated_at`, `generator_version`, `input_lineage`, `intelligence_job_id`, `intelligence_version`, `methodology_disclosure` — all 14 required keys ✓

**composite_score**:
```json
{
  "value": "1.000",
  "score_label": "HIGH_CONFIDENCE",
  "aggregate_set_hash": "e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee",
  "endpoint_count": 5,
  "component_breakdown": {
    "reliability": {"weight": 0.5, "value": "1.000"},
    "stability": {"weight": 0.2, "value": "1.000"},
    "burst": {"weight": 0.15, "value": "1.000"},
    "consistency": {"weight": 0.15, "value": "1.000"}
  }
}
```

**Endpoints** (5 total, sorted by endpoint_id):
- `health_fast`, `health_flaky`, `health_inconsistent_variant_a`, `health_inconsistent_variant_b`, `health_slow`

**input_lineage.aggregate_set_hash**: `e91c00463fdf75619fff2a7b2c36db1b10e5ec9ff3d4beb3113dd19c3822acee` — matches DynamoDB AggregateSetCompletion ✓

---

## Retrieve Command Verification

All four retrieve commands verified:

**intelligence-status**:
```bash
rcp retrieve intelligence-status \
  --client client_lineage_issue_verification_1_a6eab2b8 \
  --audit audit_20260626_6f433adc \
  --execution audexec_b146ca56faa44b7581686a0f1d5e11c7 \
  --config-version v1 --stage dev --output json
```
Result: `status: COMPLETE`, `composite_score: "1.000"`, `intelligence_job_id: intjob_243ebb6a7e444e4bb46e3ae47a907161` ✓

**intelligence-summary**: Returned full `IntelligenceMetadata` record with all fields including `aggregate_set_hash`, `aggregation_version`, `created_at`, `completed_at` ✓

**intelligence-methodology**: Returned `methodology_disclosure` section with `burst_label_definitions`, `consistency_label_definitions`, `intelligence_version`, `label_to_score_mapping`, `limitations`, `scoring`, `stability_label_definitions` ✓

---

## Campaign Result

| Check | Result |
|-------|--------|
| AggregateSetCompletion gate passed | ✓ PASS |
| IntelligenceJob → COMPLETE | ✓ PASS |
| IntelligenceMetadata → COMPLETE | ✓ PASS |
| S3 artifact written (all 14 keys) | ✓ PASS |
| composite_score in [0.0, 1.0] | ✓ PASS (1.000) |
| score_label = HIGH_CONFIDENCE | ✓ PASS |
| endpoint_count = 5 | ✓ PASS |
| aggregate_set_hash lineage traced | ✓ PASS |
| Idempotency: re-run → ALREADY_COMPLETE | ✓ PASS |
| Determinism: force re-gen → same score | ✓ PASS |
| Retrieve intelligence-status | ✓ PASS |
| Retrieve intelligence-summary | ✓ PASS |
| Retrieve intelligence-methodology | ✓ PASS |
