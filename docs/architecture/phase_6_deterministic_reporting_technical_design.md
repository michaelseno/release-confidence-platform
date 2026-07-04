# Technical Design

## Phase 6 — Deterministic Reporting

---

## 1. Feature Overview

Phase 6 is the Deterministic Reporting layer of the Release Confidence Platform. It consumes immutable Phase 5 intelligence artifacts and produces deterministic Release Confidence Reports in multiple output formats (JSON, Markdown, PDF) via a Canonical Report DTO architecture.

Phase 6 occupies a specific position in the platform pipeline:

```
Phase 1/2/3 (Execution, Evidence Capture, Finalization)
    → Phase 4 (Aggregation — produces facts)
        → Phase 5 (Reliability Intelligence — produces interpretation)
            → Phase 6 (Deterministic Reporting — produces reports)
                → Phase 7 (Audit Platform Integrity — certifies audit process)
```

**Constitutional boundary statement:** "Intelligence owns interpretation. Phase 6 owns reporting."

Phase 6 reads Phase 5 intelligence artifacts. Phase 6 writes Phase 6 report artifacts. Phase 6 never mutates any Phase 5 record. Phase 6 never reads Phase 4 aggregation artifacts or Phase 1–3 raw evidence. These boundaries are unconditional and cannot be waived.

This document covers all Phase 6 subphases:

| Subphase | Scope |
| --- | --- |
| 6.1 | Documentation — product spec, this technical design, report schema, Phase 7 consumer contract, QA plan |
| 6.2 | Report Model & Canonical DTO — `ReleaseConfidenceReport` Pydantic model, constants, versioning |
| 6.3 | Report Generation Engine — `ReportBuilder`, prerequisite gate, pipeline, status lifecycle |
| 6.4 | Report Persistence — S3 artifact write, DynamoDB `ReportJob` + `ReportMetadata` records |
| 6.5 | Markdown Formatter — `MarkdownFormatter` rendering from DTO |
| 6.6 | PDF Export — `PdfFormatter` rendering from DTO |
| 6.7 | Engineering Retrieval CLI — `retrieve report-*` operator commands |
| 6.8 | Validation Campaign — live validation against Phase 5 intelligence artifacts |

---

## 2. Product Requirements Summary

The following requirements from `docs/product/phase_6_deterministic_reporting_product_spec.md` govern this design:

| Requirement | Description |
| --- | --- |
| FR-P1 | Operator-invoked CLI with `IntelligenceMetadata.status = COMPLETE` prerequisite gate, idempotency, and status lifecycle |
| FR-P2 | Canonical Report DTO: format-neutral, faithful Phase 5 pass-through with bounded presentation layer |
| FR-P3 | Report persistence: immutable S3 JSON artifact + DynamoDB metadata/status records; no Phase 5 mutation |
| FR-P4 | JSON export: canonical JSON artifact is the serialized DTO; byte-identical for identical inputs |
| FR-P5 | Markdown formatter: full-section Markdown report rendered from DTO; deterministic |
| FR-P6 | PDF export: PDF document rendered from DTO; all content matches Markdown output |
| FR-P7 | Engineering Retrieval CLI: seven read-only retrieval commands with provenance envelopes |
| NFR-1 | Determinism: byte-identical JSON artifact for identical Phase 5 inputs within `report_v1` |
| NFR-5 | Phase 5 non-mutation: unconditional constitutional invariant |
| NFR-6 | No Phase 4 or raw evidence access |
| NFR-7 | Report schema stability within `report_v1` |
| NFR-9 | Formatter purity: no business logic in formatters |

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-P1a — CLI invocation | `rcp generate report` command in `deterministic_reporting/commands.py` |
| FR-P1b — IntelligenceMetadata gate | Enforced at pipeline entry in `engine.py` via `repository.py` DynamoDB read before any DTO construction |
| FR-P1c — Idempotency | `ReportMetadata` DynamoDB record checked before generation; `--force` required to re-generate |
| FR-P1d — Status lifecycle | `ReportJob` DynamoDB record with `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED` states |
| FR-P1e — report_version | `report_v1` carried on all artifacts; defined in `constants.py` |
| FR-P2a — Canonical DTO | `ReleaseConfidenceReport` Pydantic model in `models.py` |
| FR-P2b — Formatter input contract | All formatters accept `ReleaseConfidenceReport` only; no direct Phase 5 access from formatters |
| FR-P2c — Faithful Phase 5 pass-through | `builder.py`: reads S3 intelligence artifact; maps all fields into DTO without transformation |
| FR-P2d — Report identity | `identity.py`: `report_id` generation (`report_` prefix); `generated_at`, `generator_version` |
| FR-P2e–f — ExecutiveSummary | Bounded `score_label_description` mapping in `constants.py`; never substitutes `score_label` |
| FR-P2g — Methodology verbatim | `MethodologyDisclosure` section carries Phase 5 block without modification |
| FR-P2h — Input lineage verbatim | `InputLineageSection` carries Phase 5 lineage block without modification |
| FR-P3a–b — S3 persistence | `publisher.py`: immutable write; key includes `report_job_id` |
| FR-P3c–d — DynamoDB records | `repository.py`: `ReportJob` + `ReportMetadata` write/update paths |
| FR-P3e — Phase 5 non-mutation | `repository.py` write methods target only Phase 6 sort key namespaces |
| FR-P4 — JSON export | `json.dumps(report.model_dump(), sort_keys=True, indent=2)` via `publisher.py` |
| FR-P5 — Markdown formatter | `formatters/markdown.py`: `MarkdownFormatter.render(report) -> str` |
| FR-P6 — PDF formatter | `formatters/pdf.py`: `PdfFormatter.render(report) -> bytes` |
| FR-P7 — Retrieval CLI | `commands.py` (retrieve group): DynamoDB for status; S3 artifact for content |
| NFR-1 — Determinism | Python `Decimal` precision; `sort_keys=True`; no `datetime.now()` in DTO construction; report_id generated once per invocation |
| NFR-5 — Phase 5 non-mutation | `repository.py` contains no write methods targeting Phase 5 sort key prefixes |
| NFR-6 — No raw evidence access | `repository.py` Phase 5 reads limited to the single `IntelligenceMetadata` pattern |
| NFR-9 — Formatter purity | Formatters receive only `ReleaseConfidenceReport`; enforced by type signatures |

---

## 4. Technical Scope

### Current Technical Scope

- New `deterministic_reporting/` module under `src/release_confidence_platform/`.
- CLI `generate report` command and seven `retrieve report-*` commands.
- DynamoDB: two new record types (`ReportJob`, `ReportMetadata`).
- S3: immutable JSON report artifact written to a Phase 6-namespaced key prefix (`reports/`).
- Canonical Report DTO (`ReleaseConfidenceReport`) as the single format-neutral representation.
- Report generation pipeline: prerequisite gate, DTO construction, S3 persistence, DynamoDB lifecycle.
- `MarkdownFormatter` and `PdfFormatter`.
- Phase 7 consumer contract document.
- Unit and integration tests for all modules.
- Phase 6.8 validation campaign against Phase 5 intelligence artifacts.

### Out of Scope

- Reliability intelligence derivation or re-scoring.
- Event-driven Lambda trigger from `IntelligenceMetadata` (deferred).
- Phase 7 Audit Platform Integrity implementation.
- Customer portal or web interface.
- Report comparison or historical trending.

---

## 5. Canonical Report DTO Architecture

### 5.1 Architecture Statement

The Canonical Report DTO is the central architectural commitment of Phase 6.

```
Phase 5 Intelligence Artifact (Immutable Source of Truth)
                    │
                    ▼
          Canonical Report DTO
          (ReleaseConfidenceReport)
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
     JSON       Markdown       PDF
```

**Principles governing this architecture:**

1. **Single transformation point.** The `ReportBuilder` is the only code that reads the Phase 5 intelligence artifact and constructs the DTO. Formatters are consumers, not processors.

2. **Formatter purity.** No formatter may contain business logic, label derivation, scoring formulas, or conditional intelligence conclusions. Formatters perform structural rendering only.

3. **Format independence.** JSON, Markdown, and PDF contain identical information. The only differences are structural (markup, layout, typography). Any information present in one format must be present in all formats.

4. **Determinism.** The same Phase 5 intelligence input must produce the same DTO, which must produce the same JSON serialization. Markdown and PDF determinism is guaranteed within a fixed renderer version.

5. **DTO is the persisted artifact.** The JSON export IS the serialized DTO. There is no secondary JSON representation. S3 stores the serialized DTO; retrieving the S3 artifact reconstructs the full DTO.

### 5.2 DTO Stratification

The `ReleaseConfidenceReport` DTO is explicitly stratified into layers that make the boundary between Phase 6-generated content and Phase 5 pass-through content explicit:

```
ReleaseConfidenceReport
│
├── Layer 1: Report Identity (Phase 6-generated)
│   report_id, report_version, generated_at, generator_version
│
├── Layer 2: Intelligence Provenance (Phase 5 pass-through, no transformation)
│   intelligence_version, intelligence_job_id, client_id, audit_id,
│   audit_execution_id, config_version, aggregation_version,
│   aggregate_set_hash, intelligence_completed_at
│
├── Layer 3: Executive Summary (Phase 5 conclusions + Phase 6 presentation layer)
│   score_label [Phase 5], composite_score_value [Phase 5],
│   endpoint_count [Phase 5], audit_success_rate [Phase 5],
│   score_label_description [Phase 6 presentation — fixed mapping in constants.py]
│
├── Layer 4: Analytical Sections (Phase 5 conclusions, faithfully carried through)
│   ├── audit_reliability_overview [from Phase 5 audit_reliability_summary]
│   ├── composite_score [from Phase 5 composite_score]
│   ├── endpoints[] [from Phase 5 endpoints[]]
│   └── input_lineage [from Phase 5 input_lineage]
│
└── Layer 5: Methodology Disclosure (verbatim from Phase 5, no modification)
    methodology_disclosure, limitations
```

The explicit stratification rule:
- **Layers 2, 4, and 5** may only carry Phase 5 field values verbatim. No Phase 6 code may compute, derive, or substitute any value in these layers.
- **Layer 1** is purely Phase 6 metadata about the report artifact itself.
- **Layer 3** is a hybrid: `score_label`, `composite_score_value`, `endpoint_count`, and `audit_success_rate` are Phase 5 pass-through values; `score_label_description` is a Phase 6 presentation addition. The description is a fixed, bounded string in `constants.py` and must never substitute or modify the `score_label` value.

### 5.3 `score_label_description` Bounded Mapping

Within `report_v1`, the following mapping is fixed in `constants.py` and may not be altered without a `report_version` increment:

| `score_label` | `score_label_description` |
| --- | --- |
| `HIGH_CONFIDENCE` | Reliability indicators across all assessed endpoints are strong. The observed evidence does not indicate material reliability concerns for the audited release scope. |
| `MODERATE_CONFIDENCE` | Reliability indicators are mixed or partially insufficient. Review the per-endpoint analysis for areas requiring attention before release. |
| `LOW_CONFIDENCE` | Reliability indicators indicate meaningful reliability risk. Review the per-endpoint analysis and methodology disclosure for full evidence detail. |

This mapping is a presentation layer only. It does not constitute a release recommendation. Operators and customers draw release conclusions from the score_label, score value, and per-endpoint findings. Phase 6 does not advise release approval or rejection.

### 5.4 DTO Field Definitions

#### Identity (`ReportIdentity`)

| Field | Type | Source | Description |
| --- | --- | --- | --- |
| `report_id` | String | Phase 6 generated | Opaque report identifier; prefix `report_`; UUID hex |
| `report_version` | String | Phase 6 constant | `report_v1`; fixed from `constants.py` |
| `generated_at` | String | Phase 6 generated | UTC ISO-8601 timestamp at DTO construction time |
| `generator_version` | String | Phase 6 generated | Platform version string |

#### Intelligence Provenance (`IntelligenceProvenance`)

All fields are direct pass-through from `IntelligenceMetadata` DynamoDB record.

| Field | Type | Source | Description |
| --- | --- | --- | --- |
| `intelligence_version` | String | Phase 5 | `intel_v1` |
| `intelligence_job_id` | String | Phase 5 | Job ID of the COMPLETE generation event |
| `client_id` | String | Phase 5 | Validated client identifier |
| `audit_id` | String | Phase 5 | Validated audit identifier |
| `audit_execution_id` | String | Phase 5 | Durable execution identity |
| `config_version` | String | Phase 5 | Configuration version |
| `aggregation_version` | String | Phase 5 | Phase 4 aggregation version consumed |
| `aggregate_set_hash` | String | Phase 5 | Immutable lineage link to Phase 4 |
| `intelligence_completed_at` | String | Phase 5 | UTC ISO-8601 completion timestamp |

#### Executive Summary (`ExecutiveSummary`)

| Field | Type | Source | Description |
| --- | --- | --- | --- |
| `score_label` | String | Phase 5 | `HIGH_CONFIDENCE` \| `MODERATE_CONFIDENCE` \| `LOW_CONFIDENCE` |
| `composite_score_value` | Number | Phase 5 | Decimal in `[0.0, 1.0]`, 3 decimal places |
| `endpoint_count` | Number | Phase 5 | Number of endpoints assessed |
| `audit_success_rate` | Number | Phase 5 | Audit-level success rate; 3 decimal places |
| `total_executions` | Number | Phase 5 | Total raw execution count |
| `score_label_description` | String | Phase 6 presentation | Fixed description from bounded mapping in `constants.py` |

#### Audit Reliability Overview (`AuditReliabilityOverview`)

Direct pass-through from Phase 5 `audit_reliability_summary`. All fields carry Phase 5 values verbatim.

| Field | Type | Description |
| --- | --- | --- |
| `total_executions` | Number | Total raw result records |
| `total_pass` | Number | PASS count |
| `total_fail` | Number | Non-PASS count |
| `total_timeout` | Number | TIMEOUT classification count |
| `total_network_failure` | Number | CONNECTION_ERROR count |
| `audit_success_rate` | Number | Audit-level success rate; 3 decimal places |
| `endpoint_count` | Number | Distinct endpoint count |
| `audit_latency_mean_ms` | Number or null | Audit-level mean latency |
| `audit_latency_p95_ms` | Number or null | Audit-level p95 latency |
| `audit_latency_p99_ms` | Number or null | Audit-level p99 latency |
| `source_field_refs` | Map | Evidence trace from Phase 5 |

#### Composite Score Section (`CompositeScoreSection`)

Direct pass-through from Phase 5 `composite_score`. All fields carry Phase 5 values verbatim.

| Field | Type | Description |
| --- | --- | --- |
| `value` | Number | `[0.0, 1.0]`, 3 decimal places |
| `score_label` | String | Bounded confidence label |
| `intelligence_version` | String | `intel_v1` |
| `aggregation_version` | String | Phase 4 version consumed |
| `aggregate_set_hash` | String | Lineage hash |
| `endpoint_count` | Number | Endpoints in composite rollup |
| `component_breakdown` | Map | Per-layer weighted contribution (reliability, stability, burst, consistency) |

#### Per-Endpoint Report Sections (`endpoints[]`)

Each element is a direct pass-through of the corresponding Phase 5 endpoint entry. All sub-sections carry Phase 5 values verbatim:

- `endpoint_id`
- `reliability_metrics` (all fields from Phase 5, including `source_field_refs`)
- `stability_analysis` (labels and full `methodology_trace`)
- `burst_analysis` (labels and full `methodology_trace`)
- `consistency_analysis` (label and full `methodology_trace`)
- `endpoint_score` (all score fields and `score_derivation`)

Ordering: canonical lexicographic ascending by `endpoint_id`, consistent with Phase 5 guarantee.

#### Input Lineage (`InputLineageSection`)

Direct pass-through from Phase 5 `input_lineage`. All fields carry Phase 5 values verbatim.

#### Methodology Disclosure (`MethodologyDisclosure`)

Direct pass-through from Phase 5 `methodology_disclosure`. Every field is carried verbatim without modification, summarization, or omission:
- `intelligence_version`
- `scoring` (all sub-fields)
- `stability_label_definitions`
- `burst_label_definitions`
- `consistency_label_definitions`
- `label_to_score_mapping`
- `limitations`

---

## 6. Module Structure

```
src/release_confidence_platform/
└── deterministic_reporting/
    ├── __init__.py
    ├── constants.py         # REPORT_VERSION, SCORE_LABEL_DESCRIPTIONS, report_job_id prefix
    ├── identity.py          # report_id and report_job_id generation
    ├── models.py            # ReleaseConfidenceReport Pydantic model and all sub-models
    ├── builder.py           # ReportBuilder: Phase 5 artifact → ReleaseConfidenceReport DTO
    ├── engine.py            # Generation pipeline: gate → builder → publisher → repository
    ├── publisher.py         # S3 artifact write (serialize DTO) and read (deserialize DTO)
    ├── repository.py        # DynamoDB ReportJob + ReportMetadata read/write
    └── formatters/
        ├── __init__.py
        ├── markdown.py      # MarkdownFormatter.render(report: ReleaseConfidenceReport) -> str
        └── pdf.py           # PdfFormatter.render(report: ReleaseConfidenceReport) -> bytes
```

CLI commands are registered in `commands.py` under the `rcp` Click group following existing platform CLI conventions.

---

## 7. Report Generation Pipeline

```
rcp generate report <args>
         │
         ▼
[1] Validate input identifiers (validate_identifier for all components)
         │
         ▼
[2] Read IntelligenceMetadata DynamoDB record
    → If absent or status != COMPLETE: abort with INTELLIGENCE_NOT_COMPLETE
    → This is the Phase 6 prerequisite gate (unconditional)
         │
         ▼
[3] Check ReportMetadata idempotency
    → If COMPLETE and not --force: abort with REPORT_ALREADY_COMPLETE
    → If --force: continue; a new report_job_id will be issued
         │
         ▼
[4] Write ReportJob DynamoDB record (status = PENDING)
    → New report_job_id generated per invocation
         │
         ▼
[5] Update ReportJob → IN_PROGRESS; Update/create ReportMetadata → IN_PROGRESS
         │
         ▼
[6] Read Phase 5 S3 intelligence artifact
    → Key obtained from IntelligenceMetadata.s3_artifact_ref
    → Phase 6 must not construct or guess the S3 key independently
         │
         ▼
[7] ReportBuilder.build(intelligence_artifact, report_job_id, generated_at)
    → Constructs ReleaseConfidenceReport DTO
    → All Phase 5 fields passed through verbatim
    → Phase 6 identity and presentation fields added
         │
         ▼
[8] Serialize DTO to canonical JSON (sort_keys=True, indent=2)
         │
         ▼
[9] Write JSON artifact to S3 (reports/ key prefix)
         │
         ▼
[10] Update ReportJob → COMPLETE; Update ReportMetadata → COMPLETE
     → Sets s3_artifact_ref, composite_score, score_label, report_id on ReportMetadata
         │
         ▼
[11] Display report summary to operator
```

**Error path:** Any exception between steps 4 and 10 results in `ReportJob → FAILED` and `ReportMetadata → FAILED` updates with `failure_stage` and `failure_reason` populated.

---

## 8. Report Retrieval Workflow

Retrieval commands follow a two-step read pattern matching Phase 5:

```
retrieve report-status  → GetItem: ReportMetadata DynamoDB (no S3 read)
retrieve report-summary → GetItem: ReportMetadata (for s3_artifact_ref) → S3 read
retrieve report-*       → GetItem: ReportMetadata (for s3_artifact_ref) → S3 read → extract section
retrieve report-json    → GetItem: ReportMetadata → S3 read → output full JSON
retrieve report-markdown → GetItem: ReportMetadata → S3 read → deserialize DTO → MarkdownFormatter.render()
```

All retrieval commands display a provenance envelope before section output:
```
Report ID:             report_xxxxxxxxxxxxxxxx
Report Version:        report_v1
Intelligence Version:  intel_v1
Audit ID:              audit_xxxxxxxx
Generated At:          2026-07-04T...Z
```

---

## 9. DynamoDB Schema Summary

Full schema definitions are in `docs/architecture/phase_6_report_schema.md`.

### ReportJob

- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#RPTJOB#{report_job_id}`
- Lifecycle: `PENDING → IN_PROGRESS → COMPLETE | FAILED`
- Immutable at terminal state

### ReportMetadata

- PK: `CLIENT#{client_id}`
- SK: `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META`
- Reflects current generation state
- Phase 7 prerequisite gate anchor (`status = COMPLETE`)
- Updated on each status transition and force re-generation

The `#RPT#` SK segment is reserved exclusively for Phase 6+ records. It does not overlap with Phase 5's `#INTEL#...#META` segment.

---

## 10. S3 Artifact Structure

```
reports/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{report_version}/{report_job_id}/artifact.json
```

**Example:**
```
reports/client_abc/audit_xyz/audexec_0b1c2d3e/agg_v1/intel_v1/report_v1/rptjob_4f5a6b7c8d9e0a1b2c3d4e5f/artifact.json
```

**Key properties:**
- `report_job_id` segment guarantees per-generation uniqueness.
- Force re-generation produces a new key; the previous artifact is preserved.
- `reports/` prefix does not overlap with `intelligence/` (Phase 5) or `raw-results/` (Phase 1/2).
- Phase 7 must use `ReportMetadata.s3_artifact_ref` to locate the artifact; it must not construct the key independently.

---

## 11. Report Schema Versioning

### Version Constants

| Constant | Value | Location |
| --- | --- | --- |
| `REPORT_VERSION` | `report_v1` | `constants.py` |
| `report_job_id` prefix | `rptjob_` | `constants.py` / `identity.py` |
| `report_id` prefix | `report_` | `constants.py` / `identity.py` |

### Versioning Rules

1. The `report_v1` DTO schema is immutable after Phase 6.1 HITL approval.
2. Structural changes to `ReleaseConfidenceReport` (field addition, removal, rename, type change) require a new `report_version` (e.g., `report_v2`).
3. New `report_version` records are written to distinct `ReportMetadata` sort keys (the `#RPT#{report_version}` segment changes). Existing `report_v1` records are never modified.
4. Changes to the `score_label_description` mapping also require a new `report_version`, as they alter the presentation layer semantics.
5. New formatters for new output types are non-breaking within `report_v1`.
6. Formatter rendering improvements (visual layout, typography) that do not change information content are non-breaking within `report_v1`.

### Compatibility Gate Test

`tests/unit/test_phase6_report_contract.py` is the compatibility gate test. It validates that the `ReleaseConfidenceReport` DTO:
- Contains all defined fields for a known Phase 5 fixture.
- Carries all Phase 5 analytical sections verbatim.
- Contains correct `report_version = report_v1`.
- Contains correct `score_label_description` for each `score_label` value.
- Has byte-identical JSON serialization for identical inputs.
- Has `methodology_disclosure` fully present and verbatim.

### Mapping Fidelity Regression Test

`tests/unit/deterministic_reporting/test_builder_mapping_fidelity.py` is the mapping fidelity regression gate. It validates the one-to-one mapping between the Phase 5 intelligence artifact and the `ReleaseConfidenceReport` DTO, using a fixture with distinct values for every field. It catches mapping transpositions — wrong source field copied into a DTO field — that would not be detected by contract presence tests.

The test covers all Phase 5 pass-through mappings including: intelligence provenance, executive summary (Phase 5 fields only), audit reliability overview, composite score, per-endpoint sections (reliability metrics, stability/burst/consistency labels and traces, endpoint score), input lineage, and methodology disclosure. For verbatim sections, dictionary equality after JSON normalization is used. See `docs/qa/phase_6_deterministic_reporting_test_plan.md` Section 3.3 for the full mapping table.

**Failure of this test blocks Phase 6 implementation merges.**

---

## 12. Determinism Guarantees

| Guarantee | Mechanism |
| --- | --- |
| JSON byte-identical for identical Phase 5 inputs | `sort_keys=True`; fixed `generated_at` passed from `engine.py` (not from builder); no `datetime.now()` inside `builder.py` |
| Endpoint ordering | Lexicographic ascending by `endpoint_id`, consistent with Phase 5 |
| Numeric precision | All scores carried as-is from Phase 5 Decimal-serialized strings; no re-rounding in Phase 6 |
| `score_label_description` | Fixed bounded mapping in `constants.py`; no dynamic text |
| Formatter output | No dynamic content in Markdown templates; no environment-dependent values |
| `report_id` uniqueness | Generated once per invocation in `engine.py`; passed into `builder.py` as a parameter |

---

## 13. Phase 7 Integration Boundary

Phase 7 (Audit Platform Integrity) consumes Phase 6 report artifacts as follows:

- **Prerequisite gate**: Phase 7 must require `ReportMetadata.status = COMPLETE` before accessing Phase 6 report content.
- **S3 artifact**: Phase 7 locates the report artifact via `ReportMetadata.s3_artifact_ref`.
- **Phase 7 may**: Read the canonical JSON report artifact. Read `ReportMetadata` summary fields.
- **Phase 7 must not**: Mutate any Phase 6 DynamoDB record or S3 artifact. Re-derive report content. Access Phase 5 or Phase 4 artifacts directly for reporting purposes.

Phase 7 produces its own separate Platform Integrity Certification artifact. The final customer-facing deliverable references both the Phase 6 report and the Phase 7 certification. Phase 6 is not responsible for producing or embedding Phase 7 certification content.

Full Phase 7 boundary specification: `docs/architecture/phase_6_phase7_consumer_contract.md`.

---

## 14. Formatter Architecture

### 14.1 JSON Formatter

The JSON export is the serialized `ReleaseConfidenceReport` DTO written to S3. There is no separate JSON formatter class. The serialization in `publisher.py` is:

```python
import json
artifact_json = json.dumps(report.model_dump(), sort_keys=True, indent=2)
```

All numeric score fields are carried as Python `float` values with 3 decimal place precision (inherited from Phase 5 serialization). The JSON artifact must pass the compatibility gate test.

### 14.2 Markdown Formatter (`formatters/markdown.py`)

`MarkdownFormatter.render(report: ReleaseConfidenceReport) -> str`

Report sections and order:

1. **Header** — audit_id, generated_at, report_id, report_version
2. **Executive Summary** — score_label, composite_score_value, score_label_description, endpoint_count, audit_success_rate
3. **Release Confidence Score** — composite score value, score_label, component breakdown table (reliability/stability/burst/consistency), aggregate_set_hash
4. **Audit Reliability Overview** — table of total_executions, total_pass, total_fail, latency summary
5. **Per-Endpoint Analysis** — one section per endpoint (sorted by endpoint_id):
   - Endpoint ID
   - Composite score and score derivation
   - Reliability metrics table
   - Stability analysis labels and methodology trace
   - Burst analysis labels and methodology trace
   - Consistency analysis label and methodology trace
6. **Methodology Disclosure** — verbatim rendering of all methodology_disclosure fields; limitations rendered as a bulleted list
7. **Evidence Lineage** — aggregate_set_hash, aggregation_job_id, source_raw_result_count, manifest_hash
8. **Report Provenance** — full intelligence_provenance block

No section may be omitted. No field values may be modified for readability.

### 14.3 PDF Formatter (`formatters/pdf.py`)

`PdfFormatter.render(report: ReleaseConfidenceReport) -> bytes`

The PDF formatter renders the `ReleaseConfidenceReport` DTO to PDF. Implementation options (to be finalized in Phase 6.6):

**Option A**: `MarkdownFormatter.render(report)` → Markdown → HTML (via `markdown` library) → PDF (via `weasyprint` or `reportlab`).

**Option B**: Direct PDF generation using `reportlab` with the DTO as input.

Option A is preferred for maintainability: the Markdown output already defines the canonical information structure. The PDF is a visual rendering of that same structure.

Determinism constraint: The PDF must be deterministic within a fixed renderer version and fixed template. Timestamp fields in the PDF must be sourced from the DTO `generated_at`, not from `datetime.now()` at render time.

---

## 15. Error Codes

Phase 6 defines the following structured error codes:

| Code | Condition |
| --- | --- |
| `INTELLIGENCE_NOT_COMPLETE` | `IntelligenceMetadata` record absent or `status != COMPLETE` |
| `REPORT_ALREADY_COMPLETE` | `ReportMetadata.status = COMPLETE` exists and `--force` not supplied |
| `S3_ARTIFACT_READ_FAILURE` | Phase 5 S3 artifact cannot be read via `s3_artifact_ref` |
| `S3_ARTIFACT_WRITE_FAILURE` | Phase 6 S3 artifact write fails |
| `REPORT_SCHEMA_VALIDATION_ERROR` | DTO construction fails Pydantic validation |
| `DYNAMODB_WRITE_FAILURE` | DynamoDB write fails for `ReportJob` or `ReportMetadata` |
| `FORMATTER_ERROR` | Markdown or PDF rendering fails |

---

## 16. Non-Negotiable Invariants

The following invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 6 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion.
2. Phase 6 shall never read Phase 4 aggregation artifacts directly for any reporting purpose.
3. Phase 6 shall never read raw execution evidence from Phase 1, Phase 2, Phase 3, or S3 raw result objects.
4. `IntelligenceMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 6 report generation.
5. Phase 6 shall never mutate any Phase 5 intelligence artifact, `IntelligenceMetadata` record, or `IntelligenceJob` record.
6. Phase 6 shall never relabel, redefine, or reweight Phase 5 intelligence conclusions.
7. The Canonical Report DTO is the only authorized input to all formatters. Formatters may not access Phase 5 or Phase 4 artifacts directly.
8. Intelligence owns interpretation. Phase 6 owns reporting.

---

## 17. Traceability

- Product Spec: `docs/product/phase_6_deterministic_reporting_product_spec.md`
- Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 5 → Phase 6 Consumer Contract: `docs/architecture/phase_5_phase6_consumer_contract.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 QA/Test Plan: `docs/qa/phase_6_deterministic_reporting_test_plan.md`
- Phase 5 Technical Design: `docs/architecture/phase_5_reliability_intelligence_technical_design.md`
- Phase 5 Schema: `docs/architecture/phase_5_reliability_intelligence_schema.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Sanitization Boundary ADR: `docs/architecture/adr_sanitization_boundary.md`
- Product Constitution: `RCP_Product_Strategy.md`
- Compatibility gate test: `tests/unit/test_phase6_report_contract.py`
