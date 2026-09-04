"""Tests for A1.4a disposal-recorder `StageConfig` fields and
`validate_disposal_recorder_config()` (Increment 2).

Covers `docs/qa/a1_4a_disposal_recorder_test_plan.md` Area (g) TC-G5,
TC-G5-pos, TC-G6, TC-G7 (a-d), TC-G8 (a/b) (Section 3.7); ADR Non-Negotiable
Invariant 51; Technical Design Section 22.9.5.

Fixture shapes follow §3.7's table and §4's Edge Cases exactly: the "wrong-
stage-region" case (TC-G7(c)) is distinct from the ARN-vs-ARN mismatch case
(TC-G7(b)) and asserted as such; both independently-documented reserved-
suffix rules (`--x-s3`, `-an`) get their own dedicated fixtures, never
merged into one test case (TC-G6).
"""

from __future__ import annotations

import pytest

from release_confidence_platform.config.stage_config import (
    DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN,
    DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN,
    DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN,
    METADATA_TABLE_STREAM_ARN_PATTERN,
    StageConfig,
    validate_disposal_recorder_config,
)
from release_confidence_platform.core.exceptions import ConfigError

_VALID_UUID = "12345678-1234-1234-1234-123456789012"
_VALID_BUCKET = "rcp-dev-disposal-recovery"
_VALID_FUNCTION_ARN = "arn:aws:lambda:us-east-1:111111111111:function:evidenceDisposalRecorder"
_VALID_STREAM_ARN = (
    "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/2024-01-01T00:00:00.000"
)


def _valid_config(**overrides: object) -> StageConfig:
    base = dict(
        stage="dev",
        region="us-east-1",
        aws_profile="rcp-dev",
        config_bucket="rcp-dev-config",
        audit_metadata_table="MetadataTable",
        orchestrator_function_name="rcp-dev-orchestrator",
        scheduler_group_name="rcp-dev-schedules",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="arn:aws:lambda:us-east-1:111111111111:function:exec",
        scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:111111111111:function:final",
        scheduler_role_arn="arn:aws:iam::111111111111:role/scheduler",
        disposal_recovery_bucket_name=_VALID_BUCKET,
        disposal_recorder_function_arn=_VALID_FUNCTION_ARN,
        disposal_recorder_event_source_mapping_uuid=_VALID_UUID,
        metadata_table_stream_arn=_VALID_STREAM_ARN,
    )
    base.update(overrides)
    return StageConfig(**base)


# ---------------------------------------------------------------------------
# TC-G5: config validation ordering, negative/failure path
# ---------------------------------------------------------------------------


def test_tc_g5_placeholder_config_raises_disposal_recorder_config_error():
    config = _valid_config(disposal_recovery_bucket_name="")
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    assert excinfo.value.error_type == "DISPOSAL_RECORDER_CONFIG_ERROR"
    assert "disposal_recovery_bucket_name" in str(excinfo.value)


def test_tc_g5_structurally_malformed_non_placeholder_config_raises():
    config = _valid_config(disposal_recorder_function_arn="not-an-arn-at-all")
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    assert excinfo.value.error_type == "DISPOSAL_RECORDER_CONFIG_ERROR"
    assert "disposal_recorder_function_arn" in str(excinfo.value)


def test_tc_g5_all_failures_collected_not_short_circuited():
    config = _valid_config(
        disposal_recovery_bucket_name="",
        disposal_recorder_event_source_mapping_uuid="not-a-uuid",
        disposal_recorder_function_arn="arn:aws:lambda:us-west-2:222222222222:function:other",
        metadata_table_stream_arn=(
            "arn:aws:dynamodb:eu-west-1:333333333333:table/OtherTable/stream/2024-01-01T00:00:00.000"
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    message = str(excinfo.value)
    assert "disposal_recovery_bucket_name" in message
    assert "disposal_recorder_event_source_mapping_uuid" in message
    assert "disposal_recorder_function_arn" in message
    assert "metadata_table_stream_arn" in message
    assert "region mismatch" in message
    assert "account mismatch" in message


def test_tc_g5_instance_method_delegates_to_module_function():
    config = _valid_config(disposal_recovery_bucket_name="")
    with pytest.raises(ConfigError):
        config.validate_disposal_recorder_config()


# ---------------------------------------------------------------------------
# TC-G5-pos: config validation ordering, POSITIVE path + ordering-dependency
# proof (new, per corrected QA plan; cross-ref §22.13 item 18)
# ---------------------------------------------------------------------------


def test_tc_g5_pos_valid_config_passes_validation():
    config = _valid_config()
    validate_disposal_recorder_config(config)  # must not raise


def test_tc_g5_pos_aws_client_factory_construction_never_reached_when_validation_fails(
    monkeypatch,
):
    """Ordering-sensitive double: a fake validator/factory pair recording
    call order proves AwsClientFactory construction genuinely depends on
    validation succeeding -- not merely happens to run after it by
    incidental code order (Technical Design Section 22.9.5's "Ordering"
    paragraph, mirrored by `operator_cli/main.py`'s real dispatch
    sequence)."""
    call_order: list[str] = []

    def _raising_validate(self: StageConfig) -> None:
        call_order.append("validate")
        raise ConfigError("boom", "DISPOSAL_RECORDER_CONFIG_ERROR")

    class _FakeAwsClientFactory:
        def __init__(self, stage_config: StageConfig) -> None:
            call_order.append("constructed")

    monkeypatch.setattr(StageConfig, "validate_disposal_recorder_config", _raising_validate)
    config = _valid_config()

    def _dispatch_like_main() -> None:
        config.validate_disposal_recorder_config()
        _FakeAwsClientFactory(config)

    with pytest.raises(ConfigError):
        _dispatch_like_main()

    assert call_order == ["validate"]


def test_tc_g5_pos_aws_client_factory_constructed_only_after_validation_succeeds(monkeypatch):
    call_order: list[str] = []

    def _passing_validate(self: StageConfig) -> None:
        call_order.append("validate")

    class _FakeAwsClientFactory:
        def __init__(self, stage_config: StageConfig) -> None:
            call_order.append("constructed")

    monkeypatch.setattr(StageConfig, "validate_disposal_recorder_config", _passing_validate)
    config = _valid_config()

    def _dispatch_like_main() -> None:
        config.validate_disposal_recorder_config()
        _FakeAwsClientFactory(config)

    _dispatch_like_main()

    assert call_order == ["validate", "constructed"]


# ---------------------------------------------------------------------------
# TC-G6: structural regex validation -- 1 positive + >=1 negative per
# pattern, plus commercial-partition-lock, variable-precision stream-label,
# and both independently-named reserved-suffix (`--x-s3`, `-an`) fixtures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (_VALID_BUCKET, True),
        ("192.168.1.1", False),  # IPv4-shaped
        ("rcp..dev-disposal-recovery", False),  # consecutive periods
        ("xn--bucket-name", False),  # reserved prefix
        ("sthree-bucket-name", False),  # reserved prefix
        ("amzn-s3-demo-bucket", False),  # reserved prefix
        ("valid-bucket--x-s3", False),  # reserved suffix: directory-bucket namespace
        # independently-documented -an suffix, never merged with --x-s3
        ("valid-bucket-an", False),
    ],
)
def test_tc_g6_disposal_recovery_bucket_name_pattern(value: str, expected: bool):
    assert bool(DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN.fullmatch(value)) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (_VALID_UUID, True),
        ("not-a-uuid", False),
        ("1234567812341234123412345678901", False),  # no hyphens
        ("12345678-1234-1234-1234-12345678901", False),  # last group too short
    ],
)
def test_tc_g6_event_source_mapping_uuid_pattern(value: str, expected: bool):
    assert bool(DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN.fullmatch(value)) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (_VALID_FUNCTION_ARN, True),
        ("arn:aws-us-gov:lambda:us-gov-west-1:111111111111:function:foo", False),  # partition lock
        ("arn:aws-cn:lambda:cn-north-1:111111111111:function:foo", False),  # partition lock
        ("arn:aws:lambda:us-east-1:111111111111:function:foo:1", False),  # qualified ARN rejected
        ("not-an-arn-at-all", False),
    ],
)
def test_tc_g6_function_arn_pattern(value: str, expected: bool):
    assert bool(DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN.fullmatch(value)) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (_VALID_STREAM_ARN, True),  # 3-digit fractional seconds
        (
            "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/2024-01-01T00:00:00",
            True,
        ),  # no fractional seconds
        (
            "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/"
            "2024-01-01T00:00:00.12345",
            True,
        ),  # non-3-digit fractional seconds
        (
            "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/not-a-date-shape",
            False,
        ),  # non-date/time-shaped negative
        (
            "arn:aws-us-gov:dynamodb:us-gov-west-1:111111111111:table/MetadataTable/stream/"
            "2024-01-01T00:00:00.000",
            False,
        ),  # partition lock
    ],
)
def test_tc_g6_metadata_table_stream_arn_pattern(value: str, expected: bool):
    assert bool(METADATA_TABLE_STREAM_ARN_PATTERN.fullmatch(value)) is expected


# ---------------------------------------------------------------------------
# TC-G7: cross-field region consistency, bound to StageConfig.region
# (a) all-agree positive; (b) ARN-vs-ARN mismatch; (c) "wrong-stage-region"
# -- ARNs agree with each other but disagree with StageConfig.region; (d)
# account mismatch.
# ---------------------------------------------------------------------------


def test_tc_g7_a_all_regions_agree_passes():
    config = _valid_config()
    validate_disposal_recorder_config(config)  # must not raise


def test_tc_g7_b_arn_vs_arn_region_mismatch():
    config = _valid_config(
        disposal_recorder_function_arn=(
            "arn:aws:lambda:us-east-1:111111111111:function:evidenceDisposalRecorder"
        ),
        metadata_table_stream_arn=(
            "arn:aws:dynamodb:us-west-2:111111111111:table/MetadataTable/stream/"
            "2024-01-01T00:00:00.000"
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    assert "disposal_recorder_function_arn/metadata_table_stream_arn (region mismatch)" in str(
        excinfo.value
    )


def test_tc_g7_c_wrong_stage_region_both_arns_agree_but_disagree_with_stage_config_region():
    """Both ARNs agree with each other (us-west-2) but disagree with
    StageConfig.region (us-east-1) -- must name both region-vs-
    StageConfig.region rules, must NOT name the ARN-vs-ARN rule."""
    config = _valid_config(
        region="us-east-1",
        disposal_recorder_function_arn=(
            "arn:aws:lambda:us-west-2:111111111111:function:evidenceDisposalRecorder"
        ),
        metadata_table_stream_arn=(
            "arn:aws:dynamodb:us-west-2:111111111111:table/MetadataTable/stream/"
            "2024-01-01T00:00:00.000"
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    message = str(excinfo.value)
    assert "disposal_recorder_function_arn (region does not match StageConfig.region)" in message
    assert "metadata_table_stream_arn (region does not match StageConfig.region)" in message
    assert (
        "disposal_recorder_function_arn/metadata_table_stream_arn (region mismatch)" not in message
    )


def test_tc_g7_d_account_mismatch():
    config = _valid_config(
        disposal_recorder_function_arn=(
            "arn:aws:lambda:us-east-1:111111111111:function:evidenceDisposalRecorder"
        ),
        metadata_table_stream_arn=(
            "arn:aws:dynamodb:us-east-1:222222222222:table/MetadataTable/stream/"
            "2024-01-01T00:00:00.000"
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    assert "disposal_recorder_function_arn/metadata_table_stream_arn (account mismatch)" in str(
        excinfo.value
    )


# ---------------------------------------------------------------------------
# TC-G8: stream table-identity match against StageConfig.audit_metadata_table
# ---------------------------------------------------------------------------


def test_tc_g8_a_stream_table_matches_audit_metadata_table_passes():
    config = _valid_config(audit_metadata_table="MetadataTable")
    validate_disposal_recorder_config(config)  # must not raise


def test_tc_g8_b_stream_table_does_not_match_audit_metadata_table():
    config = _valid_config(
        audit_metadata_table="MetadataTable",
        metadata_table_stream_arn=(
            "arn:aws:dynamodb:us-east-1:111111111111:table/OtherTable/stream/"
            "2024-01-01T00:00:00.000"
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        validate_disposal_recorder_config(config)
    assert "metadata_table_stream_arn (table segment does not match audit_metadata_table)" in str(
        excinfo.value
    )
