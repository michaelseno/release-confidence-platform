"""Regression test: orchestrator._started_item() must return canonical identifiers unsanitized."""

from __future__ import annotations

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from packages.core.constants.engine import RUN_STATUS_STARTED
from packages.core.validators import OrchestratorEvent

# The canonical regression fixture UUID whose digit sequence "2475004829" matches PHONE_PATTERN.
PHONE_LIKE_UUID = "48a87626-e2f9-4f81-82ff-2475004829ec"
CLIENT_ID = "client_test"
AUDIT_ID = "audit_test"


class _NullStorage:
    """Minimal storage stub providing only the keys() method needed by _started_item."""

    def keys(self, client_id: str, audit_id: str, run_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#RUN#{run_id}"}


def _make_orchestrator() -> CoreEngineOrchestrator:
    return CoreEngineOrchestrator(
        s3_storage=_NullStorage(),
        metadata_storage=_NullStorage(),
        secrets_client=None,
    )


def _make_event(run_id: str) -> OrchestratorEvent:
    return OrchestratorEvent(
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
        scenario_type="repeated_stability",
        triggered_by="scheduler",
        run_id=run_id,
    )


def test_orchestrator_started_item_preserves_canonical_identifiers():
    """A-04: _started_item() must return PK, SK, and run_id with no [REDACTED] mutation."""
    orchestrator = _make_orchestrator()
    event = _make_event(PHONE_LIKE_UUID)

    result = orchestrator._started_item(event)

    expected_sk = f"AUDIT#{AUDIT_ID}#RUN#{PHONE_LIKE_UUID}"
    expected_pk = f"CLIENT#{CLIENT_ID}"

    assert result["PK"] == expected_pk, (
        f"PK was mutated: got {result['PK']!r}, expected {expected_pk!r}"
    )
    assert result["SK"] == expected_sk, (
        f"SK was mutated: got {result['SK']!r}, expected {expected_sk!r}"
    )
    assert result["run_id"] == PHONE_LIKE_UUID, (
        f"run_id was mutated: got {result['run_id']!r}"
    )
    assert result["audit_id"] == AUDIT_ID
    assert result["client_id"] == CLIENT_ID
    assert result["status"] == RUN_STATUS_STARTED

    assert "[REDACTED]" not in result["PK"]
    assert "[REDACTED]" not in result["SK"]
    assert "[REDACTED]" not in result["run_id"]
