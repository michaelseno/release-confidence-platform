from pathlib import Path


LAMBDA_RESERVED_ENVIRONMENT_KEYS = {
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_LAMBDA_FUNCTION_NAME",
    "AWS_LAMBDA_FUNCTION_MEMORY_SIZE",
    "AWS_LAMBDA_FUNCTION_VERSION",
    "AWS_LAMBDA_INITIALIZATION_TYPE",
    "AWS_LAMBDA_LOG_GROUP_NAME",
    "AWS_LAMBDA_LOG_STREAM_NAME",
    "LAMBDA_TASK_ROOT",
    "LAMBDA_RUNTIME_DIR",
    "_HANDLER",
    "_X_AMZN_TRACE_ID",
}


def test_serverless_configuration_contains_required_stages_and_names() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")

    for stage in ("dev", "staging", "prod"):
        assert f"- {stage}" in serverless_yml

    assert "./plugins/stage-guard" in serverless_yml
    assert "release-confidence-platform" in serverless_yml
    assert "${self:provider.stage}-raw-results" in serverless_yml
    assert "${self:provider.stage}-metadata" in serverless_yml


def test_serverless_stage_guard_rejects_unsupported_stages() -> None:
    stage_guard = Path("infra/plugins/stage-guard.js").read_text(encoding="utf-8")

    assert '["dev", "staging", "prod"]' in stage_guard
    assert "Unsupported Serverless stage" in stage_guard
    assert '"before:package:initialize"' in stage_guard


def test_resource_fragments_reference_required_resources() -> None:
    s3_yml = Path("infra/resources/s3.yml").read_text(encoding="utf-8")
    dynamodb_yml = Path("infra/resources/dynamodb.yml").read_text(encoding="utf-8")

    assert "RawResultsBucket" in s3_yml
    assert "${self:custom.rawResultsBucketName}" in s3_yml
    assert "MetadataTable" in dynamodb_yml
    assert "${self:custom.metadataTableName}" in dynamodb_yml


def test_serverless_lambda_environment_avoids_reserved_keys() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")

    reserved_definitions = [
        key for key in LAMBDA_RESERVED_ENVIRONMENT_KEYS if f"    {key}:" in serverless_yml
    ]

    assert reserved_definitions == []
