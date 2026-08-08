from __future__ import annotations

import urllib.parse
from typing import Any

import pytest
from botocore.exceptions import ClientError

from packages.core.exceptions import EngineError
from packages.storage.s3_client import S3StorageClient


def _client_error(code: str, message: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation_name=operation)


def _assert_backend_s3_diagnostics_do_not_leak(message: str) -> None:
    prohibited_values = [
        "qa-runtime-bucket",
        "raw-results/client123/audit456/run789/results.json",
        "client123",
        "audit456",
        "token=super-secret",
        "super-secret",
        "api_key=abc123",
        "password=hunter2",
    ]
    for value in prohibited_values:
        assert value not in message
    assert "aws_error_message" not in message


class HeadFailingS3:
    def __init__(self, code: str, message: str = "failed"):
        self.error = _client_error(code, message, "HeadObject")

    def head_object(self, **kwargs):  # noqa: ARG002
        raise self.error


class PutFailingS3:
    def __init__(self, code: str, message: str = "failed"):
        self.error = _client_error(code, message, "PutObject")

    def head_object(self, **kwargs):  # noqa: ARG002
        raise _client_error("404", "missing", "HeadObject")

    def put_object(self, **kwargs):  # noqa: ARG002
        raise self.error


class GenericPutFailingS3:
    def head_object(self, **kwargs):  # noqa: ARG002
        raise _client_error("404", "missing", "HeadObject")

    def put_object(self, **kwargs):  # noqa: ARG002
        raise RuntimeError("internal token=super-secret")


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_backend_object_exists_returns_false_for_not_found_codes(code: str) -> None:
    storage = S3StorageClient("runtime-bucket", HeadFailingS3(code, "missing object"))

    assert storage.object_exists("raw-results/client/audit/run/results.json") is False


@pytest.mark.parametrize("code", ["AccessDenied", "Forbidden"])
def test_backend_object_exists_permission_errors_are_actionable_and_sanitized(
    code: str,
) -> None:
    storage = S3StorageClient(
        "runtime-bucket", HeadFailingS3(code, "denied for token=super-secret")
    )

    with pytest.raises(EngineError) as exc:
        storage.object_exists("raw-results/client123/audit456/run789/results.json")

    assert exc.value.error_type == "STORAGE_PERMISSION_ERROR"
    assert "S3 runtime bucket permission denied" in exc.value.message
    assert f"aws_error_code={code}" in exc.value.message
    assert "operation=head_object" in exc.value.message
    assert "key_prefix=raw-results" in exc.value.message
    assert "required_permission=s3:GetObject+s3:ListBucket" in exc.value.message
    assert "client123" not in exc.value.message
    assert "audit456" not in exc.value.message
    assert "super-secret" not in exc.value.message


def test_backend_object_exists_no_such_bucket_is_storage_config_error() -> None:
    storage = S3StorageClient("runtime-bucket", HeadFailingS3("NoSuchBucket", "missing bucket"))

    with pytest.raises(EngineError) as exc:
        storage.object_exists("configs/client/client_config.json")

    assert exc.value.error_type == "STORAGE_CONFIG_ERROR"
    assert "S3 runtime bucket not found or not configured" in exc.value.message
    assert "aws_error_code=NoSuchBucket" in exc.value.message
    assert "operation=head_object" in exc.value.message
    assert "key_prefix=configs" in exc.value.message


@pytest.mark.parametrize(
    ("code", "expected_type", "expected_message"),
    [
        ("AccessDenied", "STORAGE_PERMISSION_ERROR", "S3 runtime bucket permission denied"),
        ("NoSuchBucket", "STORAGE_CONFIG_ERROR", "S3 runtime bucket not found or not configured"),
        ("SlowDown", "STORAGE_ERROR", "S3 runtime storage operation failed"),
    ],
)
def test_backend_write_json_put_object_errors_are_safe_and_actionable(
    code: str, expected_type: str, expected_message: str
) -> None:
    storage = S3StorageClient(
        "runtime-bucket", PutFailingS3(code, "contains Authorization: Bearer abc123")
    )

    with pytest.raises(EngineError) as exc:
        storage.write_json("raw-results/client123/audit456/run789/results.json", {"ok": True})

    assert exc.value.error_type == expected_type
    assert expected_message in exc.value.message
    assert f"aws_error_code={code}" in exc.value.message
    assert "operation=put_object" in exc.value.message
    assert "key_prefix=raw-results" in exc.value.message
    assert "required_permission=s3:PutObject" in exc.value.message
    assert "client123" not in exc.value.message
    assert "audit456" not in exc.value.message
    assert "Bearer abc123" not in exc.value.message


def test_backend_generic_put_client_error_diagnostics_do_not_leak_qa_probe_values() -> None:
    key = "raw-results/client123/audit456/run789/results.json"
    storage = S3StorageClient(
        "qa-runtime-bucket",
        PutFailingS3(
            "SlowDown",
            "bucket qa-runtime-bucket failed for "
            f"s3://qa-runtime-bucket/{key}?token=super-secret "
            "api_key=abc123 password=hunter2",
        ),
    )

    with pytest.raises(EngineError) as exc:
        storage.write_json(key, {"ok": True})

    assert exc.value.error_type == "STORAGE_ERROR"
    assert "S3 runtime storage operation failed" in exc.value.message
    assert "aws_error_code=SlowDown" in exc.value.message
    assert "operation=put_object" in exc.value.message
    assert "key_prefix=raw-results" in exc.value.message
    assert "required_permission=s3:PutObject" in exc.value.message
    _assert_backend_s3_diagnostics_do_not_leak(exc.value.message)


def test_backend_generic_head_client_error_diagnostics_do_not_leak_qa_probe_values() -> None:
    key = "raw-results/client123/audit456/run789/results.json"
    storage = S3StorageClient(
        "qa-runtime-bucket",
        HeadFailingS3(
            "SlowDown",
            "bucket qa-runtime-bucket failed for "
            f"s3://qa-runtime-bucket/{key}?token=super-secret "
            "api_key=abc123 password=hunter2",
        ),
    )

    with pytest.raises(EngineError) as exc:
        storage.object_exists(key)

    assert exc.value.error_type == "STORAGE_ERROR"
    assert "S3 runtime storage operation failed" in exc.value.message
    assert "aws_error_code=SlowDown" in exc.value.message
    assert "operation=head_object" in exc.value.message
    assert "key_prefix=raw-results" in exc.value.message
    assert "required_permission=s3:GetObject+s3:ListBucket" in exc.value.message
    _assert_backend_s3_diagnostics_do_not_leak(exc.value.message)


def test_backend_write_json_generic_put_error_maps_to_safe_storage_error() -> None:
    storage = S3StorageClient("runtime-bucket", GenericPutFailingS3())

    with pytest.raises(EngineError) as exc:
        storage.write_json("raw-results/client123/audit456/run789/results.json", {"ok": True})

    assert exc.value.error_type == "STORAGE_ERROR"
    assert exc.value.message == "S3 config write failed"
    assert "super-secret" not in exc.value.message


class RecordingPutS3:
    """Evidence Governance Workstream A1.3e (Technical Design Section 18.1,
    18.6, 18.3): stub recording put_object calls for `write_json` (Category
    5 -- configuration/input artifacts). `head_object` reports the key as
    not-found so `write_json(..., overwrite=False)` reaches `put_object`
    without raising `CONFIG_OBJECT_EXISTS`.
    """

    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, Any]] = []

    def head_object(self, **kwargs):  # noqa: ARG002
        raise _client_error("404", "missing", "HeadObject")

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_object_calls.append(kwargs)
        return {}


def _assert_write_json_put_object_carries_no_governance_tagging(kwargs: dict[str, Any]) -> None:
    # `configs/*` is Category 5 (Technical Design Section 18.1, 18.6) --
    # explicitly excluded from A1.3's custody/hold mechanism. `write_json`
    # today never sets `Tagging` at all, but the governed requirement this
    # test enforces is narrower than "Tagging must be absent": only the two
    # RCP-prefixed governance tag keys must never appear, checked only if
    # `Tagging` happens to be present. Asserting outright absence of
    # `Tagging` would over-constrain this method against legitimate future
    # unrelated tagging.
    if "Tagging" in kwargs:
        parsed_tags = urllib.parse.parse_qs(kwargs["Tagging"])
        assert "rcp-legal-hold" not in parsed_tags
        assert "rcp-evidence-class" not in parsed_tags


def test_write_json_create_carries_no_governance_tagging() -> None:
    s3 = RecordingPutS3()
    storage = S3StorageClient("runtime-bucket", s3)

    storage.write_json("configs/client123/client_config.json", {"ok": True}, overwrite=False)

    assert len(s3.put_object_calls) == 1
    _assert_write_json_put_object_carries_no_governance_tagging(s3.put_object_calls[0])


def test_write_json_force_overwrite_carries_no_governance_tagging() -> None:
    s3 = RecordingPutS3()
    storage = S3StorageClient("runtime-bucket", s3)

    storage.write_json("configs/client123/client_config.json", {"ok": True}, overwrite=True)

    assert len(s3.put_object_calls) == 1
    _assert_write_json_put_object_carries_no_governance_tagging(s3.put_object_calls[0])
