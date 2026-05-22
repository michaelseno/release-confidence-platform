from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.audit_lifecycle.cancellation import AuditCancellationService
from packages.audit_scheduling.service import AuditSchedulingService
from packages.config.audit_validation_service import AuditConfigValidationService
from packages.config.stage_config import StageConfig, StageConfigLoader
from packages.core.audit_creation_service import AuditCreationService
from packages.core.exceptions import EngineError
from packages.core.manual_run_service import ManualRunInvocationService
from packages.operator_cli.main import build_parser
from release_confidence_platform.operator_cli.main import build_parser as packaged_build_parser


class FakeS3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.writes = []

    def object_exists(self, key):
        return key in self.objects

    def write_json(self, key, payload, *, overwrite=False):
        if not overwrite and key in self.objects:
            raise AssertionError("unexpected overwrite")
        self.writes.append((key, payload, overwrite))
        self.objects[key] = payload

    def read_json(self, key):
        return self.objects[key]


class FakeRepo:
    def __init__(self, item=None):
        self.item = item
        self.puts = []
        self.force_updates = []
        self.transitions = []
        self.schedules = []
        self.cleanup_errors = []

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def get_audit_metadata(self, client_id, audit_id):
        if self.item is None:
            from packages.core.exceptions import StorageError

            raise StorageError("not found", "AUDIT_NOT_FOUND")
        return self.item

    def put_audit_metadata_once(self, item):
        self.puts.append(item)
        self.item = item

    def update_for_force_recreate(self, item):
        self.force_updates.append(item)
        self.item = {
            **(self.item or {}),
            **item,
            "lifecycle_history": [item["force_history_entry"]],
        }

    def append_lifecycle_transition(self, **kwargs):
        self.transitions.append(kwargs)
        self.item["lifecycle_state"] = kwargs["next_state"]

    def set_schedules(self, client_id, audit_id, schedules):
        self.schedules = schedules
        self.item["schedules"] = schedules

    def record_cleanup_errors(self, client_id, audit_id, cleanup_errors):
        self.cleanup_errors = cleanup_errors
        self.item["cleanup_errors"] = cleanup_errors


class FakeScheduler:
    def __init__(self, fail_delete=False):
        self.created = []
        self.deleted = []
        self.disabled = []
        self.fail_delete = fail_delete

    def create_schedule(self, definition):
        self.created.append(definition.name)
        return {**definition.metadata, "schedule_name": definition.name, "status": "created"}

    def delete_schedule(self, name, group=None):
        self.deleted.append((name, group))
        if self.fail_delete:
            raise RuntimeError("token=secret")

    def disable_schedule(self, name, group=None):
        self.disabled.append((name, group))
        if self.fail_delete:
            raise RuntimeError("Bearer abc")


class FakeLambda:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {"status_code": 202}


@pytest.fixture
def stage_config():
    return StageConfig(
        stage="dev",
        region="us-east-1",
        aws_profile="test",
        config_bucket="bucket",
        audit_metadata_table="table",
        orchestrator_function_name="orchestrator",
        scheduler_group_name="group",
        schedule_name_prefix="rcp-dev",
    )


def configs():
    client = {"client_id": "client1", "safety": {"allowed_methods": ["GET"]}}
    audit = {
        "client_id": "client1",
        "audit_id": "audit1",
        "audit_window": {"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-01-02T00:00:00Z"},
        "execution_environment": {
            "target_environment": "staging",
            "allow_production_execution": False,
        },
        "baseline_schedule": {"enabled": True, "interval_minutes": 15},
        "finalization_schedule": {"enabled": True},
    }
    endpoints = {
        "client_id": "client1",
        "audit_id": "audit1",
        "endpoints": [{"endpoint_id": "e1", "method": "GET", "url": "https://example.com/health"}],
    }
    return client, audit, endpoints


def write_configs(tmp_path: Path):
    paths = []
    for name, data in zip(("client.json", "audit.json", "endpoints.json"), configs(), strict=True):
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(path)
    return paths


def test_parser_accepts_commands_and_requires_stage():
    parser = build_parser()
    args = parser.parse_args(
        [
            "audit",
            "run",
            "--client-id",
            "c",
            "--audit-id",
            "a",
            "--scenario-type",
            "baseline_health",
            "--stage",
            "dev",
        ]
    )
    assert args.audit_command == "run"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["audit", "cancel", "--client-id", "c", "--audit-id", "a"])
    assert exc.value.code == 2


def test_packaged_entrypoint_delegates_to_operator_cli_parser():
    parser = packaged_build_parser()

    args = parser.parse_args(
        [
            "audit",
            "run",
            "--client-id",
            "c",
            "--audit-id",
            "a",
            "--scenario-type",
            "baseline_health",
            "--stage",
            "dev",
        ]
    )

    assert args.audit_command == "run"


def test_stage_config_env_override_precedence(tmp_path, monkeypatch):
    stage_dir = tmp_path / "config" / "stages"
    stage_dir.mkdir(parents=True)
    (stage_dir / "dev.json").write_text(
        json.dumps(StageConfig("dev", "file", "p", "b", "t", "f", "g", "x").to_dict())
    )
    monkeypatch.setenv("RCP_AWS_REGION", "env-region")
    loaded = StageConfigLoader(root=tmp_path).load("dev")
    assert loaded.region == "env-region"
    monkeypatch.setenv("RCP_AWS_REGION", "")
    with pytest.raises(EngineError):
        StageConfigLoader(root=tmp_path).load("dev")
    monkeypatch.setenv("RCP_AWS_REGION", "   ")
    with pytest.raises(EngineError):
        StageConfigLoader(root=tmp_path).load("dev")


def test_validate_rejects_over_48h(tmp_path):
    client, audit, endpoints = configs()
    audit["audit_window"]["end_at"] = "2026-01-04T00:00:01Z"
    with pytest.raises(EngineError):
        AuditConfigValidationService().validate_configs(
            client_config=client, audit_config=audit, endpoints_config=endpoints, stage="dev"
        )


def test_create_dry_run_reports_actions_no_mutation(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    s3 = FakeS3()
    repo = FakeRepo()
    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert len(result["planned_actions"]) == 4
    assert s3.writes == []
    assert repo.puts == []


def test_create_force_allows_draft_and_updates_only_config_keys(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": "DRAFT"})
    s3 = FakeS3({"raw-results/client1/audit1/run.json": {"keep": True}})
    result = AuditCreationService(
        stage_config=stage_config, s3_storage=s3, repository=repo
    ).create_from_files(
        client_config_path=str(c),
        audit_config_path=str(a),
        endpoints_config_path=str(e),
        force=True,
    )
    assert result["force"] is True
    assert len(s3.writes) == 3
    assert all("raw-results" not in key for key, _, _ in s3.writes)
    assert repo.force_updates[0]["force_history_entry"]["reason"] == "force_recreate"


def test_create_force_rejects_scheduled_before_mutation(tmp_path, stage_config):
    c, a, e = write_configs(tmp_path)
    repo = FakeRepo({"client_id": "client1", "audit_id": "audit1", "lifecycle_state": "SCHEDULED"})
    s3 = FakeS3()
    with pytest.raises(EngineError):
        AuditCreationService(
            stage_config=stage_config, s3_storage=s3, repository=repo
        ).create_from_files(
            client_config_path=str(c),
            audit_config_path=str(a),
            endpoints_config_path=str(e),
            force=True,
        )
    assert s3.writes == []
    assert repo.force_updates == []


def test_schedule_dry_run_skips_missing_disabled_blocks(stage_config):
    _, audit, _ = configs()
    audit["burst_schedule"] = {
        "enabled": False,
        "windows": [
            {"start_time": "01:00", "duration_minutes": 1, "request_count": 1, "concurrency": 1}
        ],
    }
    item = {
        "client_id": "client1",
        "audit_id": "audit1",
        "lifecycle_state": "DRAFT",
        "config_s3_keys": {"audit_config": "audit.json"},
    }
    repo = FakeRepo(item)
    scheduler = FakeScheduler()
    result = AuditSchedulingService(
        repository=repo, scheduler_client=scheduler, stage="dev", schedule_name_prefix="rcp-dev"
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": audit}),
        dry_run=True,
    )
    names = [s["schedule_type"] for s in result["planned_schedules"]]
    assert names == ["baseline", "finalization"]
    assert scheduler.created == []


def test_schedule_dry_run_does_not_infer_missing_finalization(stage_config):
    _, audit, _ = configs()
    audit.pop("finalization_schedule")
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    result = AuditSchedulingService(
        repository=repo,
        scheduler_client=FakeScheduler(),
        stage="dev",
        schedule_name_prefix="rcp-dev",
    ).schedule_from_persisted_audit(
        client_id="client1",
        audit_id="audit1",
        s3_storage=FakeS3({"audit.json": audit}),
        dry_run=True,
    )

    assert [s["schedule_type"] for s in result["planned_schedules"]] == ["baseline"]


def test_schedule_prod_requires_allow_production(stage_config):
    _, audit, _ = configs()
    audit["execution_environment"] = {
        "target_environment": "production",
        "allow_production_execution": True,
    }
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        }
    )
    with pytest.raises(EngineError):
        AuditSchedulingService(
            repository=repo,
            scheduler_client=FakeScheduler(),
            stage="prod",
            schedule_name_prefix="rcp-prod",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=FakeS3({"audit.json": audit}),
            allow_production=False,
        )


def test_run_dry_run_and_invalid_run_id(stage_config):
    lamb = FakeLambda()
    result = ManualRunInvocationService(stage_config=stage_config, lambda_client=lamb).run(
        client_id="client1", audit_id="audit1", scenario_type="baseline_health", dry_run=True
    )
    assert result["payload"]["triggered_by"] == "manual"
    assert "run_id" not in result["payload"]
    assert lamb.invocations == []
    with pytest.raises(EngineError):
        ManualRunInvocationService(stage_config=stage_config, lambda_client=lamb).run(
            client_id="client1", audit_id="audit1", scenario_type="baseline_health", run_id="../bad"
        )


def test_cancel_partial_cleanup_exit_behavior_shape():
    repo = FakeRepo(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "SCHEDULED",
            "schedules": [
                {"schedule_name": "s1", "schedule_group": "g", "schedule_type": "baseline"}
            ],
        }
    )
    result = AuditCancellationService(
        repository=repo, scheduler_client=FakeScheduler(fail_delete=True)
    ).cancel_for_operator(client_id="client1", audit_id="audit1", reason="operator requested")
    assert result["status"] == "cancelled_with_cleanup_warnings"
    assert repo.item["lifecycle_state"] == "CANCELLED"
    assert repo.cleanup_errors[0]["error_code"] == "SCHEDULE_CLEANUP_FAILED"
