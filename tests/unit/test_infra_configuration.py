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
    # Legal-Hold Correction B2 (Technical Design Section 19.5.8) added a
    # fifth rule, for the retention-markers/ prefix, that is deliberately
    # NOT tag-filtered (a marker is never itself subject to legal hold) --
    # see test_s3_lifecycle_configuration_has_untagged_retention_marker_rule
    # below for its own dedicated coverage. Scope this test to only the
    # tag-filtered rules, so it continues to assert exactly one rule per
    # evidence class without being broken by that structurally distinct
    # addition.
    tag_filtered_rules = [rule for rule in rules if "And" in rule["Filter"]]
    assert len(tag_filtered_rules) == len(_EVIDENCE_CLASS_TO_S3_PREFIX)

    rules_by_prefix = {rule["Filter"]["And"]["Prefix"]: rule for rule in tag_filtered_rules}
    assert set(rules_by_prefix) == set(_EVIDENCE_CLASS_TO_S3_PREFIX.values())

    for rule in tag_filtered_rules:
        assert rule["Status"] == "Enabled"
        tags = rule["Filter"]["And"]["Tags"]
        assert tags == [{"Key": "rcp-legal-hold", "Value": "false"}]
        assert "Expiration" in rule
        assert "Days" in rule["Expiration"]
        assert "NoncurrentVersionExpiration" in rule
        assert "NoncurrentDays" in rule["NoncurrentVersionExpiration"]


def test_s3_lifecycle_configuration_has_untagged_retention_marker_rule() -> None:
    """Legal-Hold Correction B2 (Technical Design Section 19.5.8; ADR
    Non-Negotiable Invariant 22): the canary marker's disposal rule is
    structurally simpler than the four evidence-class rules above -- no
    tag-filter condition, since a marker is never itself subject to legal
    hold (it is metadata ABOUT a hold, not evidence a hold protects).
    Confirmed here directly rather than assumed.
    """
    with Path("infra/resources/s3.yml").open(encoding="utf-8") as fh:
        s3_template = yaml.safe_load(fh)

    rules = s3_template["Resources"]["RawResultsBucket"]["Properties"]["LifecycleConfiguration"][
        "Rules"
    ]
    marker_rules = [rule for rule in rules if rule["Filter"].get("Prefix") == "retention-markers/"]
    assert len(marker_rules) == 1
    rule = marker_rules[0]
    assert rule["Status"] == "Enabled"
    assert "And" not in rule["Filter"], "the marker rule must not carry a tag-filter condition"
    assert "Expiration" in rule
    assert "Days" in rule["Expiration"]
    assert rule["Expiration"]["Days"] == (
        "${self:custom.custodyPeriodDays.retention_marker.${self:provider.stage}}"
    )


def test_s3_lifecycle_days_reference_custody_period_config_not_hardcoded() -> None:
    """AC-A1-5 / ADR Non-Negotiable Invariant 3: the custody-period duration
    must never be hardcoded in the CloudFormation resource literal. Assert
    every Days/NoncurrentDays value is a ${self:custom.custodyPeriodDays...}
    variable reference for the correct evidence class, and that no bare
    integer literal is used for either property anywhere in the file.
    """
    s3_yml_text = Path("infra/resources/s3.yml").read_text(encoding="utf-8")

    for evidence_class in _EVIDENCE_CLASS_TO_S3_PREFIX:
        reference = f"${{self:custom.custodyPeriodDays.{evidence_class}.${{self:provider.stage}}}}"
        assert s3_yml_text.count(reference) == 2, (
            f"expected exactly two references (Days + NoncurrentDays) to {reference!r}"
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

    resource_types = {resource.get("Type") for resource in dlq_template["Resources"].values()}
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


def test_serverless_package_patterns_include_evidence_retention_module() -> None:
    """Evidence Governance Workstream A1.3b correction (GitHub Issue #95).

    `packages/storage/dynamodb_client.py` and `packages/storage/s3_client.py`
    import `release_confidence_platform.evidence_retention.constants`. Since
    `package.patterns` is a single global list applied to all 4 Lambda
    functions (no per-function override exists in this file), that module
    must be included here or any function that packages those two storage
    modules would raise `ModuleNotFoundError` at cold start once deployed.
    This is a static/structural assertion on the parsed YAML list -- it does
    not invoke the Serverless CLI (see
    test_serverless_variable_resolution_requires_serverless_cli above for why
    that boundary exists).
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    patterns = serverless_template["package"]["patterns"]
    assert "../src/release_confidence_platform/evidence_retention/**" in patterns


_CUSTODY_PERIODS_JSON_REFERENCE_PREFIX = "${file(../config/custody_periods.json):"

_EVIDENCE_CLASS_CUSTODY_REFERENCES = {
    evidence_class: (
        f"${{file(../config/custody_periods.json):evidentiary_classes."
        f"{evidence_class}.${{self:provider.stage}}}}"
    )
    for evidence_class in (
        "raw_evidence",
        "aggregate_metadata",
        "intelligence",
        "report",
        "certificate",
    )
}
_RETENTION_MARKER_CUSTODY_REFERENCE = (
    "${file(../config/custody_periods.json):operational_durations."
    "retention_marker.${self:provider.stage}}"
)


def test_custody_period_days_config_references_authoritative_json_file() -> None:
    """Evidence Governance Workstream A1.3d.1 (ADR Decision 5's A1.3d.0
    consolidation amendment / Non-Negotiable Invariant 29; Technical Design
    Section 20.3/20.12): all six custom.custodyPeriodDays.<class> keys --
    raw_evidence, aggregate_metadata, intelligence, report, certificate,
    retention_marker -- must resolve via the exact
    ${file(../config/custody_periods.json):...} external-file reference for
    that key, migrated off the prior inline empty-mapping literal
    (A1.2/A1.3c.1). No duration value, default, or fallback exists anywhere
    in any of the six references.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    custody_period_days = serverless_template["custom"]["custodyPeriodDays"]
    expected_keys = set(_EVIDENCE_CLASS_CUSTODY_REFERENCES) | {"retention_marker"}
    assert set(custody_period_days) == expected_keys

    for evidence_class, expected_reference in _EVIDENCE_CLASS_CUSTODY_REFERENCES.items():
        actual = custody_period_days[evidence_class]
        assert actual == expected_reference, (
            f"custom.custodyPeriodDays.{evidence_class} must reference "
            f"{expected_reference!r}, got {actual!r}"
        )
    assert custody_period_days["retention_marker"] == _RETENTION_MARKER_CUSTODY_REFERENCE

    all_references = {
        **_EVIDENCE_CLASS_CUSTODY_REFERENCES,
        "retention_marker": _RETENTION_MARKER_CUSTODY_REFERENCE,
    }
    for key, reference in all_references.items():
        assert reference.startswith(_CUSTODY_PERIODS_JSON_REFERENCE_PREFIX)
        # A comma inside a Serverless Framework variable reference denotes a
        # fallback value; a bare digit sequence would indicate a hardcoded
        # duration literal accidentally introduced into the reference.
        assert "," not in reference, f"{key} reference must not carry a fallback value"
        assert not any(char.isdigit() for char in reference), (
            f"{key} reference must not contain a hardcoded duration literal: {reference!r}"
        )


def test_custody_period_days_config_respects_evidentiary_versus_operational_schema_boundary() -> (
    None
):
    """Technical Design Section 20.3: evidentiary_classes and
    operational_durations are the schema's own structural separation -- no
    evidentiary class's reference may resolve through operational_durations,
    and retention_marker must never resolve through evidentiary_classes.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    custody_period_days = serverless_template["custom"]["custodyPeriodDays"]

    for evidence_class in _EVIDENCE_CLASS_CUSTODY_REFERENCES:
        reference = custody_period_days[evidence_class]
        assert f"evidentiary_classes.{evidence_class}." in reference
        assert "operational_durations" not in reference

    retention_marker_reference = custody_period_days["retention_marker"]
    assert "operational_durations.retention_marker." in retention_marker_reference
    assert "evidentiary_classes" not in retention_marker_reference


def test_custody_periods_json_file_ships_with_no_configured_stage_values() -> None:
    """The production config/custody_periods.json file A1.3d.1 introduces
    must contain exactly the fixed schema (Technical Design Section 20.3)
    with every evidentiary class and the retention_marker operational
    duration left completely unconfigured -- no stage, for any class,
    anywhere in the file.
    """
    import json

    with Path("config/custody_periods.json").open(encoding="utf-8") as fh:
        custody_periods = json.load(fh)

    assert set(custody_periods) == {"evidentiary_classes", "operational_durations"}

    evidentiary_classes = custody_periods["evidentiary_classes"]
    assert set(evidentiary_classes) == set(_EVIDENCE_CLASS_CUSTODY_REFERENCES)
    for evidence_class, stage_values in evidentiary_classes.items():
        assert stage_values == {}, (
            f"evidentiary_classes.{evidence_class} must remain an empty "
            f"object (no stage may have a value supplied), got: {stage_values!r}"
        )

    operational_durations = custody_periods["operational_durations"]
    assert set(operational_durations) == {"retention_marker"}
    assert operational_durations["retention_marker"] == {}


def test_aggregate_metadata_custody_period_env_binding_exists_on_aggregation_only() -> None:
    """Technical Design Section 19.16.6 required test coverage: the
    CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA environment binding exists on
    auditAggregation and on no other function; no provider-wide
    (provider.environment) binding exists for this variable.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    provider_environment = serverless_template["provider"].get("environment", {})
    assert "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA" not in provider_environment, (
        "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA must not be bound provider-wide"
    )

    functions = serverless_template["functions"]
    bound_functions = [
        name
        for name, spec in functions.items()
        if "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA" in spec.get("environment", {})
    ]
    assert bound_functions == ["auditAggregation"], (
        f"expected CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA bound on exactly "
        f"['auditAggregation'], got: {bound_functions!r}"
    )


def test_aggregate_metadata_custody_period_env_binding_has_no_fallback_or_literal() -> None:
    """Technical Design Section 19.16.6: no fallback/default value, and no
    numeric duration literal, may appear in the binding's variable
    reference."""
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    binding = serverless_template["functions"]["auditAggregation"]["environment"][
        "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA"
    ]
    assert binding == (
        "${self:custom.custodyPeriodDays.aggregate_metadata.${self:provider.stage}}"
    ), f"unexpected binding shape (fallback/default or literal present?): {binding!r}"
    assert "," not in binding, "a comma indicates a Serverless Framework fallback value"


def test_aggregate_metadata_custody_period_not_bound_on_other_functions() -> None:
    """Technical Design Section 19.16.6's explicit prohibition: this
    variable must never be bound to coreEngineOrchestrator, scheduledExecution,
    auditFinalization, or any function other than auditAggregation."""
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    for name, spec in serverless_template["functions"].items():
        if name == "auditAggregation":
            continue
        assert "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA" not in spec.get("environment", {}), (
            f"CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA must not be bound on {name!r}"
        )


def test_serverless_print_fails_on_unresolved_custody_period_config_file_references() -> None:
    """Evidence Governance Workstream A1.3d.1 (Technical Design Section
    20.12's render-test requirement, superseding A1.3c.1's narrower single-
    key version): `sls print --stage <any>` must fail at variable-resolution
    time specifically because every one of the six
    ${file(../config/custody_periods.json):...} references in
    custom.custodyPeriodDays is unresolved (the referenced stage property is
    absent from every class/operational-duration object in the production
    config/custody_periods.json file) -- not merely exit non-zero for an
    unrelated reason. This is EXPECTED, correct fail-closed behavior, not a
    defect: every class/stage combination in the production file is
    intentionally left unconfigured until a separate Product Strategy
    decision supplies real duration values (see
    test_custody_periods_json_file_ships_with_no_configured_stage_values
    above). This is the same fail-closed proof already required of the
    four S3-backed evidence classes
    (test_serverless_variable_resolution_requires_serverless_cli documents
    why that check is not run by this Python suite by default); this test
    additionally attempts the real invocation when the Serverless CLI/Node
    toolchain is available, and skips (not passes silently) when it is not,
    so this specific fail-closed proof is not lost entirely to the
    "manual/CI step" boundary.

    Note: because the six custom.custodyPeriodDays.<class> references now
    fail to resolve at the ${file(...)} lookup itself (before any
    downstream consumer -- resources/s3.yml's Days/NoncurrentDays
    references, or the auditAggregation environment binding -- is ever
    reached), the failure surfaces at "custom.custodyPeriodDays.<class>",
    not at the downstream reference paths A1.2/A1.3c.1's version of this
    test asserted against. This is a strictly earlier, equally fail-closed
    resolution failure, not a weaker one.
    """
    import shutil
    import subprocess

    if shutil.which("npx") is None:
        pytest.skip("npx/Node toolchain not available in this environment")

    infra_dir = Path("infra")
    try:
        result = subprocess.run(
            ["npx", "sls", "print", "--stage", "dev"],
            cwd=infra_dir,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.skip(f"Serverless CLI invocation unavailable/timed out: {exc}")

    assert result.returncode != 0, (
        "sls print must fail (unpopulated custody-period configuration) -- "
        "a successful render here would mean the fail-closed gate is broken "
        "or a duration value was accidentally introduced"
    )
    combined_output = result.stdout + result.stderr
    for evidence_class in _EVIDENCE_CLASS_CUSTODY_REFERENCES:
        assert f"custom.custodyPeriodDays.{evidence_class}" in combined_output, (
            f"sls print's failure must name the unresolved "
            f"custom.custodyPeriodDays.{evidence_class} reference; "
            f"got output:\n{combined_output}"
        )
    assert "custom.custodyPeriodDays.retention_marker" in combined_output, (
        f"sls print's failure must name the unresolved "
        f"custom.custodyPeriodDays.retention_marker reference; "
        f"got output:\n{combined_output}"
    )
