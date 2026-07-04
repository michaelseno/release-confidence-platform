"""Canonical Report DTO for Phase 6 deterministic reporting.

ReleaseConfidenceReport is the single format-neutral representation consumed by all
formatters (JSON, Markdown, PDF). It is the only authorised input to formatters.

DTO stratification (from technical design Section 5.2):
  Layer 1 — Report Identity: Phase 6-generated fields (report_id, generated_at, etc.)
  Layer 2 — Intelligence Provenance: Phase 5 pass-through, no transformation
  Layer 3 — Executive Summary: Phase 5 conclusions + Phase 6 bounded presentation layer
  Layer 4 — Analytical Sections: Phase 5 conclusions carried faithfully
  Layer 5 — Methodology Disclosure: verbatim from Phase 5, no modification

All score fields use float, not Decimal. Phase 5 Decimal-serialised strings are
converted to float when the JSON intelligence artifact is deserialised before DTO
construction. This model is a presentation model, not a computation model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from release_confidence_platform.deterministic_reporting.constants import (
    REPORT_VERSION,
    SCORE_LABEL_BOUNDED_SET,
)


# ---------------------------------------------------------------------------
# Layer 1: Report Identity (Phase 6-generated)
# ---------------------------------------------------------------------------


class ReportIdentity(BaseModel):
    report_id: str
    report_version: str
    generated_at: str
    generator_version: str

    @field_validator("report_version")
    @classmethod
    def _report_version_must_be_v1(cls, v: str) -> str:
        if v != REPORT_VERSION:
            raise ValueError(f"report_version must be '{REPORT_VERSION}', got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Layer 2: Intelligence Provenance (Phase 5 pass-through)
# ---------------------------------------------------------------------------


class IntelligenceProvenance(BaseModel):
    intelligence_version: str
    intelligence_job_id: str
    client_id: str
    audit_id: str
    audit_execution_id: str
    config_version: str
    aggregation_version: str
    aggregate_set_hash: str
    intelligence_completed_at: str


# ---------------------------------------------------------------------------
# Layer 3: Executive Summary (Phase 5 conclusions + Phase 6 presentation layer)
# ---------------------------------------------------------------------------


class ExecutiveSummary(BaseModel):
    score_label: str
    composite_score_value: float
    endpoint_count: int
    audit_success_rate: float
    total_executions: int
    score_label_description: str

    @field_validator("score_label")
    @classmethod
    def _score_label_in_bounded_set(cls, v: str) -> str:
        if v not in SCORE_LABEL_BOUNDED_SET:
            raise ValueError(
                f"score_label must be one of {sorted(SCORE_LABEL_BOUNDED_SET)}, got {v!r}"
            )
        return v

    @field_validator("composite_score_value")
    @classmethod
    def _composite_score_value_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"composite_score_value must be in [0.0, 1.0], got {v}")
        return v


# ---------------------------------------------------------------------------
# Layer 4: Analytical Sections (Phase 5 conclusions, faithfully carried through)
# ---------------------------------------------------------------------------


class AuditReliabilityOverview(BaseModel):
    total_executions: int
    total_pass: int
    total_fail: int
    total_timeout: int
    total_network_failure: int
    audit_success_rate: float
    endpoint_count: int
    audit_latency_mean_ms: float | None = None
    audit_latency_p95_ms: float | None = None
    audit_latency_p99_ms: float | None = None
    source_field_refs: dict[str, Any]


class CompositeScoreSection(BaseModel):
    value: float
    score_label: str
    intelligence_version: str
    aggregation_version: str
    aggregate_set_hash: str
    endpoint_count: int
    component_breakdown: dict[str, Any]


class ReliabilityMetrics(BaseModel):
    execution_count: int
    pass_count: int
    fail_count: int
    timeout_count: int
    success_rate: float | None = None
    success_rate_numerator: int
    success_rate_denominator: int
    latency_min_ms: float | None = None
    latency_max_ms: float | None = None
    latency_mean_ms: float | None = None
    latency_median_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_p99_ms: float | None = None
    latency_count: int
    failure_classification_breakdown: dict[str, Any]
    http_response_distribution: dict[str, Any]
    source_field_refs: dict[str, Any]


class StabilityAnalysis(BaseModel):
    success_rate_stability_label: str
    latency_stability_label: str
    methodology_trace: dict[str, Any]


class BurstAnalysis(BaseModel):
    failure_burst_label: str
    latency_spike_label: str
    methodology_trace: dict[str, Any]


class ConsistencyAnalysis(BaseModel):
    consistency_label: str
    methodology_trace: dict[str, Any]


class EndpointScore(BaseModel):
    composite_score: float
    reliability_score: float
    stability_score: float
    burst_score: float
    consistency_score: float
    score_derivation: dict[str, Any]


class EndpointSection(BaseModel):
    endpoint_id: str
    reliability_metrics: ReliabilityMetrics
    stability_analysis: StabilityAnalysis
    burst_analysis: BurstAnalysis
    consistency_analysis: ConsistencyAnalysis
    endpoint_score: EndpointScore


# ---------------------------------------------------------------------------
# Lineage and Methodology (Layers 4–5, verbatim Phase 5 pass-through)
# ---------------------------------------------------------------------------


class InputLineageSection(BaseModel):
    aggregate_set_hash: str
    aggregation_job_id: str
    aggregation_version: str
    aggregate_set_completion_created_at: str
    endpoint_aggregate_count: int
    source_raw_result_count: int
    audit_lineage_manifest_ref: dict[str, Any]


class MethodologyDisclosure(BaseModel):
    intelligence_version: str
    scoring: dict[str, Any]
    stability_label_definitions: dict[str, Any]
    burst_label_definitions: dict[str, Any]
    consistency_label_definitions: dict[str, Any]
    label_to_score_mapping: dict[str, Any]
    limitations: list[str]


# ---------------------------------------------------------------------------
# Root Canonical Report DTO
# ---------------------------------------------------------------------------


class ReleaseConfidenceReport(BaseModel):
    identity: ReportIdentity
    intelligence_provenance: IntelligenceProvenance
    executive_summary: ExecutiveSummary
    audit_reliability_overview: AuditReliabilityOverview
    composite_score: CompositeScoreSection
    endpoints: list[EndpointSection]
    input_lineage: InputLineageSection
    methodology_disclosure: MethodologyDisclosure
