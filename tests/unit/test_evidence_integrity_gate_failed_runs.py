"""Regression tests for EVERY_TERMINAL_RUN_HAS_EVIDENCE gate exemption of FAILED runs.

Root cause (Round 5 — bugfix/phase3-running-after-window-rca-v2):
    The finalization integrity gate check CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    previously required EVERY terminal RUN (COMPLETED + FAILED) to have a
    corresponding S3 evidence object.

    FAILED runs never write S3 evidence by design: the orchestrator writes the
    S3 result *before* updating the DynamoDB status to COMPLETED.  Any exception
    on or before the S3 write results in a FAILED DynamoDB record with
    raw_result_s3_key=None and no S3 object.  Requiring S3 evidence for FAILED
    runs therefore always produces a false-positive gate failure.

Fix (Check 3 in finalization_gate.py):
    Only COMPLETED runs must have S3 evidence.  FAILED runs are exempted from
    the S3 evidence requirement.  The gate still fails closed when a COMPLETED
    run is missing evidence.

Related fixes in the same commit:
    - Fix B: audit_finalization_handler.py line 601 now reads RAW_RESULTS_BUCKET
      (was EVIDENCE_BUCKET) for consistency with the system-wide env var name.
    - Fix C: AuditFinalizationLambdaRole in phase4-aggregation-iam.yml now
      grants s3:ListBucket and s3:GetObject / s3:HeadObject on the results
      bucket (previously missing, causing AccessDenied on list_objects_v2).

Test IDs follow the specification from the Round 5 RCA brief:
    EIG-01 through EIG-06
"""

from __future__ import annotations

from pathlib import Path

from release_confidence_platform.audit_lifecycle.finalization_gate import (
    CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE,
    finalization_integrity_gate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLIENT_ID = "client_test_eig"
AUDIT_ID = "audit_eig_001"

IAM_FILE = Path("infra/resources/phase4-aggregation-iam.yml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_key(run_id: str) -> str:
    return f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{run_id}/results.json"


def _make_run(run_id: str, status: str) -> dict:
    return {"run_id": run_id, "status": status}


def _audit(execution_count: int) -> dict:
    """Return a minimal audit dict that satisfies gate input validation."""
    return {
        "finalization": {"execution_count": execution_count},
        "execution_counters": {"total_completed": execution_count},
    }


def _read_finalization_role_section() -> str:
    """Return the AuditFinalizationLambdaRole section of the IAM YAML file.

    Slices from the role declaration to the start of AuditAggregationLambdaRole
    so that aggregation permissions cannot satisfy finalization assertions.
    """
    content = IAM_FILE.read_text(encoding="utf-8")
    start = content.find("AuditFinalizationLambdaRole:")
    end = content.find("AuditAggregationLambdaRole:", start)
    if start == -1:
        raise AssertionError(
            f"AuditFinalizationLambdaRole not found in {IAM_FILE}."
        )
    return content[start:end] if end != -1 else content[start:]


# ---------------------------------------------------------------------------
# EIG-01: COMPLETED run with S3 evidence present — gate passes
# ---------------------------------------------------------------------------


def test_eig_01_completed_run_with_evidence_gate_passes() -> None:
    """EIG-01: A single COMPLETED run whose S3 evidence key is present must pass.

    This is the positive happy-path for COMPLETED runs after the Fix A change.
    The gate must still enforce evidence for COMPLETED runs.
    """
    run = _make_run("run_eig_01", "COMPLETED")
    s3_keys = [_raw_key("run_eig_01")]
    audit = _audit(execution_count=1)

    result = finalization_integrity_gate(
        audit=audit,
        run_records=[run],
        s3_evidence_keys=s3_keys,
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )

    assert result.passed, (
        "Gate must pass when every COMPLETED run has a corresponding S3 evidence key. "
        f"Failures: {[f.detail for f in result.failures]}"
    )
    evidence_failures = [
        f for f in result.failures if f.check == CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    ]
    assert not evidence_failures, (
        f"Unexpected EVERY_TERMINAL_RUN_HAS_EVIDENCE failures: {evidence_failures}"
    )


# ---------------------------------------------------------------------------
# EIG-02: COMPLETED run with S3 evidence absent — gate fails closed
# ---------------------------------------------------------------------------


def test_eig_02_completed_run_without_evidence_gate_fails() -> None:
    """EIG-02: A COMPLETED run with no S3 evidence key must cause the gate to fail.

    Fix A must not weaken the gate for COMPLETED runs.  Missing S3 evidence for
    a COMPLETED run is always anomalous (the orchestrator writes evidence before
    setting status=COMPLETED).
    """
    run = _make_run("run_eig_02", "COMPLETED")
    audit = _audit(execution_count=1)

    result = finalization_integrity_gate(
        audit=audit,
        run_records=[run],
        s3_evidence_keys=[],  # No S3 evidence at all
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )

    assert not result.passed, (
        "Gate must fail when a COMPLETED run has no corresponding S3 evidence key."
    )
    evidence_failures = [
        f for f in result.failures if f.check == CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    ]
    assert len(evidence_failures) == 1, (
        f"Expected exactly 1 EVERY_TERMINAL_RUN_HAS_EVIDENCE failure, "
        f"got {len(evidence_failures)}: {[f.detail for f in evidence_failures]}"
    )
    assert "run_eig_02" in evidence_failures[0].detail, (
        f"Failure detail must reference run_eig_02, got: {evidence_failures[0].detail}"
    )
    assert "COMPLETED" in evidence_failures[0].detail, (
        f"Failure detail must indicate the COMPLETED status, got: {evidence_failures[0].detail}"
    )


# ---------------------------------------------------------------------------
# EIG-03: FAILED run with no S3 evidence — gate passes (exemption)
# ---------------------------------------------------------------------------


def test_eig_03_failed_run_without_evidence_gate_passes() -> None:
    """EIG-03: A FAILED run with no S3 evidence must NOT block finalization.

    This is the primary regression guard for the Round 5 defect.  Before Fix A,
    this scenario produced a false-positive EVERY_TERMINAL_RUN_HAS_EVIDENCE
    gate failure, blocking finalization of any audit that contained failed runs.

    After Fix A, FAILED runs are exempt from the S3 evidence requirement.
    """
    run = _make_run("run_eig_03", "FAILED")
    audit = _audit(execution_count=1)

    result = finalization_integrity_gate(
        audit=audit,
        run_records=[run],
        s3_evidence_keys=[],  # No S3 evidence — expected for FAILED runs
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )

    evidence_failures = [
        f for f in result.failures if f.check == CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    ]
    assert not evidence_failures, (
        "Gate must NOT raise EVERY_TERMINAL_RUN_HAS_EVIDENCE for a FAILED run with "
        f"no S3 evidence.  This is the Round 5 regression.  "
        f"Unexpected failures: {[f.detail for f in evidence_failures]}"
    )


# ---------------------------------------------------------------------------
# EIG-04: Mixed — COMPLETED with evidence + FAILED without evidence — gate passes
# ---------------------------------------------------------------------------


def test_eig_04_mixed_completed_with_evidence_and_failed_without_gate_passes() -> None:
    """EIG-04: 3 COMPLETED (all with evidence) + 2 FAILED (no evidence) — gate passes.

    This is the realistic production scenario: an audit window produces a mix of
    successful and failed run occurrences.  The COMPLETED runs all have S3
    evidence; the FAILED runs do not.  The gate must pass under this condition.
    """
    completed_runs = [_make_run(f"run_ok_{i}", "COMPLETED") for i in range(3)]
    failed_runs = [_make_run(f"run_fail_{i}", "FAILED") for i in range(2)]
    all_runs = completed_runs + failed_runs
    s3_keys = [_raw_key(r["run_id"]) for r in completed_runs]
    audit = _audit(execution_count=5)

    result = finalization_integrity_gate(
        audit=audit,
        run_records=all_runs,
        s3_evidence_keys=s3_keys,
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )

    assert result.passed, (
        "Gate must pass when all COMPLETED runs have evidence and FAILED runs have none. "
        f"Failures: {[f.detail for f in result.failures]}"
    )
    evidence_failures = [
        f for f in result.failures if f.check == CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    ]
    assert not evidence_failures, (
        f"No EVERY_TERMINAL_RUN_HAS_EVIDENCE failures expected; "
        f"got: {[f.detail for f in evidence_failures]}"
    )


# ---------------------------------------------------------------------------
# EIG-05: Mixed — 1 COMPLETED missing evidence + 2 FAILED without evidence — gate fails
# ---------------------------------------------------------------------------


def test_eig_05_mixed_one_completed_missing_evidence_gate_fails() -> None:
    """EIG-05: 3 COMPLETED (2 with evidence, 1 without) + 2 FAILED without evidence.

    The gate must fail because one COMPLETED run is missing S3 evidence.
    The two FAILED runs must NOT contribute additional failures.
    """
    completed_with_evidence = [_make_run(f"run_ok_{i}", "COMPLETED") for i in range(2)]
    completed_missing_evidence = _make_run("run_missing", "COMPLETED")
    failed_runs = [_make_run(f"run_fail_{i}", "FAILED") for i in range(2)]
    all_runs = completed_with_evidence + [completed_missing_evidence] + failed_runs
    # S3 keys only for the two COMPLETED runs that have evidence
    s3_keys = [_raw_key(r["run_id"]) for r in completed_with_evidence]
    audit = _audit(execution_count=5)

    result = finalization_integrity_gate(
        audit=audit,
        run_records=all_runs,
        s3_evidence_keys=s3_keys,
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )

    assert not result.passed, (
        "Gate must fail when a COMPLETED run is missing S3 evidence."
    )
    evidence_failures = [
        f for f in result.failures if f.check == CHECK_EVERY_TERMINAL_RUN_HAS_EVIDENCE
    ]
    assert len(evidence_failures) == 1, (
        "Exactly 1 EVERY_TERMINAL_RUN_HAS_EVIDENCE failure expected "
        f"(the missing COMPLETED run), got {len(evidence_failures)}: "
        f"{[f.detail for f in evidence_failures]}"
    )
    assert "run_missing" in evidence_failures[0].detail, (
        f"Failure detail must reference run_missing, got: {evidence_failures[0].detail}"
    )
    # Verify FAILED runs did not contribute failures
    failed_run_ids = {r["run_id"] for r in failed_runs}
    for failure in evidence_failures:
        for fid in failed_run_ids:
            assert fid not in failure.detail, (
                f"FAILED run {fid} must not appear in EVERY_TERMINAL_RUN_HAS_EVIDENCE "
                f"failure details.  Got: {failure.detail}"
            )


# ---------------------------------------------------------------------------
# EIG-06: IAM regression — AuditFinalizationLambdaRole must include S3 permissions
# ---------------------------------------------------------------------------


def test_eig_06_iam_finalization_role_grants_s3_list_bucket() -> None:
    """EIG-06a: AuditFinalizationLambdaRole must include s3:ListBucket.

    The finalization handler calls S3StorageClient.list_raw_evidence_keys() which
    issues a list_objects_v2 API call.  Without s3:ListBucket the call raises
    AccessDenied.  This was Root Cause 3 identified in the Round 5 RCA.
    """
    assert IAM_FILE.exists(), (
        f"{IAM_FILE} does not exist. Cannot verify S3 permissions."
    )
    role_section = _read_finalization_role_section()
    assert "s3:ListBucket" in role_section, (
        "s3:ListBucket is missing from AuditFinalizationLambdaRole in "
        f"{IAM_FILE}.  This permission is required by list_raw_evidence_keys() "
        "called from _complete_finalization() in the finalization handler."
    )


def test_eig_06_iam_finalization_role_grants_s3_get_object() -> None:
    """EIG-06b: AuditFinalizationLambdaRole must include s3:GetObject.

    The finalization handler (via S3StorageClient) may call GetObject or
    HeadObject to verify evidence existence.  Without s3:GetObject and
    s3:HeadObject the check raises AccessDenied.  This was Root Cause 3
    identified in the Round 5 RCA.
    """
    assert IAM_FILE.exists(), (
        f"{IAM_FILE} does not exist. Cannot verify S3 permissions."
    )
    role_section = _read_finalization_role_section()
    assert "s3:GetObject" in role_section, (
        "s3:GetObject is missing from AuditFinalizationLambdaRole in "
        f"{IAM_FILE}.  This permission is required by the S3 evidence verification "
        "path in _complete_finalization()."
    )


def test_eig_06_iam_finalization_role_grants_s3_head_object() -> None:
    """EIG-06c: AuditFinalizationLambdaRole must include s3:HeadObject.

    Pair with s3:GetObject — both are required for full evidence verification.
    """
    assert IAM_FILE.exists(), (
        f"{IAM_FILE} does not exist. Cannot verify S3 permissions."
    )
    role_section = _read_finalization_role_section()
    assert "s3:HeadObject" in role_section, (
        "s3:HeadObject is missing from AuditFinalizationLambdaRole in "
        f"{IAM_FILE}.  This permission is required alongside s3:GetObject for "
        "evidence verification in _complete_finalization()."
    )


def test_eig_06_iam_finalization_role_s3_resource_scoped_to_raw_results() -> None:
    """EIG-06d: S3 permissions must be scoped to the raw-results bucket prefix.

    Both the ListBucket (with prefix condition) and GetObject/HeadObject
    statements must reference the raw-results/* path, not a wildcard bucket.
    This verifies the scoping invariant so the permissions are neither
    over-permissive nor under-scoped.
    """
    assert IAM_FILE.exists(), (
        f"{IAM_FILE} does not exist. Cannot verify S3 permission scoping."
    )
    role_section = _read_finalization_role_section()
    assert "raw-results/*" in role_section, (
        "S3 permissions in AuditFinalizationLambdaRole must be scoped to "
        "'raw-results/*' but no such path was found in the role section of "
        f"{IAM_FILE}.  Verify that both the ListBucket condition and the "
        "GetObject/HeadObject resource use the raw-results/* prefix."
    )
