"""Stage resource configuration loading for operator tooling."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from packages.core.exceptions import ConfigError

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

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def validate_orchestrator_function_name(self) -> None:
        validate_orchestrator_function_name(self.orchestrator_function_name, stage=self.stage)

    def validate_scheduler_config(self) -> None:
        validate_scheduler_config(self)


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
