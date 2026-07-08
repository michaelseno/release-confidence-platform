"""Tests for CertificationPublisher S3 artifact write."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.audit_platform_integrity.publisher import CertificationPublisher
from release_confidence_platform.core.exceptions import StorageError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUCKET = "test-bucket"
_KEY = "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json"
_ARTIFACT = {
    "terminal_state": "CERTIFIED",
    "certificate_id": "cert_abc",
    "cert_version": "cert_v1",
}


def _make_publisher(s3_client: MagicMock | None = None) -> tuple[CertificationPublisher, MagicMock]:
    if s3_client is None:
        s3_client = MagicMock()
    return CertificationPublisher(_BUCKET, s3_client), s3_client


# ---------------------------------------------------------------------------
# write_artifact tests
# ---------------------------------------------------------------------------


def test_write_artifact_calls_put_object_with_correct_bucket_and_key():
    """write_artifact must call s3_client.put_object with the correct bucket and key."""
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == _BUCKET
    assert call_kwargs["Key"] == _KEY


def test_write_artifact_serializes_with_sort_keys():
    """write_artifact must serialize with sort_keys=True for determinism."""
    publisher, s3 = _make_publisher()
    artifact = {"z_field": 1, "a_field": 2, "m_field": 3}
    publisher.write_artifact(_KEY, artifact)
    body_bytes = s3.put_object.call_args.kwargs["Body"]
    expected_bytes = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
    assert body_bytes == expected_bytes
    parsed = json.loads(body_bytes.decode("utf-8"))
    assert list(parsed.keys()) == sorted(parsed.keys())


def test_write_artifact_sets_content_type_json():
    """write_artifact must set ContentType to application/json."""
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "application/json"


def test_write_artifact_raises_storage_error_on_s3_failure():
    """write_artifact must raise StorageError with S3_CERTIFICATE_WRITE_FAILURE on failure."""
    publisher, s3 = _make_publisher()
    s3.put_object.side_effect = Exception("S3 unavailable")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "S3_CERTIFICATE_WRITE_FAILURE"
    assert "S3 unavailable" in str(exc_info.value)


def test_write_artifact_raises_assertion_error_on_non_integrity_prefix():
    """write_artifact must raise AssertionError if key does not start with 'integrity/'."""
    publisher, s3 = _make_publisher()
    bad_key = "reports/client1/audit1/artifact.json"
    with pytest.raises(AssertionError) as exc_info:
        publisher.write_artifact(bad_key, _ARTIFACT)
    assert "integrity/" in str(exc_info.value)


def test_write_artifact_raises_assertion_error_on_intelligence_prefix():
    """write_artifact must reject keys with intelligence/ prefix."""
    publisher, _ = _make_publisher()
    bad_key = "intelligence/client1/audit1/artifact.json"
    with pytest.raises(AssertionError):
        publisher.write_artifact(bad_key, _ARTIFACT)


def test_write_artifact_raises_assertion_error_on_raw_results_prefix():
    """write_artifact must reject keys with raw-results/ prefix."""
    publisher, _ = _make_publisher()
    bad_key = "raw-results/client1/audit1/artifact.json"
    with pytest.raises(AssertionError):
        publisher.write_artifact(bad_key, _ARTIFACT)


def test_write_artifact_uses_integrity_prefix():
    """Successful write_artifact must use the integrity/ key prefix."""
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Key"].startswith("integrity/")


def test_write_artifact_determinism():
    """write_artifact must produce byte-identical output for identical inputs."""
    publisher, s3 = _make_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    first_body = s3.put_object.call_args.kwargs["Body"]
    s3.reset_mock()
    publisher.write_artifact(_KEY, _ARTIFACT)
    second_body = s3.put_object.call_args.kwargs["Body"]
    assert first_body == second_body


# ---------------------------------------------------------------------------
# read_artifact tests
# ---------------------------------------------------------------------------


def test_read_artifact_raises_assertion_error_on_non_integrity_prefix():
    """read_artifact must raise AssertionError if key does not start with 'integrity/'."""
    publisher, s3 = _make_publisher()
    bad_key = "reports/client1/audit1/artifact.json"
    with pytest.raises(AssertionError) as exc_info:
        publisher.read_artifact(bad_key)
    assert "integrity/" in str(exc_info.value)


def test_read_artifact_raises_assertion_error_on_intelligence_prefix():
    """read_artifact must reject keys with intelligence/ prefix."""
    publisher, _ = _make_publisher()
    bad_key = "intelligence/client1/audit1/artifact.json"
    with pytest.raises(AssertionError):
        publisher.read_artifact(bad_key)


def test_read_artifact_accepts_integrity_prefix():
    """read_artifact must not raise AssertionError when key starts with 'integrity/'."""
    publisher, s3 = _make_publisher()
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"terminal_state": "CERTIFIED"}')}
    result = publisher.read_artifact(_KEY)
    assert result["terminal_state"] == "CERTIFIED"
