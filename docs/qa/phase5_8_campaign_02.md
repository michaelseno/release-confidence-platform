# Phase 5.8 Validation Campaign 02

## Campaign Overview

**Campaign**: Phase 5.8 Validation Campaign 02
**Date**: 2026-07-01
**Stage**: dev
**Branch**: feature/phase-5-8-validation-campaign
**Purpose**: Operational live validation against a second independent Phase 4A audit dataset (score differentiation and per-endpoint label verification)

---

## Target Audit

| Field | Value |
|-------|-------|
| client_id | `client_lineage_issue_verification_2_1b5e3d6e` |
| audit_id | `audit_20260626_c3927ce1` |
| audit_execution_id | `audexec_00294bb91dc74d499e46c9788718b86a` |
| config_version | `v1` |
| aggregation_version | `agg_v1` |
| aggregation_job_id | `aggjob_b88a256834654551b7e2a5b66ad2a75f` |
| aggregate_set_hash | `7bafd96232b0825cc7e0e6a4c0b843e9ecf079e82b1007e7efc87694dd4cf4fc` |
| endpoint_aggregate_count | 5 |
| source_raw_result_count | 960 |
| aggregate_set_completion_created_at | `2026-06-28T15:08:07Z` |

---

## Run 1 — Initial Generation (COMPLETE)

**Command**:
```bash
rcp generate intelligence \
  --client client_lineage_issue_verification_2_1b5e3d6e \
  --audit audit_20260626_c3927ce1 \
  --execution audexec_00294bb91dc74d499e46c9788718b86a \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --stage dev \
  --output json
```

**Result**:
```json
{
  "aggregation_version": "agg_v1",
  "audit_execution_id": "audexec_00294bb91dc74d499e46c9788718b86a",
  "audit_id": "audit_20260626_c3927ce1",
  "client_id": "client_lineage_issue_verification_2_1b5e3d6e",
  "command": "generate intelligence",
  "composite_score": "0.940",
  "config_version": "v1",
  "endpoint_count": 5,
  "intelligence_job_id": "intjob_ab4e177fcf0e40288e30a9d1a3bbb992",
  "intelligence_version": "intel_v1",
  "s3_artifact_ref": "intelligence/client_lineage_issue_verification_2_1b5e3d6e/audit_20260626_c3927ce1/audexec_00294bb91dc74d499e46c9788718b86a/agg_v1/intel_v1/intjob_ab4e177fcf0e40288e30a9d1a3bbb992/artifact.json",
  "score_label": "HIGH_CONFIDENCE",
  "stage": "dev",
  "status": "COMPLETE",
  "summary": "Intelligence generation complete for audit_20260626_c3927ce1"
}
```

| Field | Value |
|-------|-------|
| intelligence_job_id | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` |
| composite_score | `0.940` |
| score_label | `HIGH_CONFIDENCE` |
| endpoint_count | 5 |
| status | `COMPLETE` |

---

## Run 2 — Idempotency Check (ALREADY_COMPLETE)

**Command**: Same as Run 1 (no `--force`)

**Result**:
```json
{
  "intelligence_job_id": "intjob_ab4e177fcf0e40288e30a9d1a3bbb992",
  "composite_score": "0.940",
  "score_label": "HIGH_CONFIDENCE",
  "status": "ALREADY_COMPLETE"
}
```

**Idempotency gate**: PASSED — same `intelligence_job_id` returned, no new Phase 5 records written.

---

## Per-Endpoint Score Analysis (From S3 Artifact)

**Artifact key**: `intelligence/client_lineage_issue_verification_2_1b5e3d6e/audit_20260626_c3927ce1/audexec_00294bb91dc74d499e46c9788718b86a/agg_v1/intel_v1/intjob_ab4e177fcf0e40288e30a9d1a3bbb992/artifact.json`

**Verified per-endpoint labels** (health_fast endpoint, representative):

| Analysis | Label | Score |
|----------|-------|-------|
| success_rate_stability | STABLE | 1.0 |
| latency_stability | DEGRADED | 0.0 |
| failure_burst | NO_BURST_DETECTED | 1.0 |
| latency_spike | NO_SPIKE_DETECTED | 1.0 |
| consistency | CONSISTENT | 1.0 |

**health_fast endpoint composite**: `0.900`
- Computation: `0.50*1.000 + 0.20*((1.0+0.0)/2) + 0.15*((1.0+1.0)/2) + 0.15*1.000`
- `= 0.500 + 0.100 + 0.150 + 0.150 = 0.900`
- latency_stability DEGRADED because: `p99/mean = 330ms/64.8ms = 5.09 > P99_MEAN_RATIO_THRESHOLD 3.0`

**Methodology trace verified**: All intermediate values present (`p99_mean_ratio`, `timeout_proportion`, `outcome_variance`, `max_p99_ratio`) with full threshold disclosure ✓

**Audit composite (0.940)**: Mean of per-endpoint scores across 5 endpoints; `health_fast` contributes 0.900, reflecting genuine latency distributional spread detected by `latency_stability_v1` ✓

---

## Score Differentiation from Campaign 01

| Audit | composite_score | Score differs from Campaign 01 |
|-------|-----------------|-------------------------------|
| Campaign 01 (lineage_verification_1) | 1.000 | — |
| Campaign 02 (lineage_verification_2) | 0.940 | ✓ CONFIRMED |

Campaign 02 score differs because `health_fast` endpoint has latency DEGRADED (p99/mean > 3.0x threshold). Campaign 01 endpoints all received STABLE labels across all dimensions. This confirms the pipeline is correctly computing per-dataset scores rather than returning a constant.

---

## Campaign Result

| Check | Result |
|-------|--------|
| AggregateSetCompletion gate passed | ✓ PASS |
| IntelligenceJob → COMPLETE | ✓ PASS |
| IntelligenceMetadata → COMPLETE | ✓ PASS |
| S3 artifact written (all 14 keys) | ✓ PASS |
| composite_score in [0.0, 1.0] | ✓ PASS (0.940) |
| score_label = HIGH_CONFIDENCE | ✓ PASS |
| endpoint_count = 5 | ✓ PASS |
| aggregate_set_hash lineage traced | ✓ PASS |
| Idempotency: re-run → ALREADY_COMPLETE | ✓ PASS |
| Per-endpoint labels verified | ✓ PASS |
| Methodology traces verified | ✓ PASS |
| Score differentiates from Campaign 01 | ✓ PASS |
