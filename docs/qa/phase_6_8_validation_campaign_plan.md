# Phase 6.8 — Deterministic Reporting Validation Campaign Plan

## Overview

**Phase:** 6.8 — Operational Validation Campaign
**Date:** 2026-07-04
**Stage:** dev
**Purpose:** Live end-to-end validation of the Phase 6 Deterministic Reporting pipeline against the three Phase 4A.7 Campaign 3 48-hour audit executions that have confirmed Phase 5 intelligence artifacts.

Upon successful completion of all three campaigns, Phase 6 is formally closed and Phase 7 planning begins.

---

## Target Audits

| Campaign | Client ID | Audit ID | Execution ID | Phase 5 Status |
|---|---|---|---|---|
| Campaign 01 | `client_lineage_issue_verification_1_a6eab2b8` | `audit_20260626_6f433adc` | `audexec_b146ca56faa44b7581686a0f1d5e11c7` | COMPLETE (Phase 5.8 Campaign 01) |
| Campaign 02 | `client_lineage_issue_verification_2_1b5e3d6e` | `audit_20260626_c3927ce1` | `audexec_00294bb91dc74d499e46c9788718b86a` | COMPLETE (Phase 5.8 Campaign 02) |
| Campaign 03 | *(third Phase 4A.7 audit — ID to confirm at pre-flight)* | *(to confirm)* | *(to confirm)* | Requires pre-flight check |

**Phase 5 Intelligence Versions (Campaigns 01 & 02):**

| Field | Campaign 01 | Campaign 02 |
|---|---|---|
| `intelligence_version` | `intel_v1` | `intel_v1` |
| `intelligence_job_id` | `intjob_1356942a5393419a86a6b277a828d802` | `intjob_ab4e177fcf0e40288e30a9d1a3bbb992` |
| `composite_score` | `1.000` | `0.940` |
| `score_label` | `HIGH_CONFIDENCE` | `HIGH_CONFIDENCE` |
| `endpoint_count` | 5 | 5 |

---

## Campaign Prerequisites

Before beginning any campaign:

1. Phase 6.7 PR #74 merged and `origin/main` synced.
2. `rcp` CLI installed in venv: `pip install -e .`
3. AWS credentials active for `dev` stage.
4. DynamoDB table `release-confidence-platform-dev-metadata` accessible.
5. S3 bucket accessible (resolved from `StageConfig.config_bucket`).
6. Phase 5 `IntelligenceMetadata.status = COMPLETE` confirmed for the target audit (pre-flight step).

**Campaign 03 additional prerequisite:** Identify the third Phase 4A.7 audit's `client_id`, `audit_id`, and `audit_execution_id` from the DynamoDB table. If Phase 5 intelligence is not yet COMPLETE for this audit, run `rcp generate intelligence` before beginning the Phase 6.8 campaign for that audit.

---

## Validation Methodology

Each campaign follows this fixed sequence. All steps are mandatory. No step may be skipped.

### Step 1 — Pre-Flight: Phase 5 Gate Verification

Confirm that `IntelligenceMetadata.status = COMPLETE` for the target audit using the Phase 5 retrieval CLI:

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

**Pass criterion:** `status = COMPLETE` confirmed. `s3_artifact_ref` is present and non-null.

---

### Step 2 — Generate Report (Initial)

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

**Record:** `report_job_id`, `report_id`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`.

**Pass criteria:**
- `status = COMPLETE`
- `report_job_id` has prefix `rptjob_`
- `report_id` has prefix `report_`
- `composite_score` matches Phase 5 `composite_score` exactly (string equality)
- `score_label` matches Phase 5 `score_label` exactly
- `endpoint_count` matches Phase 5 `endpoint_count` exactly

---

### Step 3 — DynamoDB State Verification

```bash
rcp retrieve report-status \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- `Status: COMPLETE`
- `Report Job ID` matches `report_job_id` from Step 2
- `Report ID` matches `report_id` from Step 2
- Provenance envelope present: `Report ID`, `Report Version`, `Intelligence Version`, `Audit ID`, `Generated At`

---

### Step 4 — JSON Artifact Retrieval and Fidelity Check

```bash
rcp retrieve report-json \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Phase 5 → Phase 6 Fidelity Checks** (compare JSON output against Phase 5 S3 artifact):

| Section | Field | Expected Source |
|---|---|---|
| `intelligence_provenance.intelligence_version` | `intel_v1` | Phase 5 artifact `intelligence_version` |
| `intelligence_provenance.intelligence_job_id` | exact match | Phase 5 artifact `intelligence_job_id` |
| `intelligence_provenance.audit_id` | exact match | Phase 5 artifact `audit_id` |
| `intelligence_provenance.aggregate_set_hash` | exact match | Phase 5 `composite_score.aggregate_set_hash` |
| `executive_summary.composite_score_value` | exact float | Phase 5 `composite_score.value` |
| `executive_summary.score_label` | exact string | Phase 5 `composite_score.score_label` |
| `executive_summary.endpoint_count` | exact int | Phase 5 `composite_score.endpoint_count` |
| `executive_summary.audit_success_rate` | exact float | Phase 5 `audit_reliability_summary.audit_success_rate` |
| `executive_summary.total_executions` | exact int | Phase 5 `audit_reliability_summary.total_executions` |
| `executive_summary.score_label_description` | non-empty string | Phase 6 bounded mapping (not from Phase 5) |
| `audit_reliability_overview.*` | all fields | Pass-through from Phase 5 `audit_reliability_summary` |
| `composite_score.value` | exact float | Phase 5 `composite_score.value` |
| `composite_score.component_breakdown` | exact dict | Phase 5 `composite_score.component_breakdown` |
| `endpoints[*].endpoint_id` | exact strings, same order | Phase 5 `endpoints[*].endpoint_id` |
| `endpoints[*].endpoint_score.*` | exact floats | Phase 5 `endpoints[*].endpoint_score.*` |
| `endpoints[*].reliability_metrics.*` | all fields | Pass-through from Phase 5 |
| `endpoints[*].stability_analysis.*` | labels + trace | Pass-through from Phase 5 |
| `endpoints[*].burst_analysis.*` | labels + trace | Pass-through from Phase 5 |
| `endpoints[*].consistency_analysis.*` | label + trace | Pass-through from Phase 5 |
| `input_lineage.aggregate_set_hash` | exact string | Phase 5 `input_lineage.aggregate_set_hash` |
| `input_lineage.source_raw_result_count` | exact int | Phase 5 `input_lineage.source_raw_result_count` |
| `methodology_disclosure.*` | verbatim | Pass-through from Phase 5 `methodology_disclosure` |
| `identity.report_version` | `report_v1` | Phase 6 constant |

**No-mutation check:** Confirm the Phase 5 S3 artifact at the original `intelligence/.../artifact.json` key is byte-identical to its state before the Phase 6 campaign run. (Check: retrieve it again and compare `intelligence_job_id`, `composite_score`, `generated_at` to values recorded in Phase 5.8 campaign doc.)

---

### Step 5 — Executive Summary CLI Check

```bash
rcp retrieve report-summary \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- Provenance envelope present
- `Score Label` matches Phase 5 `score_label`
- `Composite Score` matches Phase 5 `composite_score.value`
- `Endpoint Count` matches Phase 5 `endpoint_count`
- `Score Label Description` is non-empty

---

### Step 6 — Per-Endpoint CLI Check

```bash
rcp retrieve report-endpoints \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- Provenance envelope present
- All 5 endpoints appear in output (by `endpoint_id`)
- Composite, Reliability, Stability, Burst, Consistency scores present for each endpoint
- Scores are decimal values in `[0.0, 1.0]`

---

### Step 7 — Methodology Disclosure CLI Check

```bash
rcp retrieve report-methodology \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- Provenance envelope present
- `Intelligence Version: intel_v1` present
- Limitations list present and non-empty
- Scoring, label definitions, and label-to-score mapping JSON blocks present

---

### Step 8 — Evidence Lineage CLI Check

```bash
rcp retrieve report-lineage \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- Provenance envelope present
- `Aggregate Set Hash` matches Phase 5 `input_lineage.aggregate_set_hash`
- `Aggregation Job ID` matches Phase 5 `input_lineage.aggregation_job_id`
- `Source Raw Result Count` matches Phase 5 `input_lineage.source_raw_result_count`

---

### Step 9 — Markdown Report

```bash
rcp retrieve report-markdown \
  --client-id <client_id> \
  --audit-id <audit_id> \
  --execution <audit_execution_id> \
  --config-version v1 \
  --aggregation-version agg_v1 \
  --intelligence-version intel_v1 \
  --report-version report_v1 \
  --stage dev
```

**Pass criteria:**
- Output begins with `# Release Confidence Report`
- All 8 section headings present: `## Executive Summary`, `## Release Confidence Score`, `## Audit Reliability Overview`, `## Per-Endpoint Analysis`, `## Methodology Disclosure`, `## Evidence Lineage`, `## Report Provenance`
- Score label and composite score values are present and correct
- All 5 endpoint IDs appear in output
- No envelope header before the Markdown heading

---

### Step 10 — PDF Report

Generate using a local Python script or CLI (no dedicated retrieve command exists for PDF — generate programmatically):

```python
import json, boto3
from release_confidence_platform.deterministic_reporting.formatters.pdf import PdfFormatter
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport

# Load artifact from S3
s3 = boto3.client("s3", region_name="us-east-1")
artifact = json.loads(s3.get_object(Bucket="<config_bucket>", Key="<s3_artifact_ref>")["Body"].read())
report = ReleaseConfidenceReport.model_validate(artifact)
pdf_bytes = PdfFormatter().render(report)

with open("report_campaign_<N>.pdf", "wb") as f:
    f.write(pdf_bytes)
print(f"PDF size: {len(pdf_bytes)} bytes")
```

**Pass criteria:**
- File is non-empty
- File begins with `%PDF-` magic bytes
- File size is reasonable (100 bytes < size < 10 MB)
- PDF opens and is visually inspectable (manual check)
- All 8 sections visible in the rendered PDF

---

### Step 11 — Idempotency Check

Re-run the `generate report` command without `--force`:

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

**Pass criteria:**
- `status = ALREADY_COMPLETE`
- `report_job_id` is identical to Step 2 value
- `report_id` is identical to Step 2 value
- No new S3 artifact written

---

### Step 12 — Deterministic Regeneration

Run `generate report --force` twice and compare outputs:

```bash
# Run A
rcp generate report --force \
  --client-id <client_id> ... --output json

# Run B (immediately after)
rcp generate report --force \
  --client-id <client_id> ... --output json
```

**Pass criteria:**
- Both runs return `status = COMPLETE`
- Both produce different `report_job_id` values (new job per force regeneration)
- Both produce the same `composite_score`, `score_label`, and `endpoint_count`
- `generation_count` increments correctly (Step 2 = 1, Run A = 2, Run B = 3)
- Retrieve `report-json` for both artifacts and confirm: `executive_summary`, `composite_score`, `endpoints[*].endpoint_score`, `methodology_disclosure`, and `input_lineage` sections are byte-identical across both generated artifacts

---

### Step 13 — Phase 5 → Phase 6 Consumer Contract Validation

Confirm the following contract invariants hold for the campaign artifact:

| Contract Invariant | Verification Method |
|---|---|
| Phase 5 `IntelligenceMetadata.status = COMPLETE` was the prerequisite gate | Step 1 pre-flight confirmed before any Phase 6 writes |
| Phase 6 engine never wrote to a Phase 5 SK (`#INTJOB#`, `#LINEAGE#`) | Confirm no new Phase 5 DynamoDB records exist post-campaign (retrieve Phase 5 status, confirm same `intelligence_job_id`) |
| Phase 5 `composite_score` is unchanged | Compare `composite_score` from Phase 5 artifact to Step 4 report JSON |
| Phase 5 `methodology_disclosure` is verbatim | Compare full `methodology_disclosure` dict between Phase 5 artifact and report JSON |
| Phase 5 `input_lineage` is verbatim | Compare full `input_lineage` dict between Phase 5 artifact and report JSON |
| `score_label_description` is Phase 6-only (not from Phase 5) | Confirm field absent in Phase 5 artifact; present in report `executive_summary` |

---

### Step 14 — Phase 6 → Phase 7 Consumer Contract Validation

Confirm the following Phase 7 gate fields are present and correct in `ReportMetadata` (via `retrieve report-status` output):

| Field | Expected Value |
|---|---|
| `status` | `COMPLETE` |
| `report_version` | `report_v1` |
| `report_id` | Present, non-null, `report_` prefix |
| `report_job_id` | Present, non-null, `rptjob_` prefix |
| `composite_score` | Matches Phase 5 value |
| `score_label` | Matches Phase 5 value |
| `endpoint_count` | Matches Phase 5 value |
| `s3_artifact_ref` | Present, non-null, begins with `reports/` |
| `aggregate_set_hash` | Matches Phase 5 `composite_score.aggregate_set_hash` |

Confirm that `s3_artifact_ref` is navigable (artifact is readable via `report-json` command — already confirmed in Step 4).

**Phase 7 must not construct the S3 key independently.** Confirm `s3_artifact_ref` follows the pattern `reports/{client_id}/{audit_id}/{exec_id}/{agg_v}/{intel_v}/{report_v}/{rptjob_id}/artifact.json`.

---

## Campaign Evidence Documents

Each campaign is documented in a dedicated evidence file:

| Campaign | Audit | Evidence File |
|---|---|---|
| Campaign 01 | `audit_20260626_6f433adc` | `docs/qa/phase_6_8_campaign_01.md` |
| Campaign 02 | `audit_20260626_c3927ce1` | `docs/qa/phase_6_8_campaign_02.md` |
| Campaign 03 | *(to confirm)* | `docs/qa/phase_6_8_campaign_03.md` |

---

## Campaign Acceptance Criteria

All three campaigns must satisfy the following for Phase 6 closure:

- [ ] All 14 validation steps passed for all three audits
- [ ] No Phase 5 mutation observed in any campaign
- [ ] Deterministic regeneration confirmed for all three audits
- [ ] All 7 `retrieve report-*` CLI commands return correct output for all three audits
- [ ] JSON, Markdown, and PDF outputs generated and verified for all three audits
- [ ] Phase 5 → Phase 6 consumer contract validated for all three audits
- [ ] Phase 6 → Phase 7 consumer contract validated for all three audits
- [ ] HITL approval received for all three campaign evidence documents

---

## Phase 6 Closure Gate

Phase 6 is formally closed when:

1. All three campaign evidence documents are complete.
2. All acceptance criteria above are satisfied.
3. HITL validation is received for the complete campaign set.
4. GitHub Issues #64–#71 are closed.

Phase 7 planning begins immediately after Phase 6 closure.
