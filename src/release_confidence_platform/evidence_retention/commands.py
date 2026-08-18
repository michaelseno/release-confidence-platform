"""CLI command definitions for A1.4b Operator CLI Retention Hold commands.

Provides parser registration and dispatch for `rcp retention hold
place|release|status` (A1.4b.0 Amendment; Technical Design Section 21,
§21.11's "New production" file). Mirrors the parser/dispatch shape already
established by `audit_platform_integrity/commands.py`'s `certify audit`
command: parser registration is a thin argparse wrapper, business logic
lives entirely in RetentionService, and identifier validation happens at
the CLI boundary before the service is ever called.

Ownership boundary (Technical Design Section 21.2; companion ADR
Non-Negotiable Invariant 32): `RetentionService` is the sole boundary
between this CLI and hold-state storage. `dispatch_retention_hold` below
constructs no `HoldRepository`/`CustodySweepClient`/`MarkerStore` of its
own and calls only `place_legal_hold`, `release_legal_hold`, and
`get_hold_status` on the `RetentionService` instance it is handed --
never `HoldRepository.get_legal_hold`/`upsert_hold`/`write_hold_event`
directly, not even for the read-only STATUS path. Constructing
`RetentionService` and its own declared constructor dependencies is
`operator_cli/main.py`'s responsibility (mirroring the existing
per-command-group construction pattern already used for `generate
intelligence`/`generate report`/`certify audit`), not this module's.

Timestamp generation (Technical Design Section 21.5's corrected contract):
the operator never supplies a `--now`/`--timestamp` argument. This module
generates the `now` value passed to `RetentionService.place_legal_hold`/
`release_legal_hold` internally, via `core.time.utc_now_iso()` -- the
established clock utility already used elsewhere in this codebase for the
identical purpose.
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import Any


def build_retention_hold_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the `hold` subparser -- with `place`/`release`/`status`
    children -- on the provided `retention` subparsers action.

    Exactly these three commands (Technical Design Section 21.5): no
    transition-listing, disposal-request, backfill, or other retention
    command is registered here.
    """
    hold = sub.add_parser("hold", help="Manage legal holds on audit evidence")
    hold_sub = hold.add_subparsers(dest="hold_command", required=True)

    place = hold_sub.add_parser("place", help="Place a legal hold on an audit identity's evidence")
    _add_hold_identity_args(place)
    place.add_argument("--actor", required=True, help="Operator identity performing this action")
    place.add_argument(
        "--reason",
        required=True,
        help="Justification for the legal hold (required, non-empty)",
    )

    release = hold_sub.add_parser(
        "release", help="Release a legal hold on an audit identity's evidence"
    )
    _add_hold_identity_args(release)
    release.add_argument("--actor", required=True, help="Operator identity performing this action")
    release.add_argument(
        "--reason",
        required=True,
        help="Justification for releasing the legal hold (required, non-empty). "
        "No synthetic or default reason may be substituted -- a legal-hold "
        "release is a governance action and its immutable LegalHoldEvent must "
        "carry the operator's actual justification.",
    )

    status = hold_sub.add_parser(
        "status", help="Show the current legal hold status for an audit identity"
    )
    _add_hold_identity_args(status)


def _add_hold_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--client-id", required=True, dest="client_id")
    parser.add_argument("--audit-id", required=True, dest="audit_id")
    parser.add_argument("--stage", required=True, choices=("dev", "staging", "prod"))
    parser.add_argument("--output", choices=("text", "json"), default="text")


def dispatch_retention_hold(args: argparse.Namespace, service: Any) -> dict[str, Any]:
    """Dispatch `retention hold place|release|status` to a `RetentionService`
    instance.

    Validates `client_id`/`audit_id` via `_validate_hold_identifier` (which
    reuses `validate_identifier`'s rules but translates its failure to this
    command group's authoritative `INVALID_IDENTIFIER` error code -- see
    `_validate_hold_identifier`'s docstring), and -- for `place`/`release`
    only -- requires a non-empty `--reason`, before any `RetentionService`
    call (Technical Design Section 21.5/21.10 item 14). The `now` timestamp
    passed to `place_legal_hold`/`release_legal_hold` is generated here,
    internally, via `core.time.utc_now_iso()` -- never supplied by the
    operator.

    Args:
        args: Parsed argparse namespace from `build_retention_hold_parser`
            (`hold_command` is one of "place", "release", "status").
        service: A `RetentionService` instance (or duck-typed equivalent).

    Returns:
        `dataclasses.asdict()` of the `HoldOperationResult` RetentionService
        returned -- the exact, complete field set (Technical Design Section
        21.4), with no field added or removed here.

    Raises:
        ValidationError: `client_id`/`audit_id` fail identifier validation
            (raised here with error code `INVALID_IDENTIFIER`, per Technical
            Design Section 21.5 -- not the `INVALID_EVENT` code
            `validate_identifier` itself raises), or (place/release only)
            `--reason` is missing or empty after stripping whitespace.
        HoldNotActiveError: RELEASE found nothing eligible to release
            (propagated unchanged from `RetentionService.release_legal_hold`).
        MarkerEstablishmentFailedError / MarkerIntegrityError / StorageError:
            Propagated unchanged from `RetentionService`.
    """
    from release_confidence_platform.core.time import utc_now_iso  # noqa: PLC0415

    _validate_hold_identifier("client_id", args.client_id)
    _validate_hold_identifier("audit_id", args.audit_id)

    hold_command = args.hold_command
    if hold_command == "place":
        _require_non_empty_reason(args.reason)
        result = service.place_legal_hold(
            args.client_id, args.audit_id, args.actor, args.reason, utc_now_iso()
        )
    elif hold_command == "release":
        _require_non_empty_reason(args.reason)
        result = service.release_legal_hold(
            args.client_id, args.audit_id, args.actor, args.reason, utc_now_iso()
        )
    elif hold_command == "status":
        result = service.get_hold_status(args.client_id, args.audit_id)
    else:
        raise AssertionError(f"retention hold {hold_command}")

    return dataclasses.asdict(result)


def _validate_hold_identifier(name: str, value: Any) -> str:
    """A1.4b-local translation boundary for `client_id`/`audit_id`
    validation (Technical Design Section 21.5).

    Reuses `core.validators.validate_identifier`'s identifier-format rules
    unchanged -- this function does not reimplement identifier validation.
    `validate_identifier` is a codebase-wide helper used by many other
    commands and always raises with error code `INVALID_EVENT`; that
    pre-existing behavior is correct and unchanged everywhere else. This
    command group's own authoritative contract (Technical Design Section
    21.5) requires error code `INVALID_IDENTIFIER` specifically for
    `retention hold place|release|status`, so a validation failure caught
    here is fully replaced with a sanitized `ValidationError` carrying that
    code, before it can propagate to operator-facing output.

    The replacement message references only `name` ("client_id" or
    "audit_id"), never the raw invalid `value` or any detail from the
    original exception -- nothing from `validate_identifier`'s own
    exception message reaches this function's raised `ValidationError`.
    The original exception is chained via `from` solely so it remains
    visible in an internal traceback; that chaining carries no operator-
    facing effect since `render_error`/`render` only ever read the
    outward-facing exception's own `.error_type`/`.message` attributes.

    Applies identically to `client_id` and `audit_id`, and -- because both
    `dispatch_retention_hold` call sites above run before any
    `hold_command` branch dispatch -- identically to `place`, `release`,
    and `status`.
    """
    from release_confidence_platform.core.exceptions import ValidationError  # noqa: PLC0415
    from release_confidence_platform.core.validators import validate_identifier  # noqa: PLC0415

    try:
        return validate_identifier(name, value)
    except ValidationError as exc:
        raise ValidationError(f"Invalid {name}", "INVALID_IDENTIFIER") from exc


def _require_non_empty_reason(reason: str | None) -> None:
    """Reject a missing or empty-string `--reason` before any
    `RetentionService` call (Technical Design Section 21.5/21.10 item 14).
    No synthetic or default reason is ever substituted here or anywhere
    else in this module.
    """
    from release_confidence_platform.core.exceptions import ValidationError  # noqa: PLC0415

    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("reason must not be empty", "INVALID_ARGUMENT")


__all__ = ["build_retention_hold_parser", "dispatch_retention_hold"]
