import pytest

from packages.storage.audit_metadata_client import (
    AuditMetadataRepository,
    DuplicateOccurrenceClaimError,
)


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803, ARG002
        key = (Item["PK"], Item["SK"])
        if key in self.items:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = Item
        return {}


def test_key_shapes_and_duplicate_occurrence_claim():
    repo = AuditMetadataRepository("table", FakeTable())
    assert repo.audit_keys("client123", "audit456") == {
        "PK": "CLIENT#client123",
        "SK": "AUDIT#audit456",
    }
    claim_key = repo.occurrence_keys("client123", "audit456", "occurrence789")
    assert claim_key == {
        "PK": "CLIENT#client123",
        "SK": "AUDIT#audit456#OCCURRENCE#occurrence789",
    }
    repo.claim_occurrence({**claim_key, "client_id": "client123", "audit_id": "audit456"})
    with pytest.raises(DuplicateOccurrenceClaimError):
        repo.claim_occurrence({**claim_key, "client_id": "client123", "audit_id": "audit456"})
