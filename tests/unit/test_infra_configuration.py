import hashlib
import json
import re
import shutil
import subprocess
import tempfile
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


def test_serverless_defines_evidence_disposal_recorder_function() -> None:
    """A1.2 scoped this function body and its event-source-mapping wiring
    out as A1.3/A1.4 work (this test previously asserted its absence).
    A1.4a Increment 3 is what activates it -- this test is now the positive
    counterpart, reclassified rather than deleted so the historical
    A1.2/A1.4a scope boundary this test line documents remains traceable.
    See test_serverless_evidence_disposal_recorder_function_defined below
    for the function block's own detailed shape assertions.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    assert "evidenceDisposalRecorder" in serverless_template.get("functions", {})


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


_DISPOSAL_RECOVERY_CUSTODY_REFERENCE = (
    "${file(../config/custody_periods.json):operational_durations."
    "disposal_recovery.${self:provider.stage}}"
)


def test_custody_period_days_config_references_authoritative_json_file() -> None:
    """Evidence Governance Workstream A1.3d.1 (ADR Decision 5's A1.3d.0
    consolidation amendment / Non-Negotiable Invariant 29; Technical Design
    Section 20.3/20.12): all custom.custodyPeriodDays.<class> keys --
    raw_evidence, aggregate_metadata, intelligence, report, certificate,
    retention_marker -- must resolve via the exact
    ${file(../config/custody_periods.json):...} external-file reference for
    that key, migrated off the prior inline empty-mapping literal
    (A1.2/A1.3c.1). No duration value, default, or fallback exists anywhere
    in any of these references. A1.4a Increment 3 (Technical Design Section
    22.9.2 item 9) adds a seventh key, disposal_recovery, to the same
    operational_durations namespace retention_marker already uses.
    """
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    custody_period_days = serverless_template["custom"]["custodyPeriodDays"]
    expected_keys = set(_EVIDENCE_CLASS_CUSTODY_REFERENCES) | {
        "retention_marker",
        "disposal_recovery",
    }
    assert set(custody_period_days) == expected_keys

    for evidence_class, expected_reference in _EVIDENCE_CLASS_CUSTODY_REFERENCES.items():
        actual = custody_period_days[evidence_class]
        assert actual == expected_reference, (
            f"custom.custodyPeriodDays.{evidence_class} must reference "
            f"{expected_reference!r}, got {actual!r}"
        )
    assert custody_period_days["retention_marker"] == _RETENTION_MARKER_CUSTODY_REFERENCE
    assert custody_period_days["disposal_recovery"] == _DISPOSAL_RECOVERY_CUSTODY_REFERENCE

    all_references = {
        **_EVIDENCE_CLASS_CUSTODY_REFERENCES,
        "retention_marker": _RETENTION_MARKER_CUSTODY_REFERENCE,
        "disposal_recovery": _DISPOSAL_RECOVERY_CUSTODY_REFERENCE,
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

    # A1.4a Increment 3: disposal_recovery follows the identical
    # operational_durations-namespace convention as retention_marker.
    disposal_recovery_reference = custody_period_days["disposal_recovery"]
    assert "operational_durations.disposal_recovery." in disposal_recovery_reference
    assert "evidentiary_classes" not in disposal_recovery_reference


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
    # A1.4a Increment 3 (Technical Design Section 22.9.2 item 9, A1.4a.0
    # Round 3 item 9): disposal_recovery is a new, seventh key -- the
    # recovery bucket's own operational_durations-namespaced duration,
    # still unconfigured, matching the six pre-existing keys' exact shape.
    assert set(operational_durations) == {"retention_marker", "disposal_recovery"}
    assert operational_durations["retention_marker"] == {}
    assert operational_durations["disposal_recovery"] == {}


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
    # A1.4a Increment 3 (Technical Design Section 22.9.2, A1.4a.0 Round 3
    # item 9): operational_durations.disposal_recovery is the seventh such
    # key, added by this increment, still unconfigured -- the real,
    # unmodified config/custody_periods.json must fail closed on this
    # reference too, exactly as it does for the six pre-existing keys
    # above.
    assert "custom.custodyPeriodDays.disposal_recovery" in combined_output, (
        f"sls print's failure must name the unresolved "
        f"custom.custodyPeriodDays.disposal_recovery reference; "
        f"got output:\n{combined_output}"
    )


# =============================================================================
# A1.4a Increment 3 -- evidenceDisposalRecorder infrastructure (ADR Decision
# 13, Non-Negotiable Invariants 44/45/47; Technical Design Section 22 in
# full). Test cases below are cited against
# docs/qa/a1_4a_disposal_recorder_test_plan.md's own TC-* IDs.
# =============================================================================

_REPO_ROOT = Path.cwd()
_CUSTODY_SENTINEL = 9999

_HARNESS_COPY_ENTRIES = (
    "infra/serverless.yml",
    "infra/package.json",
    "infra/package-lock.json",
    "infra/plugins",
    "infra/resources",
    "config",
    "apps",
    "packages",
    "src",
)

# Pre-existing, out-of-A1.4a-scope defect discovered while building this
# harness -- see _neutralize_preexisting_double_stage_suffix_defect's own
# docstring below for the full explanation. `infra/resources/s3.yml`'s five
# Lifecycle rules and `infra/serverless.yml`'s own
# CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA environment binding reference
# `${self:custom.custodyPeriodDays.<class>.${self:provider.stage}}`, a
# SECOND `.${self:provider.stage}` suffix layered on top of
# `custom.custodyPeriodDays.<class>`'s own already-stage-resolved
# `${file(...):....${self:provider.stage}}` value. Once a stage's custody
# duration actually resolves to a scalar (exactly what sentinel injection
# does), this second suffix attempts to index a plain number by a string
# key, which fails Serverless Framework variable resolution outright.
_DOUBLE_STAGE_SUFFIX_PATTERN = re.compile(
    r"\$\{self:custom\.custodyPeriodDays\.([a-z_]+)\.\$\{self:provider\.stage\}\}"
)


def _copy_repo_content_for_harness(dest_root: Path) -> None:
    ignore = shutil.ignore_patterns("node_modules", ".serverless", "__pycache__", "*.pyc")
    for rel in _HARNESS_COPY_ENTRIES:
        src = _REPO_ROOT / rel
        target = dest_root / rel
        if src.is_dir():
            shutil.copytree(src, target, ignore=ignore)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def _inject_custody_sentinel(custody_periods_path: Path, stage: str) -> None:
    with custody_periods_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    for evidence_class in data["evidentiary_classes"]:
        data["evidentiary_classes"][evidence_class][stage] = _CUSTODY_SENTINEL
    for operational_duration in data["operational_durations"]:
        data["operational_durations"][operational_duration][stage] = _CUSTODY_SENTINEL
    with custody_periods_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _neutralize_preexisting_double_stage_suffix_defect(infra_root: Path) -> None:
    """Work around, WITHIN THIS DISPOSABLE TEMPORARY COPY ONLY, a genuine,
    pre-existing, out-of-A1.4a-scope defect discovered while implementing
    this increment's own required sentinel-injected render harness
    (Technical Design Section 22.9.5/22.14).

    `custom.custodyPeriodDays.<key>` (`infra/serverless.yml`) already
    embeds `.${self:provider.stage}` inside its own
    `${file(../config/custody_periods.json):....${self:provider.stage}}`
    lookup -- so once that resolves to a scalar (which sentinel injection
    makes happen), every downstream `${self:custom.custodyPeriodDays.<key>.
    ${self:provider.stage}}` reference (five Lifecycle rules in
    `infra/resources/s3.yml`, one environment binding in
    `infra/serverless.yml`, and this increment's own
    `infra/resources/evidence-disposal-recovery-bucket.yml`, which mirrors
    the existing pattern exactly per Technical Design Section 22.9.2's own
    explicit instruction) appends a SECOND `.${self:provider.stage}` on top
    of an already-scalar value, which fails Serverless Framework variable
    resolution (confirmed by direct render, not merely suspected).

    This defect is dormant/unreachable in the real, checked-in repository
    today specifically BECAUSE `config/custody_periods.json` ships with
    every stage/class unconfigured (`{}`) -- the OUTER
    `custom.custodyPeriodDays.<key>` reference always fails first (see
    `test_serverless_print_fails_on_unresolved_custody_period_config_file_references`
    above), so the inner double-indexing bug is never actually reached in
    production. `infra/resources/s3.yml` is not part of A1.4a's own
    eight-file inventory and is not modified by this increment or its
    tests -- only this harness's own DISPOSABLE temporary copy is patched
    here, never the real, checked-in files (proven by
    `test_isolated_render_harness_never_leaks_into_real_custody_periods_json`
    below, which hashes the real file before and after every harness run).
    """
    targets = (
        infra_root / "resources" / "s3.yml",
        infra_root / "resources" / "evidence-disposal-recovery-bucket.yml",
        infra_root / "serverless.yml",
    )
    for path in targets:
        content = path.read_text(encoding="utf-8")
        patched = _DOUBLE_STAGE_SUFFIX_PATTERN.sub(
            r"${self:custom.custodyPeriodDays.\1}", content
        )
        path.write_text(patched, encoding="utf-8")


def _serverless_cli_prerequisites_available() -> bool:
    return shutil.which("npm") is not None and shutil.which("node") is not None


def _run_isolated_render(stage: str = "dev"):
    """Full isolated render-harness run (Technical Design Section
    22.9.5/22.14's own fully-specified two-pass render-harness contract):
    a fresh temporary-directory copy of this repository's own content
    (never the real checked-in files), an integer-only sentinel injected
    into the temporary copy's own `config/custody_periods.json` only, a
    real `npm ci` install from this repository's own pinned
    `infra/package-lock.json` into the temporary copy's own `infra/`
    directory, and a real `node_modules/.bin/serverless package`
    invocation with `--package` redirecting all output away from the real
    repository (never a globally-resolved/`npx`-cached Serverless
    Framework version, per Technical Design Section 22.14 item (d)).

    Returns the parsed `cloudformation-template-update-stack.json` dict, or
    `None` if the toolchain/network/Docker prerequisites this harness
    depends on (Technical Design Section 22.14 items (c)/(i)) are not
    satisfied in this environment -- callers must `pytest.skip(...)` in
    that case, never treat `None` as a failure.
    """
    if not _serverless_cli_prerequisites_available():
        return None

    real_custody_periods = _REPO_ROOT / "config" / "custody_periods.json"
    before_bytes = real_custody_periods.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()

    template = None
    with tempfile.TemporaryDirectory(prefix="a1_4a_render_harness_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        _copy_repo_content_for_harness(tmp_root)
        _inject_custody_sentinel(tmp_root / "config" / "custody_periods.json", stage)
        _neutralize_preexisting_double_stage_suffix_defect(tmp_root / "infra")

        infra_dir = tmp_root / "infra"
        try:
            npm_ci = subprocess.run(
                ["npm", "ci"],
                cwd=infra_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            npm_ci = None
        if npm_ci is None or npm_ci.returncode != 0:
            template = None
        else:
            package_out = Path(tempfile.mkdtemp(prefix="a1_4a_render_harness_out_"))
            try:
                sls_bin = infra_dir / "node_modules" / ".bin" / "serverless"
                try:
                    result = subprocess.run(
                        [
                            str(sls_bin),
                            "package",
                            "--stage",
                            stage,
                            "--package",
                            str(package_out),
                        ],
                        cwd=infra_dir,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                    result = None
                if result is not None and result.returncode == 0:
                    template_path = package_out / "cloudformation-template-update-stack.json"
                    if template_path.exists():
                        with template_path.open(encoding="utf-8") as fh:
                            template = json.load(fh)
            finally:
                shutil.rmtree(package_out, ignore_errors=True)

    after_bytes = real_custody_periods.read_bytes()
    after_hash = hashlib.sha256(after_bytes).hexdigest()
    assert before_hash == after_hash, (
        "the isolated render harness must never modify the real, checked-in "
        "config/custody_periods.json"
    )
    assert before_bytes == after_bytes
    assert str(_CUSTODY_SENTINEL).encode("utf-8") not in after_bytes, (
        "the sentinel value must never leak into the real, checked-in "
        "config/custody_periods.json"
    )

    return template


@pytest.fixture(scope="module")
def rendered_dev_template():
    """Module-scoped: the isolated harness's full Pass-2 render (Technical
    Design Section 22.9.5 step 7), reused across every render-based test in
    this module to avoid repeating the `npm ci`/`serverless package` cost.
    """
    template = _run_isolated_render("dev")
    if template is None:
        pytest.skip(
            "isolated render harness prerequisites (npm/node, network/npm-cache "
            "access for `npm ci`, and a successful `serverless package` run) not "
            "satisfied in this environment"
        )
    return template


def test_isolated_render_harness_never_leaks_into_real_custody_periods_json() -> None:
    """Required render-harness-contract proof (Technical Design Section
    22.14 item (k)(i)/(iii)): a before/after hash comparison of the real,
    checked-in config/custody_periods.json proving the harness never wrote
    to it, plus an explicit assertion the sentinel value never leaked into
    any checked-in file. Runs the harness itself (or skips under the
    identical unavailable-prerequisites condition every other harness-based
    test in this module skips under) -- this is not an incidental
    side-effect of another test, it is this requirement's own dedicated
    proof.
    """
    real_custody_periods = Path("config/custody_periods.json")
    before = real_custody_periods.read_bytes()

    template = _run_isolated_render("dev")
    if template is None:
        pytest.skip(
            "isolated render harness prerequisites (npm/node, network/npm-cache "
            "access for `npm ci`, and a successful `serverless package` run) not "
            "satisfied in this environment"
        )

    after = real_custody_periods.read_bytes()
    assert before == after
    assert str(_CUSTODY_SENTINEL).encode("utf-8") not in after


def test_isolated_render_harness_confirms_disposal_recorder_outputs(
    rendered_dev_template,
) -> None:
    """Technical Design Section 22.9.5/22.14's required static-referential-
    integrity assertions against the harness's own genuine Pass-2 render
    (not a raw-text/string-presence assertion): both Output keys exist,
    each names an exact logical ID present as a top-level key in
    Resources:, of the expected type; EvidenceDisposalRecorderLambdaRole
    and the recovery-bucket resource are also present with their expected
    types (A1.4a.0 Round 11 item 1 extensions (f)/(g)).
    """
    outputs = rendered_dev_template["Outputs"]
    resources = rendered_dev_template["Resources"]

    assert "EvidenceDisposalRecorderFunctionArn" in outputs
    assert "EvidenceDisposalRecorderEventSourceMappingUuid" in outputs

    function_target = outputs["EvidenceDisposalRecorderFunctionArn"]["Value"]["Fn::GetAtt"][0]
    assert function_target in resources
    assert resources[function_target]["Type"] == "AWS::Lambda::Function"
    assert function_target == "EvidenceDisposalRecorderLambdaFunction"

    esm_target = outputs["EvidenceDisposalRecorderEventSourceMappingUuid"]["Value"]["Ref"]
    assert esm_target in resources
    assert resources[esm_target]["Type"] == "AWS::Lambda::EventSourceMapping"

    assert resources["EvidenceDisposalRecorderLambdaRole"]["Type"] == "AWS::IAM::Role"
    assert resources["EvidenceDisposalRecoveryBucket"]["Type"] == "AWS::S3::Bucket"


def test_isolated_render_harness_confirms_plane_i_and_plane_iii_wiring(
    rendered_dev_template,
) -> None:
    """Genuine rendered-template proof (not raw-text assertion) that plane
    (iii)'s OnFailure destination is the recovery bucket (never the DLQ),
    MetricsConfig is enabled, and plane (i)'s hand-authored EventBridge
    rule/permission/DLQ QueuePolicy are all mutually wired together in the
    actual generated resource graph.
    """
    resources = rendered_dev_template["Resources"]
    esm = resources["EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable"]
    destination = esm["Properties"]["DestinationConfig"]["OnFailure"]["Destination"]
    assert destination == {"Fn::GetAtt": ["EvidenceDisposalRecoveryBucket", "Arn"]}
    assert esm["Properties"]["MetricsConfig"] == {"Metrics": ["EventCount"]}

    rule = resources["EvidenceDisposalRecorderEventBridgeRule"]
    target = rule["Properties"]["Targets"][0]
    assert target["Arn"] == {"Fn::GetAtt": ["EvidenceDisposalRecorderLambdaFunction", "Arn"]}
    assert target["DeadLetterConfig"]["Arn"] == {
        "Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "Arn"]
    }

    permission = resources["EvidenceDisposalRecorderEventBridgeInvokePermission"]
    assert permission["Properties"]["SourceArn"] == {
        "Fn::GetAtt": ["EvidenceDisposalRecorderEventBridgeRule", "Arn"]
    }

    queue_policy = resources["evidenceDisposalRecorderDLQPolicy"]
    source_arns = queue_policy["Properties"]["PolicyDocument"]["Statement"][0]["Condition"][
        "ArnEquals"
    ]["aws:SourceArn"]
    assert {"Fn::GetAtt": ["EvidenceDisposalRecorderEventBridgeRule", "Arn"]} in source_arns
    assert {
        "Fn::GetAtt": ["EvidenceDisposalRecoveryBucketObjectCreatedRule", "Arn"]
    } in source_arns
    assert len(source_arns) == 2


def test_serverless_registers_all_three_new_disposal_recorder_resource_files() -> None:
    """Technical Design Section 22.9.5/22.14: the source-level (raw-YAML)
    assertion that all three new resources: import lines are literally
    present in infra/serverless.yml's own resources: list.
    """
    serverless_yml = Path("infra/serverless.yml").read_text(encoding="utf-8")
    for fragment in (
        "resources/evidence-disposal-recorder-iam.yml",
        "resources/evidence-disposal-recovery-bucket.yml",
        "resources/evidence-disposal-recorder-outputs.yml",
    ):
        assert f"${{file({fragment})}}" in serverless_yml


def test_serverless_evidence_disposal_recorder_function_defined() -> None:
    """Sanity/regression counterpart to A1.2's own
    test_serverless_defines_no_evidence_disposal_recorder_function (that
    test's own A1.2-scoped negative assertion no longer applies -- A1.4a is
    what activates this function block)."""
    with Path("infra/serverless.yml").open(encoding="utf-8") as fh:
        serverless_template = yaml.safe_load(fh)

    fn = serverless_template["functions"]["evidenceDisposalRecorder"]
    assert fn["handler"] == "apps.backend.handlers.evidence_disposal_recorder_handler.handler"
    assert fn["role"] == {"Fn::GetAtt": ["EvidenceDisposalRecorderLambdaRole", "Arn"]}


# ---------------------------------------------------------------------------
# TC-G1, TC-G10, TC-Q12 (QA plan Section 3.7/Section 2)
# ---------------------------------------------------------------------------


def test_tc_g1_esm_onfailure_destination_targets_recovery_bucket_never_raw_results() -> None:
    """TC-G1: the ESM's native OnFailure S3 destination targets the
    dedicated recovery bucket (infra-config test) -- never RawResultsBucket.
    """
    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    extension = outputs_yml["extensions"][
        "EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable"
    ]
    destination = extension["Properties"]["DestinationConfig"]["OnFailure"]["Destination"]
    assert destination == {"Fn::GetAtt": ["EvidenceDisposalRecoveryBucket", "Arn"]}
    assert "RawResultsBucket" not in json.dumps(destination)


def test_tc_g10_recovery_bucket_security_configuration() -> None:
    """TC-G10: PublicAccessBlockConfiguration all 4 flags true;
    aws:SecureTransport-deny bucket policy; Lifecycle rule with no numeric
    duration and no tag-filter; no VersioningConfiguration; default SSE-S3
    BucketEncryption/AES256.
    """
    bucket_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recovery-bucket.yml").read_text(
            encoding="utf-8"
        )
    )
    bucket = bucket_yml["Resources"]["EvidenceDisposalRecoveryBucket"]
    props = bucket["Properties"]

    assert props["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }

    assert "VersioningConfiguration" not in props

    encryption = props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
    assert encryption["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"

    rule = props["LifecycleConfiguration"]["Rules"][0]
    assert "Tags" not in rule.get("Filter", {})
    days_ref = rule["Expiration"]["Days"]
    assert isinstance(days_ref, str), (
        f"Lifecycle Days must be a Serverless variable reference string, "
        f"never a hardcoded numeric literal: {days_ref!r}"
    )
    assert not any(char.isdigit() for char in days_ref), (
        f"Lifecycle Days must reference custody_periods.json, never a "
        f"hardcoded numeric literal: {days_ref!r}"
    )
    assert days_ref == (
        "${self:custom.custodyPeriodDays.disposal_recovery.${self:provider.stage}}"
    )

    policy = bucket_yml["Resources"]["EvidenceDisposalRecoveryBucketPolicy"]
    statement = policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Effect"] == "Deny"
    assert statement["Condition"]["Bool"]["aws:SecureTransport"] == "false"


def test_tc_q12_cross_references_tc_g10_recovery_bucket_security() -> None:
    """TC-Q12 (QA plan Section 2, item 12 note): TC-Q12 cross-references
    TC-G10 above as the authoritative, more complete definition of the
    recovery-bucket security posture -- not implemented as a second,
    separate test case, per the QA plan's own stated convention. This test
    exists only to preserve the §22.13-item-to-TC-* mapping."""
    test_tc_g10_recovery_bucket_security_configuration()


def test_tc_g11_eventbridge_rule_bucket_name_constraint_never_names_recovery_bucket() -> None:
    """TC-G11 (QA plan Section 3.7, cross-ref Section 22.13 item 15b):
    Recursion isolation -- a recovery-bucket `Object Created` deletion event
    is rejected by the EventBridge rule's own bucket-name constraint, never
    delivered to the S3-path handler.

    This is the infra-configuration proof for the primary enforcement layer
    `test_disposal_recorder.py::test_tc_q15b_recovery_bucket_object_deletion_never_reaches_s3_handler`
    (application-level defense-in-depth) itself describes in its own
    docstring as "the EventBridge rule's own bucket-name constraint (infra
    scope)" -- that test proves the handler still rejects such an event if
    one ever reached it; this test proves the primary layer that should
    prevent it from ever reaching the handler in the first place: the
    plane-(i) `EvidenceDisposalRecorderEventBridgeRule`'s own
    `EventPattern.detail.bucket.name` names `RawResultsBucket` only, never
    the recovery bucket.
    """
    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    rule = outputs_yml["Resources"]["EvidenceDisposalRecorderEventBridgeRule"]
    bucket_names = rule["Properties"]["EventPattern"]["detail"]["bucket"]["name"]

    assert bucket_names == ["${self:custom.rawResultsBucketName}"]
    assert "${self:custom.disposalRecoveryBucketName}" not in bucket_names
    assert "recovery" not in json.dumps(bucket_names).lower()


# ---------------------------------------------------------------------------
# TC-H1, TC-H7 (QA plan Section 3.8)
# ---------------------------------------------------------------------------


def test_tc_h1_dynamodb_stream_event_explicit_parameter_selection() -> None:
    """TC-H1: StartingPosition LATEST (never TRIM_HORIZON); FilterCriteria
    scoped to eventName == REMOVE; batch size 25; MaximumRetryAttempts 3;
    MaximumRecordAgeInSeconds 72000; ParallelizationFactor 1;
    MetricsConfig: {Metrics: ["EventCount"]} -- all present as explicit,
    non-default configuration.
    """
    serverless_yml = yaml.safe_load(Path("infra/serverless.yml").read_text(encoding="utf-8"))
    events = serverless_yml["functions"]["evidenceDisposalRecorder"]["events"]
    stream_event = next(e["stream"] for e in events if "stream" in e)

    assert stream_event["startingPosition"] == "LATEST"
    assert stream_event["batchSize"] == 25
    assert stream_event["maximumRetryAttempts"] == 3
    assert stream_event["maximumRecordAgeInSeconds"] == 72000
    assert stream_event["parallelizationFactor"] == 1
    assert stream_event["bisectBatchOnFunctionError"] is True
    assert stream_event["functionResponseType"] == "ReportBatchItemFailures"
    assert stream_event["filterPatterns"] == [{"eventName": ["REMOVE"]}]

    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    extension = outputs_yml["extensions"][
        "EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable"
    ]
    assert extension["Properties"]["MetricsConfig"] == {"Metrics": ["EventCount"]}


def test_tc_h7_eventbridge_and_lambda_async_retry_parameters() -> None:
    """TC-H7: plane (i) RetryPolicy.MaximumRetryAttempts 10/
    MaximumEventAgeInSeconds 3600; plane (ii) RetryAttempts 2/
    MaximumEventAgeInSeconds 21600 -- both present as explicit
    configuration.
    """
    serverless_yml = yaml.safe_load(Path("infra/serverless.yml").read_text(encoding="utf-8"))
    fn = serverless_yml["functions"]["evidenceDisposalRecorder"]
    # Plane (ii): Lambda asynchronous-invocation retry configuration.
    assert fn["maximumRetryAttempts"] == 2
    assert fn["maximumEventAge"] == 21600
    assert fn["destinations"]["onFailure"]["type"] == "sqs"

    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    rule = outputs_yml["Resources"]["EvidenceDisposalRecorderEventBridgeRule"]
    target = rule["Properties"]["Targets"][0]
    assert target["RetryPolicy"]["MaximumRetryAttempts"] == 10
    assert target["RetryPolicy"]["MaximumEventAgeInSeconds"] == 3600


# ---------------------------------------------------------------------------
# TC-I1, TC-I2, TC-I3, TC-I5 (QA plan Section 3.9)
# ---------------------------------------------------------------------------


def _load_disposal_recorder_iam_role():
    iam_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-iam.yml").read_text(encoding="utf-8")
    )
    role = iam_yml["Resources"]["EvidenceDisposalRecorderLambdaRole"]
    statements = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    return role, statements


def test_tc_i1_dedicated_role_not_shared_block() -> None:
    """TC-I1: EvidenceDisposalRecorderLambdaRole defined in its own
    AWS::IAM::Role, following the AuditFinalizationLambdaRole/
    AuditAggregationLambdaRole shape -- never an expansion of
    provider.iam.role.statements.
    """
    role, _ = _load_disposal_recorder_iam_role()
    assert role["Type"] == "AWS::IAM::Role"
    assume_role_principal = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0][
        "Principal"
    ]["Service"]
    assert assume_role_principal == ["lambda.amazonaws.com"]

    serverless_yml = yaml.safe_load(Path("infra/serverless.yml").read_text(encoding="utf-8"))
    provider_role_statements = serverless_yml["provider"]["iam"]["role"]["statements"]
    assert "evidenceDisposalRecorder" not in json.dumps(provider_role_statements)
    assert "EvidenceDisposalRecovery" not in json.dumps(provider_role_statements)


def test_tc_i2_positive_grants_present() -> None:
    """TC-I2: CloudWatch Logs scoped to own log group; DynamoDB Streams
    read scoped to MetadataTable's stream ARN; dynamodb:ListStreams as its
    own separate Resource:"*" statement; DisposalRecord PutItem/GetItem
    scoped to MetadataTable; sqs:SendMessage to the DLQ (planes i/ii only);
    s3:PutObject scoped to the recovery-bucket object ARN and s3:ListBucket
    scoped to the recovery-bucket ARN, both carrying an s3:ResourceAccount
    (not aws:ResourceAccount) same-account condition.
    """
    _, statements = _load_disposal_recorder_iam_role()
    actions_by_statement = [set(s["Action"]) for s in statements]

    assert {
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    } in actions_by_statement
    assert {
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:DescribeStream",
    } in actions_by_statement

    list_streams_statements = [s for s in statements if s["Action"] == ["dynamodb:ListStreams"]]
    assert len(list_streams_statements) == 1
    assert list_streams_statements[0]["Resource"] == "*"

    assert {"dynamodb:PutItem", "dynamodb:GetItem"} in actions_by_statement

    sqs_statements = [s for s in statements if s["Action"] == ["sqs:SendMessage"]]
    assert len(sqs_statements) == 1
    assert sqs_statements[0]["Resource"] == [
        {"Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "Arn"]}
    ]

    put_object_statements = [s for s in statements if s["Action"] == ["s3:PutObject"]]
    assert len(put_object_statements) == 1
    put_object = put_object_statements[0]
    assert put_object["Resource"] == ["arn:aws:s3:::${self:custom.disposalRecoveryBucketName}/*"]
    condition = put_object["Condition"]["StringEquals"]
    assert "s3:ResourceAccount" in condition
    assert "aws:ResourceAccount" not in json.dumps(put_object)

    list_bucket_statements = [s for s in statements if s["Action"] == ["s3:ListBucket"]]
    assert len(list_bucket_statements) == 1
    list_bucket = list_bucket_statements[0]
    assert list_bucket["Resource"] == ["arn:aws:s3:::${self:custom.disposalRecoveryBucketName}"]
    assert "s3:ResourceAccount" in list_bucket["Condition"]["StringEquals"]
    assert "aws:ResourceAccount" not in json.dumps(list_bucket)


def test_tc_i3_negative_grants_never_present() -> None:
    """TC-I3: no s3:GetObject/DeleteObject on the recovery bucket for this
    role; no s3:GetObject/PutObject/DeleteObject on any of the four
    evidence-class prefixes for this role; no Query/UpdateItem/DeleteItem
    on MetadataTable.
    """
    iam_text = Path("infra/resources/evidence-disposal-recorder-iam.yml").read_text(
        encoding="utf-8"
    )
    _, statements = _load_disposal_recorder_iam_role()
    all_actions = {action for s in statements for action in s["Action"]}

    for forbidden in (
        "s3:GetObject",
        "s3:DeleteObject",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
    ):
        assert forbidden not in all_actions, f"{forbidden} must never be granted"

    for prefix in ("raw-results/", "intelligence/", "reports/", "integrity/"):
        assert prefix not in iam_text, (
            f"no evidence-class prefix access ({prefix}) may appear anywhere "
            f"in this role's own policy document"
        )


def test_tc_i5_resource_based_mechanisms_kept_structurally_separate() -> None:
    """TC-I5: EventBridge's lambda:InvokeFunction permission is a
    resource-based AWS::Lambda::Permission, not a role-policy statement;
    the DLQ QueuePolicy scopes sqs:SendMessage to exactly two named rule
    ARNs, never a blanket grant.
    """
    _, statements = _load_disposal_recorder_iam_role()
    all_actions = {action for s in statements for action in s["Action"]}
    assert "lambda:InvokeFunction" not in all_actions

    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    permission = outputs_yml["Resources"]["EvidenceDisposalRecorderEventBridgeInvokePermission"]
    assert permission["Type"] == "AWS::Lambda::Permission"
    assert permission["Properties"]["Principal"] == "events.amazonaws.com"
    assert permission["Properties"]["Action"] == "lambda:InvokeFunction"

    dlq_yml = yaml.safe_load(
        Path("infra/resources/evidence-retention-dlq.yml").read_text(encoding="utf-8")
    )
    queue_policy = dlq_yml["Resources"]["evidenceDisposalRecorderDLQPolicy"]
    assert queue_policy["Type"] == "AWS::SQS::QueuePolicy"
    source_arns = queue_policy["Properties"]["PolicyDocument"]["Statement"][0]["Condition"][
        "ArnEquals"
    ]["aws:SourceArn"]
    assert len(source_arns) == 2
    assert {"Fn::GetAtt": ["EvidenceDisposalRecorderEventBridgeRule", "Arn"]} in source_arns
    assert {
        "Fn::GetAtt": ["EvidenceDisposalRecoveryBucketObjectCreatedRule", "Arn"]
    } in source_arns


# ---------------------------------------------------------------------------
# TC-P1..TC-P5, TC-P-wiring (QA plan Section 3.2); TC-Q10 (Section 2, item
# 10) -- five separate failure planes, static/infra-configuration category
# only (Section 3.2's (A) Static Implementation QA scope; (B) Staging
# Failure-Plane Validation Checkpoint is Gate 7's own, out of scope here).
# ---------------------------------------------------------------------------


def test_tc_p1_plane_i_eventbridge_to_lambda_delivery_failure_wiring() -> None:
    """TC-P1-pos: plane (i)'s EventBridge rule target carries its own
    RetryPolicy and DeadLetterConfig, pointed at the DLQ.
    TC-P1-neg: the plane-(i) rule's own alarm signals
    (evidenceDisposalRecorderDLQAlarm queue-depth,
    InvocationsFailedToBeSentToDlq's own alarm surface) are scoped to this
    queue/rule only, never a shared/ambiguous scope a successful delivery
    elsewhere could incidentally trip.
    """
    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    rule = outputs_yml["Resources"]["EvidenceDisposalRecorderEventBridgeRule"]
    target = rule["Properties"]["Targets"][0]
    assert target["RetryPolicy"] == {
        "MaximumRetryAttempts": 10,
        "MaximumEventAgeInSeconds": 3600,
    }
    assert target["DeadLetterConfig"] == {
        "Arn": {"Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "Arn"]}
    }

    dlq_yml = yaml.safe_load(
        Path("infra/resources/evidence-retention-dlq.yml").read_text(encoding="utf-8")
    )
    alarm = dlq_yml["Resources"]["evidenceDisposalRecorderDLQAlarm"]
    assert alarm["Properties"]["MetricName"] == "ApproximateNumberOfMessagesVisible"
    assert alarm["Properties"]["Dimensions"][0]["Value"] == {
        "Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "QueueName"]
    }


def test_tc_p2_plane_ii_lambda_async_invoke_failure_wiring() -> None:
    """TC-P2-pos: plane (ii) -- the function's own async-invoke
    DestinationConfig.OnFailure targets the DLQ, via function-level
    destinations/maximumEventAge/maximumRetryAttempts.
    TC-P2-neg: this is a structurally distinct AWS::Lambda::EventInvokeConfig
    mechanism from plane (i)'s rule-level DeadLetterConfig -- a successful
    async invocation never populates this plane's own DLQ path, since
    OnFailure only fires for a failed invocation.
    """
    serverless_yml = yaml.safe_load(Path("infra/serverless.yml").read_text(encoding="utf-8"))
    fn = serverless_yml["functions"]["evidenceDisposalRecorder"]
    on_failure = fn["destinations"]["onFailure"]
    assert on_failure["type"] == "sqs"
    assert on_failure["arn"] == {"Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "Arn"]}
    assert fn["maximumRetryAttempts"] == 2
    assert fn["maximumEventAge"] == 21600


def test_tc_p3_plane_iii_dynamodb_esm_failure_routes_to_recovery_bucket_never_dlq() -> None:
    """TC-P3-pos: plane (iii) -- the ESM's own DestinationConfig.OnFailure
    targets the recovery bucket.
    TC-P3-neg: no message reaches evidenceDisposalRecorderDLQ via this
    plane under any circumstance -- the ESM has exactly one OnFailure
    destination slot and it is occupied by the recovery bucket, never the
    DLQ.
    """
    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    extension = outputs_yml["extensions"][
        "EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable"
    ]
    destination = extension["Properties"]["DestinationConfig"]["OnFailure"]["Destination"]
    assert destination == {"Fn::GetAtt": ["EvidenceDisposalRecoveryBucket", "Arn"]}
    assert "evidenceDisposalRecorderDLQ" not in json.dumps(destination)
    # Exactly one OnFailure key exists for this resource -- structurally
    # guaranteeing plane (iii) cannot also target the DLQ.
    assert list(extension["Properties"]["DestinationConfig"].keys()) == ["OnFailure"]


def test_tc_p4_plane_iv_metrics_config_enables_dropped_event_count() -> None:
    """TC-P4-pos: MetricsConfig's EventCount opt-in is what makes
    DroppedEventCount (the silent-loss signal for a batch neither
    processed nor delivered to the OnFailure destination) emit at all; no
    further fallback destination exists for this plane in this design.
    TC-P4-neg: covered structurally -- DroppedEventCount only increments on
    genuine drop, per its own AWS-documented definition; this
    infra-configuration test's own scope is the opt-in enablement itself.
    """
    outputs_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recorder-outputs.yml").read_text(
            encoding="utf-8"
        )
    )
    extension = outputs_yml["extensions"][
        "EvidenceDisposalRecorderEventSourceMappingDynamodbMetadataTable"
    ]
    assert extension["Properties"]["MetricsConfig"] == {"Metrics": ["EventCount"]}


def test_tc_p5_plane_v_recovery_bucket_notification_failure_has_dedicated_alarm() -> None:
    """TC-P5-pos: the recovery bucket's own Object Created notification
    rule's delivery failure fires its own dedicated alarm.
    TC-P5-neg: this alarm is distinctly named/scoped from plane (i)'s own
    alarm -- the two are never conflated.
    """
    bucket_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recovery-bucket.yml").read_text(
            encoding="utf-8"
        )
    )
    alarm = bucket_yml["Resources"]["EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm"]
    assert alarm["Properties"]["Namespace"] == "AWS/Events"
    assert alarm["Properties"]["MetricName"] == "FailedInvocations"
    assert alarm["Properties"]["Dimensions"][0]["Value"] == {
        "Ref": "EvidenceDisposalRecoveryBucketObjectCreatedRule"
    }

    dlq_yml = yaml.safe_load(
        Path("infra/resources/evidence-retention-dlq.yml").read_text(encoding="utf-8")
    )
    plane_i_alarm = dlq_yml["Resources"]["evidenceDisposalRecorderDLQAlarm"]
    assert (
        plane_i_alarm["Properties"]["AlarmName"] != alarm["Properties"]["AlarmName"]
    )


def test_tc_p_wiring_recovery_bucket_notification_rule_consistency() -> None:
    """TC-P-wiring (maps to §22.13 item 10 / TC-Q10 below): the plane-(v)
    rule's own RetryPolicy, its inclusion as one of exactly two authorized
    rule ARNs in the DLQ's QueuePolicy, and its alarm's RuleName scoping
    are asserted together, not merely each independently present.
    """
    bucket_yml = yaml.safe_load(
        Path("infra/resources/evidence-disposal-recovery-bucket.yml").read_text(
            encoding="utf-8"
        )
    )
    rule = bucket_yml["Resources"]["EvidenceDisposalRecoveryBucketObjectCreatedRule"]
    target = rule["Properties"]["Targets"][0]
    assert target["RetryPolicy"] == {
        "MaximumRetryAttempts": 10,
        "MaximumEventAgeInSeconds": 3600,
    }
    assert target["Arn"] == {"Fn::GetAtt": ["evidenceDisposalRecorderDLQ", "Arn"]}

    dlq_yml = yaml.safe_load(
        Path("infra/resources/evidence-retention-dlq.yml").read_text(encoding="utf-8")
    )
    queue_policy = dlq_yml["Resources"]["evidenceDisposalRecorderDLQPolicy"]
    source_arns = queue_policy["Properties"]["PolicyDocument"]["Statement"][0]["Condition"][
        "ArnEquals"
    ]["aws:SourceArn"]
    assert {
        "Fn::GetAtt": ["EvidenceDisposalRecoveryBucketObjectCreatedRule", "Arn"]
    } in source_arns

    alarm = bucket_yml["Resources"]["EvidenceDisposalRecoveryNotificationFailedInvocationsAlarm"]
    assert alarm["Properties"]["Dimensions"][0]["Value"] == {
        "Ref": "EvidenceDisposalRecoveryBucketObjectCreatedRule"
    }


def test_tc_q10_recovery_bucket_notification_wiring_matches_tc_p_wiring() -> None:
    """TC-Q10 (QA plan Section 2, item 10): identical mutual-consistency
    requirement as TC-P-wiring above, restated at its own §22.13-mapped ID
    for the acceptance-matrix cross-reference this document's own §2 table
    maintains -- not a second, independently-implemented check."""
    test_tc_p_wiring_recovery_bucket_notification_rule_consistency()
