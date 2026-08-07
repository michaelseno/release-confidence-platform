from __future__ import annotations

import json

import pytest

from release_confidence_platform.operator_cli.result import render_error


def test_force_recreate_blocked_guidance_is_actionable():
    rendered = render_error(
        "audit create",
        "dev",
        "FORCE_RECREATE_BLOCKED",
        "Audit lifecycle is not eligible for force recreate",
    )

    assert "force recreate is allowed only" in rendered
    assert "DRAFT or FAILED" in rendered
    assert "rcp audit list --client-id <client_id> --stage dev --output json" in rendered
    assert "fresh audit ID/config bundle" in rendered
    assert "Do not manually mutate DynamoDB" in rendered


# ---------------------------------------------------------------------------
# Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.9) --
# sanitized text/JSON rendering coverage for every newly-reachable Phase 6
# reason code, plus DynamoDB storage/validation failure and the two
# pre-existing Phase 6 pipeline error codes newly reachable alongside
# hold coordination. Each case asserts: reason-code preservation, non-zero
# exit status via the CommandResult contract's own exit-code convention
# (render_error always represents an error, so this is checked at the
# CLI-dispatch integration layer for main.py; here we assert the rendered
# payload itself carries no false-success marker, no traceback, no AWS
# request detail, no DynamoDB/S3 key, and no client/audit identifier).
# ---------------------------------------------------------------------------

_CLIENT_ID = "client_sentinel_report_9f2c"
_AUDIT_ID = "audit_sentinel_report_7ab1"
_SENTINEL_S3_KEY = (
    f"reports/{_CLIENT_ID}/{_AUDIT_ID}/exec1/agg_v1/intel_v1/rpt_v1/rptjob_x/artifact.json"
)
_SENTINEL_DYNAMODB_KEY = f"CLIENT#{_CLIENT_ID}"
_SENTINEL_REQUEST_ID = "req-0987654321fedcba"

_LEAK_PROBE_STRINGS = (
    _CLIENT_ID,
    _AUDIT_ID,
    _SENTINEL_REQUEST_ID,
    _SENTINEL_DYNAMODB_KEY,
    _SENTINEL_S3_KEY,
)

_PHASE6_ERROR_CASES = [
    (
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "Custody period configuration was not provided to this repository instance",
    ),
    (
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "Hold coordination is not configured",
    ),
    (
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "Legal hold state concurrency retries exhausted",
    ),
    (
        "STORAGE_ERROR",
        "ReportMetadata item PK/SK does not match the expected "
        "CLIENT#{client_id}/AUDIT#{audit_id}#... shape; cannot resolve "
        "audit identity for legal-hold state resolution.",
    ),
    (
        "STORAGE_ERROR",
        "Legal-hold state could not be resolved prior to report artifact write.",
    ),
    (
        "STORAGE_CONFIG_ERROR",
        "DynamoDB table configuration is invalid",
    ),
    (
        "S3_WRITE_FAILED",
        "Failed to write report S3 artifact: connection reset",
    ),
    (
        "REPORT_GATE_ERROR",
        "Report generation prerequisite not satisfied: IntelligenceMetadata not found",
    ),
    (
        "REPORT_GENERATION_IN_PROGRESS",
        "Report generation is already in progress for this combination. "
        "Wait for the current generation to complete before retrying.",
    ),
]


@pytest.mark.parametrize("code,message", _PHASE6_ERROR_CASES)
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_phase6_error_rendering_preserves_code_and_leaks_nothing(code, message, output_format):
    rendered = render_error("generate report", "dev", code, message, output=output_format)

    assert code in rendered, f"expected reason code {code!r} to be preserved in rendered output"
    assert "Traceback" not in rendered
    assert '"status": "success"' not in rendered
    for probe in _LEAK_PROBE_STRINGS:
        assert probe not in rendered, (
            f"rendered output for {code!r} ({output_format}) unexpectedly leaked {probe!r}"
        )

    if output_format == "json":
        parsed = json.loads(rendered)
        assert parsed["status"] == "error"
        assert parsed["code"] == code
    else:
        assert "next_step:" in rendered
        assert f"code: {code}" in rendered


# ---------------------------------------------------------------------------
# Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.11.1) --
# shared, phase-neutral _error_next_step guidance for
# CUSTODY_PERIOD_CONFIG_MISSING / HOLD_COORDINATION_NOT_CONFIGURED /
# HOLD_STATE_CONCURRENCY_EXCEEDED, added once and reused identically by
# rcp generate intelligence, rcp generate report, and rcp certify audit.
# ---------------------------------------------------------------------------


def test_error_next_step_custody_period_config_missing():
    rendered = render_error(
        "certify audit",
        "dev",
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "Custody period configuration was not provided to this repository instance",
    )
    assert "next_step:" in rendered
    assert "bare retry will fail identically" in rendered
    assert "custody_periods.json" in rendered
    assert "evidentiary_classes" in rendered


def test_error_next_step_hold_coordination_not_configured():
    rendered = render_error(
        "certify audit",
        "dev",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "Hold coordination is not configured",
    )
    assert "next_step:" in rendered
    assert "construction-time" in rendered
    assert "escalate" in rendered


def test_error_next_step_hold_state_concurrency_exceeded():
    rendered = render_error(
        "certify audit",
        "dev",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "Legal hold state concurrency retries exhausted",
    )
    assert "next_step:" in rendered
    assert "retrying may succeed" in rendered
    assert "investigated before continuing" in rendered


@pytest.mark.parametrize(
    "code,message",
    [
        (
            "CUSTODY_PERIOD_CONFIG_MISSING",
            "Custody period configuration was not provided to this repository instance",
        ),
        ("HOLD_COORDINATION_NOT_CONFIGURED", "Hold coordination is not configured"),
        (
            "HOLD_STATE_CONCURRENCY_EXCEEDED",
            "Legal hold state concurrency retries exhausted",
        ),
    ],
)
def test_error_next_step_guidance_identical_across_intelligence_report_certificate(code, message):
    """The guidance text for a given code must not vary by which of
    intelligence/report/certificate triggered it -- _error_next_step has no
    phase-conditional branching at all."""
    contexts = [
        ("generate intelligence", "dev"),
        ("generate report", "staging"),
        ("certify audit", "prod"),
    ]
    next_steps = {
        render_error(command, stage, code, message).split("next_step: ", 1)[1]
        for command, stage in contexts
    }
    assert len(next_steps) == 1


def test_error_next_step_guidance_leaks_no_identifier_or_key():
    fake_client_id = "client_leaksentinel_9c3a"
    fake_audit_id = "audit_leaksentinel_1b7e"
    fake_key = (
        f"integrity/{fake_client_id}/{fake_audit_id}/exec1/cfg_v1/agg_v1/"
        "intel_v1/rpt_v1/cert_v1/certjob_x/artifact.json"
    )
    triggering_message = f"Hold coordination is not configured (key={fake_key})"

    rendered = render_error(
        "certify audit", "dev", "HOLD_COORDINATION_NOT_CONFIGURED", triggering_message
    )
    assert "next_step: " in rendered
    guidance = rendered.split("next_step: ", 1)[1]
    for probe in (fake_client_id, fake_audit_id, fake_key):
        assert probe not in guidance
