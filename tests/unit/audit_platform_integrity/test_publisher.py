"""Tests for CertificationPublisher S3 artifact write/read.

Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8.1):
write_artifact() additionally owns a HoldRepository-backed hold-state read
and write-time rcp-legal-hold/rcp-evidence-class object tagging, plus the
canonical 11-segment key parser (_parse_cert_key_identity) that replaces the
prior prefix-only assertion as write_artifact's authoritative structural
validation. All write_artifact tests below construct a hold-aware
CertificationPublisher via _make_hold_aware_publisher(); read_artifact is
unaffected and its existing coverage is preserved unchanged.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.audit_platform_integrity.identity import build_cert_s3_key
from release_confidence_platform.audit_platform_integrity.publisher import (
    CertificationPublisher,
    _parse_cert_key_identity,
)
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


def _make_publisher(s3_client: MagicMock | None = None) -> tuple[CertificationPublisher, MagicMock]:
    if s3_client is None:
        s3_client = MagicMock()
    return CertificationPublisher(_BUCKET, s3_client), s3_client


def _make_hold_aware_publisher(
    hold_state: dict | None = None, s3_client: MagicMock | None = None
) -> tuple[CertificationPublisher, MagicMock, _FakeHoldRepository]:
    if s3_client is None:
        s3_client = MagicMock()
    hold_repository = _FakeHoldRepository(hold_state)
    return CertificationPublisher(_BUCKET, s3_client, hold_repository), s3_client, hold_repository


# ---------------------------------------------------------------------------
# write_artifact tests
# ---------------------------------------------------------------------------


def test_write_artifact_calls_put_object_with_correct_bucket_and_key():
    """write_artifact must call s3_client.put_object with the correct bucket and key."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    s3.put_object.assert_called_once()
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == _BUCKET
    assert call_kwargs["Key"] == _KEY


def test_write_artifact_serializes_with_sort_keys():
    """write_artifact must serialize with sort_keys=True for determinism."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    artifact = {"z_field": 1, "a_field": 2, "m_field": 3}
    publisher.write_artifact(_KEY, artifact)
    body_bytes = s3.put_object.call_args.kwargs["Body"]
    expected_bytes = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
    assert body_bytes == expected_bytes
    parsed = json.loads(body_bytes.decode("utf-8"))
    assert list(parsed.keys()) == sorted(parsed.keys())


def test_write_artifact_sets_content_type_json():
    """write_artifact must set ContentType to application/json."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "application/json"


def test_write_artifact_raises_storage_error_on_s3_failure():
    """write_artifact must raise StorageError with S3_CERTIFICATE_WRITE_FAILURE on failure."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    s3.put_object.side_effect = Exception("S3 unavailable")
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "S3_CERTIFICATE_WRITE_FAILURE"
    assert "S3 unavailable" in str(exc_info.value)


def test_write_artifact_raises_assertion_error_on_non_integrity_prefix():
    """write_artifact must raise StorageError (STORAGE_ERROR) when the key does
    not match the canonical 11-segment integrity/ shape -- the canonical key
    parser (Technical Design Section 20.8.1) replaces the prior
    AssertionError-based prefix-only guard as write_artifact's authoritative
    structural validation."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    bad_key = "reports/client1/audit1/artifact.json"
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(bad_key, _ARTIFACT)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    s3.put_object.assert_not_called()


def test_write_artifact_raises_assertion_error_on_intelligence_prefix():
    """write_artifact must reject keys with intelligence/ prefix (STORAGE_ERROR)."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    bad_key = "intelligence/client1/audit1/artifact.json"
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(bad_key, _ARTIFACT)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    s3.put_object.assert_not_called()


def test_write_artifact_raises_assertion_error_on_raw_results_prefix():
    """write_artifact must reject keys with raw-results/ prefix (STORAGE_ERROR)."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    bad_key = "raw-results/client1/audit1/artifact.json"
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(bad_key, _ARTIFACT)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    s3.put_object.assert_not_called()


def test_write_artifact_uses_integrity_prefix():
    """Successful write_artifact must use the integrity/ key prefix."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    call_kwargs = s3.put_object.call_args.kwargs
    assert call_kwargs["Key"].startswith("integrity/")


def test_write_artifact_determinism():
    """write_artifact must produce byte-identical output for identical inputs."""
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    first_body = s3.put_object.call_args.kwargs["Body"]
    s3.reset_mock()
    publisher.write_artifact(_KEY, _ARTIFACT)
    second_body = s3.put_object.call_args.kwargs["Body"]
    assert first_body == second_body


# ---------------------------------------------------------------------------
# write_artifact -- governance preflight
# Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8.1)
# ---------------------------------------------------------------------------


def test_write_artifact_missing_hold_repository_wins_over_malformed_key():
    """The hold-configuration check must run before key parsing -- a missing
    HoldRepository must be reported (HOLD_COORDINATION_NOT_CONFIGURED) even
    for a simultaneously malformed key, never STORAGE_ERROR."""
    publisher, s3 = _make_publisher()  # hold_repository=None
    # 10 segments -- missing certjob_id.
    malformed_key = "integrity/c1/a1/e1/cfg1/agg1/int1/rpt1/cert1/artifact.json"
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(malformed_key, _ARTIFACT)
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    s3.get_object.assert_not_called()
    s3.put_object.assert_not_called()


def test_write_artifact_derives_client_id_and_audit_id_from_key():
    key = build_cert_s3_key(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        certjob_id="certjob_abc",
    )
    assert key == _KEY
    assert _parse_cert_key_identity(key) == ("client1", "audit1")


def test_write_artifact_tag_values_unheld():
    publisher, s3, _hold = _make_hold_aware_publisher(None)
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert (
        s3.put_object.call_args.kwargs["Tagging"]
        == "rcp-legal-hold=false&rcp-evidence-class=certificate"
    )


def test_write_artifact_tag_values_active_hold():
    publisher, s3, _hold = _make_hold_aware_publisher({"status": "ACTIVE"})
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert (
        s3.put_object.call_args.kwargs["Tagging"]
        == "rcp-legal-hold=true&rcp-evidence-class=certificate"
    )


def test_write_artifact_tag_values_released_hold():
    publisher, s3, _hold = _make_hold_aware_publisher({"status": "RELEASED"})
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert (
        s3.put_object.call_args.kwargs["Tagging"]
        == "rcp-legal-hold=false&rcp-evidence-class=certificate"
    )


def test_write_artifact_uses_consistent_read_for_hold_lookup():
    publisher, s3, hold_repository = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)
    assert hold_repository.calls == [("client1", "audit1", True)]


def test_write_artifact_raises_hold_coordination_not_configured_when_hold_repository_none():
    """Key is well-formed here -- isolates the hold-config check alone."""
    publisher, s3 = _make_publisher()
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"


def test_write_artifact_zero_aws_calls_when_hold_repository_none():
    publisher, s3 = _make_publisher()
    with pytest.raises(StorageError):
        publisher.write_artifact(_KEY, _ARTIFACT)
    assert s3.method_calls == []


def test_publisher_never_calls_custody_period_config_loader(monkeypatch):
    from release_confidence_platform.config.custody_period_config import (
        CustodyPeriodConfigLoader,
    )

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("CertificationPublisher must never call CustodyPeriodConfigLoader")

    monkeypatch.setattr(CustodyPeriodConfigLoader, "resolve", _raise_if_called)
    publisher, s3, _hold = _make_hold_aware_publisher()
    publisher.write_artifact(_KEY, _ARTIFACT)  # must not raise from the loader


# ---------------------------------------------------------------------------
# write_artifact -- canonical 11-segment key parser malformed-key matrix
# Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8.1)
# ---------------------------------------------------------------------------

_MALFORMED_KEYS = [
    pytest.param(
        "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/certjob_abc/artifact.json",
        id="10_segments_drop_cert_version",
    ),
    pytest.param(
        "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/extra/certjob_abc/artifact.json",
        id="12_segments_extra_inserted",
    ),
    pytest.param(
        "integrityWRONG/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json",
        id="wrong_segment_0",
    ),
    pytest.param(
        "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.txt",
        id="wrong_segment_10",
    ),
    pytest.param(
        "integrity//audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json",
        id="empty_client_segment",
    ),
    pytest.param(
        "integrity/client1//exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json",
        id="empty_audit_segment",
    ),
    pytest.param(
        "/integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json",
        id="leading_slash",
    ),
    pytest.param(
        "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc/artifact.json/",
        id="trailing_slash",
    ),
    pytest.param(
        "integrity/client1/audit1/exec1/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_abc//artifact.json",
        id="doubled_slash_extra_segment",
    ),
]


@pytest.mark.parametrize("bad_key", _MALFORMED_KEYS)
def test_write_artifact_rejects_malformed_key(bad_key):
    """Each malformed-key case is run with a CONFIGURED, non-None
    hold_repository -- isolating the key defect as the sole variable."""
    publisher, s3, hold_repository = _make_hold_aware_publisher()
    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(bad_key, _ARTIFACT)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    assert "client1" not in str(exc_info.value)
    assert "audit1" not in str(exc_info.value)
    assert hold_repository.calls == []
    s3.put_object.assert_not_called()


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
