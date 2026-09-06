"""Stage resource configuration loading for operator tooling."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from release_confidence_platform.core.exceptions import ConfigError

STAGES = ("dev", "staging", "prod")
REQUIRED_FIELDS = (
    "region",
    "aws_profile",
    "config_bucket",
    "audit_metadata_table",
    "orchestrator_function_name",
    "scheduler_group_name",
    "schedule_name_prefix",
    "scheduler_execution_target_arn",
    "scheduler_finalization_target_arn",
    "scheduler_role_arn",
    # A1.4a disposal-recorder deployment-to-CLI identity configuration
    # contract (ADR Non-Negotiable Invariant 51; Technical Design Section
    # 22.9.5). Fourteen entries total, mirroring scheduler_role_arn/
    # scheduler_execution_target_arn/scheduler_finalization_target_arn's own
    # existing precedent of being REQUIRED_FIELDS despite being relevant only
    # to a specific rcp command family, not every command that loads a
    # StageConfig.
    "disposal_recovery_bucket_name",
    "disposal_recorder_function_arn",
    "disposal_recorder_event_source_mapping_uuid",
    "metadata_table_stream_arn",
)
ENV_OVERRIDES = {
    "region": "RCP_AWS_REGION",
    "aws_profile": "RCP_AWS_PROFILE",
    "config_bucket": "RCP_CONFIG_BUCKET",
    "audit_metadata_table": "RCP_AUDIT_METADATA_TABLE",
    "orchestrator_function_name": "RCP_ORCHESTRATOR_FUNCTION_NAME",
    "scheduler_group_name": "RCP_SCHEDULER_GROUP_NAME",
    "schedule_name_prefix": "RCP_SCHEDULE_NAME_PREFIX",
    "scheduler_execution_target_arn": "RCP_SCHEDULER_EXECUTION_TARGET_ARN",
    "scheduler_finalization_target_arn": "RCP_SCHEDULER_FINALIZATION_TARGET_ARN",
    "scheduler_role_arn": "RCP_SCHEDULER_ROLE_ARN",
    "disposal_recovery_bucket_name": "RCP_DISPOSAL_RECOVERY_BUCKET_NAME",
    "disposal_recorder_function_arn": "RCP_DISPOSAL_RECORDER_FUNCTION_ARN",
    "disposal_recorder_event_source_mapping_uuid": (
        "RCP_DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID"
    ),
    "metadata_table_stream_arn": "RCP_METADATA_TABLE_STREAM_ARN",
}


@dataclass(frozen=True)
class StageConfig:
    stage: str
    region: str
    aws_profile: str
    config_bucket: str
    audit_metadata_table: str
    orchestrator_function_name: str
    scheduler_group_name: str
    schedule_name_prefix: str
    scheduler_execution_target_arn: str
    scheduler_finalization_target_arn: str
    scheduler_role_arn: str
    # A1.4a disposal-recorder fields (see REQUIRED_FIELDS comment above).
    # Defaulted to "" -- not None -- so every existing direct StageConfig(...)
    # construction site across this codebase's test suite (outside this
    # increment's own twelve-file inventory, which this implementation must
    # not otherwise touch) remains unaffected; StageConfigLoader.load()'s own
    # existing missing-field enforcement is what actually makes these four
    # fields required for every `rcp` invocation once REQUIRED_FIELDS lists
    # them, exactly mirroring how the ten pre-existing fields are enforced
    # today. Documented as an implementation-necessary, non-behavior-changing
    # assumption in the implementation report.
    disposal_recovery_bucket_name: str = ""
    disposal_recorder_function_arn: str = ""
    disposal_recorder_event_source_mapping_uuid: str = ""
    metadata_table_stream_arn: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def validate_orchestrator_function_name(self) -> None:
        validate_orchestrator_function_name(self.orchestrator_function_name, stage=self.stage)

    def validate_scheduler_config(self) -> None:
        validate_scheduler_config(self)

    def validate_disposal_recorder_config(self) -> None:
        validate_disposal_recorder_config(self)


class StageConfigLoader:
    def __init__(self, *, root: Path | None = None):
        self.root = root or self._default_root()

    @staticmethod
    def _default_root() -> Path:
        module_path = Path(__file__).resolve()
        for candidate in (*module_path.parents, Path.cwd(), *Path.cwd().resolve().parents):
            if (candidate / "config" / "stages").is_dir():
                return candidate
        return module_path.parents[3]

    def load(self, stage: str, env: Mapping[str, str] | None = None) -> StageConfig:
        if stage not in STAGES:
            raise ConfigError("Invalid stage", "INVALID_STAGE")
        env = os.environ if env is None else env
        path = self.root / "config" / "stages" / f"{stage}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError("Stage config file not found", "STAGE_CONFIG_ERROR") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError("Stage config JSON is invalid", "STAGE_CONFIG_ERROR") from exc
        if not isinstance(raw, dict):
            raise ConfigError("Stage config must be an object", "STAGE_CONFIG_ERROR")
        resolved = {field: raw.get(field) for field in REQUIRED_FIELDS}
        for field, env_name in ENV_OVERRIDES.items():
            if env_name in env:
                if env[env_name].strip() == "":
                    raise ConfigError(
                        f"Environment override {env_name} must not be empty",
                        "STAGE_CONFIG_ERROR",
                    )
                resolved[field] = env[env_name]
        missing = [
            field
            for field, value in resolved.items()
            if not isinstance(value, str) or value.strip() == ""
        ]
        if missing:
            raise ConfigError(
                f"Stage config missing required fields: {', '.join(missing)}",
                "STAGE_CONFIG_ERROR",
            )
        return StageConfig(stage=stage, **resolved)


def validate_orchestrator_function_name(function_name: str, *, stage: str) -> None:
    """Reject committed placeholder Lambda targets before runtime invocation."""

    if "placeholder" in function_name.lower():
        raise ConfigError(
            f"Stage orchestrator_function_name is a placeholder for stage {stage}; set a deployed "
            "Lambda function target in config/stages/<stage>.json or export "
            "RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>",
            "LAMBDA_CONFIG_ERROR",
        )


def validate_scheduler_config(config: StageConfig) -> None:
    """Reject placeholder Scheduler resources before schedule mutation attempts."""

    invalid_fields = []
    if _is_placeholder(config.scheduler_group_name):
        invalid_fields.append("scheduler_group_name")
    if _is_placeholder(config.scheduler_role_arn) or _has_placeholder_account(
        config.scheduler_role_arn
    ):
        invalid_fields.append("scheduler_role_arn")
    if _is_placeholder(config.scheduler_execution_target_arn) or _has_placeholder_account(
        config.scheduler_execution_target_arn
    ):
        invalid_fields.append("scheduler_execution_target_arn")
    if _is_placeholder(config.scheduler_finalization_target_arn) or _has_placeholder_account(
        config.scheduler_finalization_target_arn
    ):
        invalid_fields.append("scheduler_finalization_target_arn")
    if invalid_fields:
        raise ConfigError(
            "Stage scheduler configuration contains placeholder or missing deployed resources: "
            f"{', '.join(invalid_fields)}. Export RCP_SCHEDULER_GROUP_NAME, "
            "RCP_SCHEDULER_EXECUTION_TARGET_ARN, RCP_SCHEDULER_FINALIZATION_TARGET_ARN, "
            "and RCP_SCHEDULER_ROLE_ARN from deployed scheduler outputs before running "
            "rcp audit schedule.",
            "SCHEDULER_CONFIG_ERROR",
        )


def _is_placeholder(value: str | None) -> bool:
    return not value or "placeholder" in value.lower()


def _has_placeholder_account(value: str | None) -> bool:
    return bool(value and ":000000000000:" in value)


# ---------------------------------------------------------------------------
# A1.4a disposal-recorder deployment-to-CLI identity configuration contract
# (ADR Non-Negotiable Invariant 51; Technical Design Section 22.9.5).
#
# Four compiled regex constants, colocated here (not core/validators.py) --
# these patterns are specific to disposal-recorder AWS resource-identifier
# shapes, not general-purpose identifiers core/validators.py's existing
# patterns already serve for other callers across the codebase. Verbatim
# from Technical Design Section 22.9.5's own specified patterns.
# ---------------------------------------------------------------------------

# S3 bucket name: 3-63 chars, lowercase/digits/hyphens/periods, must
# begin/end with a letter or digit, no consecutive periods, not IPv4-shaped,
# rejects AWS's three documented reserved prefixes (xn--/sthree-/
# amzn-s3-demo-; sthree-configurator retained as a redundant, harmless
# subset-of-sthree- entry), AWS's five documented reserved suffixes
# (-s3alias/--ol-s3/.mrap/--x-s3/--table-s3), and the separately-documented
# `-an` account-regional-namespace suffix.
DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN = re.compile(
    r"^(?!\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$)(?!.*\.\.)"
    r"(?!xn--)(?!sthree-)(?!sthree-configurator)(?!amzn-s3-demo-)"
    r"(?!.*(?:-s3alias|--ol-s3|\.mrap|--x-s3|--table-s3)$)"
    r"(?!.*-an$)"
    r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
)

# Canonical UUID (8-4-4-4-12 hex digit groups), the event-source-mapping's
# own UUID CloudFormation/Serverless Framework assigns.
DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Lambda function ARN, commercial `aws` partition only (never aws-us-gov/
# aws-cn -- a partition lock, not merely a region-shape check), unqualified
# form (no trailing :version/:alias segment).
DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN = re.compile(
    r"^arn:aws:lambda:"
    r"(?P<region>[a-z]{2}-[a-z]+-\d{1,2}):"
    r"(?P<account_id>\d{12}):"
    r"function:"
    r"(?P<function_name>[A-Za-z0-9_-]{1,64})$"
)

# DynamoDB Streams ARN, commercial `aws` partition only, with a
# variable-precision ISO-8601-shaped (never claimed to be semantically
# validated) stream-label component.
METADATA_TABLE_STREAM_ARN_PATTERN = re.compile(
    r"^arn:aws:dynamodb:"
    r"(?P<region>[a-z]{2}-[a-z]+-\d{1,2}):"
    r"(?P<account_id>\d{12}):"
    r"table/(?P<table_name>[A-Za-z0-9_.-]{3,255})/stream/"
    r"(?P<stream_label>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)$"
)


def validate_disposal_recorder_config(config: StageConfig) -> None:
    """Reject placeholder, structurally malformed, or cross-field-
    inconsistent disposal-recorder deployment identifiers before any AWS
    call (ADR Non-Negotiable Invariant 51; Technical Design Section 22.9.5).

    Mirrors validate_scheduler_config's collected-errors shape exactly.
    Nine checks, all performed and COLLECTED -- never short-circuited --
    into one ConfigError("...", "DISPOSAL_RECORDER_CONFIG_ERROR"):
      1-4. structural regex validity for each of the four fields;
      5. ARN-vs-ARN region agreement (function ARN vs. stream ARN);
      6. ARN-vs-ARN account agreement;
      7. function-ARN-region vs. StageConfig.region;
      8. stream-ARN-region vs. StageConfig.region;
      9. stream table-identity vs. StageConfig.audit_metadata_table.

    Called by `operator_cli/main.py`'s `disposal-recorder redrive` dispatch
    branch before `AwsClientFactory` construction and before any AWS call
    (mirroring `schedule_command`'s existing
    `validate_scheduler_config()`-before-`AwsClientFactory(...)` ordering).
    """
    invalid: list[str] = []

    if _is_placeholder(config.disposal_recovery_bucket_name):
        invalid.append("disposal_recovery_bucket_name")
    elif not DISPOSAL_RECOVERY_BUCKET_NAME_PATTERN.fullmatch(config.disposal_recovery_bucket_name):
        invalid.append("disposal_recovery_bucket_name")

    if _is_placeholder(config.disposal_recorder_event_source_mapping_uuid):
        invalid.append("disposal_recorder_event_source_mapping_uuid")
    elif not DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID_PATTERN.fullmatch(
        config.disposal_recorder_event_source_mapping_uuid
    ):
        invalid.append("disposal_recorder_event_source_mapping_uuid")

    function_arn_match = None
    if _is_placeholder(config.disposal_recorder_function_arn) or _has_placeholder_account(
        config.disposal_recorder_function_arn
    ):
        invalid.append("disposal_recorder_function_arn")
    else:
        function_arn_match = DISPOSAL_RECORDER_FUNCTION_ARN_PATTERN.fullmatch(
            config.disposal_recorder_function_arn
        )
        if function_arn_match is None:
            invalid.append("disposal_recorder_function_arn")

    stream_arn_match = None
    if _is_placeholder(config.metadata_table_stream_arn) or _has_placeholder_account(
        config.metadata_table_stream_arn
    ):
        invalid.append("metadata_table_stream_arn")
    else:
        stream_arn_match = METADATA_TABLE_STREAM_ARN_PATTERN.fullmatch(
            config.metadata_table_stream_arn
        )
        if stream_arn_match is None:
            invalid.append("metadata_table_stream_arn")

    if function_arn_match is not None and stream_arn_match is not None:
        if function_arn_match.group("region") != stream_arn_match.group("region"):
            invalid.append(
                "disposal_recorder_function_arn/metadata_table_stream_arn (region mismatch)"
            )
        if function_arn_match.group("account_id") != stream_arn_match.group("account_id"):
            invalid.append(
                "disposal_recorder_function_arn/metadata_table_stream_arn (account mismatch)"
            )

    # Corrected, TD Section 22.9.5 Round 7 item 1: bind each ARN's own
    # region to StageConfig.region directly -- two ARNs agreeing with each
    # other is not sufficient if both disagree with the configured stage.
    if function_arn_match is not None and function_arn_match.group("region") != config.region:
        invalid.append("disposal_recorder_function_arn (region does not match StageConfig.region)")

    if stream_arn_match is not None and stream_arn_match.group("region") != config.region:
        invalid.append("metadata_table_stream_arn (region does not match StageConfig.region)")

    if (
        stream_arn_match is not None
        and stream_arn_match.group("table_name") != config.audit_metadata_table
    ):
        invalid.append(
            "metadata_table_stream_arn (table segment does not match audit_metadata_table)"
        )

    if invalid:
        raise ConfigError(
            "Stage disposal-recorder configuration contains placeholder, malformed, or "
            f"inconsistent deployed resources: {', '.join(invalid)}. Export "
            "RCP_DISPOSAL_RECOVERY_BUCKET_NAME, RCP_DISPOSAL_RECORDER_FUNCTION_ARN, "
            "RCP_DISPOSAL_RECORDER_EVENT_SOURCE_MAPPING_UUID, and/or RCP_METADATA_TABLE_STREAM_ARN "
            "from deployed disposal-recorder outputs, confirm both ARNs' own regions match the "
            "stage's configured region, and confirm audit_metadata_table matches the stream ARN's "
            "own table segment, before running rcp retention disposal-recorder redrive.",
            "DISPOSAL_RECORDER_CONFIG_ERROR",
        )
