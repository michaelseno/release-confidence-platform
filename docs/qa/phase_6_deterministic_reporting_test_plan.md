# QA / Test Plan

## Phase 6 — Deterministic Reporting

---

## 1. Scope

This test plan governs validation for Phase 6 — Deterministic Reporting. It covers unit tests, integration tests, contract tests, formatter tests, CLI tests, and the Phase 6.8 validation campaign.

Phase 6 introduces:
- `ReleaseConfidenceReport` Pydantic model (Canonical Report DTO)
- `ReportBuilder` — Phase 5 intelligence artifact → DTO
- `engine.py` — generation pipeline with prerequisite gate and status lifecycle
- `publisher.py` — S3 artifact write and read
- `repository.py` — DynamoDB `ReportJob` + `ReportMetadata` records
- `MarkdownFormatter` and `PdfFormatter`
- Operator CLI: `rcp generate report` and `retrieve report-*` commands

The primary validation goals:
1. Phase 5 intelligence conclusions appear faithfully in every format with no alteration.
2. Phase 5 re-derivation never occurs anywhere in Phase 6 code.
3. Report generation is deterministic: identical Phase 5 inputs produce byte-identical JSON artifacts.
4. The prerequisite gate (`IntelligenceMetadata.status = COMPLETE`) is enforced unconditionally.
5. Phase 5 records are never mutated.
6. Methodology disclosure is complete and verbatim in all formats.

---

## 2. Test Suite Structure

```
tests/
├── unit/
│   ├── deterministic_reporting/
│   │   ├── test_models.py                    # DTO schema validation
│   │   ├── test_builder.py                   # ReportBuilder unit tests
│   │   ├── test_builder_mapping_fidelity.py  # Mapping fidelity regression test (see Section 3.3)
│   │   ├── test_engine.py                    # Pipeline logic, gate enforcement
│   │   ├── test_publisher.py                 # S3 serialization/deserialization
│   │   ├── test_repository.py                # DynamoDB record construction
│   │   ├── test_formatters_markdown.py       # MarkdownFormatter output
│   │   ├── test_formatters_pdf.py            # PdfFormatter output
│   │   └── test_engine_no_phase5_mutation.py # Phase 5 non-mutation invariant
│   ├── test_phase6_report_contract.py        # DTO compatibility gate test
│   └── test_phase7_consumer_contract.py      # Phase 7 compatibility gate test
└── integration/
    └── deterministic_reporting/
        ├── test_report_generation_pipeline.py  # End-to-end with real S3 + DynamoDB
        └── test_cli_report_commands.py         # CLI command integration
```

---

## 3. Contract Tests

### 3.1 Phase 6 Report Compatibility Gate (`test_phase6_report_contract.py`)

This test uses a known Phase 5 intelligence artifact fixture and validates the resulting `ReleaseConfidenceReport` DTO. It is the gating test for Phase 6 implementation changes.

**Must cover:**

- All stable DTO fields from `docs/architecture/phase_6_deterministic_reporting_technical_design.md` Section 5.4 are present with correct types.
- `report_version = "report_v1"`.
- `intelligence_version = "intel_v1"` on the `intelligence_provenance` section.
- `executive_summary.score_label` is present and is a member of `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}`.
- `executive_summary.score_label_description` is present and matches the bounded mapping in `constants.py` for the given `score_label`.
- `executive_summary.composite_score_value` is in `[0.0, 1.0]` with exactly 3 decimal places.
- `executive_summary.audit_success_rate` is in `[0.0, 1.0]` with exactly 3 decimal places.
- `composite_score` section carries Phase 5 component_breakdown with all four layers present (reliability, stability, burst, consistency).
- `endpoints` array is sorted in lexicographic ascending order by `endpoint_id`.
- Each `endpoints[*].stability_analysis.methodology_trace` is non-empty.
- Each `endpoints[*].burst_analysis.methodology_trace` is non-empty.
- Each `endpoints[*].consistency_analysis.methodology_trace` is non-empty.
- `methodology_disclosure` is present and all sub-fields are non-empty.
- `methodology_disclosure.limitations` is non-empty.
- `input_lineage.aggregate_set_hash` is present and matches the fixture.
- JSON serialization is byte-identical for two calls with identical Phase 5 fixture input.

**Failure of this test blocks Phase 6 implementation changes.**

---

### 3.3 Builder Mapping Fidelity Regression Test (`test_builder_mapping_fidelity.py`)

This test validates the one-to-one mapping between the Phase 5 intelligence artifact and the `ReleaseConfidenceReport` DTO. It is designed to catch field mapping regressions — cases where the wrong source field is copied into a DTO field — that would not be caught by presence-and-type contract tests. This test is part of the mandatory Phase 6 regression suite and must pass for all merges to main.

**Purpose distinction:**
- `test_phase6_report_contract.py` — validates that fields are present and correctly typed (contract)
- `test_builder.py` — validates builder logic and edge cases
- `test_builder_mapping_fidelity.py` — validates that the correct Phase 5 source field is mapped to each DTO target field (mapping correctness)

**Structure:** The test uses a Phase 5 intelligence artifact fixture with distinct, non-repeating values for every field, so that any mapping transposition is detectable. The fixture is designed so that no two sibling fields share the same value.

**Must cover all Phase 5 pass-through mappings:**

| DTO Field | Expected Phase 5 Source | Mapping Rule |
| --- | --- | --- |
| `intelligence_provenance.intelligence_version` | `artifact["intelligence_version"]` | Direct |
| `intelligence_provenance.intelligence_job_id` | `artifact["intelligence_job_id"]` | Direct |
| `intelligence_provenance.client_id` | `artifact["client_id"]` | Direct |
| `intelligence_provenance.audit_id` | `artifact["audit_id"]` | Direct |
| `intelligence_provenance.audit_execution_id` | `artifact["audit_execution_id"]` | Direct |
| `intelligence_provenance.config_version` | `artifact["config_version"]` | Direct |
| `intelligence_provenance.aggregation_version` | `artifact["aggregation_version"]` | Direct |
| `intelligence_provenance.aggregate_set_hash` | `artifact["composite_score"]["aggregate_set_hash"]` | Via composite_score |
| `executive_summary.score_label` | `artifact["composite_score"]["score_label"]` | Direct |
| `executive_summary.composite_score_value` | `artifact["composite_score"]["value"]` | Direct |
| `executive_summary.endpoint_count` | `artifact["composite_score"]["endpoint_count"]` | Direct |
| `executive_summary.audit_success_rate` | `artifact["audit_reliability_summary"]["audit_success_rate"]` | Direct |
| `executive_summary.total_executions` | `artifact["audit_reliability_summary"]["total_executions"]` | Direct |
| `audit_reliability_overview.total_executions` | `artifact["audit_reliability_summary"]["total_executions"]` | Direct |
| `audit_reliability_overview.total_pass` | `artifact["audit_reliability_summary"]["total_pass"]` | Direct |
| `audit_reliability_overview.total_fail` | `artifact["audit_reliability_summary"]["total_fail"]` | Direct |
| `audit_reliability_overview.total_timeout` | `artifact["audit_reliability_summary"]["total_timeout"]` | Direct |
| `audit_reliability_overview.total_network_failure` | `artifact["audit_reliability_summary"]["total_network_failure"]` | Direct |
| `audit_reliability_overview.audit_success_rate` | `artifact["audit_reliability_summary"]["audit_success_rate"]` | Direct |
| `audit_reliability_overview.audit_latency_mean_ms` | `artifact["audit_reliability_summary"]["audit_latency_mean_ms"]` | Direct |
| `audit_reliability_overview.audit_latency_p95_ms` | `artifact["audit_reliability_summary"]["audit_latency_p95_ms"]` | Direct |
| `audit_reliability_overview.audit_latency_p99_ms` | `artifact["audit_reliability_summary"]["audit_latency_p99_ms"]` | Direct |
| `audit_reliability_overview.source_field_refs` | `artifact["audit_reliability_summary"]["source_field_refs"]` | Verbatim |
| `composite_score.value` | `artifact["composite_score"]["value"]` | Direct |
| `composite_score.score_label` | `artifact["composite_score"]["score_label"]` | Direct |
| `composite_score.aggregate_set_hash` | `artifact["composite_score"]["aggregate_set_hash"]` | Direct |
| `composite_score.component_breakdown` | `artifact["composite_score"]["component_breakdown"]` | Verbatim |
| `input_lineage` (all sub-fields) | `artifact["input_lineage"]` | Verbatim |
| `methodology_disclosure` (all sub-fields) | `artifact["methodology_disclosure"]` | Verbatim |
| Per-endpoint `reliability_metrics` (all fields) | `artifact["endpoints"][*]["reliability_metrics"]` | Verbatim per endpoint |
| Per-endpoint `stability_analysis` (labels + trace) | `artifact["endpoints"][*]["stability_analysis"]` | Verbatim per endpoint |
| Per-endpoint `burst_analysis` (labels + trace) | `artifact["endpoints"][*]["burst_analysis"]` | Verbatim per endpoint |
| Per-endpoint `consistency_analysis` (label + trace) | `artifact["endpoints"][*]["consistency_analysis"]` | Verbatim per endpoint |
| Per-endpoint `endpoint_score` (all fields) | `artifact["endpoints"][*]["endpoint_score"]` | Verbatim per endpoint |

**Verbatim mapping rule:** For sections designated "Verbatim", the test asserts `dto_section.model_dump() == artifact_section` after JSON round-trip normalization. No individual sub-field assertion is required; the dictionary equality check is sufficient to catch any transposition or omission.

**Distinct-value fixture requirement:** The fixture must ensure that `total_pass != total_fail != total_timeout != total_network_failure`, that per-endpoint scores are all distinct, and that `composite_score.value != endpoint_score.composite_score` for at least one endpoint. This makes transposition detectable.

**Failure of this test blocks Phase 6 implementation merges.**

---

### 3.2 Phase 7 Consumer Contract Gate (`test_phase7_consumer_contract.py`)

This test validates that all stable fields defined in `docs/architecture/phase_6_phase7_consumer_contract.md` Section 3 are present and correctly typed in the Phase 6 report artifact output.

**Must cover:**

- All `ReportMetadata` stable DynamoDB field schemas from Section 3.1 of the Phase 7 consumer contract.
- All S3 artifact top-level sections from Section 3.2.
- All per-endpoint sub-sections.
- All `methodology_disclosure` sub-fields.
- `score_label` bounded value set membership.
- `score_label_description` bounded value set membership.
- `composite_score.value` range `[0.0, 1.0]`.
- Numeric precision: 3 decimal places for all score fields.
- `endpoints` array lexicographic sort order.

**Failure of this test blocks Phase 6 implementation changes.**

---

## 4. Unit Tests

### 4.1 `test_models.py` — DTO Schema Validation

| Test Case | Description |
| --- | --- |
| Valid DTO from complete Phase 5 fixture | Pydantic model validates without error |
| Missing `report_id` | Pydantic raises `ValidationError` |
| Missing `methodology_disclosure` | Pydantic raises `ValidationError` |
| Missing `endpoints` | Pydantic raises `ValidationError` |
| `composite_score_value` out of range | Pydantic raises `ValidationError` if validator enforces `[0.0, 1.0]` |
| `score_label` not in bounded set | Pydantic raises `ValidationError` if validator enforces bounded set |
| `report_version` not `report_v1` | Pydantic raises `ValidationError` if validator enforces constant |

---

### 4.2 `test_builder.py` — ReportBuilder

| Test Case | Description |
| --- | --- |
| Full artifact → DTO construction | All Phase 5 fields present in output DTO |
| `score_label` faithfully carried | `executive_summary.score_label` matches Phase 5 `composite_score.score_label` |
| `score_label_description` correct | Matches bounded mapping in `constants.py` for given `score_label` |
| Methodology disclosure verbatim | `methodology_disclosure` in DTO byte-matches Phase 5 fixture block |
| Input lineage verbatim | `input_lineage` in DTO matches Phase 5 fixture |
| Endpoint ordering | `endpoints` sorted lexicographically by `endpoint_id` |
| Single endpoint artifact | Single-endpoint DTO correct, no array errors |
| `source_field_refs` carried | All `reliability_metrics.source_field_refs` present in DTO |
| All methodology_trace fields present | Stability, burst, consistency traces all non-empty |
| `generated_at` from parameter, not datetime.now() | Builder uses passed-in timestamp; not system clock |
| Determinism: two calls with same input | Identical DTO output (excluding `report_id` if generated inside builder) |
| Builder does not call Phase 4 reads | No `#AGG#` or `#AGGJOB#` DynamoDB reads occur |
| Builder does not call Phase 5 DynamoDB writes | No `#INTEL#` or `#INTJOB#` DynamoDB writes occur |

---

### 4.3 `test_engine.py` — Generation Pipeline

| Test Case | Description |
| --- | --- |
| Happy path: gate passes, new report | Complete pipeline produces `ReportMetadata.status = COMPLETE` |
| Gate failure: `IntelligenceMetadata` absent | `INTELLIGENCE_NOT_COMPLETE` error; no `ReportJob` written |
| Gate failure: `IntelligenceMetadata.status = IN_PROGRESS` | `INTELLIGENCE_NOT_COMPLETE` error; no `ReportJob` written |
| Gate failure: `IntelligenceMetadata.status = FAILED` | `INTELLIGENCE_NOT_COMPLETE` error; no `ReportJob` written |
| Gate failure: `IntelligenceMetadata.status = PENDING` | `INTELLIGENCE_NOT_COMPLETE` error |
| Idempotency: existing `COMPLETE` without `--force` | `REPORT_ALREADY_COMPLETE` error; no new write |
| Idempotency: existing `COMPLETE` with `--force` | New `report_job_id` generated; new S3 artifact written |
| S3 write failure | `ReportJob.status = FAILED`; `ReportMetadata.status = FAILED`; `failure_stage` set |
| DynamoDB write failure on `PENDING` | `ReportJob` write failure surfaces to caller |
| `FAILED` state on pipeline exception | Both `ReportJob` and `ReportMetadata` transition to `FAILED` |
| `generation_count` increments on force | `ReportMetadata.generation_count` = `n+1` after force re-generation |
| `created_at` not updated on force | `ReportMetadata.created_at` unchanged on force re-generation |

---

### 4.4 `test_publisher.py` — S3 Serialization

| Test Case | Description |
| --- | --- |
| Serialize DTO → JSON string | Valid JSON; all sections present |
| JSON sort_keys consistent | Same DTO → identical JSON string on repeat calls |
| `sort_keys=True` applied | Field ordering is canonical alphabetical |
| Deserialize JSON → DTO | Round-trip produces structurally identical DTO |
| Score fields at 3 decimal places | All numeric score fields have exactly 3 decimal places |
| S3 key construction | Key follows expected pattern with all components |
| S3 artifact content matches input DTO | Byte-for-byte match after write + read round-trip |

---

### 4.5 `test_repository.py` — DynamoDB Records

| Test Case | Description |
| --- | --- |
| `ReportJob` PK/SK construction | PK = `CLIENT#{client_id}`; SK = `AUDIT#{id}#RPTJOB#{id}` |
| `ReportMetadata` PK/SK construction | Correct full SK with all version components |
| `record_type = report_job` | `ReportJob` record has correct `record_type` |
| `record_type = report_metadata` | `ReportMetadata` record has correct `record_type` |
| `generation_count = 1` on first write | Initial metadata record has `generation_count = 1` |
| Status transitions write correct fields | `COMPLETE` write includes `s3_artifact_ref`, `report_id`, `score_label` |
| Phase 5 SK never written | No write to any SK containing `#INTEL#` or `#INTJOB#` |
| Phase 4 SK never written | No write to any Phase 4-namespaced SK |

---

### 4.6 `test_formatters_markdown.py` — Markdown Formatter

| Test Case | Description |
| --- | --- |
| All required sections present | Header, Executive Summary, Release Confidence Score, Audit Reliability Overview, Per-Endpoint Analysis, Methodology Disclosure, Evidence Lineage, Report Provenance |
| Methodology disclosure verbatim | All `methodology_disclosure` field values appear literally in Markdown output |
| Limitations rendered | Each `limitations` entry appears in Markdown |
| Endpoint ordering in Markdown | Endpoints appear in lexicographic order by `endpoint_id` |
| No `datetime.now()` in formatter | Markdown `generated_at` sourced from DTO field only |
| All four component layers present | Reliability, stability, burst, consistency appear in score section |
| Score values match DTO | Composite score, per-endpoint scores not reformatted beyond 3 decimal places |
| `score_label_description` rendered | Appears in Executive Summary section |
| Determinism: two renders of same DTO | Identical Markdown output |
| No Phase 5 re-derivation | Formatter reads only DTO fields; no computation |

---

### 4.7 `test_formatters_pdf.py` — PDF Formatter

| Test Case | Description |
| --- | --- |
| Valid PDF bytes returned | Output is valid PDF byte sequence |
| No exceptions on standard DTO | Rendering completes without error |
| Methodology limitations present | Limitations text present in PDF content |
| Score label present | `score_label` text present in PDF content |
| Determinism within renderer version | Same DTO + same renderer version → same PDF bytes |
| No Phase 5 re-derivation | Formatter reads only DTO fields |

---

### 4.8 `test_engine_no_phase5_mutation.py` — Phase 5 Non-Mutation Invariant

| Test Case | Description |
| --- | --- |
| `repository.py` write methods list | All write methods target only `#RPTJOB#` or `#RPT#...#META` sort keys |
| No `IntelligenceMetadata` write | Grep/AST check: no `#INTEL#...#META` SK in write paths |
| No `IntelligenceJob` write | Grep/AST check: no `#INTJOB#` SK in write paths |
| No Phase 4 SK in write paths | Grep/AST check: no `#AGG#`, `#AGGJOB#`, `#SET` in write paths |

**This invariant must be covered unconditionally.**

---

## 5. Integration Tests

### 5.1 `test_report_generation_pipeline.py`

Integration tests using real DynamoDB (localstack) and real S3 (localstack):

| Test Case | Description |
| --- | --- |
| Full pipeline: Phase 5 fixture → complete report | `ReportMetadata.status = COMPLETE`; S3 artifact exists and valid |
| S3 artifact deserializable | Artifact JSON deserializes back to `ReleaseConfidenceReport` |
| `score_label` on metadata matches artifact | DynamoDB summary field matches S3 artifact value |
| `s3_artifact_ref` points to readable object | Key navigable and content consistent |
| Force re-generation produces new artifact | New `report_job_id` in S3 key; old artifact preserved |
| `generation_count` increments | After force re-gen, `generation_count = 2` |

---

### 5.2 `test_cli_report_commands.py`

Integration tests for CLI commands:

| Command | Test Case |
| --- | --- |
| `generate report` | Happy path; `ReportMetadata.status = COMPLETE` after |
| `generate report` (gate fail) | Correct error message and exit code |
| `generate report` (idempotent) | No re-generation without `--force`; correct message |
| `generate report --force` | New artifact generated; `generation_count` incremented |
| `retrieve report-status` | Displays status, score_label, report_job_id |
| `retrieve report-summary` | Displays executive summary fields |
| `retrieve report-endpoints` | All endpoints displayed with scores |
| `retrieve report-methodology` | Full methodology disclosure displayed |
| `retrieve report-lineage` | Lineage fields including `aggregate_set_hash` displayed |
| `retrieve report-json` | Full JSON artifact output; parseable |
| `retrieve report-markdown` | Full Markdown output; all sections present |
| Provenance envelope present | All retrieve commands display `report_id`, `report_version`, `audit_id`, `generated_at` |

---

## 6. Acceptance Criteria Coverage

| Acceptance Criterion | Covered By |
| --- | --- |
| Phase 5 conclusions faithfully in JSON artifact | `test_phase6_report_contract.py`; `test_builder.py` |
| Phase 5 conclusions faithfully in Markdown | `test_formatters_markdown.py` |
| Phase 5 conclusions faithfully in PDF | `test_formatters_pdf.py` |
| No Phase 5 re-derivation | `test_engine_no_phase5_mutation.py`; `test_builder.py` |
| Deterministic JSON for identical inputs | `test_phase6_report_contract.py`; `test_publisher.py` |
| Prerequisite gate unconditional | `test_engine.py` gate failure cases |
| Methodology disclosure verbatim | `test_phase6_report_contract.py`; `test_formatters_markdown.py` |
| Limitations verbatim | `test_formatters_markdown.py`; `test_formatters_pdf.py` |
| Phase 5 records never mutated | `test_engine_no_phase5_mutation.py` |
| `ReportMetadata.status = COMPLETE` reliable for Phase 7 | `test_phase7_consumer_contract.py`; `test_report_generation_pipeline.py` |
| Retrieval CLI read-only | `test_cli_report_commands.py`; `test_engine_no_phase5_mutation.py` |
| `report_version = report_v1` on all artifacts | `test_phase6_report_contract.py`; `test_models.py` |
| `score_label_description` bounded mapping | `test_phase6_report_contract.py`; `test_builder.py` |

---

## 7. Phase 6.8 Validation Campaign

The Phase 6.8 Validation Campaign is a live end-to-end validation against Phase 5 intelligence artifacts already persisted from the Phase 5.8 validation campaign.

### Campaign Objectives

1. Confirm `rcp generate report` runs to completion against real Phase 5 intelligence artifacts.
2. Confirm the canonical JSON artifact is present and valid in S3.
3. Confirm all Phase 5 intelligence conclusions appear faithfully in the JSON artifact.
4. Confirm Markdown report renders correctly and all sections are present.
5. Confirm PDF report renders and is non-empty.
6. Confirm all `retrieve report-*` commands return correct data.
7. Confirm `ReportMetadata.status = COMPLETE` is set in DynamoDB.
8. Confirm force re-generation produces a new artifact and increments `generation_count`.

### Campaign Prerequisites

- Phase 5.8 validation artifacts must be accessible (Phase 5 `IntelligenceMetadata.status = COMPLETE`).
- Platform S3 bucket and DynamoDB table accessible in `dev` or `staging` stage.

### Campaign Acceptance Criteria

All campaign objectives satisfied without error. Evidence recorded in campaign document.

---

## 8. Regression Criteria

Changes to any Phase 6 module that affect the following require re-running the full unit test suite:

- `models.py` — DTO schema changes
- `builder.py` — field mapping changes
- `constants.py` — `score_label_description` mapping changes or `REPORT_VERSION` changes
- `publisher.py` — serialization format changes
- `formatters/markdown.py` — section changes
- `formatters/pdf.py` — rendering changes

Changes to `repository.py` write paths additionally require `test_engine_no_phase5_mutation.py` to pass.

**`test_phase6_report_contract.py` and `test_phase7_consumer_contract.py` must pass for all merges to main.**

---

## 9. Traceability

- Product Spec: `docs/product/phase_6_deterministic_reporting_product_spec.md`
- Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 5 → Phase 6 Consumer Contract: `docs/architecture/phase_5_phase6_consumer_contract.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 5 QA Plan (predecessor): `docs/qa/phase_5_reliability_intelligence_test_plan.md`
