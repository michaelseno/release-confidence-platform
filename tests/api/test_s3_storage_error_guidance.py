from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.operator_cli.result import render_error
from release_confidence_platform.storage.s3_client import S3StorageClient


class FailingS3Put:
    def __init__(self, code: str, message: str):
        self.error = ClientError(
            {"Error": {"Code": code, "Message": message}}, operation_name="PutObject"
        )

    def head_object(self, **kwargs):  # noqa: ARG002
        raise ClientError(
            {"Error": {"Code": "404", "Message": "not found"}}, operation_name="HeadObject"
        )

    def put_object(self, **kwargs):  # noqa: ARG002
        raise self.error


@pytest.mark.parametrize(
    ("aws_code", "expected_error_type", "expected_message"),
    [
        ("NoSuchBucket", "STORAGE_CONFIG_ERROR", "S3 config bucket not found for stage"),
        (
            "AccessDenied",
            "STORAGE_PERMISSION_ERROR",
            "S3 config bucket write permission denied",
        ),
    ],
)
def test_known_s3_write_failures_are_actionable_and_sanitized(
    aws_code: str, expected_error_type: str, expected_message: str
):
    storage = S3StorageClient(
        "configured-bucket", FailingS3Put(aws_code, "contains token=super-secret")
    )

    with pytest.raises(EngineError) as exc:
        storage.write_json("configs/client1/audits/audit1/audit_config.json", {"ok": True})

    assert exc.value.error_type == expected_error_type
    assert expected_message in exc.value.message
    assert f"aws_error_code={aws_code}" in exc.value.message
    assert "operation=put_object" in exc.value.message
    assert "key_prefix=configs" in exc.value.message
    assert "client1" not in exc.value.message
    assert "audit1" not in exc.value.message
    assert "super-secret" not in exc.value.message

    rendered = render_error("audit create", "dev", exc.value.error_type, exc.value.message)
    assert "correct the error and retry" not in rendered
    assert "config/stages/dev.json config_bucket" in rendered
    assert "export RCP_CONFIG_BUCKET=<real-dev-bucket>" in rendered
    assert "RCP_AUDIT_METADATA_TABLE=<real-metadata-table>" in rendered
    assert "RCP_AWS_PROFILE=<aws-profile>" in rendered
    assert "RCP_AWS_REGION=<aws-region>" in rendered
    assert "not just assigned as shell-local variables" in rendered
    assert "bucket exists in the configured region" in rendered
    assert "selected AWS profile has s3:PutObject and s3:HeadObject permissions" in rendered


def test_generic_s3_write_failure_keeps_structured_sanitized_diagnostic_context():
    storage = S3StorageClient(
        "configured-bucket",
        FailingS3Put("SlowDown", "retry later with Authorization: Bearer abc123"),
    )

    with pytest.raises(EngineError) as exc:
        storage.write_json("configs/client1/client_config.json", {"password": "secret-value"})

    assert exc.value.error_type == "STORAGE_ERROR"
    assert "S3 config write failed" in exc.value.message
    assert "aws_error_code=SlowDown" in exc.value.message
    assert "operation=put_object" in exc.value.message
    assert "key_prefix=configs" in exc.value.message
    assert "[REDACTED]" in exc.value.message
    assert "Bearer abc123" not in exc.value.message
    assert "secret-value" not in exc.value.message

    rendered = render_error("audit create", "dev", exc.value.error_type, exc.value.message)
    assert "config/stages/dev.json config_bucket" in rendered
    assert "export RCP_CONFIG_BUCKET=<real-dev-bucket>" in rendered
    assert "correct the error and retry" not in rendered
