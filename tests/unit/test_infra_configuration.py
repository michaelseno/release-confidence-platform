import zipfile
from pathlib import Path

import pytest
import yaml

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


# ---------------------------------------------------------------------------
# Evidence Governance Workstream A1.2 -- S3 Lifecycle / DynamoDB TTL+Streams /
# evidenceDisposalRecorderDLQ infrastructure (GitHub Issue #94).
#
# No YAML-parsing test pattern existed in this file prior to A1.2 (every test
# above is a plain-text substring assertion on Path.read_text()). These new
# tests add yaml.safe_load()-based syntax validation (per this subphase's
# explicit test-coverage requirement) while keeping every existing test's
# plain-text style untouched. yaml.safe_load() catches YAML syntax errors
# only -- it does NOT resolve Serverless Framework `${self:...}` variable
# references (those remain opaque strings to a plain YAML parser) and does
# NOT validate against the CloudFormation resource schema. Full
# variable-resolution validation (`sls print` / `sls package`) requires the
# Serverless CLI and Node toolchain and is a manual/CI step this Python test
# suite cannot execute standalone -- see
# test_serverless_variable_resolution_requires_serverless_cli below, which
# documents this boundary explicitly rather than faking a deeper check.
# ---------------------------------------------------------------------------

_EVIDENCE_RETENTION_TEMPLATE_FILES = (
    Path("infra/resources/s3.yml"),
    Path("infra/resources/dynamodb.yml"),
    Path("infra/resources/evidence-retention-dlq.yml"),
    Path("infra/serverless.yml"),
)

_EVIDENCE_CLASS_TO_S3_PREFIX = {
    "raw_evidence": "raw-results/",
    "intelligence": "intelligence/",
    "report": "reports/",
    "certificate": "integrity/",
}


def test_evidence_retention_template_files_are_syntactically_valid_yaml() -> None:
    """yaml.safe_load() must parse every A1.2-modified/new template file
    without raising -- this is the syntax-error catch this subphase's test
    coverage requires, given no yaml-parsing pattern previously existed in
    this repo's infra tests.
    """
    for path in _EVIDENCE_RETENTION_TEMPLATE_FILES:
        with path.open(encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh)
        assert isinstance(parsed, dict), f"{path} did not parse to a YAML mapping"


def test_serverless_variable_resolution_requires_serverless_cli() -> None:
    """Documents, rather than fakes, the boundary of the YAML-syntax check
    above: ${self:custom.custodyPeriodDays...} references are opaque strings
    to yaml.safe_load() and are never resolved by it. Confirming that a
    referenced custody-period stage key is genuinely absent (not silently
    defaulted) requires actually resolving Serverless variables, which
    requires invoking the Serverless CLI (`sls print --stage <stage>`) via
    Node -- a manual/CI step, not something this pytest suite runs.
    """
    pytest.skip(
        "Full serverless.yml variable resolution (sls print) requires the "
        "Serverless CLI/Node toolchain and is a manual/CI validation step, "
        "not something this Python test suite executes. This test exists to "
        "document that boundary explicitly rather than silently omitting it."
    )


def test_s3_lifecycle_configuration_has_one_tag_filtered_rule_per_evidence_class() -> None:
    with Path("infra/resources/s3.yml").open(encoding="utf-8") as fh:
        s3_template = yaml.safe_load(fh)

    rules = s3_template["Resources"]["RawResultsBucket"]["Properties"]["LifecycleConfiguration"][
        "Rules"
    ]
    assert len(rules) == len(_EVIDENCE_CLASS_TO_S3_PREFIX)

    rules_by_prefix = {rule["Filter"]["And"]["Prefix"]: rule for rule in rules}
    assert set(rules_by_prefix) == set(_EVIDENCE_CLASS_TO_S3_PREFIX.values())

    for rule in rules:
        assert rule["Status"] == "Enabled"
        tags = rule["Filter"]["And"]["Tags"]
        assert tags == [{"Key": "rcp-legal-hold", "Value": "false"}]
        assert "Expiration" in rule
        assert "Days" in rule["Expiration"]
        assert "NoncurrentVersionExpiration" in rule
        assert "NoncurrentDays" in rule["NoncurrentVersionExpiration"]


def test_s3_lifecycle_days_reference_custody_period_config_not_hardcoded() -> None:
    """AC-A1-5 / ADR Non-Negotiable Invariant 3: the custody-period duration
    must never be hardcoded in the CloudFormation resource literal. Assert
    every Days/NoncurrentDays value is a ${self:custom.custodyPeriodDays...}
    variable reference for the correct evidence class, and that no bare
    integer literal is used for either property anywhere in the file.
    """
    s3_yml_text = Path("infra/resources/s3.yml").read_text(encoding="utf-8")

    for evidence_class in _EVIDENCE_CLASS_TO_S3_PREFIX:
        reference = (
            f"${{self:custom.custodyPeriodDays.{evidence_class}.${{self:provider.stage}}}}"
        )
        assert s3_yml_text.count(reference) == 2, (
            f"expected exactly two references (Days + NoncurrentDays) to "
            f"{reference!r}"
        )

    for line in s3_yml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Days:") or stripped.startswith("NoncurrentDays:"):
            _, _, value = stripped.partition(":")
            value = value.strip()
            assert value.startswith("${self:custom.custodyPeriodDays."), (
                f"Days/NoncurrentDays value must reference custom.custodyPeriodDays, "
                f"got: {stripped!r}"
            )


def test_s3_notification_configuration_routes_through_eventbridge() -> None:
    with Path("infra/resources/s3.yml").open(encoding="utf-8") as fh:
        s3_template = yaml.safe_load(fh)

    notification_config = s3_template["Resources"]["RawResultsBucket"]["Properties"][
        "NotificationConfiguration"
    ]
    assert "EventBridgeConfiguration" in notification_config


def test_dynamodb_ttl_specification_targets_ttl_disposal_at_attribute() -> None:
    with Path("infra/resources/dynamodb.yml").open(encoding="utf-8") as fh:
        dynamodb_template = yaml.safe_load(fh)

    ttl_spec = dynamodb_template["Resources"]["MetadataTable"]["Properties"][
        "TimeToLiveSpecification"
    ]
    assert ttl_spec == {"AttributeName": "ttl_disposal_at", "Enabled": True}


def test_dynamodb_stream_specification_uses_new_and_old_images() -> None:
    with Path("infra/resources/dynamodb.yml").open(encoding="utf-8") as fh:
        dynamodb_template = yaml.safe_load(fh)

    stream_spec = dynamodb_template["Resources"]["MetadataTable"]["Properties"][
        "StreamSpecification"
    ]
    assert stream_spec == {"StreamViewType": "NEW_AND_OLD_IMAGES"}


def test_evidence_disposal_recorder_dlq_and_alarm_resources_present() -> None:
    with Path("infra/resources/evidence-retention-dlq.yml").open(encoding="utf-8") as fh:
        dlq_template = yaml.safe_load(fh)

    resources = dlq_template["Resources"]
    assert resources["evidenceDisposalRecorderDLQ"]["Type"] == "AWS::SQS::Queue"

    alarm = resources["evidenceDisposalRecorderDLQAlarm"]
    assert alarm["Type"] == "AWS::CloudWatch::Alarm"
    alarm_properties = alarm["Properties"]
    assert alarm_properties["Namespace"] == "AWS/SQS"
    assert alarm_properties["MetricName"] == "ApproximateNumberOfMessagesVisible"
    assert alarm_properties["Threshold"] == 0
    assert alarm_properties["ComparisonOperator"] == "GreaterThanThreshold"


def test_evidence_retention_dlq_template_defines_no_lambda_function() -> None:
    """This subphase must not define the evidenceDisposalRecorder Lambda
    function body, its event source mappings, or any handler behavior
    (explicitly out of scope -- A1.3/A1.4). The DLQ resource file must stand
    on its own without any AWS::Lambda::Function resource.
    """
    with Path("infra/resources/evidence-retention-dlq.yml").open(encoding="utf-8") as fh:
        dlq_template = yaml.safe_load(fh)

    resource_types = {
        resource.get("Type") for resource in dlq_template["Resources"].values()
    }
    assert "AWS::Lambda::Function" not in resource_types
    assert "AWS::Lambda::EventSourceMapping" not in resource_types


def test_serverless_registers_evidence_retention_dlq_resource_file() -> None:
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")
    assert "${file(resources/evidence-retention-dlq.yml)}" in serverless_yml


def test_serverless_defines_no_evidence_disposal_recorder_function() -> None:
    """Explicitly out of scope for A1.2: the evidenceDisposalRecorder Lambda
    function body and its event-source-mapping wiring belong to A1.3/A1.4.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    assert "evidenceDisposalRecorder" not in serverless_template.get("functions", {})


def test_custody_period_days_config_defines_no_value_for_any_stage() -> None:
    """AC-A1-5 / ADR Non-Negotiable Invariant 3: no custody-period duration
    value may exist anywhere in serverless.yml for any evidence class or any
    stage. Each per-evidence-class block must be an empty mapping -- a
    hardcoded number, an empty string silently treated as zero, or a
    populated stage key would all violate this constraint.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    custody_period_days = serverless_template["custom"]["custodyPeriodDays"]
    assert set(custody_period_days) == set(_EVIDENCE_CLASS_TO_S3_PREFIX)
    for evidence_class, stage_values in custody_period_days.items():
        assert stage_values == {}, (
            f"custom.custodyPeriodDays.{evidence_class} must remain an empty "
            f"mapping (no stage may have a value supplied), got: {stage_values!r}"
        )
