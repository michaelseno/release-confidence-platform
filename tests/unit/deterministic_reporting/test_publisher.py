"""Tests for ReportPublisher S3 artifact write/read.

Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.6):
write_artifact() additionally owns a HoldRepository-backed hold-state read
and write-time rcp-legal-hold/rcp-evidence-class object tagging. All
write_artifact tests below construct a hold-aware ReportPublisher via
_make_hold_aware_publisher(); read_artifact is unaffected and its existing
coverage is preserved unchanged.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.deterministic_reporting.publisher import (
    ReportPublisher,
    _parse_report_key_identity,
    _report_tagging,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUCKET = "test-bucket"
_KEY = "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/artifact.json"
_ARTIFACT = {"report_version": "rpt_v1", "status": "COMPLETE", "score": "0.850"}


class _FakeHoldRepository:
    def __init__(self, hold_state: dict | None = None, *, raises: Exception | None = None):
        self.hold_state = hold_state
        self.raises = raises
        self.calls: list[tuple] = []

    def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
        self.calls.append((client_id, audit_id, consistent_read))
        if self.raises is not None:
            raise self.raises
        return self.hold_state


def _make_publisher(s3_client: MagicMock | None = None) -> tuple[ReportPublisher, MagicMock]:
    if s3_client is None:
        s3_client = MagicMock()
    return ReportPublisher(_BUCKET, s3_client), s3_client


def _make_hold_aware_publisher(
    hold_state: dict | None = None, s3_client: MagicMock | None = None
) -> tuple[ReportPublisher, MagicMock, _FakeHoldRepository]:
    if s3_client is None:
        s3_client = MagicMock()
    hold_repository = _FakeHoldRepository(hold_state)
    return ReportPublisher(_BUCKET, s3_client, hold_repository), s3_client, hold_repository


def _make_s3_body(content: dict) -> MagicMock:
    body_mock = MagicMock()
    body_mock.read.return_value = json.dumps(content).encode("utf-8")
    return body_mock


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


def test_constructor_defaults_hold_repository_to_none():
    publisher, _ = _make_publisher()
    assert publisher._hold_repository is None


def test_constructor_accepts_positional_hold_repository():
    hold_repository = _FakeHoldRepository()
    publisher = ReportPublisher(_BUCKET, MagicMock(), hold_repository)
    assert publisher._hold_repository is hold_repository


# ---------------------------------------------------------------------------
# write_artifact tests
# ---------------------------------------------------------------------------


def test_write_artifact_calls_put_object_with_correct_bucket_and_key():
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == _BUCKET
    assert call_kwargs["Key"] == _KEY


def test_write_artifact_serializes_with_sort_keys():
    publisher, s3, _hold = _make_hold_aware_publisher()
    artifact = {"z_field": 1, "a_field": 2, "m_field": 3}
    publisher.write_artifact(_KEY, artifact)
    body_bytes = s3.put_object.call_args.kwargs["Body"]
    parsed = json.loads(body_bytes.decode("utf-8"))
    expected_bytes = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
    assert body_bytes == expected_bytes
    assert list(parsed.keys()) == sorted(parsed.keys())


def test_write_artifact_sets_content_type_json():
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "application/json"


def test_write_artifact_raises_storage_error_on_s3_failure():
    publisher, s3, _hold = _make_hold_aware_publisher()
    s3.put_object.side_effect = Exception("S3 unavailable")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "S3_WRITE_FAILED"
    assert "S3 unavailable" in str(exc_info.value)


def test_write_artifact_determinism():
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    first_body = s3.put_object.call_args.kwargs["Body"]
    s3.reset_mock()
    publisher.write_artifact(_KEY, _ARTIFACT)
    second_body = s3.put_object.call_args.kwargs["Body"]
    assert first_body == second_body


def test_write_artifact_uses_reports_prefix():
    publisher, s3, _hold = _make_hold_aware_publisher()
    key = "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_xyz/artifact.json"
    publisher.write_artifact(key, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Key"].startswith("reports/")


# ---------------------------------------------------------------------------
# write_artifact -- governance preflight
# ---------------------------------------------------------------------------


def test_write_artifact_fails_closed_when_hold_repository_not_configured():
    publisher, s3 = _make_publisher()  # hold_repository=None
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    s3.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# 9-segment key parser tests (_parse_report_key_identity)
# ---------------------------------------------------------------------------


def test_parse_report_key_identity_valid():
    assert _parse_report_key_identity(_KEY) == ("client1", "audit1")


@pytest.mark.parametrize(
    "key",
    [
        "wrong-prefix/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/artifact.json",
        "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc",
        "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/wrong.json",
        "reports//audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/artifact.json",
        "reports/client1//exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/artifact.json",
        # 8-segment (Phase 5 shape) must NOT parse as a Phase 6 key.
        "reports/client1/audit1/exec1/agg_v1/intel_v1/rptjob_abc/artifact.json",
    ],
)
def test_parse_report_key_identity_malformed(key):
    with pytest.raises(StorageError) as exc_info:
        _parse_report_key_identity(key)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    assert key not in str(exc_info.value)


def test_parse_report_key_identity_error_message_never_echoes_key():
    bad_key = "reports/SENSITIVE_CLIENT/SENSITIVE_AUDIT/exec1/agg_v1/intel_v1/rpt_v1/x"
    with pytest.raises(StorageError) as exc_info:
        _parse_report_key_identity(bad_key)
    assert "SENSITIVE_CLIENT" not in str(exc_info.value)
    assert "SENSITIVE_AUDIT" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Strongly-consistent hold-read assertion
# ---------------------------------------------------------------------------


def test_write_artifact_reads_hold_state_with_consistent_read_true():
    publisher, s3, hold_repository = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert hold_repository.calls == [("client1", "audit1", True)]


def test_write_artifact_reads_hold_before_put_object():
    order: list = []

    class _Hold:
        def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
            order.append("get_legal_hold")
            return None

    class _S3:
        def put_object(self, **kwargs):
            order.append("put_object")
            return {}

    publisher = ReportPublisher(_BUCKET, _S3(), _Hold())
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert order == ["get_legal_hold", "put_object"]


# ---------------------------------------------------------------------------
# Tag-value assertions -- held / unheld
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hold_state,expected_tag",
    [
        (None, "rcp-legal-hold=false&rcp-evidence-class=report"),
        ({"status": "ACTIVE"}, "rcp-legal-hold=true&rcp-evidence-class=report"),
        ({"status": "RELEASED"}, "rcp-legal-hold=false&rcp-evidence-class=report"),
    ],
)
def test_report_tagging_exact_string_per_state(hold_state, expected_tag):
    assert _report_tagging(hold_state) == expected_tag


@pytest.mark.parametrize(
    "hold_state,expected_tag",
    [
        (None, "rcp-legal-hold=false&rcp-evidence-class=report"),
        ({"status": "ACTIVE"}, "rcp-legal-hold=true&rcp-evidence-class=report"),
        ({"status": "RELEASED"}, "rcp-legal-hold=false&rcp-evidence-class=report"),
    ],
)
def test_write_artifact_passes_correct_tagging_string(hold_state, expected_tag):
    publisher, s3, _hold = _make_hold_aware_publisher(hold_state)
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert s3.put_object.call_args.kwargs["Tagging"] == expected_tag


# ---------------------------------------------------------------------------
# Hold-error-identity-preservation
# ---------------------------------------------------------------------------


def test_write_artifact_storage_error_from_hold_read_propagates_unchanged():
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher._hold_repository.raises = StorageError("hold read failed", "SOME_OTHER_CODE")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "SOME_OTHER_CODE"
    s3.put_object.assert_not_called()


def test_write_artifact_unexpected_exception_from_hold_read_maps_to_storage_error():
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher._hold_repository.raises = RuntimeError("unexpected failure")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    s3.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# S3-write-failure (governance-aware path)
# ---------------------------------------------------------------------------


def test_write_artifact_s3_failure_after_successful_hold_read():
    publisher, s3, hold_repository = _make_hold_aware_publisher()
    s3.put_object.side_effect = Exception("bucket unavailable")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "S3_WRITE_FAILED"
    assert hold_repository.calls, "hold read must still occur before the S3 failure"


# ---------------------------------------------------------------------------
# read_artifact tests
# ---------------------------------------------------------------------------


def test_read_artifact_calls_get_object():
    publisher, s3 = _make_publisher()
    s3.get_object.return_value = {"Body": _make_s3_body(_ARTIFACT)}
    publisher.read_artifact(_KEY)
    s3.get_object.assert_called_once_with(Bucket=_BUCKET, Key=_KEY)


def test_read_artifact_returns_parsed_dict():
    publisher, s3 = _make_publisher()
    s3.get_object.return_value = {"Body": _make_s3_body(_ARTIFACT)}
    result = publisher.read_artifact(_KEY)
    assert result == _ARTIFACT
    assert isinstance(result, dict)


def test_read_artifact_raises_storage_error_on_s3_failure():
    publisher, s3 = _make_publisher()
    s3.get_object.side_effect = Exception("bucket not found")
    with pytest.raises(StorageError) as exc_info:
        publisher.read_artifact(_KEY)
    assert exc_info.value.error_type == "S3_READ_FAILED"
    assert "bucket not found" in str(exc_info.value)
