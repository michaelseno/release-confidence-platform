from pathlib import Path


def test_serverless_configuration_contains_required_stages_and_names() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")

    for stage in ("dev", "staging", "prod"):
        assert f"- {stage}" in serverless_yml

    assert "release-confidence-platform" in serverless_yml
    assert "${self:provider.stage}-raw-results" in serverless_yml
    assert "${self:provider.stage}-metadata" in serverless_yml


def test_resource_fragments_reference_required_resources() -> None:
    s3_yml = Path("infra/resources/s3.yml").read_text(encoding="utf-8")
    dynamodb_yml = Path("infra/resources/dynamodb.yml").read_text(encoding="utf-8")

    assert "RawResultsBucket" in s3_yml
    assert "${self:custom.rawResultsBucketName}" in s3_yml
    assert "MetadataTable" in dynamodb_yml
    assert "${self:custom.metadataTableName}" in dynamodb_yml
