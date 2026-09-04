"""Tests for `rcp retention hold place|release|status` -- the A1.4b.0
Amendment's new Operator CLI command group (Technical Design Section 21;
companion ADR Decision 12, Non-Negotiable Invariants 32-37).

Two layers of coverage, mirroring this codebase's existing convention
(test_operator_cli_certify.py / test_operator_cli_generate_intelligence.py):

  1. `evidence_retention/commands.py`'s `dispatch_retention_hold` tested
     directly against a fake `RetentionService` double -- proves reason
     validation happens before any service method call (Section 21.10 item
     14), that the correct single method is invoked per subcommand, that
     the `now` timestamp is generated internally (never operator-supplied),
     and a structural/source-level proof that this module never references
     `HoldRepository.get_legal_hold`/`upsert_hold`/`write_hold_event`
     (Section 21.10 item 16).
  2. `operator_cli/main.py`'s `retention` dispatch block, exercised through
     `main()` end to end with `StageConfigLoader`/`AwsClientFactory` faked
     out and a capturing fake `RetentionService` substituted for the real
     one -- proves the composition wiring: exactly one `RetentionService`
     is constructed per invocation, with `HoldRepository`,
     `CustodySweepClient`, `MarkerStore`, and `HoldTransitions` as its
     declared dependencies (Section 21.2), and that CLI output for all
     three commands renders through the existing sanitization boundary
     with no fabricated count fields (Section 21.8/21.9, items 17-18).

Mocking style follows test_operator_cli_generate_intelligence.py's
`monkeypatch.setattr(<source module>, "<Name>", <Fake>)` pattern: patching
the attribute on the *source* module is what takes effect, since `from
module import Name` inside `dispatch()` resolves `module.Name` fresh on
every call.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest

import release_confidence_platform.core.time as core_time_module
import release_confidence_platform.evidence_retention.disposal_recorder_redrive as redrive_module
import release_confidence_platform.evidence_retention.retention_service as retention_service_module
import release_confidence_platform.storage.aws_client_factory as aws_client_factory_module
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.exceptions import ConfigError, ValidationError
from release_confidence_platform.evidence_retention import commands as commands_module
from release_confidence_platform.evidence_retention.commands import (
    dispatch_disposal_recorder_redrive,
    dispatch_retention_hold,
)
from release_confidence_platform.evidence_retention.disposal_recorder_redrive import (
    REDRIVE_OUTCOME_PROCESSED,
    REDRIVE_OUTCOME_REJECTED,
    DisposalRedriveResult,
)
from release_confidence_platform.evidence_retention.retention_service import HoldOperationResult
from release_confidence_platform.operator_cli.main import build_parser, main

_CLIENT_ID = "client_retention_sentinel_9f2c"
_AUDIT_ID = "audit_retention_sentinel_7ab1"
_ACTOR = "operator_a"
_REASON = "litigation hold"
_FIXED_NOW = "2026-07-18T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Layer 1: dispatch_retention_hold() against a fake RetentionService
# ---------------------------------------------------------------------------


class _FakeService:
    def __init__(self, result: HoldOperationResult | None = None) -> None:
        self.place_calls: list[tuple] = []
        self.release_calls: list[tuple] = []
        self.status_calls: list[tuple] = []
        self._result = result or _default_result()

    def place_legal_hold(self, client_id, audit_id, actor, reason, now):
        self.place_calls.append((client_id, audit_id, actor, reason, now))
        return self._result

    def release_legal_hold(self, client_id, audit_id, actor, reason, now):
        self.release_calls.append((client_id, audit_id, actor, reason, now))
        return self._result

    def get_hold_status(self, client_id, audit_id):
        self.status_calls.append((client_id, audit_id))
        return self._result


def _default_result(**overrides) -> HoldOperationResult:
    base = dict(
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        hold_id="hold_abc123",
        hold_version=1,
        status="ACTIVE",
        sweep_status="COMPLETE",
        fully_enforced=True,
        placed_at=_FIXED_NOW,
        released_at=None,
        hold_count=1,
        disposition="completed",
    )
    base.update(overrides)
    return HoldOperationResult(**base)


def _parser():
    parser = build_parser()
    return parser


def _place_args(**overrides):
    argv = {
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "stage": "dev",
        "output": "text",
        "actor": _ACTOR,
        "reason": _REASON,
        "hold_command": "place",
    }
    argv.update(overrides)
    return _parser().parse_args(
        [
            "retention",
            "hold",
            "place",
            "--client-id",
            argv["client_id"],
            "--audit-id",
            argv["audit_id"],
            "--stage",
            argv["stage"],
            "--actor",
            argv["actor"],
            "--reason",
            argv["reason"],
        ]
    )


def test_place_calls_only_place_legal_hold_with_generated_timestamp(monkeypatch):
    monkeypatch.setattr(core_time_module, "utc_now_iso", lambda: _FIXED_NOW)
    service = _FakeService()
    args = _place_args()

    result = dispatch_retention_hold(args, service)

    assert service.place_calls == [(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _FIXED_NOW)]
    assert service.release_calls == []
    assert service.status_calls == []
    assert result["disposition"] == "completed"


def test_release_requires_non_empty_reason_before_any_service_call():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "",
        ]
    )

    with pytest.raises(ValidationError):
        dispatch_retention_hold(args, service)

    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_release_requires_non_empty_reason_whitespace_only_rejected():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "   ",
        ]
    )

    with pytest.raises(ValidationError):
        dispatch_retention_hold(args, service)

    assert service.release_calls == []


def test_place_requires_non_empty_reason_before_any_service_call():
    service = _FakeService()
    args = _place_args(reason="")

    with pytest.raises(ValidationError):
        dispatch_retention_hold(args, service)

    assert service.place_calls == []


def test_release_calls_only_release_legal_hold(monkeypatch):
    monkeypatch.setattr(core_time_module, "utc_now_iso", lambda: _FIXED_NOW)
    service = _FakeService(_default_result(status="RELEASED", disposition="completed"))
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "released for cause",
        ]
    )

    result = dispatch_retention_hold(args, service)

    assert service.release_calls == [
        (_CLIENT_ID, _AUDIT_ID, _ACTOR, "released for cause", _FIXED_NOW)
    ]
    assert service.place_calls == []
    assert result["status"] == "RELEASED"


def test_status_calls_only_get_hold_status_no_actor_or_reason_required():
    service = _FakeService(
        _default_result(
            status="NEVER_HELD",
            sweep_status=None,
            fully_enforced=False,
            hold_id=None,
            hold_version=None,
            placed_at=None,
            hold_count=0,
            disposition=None,
        )
    )
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "status",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
        ]
    )

    result = dispatch_retention_hold(args, service)

    assert service.status_calls == [(_CLIENT_ID, _AUDIT_ID)]
    assert service.place_calls == []
    assert service.release_calls == []
    assert result["status"] == "NEVER_HELD"
    assert result["disposition"] is None


def test_dispatch_return_value_is_exact_hold_operation_result_field_set():
    service = _FakeService()
    args = _place_args()

    result = dispatch_retention_hold(args, service)

    assert set(result.keys()) == {f.name for f in dataclasses.fields(HoldOperationResult)}


def test_status_command_does_not_require_reason_or_actor_arguments():
    """STATUS's Request Parameters are exactly --client-id/--audit-id/--stage
    (Technical Design Section 21.5) -- --actor/--reason must not be
    accepted or required for this subcommand."""
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "status",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
        ]
    )
    assert not hasattr(args, "actor")
    assert not hasattr(args, "reason")


def test_missing_reason_argument_rejected_by_argparse():
    parser = _parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "retention",
                "hold",
                "place",
                "--client-id",
                _CLIENT_ID,
                "--audit-id",
                _AUDIT_ID,
                "--stage",
                "dev",
                "--actor",
                _ACTOR,
            ]
        )


# ---------------------------------------------------------------------------
# INVALID_IDENTIFIER translation boundary (Technical Design Section 21.5):
# an invalid client_id/audit_id must surface as INVALID_IDENTIFIER -- never
# the codebase-wide validate_identifier() helper's own INVALID_EVENT code --
# identically for place/release/status, with no RetentionService method
# invoked and no raw invalid value, exception detail/traceback, DynamoDB
# storage key, or AWS-specific detail leaked into rendered output.
# ---------------------------------------------------------------------------

_INVALID_CLIENT_ID = "sentinel invalid/client id!!"
_INVALID_AUDIT_ID = "sentinel invalid/audit id!!"

_FORBIDDEN_LEAK_STRINGS = (
    "Traceback",
    "DynamoDB",
    "dynamodb",
    "arn:aws",
    "s3://",
    "PutItem",
    "GetItem",
    "UpdateItem",
    "boto3",
    "botocore",
)


def test_dispatch_place_invalid_client_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    args = _place_args(client_id=_INVALID_CLIENT_ID)

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_dispatch_place_invalid_audit_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    args = _place_args(audit_id=_INVALID_AUDIT_ID)

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_dispatch_release_invalid_client_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _INVALID_CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "released for cause",
        ]
    )

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_dispatch_release_invalid_audit_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _INVALID_AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "released for cause",
        ]
    )

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_dispatch_status_invalid_client_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "status",
            "--client-id",
            _INVALID_CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
        ]
    )

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


def test_dispatch_status_invalid_audit_id_raises_invalid_identifier_no_service_call():
    service = _FakeService()
    parser = _parser()
    args = parser.parse_args(
        [
            "retention",
            "hold",
            "status",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _INVALID_AUDIT_ID,
            "--stage",
            "dev",
        ]
    )

    with pytest.raises(ValidationError) as excinfo:
        dispatch_retention_hold(args, service)

    assert excinfo.value.error_type == "INVALID_IDENTIFIER"
    assert service.place_calls == []
    assert service.release_calls == []
    assert service.status_calls == []


@pytest.mark.parametrize("hold_command", ["place", "release", "status"])
@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize("bad_field", ["client_id", "audit_id"])
def test_main_invalid_identifier_renders_invalid_identifier_not_invalid_event(
    monkeypatch, capsys, hold_command, output_format, bad_field
):
    """End-to-end (Layer 2), through `render_error()`'s existing
    sanitization boundary: for all three `retention hold` commands and both
    output formats, an invalid `client_id` or `audit_id` renders error code
    `INVALID_IDENTIFIER` -- `INVALID_EVENT` (the codebase-wide
    `validate_identifier()` helper's own code) must never appear anywhere in
    the rendered output. No raw invalid identifier value, exception detail
    or traceback, DynamoDB storage key, or AWS-specific detail leaks into
    the output, and RetentionService's place/release/status methods are
    never called.
    """
    _apply_main_patches(monkeypatch)
    client_id = _INVALID_CLIENT_ID if bad_field == "client_id" else _CLIENT_ID
    audit_id = _INVALID_AUDIT_ID if bad_field == "audit_id" else _AUDIT_ID
    invalid_value = _INVALID_CLIENT_ID if bad_field == "client_id" else _INVALID_AUDIT_ID

    argv = [
        "retention",
        "hold",
        hold_command,
        "--client-id",
        client_id,
        "--audit-id",
        audit_id,
        "--stage",
        "dev",
    ]
    if hold_command in ("place", "release"):
        argv += ["--actor", _ACTOR, "--reason", _REASON]
    argv += ["--output", output_format]

    exit_code = main(argv)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "INVALID_EVENT" not in captured.out
    assert invalid_value not in captured.out
    for forbidden in _FORBIDDEN_LEAK_STRINGS:
        assert forbidden not in captured.out
    if output_format == "json":
        parsed = json.loads(captured.out)
        assert parsed["code"] == "INVALID_IDENTIFIER"
        assert parsed["status"] == "error"
    else:
        assert "code: INVALID_IDENTIFIER" in captured.out
    # RetentionService is constructed before dispatch_retention_hold runs
    # (main.py's existing composition order -- see
    # test_main_place_empty_reason_never_calls_place_legal_hold above), but
    # none of its place/release/status methods may ever be called for a
    # request that fails identifier validation.
    assert len(_CapturingRetentionService.instances) == 1
    instance = _CapturingRetentionService.instances[0]
    assert instance.place_calls == []
    assert instance.release_calls == []
    assert instance.status_calls == []


# ---------------------------------------------------------------------------
# Structural / import-level proof (Technical Design Section 21.10 item 16):
# evidence_retention/commands.py must never call HoldRepository read/write
# methods directly, for any of the three operations, including STATUS.
# ---------------------------------------------------------------------------


def _executable_ast_node_names(module) -> set[str]:
    """Collect identifier names (attribute accesses, imported names, and
    call targets) from the module's parsed AST -- excludes docstrings and
    comments, which are not represented as Name/Attribute/alias nodes, so
    this is immune to the module's own prose mentioning these names for
    explanatory purposes.
    """
    import ast

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


def test_commands_module_never_references_hold_repository_directly():
    names = _executable_ast_node_names(commands_module)
    for forbidden in ("get_legal_hold", "upsert_hold", "write_hold_event", "HoldRepository"):
        assert forbidden not in names, (
            f"evidence_retention/commands.py must never reference "
            f"{forbidden!r} directly (Technical Design Section 21.2)"
        )


def test_commands_module_constructs_no_aws_client_of_its_own():
    """RetentionService (and its own declared constructor dependencies) is
    the only thing this module is permitted to construct/call -- it must
    never import CustodySweepClient/MarkerStore/HoldRepository/HoldTransitions
    itself (main.py owns that construction, Section 21.11)."""
    names = _executable_ast_node_names(commands_module)
    for forbidden in ("CustodySweepClient", "MarkerStore", "HoldTransitions"):
        assert forbidden not in names


def test_hold_already_active_never_appears_in_commands_module():
    """Companion ADR Non-Negotiable Invariant 36: HOLD_ALREADY_ACTIVE is not
    a recognized error code anywhere in the operator CLI/RetentionService
    contract."""
    source = inspect.getsource(commands_module)
    assert "HOLD_ALREADY_ACTIVE" not in source


# ---------------------------------------------------------------------------
# Layer 2: operator_cli/main.py composition -- construction wiring and
# end-to-end CLI output, with StageConfigLoader/AwsClientFactory faked and
# a capturing fake RetentionService substituted for the real one.
# ---------------------------------------------------------------------------

_STAGE_CONFIG = StageConfig(
    stage="dev",
    region="us-east-1",
    aws_profile="test",
    config_bucket="bucket",
    audit_metadata_table="table",
    orchestrator_function_name="orchestrator",
    scheduler_group_name="group",
    schedule_name_prefix="rcp-dev",
    scheduler_execution_target_arn="arn:aws:lambda:us-east-1:123:function:execution",
    scheduler_finalization_target_arn="arn:aws:lambda:us-east-1:123:function:finalization",
    scheduler_role_arn="arn:aws:iam::123:role/scheduler",
    # A1.4a disposal-recorder fields (Increment 2) -- a well-formed,
    # internally-consistent set so redrive dispatch/wiring tests below can
    # exercise the real validate_disposal_recorder_config() without needing
    # to monkeypatch it away for every positive-path test.
    disposal_recovery_bucket_name="rcp-dev-disposal-recovery",
    disposal_recorder_function_arn=(
        "arn:aws:lambda:us-east-1:111111111111:function:evidenceDisposalRecorder"
    ),
    disposal_recorder_event_source_mapping_uuid="12345678-1234-1234-1234-123456789012",
    metadata_table_stream_arn=(
        "arn:aws:dynamodb:us-east-1:111111111111:table/table/stream/2024-01-01T00:00:00.000"
    ),
)


class _FakeStageConfigLoader:
    def __init__(self, *args, **kwargs):
        pass

    def load(self, stage, env=None):
        return _STAGE_CONFIG


class _FakeSession:
    def client(self, name):
        return object()


class _FakeAwsClientFactory:
    def __init__(self, stage_config):
        self.stage_config = stage_config
        self._session = _FakeSession()


class _CapturingRetentionService:
    instances: list[_CapturingRetentionService] = []
    result: HoldOperationResult = _default_result()
    raises: Exception | None = None

    def __init__(self, hold_transitions, hold_repository, marker_store, custody_sweep_client):
        self.hold_transitions = hold_transitions
        self.hold_repository = hold_repository
        self.marker_store = marker_store
        self.custody_sweep_client = custody_sweep_client
        self.place_calls: list[tuple] = []
        self.release_calls: list[tuple] = []
        self.status_calls: list[tuple] = []
        _CapturingRetentionService.instances.append(self)

    def place_legal_hold(self, client_id, audit_id, actor, reason, now):
        self.place_calls.append((client_id, audit_id, actor, reason, now))
        if _CapturingRetentionService.raises is not None:
            raise _CapturingRetentionService.raises
        return _CapturingRetentionService.result

    def release_legal_hold(self, client_id, audit_id, actor, reason, now):
        self.release_calls.append((client_id, audit_id, actor, reason, now))
        if _CapturingRetentionService.raises is not None:
            raise _CapturingRetentionService.raises
        return _CapturingRetentionService.result

    def get_hold_status(self, client_id, audit_id):
        self.status_calls.append((client_id, audit_id))
        return _CapturingRetentionService.result


@pytest.fixture(autouse=True)
def _reset_fakes():
    _CapturingRetentionService.instances = []
    _CapturingRetentionService.result = _default_result()
    _CapturingRetentionService.raises = None
    yield


def _apply_main_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    import release_confidence_platform.config.stage_config as stage_config_module

    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(retention_service_module, "RetentionService", _CapturingRetentionService)


def test_main_place_constructs_exactly_one_retention_service_with_declared_dependencies(
    monkeypatch,
):
    from release_confidence_platform.evidence_retention.custody_sweep_client import (
        CustodySweepClient,
    )
    from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
    from release_confidence_platform.evidence_retention.hold_transitions import HoldTransitions
    from release_confidence_platform.evidence_retention.marker_store import MarkerStore

    _apply_main_patches(monkeypatch)

    exit_code = main(
        [
            "retention",
            "hold",
            "place",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            _REASON,
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    assert len(_CapturingRetentionService.instances) == 1
    instance = _CapturingRetentionService.instances[0]
    assert isinstance(instance.hold_transitions, HoldTransitions)
    assert isinstance(instance.hold_repository, HoldRepository)
    assert isinstance(instance.marker_store, MarkerStore)
    assert isinstance(instance.custody_sweep_client, CustodySweepClient)
    # The same HoldRepository instance is reused by HoldTransitions itself.
    assert instance.hold_transitions._holds is instance.hold_repository
    assert len(instance.place_calls) == 1
    assert instance.release_calls == []
    assert instance.status_calls == []


def test_main_release_invokes_only_release_legal_hold(monkeypatch):
    _apply_main_patches(monkeypatch)
    _CapturingRetentionService.result = _default_result(status="RELEASED")

    exit_code = main(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "released for cause",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    instance = _CapturingRetentionService.instances[0]
    assert len(instance.release_calls) == 1
    assert instance.place_calls == []
    assert instance.status_calls == []


def test_main_status_invokes_only_get_hold_status_and_never_held_exit_zero(monkeypatch, capsys):
    _apply_main_patches(monkeypatch)
    _CapturingRetentionService.result = _default_result(
        status="NEVER_HELD",
        sweep_status=None,
        fully_enforced=False,
        hold_id=None,
        hold_version=None,
        placed_at=None,
        hold_count=0,
        disposition=None,
    )

    exit_code = main(
        [
            "retention",
            "hold",
            "status",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    instance = _CapturingRetentionService.instances[0]
    assert instance.status_calls == [(_CLIENT_ID, _AUDIT_ID)]
    assert instance.place_calls == []
    assert instance.release_calls == []
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["status"] == "NEVER_HELD"


def test_main_place_json_output_has_no_fabricated_count_fields(monkeypatch, capsys):
    _apply_main_patches(monkeypatch)

    exit_code = main(
        [
            "retention",
            "hold",
            "place",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            _REASON,
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "s3_versions_retagged_count" not in parsed
    assert "dynamodb_items_updated_count" not in parsed
    assert "reason" not in parsed
    assert "placed_by" not in parsed
    assert "released_by" not in parsed
    assert "marker_s3_key" not in parsed


def test_main_place_text_output_renders_hold_fields(monkeypatch, capsys):
    _apply_main_patches(monkeypatch)

    exit_code = main(
        [
            "retention",
            "hold",
            "place",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            _REASON,
            "--output",
            "text",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "status: ACTIVE" in captured.out
    assert "disposition: completed" in captured.out
    assert "SUCCESS: retention hold place" in captured.out


def test_main_release_hold_not_active_renders_error_and_nonzero_exit(monkeypatch, capsys):
    from release_confidence_platform.evidence_retention.hold_transitions import (
        HoldNotActiveError,
    )

    _apply_main_patches(monkeypatch)
    _CapturingRetentionService.raises = HoldNotActiveError()

    exit_code = main(
        [
            "retention",
            "hold",
            "release",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "released for cause",
            "--output",
            "json",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["code"] == "HOLD_NOT_ACTIVE"
    assert parsed["status"] == "error"


def test_main_place_missing_reason_never_constructs_retention_service(monkeypatch, capsys):
    """Argparse itself rejects a missing --reason before dispatch() ever
    runs -- RetentionService (and therefore HoldRepository/CustodySweepClient/
    MarkerStore/HoldTransitions) must never be constructed for a request that
    never reaches the service layer."""
    _apply_main_patches(monkeypatch)

    with pytest.raises(SystemExit):
        main(
            [
                "retention",
                "hold",
                "place",
                "--client-id",
                _CLIENT_ID,
                "--audit-id",
                _AUDIT_ID,
                "--stage",
                "dev",
                "--actor",
                _ACTOR,
            ]
        )

    assert _CapturingRetentionService.instances == []


def test_main_place_empty_reason_never_calls_place_legal_hold(monkeypatch, capsys):
    _apply_main_patches(monkeypatch)

    exit_code = main(
        [
            "retention",
            "hold",
            "place",
            "--client-id",
            _CLIENT_ID,
            "--audit-id",
            _AUDIT_ID,
            "--stage",
            "dev",
            "--actor",
            _ACTOR,
            "--reason",
            "",
            "--output",
            "json",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["status"] == "error"
    # RetentionService IS constructed (main.py builds it before dispatch),
    # but its place_legal_hold method must never be called for an empty
    # --reason -- the validation happens inside dispatch_retention_hold,
    # before any RetentionService method call (Section 21.10 item 14).
    if _CapturingRetentionService.instances:
        assert _CapturingRetentionService.instances[0].place_calls == []


def test_build_retention_hold_parser_registers_exactly_three_commands():
    """Technical Design Section 21.5: exactly place/release/status -- no
    transition-listing, disposal-request, or backfill command."""
    parser = _parser()
    hold_subparsers_action = None
    for action in parser._subparsers._group_actions:  # type: ignore[union-attr]
        if "retention" in getattr(action, "choices", {}):
            retention_parser = action.choices["retention"]
            for sub_action in retention_parser._subparsers._group_actions:
                if "hold" in getattr(sub_action, "choices", {}):
                    hold_parser = sub_action.choices["hold"]
                    for hold_sub_action in hold_parser._subparsers._group_actions:
                        hold_subparsers_action = hold_sub_action
    assert hold_subparsers_action is not None
    assert set(hold_subparsers_action.choices.keys()) == {"place", "release", "status"}


# ---------------------------------------------------------------------------
# `rcp retention disposal-recorder redrive` (A1.4a Increment 2; Technical
# Design Section 22.9.3/22.9.5). Mirrors the hold-command coverage above:
# Layer 1 (dispatch_disposal_recorder_redrive against a fake
# redrive_disposal_recorder), parser structure, and Layer 2 (main()
# end-to-end with StageConfigLoader/AwsClientFactory faked out).
# ---------------------------------------------------------------------------


def _default_redrive_result(**overrides) -> DisposalRedriveResult:
    base = dict(
        recovery_object_key="aws/lambda/12345678-1234-1234-1234-123456789012/2024/01/01/x",
        outcome=REDRIVE_OUTCOME_PROCESSED,
        rejection_reason=None,
        record_outcomes=(),
        record_count=1,
        success_count=1,
        failure_count=0,
        exit_code=0,
    )
    base.update(overrides)
    return DisposalRedriveResult(**base)


def _redrive_args(**overrides):
    argv = {
        "recovery_object_key": "aws/lambda/12345678-1234-1234-1234-123456789012/2024/01/01/x",
        "stage": "dev",
        "output": "text",
    }
    argv.update(overrides)
    return _parser().parse_args(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            argv["recovery_object_key"],
            "--stage",
            argv["stage"],
            "--output",
            argv["output"],
        ]
    )


# --- Layer 1: dispatch_disposal_recorder_redrive() against a fake redrive function ---


def test_dispatch_disposal_recorder_redrive_calls_redrive_disposal_recorder_with_parsed_args(
    monkeypatch,
):
    captured_calls: list[dict] = []

    def _fake_redrive(**kwargs):
        captured_calls.append(kwargs)
        return _default_redrive_result()

    monkeypatch.setattr(
        redrive_module, "redrive_disposal_recorder", _fake_redrive
    )
    args = _redrive_args()
    stage_config = object()
    s3_client = object()
    repository = object()

    result = dispatch_disposal_recorder_redrive(
        args, stage_config=stage_config, s3_client=s3_client, repository=repository
    )

    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["recovery_object_key"] == args.recovery_object_key
    assert call["stage_config"] is stage_config
    assert call["s3_client"] is s3_client
    assert call["repository"] is repository
    assert result["outcome"] == REDRIVE_OUTCOME_PROCESSED
    assert result["exit_code"] == 0


def test_dispatch_disposal_recorder_redrive_returns_exact_field_set(monkeypatch):
    import dataclasses as dataclasses_module

    monkeypatch.setattr(
        redrive_module,
        "redrive_disposal_recorder",
        lambda **kwargs: _default_redrive_result(),
    )
    args = _redrive_args()

    result = dispatch_disposal_recorder_redrive(
        args, stage_config=object(), s3_client=object(), repository=object()
    )

    assert set(result.keys()) == {f.name for f in dataclasses_module.fields(DisposalRedriveResult)}


# --- Parser structure ---


def test_build_disposal_recorder_redrive_parser_registers_exactly_one_command():
    """Technical Design Section 22.9.3: exactly `redrive` -- no status/list/
    inspect command for this command group exists in this design."""
    parser = _parser()
    disposal_recorder_subparsers_action = None
    for action in parser._subparsers._group_actions:  # type: ignore[union-attr]
        if "retention" in getattr(action, "choices", {}):
            retention_parser = action.choices["retention"]
            for sub_action in retention_parser._subparsers._group_actions:
                if "disposal-recorder" in getattr(sub_action, "choices", {}):
                    disposal_recorder_parser = sub_action.choices["disposal-recorder"]
                    for dr_sub_action in disposal_recorder_parser._subparsers._group_actions:
                        disposal_recorder_subparsers_action = dr_sub_action
    assert disposal_recorder_subparsers_action is not None
    assert set(disposal_recorder_subparsers_action.choices.keys()) == {"redrive"}


def test_disposal_recorder_redrive_parser_has_no_bucket_shaped_argument():
    """TC-G9's construction-time guarantee, exercised at the actual parser
    the CLI registers (`evidence_retention/commands.py`'s
    `build_disposal_recorder_redrive_parser`, wired into `main.py`'s
    top-level parser): no `--bucket`/`--recovery-bucket`-shaped argument
    exists anywhere in this command's own argparse registration -- the
    bucket name is always resolved from
    `StageConfig.disposal_recovery_bucket_name`, never a CLI argument."""
    args = _redrive_args()
    for forbidden in ("bucket", "recovery_bucket", "bucket_name"):
        assert not hasattr(args, forbidden)


def test_disposal_recorder_redrive_requires_recovery_object_key():
    parser = _parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["retention", "disposal-recorder", "redrive", "--stage", "dev"])


# --- Layer 2: operator_cli/main.py composition ---


class _TaggedFakeSession:
    def __init__(self) -> None:
        self.client_calls: list[str] = []

    def client(self, name):
        self.client_calls.append(name)
        return f"fake-{name}-client"


class _TaggedFakeAwsClientFactory:
    instances: list[_TaggedFakeAwsClientFactory] = []

    def __init__(self, stage_config):
        self.stage_config = stage_config
        self._session = _TaggedFakeSession()
        _TaggedFakeAwsClientFactory.instances.append(self)


class _CapturingRedrive:
    calls: list[dict] = []
    result: DisposalRedriveResult = _default_redrive_result()
    raises: Exception | None = None

    @classmethod
    def fake_redrive(cls, **kwargs):
        cls.calls.append(kwargs)
        if cls.raises is not None:
            raise cls.raises
        return cls.result


@pytest.fixture(autouse=True)
def _reset_disposal_redrive_fakes():
    _TaggedFakeAwsClientFactory.instances = []
    _CapturingRedrive.calls = []
    _CapturingRedrive.result = _default_redrive_result()
    _CapturingRedrive.raises = None
    yield


def _apply_disposal_redrive_main_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    import release_confidence_platform.config.stage_config as stage_config_module

    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _TaggedFakeAwsClientFactory)
    monkeypatch.setattr(
        redrive_module,
        "redrive_disposal_recorder",
        _CapturingRedrive.fake_redrive,
    )


def test_main_disposal_recorder_redrive_validates_config_before_aws_client_factory_construction(
    monkeypatch,
):
    """TC-G5/TC-G5-pos ordering, exercised through the real dispatch path:
    `validate_disposal_recorder_config()` must be called, and must succeed,
    before `AwsClientFactory` is ever constructed (Technical Design Section
    22.9.5's "Ordering" paragraph)."""
    call_order: list[str] = []

    def _tracking_validate(self):
        call_order.append("validate")

    class _TrackingAwsClientFactory(_TaggedFakeAwsClientFactory):
        def __init__(self, stage_config):
            call_order.append("constructed")
            super().__init__(stage_config)

    _apply_disposal_redrive_main_patches(monkeypatch)
    monkeypatch.setattr(StageConfig, "validate_disposal_recorder_config", _tracking_validate)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _TrackingAwsClientFactory)

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    assert call_order == ["validate", "constructed"]


def test_main_disposal_recorder_redrive_config_error_short_circuits_before_construction(
    monkeypatch,
):
    """TC-G5 negative path through the real dispatch code: a
    DISPOSAL_RECORDER_CONFIG_ERROR raised by
    validate_disposal_recorder_config() must short-circuit before
    AwsClientFactory is constructed and before redrive_disposal_recorder is
    ever invoked."""

    def _raising_validate(self):
        raise ConfigError("boom", "DISPOSAL_RECORDER_CONFIG_ERROR")

    _apply_disposal_redrive_main_patches(monkeypatch)
    monkeypatch.setattr(StageConfig, "validate_disposal_recorder_config", _raising_validate)

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 1
    assert _TaggedFakeAwsClientFactory.instances == []
    assert _CapturingRedrive.calls == []


def test_main_disposal_recorder_redrive_constructs_s3_client_from_aws_client_factory(monkeypatch):
    """TC-I4, end to end: the S3 client `dispatch_disposal_recorder_redrive`
    receives is exactly the one `AwsClientFactory._session.client("s3")`
    returns -- constructed from the operator's own resolved credentials,
    never a raw/unscoped client and never anything resembling
    `EvidenceDisposalRecorderLambdaRole`."""
    _apply_disposal_redrive_main_patches(monkeypatch)

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    assert len(_CapturingRedrive.calls) == 1
    assert _CapturingRedrive.calls[0]["s3_client"] == "fake-s3-client"
    assert len(_TaggedFakeAwsClientFactory.instances) == 1
    assert "s3" in _TaggedFakeAwsClientFactory.instances[0]._session.client_calls


def test_main_disposal_recorder_redrive_success_json_output(monkeypatch, capsys):
    _apply_disposal_redrive_main_patches(monkeypatch)
    _CapturingRedrive.result = _default_redrive_result(success_count=2, record_count=2)

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "success"
    assert parsed["outcome"] == REDRIVE_OUTCOME_PROCESSED
    assert parsed["record_count"] == 2


def test_main_disposal_recorder_redrive_rejected_renders_error_and_nonzero_exit(
    monkeypatch, capsys
):
    _apply_disposal_redrive_main_patches(monkeypatch)
    _CapturingRedrive.result = DisposalRedriveResult(
        recovery_object_key="aws/lambda/x/y",
        outcome=REDRIVE_OUTCOME_REJECTED,
        rejection_reason="stream_arn_mismatch",
        record_outcomes=(),
        record_count=0,
        success_count=0,
        failure_count=0,
        exit_code=1,
    )

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "failed"
    assert parsed["outcome"] == REDRIVE_OUTCOME_REJECTED
    assert parsed["rejection_reason"] == "stream_arn_mismatch"


def test_main_disposal_recorder_redrive_partial_failure_status(monkeypatch, capsys):
    _apply_disposal_redrive_main_patches(monkeypatch)
    _CapturingRedrive.result = _default_redrive_result(
        record_count=2, success_count=1, failure_count=1, exit_code=1
    )

    exit_code = main(
        [
            "retention",
            "disposal-recorder",
            "redrive",
            "--recovery-object-key",
            "aws/lambda/x/y",
            "--stage",
            "dev",
            "--output",
            "json",
        ]
    )

    assert exit_code == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "partial_failure"
