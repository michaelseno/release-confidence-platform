# Product Specification

## 1. Feature Overview

Phase 6 is the Deterministic Reporting layer of the Release Confidence Platform.

Its purpose is to consume the immutable Phase 5 intelligence artifacts produced by the Reliability Intelligence layer and translate them into deterministic, human-readable Release Confidence Reports. Phase 6 does not perform analysis. Every conclusion presented in a Phase 6 report is a faithful rendering of a pre-computed Phase 5 intelligence conclusion.

Phase 6 delivers:

- A Canonical Report DTO — a structured, format-neutral representation of the full Release Confidence Report, built deterministically from Phase 5 intelligence
- An immutable JSON report artifact persisted to S3 (the serialized Canonical Report DTO)
- Lightweight DynamoDB report metadata and status tracking
- A Markdown-formatted Release Confidence Report rendered from the Canonical DTO
- A PDF-formatted Release Confidence Report rendered from the Canonical DTO
- An operator CLI for report generation and retrieval
- A Phase 7 consumer contract defining the stable interface between Phase 6 reporting and Phase 7 Audit Platform Integrity verification

Phase 6 is not an autonomous system. For initial implementation, it is operator-invoked via CLI after Phase 5 intelligence generation is confirmed complete. All report content derives from Phase 5 intelligence artifacts. No Phase 4 aggregation artifacts or Phase 1–3 raw evidence is accessed directly.

Phase 6 is NOT any of the following:

- An intelligence or analysis layer (Phase 5)
- A scoring or reliability assessment layer (Phase 5)
- A dashboard or real-time visualization layer
- A monitoring or observability platform
- A CI/CD integration or gating mechanism (Phase 7)
- A customer portal or self-service interface
- An automated trigger for any downstream action
- A storage system for raw evidence or aggregation artifacts

### Backend / System Impact

- A new `deterministic_reporting/` module is introduced under `src/release_confidence_platform/`.
- Phase 6 writes its own artifact layer to S3 (immutable JSON report artifacts) and DynamoDB (report job records, report metadata records).
- Phase 6 does not mutate any Phase 5 intelligence artifact, Phase 4 aggregation artifact, or any earlier-phase record.
- Phase 6 requires `IntelligenceMetadata.status = COMPLETE` before consuming any Phase 5 intelligence artifact.
- Phase 6 extends the operator CLI with report generation and report retrieval commands.
- Phase 6 publishes the Phase 7 consumer contract, defining what Phase 7 may consume from Phase 6 report artifacts.

---

## 2. Problem Statement

Phase 5 and Phase 5.8 validation campaigns have delivered a complete, validated, production-ready Reliability Intelligence layer. The platform can now produce immutable, deterministic intelligence artifacts containing per-endpoint reliability scores, stability labels, burst labels, consistency labels, composite scores, and full methodology traces.

These intelligence artifacts answer the analytical question — "What is the measured reliability of this API?" — but they are not consumable by operators, customers, or CI/CD systems in their current JSON form. The gap between structured intelligence and a human-readable, evidence-backed Release Confidence Report is the problem Phase 6 solves.

Specifically:

1. **No Release Confidence Report exists.** There is no mechanism to produce a customer-facing document that faithfully presents Phase 5 intelligence findings with executive summary, per-endpoint analysis, methodology disclosure, and evidence lineage.

2. **No canonical report model exists.** There is no Canonical Report DTO that defines the authoritative, format-neutral representation of a Release Confidence Report, from which all output formats (JSON, Markdown, PDF) are derived deterministically.

3. **No report persistence exists.** There is no S3/DynamoDB artifact lifecycle for report artifacts, no idempotency control, and no status tracking for report generation.

4. **No export formats exist.** Operators cannot produce Markdown or PDF reports for customer delivery.

5. **Phase 7 has no input.** Phase 7 (Audit Platform Integrity) requires Phase 6 report artifacts as input for platform integrity certification. Without Phase 6, Phase 7 cannot begin.

Phase 6 closes all of these gaps while preserving the platform's constitutional boundary: **Intelligence owns interpretation. Phase 6 owns reporting.**

---

## 3. User Persona / Target User

### Platform Engineer / Operator

Invokes Phase 6 report generation via CLI after confirming Phase 5 intelligence generation is complete. Inspects report artifacts to verify determinism, methodology disclosure completeness, and evidence traceability. Uses the Phase 6 Engineering Retrieval CLI for operational debugging and pre-delivery validation.

### QA Engineer

Validates Phase 6 report output against known fixture inputs. Confirms that all Phase 5 conclusions are faithfully rendered without alteration, that no re-derivation of intelligence occurs, that all methodology disclosure fields are present and verbatim, and that all output formats (JSON, Markdown, PDF) are consistent and deterministic.

### Phase 7 Platform Integrity Consumer (Internal)

Reads Phase 6 report artifacts to perform Audit Platform Integrity verification. Requires `ReportMetadata.status = COMPLETE` as its prerequisite gate. Must not mutate Phase 6 report artifacts.

### Audit Customer (Indirect)

Receives the final Markdown or PDF Release Confidence Report as the deliverable of a Release Confidence Audit engagement. Expects every conclusion in the report to trace back to objective operational evidence. Does not directly interact with Phase 6 CLI or artifacts.

---

## 4. Functional Requirements

### FR-P1 — Report Generation CLI

**FR-P1a**: Phase 6 exposes an operator CLI command `rcp generate report` that accepts `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, and optionally `--force`.

**FR-P1b**: Before any report generation activity, Phase 6 must check `IntelligenceMetadata.status = COMPLETE`. If the record is absent or `status != COMPLETE`, Phase 6 must abort with a structured error: `INTELLIGENCE_NOT_COMPLETE`. This is the Phase 6 prerequisite gate, directly analogous to the `AggregateSetCompletion` gate used by Phase 5.

**FR-P1c**: Phase 6 must implement idempotency. If a `ReportMetadata` record already exists with `status = COMPLETE`, Phase 6 must not re-generate without `--force`. The existing report artifact remains authoritative.

**FR-P1d**: Phase 6 must maintain a status lifecycle for each generation invocation using a `ReportJob` DynamoDB record: `PENDING` → `IN_PROGRESS` → `COMPLETE` | `FAILED`.

**FR-P1e**: All Phase 6 artifacts carry a `report_version` constant (`report_v1`) on every record and in every artifact.

### FR-P2 — Canonical Report DTO

**FR-P2a**: Phase 6 must define a `ReleaseConfidenceReport` Pydantic model that is the single canonical, format-neutral representation of a Release Confidence Report.

**FR-P2b**: The DTO is the only authorized input to all formatters (JSON, Markdown, PDF). Formatters must not access Phase 5 intelligence artifacts directly.

**FR-P2c**: The DTO must carry all Phase 5 intelligence conclusions faithfully without alteration, relabeling, or re-derivation. Every Phase 5 score, label, methodology trace, and evidence reference must be present in the DTO.

**FR-P2d**: The DTO must include report-level identity fields (`report_id`, `report_version`, `generated_at`, `generator_version`) generated by Phase 6.

**FR-P2e**: The DTO must include an `ExecutiveSummary` section that presents the Phase 5 `score_label`, `composite_score.value`, `endpoint_count`, and audit-level success rate, plus a bounded set of deterministic `score_label_description` strings fixed within `report_v1`.

**FR-P2f**: `score_label_description` must be derived deterministically from the `score_label` bounded value set (`HIGH_CONFIDENCE`, `MODERATE_CONFIDENCE`, `LOW_CONFIDENCE`) using a fixed mapping defined in `constants.py`. This mapping is presentation-only and must not alter or substitute the Phase 5 `score_label` value.

**FR-P2g**: The DTO must carry `methodology_disclosure` verbatim from Phase 5 without any omission, summarization, or modification.

**FR-P2h**: The DTO must carry `input_lineage` verbatim from Phase 5, preserving the complete chain of evidence lineage back to Phase 4 aggregation.

### FR-P3 — Report Persistence

**FR-P3a**: Phase 6 must persist the serialized Canonical Report DTO as an immutable JSON artifact in S3 under the `reports/` key prefix namespace.

**FR-P3b**: The S3 artifact key must include the `report_job_id` segment to guarantee per-generation uniqueness. Force re-generation produces a new key. The previous artifact is never deleted.

**FR-P3c**: Phase 6 must write a `ReportJob` DynamoDB record per invocation (one per `report_job_id`), immutable once at terminal state.

**FR-P3d**: Phase 6 must write a `ReportMetadata` DynamoDB record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)` combination. This record reflects current generation state and is the Phase 7 prerequisite gate anchor.

**FR-P3e**: Phase 6 must never mutate any Phase 5 DynamoDB record (`IntelligenceJob`, `IntelligenceMetadata`), Phase 4 DynamoDB record, or any earlier-phase record.

### FR-P4 — JSON Export

**FR-P4a**: The canonical JSON report artifact persisted to S3 constitutes the JSON export. Its schema is the serialized `ReleaseConfidenceReport` DTO.

**FR-P4b**: JSON serialization must use canonical field ordering (`sort_keys=True`) and 3-decimal-place precision for all numeric score fields, consistent with Phase 5 artifact serialization.

**FR-P4c**: The JSON artifact must be byte-identical for identical Phase 5 intelligence inputs within `report_v1`.

### FR-P5 — Markdown Formatter

**FR-P5a**: A `MarkdownFormatter` must produce a complete, structured Markdown document from the `ReleaseConfidenceReport` DTO.

**FR-P5b**: The Markdown report must include all major sections: Executive Summary, Audit Overview, Release Confidence Score, Per-Endpoint Analysis, Methodology Disclosure, Evidence Lineage, and Limitations.

**FR-P5c**: The Markdown output must be deterministic: identical DTO input produces identical Markdown output.

**FR-P5d**: The Markdown formatter must not contain business logic, scoring logic, or label derivation. All values are read from the DTO.

**FR-P5e**: Methodology disclosure and limitations must be rendered verbatim from the DTO. No editorial summarization or omission is permitted.

### FR-P6 — PDF Export

**FR-P6a**: A `PdfFormatter` must produce a PDF document from the `ReleaseConfidenceReport` DTO.

**FR-P6b**: The PDF must include the same sections and content as the Markdown output. Visual formatting may differ, but all textual information must be identical.

**FR-P6c**: The PDF formatter must not contain business logic, scoring logic, or label derivation.

**FR-P6d**: PDF generation may be implemented by rendering Markdown to HTML and converting to PDF, or by direct PDF generation. The implementation choice must be documented in the technical design.

### FR-P7 — Engineering Retrieval CLI

**FR-P7a**: Phase 6 exposes a set of operator CLI `retrieve report-*` commands for read-only access to Phase 6 report artifacts.

**FR-P7b**: Required retrieval commands:
- `retrieve report-status` — display `ReportMetadata` status, score_label, and report_job_id
- `retrieve report-summary` — display Executive Summary section from S3 artifact
- `retrieve report-endpoints` — display per-endpoint analysis sections from S3 artifact
- `retrieve report-methodology` — display methodology disclosure verbatim from S3 artifact
- `retrieve report-lineage` — display evidence lineage from S3 artifact
- `retrieve report-json` — output the full canonical JSON artifact
- `retrieve report-markdown` — render and output the full Markdown report on-demand

**FR-P7c**: All retrieval commands are unconditionally read-only. No `ReportJob` or `ReportMetadata` record may be written, updated, or deleted by a retrieval command.

**FR-P7d**: All retrieval commands must include a provenance envelope identifying `report_version`, `report_id`, `intelligence_version`, `audit_id`, and `generated_at`.

---

## 5. Non-Functional Requirements

**NFR-1 — Determinism**: Identical Phase 5 intelligence inputs must produce byte-identical canonical JSON report artifacts within `report_v1`. This guarantee applies to all `report_v1` generation events regardless of timestamp, environment, or operator.

**NFR-2 — Evidence Traceability**: Every Phase 5 intelligence conclusion presented in a Phase 6 report must be traceable back to its source Phase 5 artifact field. The DTO must carry all source_field_refs and methodology traces from Phase 5.

**NFR-3 — Methodology Disclosure Completeness**: The full Phase 5 `methodology_disclosure` block must be present and verbatim in every Phase 6 report artifact and every rendered format. No field may be omitted, summarized, or paraphrased.

**NFR-4 — Limitation Disclosure Completeness**: The `limitations` array from Phase 5 `methodology_disclosure` must be presented verbatim in every Phase 6 report format. No limitation may be omitted.

**NFR-5 — Phase 5 Non-Mutation**: Phase 6 must never write to or mutate any Phase 5 DynamoDB record or S3 artifact. This is a constitutional invariant.

**NFR-6 — Phase 4 and Earlier Non-Access**: Phase 6 must not read Phase 4 aggregation artifacts, Phase 3 audit lifecycle records, or Phase 1–2 raw execution evidence directly. All Phase 6 inputs must come from Phase 5 intelligence artifacts.

**NFR-7 — Report Schema Stability**: The `report_v1` DTO schema is immutable after HITL approval of Phase 6.1 documentation. Schema changes require a new `report_version`.

**NFR-8 — Prerequisite Gate Enforcement**: The `IntelligenceMetadata.status = COMPLETE` gate is unconditional. Phase 6 must not attempt report generation if this gate is not satisfied, regardless of S3 key existence, partial artifact presence, or any other signal.

**NFR-9 — Formatter Purity**: No formatter (JSON, Markdown, PDF) may contain business logic, scoring derivation, or label re-interpretation. All analytical content originates in the DTO.

---

## 6. Out of Scope

The following are explicitly out of scope for Phase 6:

- Reliability intelligence derivation (Phase 5)
- Release Confidence Scoring re-computation (Phase 5)
- Any label derivation, threshold application, or analytical conclusion
- Audit Platform Integrity verification (Phase 7)
- CI/CD integration or gating (Phase 7 or later)
- Customer portal, web interface, or dashboard
- Event-driven Lambda trigger from `IntelligenceMetadata`
- Real-time or streaming report delivery
- Report comparison, trending, or historical analysis
- Custom scoring or weighting overrides
- Redaction, anonymization, or customer-configurable content filtering
- Multi-audit aggregation or portfolio reporting

---

## 7. Subphase Breakdown

| Subphase | Scope |
| --- | --- |
| 6.1 | Documentation — product spec, technical design, report schema, Phase 7 consumer contract, QA plan |
| 6.2 | Report Model & Canonical DTO — `ReleaseConfidenceReport` Pydantic model, constants, versioning |
| 6.3 | Report Generation Engine — `ReportBuilder`, prerequisite gate, pipeline, status lifecycle |
| 6.4 | Report Persistence — S3 artifact write, DynamoDB `ReportJob` + `ReportMetadata` records |
| 6.5 | Markdown Formatter — `MarkdownFormatter` rendering from DTO |
| 6.6 | PDF Export — `PdfFormatter` rendering from DTO |
| 6.7 | Engineering Retrieval CLI — `retrieve report-*` operator commands |
| 6.8 | Validation Campaign — live validation against Phase 5 intelligence artifacts |

---

## 8. Success Criteria

The Phase 6 initiative is complete when:

1. All Phase 6.1 documentation artifacts are HITL-approved.
2. The `ReleaseConfidenceReport` DTO schema is defined, versioned, and covered by a compatibility gate test.
3. `rcp generate report` produces a canonical JSON artifact that is byte-identical for identical Phase 5 inputs.
4. All Phase 5 intelligence conclusions appear faithfully in the JSON artifact, the Markdown report, and the PDF report.
5. The full `methodology_disclosure` block appears verbatim in all formats.
6. No Phase 5 re-derivation, re-scoring, or reinterpretation occurs anywhere in Phase 6 code.
7. The `IntelligenceMetadata.status = COMPLETE` prerequisite gate is enforced unconditionally.
8. `ReportMetadata.status = COMPLETE` is the reliable Phase 7 prerequisite gate anchor.
9. All retrieval CLI commands return correct data with complete provenance envelopes.
10. The Phase 6.8 validation campaign confirms correct report generation against known Phase 5 intelligence artifacts.

---

## 9. Traceability

- Phase 5 → Phase 6 Consumer Contract: `docs/architecture/phase_5_phase6_consumer_contract.md`
- Phase 6 Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 QA/Test Plan: `docs/qa/phase_6_deterministic_reporting_test_plan.md`
- Phase 5 Product Spec: `docs/product/phase_5_reliability_intelligence_product_spec.md`
- Phase 5 Technical Design: `docs/architecture/phase_5_reliability_intelligence_technical_design.md`
- Product Constitution: `RCP_Product_Strategy.md`
