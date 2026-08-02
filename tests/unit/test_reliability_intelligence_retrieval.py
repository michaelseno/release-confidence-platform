"""IRET-U01 through IRET-RO02 — Phase 5.7 Intelligence Retrieval Layer unit tests.

Covers all test IDs:
  IRET-U01–06, IRET-F01–04, IRET-PROV01–03, IRET-REPR01, IRET-S01–05, IRET-RO01–02

Also covers Evidence Governance Workstream A1.3d.2 (Technical Design Section
20.4/20.12): `retrieve intelligence-*` must succeed, with zero
`CustodyPeriodConfigLoader.resolve` calls, zero `HoldRepository(` construction,
and zero governed-write calls, under three `config/custody_periods.json`
`intelligence`-class shapes -- because the read-only retrieval construction
path never resolves custody configuration or constructs hold coordination at
all (Invariant 31; the `retrieve intelligence-*` dispatch block in
operator_cli/main.py has no reference to either).
"""

from __future__ import annotations

import argparse
import json

import pytest

import release_confidence_platform.config.custody_period_config as custody_period_config_module
import release_confidence_platform.config.stage_config as stage_config_module
import release_confidence_platform.storage.aws_client_factory as aws_client_factory_module
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.operator_cli.main import main
from release_confidence_platform.reliability_intelligence.commands import (
    dispatch_intelligence_retrieve,
)
from release_confidence_platform.reliability_intelligence.dtypes import (
    _INTELLIGENCE_NOTICE,
    IntelligenceFilter,
    IntelligenceNotFoundDTO,
    IntelligenceStatusDTO,
    IntelligenceSummaryDTO,
)
from release_confidence_platform.reliability_intelligence.formatter import (
    IntelligenceFormatter,
)
from release_confidence_platform.reliability_intelligence.intelligence_service import (
    IntelligenceRetrievalService,
)

# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------


class MockIntelligenceRepo:
    def __init__(self, metadata=None):
        self._metadata = metadata
        self.write_calls: list = []  # track any write attempts (IRET-RO01)

    def get_intelligence_metadata(self, filters):
        return self._metadata

    # Stub write methods that track calls (IRET-RO01)
    def put_intelligence_metadata(self, *args, **kwargs):
        self.write_calls.append(("put_intelligence_metadata", args, kwargs))

    def update_intelligence_status(self, *args, **kwargs):
        self.write_calls.append(("update_intelligence_status", args, kwargs))


class MockIntelligencePublisher:
    def __init__(self, artifact=None):
        self._artifact = artifact
        self.write_calls: list = []  # track any write attempts (IRET-RO02)

    def read_artifact(self, s3_ref):
        return self._artifact

    # Stub write methods that track calls (IRET-RO02)
    def write_artifact(self, *args, **kwargs):
        self.write_calls.append(("write_artifact", args, kwargs))


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_COMPLETE_METADATA = {
    "intelligence_version": "intel_v1",
    "intelligence_job_id": "intjob_abc123",
    "client_id": "client1",
    "audit_id": "audit1",
    "audit_execution_id": "exec1",
    "config_version": "cfg_v1",
    "aggregation_version": "agg_v1",
    "status": "COMPLETE",
    "composite_score": "0.850",
    "score_label": "HIGH_CONFIDENCE",
    "endpoint_count": 3,
    "s3_artifact_ref": "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc123/artifact.json",  # noqa: E501
    "aggregate_set_hash": "abc123hash",
    "created_at": "2026-07-01T00:00:00.000Z",
    "completed_at": "2026-07-01T01:00:00.000Z",
    "failure_reason_code": None,
}

_FAILED_METADATA = {
    **_COMPLETE_METADATA,
    "status": "FAILED",
    "composite_score": None,
    "score_label": None,
    "endpoint_count": None,
    "s3_artifact_ref": None,
    "completed_at": None,
    "failure_reason_code": "PHASE4_RECORD_INCONSISTENCY",
}

_S3_ARTIFACT = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "audit_reliability_summary": {
        "total_execution_count": 300,
        "total_successful": 255,
        "total_failed": 45,
        "endpoint_count": 3,
    },
    "composite_score": {
        "value": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 3,
        "aggregate_set_hash": "abc123hash",
        "component_breakdown": {
            "reliability": {
                "weight": 0.5,
                "value": "0.850",
                "description": "Mean of per-endpoint success rates",
            },
            "stability": {
                "weight": 0.2,
                "value": "0.750",
                "description": "Mean of per-endpoint stability scores",
            },
            "burst": {
                "weight": 0.15,
                "value": "1.000",
                "description": "Mean of per-endpoint burst scores",
            },
            "consistency": {
                "weight": 0.15,
                "value": "0.500",
                "description": "Mean of per-endpoint consistency scores",
            },
        },
    },
    "input_lineage": {
        "aggregate_set_hash": "abc123hash",
        "aggregation_job_id": "aggjob_xyz",
    },
    "endpoints": [
        {
            "endpoint_id": "ep_001",
            "reliability_metrics": {
                "execution_count": 100,
                "pass_count": 85,
                "success_rate": "0.850",
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE",
                "latency_stability_label": "STABLE",
            },
            "burst_analysis": {
                "failure_burst_label": "NO_BURST_DETECTED",
                "latency_spike_label": "NO_SPIKE_DETECTED",
            },
            "consistency_analysis": {
                "consistency_label": "CONSISTENT",
            },
            "endpoint_score": {
                "composite_score": "0.850",
                "reliability_score": "0.850",
            },
        }
    ],
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {
            "per_endpoint_formula": (
                "0.50 * reliability_score + 0.20 * stability_score"
                " + 0.15 * burst_score + 0.15 * consistency_score"
            ),
            "component_weights": {
                "reliability": 0.5,
                "stability": 0.2,
                "burst": 0.15,
                "consistency": 0.15,
            },
        },
        "label_to_score_mapping": {
            "STABLE": 1.0,
            "DEGRADED": 0.0,
            "INSUFFICIENT_DATA": 0.5,
        },
        "limitations": [
            "burst timing attribution cannot be determined from agg_v1 inputs",
            "per-run or per-scenario consistency is not assessable from agg_v1",
        ],
    },
}

_FILTERS = IntelligenceFilter(
    client_id="client1",
    audit_id="audit1",
    audit_execution_id="exec1",
    config_version="cfg_v1",
    aggregation_version="agg_v1",
)


def _make_svc(metadata=None, artifact=None):
    repo = MockIntelligenceRepo(metadata=metadata)
    publisher = MockIntelligencePublisher(artifact=artifact)
    return IntelligenceRetrievalService(repo, publisher)


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a mock argparse namespace for dispatch tests."""
    defaults = {
        "client": "client1",
        "audit": "audit1",
        "execution": "exec1",
        "stage": "dev",
        "output": "human",
        "endpoint": None,
        "intelligence_version": "intel_v1",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# IRET-U04, IRET-U05, IRET-U06 — retrieve_status
# ---------------------------------------------------------------------------


class TestRetrieveStatus:
    def test_iret_u04_returns_status_and_job_id(self):
        """IRET-U04: status and intelligence_job_id are present."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        assert isinstance(dto, IntelligenceStatusDTO)
        assert dto.status == "COMPLETE"
        assert dto.intelligence_job_id == "intjob_abc123"

    def test_iret_u04_complete_job_has_score_and_label(self):
        """IRET-U04: COMPLETE job has composite_score and score_label."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        assert dto.composite_score == "0.850"
        assert dto.score_label == "HIGH_CONFIDENCE"
        assert dto.endpoint_count == 3

    def test_iret_u05_failed_job_has_failure_reason(self):
        """IRET-U05: FAILED job — failure_reason present."""
        svc = _make_svc(metadata=_FAILED_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        assert isinstance(dto, IntelligenceStatusDTO)
        assert dto.status == "FAILED"
        assert dto.failure_reason == "PHASE4_RECORD_INCONSISTENCY"

    def test_iret_u05_failed_job_score_and_label_are_none(self):
        """IRET-U05: FAILED job — composite_score and score_label are None."""
        svc = _make_svc(metadata=_FAILED_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        assert dto.composite_score is None
        assert dto.score_label is None

    def test_iret_u06_not_found_returns_dto(self):
        """IRET-U06: metadata is None → controlled IntelligenceNotFoundDTO."""
        svc = _make_svc(metadata=None)
        dto = svc.retrieve_status(_FILTERS)
        assert isinstance(dto, IntelligenceNotFoundDTO)
        assert dto.reason == "INTELLIGENCE_NOT_FOUND"
        assert dto.client_id == "client1"
        assert dto.audit_id == "audit1"


# ---------------------------------------------------------------------------
# IRET-U01 — retrieve_summary
# ---------------------------------------------------------------------------


class TestRetrieveSummary:
    def test_iret_u01_all_metadata_fields_present(self):
        """IRET-U01: all IntelligenceMetadata stable fields present in result."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_summary(_FILTERS)
        assert isinstance(dto, IntelligenceSummaryDTO)
        assert dto.intelligence_version == "intel_v1"
        assert dto.intelligence_job_id == "intjob_abc123"
        assert dto.client_id == "client1"
        assert dto.audit_id == "audit1"
        assert dto.audit_execution_id == "exec1"
        assert dto.config_version == "cfg_v1"
        assert dto.aggregation_version == "agg_v1"
        assert dto.status == "COMPLETE"
        assert dto.composite_score == "0.850"
        assert dto.score_label == "HIGH_CONFIDENCE"
        assert dto.endpoint_count == 3
        assert dto.s3_artifact_ref == (
            "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc123/artifact.json"
        )
        assert dto.aggregate_set_hash == "abc123hash"
        assert dto.created_at == "2026-07-01T00:00:00.000Z"
        assert dto.completed_at == "2026-07-01T01:00:00.000Z"

    def test_iret_u06_not_found_returns_dto(self):
        """IRET-U06: metadata is None → IntelligenceNotFoundDTO."""
        svc = _make_svc(metadata=None)
        dto = svc.retrieve_summary(_FILTERS)
        assert isinstance(dto, IntelligenceNotFoundDTO)
        assert dto.reason == "INTELLIGENCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# IRET-U02, IRET-U06 — retrieve_detail
# ---------------------------------------------------------------------------


class TestRetrieveDetail:
    def test_iret_u02_full_artifact_top_level_sections_present(self):
        """IRET-U02: full S3 artifact — all top-level sections present."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, dict)
        assert "intelligence_version" in result
        assert "aggregation_version" in result
        assert "audit_reliability_summary" in result
        assert "composite_score" in result
        assert "input_lineage" in result
        assert "endpoints" in result
        assert "methodology_disclosure" in result

    def test_iret_u02_artifact_version_values(self):
        """IRET-U02: version fields carry expected values."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_detail(_FILTERS)
        assert result["intelligence_version"] == "intel_v1"
        assert result["aggregation_version"] == "agg_v1"

    def test_iret_u06_detail_not_found_no_metadata(self):
        """IRET-U06: no metadata → controlled IntelligenceNotFoundDTO."""
        svc = _make_svc(metadata=None, artifact=_S3_ARTIFACT)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, IntelligenceNotFoundDTO)
        assert result.reason == "INTELLIGENCE_NOT_FOUND"

    def test_iret_u06_detail_not_found_no_s3_ref(self):
        """IRET-U06: metadata has no s3_artifact_ref → controlled IntelligenceNotFoundDTO."""
        metadata_no_ref = {**_COMPLETE_METADATA, "s3_artifact_ref": None}
        svc = _make_svc(metadata=metadata_no_ref, artifact=_S3_ARTIFACT)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, IntelligenceNotFoundDTO)
        assert result.reason == "ARTIFACT_NOT_READABLE"

    def test_iret_u06_detail_not_found_artifact_returns_none(self):
        """IRET-U06: publisher returns None artifact → controlled IntelligenceNotFoundDTO."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=None)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, IntelligenceNotFoundDTO)
        assert result.reason == "ARTIFACT_NOT_FOUND"

    def test_iret_u06_detail_not_found_no_publisher(self):
        """IRET-U06: no publisher → controlled IntelligenceNotFoundDTO."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        svc = IntelligenceRetrievalService(repo, publisher=None)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, IntelligenceNotFoundDTO)
        assert result.reason == "ARTIFACT_NOT_READABLE"


# ---------------------------------------------------------------------------
# IRET-U03 — retrieve_methodology
# ---------------------------------------------------------------------------


class TestRetrieveMethodology:
    def test_iret_u03_methodology_disclosure_present(self):
        """IRET-U03: methodology_disclosure section is returned."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_methodology(_FILTERS)
        assert isinstance(result, dict)
        assert "scoring" in result

    def test_iret_u03_per_endpoint_formula_present(self):
        """IRET-U03: scoring.per_endpoint_formula present."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_methodology(_FILTERS)
        assert "per_endpoint_formula" in result["scoring"]
        formula = result["scoring"]["per_endpoint_formula"]
        assert "reliability_score" in formula

    def test_iret_u03_limitations_present(self):
        """IRET-U03: limitations list present and non-empty."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_methodology(_FILTERS)
        assert "limitations" in result
        assert len(result["limitations"]) > 0

    def test_iret_u03_not_found_propagates(self):
        """IRET-U03: not-found from retrieve_detail propagates."""
        svc = _make_svc(metadata=None, artifact=_S3_ARTIFACT)
        result = svc.retrieve_methodology(_FILTERS)
        assert isinstance(result, IntelligenceNotFoundDTO)


# ---------------------------------------------------------------------------
# IRET-F01, IRET-F03, IRET-REPR01 — JSON output format
# ---------------------------------------------------------------------------


class TestOutputFormatJson:
    def _make_envelope(self):
        return IntelligenceFormatter.build_envelope(
            _FILTERS,
            {
                "intelligence_job_id": "intjob_abc123",
                "aggregate_set_hash": "abc123hash",
                "intelligence_version": "intel_v1",
                "aggregation_version": "agg_v1",
            },
        )

    def test_iret_f01_json_parse_succeeds(self):
        """IRET-F01: format_json output is valid JSON."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        dto = svc.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        output = IntelligenceFormatter.format_json(dto, envelope)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
        assert "data" in parsed

    def test_iret_f03_deterministic_two_calls(self):
        """IRET-F03: two calls with same data → identical strings."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        out1 = IntelligenceFormatter.format_json(dto, envelope)
        out2 = IntelligenceFormatter.format_json(dto, envelope)
        assert out1 == out2

    def test_iret_repr01_byte_identical_for_same_persisted_state(self):
        """IRET-REPR01: same persisted state → byte-identical JSON."""
        svc1 = _make_svc(metadata=_COMPLETE_METADATA)
        svc2 = _make_svc(metadata=_COMPLETE_METADATA)
        dto1 = svc1.retrieve_summary(_FILTERS)
        dto2 = svc2.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        out1 = IntelligenceFormatter.format_json(dto1, envelope)
        out2 = IntelligenceFormatter.format_json(dto2, envelope)
        assert out1 == out2

    def test_iret_f01_json_contains_envelope_fields(self):
        """IRET-F01: top-level JSON contains all envelope fields."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        envelope = self._make_envelope()
        output = IntelligenceFormatter.format_json(dto, envelope)
        parsed = json.loads(output)
        assert "_notice" in parsed
        assert "retrieved_at" in parsed
        assert "retrieval_version" in parsed
        assert "intelligence_version" in parsed
        assert "audit_id" in parsed
        assert "client_id" in parsed


# ---------------------------------------------------------------------------
# IRET-F02, IRET-F04, IRET-PROV03 — human output format
# ---------------------------------------------------------------------------


class TestOutputFormatHuman:
    def _make_envelope(self):
        return IntelligenceFormatter.build_envelope(_FILTERS, None)

    def test_iret_f02_human_output_is_non_empty(self):
        """IRET-F02: human output is non-empty."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        output = IntelligenceFormatter.format_human(dto, envelope)
        assert len(output) > 0

    def test_iret_f02_human_output_key_labels_present(self):
        """IRET-F02: key labels present in human output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        output = IntelligenceFormatter.format_human(dto, envelope)
        assert "Client" in output
        assert "Audit" in output
        assert "Retrieved at" in output

    def test_iret_f04_default_output_format_is_human(self):
        """IRET-F04: default output format is 'human' (no --output flag)."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="intelligence-summary")
        # output not explicitly set → defaults to "human"
        assert args.output == "human"
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        assert isinstance(output, str)
        # human output contains the disclaimer notice
        assert _INTELLIGENCE_NOTICE in output

    def test_iret_prov03_disclaimer_in_human_output(self):
        """IRET-PROV03: disclaimer text appears in human output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_summary(_FILTERS)
        envelope = self._make_envelope()
        output = IntelligenceFormatter.format_human(dto, envelope)
        assert _INTELLIGENCE_NOTICE in output


# ---------------------------------------------------------------------------
# IRET-PROV01, IRET-PROV02 — provenance envelope
# ---------------------------------------------------------------------------


class TestProvenanceEnvelope:
    def _build_envelope(self, metadata_dict=None):
        return IntelligenceFormatter.build_envelope(_FILTERS, metadata_dict)

    def test_iret_prov01_required_top_level_fields_present(self):
        """IRET-PROV01: retrieved_at, retrieval_version, intelligence_version,
        audit_id, client_id, intelligence_job_id all present."""
        md = {
            "intelligence_job_id": "intjob_abc123",
            "aggregate_set_hash": "abc123hash",
            "intelligence_version": "intel_v1",
            "aggregation_version": "agg_v1",
        }
        envelope = self._build_envelope(md)
        assert envelope.retrieved_at is not None
        assert envelope.retrieval_version is not None
        assert envelope.intelligence_version is not None
        assert envelope.audit_id is not None
        assert envelope.client_id is not None
        assert envelope.intelligence_job_id == "intjob_abc123"

    def test_iret_prov02_notice_field_present(self):
        """IRET-PROV02: _notice field present with disclaimer string."""
        envelope = self._build_envelope()
        assert envelope._notice == _INTELLIGENCE_NOTICE

    def test_iret_prov02_notice_in_json_output(self):
        """IRET-PROV02: _notice appears in JSON output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA)
        dto = svc.retrieve_status(_FILTERS)
        envelope = self._build_envelope(
            {
                "intelligence_job_id": "intjob_abc123",
                "intelligence_version": "intel_v1",
                "aggregation_version": "agg_v1",
                "aggregate_set_hash": None,
            }
        )
        output = IntelligenceFormatter.format_json(dto, envelope)
        parsed = json.loads(output)
        assert "_notice" in parsed
        assert parsed["_notice"] == _INTELLIGENCE_NOTICE

    def test_iret_prov01_retrieved_at_is_utc_format(self):
        """IRET-PROV01: retrieved_at is ISO-8601 UTC format."""
        envelope = self._build_envelope()
        assert envelope.retrieved_at.endswith("Z")
        assert "T" in envelope.retrieved_at

    def test_iret_prov01_retrieval_version_present(self):
        """IRET-PROV01: retrieval_version is non-empty string."""
        envelope = self._build_envelope()
        assert envelope.retrieval_version
        assert isinstance(envelope.retrieval_version, str)


# ---------------------------------------------------------------------------
# IRET-S01–S05 — sensitive data exclusion
# ---------------------------------------------------------------------------


class TestSensitiveDataExclusion:
    def _json_string(self, svc, retrieve_fn_name):
        dto_method = getattr(svc, retrieve_fn_name)
        dto = dto_method(_FILTERS)
        envelope = IntelligenceFormatter.build_envelope(_FILTERS, None)
        return IntelligenceFormatter.format_json(dto, envelope)

    def test_iret_s01_no_request_response_bodies(self):
        """IRET-S01: no raw request/response bodies in any output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        for method in ("retrieve_status", "retrieve_summary"):
            output = self._json_string(svc, method)
            assert "request_body" not in output
            assert "response_body" not in output

    def test_iret_s01_detail_no_request_response_bodies(self):
        """IRET-S01: full artifact output has no raw request/response bodies."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        dto = svc.retrieve_detail(_FILTERS)
        envelope = IntelligenceFormatter.build_envelope(_FILTERS, None)
        output = IntelligenceFormatter.format_json(dto, envelope)
        assert "request_body" not in output
        assert "response_body" not in output

    def test_iret_s02_no_raw_headers_cookies_tokens(self):
        """IRET-S02: no raw headers, cookies, or tokens in output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        for method in ("retrieve_status", "retrieve_summary"):
            output = self._json_string(svc, method)
            output_lower = output.lower()
            assert "authorization" not in output_lower
            assert "cookie" not in output_lower

    def test_iret_s03_no_credentials_secrets_pii(self):
        """IRET-S03: no credentials, secrets, or PII in output."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        for method in ("retrieve_status", "retrieve_summary"):
            output = self._json_string(svc, method)
            output_lower = output.lower()
            assert "password" not in output_lower
            assert "secret" not in output_lower
            assert "credential" not in output_lower

    def test_iret_s04_endpoint_ids_are_sanitized_identifiers(self):
        """IRET-S04: endpoint_id values in artifact are sanitized Phase 4 identifiers."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        result = svc.retrieve_detail(_FILTERS)
        assert isinstance(result, dict)
        endpoints = result.get("endpoints", [])
        assert len(endpoints) > 0
        for ep in endpoints:
            ep_id = ep.get("endpoint_id", "")
            # Sanitized endpoint IDs use Phase 4 generated identifiers (ep_NNN style)
            assert isinstance(ep_id, str)
            assert len(ep_id) > 0
            # Should not be raw URLs or contain protocol schemes
            assert "://" not in ep_id

    def test_iret_s05_s3_artifact_ref_is_intelligence_path(self):
        """IRET-S05: s3_artifact_ref is only the S3 key path (starts with 'intelligence/')."""
        svc = _make_svc(metadata=_COMPLETE_METADATA, artifact=_S3_ARTIFACT)
        dto = svc.retrieve_status(_FILTERS)
        assert isinstance(dto, IntelligenceStatusDTO)
        assert dto.s3_artifact_ref is not None
        assert dto.s3_artifact_ref.startswith("intelligence/")
        # Should not be a full S3 URL
        assert "s3://" not in dto.s3_artifact_ref
        assert "https://" not in dto.s3_artifact_ref


# ---------------------------------------------------------------------------
# IRET-RO01, IRET-RO02 — read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant:
    def test_iret_ro01_all_retrieve_calls_leave_repo_write_calls_empty(self):
        """IRET-RO01: all retrieve_* calls → repo.write_calls is empty."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)

        svc.retrieve_status(_FILTERS)
        svc.retrieve_summary(_FILTERS)
        svc.retrieve_detail(_FILTERS)
        svc.retrieve_methodology(_FILTERS)

        assert repo.write_calls == [], f"Repository write methods were called: {repo.write_calls}"

    def test_iret_ro02_all_retrieve_calls_leave_publisher_write_calls_empty(self):
        """IRET-RO02: all retrieve_* calls → publisher.write_calls is empty."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)

        svc.retrieve_status(_FILTERS)
        svc.retrieve_summary(_FILTERS)
        svc.retrieve_detail(_FILTERS)
        svc.retrieve_methodology(_FILTERS)

        assert publisher.write_calls == [], (
            f"Publisher write methods were called: {publisher.write_calls}"
        )

    def test_iret_ro01_not_found_path_also_read_only(self):
        """IRET-RO01: not-found paths do not trigger any write calls."""
        repo = MockIntelligenceRepo(metadata=None)
        publisher = MockIntelligencePublisher(artifact=None)
        svc = IntelligenceRetrievalService(repo, publisher)

        svc.retrieve_status(_FILTERS)
        svc.retrieve_summary(_FILTERS)
        svc.retrieve_detail(_FILTERS)

        assert repo.write_calls == []
        assert publisher.write_calls == []

    def test_iret_ro02_failed_job_path_also_read_only(self):
        """IRET-RO02: FAILED job retrieval does not trigger any write calls."""
        repo = MockIntelligenceRepo(metadata=_FAILED_METADATA)
        publisher = MockIntelligencePublisher(artifact=None)
        svc = IntelligenceRetrievalService(repo, publisher)

        svc.retrieve_status(_FILTERS)
        svc.retrieve_summary(_FILTERS)

        assert repo.write_calls == []
        assert publisher.write_calls == []


# ---------------------------------------------------------------------------
# Dispatch integration tests (format_json via dispatch)
# ---------------------------------------------------------------------------


class TestDispatchIntegration:
    def test_dispatch_intelligence_status_json(self):
        """dispatch returns valid JSON for intelligence-status command."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="intelligence-status", output="json")
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        parsed = json.loads(output)
        assert "_notice" in parsed
        assert "data" in parsed

    def test_dispatch_intelligence_summary_json(self):
        """dispatch returns valid JSON for intelligence-summary command."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="intelligence-summary", output="json")
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_dispatch_intelligence_detail_json(self):
        """dispatch returns valid JSON for intelligence-detail command."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="intelligence-detail", output="json")
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_dispatch_intelligence_methodology_json(self):
        """dispatch returns valid JSON for intelligence-methodology command."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="intelligence-methodology", output="json")
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        parsed = json.loads(output)
        assert "data" in parsed

    def test_dispatch_unknown_command_returns_not_found(self):
        """dispatch returns IntelligenceNotFoundDTO for unknown command."""
        repo = MockIntelligenceRepo(metadata=_COMPLETE_METADATA)
        publisher = MockIntelligencePublisher(artifact=_S3_ARTIFACT)
        svc = IntelligenceRetrievalService(repo, publisher)
        args = _make_args(retrieve_command="unknown-command", output="json")
        output = dispatch_intelligence_retrieve(args, svc, IntelligenceFormatter)
        parsed = json.loads(output)
        assert parsed["data"]["reason"] == "UNKNOWN_COMMAND"


# ---------------------------------------------------------------------------
# Evidence Governance Workstream A1.3d.2 -- retrieve intelligence-* succeeds
# under three config/custody_periods.json `intelligence`-class shapes, with
# zero CustodyPeriodConfigLoader.resolve calls, zero HoldRepository(
# construction, and zero governed-write calls (Technical Design Section
# 20.4/20.12; ADR Invariant 31).
# ---------------------------------------------------------------------------

_CUSTODY_FIXTURE_VARIANTS = [
    pytest.param(
        {"evidentiary_classes": {"intelligence": {}}},
        id="intelligence_present_empty",
    ),
    pytest.param(
        {"evidentiary_classes": {"intelligence": {"staging": 30}}},
        id="intelligence_present_unrelated_stage_only",
    ),
    pytest.param(
        {"evidentiary_classes": {}},
        id="intelligence_key_absent",
    ),
]

_RETRIEVAL_STAGE_CONFIG = StageConfig(
    stage="dev",
    region="us-east-1",
    aws_profile="test",
    config_bucket="bucket",
    audit_metadata_table="table",
    orchestrator_function_name="orchestrator",
    scheduler_group_name="group",
    schedule_name_prefix="rcp-dev",
    scheduler_execution_target_arn="arn:aws:lambda:us-east-1:123:function:execution",
    scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:123:function:finalization",
    scheduler_role_arn="arn:aws:iam::123:role/scheduler",
)


class _RetrievalFakeStageConfigLoader:
    def __init__(self, *args, **kwargs):
        pass

    def load(self, stage, env=None):
        return _RETRIEVAL_STAGE_CONFIG


class _RetrievalFakeDynamoDBClient:
    """Read-only-shaped fake: defines get_item only -- any put_item/
    update_item/transact_write_items call (a governed write) raises
    AttributeError, which surfaces as a non-zero CLI exit code and fails
    the test's exit_code==0 assertion."""

    def __init__(self, item: dict):
        from release_confidence_platform.storage.dynamodb_codec import encode_item

        self._encoded_item = encode_item(item)
        self.get_item_calls: list = []

    def get_item(self, **kwargs):
        self.get_item_calls.append(kwargs)
        return {"Item": self._encoded_item}


class _RetrievalFakeSession:
    def __init__(self, dynamodb_client):
        self._dynamodb_client = dynamodb_client

    def client(self, name):
        if name == "dynamodb":
            return self._dynamodb_client
        if name == "s3":
            return object()
        raise AssertionError(name)  # pragma: no cover - defensive


class _RetrievalFakeAwsClientFactory:
    instances: list = []

    def __init__(self, stage_config):
        self.stage_config = stage_config
        self._session = _RetrievalFakeSession(_RETRIEVAL_DYNAMODB_CLIENT_HOLDER["client"])
        _RetrievalFakeAwsClientFactory.instances.append(self)


_RETRIEVAL_DYNAMODB_CLIENT_HOLDER: dict = {}


class TestRetrieveIntelligenceCustodyConfigIndependence:
    """A1.3d.2: `retrieve intelligence-*` must succeed regardless of the
    `intelligence` evidence class's configuration state in
    config/custody_periods.json, and must never resolve custody
    configuration or construct hold coordination -- the retrieve dispatch
    block in operator_cli/main.py has no reference to either."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        _RetrievalFakeAwsClientFactory.instances = []
        _RETRIEVAL_DYNAMODB_CLIENT_HOLDER.clear()
        yield

    def _apply_patches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, custody_config
    ) -> tuple[list, list]:
        monkeypatch.setattr(
            stage_config_module, "StageConfigLoader", _RetrievalFakeStageConfigLoader
        )
        monkeypatch.setattr(
            aws_client_factory_module, "AwsClientFactory", _RetrievalFakeAwsClientFactory
        )

        # Write this parametrization case's fixture variant to a real,
        # temporary config/custody_periods.json. The REAL
        # CustodyPeriodConfigLoader class is used (not a replacement fake)
        # so that, should a future regression ever cause the retrieve
        # dispatch path to call CustodyPeriodConfigLoader.resolve(), it
        # would run the real loader against this genuinely-distinct on-disk
        # shape -- including raising ConfigError for the absent-key/
        # absent-stage variants -- rather than silently passing against an
        # artificial stub that intercepts before any real behavior runs.
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "custody_periods.json").write_text(
            json.dumps(custody_config), encoding="utf-8"
        )
        loader_cls = custody_period_config_module.CustodyPeriodConfigLoader
        monkeypatch.setattr(loader_cls, "_default_root", staticmethod(lambda: tmp_path))

        original_resolve = loader_cls.resolve
        resolve_calls: list = []

        def _spy_resolve(self_, evidence_class, stage):
            resolve_calls.append((evidence_class, stage))
            return original_resolve(self_, evidence_class, stage)

        monkeypatch.setattr(loader_cls, "resolve", _spy_resolve)

        original_hold_repository_init = HoldRepository.__init__
        hold_repository_calls: list = []

        def _spy_init(self_, *args, **kwargs):
            hold_repository_calls.append((args, kwargs))
            original_hold_repository_init(self_, *args, **kwargs)

        monkeypatch.setattr(HoldRepository, "__init__", _spy_init)
        return resolve_calls, hold_repository_calls

    @pytest.mark.parametrize("custody_config", _CUSTODY_FIXTURE_VARIANTS)
    def test_retrieve_intelligence_status_succeeds_regardless_of_custody_config(
        self, monkeypatch, tmp_path, custody_config
    ):
        resolve_calls, hold_repository_calls = self._apply_patches(
            monkeypatch, tmp_path, custody_config
        )
        item = {
            **_COMPLETE_METADATA,
            "PK": "CLIENT#client1",
            "SK": ("AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#META"),
        }
        _RETRIEVAL_DYNAMODB_CLIENT_HOLDER["client"] = _RetrievalFakeDynamoDBClient(item)

        exit_code = main(
            [
                "retrieve",
                "intelligence-status",
                "--client",
                "client1",
                "--audit",
                "audit1",
                "--execution",
                "exec1",
                "--stage",
                "dev",
                "--output",
                "json",
            ]
        )

        assert exit_code == 0
        assert resolve_calls == [], (
            "retrieve intelligence-status must never call CustodyPeriodConfigLoader.resolve"
        )
        assert hold_repository_calls == [], (
            "retrieve intelligence-status must never construct HoldRepository"
        )

    @pytest.mark.parametrize("custody_config", _CUSTODY_FIXTURE_VARIANTS)
    def test_retrieve_intelligence_summary_succeeds_regardless_of_custody_config(
        self, monkeypatch, tmp_path, custody_config
    ):
        resolve_calls, hold_repository_calls = self._apply_patches(
            monkeypatch, tmp_path, custody_config
        )
        item = {
            **_COMPLETE_METADATA,
            "PK": "CLIENT#client1",
            "SK": ("AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#META"),
        }
        _RETRIEVAL_DYNAMODB_CLIENT_HOLDER["client"] = _RetrievalFakeDynamoDBClient(item)

        exit_code = main(
            [
                "retrieve",
                "intelligence-summary",
                "--client",
                "client1",
                "--audit",
                "audit1",
                "--execution",
                "exec1",
                "--stage",
                "dev",
                "--output",
                "json",
            ]
        )

        assert exit_code == 0
        assert resolve_calls == [], (
            "retrieve intelligence-summary must never call CustodyPeriodConfigLoader.resolve"
        )
        assert hold_repository_calls == [], (
            "retrieve intelligence-summary must never construct HoldRepository"
        )
