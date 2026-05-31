from __future__ import annotations

from release_confidence_platform.operator_cli.discovery_service import DiscoveryListService
from release_confidence_platform.storage.audit_metadata_client import AuditMetadataRepository


def test_audit_list_unmarshals_dynamodb_client_items_and_filters_child_records():
    class FakeDdb:
        def query(self, **kwargs):
            return {
                "Items": [
                    {
                        "PK": {"S": "CLIENT#client1"},
                        "SK": {"S": "AUDIT#audit1"},
                        "lifecycle_state": {"S": "DRAFT"},
                        "created_at": {"S": "2026-05-23T00:00:00Z"},
                        "target_environment": {"S": "staging"},
                        "config_version": {"S": "v1"},
                    },
                    {
                        "PK": {"S": "CLIENT#client1"},
                        "SK": {"S": "AUDIT#audit1#RUN#run1"},
                        "status": {"S": "SUCCEEDED"},
                    },
                    {
                        "PK": {"S": "CLIENT#client1"},
                        "SK": {"S": "AUDIT#audit1#OCCURRENCE#001"},
                        "lifecycle_state": {"S": "RUNNING"},
                    },
                    {
                        "PK": {"S": "CLIENT#client1"},
                        "SK": {"S": "AUDIT#audit1#UNKNOWN#child1"},
                    },
                ]
            }

    repo = AuditMetadataRepository("table", FakeDdb())

    result = DiscoveryListService(repo).list_audits(client_id="client1", limit=10)

    assert result["items"] == [
        {
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "created_at": "2026-05-23T00:00:00Z",
            "target_environment": "staging",
            "config_version": "v1",
        }
    ]


def test_client_list_unmarshals_dynamodb_client_summary_fields():
    class FakeDdb:
        def scan(self, **kwargs):
            return {
                "Items": [
                    {
                        "PK": {"S": "CLIENT#client1"},
                        "SK": {"S": "AUDIT#audit1"},
                        "client_name": {"S": "Client One"},
                        "created_at": {"S": "2026-05-23T00:00:00Z"},
                    }
                ]
            }

    repo = AuditMetadataRepository("table", FakeDdb())

    result = DiscoveryListService(repo).list_clients(limit=10)

    assert result["items"] == [
        {
            "client_id": "client1",
            "client_name": "Client One",
            "created_at": "2026-05-23T00:00:00Z",
            "active_audit_count": 1,
        }
    ]
