import zipfile
from pathlib import Path

import pytest

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


def test_serverless_grants_prefix_scoped_s3_listbucket_for_runtime_bucket() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")

    assert "- s3:ListBucket" in serverless_yml
    assert "arn:aws:s3:::${self:custom.rawResultsBucketName}" in serverless_yml
    assert "StringLike:" in serverless_yml
    assert "s3:prefix:" in serverless_yml
    for prefix in ("raw-results/*", "configs/*", "data-pools/*"):
        assert f"- {prefix}" in serverless_yml


def test_serverless_scopes_runtime_s3_object_permissions_to_required_prefixes() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")

    assert "arn:aws:s3:::${self:custom.rawResultsBucketName}/*" not in serverless_yml
    for prefix in ("raw-results", "configs", "data-pools"):
        assert f"arn:aws:s3:::${{self:custom.rawResultsBucketName}}/{prefix}/*" in serverless_yml
    assert "- s3:GetObject" in serverless_yml
    assert "- s3:HeadObject" in serverless_yml
    assert "- s3:PutObject" in serverless_yml


def test_backend_lambda_requirements_manifest_includes_requests() -> None:
    requirements = Path("apps/backend/requirements.txt").read_text(encoding="utf-8")

    assert "requests>=2.31,<3" in requirements


def test_serverless_packages_backend_python_requirements() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")
    package_json = Path("infra/package.json").read_text(encoding="utf-8")

    assert "serverless-python-requirements" in serverless_yml
    assert "pythonRequirements:" in serverless_yml
    assert "fileName: ../apps/backend/requirements.txt" in serverless_yml
    assert "slim: true" in serverless_yml
    assert "dockerizePip: non-linux" in serverless_yml
    assert '"serverless-python-requirements"' in package_json


def test_serverless_artifact_contains_backend_handler_and_requests_dependencies_if_present() -> (
    None
):
    artifact = Path("infra/.serverless/release-confidence-platform.zip")
    if not artifact.exists():
        pytest.skip("serverless package artifact is not present; run infra package validation")
    inputs = [
        Path("infra/serverless.yml"),
        Path("infra/package.json"),
        Path("apps/backend/requirements.txt"),
    ]
    if artifact.stat().st_mtime < max(path.stat().st_mtime for path in inputs):
        pytest.skip("serverless package artifact predates packaging configuration inputs")

    with zipfile.ZipFile(artifact) as zip_file:
        names = set(zip_file.namelist())

    assert "apps/backend/handlers/orchestrator_handler.py" in names
    assert "requests/__init__.py" in names
    for dependency in ("urllib3", "certifi", "charset_normalizer", "idna"):
        assert f"{dependency}/__init__.py" in names
