"""Reusable DynamoDB TransactWriteItems coordination mechanism for Category
1/2 governed-record writes against LegalHold.hold_version.

Companion ADR Non-Negotiable Invariants 11, 12, 14; Technical Design Section
19.4 ("DynamoDB Concurrency Protocol"). Reuses this codebase's existing
transactional pattern (AggregationRepository.put_records_once,
aggregation/repository.py) and existing optimistic-concurrency idiom
(AuditMetadataRepository.append_lifecycle_transition's
`lifecycle_state = :expected_state`, storage/audit_metadata_client.py)
rather than introducing new infrastructure.

Legal-Hold Correction B1 scope: this module builds the reusable mechanism
only. No Category 1/2 write path (RunMetadata, raw evidence, Phase 4/5/6/7
records) is wired to it here -- that wiring is subphases C+D (RunMetadata /
raw evidence) and E/F (Phase 4-7), not B1. Every test proving this mechanism
works uses a caller-supplied builder standing in for a hypothetical governed
record's own Put/Update -- per B1's own scope note, no orchestration beyond
what is needed to prove the DynamoDB coordination foundation works
end-to-end in a test.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    HOLD_STATE_CONCURRENCY_EXCEEDED_CODE,
    HOLD_STATUS_ACTIVE,
    MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.storage.dynamodb_codec import (
    encode_item,
    encode_value,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# AWS's own literal marker (the string "None", not Python None) for a
# TransactWriteItems CancellationReasons entry belonging to an item whose own
# condition did not cause the cancellation.
_UNAFFECTED_CANCELLATION_CODE = "None"

# Builder contract: given the hold_state just read (or None if the audit was
# never held), return the governed record's own transact-items (unchanged
# from that write path's existing condition) and, separately, the LegalHold
# ConditionCheck item to append. Kept as two return values (not one combined
# list) so this module -- not the caller -- always controls where the hold
# ConditionCheck lands, which is what the precedence check below indexes on.
TransactItemsBuilder = Callable[
    [dict[str, Any] | None],
    tuple[Sequence[dict[str, Any]], dict[str, Any]],
]

GovernedConditionFailedCallback = Callable[[list[dict[str, Any]]], None]


class HoldStateConcurrencyExceededError(StorageError):
    """Technical Design Section 19.4 step 5 / Section 19.15.

    Raised when the LegalHold.hold_version ConditionCheck fails on every
    attempt up to the bounded retry limit -- a genuine, sustained hold-state
    race, not a one-off collision. Never fall back to an unconditioned write
    on exhaustion (ADR Non-Negotiable Invariant 11/14).
    """

    def __init__(self, message: str = "Legal hold state concurrency retries exhausted"):
        super().__init__(message, HOLD_STATE_CONCURRENCY_EXCEEDED_CODE)


def build_hold_version_condition_check_item(
    table_name: str,
    hold_key: dict[str, str],
    hold_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the LegalHold ConditionCheck transact-item (Technical Design
    Section 19.4 step 3, "Item A").

    A pure assertion with no write of its own: `attribute_not_exists(PK)` if
    no hold has ever been placed for this audit identity (hold_state is
    None), or `hold_version = :expected_hold_version` (the exact value just
    read) otherwise. Aborts the entire transaction if false.
    """
    if hold_state is None:
        return {
            "ConditionCheck": {
                "TableName": table_name,
                "Key": encode_item(hold_key),
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
    return {
        "ConditionCheck": {
            "TableName": table_name,
            "Key": encode_item(hold_key),
            "ConditionExpression": "hold_version = :expected_hold_version",
            "ExpressionAttributeValues": {
                ":expected_hold_version": encode_value(hold_state["hold_version"]),
            },
        }
    }


def compute_ttl_disposal_at(
    hold_state: dict[str, Any] | None, custody_expires_at: int
) -> int | None:
    """Technical Design Section 19.4 step 2.

    `custody_expires_at` is always computed fresh by the caller, independent
    of hold state (unchanged from the existing design). `ttl_disposal_at` is
    omitted (None) if and only if the audit identity is currently under an
    ACTIVE hold; otherwise it equals `custody_expires_at`.
    """
    if hold_state is not None and hold_state.get("status") == HOLD_STATUS_ACTIVE:
        return None
    return custody_expires_at


def _reason_failed(reason: dict[str, Any]) -> bool:
    code = reason.get("Code")
    return code not in (None, _UNAFFECTED_CANCELLATION_CODE)


class HoldCoordinatedTransactionRunner:
    """Executes a governed-record write as a `TransactWriteItems` call
    conditioned against `LegalHold.hold_version`, with bounded retry and the
    Technical Design Section 19.4 step 4 dual-failure precedence rule.

    `build_transact_items(hold_state)` is supplied by the caller (a future
    Category 1/2 write path, out of B1's own scope to wire) and must return
    `(governed_items, hold_condition_item)`:

      - `governed_items`: the transact-items representing the governed
        record's own Put/Update(s), with whatever condition that write
        already carries today, unchanged (e.g. `attribute_not_exists(PK)
        AND attribute_not_exists(SK)` for a CREATE; for Phase 4's
        `put_records_once`, its variable-length `4 + 3N` governed-action
        set, N = distinct endpoint count, per Technical Design Section
        19.16).
      - `hold_condition_item`: built via `build_hold_version_condition_check_item`
        against the same `hold_state` this call received.

    `on_governed_condition_failed`, if supplied, is invoked with the raw
    `CancellationReasons` list when a governed item's own condition failed --
    it is the caller's responsibility to raise that write path's existing,
    specific error (`DuplicateRunIdError`, `ConditionalWriteError`, etc.)
    from that callback, per Technical Design Section 19.4 step 4's explicit
    precedence: a governed record's own condition failure is surfaced
    regardless of whether the hold ConditionCheck also failed in the same
    attempt, and is never masked behind a hold-version retry loop. If no
    callback is supplied, the original `ClientError` is re-raised unchanged.
    """

    def __init__(
        self,
        dynamodb_client: Any,
        hold_repository: HoldRepository,
        *,
        max_attempts: int = MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
    ) -> None:
        self._dynamodb_client = dynamodb_client
        self._hold_repository = hold_repository
        self._max_attempts = max_attempts

    def run(
        self,
        client_id: str,
        audit_id: str,
        build_transact_items: TransactItemsBuilder,
        *,
        on_governed_condition_failed: GovernedConditionFailedCallback | None = None,
    ) -> dict[str, Any] | None:
        """Run the coordinated transaction, retrying up to `max_attempts`
        times on a detected hold-state race or an unrelated transient
        cancellation. Returns the `hold_state` observed by the attempt that
        committed successfully (possibly None, if the audit was never held).

        Raises:
            HoldStateConcurrencyExceededError: Retry attempts exhausted with
                the hold ConditionCheck the cause on at least the final
                attempt (Technical Design Section 19.4 step 5).
            StorageError: Any DynamoDB failure unrelated to a condition
                check (e.g. `ResourceNotFoundException`), surfaced via the
                existing `storage_error_from_dynamodb_client_error` path.
            Exception: Whatever `on_governed_condition_failed` raises, or
                (absent a callback) the raw `ClientError`, when the governed
                record's own condition failed -- per the precedence rule,
                this is never converted into a retry or into
                `HoldStateConcurrencyExceededError`.
        """
        for _attempt in range(1, self._max_attempts + 1):
            hold_state = self._hold_repository.get_legal_hold(client_id, audit_id)
            governed_items, hold_condition_item = build_transact_items(hold_state)
            governed_items = list(governed_items)
            transact_items = governed_items + [hold_condition_item]
            try:
                self._dynamodb_client.transact_write_items(TransactItems=transact_items)
                return hold_state
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code != "TransactionCanceledException":
                    raise storage_error_from_dynamodb_client_error(
                        exc, operation="transact_write_items"
                    ) from exc
                reasons = exc.response.get("CancellationReasons", []) or []
                governed_failed = any(
                    _reason_failed(reason) for reason in reasons[: len(governed_items)]
                )
                if governed_failed:
                    # Step 4's explicit precedence: the governed record's
                    # own condition failure wins regardless of whether the
                    # hold ConditionCheck also failed in this same attempt --
                    # never retried, never masked as a hold-version race.
                    if on_governed_condition_failed is not None:
                        on_governed_condition_failed(reasons)
                    raise
                # Either the hold ConditionCheck failed (a genuine hold-state
                # race) or neither item's own condition failed but the
                # transaction was still cancelled anyway (a transient,
                # condition-unrelated cancellation, e.g. throttling) --
                # Technical Design Section 19.4 step 4's second and third
                # bullets: retry either way, bounded by the same attempt cap.
                continue
            except Exception as exc:  # pragma: no cover - defensive, mirrors
                # AggregationRepository.put_records_once's own catch-all for
                # non-ClientError failures (e.g. connection errors).
                raise storage_error_from_dynamodb_request_error(
                    exc, operation="transact_write_items"
                ) from exc
        raise HoldStateConcurrencyExceededError()


__all__ = [
    "GovernedConditionFailedCallback",
    "HoldCoordinatedTransactionRunner",
    "HoldStateConcurrencyExceededError",
    "TransactItemsBuilder",
    "build_hold_version_condition_check_item",
    "compute_ttl_disposal_at",
]
