"""Tests for operator_cli/main.py's `generate intelligence` dispatch block --
Evidence Governance Workstream A1.3d.2 (Technical Design Section 20.4, 20.5;
ADR Non-Negotiable Invariants 30-31).

Verifies:
  - Non-dry-run: CustodyPeriodConfigLoader.resolve is called exactly once,
    before AwsClientFactory construction; the resolved integer is injected
    into IntelligenceRepository; the same HoldRepository instance (identity
    checked via `is`) is injected into both IntelligenceRepository and
    IntelligencePublisher; IntelligencePublisher receives no duration
    argument; a CUSTODY_PERIOD_CONFIG_MISSING resolution failure produces
    zero AwsClientFactory/boto3 client construction and zero AWS calls of
    any kind.
  - Dry-run: zero CustodyPeriodConfigLoader.resolve calls; zero
    HoldRepository construction; IntelligenceRepository/IntelligencePublisher
    constructed with hold_repository/custody_period_days at their None
    default; existing dry-run CLI output/exit-code shape is unaffected.
  - Rendering/sanitization: CUSTODY_PERIOD_CONFIG_MISSING,
    HOLD_COORDINATION_NOT_CONFIGURED, HOLD_STATE_CONCURRENCY_EXCEEDED, and a
    generic STORAGE_ERROR (a simulated hold-read failure) all render through
    render_error() with the reason code preserved, a non-zero exit code, and
    no raw traceback / AWS request ID / DynamoDB key / S3 key /
    client_id/audit_id value leaked -- using the REAL, reachable production
    message text for each code (none of which embeds any identity or key
    value, confirmed by direct inspection of repository.py/publisher.py/
    hold_coordination.py) while passing recognizable sentinel identifiers as
    the CLI's own --client/--audit arguments, to prove render_error()'s
    {command, stage, code, message} envelope structurally excludes them.

Mocking style follows tests/unit/test_operator_cli_certify.py (closest
existing write-capable CLI-dispatch precedent) and
tests/unit/test_operator_cli_rcp.py's `monkeypatch.setattr(services,
"AwsClientFactory", FakeFactory)` pattern, adapted for main.py's local,
per-dispatch-call imports: patching the attribute on the *source* module
(e.g. `release_confidence_platform.storage.aws_client_factory.AwsClientFactory`)
is what takes effect, since `from module import Name` inside dispatch()
resolves `module.Name` fresh on every call.
"""

from __future__ import annotations

import json

import pytest

import release_confidence_platform.config.custody_period_config as custody_period_config_module
import release_confidence_platform.config.stage_config as stage_config_module
import release_confidence_platform.reliability_intelligence.engine as engine_module
import release_confidence_platform.storage.aws_client_factory as aws_client_factory_module
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.exceptions import ConfigError, StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.operator_cli.main import main

CLIENT_ID = "client_sentinel_9f2c"
AUDIT_ID = "audit_sentinel_7ab1"

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
)

_CALL_ORDER: list[str] = []
_HOLD_REPOSITORY_INIT_CALLS: list[tuple] = []
_ORIGINAL_HOLD_REPOSITORY_INIT = HoldRepository.__init__


class _FakeStageConfigLoader:
    def __init__(self, *args, **kwargs):
        pass

    def load(self, stage, env=None):
        return _STAGE_CONFIG


class _FakeSession:
    def __init__(self):
        self.client_calls: list[str] = []

    def client(self, name):
        self.client_calls.append(name)
        return object()


class _FakeAwsClientFactory:
    instances: list[_FakeAwsClientFactory] = []

    def __init__(self, stage_config):
        self.stage_config = stage_config
        self._session = _FakeSession()
        _CALL_ORDER.append("aws_client_factory_init")
        _FakeAwsClientFactory.instances.append(self)


class _FakeCustodyPeriodConfigLoader:
    calls: list[tuple[str, str]] = []
    return_value: int = 30
    raises: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    def resolve(self, evidence_class, stage):
        _FakeCustodyPeriodConfigLoader.calls.append((evidence_class, stage))
        _CALL_ORDER.append("custody_resolve")
        if _FakeCustodyPeriodConfigLoader.raises is not None:
            raise _FakeCustodyPeriodConfigLoader.raises
        return _FakeCustodyPeriodConfigLoader.return_value


class _CapturingEngine:
    last_repository = None
    last_publisher = None
    last_logger = None
    generate_kwargs: dict | None = None
    result: dict = {}
    raises: Exception | None = None

    def __init__(self, repository, publisher, logger=None):
        _CapturingEngine.last_repository = repository
        _CapturingEngine.last_publisher = publisher
        _CapturingEngine.last_logger = logger
        _CALL_ORDER.append("engine_init")

    def generate(self, **kwargs):
        _CapturingEngine.generate_kwargs = kwargs
        if _CapturingEngine.raises is not None:
            raise _CapturingEngine.raises
        return _CapturingEngine.result


def _spy_hold_repository_init(self, *args, **kwargs):
    _HOLD_REPOSITORY_INIT_CALLS.append((args, kwargs))
    _CALL_ORDER.append("hold_repository_init")
    _ORIGINAL_HOLD_REPOSITORY_INIT(self, *args, **kwargs)


def _default_result() -> dict:
    return {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "audit_execution_id": "exec1",
        "config_version": "cfg_v1",
        "aggregation_version": "agg_v1",
        "intelligence_job_id": "intjob_fake",
        "status": "COMPLETE",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": (
            f"intelligence/{CLIENT_ID}/{AUDIT_ID}/exec1/agg_v1/intel_v1/intjob_fake/artifact.json"
        ),
    }


@pytest.fixture(autouse=True)
def _reset_fakes():
    _CALL_ORDER.clear()
    _HOLD_REPOSITORY_INIT_CALLS.clear()
    _FakeAwsClientFactory.instances = []
    _FakeCustodyPeriodConfigLoader.calls = []
    _FakeCustodyPeriodConfigLoader.return_value = 30
    _FakeCustodyPeriodConfigLoader.raises = None
    _CapturingEngine.last_repository = None
    _CapturingEngine.last_publisher = None
    _CapturingEngine.last_logger = None
    _CapturingEngine.generate_kwargs = None
    _CapturingEngine.result = _default_result()
    _CapturingEngine.raises = None
    yield


def _apply_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(
        custody_period_config_module, "CustodyPeriodConfigLoader", _FakeCustodyPeriodConfigLoader
    )
    monkeypatch.setattr(engine_module, "IntelligenceEngine", _CapturingEngine)
    monkeypatch.setattr(HoldRepository, "__init__", _spy_hold_repository_init)


def _argv(*, dry_run: bool = False, force: bool = False, output: str = "json") -> list[str]:
    argv = [
        "generate",
        "intelligence",
        "--client",
        CLIENT_ID,
        "--audit",
        AUDIT_ID,
        "--execution",
        "exec1",
        "--config-version",
        "cfg_v1",
        "--stage",
        "dev",
        "--output",
        output,
    ]
    if dry_run:
        argv.append("--dry-run")
    if force:
        argv.append("--force")
    return argv


# ---------------------------------------------------------------------------
# Non-dry-run: resolution ordering, injection, identity, failure isolation
# ---------------------------------------------------------------------------


def test_generate_resolves_custody_period_exactly_once(monkeypatch):
    _apply_patches(monkeypatch)
    exit_code = main(_argv())
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == [("intelligence", "dev")]


def test_generate_resolves_custody_period_before_aws_client_factory_construction(monkeypatch):
    _apply_patches(monkeypatch)
    main(_argv())
    assert "custody_resolve" in _CALL_ORDER
    assert "aws_client_factory_init" in _CALL_ORDER
    assert _CALL_ORDER.index("custody_resolve") < _CALL_ORDER.index("aws_client_factory_init")


def test_generate_injects_resolved_custody_period_into_repository(monkeypatch):
    _apply_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.return_value = 45
    main(_argv())
    assert _CapturingEngine.last_repository is not None
    assert _CapturingEngine.last_repository._custody_period_days == 45


def test_generate_injects_same_hold_repository_instance_into_both(monkeypatch):
    _apply_patches(monkeypatch)
    main(_argv())
    repo_hold = _CapturingEngine.last_repository._hold_repository
    pub_hold = _CapturingEngine.last_publisher._hold_repository
    assert repo_hold is not None
    assert repo_hold is pub_hold
    assert isinstance(repo_hold, HoldRepository)


def test_generate_publisher_receives_no_duration_argument(monkeypatch):
    _apply_patches(monkeypatch)
    main(_argv())
    publisher = _CapturingEngine.last_publisher
    assert not hasattr(publisher, "_custody_period_days")
    assert not hasattr(publisher, "custody_period_days")


def test_generate_custody_resolution_failure_zero_aws_construction(monkeypatch):
    _apply_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.raises = ConfigError(
        "Custody period configuration value is not a valid positive integer",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    )
    exit_code = main(_argv())
    assert exit_code != 0
    assert _FakeAwsClientFactory.instances == []
    assert _HOLD_REPOSITORY_INIT_CALLS == []
    assert _CapturingEngine.last_repository is None
    assert _CapturingEngine.last_publisher is None


# ---------------------------------------------------------------------------
# Dry-run: zero resolution, zero HoldRepository, None-governed construction
# ---------------------------------------------------------------------------


def test_dry_run_zero_custody_resolve_calls(monkeypatch):
    _apply_patches(monkeypatch)
    _CapturingEngine.result = {**_default_result(), "status": "DRY_RUN", "s3_artifact_ref": None}
    exit_code = main(_argv(dry_run=True))
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == []


def test_dry_run_zero_hold_repository_construction(monkeypatch):
    _apply_patches(monkeypatch)
    _CapturingEngine.result = {**_default_result(), "status": "DRY_RUN", "s3_artifact_ref": None}
    main(_argv(dry_run=True))
    assert _HOLD_REPOSITORY_INIT_CALLS == []


def test_dry_run_repository_and_publisher_constructed_with_none_governance(monkeypatch):
    _apply_patches(monkeypatch)
    _CapturingEngine.result = {**_default_result(), "status": "DRY_RUN", "s3_artifact_ref": None}
    main(_argv(dry_run=True))
    assert _CapturingEngine.last_repository._hold_repository is None
    assert _CapturingEngine.last_repository._custody_period_days is None
    assert _CapturingEngine.last_publisher._hold_repository is None


def test_dry_run_still_constructs_aws_clients_for_existing_read_only_query(monkeypatch):
    """--dry-run's existing read-only query still needs dynamodb_client --
    client construction itself is not gated by --dry-run (Technical Design
    Section 20.5)."""
    _apply_patches(monkeypatch)
    _CapturingEngine.result = {**_default_result(), "status": "DRY_RUN", "s3_artifact_ref": None}
    main(_argv(dry_run=True))
    assert len(_FakeAwsClientFactory.instances) == 1


def test_dry_run_output_shape_and_exit_code_unaffected(monkeypatch, capsys):
    _apply_patches(monkeypatch)
    _CapturingEngine.result = {**_default_result(), "status": "DRY_RUN", "s3_artifact_ref": None}
    exit_code = main(_argv(dry_run=True))
    assert exit_code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    # NOTE: CommandResult.data's own "status" key (the raw engine status,
    # "DRY_RUN") wins over CommandResult.status ("dry_run") in the rendered
    # JSON payload -- pre-existing render() merge order (operator_cli/result.py),
    # unaffected by this subphase. This assertion pins current, unchanged
    # behavior, not new behavior.
    assert parsed["status"] == "DRY_RUN"
    assert parsed["command"] == "generate intelligence"
    assert parsed["stage"] == "dev"


# ---------------------------------------------------------------------------
# Rendering / sanitization -- real, reachable production message text for
# each newly-reachable reason code (Technical Design Section 20.11)
# ---------------------------------------------------------------------------

_SENTINEL_S3_KEY = (
    f"intelligence/{CLIENT_ID}/{AUDIT_ID}/exec1/agg_v1/intel_v1/intjob_x/artifact.json"
)

_LEAK_PROBE_STRINGS = (
    CLIENT_ID,
    AUDIT_ID,
    "req-1234567890abcdef",  # sentinel AWS request id
    f"CLIENT#{CLIENT_ID}",  # sentinel DynamoDB key
    _SENTINEL_S3_KEY,
)


def _real_exception_for(code: str) -> Exception:
    if code == "CUSTODY_PERIOD_CONFIG_MISSING":
        return ConfigError(
            "Custody period configuration value is not a valid positive integer",
            "CUSTODY_PERIOD_CONFIG_MISSING",
        )
    if code == "HOLD_COORDINATION_NOT_CONFIGURED":
        return StorageError(
            "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
        )
    if code == "HOLD_STATE_CONCURRENCY_EXCEEDED":
        return HoldStateConcurrencyExceededError()
    if code == "STORAGE_ERROR":
        return StorageError(
            "Legal-hold state could not be resolved prior to intelligence artifact write.",
            "STORAGE_ERROR",
        )
    raise AssertionError(code)  # pragma: no cover - defensive


@pytest.mark.parametrize(
    "code",
    [
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
        "STORAGE_ERROR",
    ],
)
@pytest.mark.parametrize("output_format", ["human", "json"])
def test_error_rendering_preserves_code_nonzero_exit_and_leaks_nothing(
    monkeypatch, capsys, code, output_format
):
    _apply_patches(monkeypatch)
    exc = _real_exception_for(code)
    if code == "CUSTODY_PERIOD_CONFIG_MISSING":
        _FakeCustodyPeriodConfigLoader.raises = exc
    else:
        _CapturingEngine.raises = exc

    exit_code = main(_argv(output=output_format))

    assert exit_code != 0, f"expected non-zero exit code for {code}"
    out = capsys.readouterr().out
    assert code in out, f"expected reason code {code!r} to be preserved in rendered output"
    assert "Traceback" not in out
    for probe in _LEAK_PROBE_STRINGS:
        assert probe not in out, (
            f"rendered output for {code!r} ({output_format}) unexpectedly leaked {probe!r}: {out!r}"
        )
