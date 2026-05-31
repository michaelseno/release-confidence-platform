from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from release_confidence_platform.core.exceptions import StorageError, ValidationError
from release_confidence_platform.operator_cli.discovery_service import (
    ConfigDiscoveryService,
    DiscoveryListService,
)
from release_confidence_platform.operator_cli.main import build_parser
from release_confidence_platform.operator_cli.result import CommandResult, render
from release_confidence_platform.storage.audit_metadata_client import AuditMetadataRepository
from release_confidence_platform.storage.s3_client import S3StorageClient


class FakeRepository:
    def __init__(self):
        self.registry_page = None
        self.scan_page = {"items": []}
        self.audit_page = {"items": []}
        self.scans = []
        self.audit_queries = []

    def list_clients_from_registry(self, *, limit):
        return self.registry_page

    def scan_clients_bounded(self, *, limit, max_items):
        self.scans.append({"limit": limit, "max_items": max_items})
        return self.scan_page

    def list_audits_for_client(self, client_id, *, limit):
        self.audit_queries.append({"client_id": client_id, "limit": limit})
        return self.audit_page


class FakeBody:
    def __init__(self, value: str):
        self.value = value

    def read(self):
        return self.value.encode("utf-8")


class FakeS3Client:
    def __init__(self, objects: dict[str, str]):
        self.objects = objects
        self.head_calls = []
        self.get_calls = []
        self.list_calls = []

    def head_object(self, Bucket, Key):
        self.head_calls.append((Bucket, Key))
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {
            "ContentLength": len(self.objects[Key]),
            "LastModified": datetime(2026, 5, 23, tzinfo=UTC),
            "VersionId": "v1",
        }

    def get_object(self, Bucket, Key):
        self.get_calls.append((Bucket, Key))
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {"Body": FakeBody(self.objects[Key])}

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        return {"Contents": []}

    def put_object(self, **kwargs):  # pragma: no cover - must not be called by discovery
        raise AssertionError("mutating S3 call attempted")


def test_parser_exposes_discovery_commands_and_rejects_version_id():
    parser = build_parser()

    client = parser.parse_args(["client", "list", "--stage", "dev", "--limit", "25"])
    assert client.group == "client"
    assert client.client_command == "list"
    assert client.limit == 25

    audit = parser.parse_args(
        ["audit", "list", "--client-id", "client1", "--stage", "dev", "--output", "json"]
    )
    assert audit.audit_command == "list"
    assert audit.output == "json"

    config = parser.parse_args(
        [
            "config",
            "download",
            "--client-id",
            "client1",
            "--audit-id",
            "audit1",
            "--output-dir",
            "out",
            "--stage",
            "dev",
            "--overwrite",
        ]
    )
    assert config.config_command == "download"
    assert config.overwrite is True

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "config",
                "download",
                "--client-id",
                "c",
                "--audit-id",
                "a",
                "--output-dir",
                "out",
                "--stage",
                "dev",
                "--version-id",
                "v1",
            ]
        )
    assert exc.value.code == 2


@pytest.mark.parametrize("limit", [0, -1, 1001])
def test_parser_rejects_invalid_limits(limit):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["client", "list", "--stage", "dev", "--limit", str(limit)])
    assert exc.value.code == 2


def test_client_list_uses_bounded_scan_fallback_and_deduplicates():
    repo = FakeRepository()
    repo.scan_page = {
        "items": [
            {"client_id": "client1", "updated_at": "2026-05-23T00:00:00Z"},
            {"client_id": "client2", "active_audit_count": 1},
        ]
    }

    data = DiscoveryListService(repo).list_clients(limit=10)

    assert [item["client_id"] for item in data["items"]] == ["client1", "client2"]
    assert repo.scans == [{"limit": 10, "max_items": 1000}]
    assert data["fallback"] == "bounded_audit_metadata_scan"


def test_client_list_uses_registry_when_available():
    repo = FakeRepository()
    repo.registry_page = {"items": [{"client_id": "client1"}]}

    data = DiscoveryListService(repo).list_clients(limit=1)

    assert data["items"] == [{"client_id": "client1"}]
    assert repo.scans == []
    assert data["fallback"] == "client_registry"


def test_audit_list_queries_by_client_and_filters_child_records():
    repo = FakeRepository()
    repo.audit_page = {
        "items": [
            {"SK": "AUDIT#audit1", "lifecycle_state": "DRAFT", "created_at": "now"},
            {"SK": "AUDIT#audit1#RUN#run1", "status": "SUCCEEDED"},
            {"SK": "AUDIT#audit1#OCCURRENCE#1", "lifecycle_state": "RUNNING"},
            {"SK": "AUDIT#audit1#UNKNOWN#child1", "payload": "ignored"},
        ]
    }

    data = DiscoveryListService(repo).list_audits(client_id="client1", limit=5)

    assert repo.audit_queries == [{"client_id": "client1", "limit": 5}]
    assert data["items"] == [
        {"lifecycle_state": "DRAFT", "created_at": "now", "audit_id": "audit1"}
    ]


def test_service_rejects_invalid_limit_before_repository_call():
    repo = FakeRepository()
    with pytest.raises(ValidationError):
        DiscoveryListService(repo).list_clients(limit=1001)
    assert repo.scans == []


def test_audit_metadata_repository_query_and_scan_are_bounded():
    class FakeDdb:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(("query", kwargs))
            return {"Items": [{"SK": "AUDIT#audit1"}]}

        def scan(self, **kwargs):
            self.calls.append(("scan", kwargs))
            return {"Items": [{"PK": "CLIENT#client1", "SK": "AUDIT#audit1"}]}

    ddb = FakeDdb()
    repo = AuditMetadataRepository("table", ddb)

    repo.list_audits_for_client("client1", limit=7)
    repo.scan_clients_bounded(limit=3, max_items=3)

    assert ddb.calls[0][0] == "query"
    assert ddb.calls[0][1]["Limit"] == 7
    assert ddb.calls[1][0] == "scan"
    assert ddb.calls[1][1]["Limit"] == 3


def test_audit_metadata_repository_filters_canonical_rows_across_query_pages():
    class FakeDdb:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {
                    "Items": [
                        {"PK": "CLIENT#client1", "SK": "AUDIT#audit1#RUN#run1"},
                        {"PK": "CLIENT#client1", "SK": "AUDIT#audit1#OCCURRENCE#occ1"},
                    ],
                    "LastEvaluatedKey": {"PK": "CLIENT#client1", "SK": "AUDIT#audit1#OCCURRENCE#occ1"},
                }
            return {
                "Items": [
                    {
                        "PK": "CLIENT#client1",
                        "SK": "AUDIT#audit1",
                        "lifecycle_state": "DRAFT",
                    },
                    {"PK": "CLIENT#client1", "SK": "AUDIT#audit1#UNKNOWN#child1"},
                ]
            }

    ddb = FakeDdb()
    repo = AuditMetadataRepository("table", ddb)

    page = repo.list_audits_for_client("client1", limit=2)

    assert page == {
        "items": [{"PK": "CLIENT#client1", "SK": "AUDIT#audit1", "lifecycle_state": "DRAFT"}],
        "last_evaluated_key": None,
    }
    assert len(ddb.calls) == 2
    assert ddb.calls[1]["ExclusiveStartKey"] == {
        "PK": {"S": "CLIENT#client1"},
        "SK": {"S": "AUDIT#audit1#OCCURRENCE#occ1"},
    }


def _s3_storage(objects: dict[str, str]) -> tuple[S3StorageClient, FakeS3Client]:
    client = FakeS3Client(objects)
    return S3StorageClient("bucket", client), client


def test_config_list_heads_expected_artifacts_without_download():
    storage, fake = _s3_storage(
        {
            "configs/client1/client_config.json": "{}",
            "configs/client1/audits/audit1/audit_config.json": "{}",
            "configs/client1/audits/audit1/endpoints.json": "{}",
        }
    )

    data = ConfigDiscoveryService(storage, stage="dev").list_config_keys(
        client_id="client1", audit_id="audit1"
    )

    assert data["count"] == 3
    assert [entry["key"] for entry in data["config_keys"]] == [
        "configs/client1/client_config.json",
        "configs/client1/audits/audit1/audit_config.json",
        "configs/client1/audits/audit1/endpoints.json",
    ]
    assert fake.get_calls == []
    assert all("raw-results" not in key for _, key in fake.head_calls)


def test_config_download_fetches_exactly_three_and_creates_output_dir(tmp_path):
    storage, fake = _s3_storage(
        {
            "configs/client1/client_config.json": '{"client": true}',
            "configs/client1/audits/audit1/audit_config.json": '{"audit": true}',
            "configs/client1/audits/audit1/endpoints.json": '{"endpoints": []}',
            "raw-results/client1/audit1/run/results.json": "do not read",
        }
    )
    output_dir = tmp_path / ".local-configs" / "client1" / "audit1"

    data = ConfigDiscoveryService(storage, stage="dev").download_audit_config_set(
        client_id="client1", audit_id="audit1", output_dir=output_dir
    )

    assert sorted(path.name for path in output_dir.iterdir()) == [
        "audit_config.json",
        "client_config.json",
        "endpoints.json",
    ]
    assert [key for _, key in fake.get_calls] == [
        "configs/client1/client_config.json",
        "configs/client1/audits/audit1/audit_config.json",
        "configs/client1/audits/audit1/endpoints.json",
    ]
    assert data["warning"].startswith("downloaded configs may contain sensitive")


def test_config_download_prevents_and_allows_overwrite(tmp_path):
    storage, _fake = _s3_storage(
        {
            "configs/client1/client_config.json": "new-client",
            "configs/client1/audits/audit1/audit_config.json": "new-audit",
            "configs/client1/audits/audit1/endpoints.json": "new-endpoints",
        }
    )
    output_dir = tmp_path / "configs"
    output_dir.mkdir()
    existing = output_dir / "client_config.json"
    existing.write_text("old", encoding="utf-8")

    with pytest.raises(StorageError) as exc:
        ConfigDiscoveryService(storage, stage="dev").download_audit_config_set(
            client_id="client1", audit_id="audit1", output_dir=output_dir
        )
    assert exc.value.error_type == "LOCAL_FILE_EXISTS"
    assert existing.read_text(encoding="utf-8") == "old"

    ConfigDiscoveryService(storage, stage="dev").download_audit_config_set(
        client_id="client1", audit_id="audit1", output_dir=output_dir, overwrite=True
    )
    assert existing.read_text(encoding="utf-8") == "new-client"


def test_config_download_missing_artifact_fails_before_writes(tmp_path):
    storage, _fake = _s3_storage({"configs/client1/client_config.json": "{}"})

    with pytest.raises(StorageError) as exc:
        ConfigDiscoveryService(storage, stage="dev").download_audit_config_set(
            client_id="client1", audit_id="audit1", output_dir=tmp_path / "out"
        )

    assert exc.value.error_type == "CONFIG_ARTIFACT_NOT_FOUND"
    assert not (tmp_path / "out").exists()


def test_json_and_human_output_for_discovery_results():
    result = CommandResult(
        command="client list",
        stage="dev",
        status="success",
        summary="found 1 clients",
        data={"items": [{"client_id": "client1"}], "count": 1, "truncated": False},
    )

    payload = json.loads(render(result, output="json"))
    assert payload["items"] == [{"client_id": "client1"}]
    human = render(result, output="text")
    assert "SUCCESS: client list" in human
    assert "client1" in human
