"""Phase 4A.7 regression: lifecycle-transitions retrieval must read the actual storage shape.

Incident: `rcp retrieve lifecycle-transitions` returns total_count=0 for every audit, even
audits with a confirmed DRAFT->SCHEDULED->RUNNING->FINALIZING->COMPLETED lifecycle history
(documented for audit_20260609_b18fee6a in docs/qa/phase4a7_campaign_01.md, section 8).

Root cause: RetrievalRepository.list_lifecycle_history queries for child records at SK
prefix AUDIT#{audit_id}#LIFECYCLE#. No such records are ever written. Lifecycle transitions
are persisted as a `lifecycle_history` list attribute on the root audit item itself — see
AuditLifecycleService.transition() / AuditMetadataRepository.append_lifecycle_transition()
(list_append onto PK=CLIENT#{client_id}, SK=AUDIT#{audit_id}).

These tests exercise the REAL RetrievalRepository (not a hand-written stub) against a
DynamoDB fake that implements true low-level get_item/query semantics, matching how
RetrievalRepository._call() encodes/decodes via dynamodb_codec.
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from release_confidence_platform.retrieval.dtypes import RetrievalFilter
from release_confidence_platform.retrieval.repository import RetrievalRepository
from release_confidence_platform.retrieval.service import RetrievalService

_SER = TypeSerializer()
_DESER = TypeDeserializer()

CLIENT_ID = "client_phase_4_validation_555d54cc"
AUDIT_ID = "audit_20260609_b18fee6a"


def _to_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _SER.serialize(v) for k, v in item.items()}


def _from_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _DESER.deserialize(v) for k, v in item.items()}


class _FakeLowLevelDynamoDB:
    """True low-level boto3.client('dynamodb') semantics: typed values in and out."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def seed(self, item: dict[str, Any]) -> None:
        typed = _to_typed(item)
        self.items[(typed["PK"]["S"], typed["SK"]["S"])] = typed

    def get_item(self, TableName: str, Key: dict[str, Any]) -> dict[str, Any]:
        pk, sk = Key["PK"]["S"], Key["SK"]["S"]
        item = self.items.get((pk, sk))
        return {"Item": item} if item else {}

    def query(
        self,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        pk = ExpressionAttributeValues[":pk"]["S"]
        sk_prefix = ExpressionAttributeValues[":sk_prefix"]["S"]
        items = [v for (p, s), v in self.items.items() if p == pk and s.startswith(sk_prefix)]
        return {"Items": items}


_LIFECYCLE_HISTORY = [
    {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "from_state": "DRAFT",
        "to_state": "SCHEDULED",
        "timestamp": "2026-06-09T13:22:28.844576Z",
        "reason": "schedules_created",
        "actor": "operator_cli",
        "metadata": {"schedule_count": 26},
    },
    {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "from_state": "SCHEDULED",
        "to_state": "RUNNING",
        "timestamp": "2026-06-09T13:23:02.511097Z",
        "reason": "scheduled_occurrence_started",
        "actor": "orchestrator",
        "metadata": {},
    },
    {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "from_state": "RUNNING",
        "to_state": "FINALIZING",
        "timestamp": "2026-06-09T15:22:57.360251Z",
        "reason": "finalization_trigger",
        "actor": "finalization_handler",
        "metadata": {"execution_count": 25},
    },
    {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "from_state": "FINALIZING",
        "to_state": "COMPLETED",
        "timestamp": "2026-06-09T15:22:57.419283Z",
        "reason": "finalization_completed",
        "actor": "finalization_handler",
        "metadata": {"execution_count": 25},
    },
]


def _seed_root_audit_item(
    db: _FakeLowLevelDynamoDB, *, lifecycle_history: list[dict[str, Any]]
) -> None:
    db.seed(
        {
            "PK": f"CLIENT#{CLIENT_ID}",
            "SK": f"AUDIT#{AUDIT_ID}",
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "lifecycle_state": "COMPLETED",
            "lifecycle_history": lifecycle_history,
        }
    )


def test_list_lifecycle_history_reads_from_root_audit_item_attribute():
    """The repository must return the lifecycle_history list stored on the root audit
    item, not query for nonexistent AUDIT#...#LIFECYCLE# child records."""
    db = _FakeLowLevelDynamoDB()
    _seed_root_audit_item(db, lifecycle_history=_LIFECYCLE_HISTORY)
    repo = RetrievalRepository("table", db)

    history = repo.list_lifecycle_history(CLIENT_ID, AUDIT_ID)

    assert len(history) == 4, f"expected 4 transitions, got {len(history)}: {history}"
    assert {h["to_state"] for h in history} == {"SCHEDULED", "RUNNING", "FINALIZING", "COMPLETED"}


def test_list_lifecycle_history_returns_empty_list_when_audit_missing():
    db = _FakeLowLevelDynamoDB()
    repo = RetrievalRepository("table", db)

    assert repo.list_lifecycle_history(CLIENT_ID, AUDIT_ID) == []


def test_list_lifecycle_history_returns_empty_list_when_no_history_attribute_present():
    db = _FakeLowLevelDynamoDB()
    db.seed(
        {
            "PK": f"CLIENT#{CLIENT_ID}",
            "SK": f"AUDIT#{AUDIT_ID}",
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "lifecycle_state": "DRAFT",
        }
    )
    repo = RetrievalRepository("table", db)

    assert repo.list_lifecycle_history(CLIENT_ID, AUDIT_ID) == []


def test_get_lifecycle_transitions_end_to_end_returns_populated_history():
    """Full stack (real RetrievalRepository + real RetrievalService) must surface a
    populated, deterministically ordered transition history for a completed audit."""
    db = _FakeLowLevelDynamoDB()
    _seed_root_audit_item(db, lifecycle_history=_LIFECYCLE_HISTORY)
    repo = RetrievalRepository("table", db)
    svc = RetrievalService(repo)
    filters = RetrievalFilter(client_id=CLIENT_ID, audit_id=AUDIT_ID)

    dto = svc.get_lifecycle_transitions(filters)

    assert dto.total_count == 4
    assert [t.to_state for t in dto.transitions] == [
        "SCHEDULED",
        "RUNNING",
        "FINALIZING",
        "COMPLETED",
    ]
    assert dto.transitions[0].actor == "operator_cli"
    assert dto.transitions[-1].reason == "finalization_completed"
