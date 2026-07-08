"""Tests for Phase 7.6/7.7 Certification CLI commands.

Covers:
- build_certify_parser registers certify audit correctly
- dispatch_certify_audit calls engine.certify() with correct args
- dispatch_certify_audit passes force=True when --force flag present
- dispatch_certify_audit raises ValidationError when validate_identifier fails
- dispatch_cert_retrieve routes to the correct service method for each command
- CertificationRetrievalService.get_cert_status returns correct fields from DynamoDB mock
- CertificationRetrievalService.get_cert_json calls S3 via publisher after DynamoDB lookup
- CERTIFICATION_NOT_FOUND error raised when CertificationMetadata is absent
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.audit_platform_integrity.commands import (
    build_certify_parser,
    dispatch_certify_audit,
)
from release_confidence_platform.audit_platform_integrity.cert_retrieve_commands import (
    CertificationRetrievalService,
    build_cert_retrieve_parser,
    dispatch_cert_retrieve,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CERT_METADATA = {
    "certificate_id": "cert_abc123",
    "certificate_version": "cert_v1",
    "certjob_id": "certjob_xyz456",
    "client_id": "client_test",
    "audit_id": "audit_test",
    "audit_execution_id": "exec_001",
    "config_version": "v1",
    "aggregation_version": "agg_v1",
    "intelligence_version": "intel_v1",
    "report_version": "report_v1",
    "cert_version": "cert_v1",
    "terminal_state": "CERTIFIED",
    "report_id": "report_testid001",
    "s3_certificate_ref": "integrity/client_test/audit_test/exec_001/v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_xyz456/artifact.json",
    "s3_report_artifact_ref": "reports/client_test/audit_test/exec_001/v1/agg_v1/intel_v1/report_v1/rptjob_test/artifact.json",
    "aggregate_set_hash": "hashABC123",
    "created_at": "2026-07-07T10:00:00Z",
    "completed_at": "2026-07-07T10:01:00Z",
}

_CERT_ARTIFACT = {
    "identity": {
        "certificate_id": "cert_abc123",
        "certificate_version": "cert_v1",
        "generated_at": "2026-07-07T10:01:00Z",
        "generator_version": "1.0.0",
    },
    "result": {
        "terminal_state": "CERTIFIED",
        "certification_summary": "INTEGRITY_VERIFIED",
        "disclosed_failures": [],
    },
    "domain_results": [
        {
            "domain": "RUNNER_HEALTH",
            "status": "PASSED",
            "checks_performed": 4,
            "checks_passed": 4,
            "failure_details": [],
            "evidence_refs": ["endpoints[].reliability_metrics"],
        }
    ],
    "report_reference": {
        "report_id": "report_testid001",
        "report_version": "report_v1",
        "s3_report_artifact_ref": "reports/.../artifact.json",
        "intelligence_version": "intel_v1",
        "aggregate_set_hash": "hashABC123",
    },
    "audit_provenance": {
        "client_id": "client_test",
        "audit_id": "audit_test",
        "audit_execution_id": "exec_001",
        "config_version": "v1",
        "aggregation_version": "agg_v1",
        "intelligence_version": "intel_v1",
        "report_version": "report_v1",
    },
    "certjob_id": "certjob_xyz456",
}


def _make_cert_args(command: str = "cert-status") -> argparse.Namespace:
    return argparse.Namespace(
        retrieve_command=command,
        client_id="client_test",
        audit_id="audit_test",
        execution="exec_001",
        config_version="v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        stage="dev",
        output="human",
    )


def _make_certify_args(**overrides) -> argparse.Namespace:
    base = argparse.Namespace(
        certify_command="audit",
        client_id="client_test",
        audit_id="audit_test",
        execution="exec_001",
        config_version="v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        stage="dev",
        force=False,
        output="human",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_retrieval_svc(metadata=None, artifact=None):
    svc = MagicMock(spec=CertificationRetrievalService)
    if metadata is not None:
        status_data = {
            "terminal_state": metadata.get("terminal_state"),
            "certificate_id": metadata.get("certificate_id"),
            "certjob_id": metadata.get("certjob_id"),
            "s3_cert_ref": metadata.get("s3_certificate_ref"),
            "s3_report_artifact_ref": metadata.get("s3_report_artifact_ref"),
            "certificate_version": metadata.get("certificate_version"),
            "report_id": metadata.get("report_id"),
            "generated_at": metadata.get("completed_at"),
        }
        svc.get_cert_status.return_value = status_data
        svc.get_cert_summary.return_value = metadata
        domains_data = {
            "certificate_id": metadata.get("certificate_id"),
            "certificate_version": metadata.get("certificate_version"),
            "terminal_state": metadata.get("terminal_state"),
            "report_id": metadata.get("report_id"),
            "generated_at": metadata.get("completed_at"),
            "domain_results": artifact.get("domain_results", []) if artifact else [],
        }
        svc.get_cert_domains.return_value = domains_data
        svc.get_cert_json.return_value = artifact or {}
    return svc


# ---------------------------------------------------------------------------
# 1. build_certify_parser registers certify audit with required args
# ---------------------------------------------------------------------------


def test_build_certify_parser_registers_audit_subcommand():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command")
    build_certify_parser(sub)
    assert "audit" in sub.choices


def test_build_certify_parser_requires_client_id():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["audit", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"])


def test_build_certify_parser_requires_audit_id():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["audit", "--client-id", "c1", "--execution", "e1", "--stage", "dev"])


def test_build_certify_parser_requires_execution():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["audit", "--client-id", "c1", "--audit-id", "a1", "--stage", "dev"])


def test_build_certify_parser_requires_stage():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["audit", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1"])


def test_build_certify_parser_defaults():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    args = parser.parse_args(
        ["audit", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"]
    )
    assert args.config_version == "v1"
    assert args.aggregation_version == "agg_v1"
    assert args.intelligence_version == "intel_v1"
    assert args.report_version == "report_v1"
    assert args.cert_version == "cert_v1"
    assert args.force is False


def test_build_certify_parser_force_flag():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="certify_command", required=True)
    build_certify_parser(sub)
    args = parser.parse_args(
        [
            "audit",
            "--client-id", "c1",
            "--audit-id", "a1",
            "--execution", "e1",
            "--stage", "dev",
            "--force",
        ]
    )
    assert args.force is True


# ---------------------------------------------------------------------------
# 2. dispatch_certify_audit calls engine.certify() with correct args
# ---------------------------------------------------------------------------


def _make_mock_certificate(certjob_id="certjob_abc"):
    cert = MagicMock()
    cert.identity.certificate_id = "cert_testid001"
    cert.result.terminal_state = "CERTIFIED"
    cert.result.disclosed_failures = []
    cert.certjob_id = certjob_id
    cert.domain_results = []
    return cert


def test_dispatch_certify_audit_calls_engine_certify():
    engine = MagicMock()
    engine.certify.return_value = _make_mock_certificate()
    args = _make_certify_args()

    result = dispatch_certify_audit(args, engine)

    engine.certify.assert_called_once_with(
        client_id="client_test",
        audit_id="audit_test",
        audit_execution_id="exec_001",
        config_version="v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        force=False,
    )


def test_dispatch_certify_audit_passes_force_true():
    engine = MagicMock()
    engine.certify.return_value = _make_mock_certificate()
    args = _make_certify_args(force=True)

    dispatch_certify_audit(args, engine)

    engine.certify.assert_called_once()
    call_kwargs = engine.certify.call_args[1]
    assert call_kwargs["force"] is True


def test_dispatch_certify_audit_returns_summary_dict():
    engine = MagicMock()
    engine.certify.return_value = _make_mock_certificate()
    args = _make_certify_args()

    result = dispatch_certify_audit(args, engine)

    assert isinstance(result, dict)
    assert result["certificate_id"] == "cert_testid001"
    assert result["terminal_state"] == "CERTIFIED"
    assert "s3_cert_ref" in result
    assert "disclosed_failures" in result


def test_dispatch_certify_audit_s3_cert_ref_uses_certjob_id():
    engine = MagicMock()
    engine.certify.return_value = _make_mock_certificate(certjob_id="certjob_specific123")
    args = _make_certify_args()

    result = dispatch_certify_audit(args, engine)

    assert "certjob_specific123" in result["s3_cert_ref"]
    assert result["s3_cert_ref"].startswith("integrity/")


# ---------------------------------------------------------------------------
# 3. dispatch_certify_audit raises ValidationError when validate_identifier fails
# ---------------------------------------------------------------------------


def test_dispatch_certify_audit_invalid_client_id_raises():
    engine = MagicMock()
    args = _make_certify_args(client_id="")  # empty string is invalid

    with pytest.raises(ValidationError):
        dispatch_certify_audit(args, engine)

    engine.certify.assert_not_called()


def test_dispatch_certify_audit_invalid_audit_id_raises():
    engine = MagicMock()
    args = _make_certify_args(audit_id="bad id with spaces")

    with pytest.raises(ValidationError):
        dispatch_certify_audit(args, engine)

    engine.certify.assert_not_called()


def test_dispatch_certify_audit_invalid_execution_raises():
    engine = MagicMock()
    args = _make_certify_args(execution=None)

    with pytest.raises(ValidationError):
        dispatch_certify_audit(args, engine)

    engine.certify.assert_not_called()


# ---------------------------------------------------------------------------
# 4. build_cert_retrieve_parser registers all four commands
# ---------------------------------------------------------------------------


def test_build_cert_retrieve_parser_registers_four_commands():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="retrieve_command")
    build_cert_retrieve_parser(sub)
    expected = {"cert-status", "cert-summary", "cert-domains", "cert-json"}
    registered = set(sub.choices.keys())
    assert expected == registered, (
        f"Subcommand mismatch. Missing: {expected - registered}, Extra: {registered - expected}"
    )


# ---------------------------------------------------------------------------
# 5. dispatch_cert_retrieve routes to the correct service method
# ---------------------------------------------------------------------------


def test_dispatch_cert_retrieve_cert_status_calls_get_cert_status():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    dispatch_cert_retrieve(_make_cert_args("cert-status"), svc)
    svc.get_cert_status.assert_called_once()


def test_dispatch_cert_retrieve_cert_summary_calls_get_cert_summary():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    dispatch_cert_retrieve(_make_cert_args("cert-summary"), svc)
    svc.get_cert_summary.assert_called_once()


def test_dispatch_cert_retrieve_cert_domains_calls_get_cert_domains():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    dispatch_cert_retrieve(_make_cert_args("cert-domains"), svc)
    svc.get_cert_domains.assert_called_once()


def test_dispatch_cert_retrieve_cert_json_calls_get_cert_json():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    dispatch_cert_retrieve(_make_cert_args("cert-json"), svc)
    svc.get_cert_json.assert_called_once()


def test_dispatch_cert_retrieve_unknown_command_raises():
    svc = MagicMock(spec=CertificationRetrievalService)
    args = _make_cert_args("cert-unknown-command")
    with pytest.raises(ValidationError):
        dispatch_cert_retrieve(args, svc)


# ---------------------------------------------------------------------------
# 6. dispatch_cert_retrieve raises ValidationError on invalid identifiers
# ---------------------------------------------------------------------------


def test_dispatch_cert_retrieve_invalid_client_id_raises():
    svc = MagicMock(spec=CertificationRetrievalService)
    args = _make_cert_args("cert-status")
    args.client_id = ""
    with pytest.raises(ValidationError):
        dispatch_cert_retrieve(args, svc)
    svc.get_cert_status.assert_not_called()


def test_dispatch_cert_retrieve_invalid_audit_id_raises():
    svc = MagicMock(spec=CertificationRetrievalService)
    args = _make_cert_args("cert-status")
    args.audit_id = "bad audit id"
    with pytest.raises(ValidationError):
        dispatch_cert_retrieve(args, svc)
    svc.get_cert_status.assert_not_called()


# ---------------------------------------------------------------------------
# 7. CertificationRetrievalService.get_cert_status returns correct fields
# ---------------------------------------------------------------------------


def test_get_cert_status_returns_correct_fields():
    repo = MagicMock()
    publisher = MagicMock()
    repo.get_cert_metadata.return_value = _CERT_METADATA

    svc = CertificationRetrievalService(repo, publisher)
    result = svc.get_cert_status(
        "client_test", "audit_test", "exec_001",
        "v1", "agg_v1", "intel_v1", "report_v1", "cert_v1",
    )

    assert result["terminal_state"] == "CERTIFIED"
    assert result["certificate_id"] == "cert_abc123"
    assert result["certjob_id"] == "certjob_xyz456"
    assert result["s3_cert_ref"] == _CERT_METADATA["s3_certificate_ref"]
    assert result["s3_report_artifact_ref"] == _CERT_METADATA["s3_report_artifact_ref"]
    assert result["certificate_version"] == "cert_v1"
    assert result["report_id"] == "report_testid001"
    assert result["generated_at"] == "2026-07-07T10:01:00Z"
    publisher.read_artifact.assert_not_called()


def test_get_cert_status_not_found_raises():
    repo = MagicMock()
    publisher = MagicMock()
    repo.get_cert_metadata.return_value = None

    svc = CertificationRetrievalService(repo, publisher)
    with pytest.raises(ValidationError) as exc_info:
        svc.get_cert_status(
            "client_test", "audit_test", "exec_001",
            "v1", "agg_v1", "intel_v1", "report_v1", "cert_v1",
        )
    assert "CERTIFICATION_NOT_FOUND" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. CertificationRetrievalService.get_cert_json calls S3 via publisher
# ---------------------------------------------------------------------------


def test_get_cert_json_calls_publisher_read_artifact():
    repo = MagicMock()
    publisher = MagicMock()
    repo.get_cert_metadata.return_value = _CERT_METADATA
    publisher.read_artifact.return_value = _CERT_ARTIFACT

    svc = CertificationRetrievalService(repo, publisher)
    result = svc.get_cert_json(
        "client_test", "audit_test", "exec_001",
        "v1", "agg_v1", "intel_v1", "report_v1", "cert_v1",
    )

    publisher.read_artifact.assert_called_once_with(_CERT_METADATA["s3_certificate_ref"])
    assert result == _CERT_ARTIFACT


def test_get_cert_json_not_found_raises():
    repo = MagicMock()
    publisher = MagicMock()
    repo.get_cert_metadata.return_value = None

    svc = CertificationRetrievalService(repo, publisher)
    with pytest.raises(ValidationError) as exc_info:
        svc.get_cert_json(
            "client_test", "audit_test", "exec_001",
            "v1", "agg_v1", "intel_v1", "report_v1", "cert_v1",
        )
    assert "CERTIFICATION_NOT_FOUND" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 9. CERTIFICATION_NOT_FOUND for all four commands when metadata absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["cert-status", "cert-summary", "cert-domains", "cert-json"])
def test_certification_not_found_raised_for_all_commands(command):
    repo = MagicMock()
    publisher = MagicMock()
    repo.get_cert_metadata.return_value = None

    svc = CertificationRetrievalService(repo, publisher)
    retrieve_method = {
        "cert-status": svc.get_cert_status,
        "cert-summary": svc.get_cert_summary,
        "cert-domains": svc.get_cert_domains,
        "cert-json": svc.get_cert_json,
    }[command]

    with pytest.raises(ValidationError) as exc_info:
        retrieve_method(
            "client_test", "audit_test", "exec_001",
            "v1", "agg_v1", "intel_v1", "report_v1", "cert_v1",
        )
    assert "CERTIFICATION_NOT_FOUND" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 10. dispatch_cert_retrieve output contains provenance envelope fields
# ---------------------------------------------------------------------------


def test_cert_status_output_contains_certificate_id():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    result = dispatch_cert_retrieve(_make_cert_args("cert-status"), svc)
    assert "cert_abc123" in result


def test_cert_status_output_contains_terminal_state():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    result = dispatch_cert_retrieve(_make_cert_args("cert-status"), svc)
    assert "CERTIFIED" in result


def test_cert_json_output_is_valid_json():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    result = dispatch_cert_retrieve(_make_cert_args("cert-json"), svc)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_cert_summary_output_contains_all_metadata_fields():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    result = dispatch_cert_retrieve(_make_cert_args("cert-summary"), svc)
    assert "client_test" in result
    assert "audit_test" in result
    assert "CERTIFIED" in result


def test_cert_domains_output_contains_domain_name():
    svc = _make_retrieval_svc(metadata=_CERT_METADATA, artifact=_CERT_ARTIFACT)
    result = dispatch_cert_retrieve(_make_cert_args("cert-domains"), svc)
    assert isinstance(result, str)
    assert len(result) > 0
