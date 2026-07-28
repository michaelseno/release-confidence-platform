"""Evidence Governance Workstream A1.LH3 -- packages/storage/s3_client.py
hold-aware raw-evidence S3 tagging tests.

Supersedes A1.3b's own test file of the same name: `_RAW_EVIDENCE_TAGGING`
was a module-level constant computed once at import time from a hardcoded
`rcp-legal-hold=false` -- it could never reflect runtime hold state by
construction (Technical Design Section 19.8's impact analysis). This file
proves the correction: `write_raw_results_once` now resolves current
legal-hold state fresh, via a `ConsistentRead=True`
`HoldRepository.get_legal_hold` call immediately before every `put_object`
(Technical Design Section 19.5.4), and fails closed rather than writing with
an unresolved hold state (Section 19.14).

Covers Technical Design Section 18.1 (Category 1 -- governed evidence) and
Section 11 row 3 (write_raw_results_once, the sole PutObject call site for
raw execution evidence).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import pytest
from botocore.exceptions import ClientError

from packages.core.exceptions import DuplicateRunIdError, StorageError
from packages.storage.s3_client import S3StorageClient
from release_confidence_platform.evidence_retention.constants import (
    HOLD_STATUS_ACTIVE,
    HOLD_STATUS_RELEASED,
)


def _not_found_error() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")


class CapturingS3Api:
    """Fake S3 API: object never pre-exists, records every put_object call."""

    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, object]] = []

    def head_object(self, **kwargs):  # noqa: ARG002
        raise _not_found_error()

    def put_object(self, **kwargs):
        self.put_object_calls.append(kwargs)
        return {}


class StubHoldRepository:
    """Records every get_legal_hold call (including consistent_read) and
    returns a test-controlled, per-call hold_state -- proving each call is
    resolved fresh rather than cached/reused (the direct regression coverage
    for the old module-level-constant defect)."""

    def __init__(self, hold_state: dict[str, Any] | None = None) -> None:
        self.hold_state = hold_state
        self.calls: list[dict[str, Any]] = []

    def get_legal_hold(
        self, client_id: str, audit_id: str, *, consistent_read: bool = False
    ) -> dict[str, Any] | None:
        self.calls.append(
            {"client_id": client_id, "audit_id": audit_id, "consistent_read": consistent_read}
        )
        return self.hold_state


class FailingHoldRepository:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def get_legal_hold(self, client_id: str, audit_id: str, *, consistent_read: bool = False):
        raise self._exc


def _tags_from_tagging_string(tagging: str) -> dict[str, str]:
    parsed = parse_qs(tagging)
    return {key: values[0] for key, values in parsed.items()}


# ---------------------------------------------------------------------------
# Per-call tag correctness
# ---------------------------------------------------------------------------


def test_write_raw_results_once_tags_object_legal_hold_false_when_no_hold_exists():
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once(
        "raw-results/client1/audit1/run1/results.json", {"results": []}
    )

    assert len(api.put_object_calls) == 1
    call = api.put_object_calls[0]
    assert "Tagging" in call
    tags = _tags_from_tagging_string(call["Tagging"])
    assert tags == {"rcp-legal-hold": "false", "rcp-evidence-class": "raw_evidence"}


def test_write_raw_results_once_tags_object_legal_hold_true_under_active_hold():
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state={"status": HOLD_STATUS_ACTIVE, "hold_version": 1})
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once(
        "raw-results/client1/audit1/run1/results.json", {"results": []}
    )

    tags = _tags_from_tagging_string(api.put_object_calls[0]["Tagging"])
    assert tags == {"rcp-legal-hold": "true", "rcp-evidence-class": "raw_evidence"}


def test_write_raw_results_once_tags_object_legal_hold_false_under_released_hold():
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(
        hold_state={"status": HOLD_STATUS_RELEASED, "hold_version": 2}
    )
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once(
        "raw-results/client1/audit1/run1/results.json", {"results": []}
    )

    tags = _tags_from_tagging_string(api.put_object_calls[0]["Tagging"])
    assert tags["rcp-legal-hold"] == "false"


def test_write_raw_results_once_evidence_class_tag_is_fixed_regardless_of_key():
    """rcp-evidence-class is a hardcoded constant on this method -- every
    call site writes raw evidence (confirmed by the Technical Design) -- so
    the tag value must not vary with the key or payload."""
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once(
        "raw-results/other-client/other-audit/run9/results.json", {"anything": True}
    )

    tags = _tags_from_tagging_string(api.put_object_calls[0]["Tagging"])
    assert tags["rcp-evidence-class"] == "raw_evidence"


def test_write_raw_results_once_preserves_existing_content_type_and_body():
    """Adding Tagging must not disturb the pre-existing PutObject shape."""
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once("raw-results/c/a/r/results.json", {"k": "v"})

    call = api.put_object_calls[0]
    assert call["ContentType"] == "application/json"
    assert b'"k": "v"' in call["Body"] or b'"k":"v"' in call["Body"]


# ---------------------------------------------------------------------------
# No reuse of stale module-level hold state (the direct regression test)
# ---------------------------------------------------------------------------


def test_write_raw_results_once_does_not_reuse_stale_module_level_hold_state():
    """Two writes through the SAME S3StorageClient instance, with the
    underlying hold state changed in between, must produce DIFFERENT tags --
    proving tagging is computed fresh per call, never cached at
    import/construction time (the direct regression test for the old
    _RAW_EVIDENCE_TAGGING module-level-constant defect)."""
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once("raw-results/client1/audit1/run1/results.json", {"a": 1})
    first_tags = _tags_from_tagging_string(api.put_object_calls[0]["Tagging"])

    # Simulate a concurrent PLACE landing between the two writes.
    hold_repo.hold_state = {"status": HOLD_STATUS_ACTIVE, "hold_version": 1}
    storage.write_raw_results_once("raw-results/client1/audit1/run2/results.json", {"a": 2})
    second_tags = _tags_from_tagging_string(api.put_object_calls[1]["Tagging"])

    assert first_tags["rcp-legal-hold"] == "false"
    assert second_tags["rcp-legal-hold"] == "true"


def test_write_raw_results_once_place_racing_creation_is_observed_by_a_later_write():
    """A PLACE committing between two writes (simulating the write-time race
    Technical Design Section 19.11 category 3 describes) must be observed by
    whichever write's own consistent read happens after it commits -- this
    subphase's own responsibility is exactly that per-call freshness; the
    residual window before the marker-anchored reconciliation pass runs is
    A1.LH2's separately-scoped responsibility, not re-implemented here."""
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once("raw-results/client1/audit1/run1/results.json", {"a": 1})
    hold_repo.hold_state = {"status": HOLD_STATUS_ACTIVE, "hold_version": 1}
    storage.write_raw_results_once("raw-results/client1/audit1/run2/results.json", {"a": 2})

    tags = _tags_from_tagging_string(api.put_object_calls[1]["Tagging"])
    assert tags["rcp-legal-hold"] == "true"


def test_write_raw_results_once_release_racing_creation_is_observed_by_a_later_write():
    """Symmetric case: a RELEASE committing between two writes must be
    observed by a later write's own fresh consistent read."""
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state={"status": HOLD_STATUS_ACTIVE, "hold_version": 1})
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once("raw-results/client1/audit1/run1/results.json", {"a": 1})
    hold_repo.hold_state = {"status": HOLD_STATUS_RELEASED, "hold_version": 2}
    storage.write_raw_results_once("raw-results/client1/audit1/run2/results.json", {"a": 2})

    tags = _tags_from_tagging_string(api.put_object_calls[1]["Tagging"])
    assert tags["rcp-legal-hold"] == "false"


# ---------------------------------------------------------------------------
# Consistent-read enforcement (Technical Design Section 19.5.4)
# ---------------------------------------------------------------------------


def test_write_raw_results_once_requests_a_consistent_read():
    api = CapturingS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    storage.write_raw_results_once(
        "raw-results/client1/audit1/run1/results.json", {"results": []}
    )

    assert len(hold_repo.calls) == 1
    assert hold_repo.calls[0]["consistent_read"] is True
    assert hold_repo.calls[0]["client_id"] == "client1"
    assert hold_repo.calls[0]["audit_id"] == "audit1"


# ---------------------------------------------------------------------------
# Fail-closed behavior (Technical Design Section 19.14)
# ---------------------------------------------------------------------------


def test_write_raw_results_once_fails_closed_when_hold_repository_not_configured():
    api = CapturingS3Api()
    storage = S3StorageClient("bucket", api)

    with pytest.raises(StorageError) as exc:
        storage.write_raw_results_once(
            "raw-results/client1/audit1/run1/results.json", {"results": []}
        )

    assert exc.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert api.put_object_calls == []


def test_write_raw_results_once_hold_read_failure_prevents_put_object():
    api = CapturingS3Api()
    hold_repo = FailingHoldRepository(RuntimeError("DynamoDB unavailable"))
    storage = S3StorageClient("bucket", api, hold_repo)

    with pytest.raises(StorageError) as exc:
        storage.write_raw_results_once(
            "raw-results/client1/audit1/run1/results.json", {"results": []}
        )

    assert exc.value.error_type == "HOLD_STATE_UNRESOLVABLE"
    assert api.put_object_calls == []


def test_write_raw_results_once_hold_read_storage_error_is_reraised_with_original_code():
    """A classified failure (release_confidence_platform.core.exceptions.
    StorageError, the exception hierarchy HoldRepository actually raises)
    must be re-surfaced as this module's own StorageError with the same
    error_type -- preserving Technical Design Section 19.15's distinguishable
    codes across the cross-package exception-hierarchy boundary, rather than
    being swallowed into a generic failure."""
    from release_confidence_platform.core.exceptions import StorageError as HoldStorageError

    api = CapturingS3Api()
    hold_repo = FailingHoldRepository(
        HoldStorageError("DynamoDB legal hold table not found", "STORAGE_CONFIG_ERROR")
    )
    storage = S3StorageClient("bucket", api, hold_repo)

    with pytest.raises(StorageError) as exc:
        storage.write_raw_results_once(
            "raw-results/client1/audit1/run1/results.json", {"results": []}
        )

    assert exc.value.error_type == "STORAGE_CONFIG_ERROR"
    assert isinstance(exc.value, StorageError)
    assert api.put_object_calls == []


# ---------------------------------------------------------------------------
# Existing duplicate-write behavior unchanged
# ---------------------------------------------------------------------------


def test_write_raw_results_once_duplicate_key_raises_before_consulting_hold_state():
    class ExistingObjectS3Api(CapturingS3Api):
        def head_object(self, **kwargs):  # noqa: ARG002
            return {}

    api = ExistingObjectS3Api()
    hold_repo = StubHoldRepository(hold_state=None)
    storage = S3StorageClient("bucket", api, hold_repo)

    with pytest.raises(DuplicateRunIdError):
        storage.write_raw_results_once(
            "raw-results/client1/audit1/run1/results.json", {"results": []}
        )

    assert api.put_object_calls == []
    assert hold_repo.calls == []
