"""Evidence Governance Workstream A1.LH3 -- Lambda dependency-construction
wiring tests for the two production call sites that independently construct
DynamoDBMetadataClient/S3StorageClient:

  * apps/backend/handlers/orchestrator_handler.py (Phase 1 core engine,
    manual/baseline/burst invocations).
  * apps/backend/handlers/scheduled_execution_handler.py (the
    SCHEDULE_TYPE_REPEATED path the companion ADR's own motivating example
    cites -- repeated, separately-scheduled invocations across an audit's
    execution window; discovered during this subphase's implementation as a
    second, independent production writer requiring the identical fix).

Both must:
  * construct exactly one HoldRepository per invocation and inject the SAME
    instance into both DynamoDBMetadataClient and S3StorageClient (Technical
    Design Section 19.10 item (c+d): "construct one HoldRepository, inject
    it into both").
  * supply `table.meta.client` (the low-level client accessor) as
    HoldRepository's dynamodb_client and as DynamoDBMetadataClient's
    transact_dynamodb_client -- never the Table resource itself, which has
    no transact_write_items/get_item(TableName=...) surface.
  * retain the Table RESOURCE for DynamoDBMetadataClient's own
    dynamodb_client argument (its pre-existing get_item/put_item/
    update_item operations, unchanged).
  * introduce no new environment variable or custody-duration value.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.backend.handlers import orchestrator_handler, scheduled_execution_handler
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository


class _RecordingLowLevelClient:
    """Stands in for table.meta.client -- identity matters (object identity
    checks below), behavior does not (never actually invoked; the FakeCore/
    FakeOrchestrator/FakeScheduledHandler doubles below never call
    metadata_storage/s3_storage)."""


class _RecordingTable:
    def __init__(self) -> None:
        self.meta = type("Meta", (), {"client": _RecordingLowLevelClient()})()


class _FakeBoto3:
    def __init__(self) -> None:
        self.table = _RecordingTable()
        self.client_calls: list[str] = []
        self.resource_calls: list[str] = []
        self.table_name_requested: str | None = None

    def client(self, name):
        self.client_calls.append(name)
        return object()

    def resource(self, name):
        self.resource_calls.append(name)
        fake_boto3 = self

        class _Resource:
            def Table(self, table_name):
                fake_boto3.table_name_requested = table_name
                return fake_boto3.table

        return _Resource()


class _CapturingCoreEngineOrchestrator:
    """Captures the s3_storage/metadata_storage kwargs orchestrator_handler
    constructs it with, without actually running anything."""

    last_kwargs: dict[str, Any] | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs

    def run(self, event):  # noqa: ARG002
        return {"status": "COMPLETED"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RAW_RESULTS_BUCKET", "bucket")
    monkeypatch.setenv("METADATA_TABLE", "table")


def test_orchestrator_handler_constructs_one_hold_repository_shared_by_both_clients(monkeypatch):
    fake_boto3 = _FakeBoto3()
    monkeypatch.setattr(orchestrator_handler, "boto3", fake_boto3)
    monkeypatch.setattr(
        orchestrator_handler, "CoreEngineOrchestrator", _CapturingCoreEngineOrchestrator
    )

    orchestrator_handler.handler({"client_id": "c", "audit_id": "a"}, None)

    kwargs = _CapturingCoreEngineOrchestrator.last_kwargs
    metadata_storage = kwargs["metadata_storage"]
    s3_storage = kwargs["s3_storage"]

    # One shared HoldRepository instance reaches both governed write paths.
    assert metadata_storage._hold_repository is s3_storage._hold_repository
    assert isinstance(metadata_storage._hold_repository, HoldRepository)

    # table.meta.client (the low-level accessor), not the Table resource
    # itself, backs the HoldRepository / transact_dynamodb_client.
    low_level_client = fake_boto3.table.meta.client
    assert metadata_storage._hold_repository.dynamodb_client is low_level_client
    assert metadata_storage._hold_coordination_runner._dynamodb_client is low_level_client

    # The Table RESOURCE remains DynamoDBMetadataClient's own dynamodb_client
    # for its pre-existing get_item/put_item/update_item operations.
    assert metadata_storage.dynamodb_client is fake_boto3.table

    # No new environment variable or custody-duration value introduced --
    # only the pre-existing RAW_RESULTS_BUCKET/METADATA_TABLE are consulted.
    assert fake_boto3.table_name_requested == "table"
    assert metadata_storage._hold_repository.table_name == "table"


def test_scheduled_execution_handler_constructs_one_hold_repository_shared_by_both_clients(
    monkeypatch,
):
    fake_boto3 = _FakeBoto3()

    class _CapturingScheduledOrchestrator(_CapturingCoreEngineOrchestrator):
        pass

    class _NoOpAuditMetadataRepository:
        def __init__(self, *args, **kwargs):
            pass

    class _NoOpScheduledExecutionHandler:
        def __init__(self, *, repository, orchestrator):
            self.repository = repository
            self.orchestrator = orchestrator

        def handle(self, event):
            return {"status": "COMPLETED"}

    monkeypatch.setattr(scheduled_execution_handler, "boto3", fake_boto3)
    monkeypatch.setattr(
        scheduled_execution_handler, "CoreEngineOrchestrator", _CapturingScheduledOrchestrator
    )
    monkeypatch.setattr(
        scheduled_execution_handler, "AuditMetadataRepository", _NoOpAuditMetadataRepository
    )
    monkeypatch.setattr(
        scheduled_execution_handler, "ScheduledExecutionHandler", _NoOpScheduledExecutionHandler
    )

    scheduled_execution_handler.handler({"client_id": "c", "audit_id": "a"}, None)

    kwargs = _CapturingScheduledOrchestrator.last_kwargs
    metadata_storage = kwargs["metadata_storage"]
    s3_storage = kwargs["s3_storage"]

    assert metadata_storage._hold_repository is s3_storage._hold_repository
    assert isinstance(metadata_storage._hold_repository, HoldRepository)
    assert metadata_storage._hold_repository.dynamodb_client is fake_boto3.table.meta.client
    assert metadata_storage.dynamodb_client is fake_boto3.table
