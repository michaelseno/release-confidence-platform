"""Regression guard: AuditFinalizationLambdaRole DynamoDB permission coverage.

This test was introduced in Round 4 of the phase3-running-after-window RCA
investigation after an AccessDeniedException on dynamodb:Query during
list_run_records() halted the finalization handler in the AWS dev environment.

The finalization handler end-to-end execution path requires these DynamoDB
actions against the MetadataTable:

    dynamodb:GetItem   — get_audit_metadata()
    dynamodb:Query     — list_run_records() (paginated SK begins_with scan)
    dynamodb:PutItem   — put_aggregation_job_intent_once()
    dynamodb:UpdateItem — append_lifecycle_transition(), record_finalization(),
                          update_aggregation_job_intent()

All four must be present in the AuditFinalizationLambdaRole IAM policy declared
in infra/resources/phase4-aggregation-iam.yml.  Adding or removing required
DynamoDB operations from the handler without updating the IAM policy will cause
this test to fail, prompting an IAM policy review before deployment.

Do not edit this test to work around a missing permission — update the IAM
policy in phase4-aggregation-iam.yml instead.
"""
from pathlib import Path

IAM_FILE = Path("infra/resources/phase4-aggregation-iam.yml")

# Complete set of DynamoDB actions that AuditFinalizationLambdaRole must
# declare to allow the finalization handler to run without AccessDenied errors.
REQUIRED_FINALIZATION_DYNAMODB_ACTIONS = {
    "dynamodb:GetItem",
    "dynamodb:Query",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
}


def _read_finalization_role_policy() -> str:
    """Return only the AuditFinalizationLambdaRole section of the IAM file.

    The file also contains AuditAggregationLambdaRole.  We isolate the
    finalization section by slicing from the role declaration up to (but not
    including) the aggregation role declaration so that aggregation permissions
    cannot satisfy the finalization assertions.
    """
    content = IAM_FILE.read_text(encoding="utf-8")
    start = content.find("AuditFinalizationLambdaRole:")
    end = content.find("AuditAggregationLambdaRole:", start)
    if start == -1:
        raise AssertionError(
            f"AuditFinalizationLambdaRole not found in {IAM_FILE}. "
            "Ensure the role exists and is declared before AuditAggregationLambdaRole."
        )
    if end == -1:
        return content[start:]
    return content[start:end]


def test_audit_finalization_iam_file_exists() -> None:
    """The IAM file that declares AuditFinalizationLambdaRole must exist."""
    assert IAM_FILE.exists(), (
        f"{IAM_FILE} does not exist. "
        "The AuditFinalizationLambdaRole IAM policy must be declared in this file."
    )


def test_audit_finalization_role_declared() -> None:
    """AuditFinalizationLambdaRole must be declared in the IAM resource file."""
    content = IAM_FILE.read_text(encoding="utf-8")
    assert "AuditFinalizationLambdaRole:" in content, (
        "AuditFinalizationLambdaRole is not declared in "
        f"{IAM_FILE}. Add the role definition or update the file path."
    )


def test_audit_finalization_role_grants_dynamodb_query() -> None:
    """AuditFinalizationLambdaRole must include dynamodb:Query.

    list_run_records() in AuditMetadataRepository performs a DynamoDB Query
    using begins_with(SK, 'AUDIT#<audit_id>#RUN#').  Without this permission
    the finalization handler raises AccessDeniedException and the audit remains
    stuck in RUNNING or FINALIZING.  This was the root cause of the Round 4
    HITL failure.
    """
    policy_section = _read_finalization_role_policy()
    assert "dynamodb:Query" in policy_section, (
        "dynamodb:Query is missing from AuditFinalizationLambdaRole. "
        "Add it to the DynamoDB statement in infra/resources/phase4-aggregation-iam.yml. "
        "This permission is required by list_run_records() called from _complete_finalization()."
    )


def test_audit_finalization_role_grants_all_required_dynamodb_actions() -> None:
    """AuditFinalizationLambdaRole must declare all required DynamoDB actions.

    Checks the complete set of DynamoDB operations exercised by the finalization
    handler's end-to-end execution path.  A missing action will cause an
    AccessDeniedException in the AWS runtime even though unit tests pass.
    """
    policy_section = _read_finalization_role_policy()
    missing = {
        action
        for action in REQUIRED_FINALIZATION_DYNAMODB_ACTIONS
        if action not in policy_section
    }
    assert not missing, (
        f"AuditFinalizationLambdaRole is missing DynamoDB action(s): {sorted(missing)}. "
        "Update infra/resources/phase4-aggregation-iam.yml to include all required actions. "
        f"Full required set: {sorted(REQUIRED_FINALIZATION_DYNAMODB_ACTIONS)}"
    )


def test_audit_finalization_role_grants_lambda_invoke() -> None:
    """AuditFinalizationLambdaRole must include lambda:InvokeFunction.

    The finalization handler invokes AuditAggregationLambdaFunction asynchronously
    via _trigger_aggregation_after_finalization().  Without this permission the
    aggregation trigger call will fail with AccessDeniedException.
    """
    policy_section = _read_finalization_role_policy()
    assert "lambda:InvokeFunction" in policy_section, (
        "lambda:InvokeFunction is missing from AuditFinalizationLambdaRole. "
        "Add it to infra/resources/phase4-aggregation-iam.yml."
    )


def test_audit_finalization_role_metadata_table_resource_present() -> None:
    """AuditFinalizationLambdaRole DynamoDB statement must reference MetadataTable.

    The DynamoDB permissions must be scoped to the MetadataTable CloudFormation
    resource (via Fn::GetAtt) rather than a wildcard or hard-coded ARN, to ensure
    stage-specific table isolation and to allow CloudFormation to track the
    dependency.
    """
    policy_section = _read_finalization_role_policy()
    assert "MetadataTable" in policy_section, (
        "MetadataTable resource reference not found in the AuditFinalizationLambdaRole "
        "DynamoDB statement. Use Fn::GetAtt: [MetadataTable, Arn] as the Resource."
    )


# ---------------------------------------------------------------------------
# S3 permissions — added in Round 5 (bugfix/phase3-running-after-window-rca-v2)
#
# Root Cause 3 from the Round 5 RCA: AuditFinalizationLambdaRole had no S3
# grants at all.  The finalization handler calls
# S3StorageClient.list_raw_evidence_keys() (list_objects_v2) inside
# _complete_finalization() to gather evidence keys for the integrity gate.
# Without s3:ListBucket the call raises AccessDenied and the gate never runs.
# ---------------------------------------------------------------------------


def test_audit_finalization_role_grants_s3_list_bucket() -> None:
    """AuditFinalizationLambdaRole must include s3:ListBucket.

    The finalization handler calls S3StorageClient.list_raw_evidence_keys()
    which issues a list_objects_v2 API call.  Without this permission the call
    raises AccessDenied, preventing the integrity gate from running at all.
    """
    policy_section = _read_finalization_role_policy()
    assert "s3:ListBucket" in policy_section, (
        "s3:ListBucket is missing from AuditFinalizationLambdaRole. "
        "Add it to infra/resources/phase4-aggregation-iam.yml. "
        "This permission is required by list_raw_evidence_keys() called from "
        "_complete_finalization() in the finalization handler."
    )


def test_audit_finalization_role_grants_s3_get_object() -> None:
    """AuditFinalizationLambdaRole must include s3:GetObject.

    Required for the S3 evidence verification path in _complete_finalization().
    Without it, evidence reads raise AccessDenied.
    """
    policy_section = _read_finalization_role_policy()
    assert "s3:GetObject" in policy_section, (
        "s3:GetObject is missing from AuditFinalizationLambdaRole. "
        "Add it to infra/resources/phase4-aggregation-iam.yml."
    )


def test_audit_finalization_role_grants_s3_head_object() -> None:
    """AuditFinalizationLambdaRole must include s3:HeadObject.

    Pair with s3:GetObject — both are required for full S3 evidence verification.
    """
    policy_section = _read_finalization_role_policy()
    assert "s3:HeadObject" in policy_section, (
        "s3:HeadObject is missing from AuditFinalizationLambdaRole. "
        "Add it to infra/resources/phase4-aggregation-iam.yml."
    )
