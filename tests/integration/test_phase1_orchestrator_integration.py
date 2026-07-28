import json
from io import BytesIO

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


class S3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):  # noqa: N803, ARG002
        return {"Body": BytesIO(json.dumps(self.objects[Key]).encode())}

    def head_object(self, Bucket, Key):  # noqa: N803, ARG002
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, ContentType, Tagging=None):  # noqa: N803, ARG002
        self.objects[Key] = json.loads(Body.decode())


class DDB:
    def __init__(self):
        self.items = {}

    def get_item(self, TableName, Key):  # noqa: N803, ARG002
        key = tuple(Key.values())
        return {"Item": self.items[key]} if key in self.items else {}

    def put_item(self, TableName, Item, ConditionExpression):  # noqa: N803, ARG002
        self.items[tuple((Item["PK"], Item["SK"]))] = Item

    def update_item(self, TableName, Key, ExpressionAttributeValues, **kwargs):  # noqa: N803, ARG002
        names = kwargs["ExpressionAttributeNames"]
        for index, name in enumerate(names.values()):
            self.items[tuple(Key.values())][name] = ExpressionAttributeValues[f":v{index}"]

    def transact_write_items(self, TransactItems):  # noqa: N803
        # Evidence Governance Workstream A1.LH3: put_started_once now writes
        # via TransactWriteItems. No LegalHold record is ever stored here
        # (paired with _NoLegalHoldRepository below), so the ConditionCheck
        # item always trivially passes; only the governed Put item's own
        # condition can fail, preserving pre-existing behavior.
        from botocore.exceptions import ClientError

        from release_confidence_platform.storage.dynamodb_codec import decode_item

        reasons = []
        any_failed = False
        for transact_item in TransactItems:
            if "Put" in transact_item:
                item = decode_item(transact_item["Put"]["Item"])
                key = (item["PK"], item["SK"])
                if key in self.items:
                    reasons.append({"Code": "ConditionalCheckFailed"})
                    any_failed = True
                else:
                    reasons.append({"Code": "None"})
            else:
                reasons.append({"Code": "None"})
        if any_failed:
            raise ClientError(
                {
                    "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                    "CancellationReasons": reasons,
                },
                "TransactWriteItems",
            )
        for transact_item in TransactItems:
            if "Put" in transact_item:
                item = decode_item(transact_item["Put"]["Item"])
                self.items[(item["PK"], item["SK"])] = item
        return {}


class _NoLegalHoldRepository:
    def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):  # noqa: ARG002
        return None

    def legal_hold_key(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#LEGALHOLD"}


_NO_HOLD = _NoLegalHoldRepository()


class Secrets:
    def get_secret_value(self, SecretId):  # noqa: N803, ARG002
        return {"SecretString": "Bearer secret-token"}


class Response:
    status_code = 200

    def json(self):
        return {"ok": True}


class Session:
    def request(self, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
        return Response()


def test_orchestrator_completes_with_mocked_aws_and_http() -> None:
    objects = {
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "ep1",
                    "method": "GET",
                    "url": "https://service.test/health?email=user@example.com",
                    "payload_strategy": "static",
                    "headers": {"Authorization": {"secret_ref": "auth-secret"}},
                    "assertions": {
                        "expected_status_codes": [200],
                        "expect_json": True,
                        "required_response_fields": ["ok"],
                    },
                }
            ]
        },
    }
    from apps.backend.runner.api_runner import ApiRunner

    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", S3(objects), _NO_HOLD),
        metadata_storage=DynamoDBMetadataClient("table", DDB(), _NO_HOLD),
        secrets_client=SecretsManagerClient(Secrets()),
        runner=ApiRunner(Session()),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": "safe_run_123",
        }
    )
    assert response["status"] == "COMPLETED"
    raw = objects["raw-results/client/audit/safe_run_123/results.json"]
    assert raw["raw_result_version"] == "v1"
    assert raw["results"][0]["failure_type"] == "PASS"
    assert "user%40example.com" not in raw["results"][0]["url"]
