"""Tests for ReportPublisher S3 artifact write/read."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.deterministic_reporting.publisher import ReportPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUCKET = "test-bucket"
_KEY = "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_abc/artifact.json"
_ARTIFACT = {"report_version": "rpt_v1", "status": "COMPLETE", "score": "0.850"}


def _make_publisher(s3_client: MagicMock | None = None) -> tuple[ReportPublisher, MagicMock]:
    if s3_client is None:
        s3_client = MagicMock()
    return ReportPublisher(_BUCKET, s3_client), s3_client


def _make_s3_body(content: dict) -> MagicMock:
    body_mock = MagicMock()
    body_mock.read.return_value = json.dumps(content).encode("utf-8")
    return body_mock


# ---------------------------------------------------------------------------
# write_artifact tests
# ---------------------------------------------------------------------------


def test_write_artifact_calls_put_object_with_correct_bucket_and_key():
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == _BUCKET
    assert call_kwargs["Key"] == _KEY


def test_write_artifact_serializes_with_sort_keys():
    publisher, s3 = _make_publisher()
    artifact = {"z_field": 1, "a_field": 2, "m_field": 3}
    publisher.write_artifact(_KEY, artifact)
    body_bytes = s3.put_object.call_args.kwargs["Body"]
    parsed = json.loads(body_bytes.decode("utf-8"))
    expected_bytes = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
    assert body_bytes == expected_bytes
    assert list(parsed.keys()) == sorted(parsed.keys())


def test_write_artifact_sets_content_type_json():
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "application/json"


def test_write_artifact_raises_storage_error_on_s3_failure():
    publisher, s3 = _make_publisher()
    s3.put_object.side_effect = Exception("S3 unavailable")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "S3_WRITE_FAILED"
    assert "S3 unavailable" in str(exc_info.value)


def test_write_artifact_determinism():
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    first_body = s3.put_object.call_args.kwargs["Body"]
    s3.reset_mock()
    publisher.write_artifact(_KEY, _ARTIFACT)
    second_body = s3.put_object.call_args.kwargs["Body"]
    assert first_body == second_body


def test_write_artifact_uses_reports_prefix():
    publisher, s3 = _make_publisher()
    key = "reports/client1/audit1/exec1/agg_v1/intel_v1/rpt_v1/rptjob_xyz/artifact.json"
    publisher.write_artifact(key, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Key"].startswith("reports/")


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
