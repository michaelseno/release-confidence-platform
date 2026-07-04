"""Markdown formatter for the ReleaseConfidenceReport DTO.

MarkdownFormatter.render() is a pure presentation function. It accepts only the
ReleaseConfidenceReport DTO and returns a Markdown string. It contains no
scoring logic, label derivation, business logic, or Phase 5/4 access.

All field values are rendered verbatim from the DTO. No field may be omitted,
recomputed, summarized, or modified for readability.
"""
from __future__ import annotations

import json

from release_confidence_platform.deterministic_reporting.models import (
    EndpointSection,
    ReleaseConfidenceReport,
)

# Triple-backtick fence used to embed code blocks without terminating the
# surrounding f-string.
_FENCE = "```"


def _na(val: float | None, fmt: str = "") -> str:
    """Render a nullable float as a formatted string or 'N/A' when None.

    Args:
        val: The nullable float value.
        fmt: Optional format spec (e.g. '.3f'). When empty, renders via str().

    Returns:
        Formatted string or 'N/A'.
    """
    if val is None:
        return "N/A"
    if fmt:
        return format(val, fmt)
    return str(val)


class MarkdownFormatter:
    """Renders a ReleaseConfidenceReport to Markdown string.

    The formatter is stateless. Every call to render() derives output solely
    from the DTO fields. No I/O, no scoring constants, no datetime access.
    """

    def render(self, report: ReleaseConfidenceReport) -> str:
        """Render the report DTO to a Markdown string.

        Args:
            report: Fully populated ReleaseConfidenceReport DTO.

        Returns:
            Complete Markdown document as a string, terminated with a newline.
        """
        sections = [
            self._render_header(report),
            self._render_executive_summary(report),
            self._render_composite_score(report),
            self._render_audit_reliability_overview(report),
            self._render_per_endpoint_analysis(report),
            self._render_methodology_disclosure(report),
            self._render_evidence_lineage(report),
            self._render_report_provenance(report),
        ]
        return "\n\n".join(sections) + "\n"

    # ------------------------------------------------------------------
    # Section 1: Header
    # ------------------------------------------------------------------

    def _render_header(self, report: ReleaseConfidenceReport) -> str:
        lines = [
            "# Release Confidence Report",
            "",
            f"**Audit ID:** {report.intelligence_provenance.audit_id}",
            f"**Report ID:** {report.identity.report_id}",
            f"**Report Version:** {report.identity.report_version}",
            f"**Generated At:** {report.identity.generated_at}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 2: Executive Summary
    # ------------------------------------------------------------------

    def _render_executive_summary(self, report: ReleaseConfidenceReport) -> str:
        es = report.executive_summary
        lines = [
            "## Executive Summary",
            "",
            f"**Confidence Level:** {es.score_label}",
            f"**Composite Score:** {es.composite_score_value:.3f}",
            f"**Endpoints Assessed:** {es.endpoint_count}",
            f"**Audit Success Rate:** {es.audit_success_rate:.3f}",
            f"**Total Executions:** {es.total_executions}",
            "",
            f"> {es.score_label_description}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 3: Release Confidence Score
    # ------------------------------------------------------------------

    def _render_composite_score(self, report: ReleaseConfidenceReport) -> str:
        cs = report.composite_score
        breakdown_json = json.dumps(cs.component_breakdown, indent=2, sort_keys=True)
        lines = [
            "## Release Confidence Score",
            "",
            f"**Score:** {cs.value:.3f}",
            f"**Label:** {cs.score_label}",
            f"**Aggregate Set Hash:** {cs.aggregate_set_hash}",
            f"**Endpoint Count:** {cs.endpoint_count}",
            "",
            "### Component Breakdown",
            "",
            f"{_FENCE}json",
            breakdown_json,
            _FENCE,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 4: Audit Reliability Overview
    # ------------------------------------------------------------------

    def _render_audit_reliability_overview(self, report: ReleaseConfidenceReport) -> str:
        ar = report.audit_reliability_overview
        lines = [
            "## Audit Reliability Overview",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total Executions | {ar.total_executions} |",
            f"| Pass | {ar.total_pass} |",
            f"| Fail | {ar.total_fail} |",
            f"| Timeout | {ar.total_timeout} |",
            f"| Network Failure | {ar.total_network_failure} |",
            f"| Success Rate | {ar.audit_success_rate:.3f} |",
            f"| Endpoint Count | {ar.endpoint_count} |",
            f"| Latency Mean (ms) | {_na(ar.audit_latency_mean_ms)} |",
            f"| Latency p95 (ms) | {_na(ar.audit_latency_p95_ms)} |",
            f"| Latency p99 (ms) | {_na(ar.audit_latency_p99_ms)} |",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 5: Per-Endpoint Analysis
    # ------------------------------------------------------------------

    def _render_per_endpoint_analysis(self, report: ReleaseConfidenceReport) -> str:
        parts: list[str] = ["## Per-Endpoint Analysis"]
        for ep in report.endpoints:
            parts.append(self._render_endpoint_section(ep))
        return "\n\n".join(parts)

    def _render_endpoint_section(self, ep: EndpointSection) -> str:
        rm = ep.reliability_metrics
        sa = ep.stability_analysis
        ba = ep.burst_analysis
        ca = ep.consistency_analysis
        es = ep.endpoint_score

        score_derivation_json = json.dumps(es.score_derivation, indent=2, sort_keys=True)
        stability_trace_json = json.dumps(sa.methodology_trace, indent=2, sort_keys=True)
        burst_trace_json = json.dumps(ba.methodology_trace, indent=2, sort_keys=True)
        consistency_trace_json = json.dumps(ca.methodology_trace, indent=2, sort_keys=True)

        lines = [
            f"### Endpoint: {ep.endpoint_id}",
            "",
            f"**Composite Score:** {es.composite_score:.3f}",
            f"**Reliability Score:** {es.reliability_score:.3f}",
            f"**Stability Score:** {es.stability_score:.3f}",
            f"**Burst Score:** {es.burst_score:.3f}",
            f"**Consistency Score:** {es.consistency_score:.3f}",
            "",
            "#### Score Derivation",
            "",
            f"{_FENCE}json",
            score_derivation_json,
            _FENCE,
            "",
            "#### Reliability Metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Execution Count | {rm.execution_count} |",
            f"| Pass | {rm.pass_count} |",
            f"| Fail | {rm.fail_count} |",
            f"| Timeout | {rm.timeout_count} |",
            f"| Success Rate | {_na(rm.success_rate, '.3f')} |",
            f"| Latency Min (ms) | {_na(rm.latency_min_ms)} |",
            f"| Latency Max (ms) | {_na(rm.latency_max_ms)} |",
            f"| Latency Mean (ms) | {_na(rm.latency_mean_ms)} |",
            f"| Latency Median (ms) | {_na(rm.latency_median_ms)} |",
            f"| Latency p95 (ms) | {_na(rm.latency_p95_ms)} |",
            f"| Latency p99 (ms) | {_na(rm.latency_p99_ms)} |",
            f"| Latency Count | {rm.latency_count} |",
            "",
            "#### Stability Analysis",
            "",
            f"**Success Rate Stability:** {sa.success_rate_stability_label}",
            f"**Latency Stability:** {sa.latency_stability_label}",
            "",
            f"{_FENCE}json",
            stability_trace_json,
            _FENCE,
            "",
            "#### Burst Analysis",
            "",
            f"**Failure Burst:** {ba.failure_burst_label}",
            f"**Latency Spike:** {ba.latency_spike_label}",
            "",
            f"{_FENCE}json",
            burst_trace_json,
            _FENCE,
            "",
            "#### Consistency Analysis",
            "",
            f"**Consistency:** {ca.consistency_label}",
            "",
            f"{_FENCE}json",
            consistency_trace_json,
            _FENCE,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 6: Methodology Disclosure
    # ------------------------------------------------------------------

    def _render_methodology_disclosure(self, report: ReleaseConfidenceReport) -> str:
        md = report.methodology_disclosure
        limitations_list = "\n".join(f"- {lim}" for lim in md.limitations)
        lines = [
            "## Methodology Disclosure",
            "",
            f"**Intelligence Version:** {md.intelligence_version}",
            "",
            "### Scoring",
            "",
            f"{_FENCE}json",
            json.dumps(md.scoring, indent=2, sort_keys=True),
            _FENCE,
            "",
            "### Stability Label Definitions",
            "",
            f"{_FENCE}json",
            json.dumps(md.stability_label_definitions, indent=2, sort_keys=True),
            _FENCE,
            "",
            "### Burst Label Definitions",
            "",
            f"{_FENCE}json",
            json.dumps(md.burst_label_definitions, indent=2, sort_keys=True),
            _FENCE,
            "",
            "### Consistency Label Definitions",
            "",
            f"{_FENCE}json",
            json.dumps(md.consistency_label_definitions, indent=2, sort_keys=True),
            _FENCE,
            "",
            "### Label-to-Score Mapping",
            "",
            f"{_FENCE}json",
            json.dumps(md.label_to_score_mapping, indent=2, sort_keys=True),
            _FENCE,
            "",
            "### Limitations",
            "",
            limitations_list,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 7: Evidence Lineage
    # ------------------------------------------------------------------

    def _render_evidence_lineage(self, report: ReleaseConfidenceReport) -> str:
        il = report.input_lineage
        manifest_json = json.dumps(il.audit_lineage_manifest_ref, indent=2, sort_keys=True)
        lines = [
            "## Evidence Lineage",
            "",
            f"**Aggregate Set Hash:** {il.aggregate_set_hash}",
            f"**Aggregation Job ID:** {il.aggregation_job_id}",
            f"**Aggregation Version:** {il.aggregation_version}",
            f"**Source Raw Result Count:** {il.source_raw_result_count}",
            f"**Endpoint Aggregate Count:** {il.endpoint_aggregate_count}",
            f"**Aggregate Set Completion:** {il.aggregate_set_completion_created_at}",
            "",
            "### Audit Lineage Manifest Reference",
            "",
            f"{_FENCE}json",
            manifest_json,
            _FENCE,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 8: Report Provenance
    # ------------------------------------------------------------------

    def _render_report_provenance(self, report: ReleaseConfidenceReport) -> str:
        ip = report.intelligence_provenance
        lines = [
            "## Report Provenance",
            "",
            f"**Intelligence Version:** {ip.intelligence_version}",
            f"**Intelligence Job ID:** {ip.intelligence_job_id}",
            f"**Client ID:** {ip.client_id}",
            f"**Audit ID:** {ip.audit_id}",
            f"**Audit Execution ID:** {ip.audit_execution_id}",
            f"**Config Version:** {ip.config_version}",
            f"**Aggregation Version:** {ip.aggregation_version}",
            f"**Aggregate Set Hash:** {ip.aggregate_set_hash}",
            f"**Intelligence Completed At:** {ip.intelligence_completed_at}",
            f"**Generator Version:** {report.identity.generator_version}",
        ]
        return "\n".join(lines)
