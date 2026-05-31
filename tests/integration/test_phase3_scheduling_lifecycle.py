from datetime import UTC, datetime, timedelta

import pytest

from packages.audit_scheduling.service import AuditSchedulingService
from packages.core.exceptions import ValidationError


class Repo:
    def __init__(self):
        self.items = {}

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def put_audit_metadata_once(self, item):
        self.items[(item["PK"], item["SK"])] = item

    def get_audit_metadata(self, client_id, audit_id):
        return self.items[(f"CLIENT#{client_id}", f"AUDIT#{audit_id}")]

    def set_schedules(self, client_id, audit_id, schedules):
        self.get_audit_metadata(client_id, audit_id)["schedules"] = schedules

    def record_cleanup_errors(self, client_id, audit_id, errors):
        self.get_audit_metadata(client_id, audit_id)["cleanup_errors"] = errors

    def append_lifecycle_transition(self, **kwargs):
        item = self.get_audit_metadata(kwargs["client_id"], kwargs["audit_id"])
        item["lifecycle_state"] = kwargs["next_state"]
        item.setdefault("lifecycle_history", []).append(kwargs["history_entry"])


class Scheduler:
    def __init__(self, fail_after=None):
        self.created = []
        self.deleted = []
        self.fail_after = fail_after

    def create_schedule(self, definition):
        if self.fail_after is not None and len(self.created) >= self.fail_after:
            raise RuntimeError("provider failure")
        metadata = {**definition.metadata, "status": "created"}
        self.created.append(metadata)
        return metadata

    def delete_schedule(self, schedule_name, group_name=None):  # noqa: ARG002
        self.deleted.append(schedule_name)

    def disable_schedule(self, schedule_name, group_name=None):  # noqa: ARG002
        raise AssertionError("disable should not be needed")


class S3ShouldNotRead:
    def read_json(self, key):  # noqa: ARG002
        raise AssertionError("non-DRAFT lifecycle validation should block before S3 reads")


def valid_config():
    token_expiry = (datetime.now(UTC) + timedelta(hours=70)).isoformat().replace("+00:00", "Z")
    return {
        "client_id": "client123",
        "audit_id": "audit456",
        "audit_window": {"start_time": "2026-05-19T00:00:00Z", "duration_hours": 48},
        "execution_environment": {
            "target_environment": "staging",
            "allow_production_execution": False,
        },
        "baseline": {"enabled": True},
        "burst_schedule": {
            "enabled": True,
            "windows": [
                {
                    "start_time": "09:00",
                    "duration_minutes": 30,
                    "request_count": 100,
                    "concurrency": 5,
                }
            ],
        },
        "repeated": [
            {"enabled": True, "schedule_time": "2026-05-19T01:00:00Z", "iteration_count": 2}
        ],
        "temporary_token": {"token_ref": "arn:ref", "expires_at": token_expiry, "scope": "audit"},
    }


def test_successful_full_scheduling_path():
    repo = Repo()
    scheduler = Scheduler()
    result = AuditSchedulingService(
        repository=repo, scheduler_client=scheduler, stage="dev"
    ).schedule_audit(valid_config())
    item = repo.get_audit_metadata("client123", "audit456")
    assert result["lifecycle_state"] == "SCHEDULED"
    assert len(scheduler.created) == 195
    assert item["PK"] == "CLIENT#client123"
    assert item["SK"] == "AUDIT#audit456"
    assert item["lifecycle_history"][-1]["to_state"] == "SCHEDULED"
    assert all("run_id" not in schedule for schedule in item["schedules"])
    baseline_schedules = [
        schedule for schedule in item["schedules"] if schedule["schedule_type"] == "baseline"
    ]
    assert len(baseline_schedules) == 192
    assert all(
        schedule["schedule_expression_summary"].startswith("at(")
        for schedule in baseline_schedules
    )


def test_scheduling_validation_blocks_before_aws_calls():
    repo = Repo()
    scheduler = Scheduler()
    config = valid_config()
    config["execution_environment"] = {
        "target_environment": "production",
        "allow_production_execution": False,
    }
    with pytest.raises(ValidationError):
        AuditSchedulingService(
            repository=repo, scheduler_client=scheduler, stage="dev"
        ).schedule_audit(config)
    assert scheduler.created == []


def test_schedule_from_persisted_non_draft_reports_lifecycle_context_before_side_effects():
    repo = Repo()
    scheduler = Scheduler()
    repo.items[("CLIENT#client123", "AUDIT#audit456")] = {
        "PK": "CLIENT#client123",
        "SK": "AUDIT#audit456",
        "client_id": "client123",
        "audit_id": "audit456",
        "lifecycle_state": "SCHEDULED",
        "config_s3_keys": {"audit_config": "audit.json"},
    }

    with pytest.raises(ValidationError) as exc:
        AuditSchedulingService(
            repository=repo, scheduler_client=scheduler, stage="dev"
        ).schedule_from_persisted_audit(
            client_id="client123",
            audit_id="audit456",
            s3_storage=S3ShouldNotRead(),
            dry_run=True,
        )

    assert exc.value.error_type == "INVALID_LIFECYCLE_STATE"
    assert "current_state=SCHEDULED" in exc.value.message
    assert "required_state=DRAFT" in exc.value.message
    assert scheduler.created == []


def test_partial_schedule_creation_rolls_back_and_fails_audit():
    repo = Repo()
    scheduler = Scheduler(fail_after=1)
    with pytest.raises(RuntimeError):
        AuditSchedulingService(
            repository=repo, scheduler_client=scheduler, stage="dev"
        ).schedule_audit(valid_config())
    item = repo.get_audit_metadata("client123", "audit456")
    assert item["lifecycle_state"] == "FAILED"
    assert scheduler.deleted == [scheduler.created[0]["schedule_name"]]
    assert "SCHEDULED_WITH_ERRORS" not in str(item)
