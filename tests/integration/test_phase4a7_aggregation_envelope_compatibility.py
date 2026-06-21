"""Phase 4A.7 regression: aggregation must accept a runner-produced raw result envelope
whose run_id coincidentally contains a PHONE_PATTERN-matching digit run.

Incident: three independent 48-hour audits failed aggregation consistently with
failure_category=EVIDENCE_PRODUCING, reason_code=INVALID_RAW_RESULT_ENVELOPE,
aggregation_version=agg_v1. Root cause: apps/backend/orchestrator/service.py wraps the
S3 raw result envelope (and each per-result record) in sanitize() before persisting it.
sanitize()'s PHONE_PATTERN matched a coincidental 10-digit run inside the run_id UUID and
redacted it, while the DynamoDB run record (never sanitized) kept the original value.
AggregationOrchestrator._load_records' strict equality check between the two then raised
INVALID_RAW_RESULT_ENVELOPE and aborted the entire aggregation job.

This test exercises the REAL production code on both sides of the boundary:
  - apps.backend.orchestrator.service.CoreEngineOrchestrator (the runner/writer), wired
    exactly as apps/backend/handlers/orchestrator_handler.py wires it: a Table-RESOURCE
    style DynamoDB client (no encode/decode) for run metadata.
  - release_confidence_platform.aggregation.orchestrator.AggregationOrchestrator (the
    aggregator/reader), wired exactly as
    apps/backend/handlers/aggregation_handler.py wires it: a low-level boto3 DynamoDB
    CLIENT, decoded via release_confidence_platform.storage.dynamodb_codec.

Both fakes share one underlying typed-AttributeValue store (via boto3's real
TypeSerializer/TypeDeserializer) so this is a faithful simulation of the real DynamoDB
wire format, not a hand-rolled shortcut.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import ApiRunner
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient
from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.aggregation.repository import AggregationRepository
from release_confidence_platform.core.logging import StructuredLogger

# The canonical regression fixture UUID (shared with tests/unit/test_sanitizer_uuid_boundary.py
# and tests/unit/test_execution_identity_dynamodb.py): its digit run "2475004829" matches
# PHONE_PATTERN in sanitization/sanitizer.py.
PHONE_LIKE_RUN_ID = "48a87626-e2f9-4f81-82ff-2475004829ec"
CLIENT_ID = "client"
AUDIT_ID = "audit"

_SER = TypeSerializer()
_DESER = TypeDeserializer()


def _to_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _SER.serialize(v) for k, v in item.items()}


def _from_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _DESER.deserialize(v) for k, v in item.items()}


class _SharedDynamoStorage:
    """Always stores items in true DynamoDB typed-AttributeValue format."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put(self, typed_item: dict[str, Any]) -> None:
        self.items[(typed_item["PK"]["S"], typed_item["SK"]["S"])] = typed_item

    def get(self, pk: str, sk: str) -> dict[str, Any] | None:
        return self.items.get((pk, sk))

    def query_prefix(self, pk: str, sk_prefix: str) -> list[dict[str, Any]]:
        return [v for (p, s), v in self.items.items() if p == pk and s.startswith(sk_prefix)]


class _TableResource:
    """Mirrors boto3.resource('dynamodb').Table(...): native values, no TableName kwarg."""

    def __init__(self, storage: _SharedDynamoStorage) -> None:
        self.storage = storage

    def get_item(self, Key: dict[str, Any]) -> dict[str, Any]:
        typed_key = _to_typed(Key)
        item = self.storage.get(typed_key["PK"]["S"], typed_key["SK"]["S"])
        return {"Item": _from_typed(item)} if item else {}

    def put_item(
        self, Item: dict[str, Any], ConditionExpression: str | None = None, **_: Any
    ) -> dict[str, Any]:
        typed = _to_typed(Item)
        pk, sk = typed["PK"]["S"], typed["SK"]["S"]
        if (
            ConditionExpression
            and "attribute_not_exists" in ConditionExpression
            and self.storage.get(pk, sk)
        ):
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem"
            )
        self.storage.put(typed)
        return {}

    def update_item(
        self,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ExpressionAttributeNames: dict[str, str] | None = None,
        ConditionExpression: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        typed_key = _to_typed(Key)
        pk, sk = typed_key["PK"]["S"], typed_key["SK"]["S"]
        existing = self.storage.get(pk, sk) or {"PK": typed_key["PK"], "SK": typed_key["SK"]}
        names = ExpressionAttributeNames or {}
        typed_values = _to_typed(ExpressionAttributeValues)
        for placeholder, attr_name in names.items():
            val_placeholder = UpdateExpression.split(f"{placeholder} = ")[1].split(",")[0].strip()
            existing[attr_name] = typed_values[val_placeholder]
        self.storage.put(existing)
        return {}


class _LowLevelClient:
    """Mirrors boto3.client('dynamodb'): typed values in and out, accepts TableName=."""

    def __init__(self, storage: _SharedDynamoStorage) -> None:
        self.storage = storage

    def query(
        self,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        pk = ExpressionAttributeValues[":pk"]["S"]
        sk_prefix = ExpressionAttributeValues[":sk_prefix"]["S"]
        return {"Items": self.storage.query_prefix(pk, sk_prefix)}


class _FakeS3:
    def __init__(self, objects: dict[str, Any]) -> None:
        self.objects = objects

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": BytesIO(json.dumps(self.objects[Key]).encode())}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects[Key] = json.loads(Body.decode())


class _FakeSecrets:
    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        return {"SecretString": "Bearer secret-token"}


class _FakeResponse:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {"ok": True}


class _FakeSession:
    def request(self, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse()


class _FakeReadOnlyS3Storage:
    """Matches the read_json interface the aggregation orchestrator needs."""

    def __init__(self, objects: dict[str, Any]) -> None:
        self.objects = objects

    def read_json(self, key: str) -> dict[str, Any]:
        return self.objects[key]


def _run_orchestrator_with_fixed_run_id(
    objects: dict[str, Any], table_resource: _TableResource
) -> dict[str, Any]:
    return CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", _FakeS3(objects)),
        metadata_storage=DynamoDBMetadataClient("table", table_resource),
        secrets_client=SecretsManagerClient(_FakeSecrets()),
        runner=ApiRunner(_FakeSession()),
    ).run(
        {
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "scenario_type": "release_smoke",
            "triggered_by": "scheduler",
            "run_id": PHONE_LIKE_RUN_ID,
        }
    )


@pytest.fixture
def envelope_objects() -> dict[str, Any]:
    return {
        f"configs/{CLIENT_ID}/{CLIENT_ID}_config.json": {"client_id": CLIENT_ID},
        f"configs/{CLIENT_ID}/audits/{AUDIT_ID}/audit_config.json": {"audit_id": AUDIT_ID},
        f"configs/{CLIENT_ID}/audits/{AUDIT_ID}/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "GET",
                    "url": "https://service.test/health",
                    "payload_strategy": "static",
                    "headers": {},
                    "assertions": {"expected_status_codes": [200]},
                }
            ]
        },
    }


def test_runner_persists_phone_like_run_id_unredacted_in_envelope(envelope_objects):
    """WS-D (unit-level): the runner's own S3 envelope body must keep run_id byte-identical,
    proving the sanitizer fix reaches the actual envelope-construction call site."""
    storage = _SharedDynamoStorage()
    response = _run_orchestrator_with_fixed_run_id(envelope_objects, _TableResource(storage))

    assert response["status"] == "COMPLETED"
    key = f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{PHONE_LIKE_RUN_ID}/results.json"
    envelope = envelope_objects[key]
    assert envelope["run_id"] == PHONE_LIKE_RUN_ID, (
        f"S3 envelope run_id was mutated by sanitize(): {envelope['run_id']!r}"
    )
    assert "[REDACTED]" not in envelope["run_id"]
    assert envelope["results"][0]["run_id"] == PHONE_LIKE_RUN_ID


def test_aggregation_accepts_runner_produced_envelope_with_phone_like_run_id(envelope_objects):
    """End-to-end: write via the real runner (packages/Table-resource pairing), read via the
    real aggregation repository (release_confidence_platform/low-level-client pairing).
    Must not raise INVALID_RAW_RESULT_ENVELOPE."""
    storage = _SharedDynamoStorage()
    write_response = _run_orchestrator_with_fixed_run_id(envelope_objects, _TableResource(storage))
    assert write_response["status"] == "COMPLETED"

    agg_repo = AggregationRepository("table", _LowLevelClient(storage))
    runs = agg_repo.list_completed_runs(CLIENT_ID, AUDIT_ID)
    assert len(runs) == 1
    assert runs[0]["run_id"] == PHONE_LIKE_RUN_ID

    agg_orchestrator = AggregationOrchestrator(
        repository=agg_repo,
        s3_storage=_FakeReadOnlyS3Storage(envelope_objects),
        logger=StructuredLogger(),
    )

    records = agg_orchestrator._load_records(runs, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(records) == 1
    assert records[0].run_id == PHONE_LIKE_RUN_ID
