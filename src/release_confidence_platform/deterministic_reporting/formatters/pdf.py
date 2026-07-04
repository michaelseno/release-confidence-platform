"""PDF formatter for the ReleaseConfidenceReport DTO.

PdfFormatter.render() is a pure presentation function. It accepts only the
ReleaseConfidenceReport DTO and returns a PDF as bytes. It contains no scoring
logic, label derivation, business logic, or Phase 5/4 access.

Uses fpdf2 (pure Python, no system dependencies). All text values are sourced
verbatim from the DTO. The PDF creation date is fixed to report.identity.generated_at
for determinism — no datetime.now() call is made at render time.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fpdf import FPDF

from release_confidence_platform.deterministic_reporting.models import (
    EndpointSection,
    ReleaseConfidenceReport,
)

# Column widths for two-column metric tables (label | value).
_LABEL_COL = 95
_VALUE_COL = 95
_ROW_H = 7


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


def _safe(text: str) -> str:
    """Encode text safely for fpdf2 built-in fonts (latin-1 subset).

    Characters outside latin-1 are replaced with '?' to prevent encoding errors.
    """
    return text.encode("latin-1", errors="replace").decode("latin-1")


class PdfFormatter:
    """Renders a ReleaseConfidenceReport to PDF bytes.

    The formatter is stateless. Every call to render() derives output solely
    from the DTO fields. No I/O, no scoring constants, no datetime.now() access.
    """

    def render(self, report: ReleaseConfidenceReport) -> bytes:
        """Render the report DTO to PDF bytes.

        Args:
            report: Fully populated ReleaseConfidenceReport DTO.

        Returns:
            Complete PDF document as bytes.
        """
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        # Fix creation date to DTO timestamp for determinism.
        generated_dt = datetime.fromisoformat(
            report.identity.generated_at.replace("Z", "+00:00")
        )
        pdf.set_creation_date(generated_dt)
        pdf.set_author("Release Confidence Platform")
        pdf.set_title(
            _safe(
                f"Release Confidence Report — {report.intelligence_provenance.audit_id}"
            )
        )

        pdf.add_page()

        self._render_header(pdf, report)
        self._section_separator(pdf)

        self._render_executive_summary(pdf, report)
        self._section_separator(pdf)

        self._render_composite_score(pdf, report)
        self._section_separator(pdf)

        self._render_audit_reliability_overview(pdf, report)
        self._section_separator(pdf)

        self._render_per_endpoint_analysis(pdf, report)
        self._section_separator(pdf)

        self._render_methodology_disclosure(pdf, report)
        self._section_separator(pdf)

        self._render_evidence_lineage(pdf, report)
        self._section_separator(pdf)

        self._render_report_provenance(pdf, report)

        return bytes(pdf.output())

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _section_separator(self, pdf: FPDF) -> None:
        """Add vertical spacing and a horizontal rule between sections."""
        pdf.ln(4)
        pdf.line(
            pdf.get_x(),
            pdf.get_y(),
            pdf.get_x() + pdf.epw,
            pdf.get_y(),
        )
        pdf.ln(4)

    def _h1(self, pdf: FPDF, text: str) -> None:
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 10, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def _h2(self, pdf: FPDF, text: str) -> None:
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def _h3(self, pdf: FPDF, text: str) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def _h4(self, pdf: FPDF, text: str) -> None:
        pdf.set_font("Helvetica", "BI", 11)
        pdf.cell(0, 6, _safe(text), new_x="LMARGIN", new_y="NEXT")

    def _body(self, pdf: FPDF, text: str) -> None:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6, _safe(text))

    def _kv(self, pdf: FPDF, key: str, value: str) -> None:
        """Render a key-value line.

        Uses a fixed 65mm label column and renders the remainder of the line
        width for the value, avoiding mixed cell/multi_cell positioning issues.
        """
        key_w = 65
        val_w = pdf.epw - key_w
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(key_w, 6, _safe(f"{key}:"), new_x="RIGHT", new_y="LAST")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(val_w, 6, _safe(value), new_x="LMARGIN", new_y="NEXT")

    def _json_block(self, pdf: FPDF, data: object) -> None:
        """Render a JSON block using Courier (monospace) font."""
        json_text = json.dumps(data, indent=2, sort_keys=True)
        pdf.set_font("Courier", "", 9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _safe(json_text))
        pdf.ln(2)

    def _table_row(
        self, pdf: FPDF, label: str, value: str, *, header: bool = False
    ) -> None:
        """Render a two-column table row."""
        style = "B" if header else ""
        pdf.set_font("Helvetica", style, 10)
        pdf.cell(_LABEL_COL, _ROW_H, _safe(label), border=1)
        pdf.cell(_VALUE_COL, _ROW_H, _safe(value), border=1, new_x="LMARGIN", new_y="NEXT")

    # ------------------------------------------------------------------
    # Section 1: Header
    # ------------------------------------------------------------------

    def _render_header(self, pdf: FPDF, report: ReleaseConfidenceReport) -> None:
        self._h1(pdf, "Release Confidence Report")
        pdf.ln(4)
        self._kv(pdf, "Audit ID", report.intelligence_provenance.audit_id)
        self._kv(pdf, "Report ID", report.identity.report_id)
        self._kv(pdf, "Report Version", report.identity.report_version)
        self._kv(pdf, "Generated At", report.identity.generated_at)

    # ------------------------------------------------------------------
    # Section 2: Executive Summary
    # ------------------------------------------------------------------

    def _render_executive_summary(self, pdf: FPDF, report: ReleaseConfidenceReport) -> None:
        es = report.executive_summary
        self._h2(pdf, "Executive Summary")
        pdf.ln(2)
        self._kv(pdf, "Confidence Level", es.score_label)
        self._kv(pdf, "Composite Score", f"{es.composite_score_value:.3f}")
        self._kv(pdf, "Endpoints Assessed", str(es.endpoint_count))
        self._kv(pdf, "Audit Success Rate", f"{es.audit_success_rate:.3f}")
        self._kv(pdf, "Total Executions", str(es.total_executions))
        pdf.ln(3)
        self._body(pdf, es.score_label_description)

    # ------------------------------------------------------------------
    # Section 3: Release Confidence Score
    # ------------------------------------------------------------------

    def _render_composite_score(self, pdf: FPDF, report: ReleaseConfidenceReport) -> None:
        cs = report.composite_score
        self._h2(pdf, "Release Confidence Score")
        pdf.ln(2)
        self._kv(pdf, "Score", f"{cs.value:.3f}")
        self._kv(pdf, "Label", cs.score_label)
        self._kv(pdf, "Aggregate Set Hash", cs.aggregate_set_hash)
        self._kv(pdf, "Endpoint Count", str(cs.endpoint_count))
        pdf.ln(2)
        self._h3(pdf, "Component Breakdown")
        self._json_block(pdf, cs.component_breakdown)

    # ------------------------------------------------------------------
    # Section 4: Audit Reliability Overview
    # ------------------------------------------------------------------

    def _render_audit_reliability_overview(
        self, pdf: FPDF, report: ReleaseConfidenceReport
    ) -> None:
        ar = report.audit_reliability_overview
        self._h2(pdf, "Audit Reliability Overview")
        pdf.ln(2)
        self._table_row(pdf, "Metric", "Value", header=True)
        self._table_row(pdf, "Total Executions", str(ar.total_executions))
        self._table_row(pdf, "Pass", str(ar.total_pass))
        self._table_row(pdf, "Fail", str(ar.total_fail))
        self._table_row(pdf, "Timeout", str(ar.total_timeout))
        self._table_row(pdf, "Network Failure", str(ar.total_network_failure))
        self._table_row(pdf, "Success Rate", f"{ar.audit_success_rate:.3f}")
        self._table_row(pdf, "Endpoint Count", str(ar.endpoint_count))
        self._table_row(pdf, "Latency Mean (ms)", _na(ar.audit_latency_mean_ms))
        self._table_row(pdf, "Latency p95 (ms)", _na(ar.audit_latency_p95_ms))
        self._table_row(pdf, "Latency p99 (ms)", _na(ar.audit_latency_p99_ms))

    # ------------------------------------------------------------------
    # Section 5: Per-Endpoint Analysis
    # ------------------------------------------------------------------

    def _render_per_endpoint_analysis(
        self, pdf: FPDF, report: ReleaseConfidenceReport
    ) -> None:
        self._h2(pdf, "Per-Endpoint Analysis")
        pdf.ln(2)
        for i, ep in enumerate(report.endpoints):
            if i > 0:
                # Thick separator between endpoints.
                pdf.ln(4)
                pdf.line(
                    pdf.get_x(),
                    pdf.get_y(),
                    pdf.get_x() + pdf.epw,
                    pdf.get_y(),
                )
                pdf.ln(4)
            self._render_endpoint_section(pdf, ep)

    def _render_endpoint_section(self, pdf: FPDF, ep: EndpointSection) -> None:
        rm = ep.reliability_metrics
        sa = ep.stability_analysis
        ba = ep.burst_analysis
        ca = ep.consistency_analysis
        es = ep.endpoint_score

        self._h3(pdf, f"Endpoint: {ep.endpoint_id}")
        pdf.ln(2)

        self._kv(pdf, "Composite Score", f"{es.composite_score:.3f}")
        self._kv(pdf, "Reliability Score", f"{es.reliability_score:.3f}")
        self._kv(pdf, "Stability Score", f"{es.stability_score:.3f}")
        self._kv(pdf, "Burst Score", f"{es.burst_score:.3f}")
        self._kv(pdf, "Consistency Score", f"{es.consistency_score:.3f}")
        pdf.ln(2)

        self._h4(pdf, "Score Derivation")
        self._json_block(pdf, es.score_derivation)

        self._h4(pdf, "Reliability Metrics")
        pdf.ln(1)
        self._table_row(pdf, "Metric", "Value", header=True)
        self._table_row(pdf, "Execution Count", str(rm.execution_count))
        self._table_row(pdf, "Pass", str(rm.pass_count))
        self._table_row(pdf, "Fail", str(rm.fail_count))
        self._table_row(pdf, "Timeout", str(rm.timeout_count))
        self._table_row(pdf, "Success Rate", _na(rm.success_rate, ".3f"))
        self._table_row(pdf, "Latency Min (ms)", _na(rm.latency_min_ms))
        self._table_row(pdf, "Latency Max (ms)", _na(rm.latency_max_ms))
        self._table_row(pdf, "Latency Mean (ms)", _na(rm.latency_mean_ms))
        self._table_row(pdf, "Latency Median (ms)", _na(rm.latency_median_ms))
        self._table_row(pdf, "Latency p95 (ms)", _na(rm.latency_p95_ms))
        self._table_row(pdf, "Latency p99 (ms)", _na(rm.latency_p99_ms))
        self._table_row(pdf, "Latency Count", str(rm.latency_count))
        pdf.ln(2)

        self._h4(pdf, "Stability Analysis")
        self._kv(pdf, "Success Rate Stability", sa.success_rate_stability_label)
        self._kv(pdf, "Latency Stability", sa.latency_stability_label)
        self._json_block(pdf, sa.methodology_trace)

        self._h4(pdf, "Burst Analysis")
        self._kv(pdf, "Failure Burst", ba.failure_burst_label)
        self._kv(pdf, "Latency Spike", ba.latency_spike_label)
        self._json_block(pdf, ba.methodology_trace)

        self._h4(pdf, "Consistency Analysis")
        self._kv(pdf, "Consistency", ca.consistency_label)
        self._json_block(pdf, ca.methodology_trace)

    # ------------------------------------------------------------------
    # Section 6: Methodology Disclosure
    # ------------------------------------------------------------------

    def _render_methodology_disclosure(
        self, pdf: FPDF, report: ReleaseConfidenceReport
    ) -> None:
        md = report.methodology_disclosure
        self._h2(pdf, "Methodology Disclosure")
        pdf.ln(2)
        self._kv(pdf, "Intelligence Version", md.intelligence_version)
        pdf.ln(2)

        self._h3(pdf, "Scoring")
        self._json_block(pdf, md.scoring)

        self._h3(pdf, "Stability Label Definitions")
        self._json_block(pdf, md.stability_label_definitions)

        self._h3(pdf, "Burst Label Definitions")
        self._json_block(pdf, md.burst_label_definitions)

        self._h3(pdf, "Consistency Label Definitions")
        self._json_block(pdf, md.consistency_label_definitions)

        self._h3(pdf, "Label-to-Score Mapping")
        self._json_block(pdf, md.label_to_score_mapping)

        self._h3(pdf, "Limitations")
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 11)
        for limitation in md.limitations:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 6, _safe(f"- {limitation}"))

    # ------------------------------------------------------------------
    # Section 7: Evidence Lineage
    # ------------------------------------------------------------------

    def _render_evidence_lineage(self, pdf: FPDF, report: ReleaseConfidenceReport) -> None:
        il = report.input_lineage
        self._h2(pdf, "Evidence Lineage")
        pdf.ln(2)
        self._kv(pdf, "Aggregate Set Hash", il.aggregate_set_hash)
        self._kv(pdf, "Aggregation Job ID", il.aggregation_job_id)
        self._kv(pdf, "Aggregation Version", il.aggregation_version)
        self._kv(pdf, "Source Raw Result Count", str(il.source_raw_result_count))
        self._kv(pdf, "Endpoint Aggregate Count", str(il.endpoint_aggregate_count))
        self._kv(
            pdf,
            "Aggregate Set Completion",
            il.aggregate_set_completion_created_at,
        )
        pdf.ln(2)
        self._h3(pdf, "Audit Lineage Manifest Reference")
        self._json_block(pdf, il.audit_lineage_manifest_ref)

    # ------------------------------------------------------------------
    # Section 8: Report Provenance
    # ------------------------------------------------------------------

    def _render_report_provenance(self, pdf: FPDF, report: ReleaseConfidenceReport) -> None:
        ip = report.intelligence_provenance
        self._h2(pdf, "Report Provenance")
        pdf.ln(2)
        self._kv(pdf, "Intelligence Version", ip.intelligence_version)
        self._kv(pdf, "Intelligence Job ID", ip.intelligence_job_id)
        self._kv(pdf, "Client ID", ip.client_id)
        self._kv(pdf, "Audit ID", ip.audit_id)
        self._kv(pdf, "Audit Execution ID", ip.audit_execution_id)
        self._kv(pdf, "Config Version", ip.config_version)
        self._kv(pdf, "Aggregation Version", ip.aggregation_version)
        self._kv(pdf, "Aggregate Set Hash", ip.aggregate_set_hash)
        self._kv(pdf, "Intelligence Completed At", ip.intelligence_completed_at)
        self._kv(pdf, "Generator Version", report.identity.generator_version)
