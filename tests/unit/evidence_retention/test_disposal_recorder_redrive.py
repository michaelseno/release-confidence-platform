"""Tests for `evidence_retention.disposal_recorder_redrive` (A1.4a Increment 2).

Covers `docs/qa/a1_4a_disposal_recorder_test_plan.md` Area (g) TC-G2, TC-G3,
TC-G4, TC-G9 (Section 3.7) and Area (i) TC-I4 (structural half; the
end-to-end construction-path proof lives in test_operator_cli_retention.py)
and TC-I6(b) (Section 3.9).

TC-G9's six numbered runtime checks are tested one negative fixture per
check, in the Technical Design Section 22.9.3 order; the "check 4 passes,
check 6 fails" edge case (§4 Edge Cases) is included explicitly, proving the
two checks are independent and neither subsumes the other.
"""

from __future__ import annotations

import ast
import inspect
import json
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.evidence_retention import disposal_recorder
from release_confidence_platform.evidence_retention import (
    disposal_recorder_redrive as redrive_module,
)
from release_confidence_platform.evidence_retention.disposal_recorder_redrive import (
    REDRIVE_OUTCOME_PROCESSED,
    REDRIVE_OUTCOME_REJECTED,
    redrive_disposal_recorder,
)
from release_confidence_platform.evidence_retention.disposal_repository import (
    ConditionalWriteError,
)
from release_confidence_platform.storage.dynamodb_codec import encode_item

_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_STREAM_ARN = (
    "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/2024-01-01T00:00:00.000"
)
_FUNCTION_ARN = "arn:aws:lambda:us-east-1:111111111111:function:evidenceDisposalRecorder"
_ESM_UUID = "12345678-1234-1234-1234-123456789012"
_BUCKET = "rcp-dev-disposal-recovery"
_RECOVERY_KEY = f"aws/lambda/{_ESM_UUID}/2024/01/01/abcdef0123456789"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _old_image(**overrides: Any) -> dict[str, Any]:
    data = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
        "evidence_class": "raw_evidence",
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    data.update(overrides)
    return data


def _dynamodb_record(
    *, old_image: Any = None, event_id: str = "event-abc123", **overrides: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "eventID": event_id,
        "eventName": "REMOVE",
        "eventSourceARN": _STREAM_ARN,
        "userIdentity": {"type": "Service", "principalId": "dynamodb.amazonaws.com"},
        "dynamodb": {"ApproximateCreationDateTime": 1735689600.0, "SequenceNumber": "100"},
    }
    resolved_old_image = _old_image() if old_image is None else old_image
    if resolved_old_image is not None:
        record["dynamodb"]["OldImage"] = encode_item(resolved_old_image)
    record.update(overrides)
    return record


def _recovery_body(
    *, records: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "version": "1.0",
        "requestContext": {"functionArn": _FUNCTION_ARN},
        "DDBStreamBatchInfo": {"streamArn": _STREAM_ARN, "batchSize": 1},
        "payload": {"Records": records if records is not None else [_dynamodb_record()]},
    }
    body.update(overrides)
    return body


def _stage_config(**overrides: Any) -> StageConfig:
    base = dict(
        stage="dev",
        region="us-east-1",
        aws_profile="rcp-dev",
        config_bucket="rcp-dev-config",
        audit_metadata_table="MetadataTable",
        orchestrator_function_name="rcp-dev-orchestrator",
        scheduler_group_name="rcp-dev-schedules",
        schedule_name_prefix="rcp-dev",
        scheduler_execution_target_arn="arn:aws:lambda:us-east-1:111111111111:function:exec",
        scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:111111111111:function:final",
        scheduler_role_arn="arn:aws:iam::111111111111:role/scheduler",
        disposal_recovery_bucket_name=_BUCKET,
        disposal_recorder_function_arn=_FUNCTION_ARN,
        disposal_recorder_event_source_mapping_uuid=_ESM_UUID,
        metadata_table_stream_arn=_STREAM_ARN,
    )
    base.update(overrides)
    return StageConfig(**base)


class _FakeStreamBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    """Minimal boto3 S3 client double. `delete_object` raises if ever
    called -- the strongest possible proof TC-G4 requires (post-redrive
    retention: the recovery object is never deleted on success)."""

    def __init__(
        self, *, body: dict[str, Any] | None = None, get_object_error: ClientError | None = None
    ) -> None:
        self.body = body
        self.get_object_error = get_object_error
        self.get_object_calls: list[dict[str, Any]] = []
        self.delete_object_calls: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_object_calls.append(kwargs)
        if self.get_object_error is not None:
            raise self.get_object_error
        return {"Body": _FakeStreamBody(json.dumps(self.body).encode("utf-8"))}

    def delete_object(self, **kwargs: Any) -> None:  # pragma: no cover -- must never be called
        self.delete_object_calls.append(kwargs)
        raise AssertionError(
            "delete_object must never be called by redrive_disposal_recorder (TC-G4)"
        )


def _executable_ast_node_names(module) -> set[str]:
    """Collect identifier names (attribute accesses, imported names, and
    call targets) from the module's parsed AST -- excludes docstrings and
    comments, which are not represented as Name/Attribute/alias nodes, so
    this is immune to the module's own prose mentioning these names for
    explanatory purposes. Mirrors test_operator_cli_retention.py's own
    identically-named helper.
    """
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class _FakeRepository:
    """Minimal DisposalRepository double: put_disposal_record can be made to
    raise ConditionalWriteError; get_disposal_record returns a preset item.
    """

    def __init__(
        self, *, existing_item: dict[str, Any] | None = None, conflict: bool = False
    ) -> None:
        self.existing_item = existing_item
        self.conflict = conflict
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[Any] = []

    def put_disposal_record(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if self.conflict:
            raise ConditionalWriteError()

    def get_disposal_record(self, client_id, audit_id, disposal_id, *, consistent_read=False):
        self.get_calls.append((client_id, audit_id, disposal_id, consistent_read))
        return self.existing_item


class _SelectiveFakeRepository:
    """A DisposalRepository double that conflicts (and resolves via
    read-back) only for pre-seeded disposal_ids -- lets a single redrive
    invocation contain both an already-recorded record (TC-G3) and a
    genuinely new one, exactly as a real partial-batch-failure redrive
    would."""

    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[Any] = []
        self._existing: dict[str, dict[str, Any]] = {}

    def seed_existing(self, disposal_id: str, item: dict[str, Any]) -> None:
        self._existing[disposal_id] = item

    def put_disposal_record(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if kwargs["disposal_id"] in self._existing:
            raise ConditionalWriteError()

    def get_disposal_record(self, client_id, audit_id, disposal_id, *, consistent_read=False):
        self.get_calls.append((client_id, audit_id, disposal_id, consistent_read))
        return self._existing.get(disposal_id)


# ---------------------------------------------------------------------------
# TC-G2: redrive reprocessing success
# ---------------------------------------------------------------------------


def test_tc_g2_redrive_reprocessing_success():
    repository = _FakeRepository()
    s3_client = _FakeS3Client(body=_recovery_body())
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_PROCESSED
    assert result.exit_code == 0
    assert result.record_count == 1
    assert result.success_count == 1
    assert result.failure_count == 0
    assert len(repository.put_calls) == 1
    assert s3_client.get_object_calls == [{"Bucket": _BUCKET, "Key": _RECOVERY_KEY}]


# ---------------------------------------------------------------------------
# TC-G3: partial-pre-recorded redrive resolves via duplicate-verification
# ---------------------------------------------------------------------------


def test_tc_g3_partial_pre_recorded_redrive_resolves_via_duplicate_verification():
    already_recorded_record = _dynamodb_record(event_id="event-already-recorded")
    new_record = _dynamodb_record(event_id="event-new")

    # Simulate "record 1 was already successfully written in a prior
    # invocation" by running the identical shared processing function once
    # against a fresh, non-conflicting repository to capture the exact
    # DisposalRecord it produces.
    priming_repository = _FakeRepository()
    priming_outcome = disposal_recorder.process_dynamodb_stream_record(
        already_recorded_record,
        expected_stream_arn=_STREAM_ARN,
        repository=priming_repository,
        now_fn=lambda: "2026-01-01T00:00:00.000Z",
    )
    assert priming_outcome.disposition == disposal_recorder.DISPOSITION_RECORDABLE
    existing_disposal_id = priming_outcome.disposal_record.disposal_id
    existing_item = priming_outcome.disposal_record.to_dict()

    repository = _SelectiveFakeRepository()
    repository.seed_existing(existing_disposal_id, existing_item)

    s3_client = _FakeS3Client(body=_recovery_body(records=[already_recorded_record, new_record]))
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
        now_fn=lambda: "2026-01-01T00:00:00.000Z",
    )

    assert result.outcome == REDRIVE_OUTCOME_PROCESSED
    assert result.record_count == 2
    dispositions = {o.record_identifier: o.disposition for o in result.record_outcomes}
    assert (
        dispositions["event-already-recorded"] == disposal_recorder.DISPOSITION_CONFIRMED_DUPLICATE
    )
    assert dispositions["event-new"] == disposal_recorder.DISPOSITION_RECORDABLE
    assert result.success_count == 2
    assert result.failure_count == 0
    assert result.exit_code == 0
    # The already-recorded record must never be re-written -- it resolves
    # via duplicate-verification's read-back, not a second overwriting put.
    assert len(repository.get_calls) == 1


# ---------------------------------------------------------------------------
# TC-G4: post-redrive retention -- no s3:DeleteObject call ever made
# ---------------------------------------------------------------------------


def test_tc_g4_post_redrive_retention_no_delete_object_call():
    repository = _FakeRepository()
    s3_client = _FakeS3Client(body=_recovery_body())
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_PROCESSED
    assert s3_client.delete_object_calls == []


def test_tc_g4_redrive_module_never_references_delete_object():
    """Structural proof, stronger than the behavioral fake-client assertion
    above: `delete_object` is never an executable identifier anywhere in
    this module's own code (AST-level -- immune to the module's own prose
    discussing this guarantee in its docstrings), so no code path could
    call it even under a fixture this test suite has not anticipated."""
    names = _executable_ast_node_names(redrive_module)
    assert "delete_object" not in names


# ---------------------------------------------------------------------------
# TC-G9: construction-time bucket guarantee + six numbered runtime checks
# ---------------------------------------------------------------------------


def test_tc_g9_construction_time_bucket_guarantee_no_bucket_parameter():
    """The construction-time guarantee: `redrive_disposal_recorder`'s own
    function signature has no `bucket`-shaped parameter at all -- the
    bucket name is always resolved from
    `stage_config.disposal_recovery_bucket_name` internally, so no caller-
    suppliable value can ever reach `GetObject`'s `Bucket` argument."""
    parameters = inspect.signature(redrive_disposal_recorder).parameters
    assert "bucket" not in parameters
    assert "recovery_bucket" not in parameters


def test_tc_g9_check1_esm_uuid_key_prefix_mismatch():
    repository = _FakeRepository()
    s3_client = _FakeS3Client(body=_recovery_body())
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key="aws/lambda/00000000-0000-0000-0000-000000000000/2024/01/01/x",
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "recovery_object_key_esm_uuid_mismatch"
    assert result.exit_code == 1
    assert repository.put_calls == []


def test_tc_g9_check2_function_arn_mismatch():
    repository = _FakeRepository()
    body = _recovery_body(
        requestContext={
            "functionArn": "arn:aws:lambda:us-east-1:111111111111:function:someOtherFunction"
        }
    )
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "function_arn_mismatch"
    assert repository.put_calls == []


def test_tc_g9_check3_unsupported_envelope_version():
    repository = _FakeRepository()
    body = _recovery_body(version="2.0")
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "unsupported_envelope_version"
    assert repository.put_calls == []


def test_tc_g9_check4_ddb_stream_batch_info_stream_arn_mismatch():
    repository = _FakeRepository()
    other_stream_arn = (
        "arn:aws:dynamodb:us-east-1:111111111111:table/Other/stream/2024-01-01T00:00:00.000"
    )
    body = _recovery_body(DDBStreamBatchInfo={"streamArn": other_stream_arn, "batchSize": 1})
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "stream_arn_mismatch"
    assert repository.put_calls == []


def test_tc_g9_check5_payload_missing_or_malformed_dynamodb_streams_shape():
    repository = _FakeRepository()
    body = _recovery_body(payload={"Records": []})
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "payload_missing_or_malformed_dynamodb_streams_shape"
    assert repository.put_calls == []


def test_tc_g9_check5_payload_not_a_dict():
    repository = _FakeRepository()
    body = _recovery_body(payload="not-a-dict")
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "payload_missing_or_malformed_dynamodb_streams_shape"


def test_tc_g9_check6_per_record_event_source_arn_mismatch_while_check4_passes():
    """Edge case (§4): DDBStreamBatchInfo.streamArn matches (check 4
    passes) but a single per-record eventSourceARN within payload does not
    (check 6 fails) -- proves the two checks are independent and neither
    subsumes the other."""
    repository = _FakeRepository()
    mismatched_record = _dynamodb_record(
        eventSourceARN="arn:aws:dynamodb:us-east-1:111111111111:table/Other/stream/x"
    )
    body = _recovery_body(records=[mismatched_record])
    s3_client = _FakeS3Client(body=body)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "per_record_event_source_arn_mismatch"
    assert repository.put_calls == []


# ---------------------------------------------------------------------------
# TC-I4: redrive credential-source assertion (structural half -- see
# test_operator_cli_retention.py for the end-to-end construction-path proof
# through operator_cli/main.py's own dispatch)
# ---------------------------------------------------------------------------


def test_tc_i4_redrive_module_never_constructs_its_own_aws_client():
    """This module never imports AwsClientFactory and never constructs a
    boto3 client of its own -- its `s3_client` parameter is always supplied
    by the caller (`operator_cli/main.py`), constructed from the operator's
    own resolved AwsClientFactory credentials, never from
    `EvidenceDisposalRecorderLambdaRole` and never a second, dedicated IAM
    role this design does not provision (ADR Non-Negotiable Invariant 47).
    Uses AST-level identifier extraction (immune to the module's own prose
    discussing `AwsClientFactory`/`boto3` in its docstrings), mirroring
    test_operator_cli_retention.py's own structural proof style.
    """
    names = _executable_ast_node_names(redrive_module)
    assert "AwsClientFactory" not in names
    assert "boto3" not in names


# ---------------------------------------------------------------------------
# TC-I6(b): mocked AccessDenied/ClientError on GetObject -> explicit
# fail-closed DisposalRedriveResult rejection, never a crash or silent
# partial success.
# ---------------------------------------------------------------------------


def test_tc_i6_b_access_denied_on_get_object_fails_closed():
    repository = _FakeRepository()
    error = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")
    s3_client = _FakeS3Client(get_object_error=error)
    stage_config = _stage_config()

    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "recovery_object_read_failed:AccessDenied"
    assert result.exit_code == 1
    assert repository.put_calls == []


def test_tc_i6_b_generic_client_error_on_get_object_fails_closed_no_crash():
    repository = _FakeRepository()
    error = ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "GetObject")
    s3_client = _FakeS3Client(get_object_error=error)
    stage_config = _stage_config()

    # Must not raise -- fail-closed rejection, never an unhandled crash or
    # silent partial success.
    result = redrive_disposal_recorder(
        recovery_object_key=_RECOVERY_KEY,
        stage_config=stage_config,
        s3_client=s3_client,
        repository=repository,
    )

    assert result.outcome == REDRIVE_OUTCOME_REJECTED
    assert result.rejection_reason == "recovery_object_read_failed:InternalError"
    assert result.exit_code == 1
    assert repository.put_calls == []
