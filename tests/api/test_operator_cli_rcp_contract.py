from __future__ import annotations

import json

import pytest

from release_confidence_platform.audit_scheduling.service import AuditSchedulingService
from release_confidence_platform.config.stage_config import StageConfig, StageConfigLoader
from release_confidence_platform.core.exceptions import EngineError


class FakeS3:
    def __init__(self, objects: dict[str, dict]):
        self.objects = objects

    def read_json(self, key: str) -> dict:
        return self.objects[key]


class FakeRepo:
    def __init__(self, item: dict):
        self.item = item
        self.schedules: list[dict] = []

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict:
        return self.item

    def set_schedules(self, client_id: str, audit_id: str, schedules: list[dict]) -> None:
        self.schedules = schedules

    def append_lifecycle_transition(self, **kwargs) -> None:
        self.item["lifecycle_state"] = kwargs["next_state"]


class FakeScheduler:
    def __init__(self):
        self.created: list[str] = []

    def create_schedule(self, definition):
        self.created.append(definition.name)
        return {**definition.metadata, "schedule_name": definition.name, "status": "created"}


def _stage_file_payload() -> dict[str, str]:
    return StageConfig(
        stage="dev",
        region="us-east-1",
        aws_profile="profile",
        config_bucket="bucket",
        audit_metadata_table="table",
        orchestrator_function_name="fn",
        scheduler_group_name="group",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="arn:aws:lambda:us-east-1:123:function:execution",
        scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:123:function:finalization",
        scheduler_role_arn="arn:aws:iam::123:role/scheduler",
    ).to_dict()


def _audit_config_without_finalization() -> dict:
    return {
        "client_id": "client1",
        "audit_id": "audit1",
        "audit_window": {
            "start_at": "2026-01-01T00:00:00Z",
            "end_at": "2026-01-01T01:00:00Z",
        },
        "execution_environment": {
            "target_environment": "staging",
            "allow_production_execution": False,
        },
        "baseline_schedule": {"enabled": True, "interval_minutes": 15},
    }


def test_stage_config_whitespace_env_override_is_rejected(tmp_path, monkeypatch):
    stage_dir = tmp_path / "config" / "stages"
    stage_dir.mkdir(parents=True)
    (stage_dir / "dev.json").write_text(json.dumps(_stage_file_payload()), encoding="utf-8")
    monkeypatch.setenv("RCP_CONFIG_BUCKET", "   ")

    with pytest.raises(EngineError):
        StageConfigLoader(root=tmp_path).load("dev")


def test_schedule_missing_finalization_block_does_not_infer_finalization_schedule():
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    scheduler = FakeScheduler()

    result = AuditSchedulingService(
        repository=repo,
        scheduler_client=scheduler,
        stage="staging",
        schedule_name_prefix="rcp-staging",
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": _audit_config_without_finalization()}),
        dry_run=True,
    )

    planned_types = [schedule["schedule_type"] for schedule in result["planned_schedules"]]
    assert planned_types == ["baseline"]
