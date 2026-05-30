import json
from io import BytesIO

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from apps.backend.runner.api_runner import ApiRunner
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient


class S3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):  # noqa: N803, ARG002
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {"Body": BytesIO(json.dumps(self.objects[Key]).encode())}

    def head_object(self, Bucket, Key):  # noqa: N803, ARG002
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803, ARG002
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


class Secrets:
    def get_secret_value(self, SecretId):  # noqa: N803, ARG002
        return {"SecretString": "Bearer secret-token"}


class Response:
    status_code = 200

    def json(self):
        return {"ok": True, "b": 2, "a": 1}


class Session:
    def __init__(self):
        self.requests = []

    def request(self, **kwargs):
        self.requests.append(kwargs)
        return Response()


def test_orchestrator_executes_generated_and_data_pool_payloads_with_safe_metadata() -> None:
    objects = {
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "data-pools/client/users.json": {
            "records": [{"user": {"id": "u1"}, "email": "a@example.test"}]
        },
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": "gen",
                    "method": "POST",
                    "url": "https://service.test/gen",
                    "payload_strategy": "generated",
                    "payload_template": {
                        "email": "audit-{{uuid}}@example.test",
                        "run": "{{run_id}}",
                    },
                    "payload_safety": {"allow_generated_payloads": True},
                    "assertions": {"expected_status_codes": [200]},
                },
                {
                    "endpoint_id": "pool",
                    "method": "POST",
                    "url": "https://service.test/pool",
                    "payload_strategy": "data_pool",
                    "data_pool_name": "users",
                    "payload_template": {"id": "{{user.id}}", "run": "{{run_id}}"},
                    "payload_safety": {"allow_data_pool_reuse": True},
                    "assertions": {"expected_status_codes": [200]},
                },
            ]
        },
    }
    session = Session()
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", S3(objects)),
        metadata_storage=DynamoDBMetadataClient("table", DDB()),
        secrets_client=SecretsManagerClient(Secrets()),
        runner=ApiRunner(session),
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
    assert len(session.requests) == 2
    raw = objects["raw-results/client/audit/safe_run_123/results.json"]
    assert raw["raw_result_version"] == "v1"
    assert raw["results"][0]["payload_strategy"] == "generated"
    assert raw["results"][0]["payload_metadata"]["data_pool_name"] is None
    assert raw["results"][1]["payload_strategy"] == "data_pool"
    assert raw["results"][1]["payload_metadata"]["data_pool_name"] == "users"
    assert "a@example.test" not in json.dumps(raw)
    assert raw["results"][0]["response_fingerprint"] == raw["results"][1]["response_fingerprint"]


def test_orchestrator_executes_named_static_get_health_endpoints_without_duplicate_errors() -> None:
    endpoint_ids = [
        "health_fast",
        "health_slow",
        "health_flaky",
        "health_inconsistent_variant_a",
        "health_inconsistent_variant_b",
    ]
    objects = {
        "configs/client/client_config.json": {"client_id": "client"},
        "configs/client/audits/audit/audit_config.json": {"audit_id": "audit"},
        "configs/client/audits/audit/endpoints.json": {
            "endpoints": [
                {
                    "endpoint_id": endpoint_id,
                    "method": "GET",
                    "url": f"https://service.test/{endpoint_id}",
                    "payload_strategy": "static",
                    "assertions": {"expected_status_codes": [200]},
                }
                for endpoint_id in endpoint_ids
            ]
        },
    }
    session = Session()
    response = CoreEngineOrchestrator(
        s3_storage=S3StorageClient("bucket", S3(objects)),
        metadata_storage=DynamoDBMetadataClient("table", DDB()),
        secrets_client=SecretsManagerClient(Secrets()),
        runner=ApiRunner(session),
    ).run(
        {
            "client_id": "client",
            "audit_id": "audit",
            "scenario_type": "release_smoke",
            "triggered_by": "operator",
            "run_id": "safe_run_456",
        }
    )

    assert response["status"] == "COMPLETED"
    assert len(session.requests) == 5
    raw = objects["raw-results/client/audit/safe_run_456/results.json"]
    assert [result["endpoint_id"] for result in raw["results"]] == endpoint_ids
    assert {result["failure_type"] for result in raw["results"]} == {"PASS"}
    assert all(
        result["payload_metadata"]["duplicate_detected"] is False
        and result["payload_metadata"]["duplicate_check_scope"] == "not_applicable"
        for result in raw["results"]
    )
