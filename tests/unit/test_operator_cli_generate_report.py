"""Tests for operator_cli/main.py's Phase 6 `operator_cli/main.py` construction
contract -- Evidence Governance Workstream A1.3d.3 (Technical Design Section
20.4, 20.7.1, 20.7.2, 20.7.8; ADR Non-Negotiable Invariants 30-31).

Despite its generation-only filename (mirroring
test_operator_cli_generate_intelligence.py's naming convention), this file
owns BOTH halves of Phase 6's operator_cli/main.py composition contract:

  (a) `generate report` CLI dispatch (write-capable): resolver-called-
      exactly-once, before-AwsClientFactory, injected-integer,
      shared-HoldRepository-identity via `is`, publisher-receives-no-
      duration, no-AWS-client-construction-on-CUSTODY_PERIOD_CONFIG_MISSING-
      failure.
  (b) All seven `retrieve report-*` variants' composition (read-only):
      `report` custody configuration may remain unconfigured,
      CustodyPeriodConfigLoader.resolve is never called, HoldRepository is
      never constructed, ReportRepository/ReportPublisher use dependency-
      free (None-default) construction, the DynamoDB and S3 clients are
      constructed exactly as current composition requires, no governed
      report write occurs, and each command's output remains content-
      compatible -- specifically for report-status: zero S3 API operations
      despite S3 client/ReportPublisher construction, and preservation of
      its pre-rendered-text behavior even when --output json is requested.

Phase 6 has no dry-run mode (unlike Phase 5), so this file has no dry-run
section.

Mocking style follows test_operator_cli_generate_intelligence.py: patching
the attribute on the *source* module is what takes effect, since
`from module import Name` inside dispatch() resolves `module.Name` fresh on
every call. The generate half replaces ReportingEngine wholesale (its
constructor captures the real ReportRepository/ReportPublisher instances it
receives, so their `_hold_repository`/`_custody_period_days` attributes can
be inspected directly). The retrieve half replaces ReportRetrievalService
wholesale (it captures the real repository/publisher instances it receives)
and MarkdownFormatter, while leaving ReportRepository/ReportPublisher/
HoldRepository as their real classes so construction-mode assertions
(`is`, `None`-default) are meaningful.
"""

from __future__ import annotations

import json

import pytest

import release_confidence_platform.config.custody_period_config as custody_period_config_module
import release_confidence_platform.config.stage_config as stage_config_module
import release_confidence_platform.deterministic_reporting.engine as engine_module
import release_confidence_platform.deterministic_reporting.formatters.markdown as markdown_module
import release_confidence_platform.deterministic_reporting.report_service as report_service_module
import release_confidence_platform.storage.aws_client_factory as aws_client_factory_module
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.exceptions import ConfigError, StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.operator_cli.main import main

CLIENT_ID = "client_report_sentinel_4d1a"
AUDIT_ID = "audit_report_sentinel_6c2e"

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


class _TrackingS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        raise AssertionError("report-status must never call S3 get_object")

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        raise AssertionError("retrieve report-* must never call S3 put_object")


class _FakeSession:
    def __init__(self):
        self.client_calls: list[str] = []
        self.s3_client = _TrackingS3Client()

    def client(self, name):
        self.client_calls.append(name)
        if name == "s3":
            return self.s3_client
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
        "report_job_id": "rptjob_fake",
        "report_id": "report_fake",
        "report_version": "report_v1",
        "status": "COMPLETE",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": (
            f"reports/{CLIENT_ID}/{AUDIT_ID}/exec1/agg_v1/intel_v1/report_v1/rptjob_fake/artifact.json"
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


def _apply_generate_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(
        custody_period_config_module, "CustodyPeriodConfigLoader", _FakeCustodyPeriodConfigLoader
    )
    monkeypatch.setattr(engine_module, "ReportingEngine", _CapturingEngine)
    monkeypatch.setattr(HoldRepository, "__init__", _spy_hold_repository_init)


def _generate_argv(*, force: bool = False, output: str = "json") -> list[str]:
    argv = [
        "generate",
        "report",
        "--client",
        CLIENT_ID,
        "--audit",
        AUDIT_ID,
        "--execution",
        "exec1",
        "--stage",
        "dev",
        "--output",
        output,
    ]
    if force:
        argv.append("--force")
    return argv


# ---------------------------------------------------------------------------
# (a) generate report -- resolution ordering, injection, identity, isolation
# ---------------------------------------------------------------------------


def test_generate_report_resolves_custody_period_exactly_once(monkeypatch):
    _apply_generate_patches(monkeypatch)
    exit_code = main(_generate_argv())
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == [("report", "dev")]


def test_generate_report_resolves_before_aws_client_factory_construction(monkeypatch):
    _apply_generate_patches(monkeypatch)
    main(_generate_argv())
    assert "custody_resolve" in _CALL_ORDER
    assert "aws_client_factory_init" in _CALL_ORDER
    assert _CALL_ORDER.index("custody_resolve") < _CALL_ORDER.index("aws_client_factory_init")


def test_generate_report_injects_resolved_custody_period_into_repository(monkeypatch):
    _apply_generate_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.return_value = 45
    main(_generate_argv())
    assert _CapturingEngine.last_repository is not None
    assert _CapturingEngine.last_repository._custody_period_days == 45


def test_generate_report_injects_same_hold_repository_instance_into_both(monkeypatch):
    _apply_generate_patches(monkeypatch)
    main(_generate_argv())
    repo_hold = _CapturingEngine.last_repository._hold_repository
    pub_hold = _CapturingEngine.last_publisher._hold_repository
    assert repo_hold is not None
    assert repo_hold is pub_hold
    assert isinstance(repo_hold, HoldRepository)


def test_generate_report_publisher_receives_no_duration_argument(monkeypatch):
    _apply_generate_patches(monkeypatch)
    main(_generate_argv())
    publisher = _CapturingEngine.last_publisher
    assert not hasattr(publisher, "_custody_period_days")
    assert not hasattr(publisher, "custody_period_days")


def test_generate_report_custody_resolution_failure_zero_aws_construction(monkeypatch):
    _apply_generate_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.raises = ConfigError(
        "Custody period configuration value is not a valid positive integer",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    )
    exit_code = main(_generate_argv())
    assert exit_code != 0
    assert _FakeAwsClientFactory.instances == []
    assert _HOLD_REPOSITORY_INIT_CALLS == []
    assert _CapturingEngine.last_repository is None
    assert _CapturingEngine.last_publisher is None


def test_generate_report_force_flag_reaches_engine(monkeypatch):
    _apply_generate_patches(monkeypatch)
    main(_generate_argv(force=True))
    assert _CapturingEngine.generate_kwargs["force"] is True


# ---------------------------------------------------------------------------
# (a) generate report -- rendering / sanitization for newly-reachable codes
# ---------------------------------------------------------------------------

_LEAK_PROBE_STRINGS = (
    CLIENT_ID,
    AUDIT_ID,
    "req-abcdef1234567890",
    f"CLIENT#{CLIENT_ID}",
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
    raise AssertionError(code)  # pragma: no cover - defensive


@pytest.mark.parametrize(
    "code",
    [
        "CUSTODY_PERIOD_CONFIG_MISSING",
        "HOLD_COORDINATION_NOT_CONFIGURED",
        "HOLD_STATE_CONCURRENCY_EXCEEDED",
    ],
)
@pytest.mark.parametrize("output_format", ["human", "json"])
def test_generate_report_error_rendering_preserves_code_and_leaks_nothing(
    monkeypatch, capsys, code, output_format
):
    _apply_generate_patches(monkeypatch)
    exc = _real_exception_for(code)
    if code == "CUSTODY_PERIOD_CONFIG_MISSING":
        _FakeCustodyPeriodConfigLoader.raises = exc
    else:
        _CapturingEngine.raises = exc

    exit_code = main(_generate_argv(output=output_format))

    assert exit_code != 0
    out = capsys.readouterr().out
    assert code in out
    assert "Traceback" not in out
    for probe in _LEAK_PROBE_STRINGS:
        assert probe not in out


# ---------------------------------------------------------------------------
# (b) retrieve report-* -- shared fixtures
# ---------------------------------------------------------------------------


class _FakeIdentity:
    def __init__(self):
        self.report_id = "report_fake"
        self.report_version = "report_v1"
        self.generated_at = "2026-07-04T12:00:00Z"


class _FakeIntelligenceProvenance:
    def __init__(self):
        self.intelligence_version = "intel_v1"
        self.audit_id = AUDIT_ID
        self.aggregate_set_hash = "hashFAKE"


class _FakeExecutiveSummary:
    def __init__(self):
        self.score_label = "HIGH_CONFIDENCE"
        self.composite_score_value = 0.9
        self.endpoint_count = 1
        self.audit_success_rate = 0.9
        self.total_executions = 20
        self.score_label_description = "High confidence"


class _FakeEndpointScore:
    def __init__(self):
        self.composite_score = 0.9
        self.reliability_score = 0.9
        self.stability_score = 1.0
        self.burst_score = 1.0
        self.consistency_score = 1.0


class _FakeEndpoint:
    def __init__(self):
        self.endpoint_id = "ep_fake"
        self.endpoint_score = _FakeEndpointScore()


class _FakeMethodologyDisclosure:
    def __init__(self):
        self.intelligence_version = "intel_v1"
        self.limitations = ["MVP limitation"]
        self.scoring = {"method": "composite"}
        self.stability_label_definitions = {"STABLE": "..."}
        self.burst_label_definitions = {"NO_BURST": "..."}
        self.consistency_label_definitions = {"CONSISTENT": "..."}
        self.label_to_score_mapping = {"HIGH_CONFIDENCE": 0.9}


class _FakeInputLineage:
    def __init__(self):
        self.aggregate_set_hash = "hashFAKE"
        self.aggregation_job_id = "aggjob_fake"
        self.aggregation_version = "agg_v1"
        self.aggregate_set_completion_created_at = "2026-07-04T10:00:00Z"
        self.endpoint_aggregate_count = 1
        self.source_raw_result_count = 20
        self.audit_lineage_manifest_ref = None


class _FakeReportDto:
    def __init__(self):
        self.identity = _FakeIdentity()
        self.intelligence_provenance = _FakeIntelligenceProvenance()
        self.executive_summary = _FakeExecutiveSummary()
        self.endpoints = [_FakeEndpoint()]
        self.methodology_disclosure = _FakeMethodologyDisclosure()
        self.input_lineage = _FakeInputLineage()


_FAKE_STATUS_METADATA = {
    "report_id": "report_fake",
    "report_version": "report_v1",
    "intelligence_version": "intel_v1",
    "audit_id": AUDIT_ID,
    "completed_at": "2026-07-04T12:00:00Z",
    "status": "COMPLETE",
    "score_label": "HIGH_CONFIDENCE",
    "report_job_id": "rptjob_fake",
}

_FAKE_ARTIFACT = {"report_version": "report_v1", "status": "COMPLETE"}


class _FakeReportRetrievalService:
    last_repository = None
    last_publisher = None
    init_count = 0

    def __init__(self, repository, publisher):
        _FakeReportRetrievalService.last_repository = repository
        _FakeReportRetrievalService.last_publisher = publisher
        _FakeReportRetrievalService.init_count += 1

    def get_report_status(self, *args):
        return _FAKE_STATUS_METADATA

    def get_report_dto(self, *args):
        return _FakeReportDto()

    def get_report_artifact(self, *args):
        return _FAKE_ARTIFACT


class _FakeMarkdownFormatter:
    def render(self, dto):
        return "# Fake Markdown Report"


def _apply_retrieve_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(
        custody_period_config_module, "CustodyPeriodConfigLoader", _FakeCustodyPeriodConfigLoader
    )
    monkeypatch.setattr(
        report_service_module, "ReportRetrievalService", _FakeReportRetrievalService
    )
    monkeypatch.setattr(markdown_module, "MarkdownFormatter", _FakeMarkdownFormatter)
    monkeypatch.setattr(HoldRepository, "__init__", _spy_hold_repository_init)
    _FakeReportRetrievalService.last_repository = None
    _FakeReportRetrievalService.last_publisher = None
    _FakeReportRetrievalService.init_count = 0


def _retrieve_argv(command: str, *, output: str = "text") -> list[str]:
    return [
        "retrieve",
        command,
        "--client-id",
        CLIENT_ID,
        "--audit-id",
        AUDIT_ID,
        "--execution",
        "exec1",
        "--config-version",
        "cfg_v1",
        "--aggregation-version",
        "agg_v1",
        "--intelligence-version",
        "intel_v1",
        "--stage",
        "dev",
        "--output",
        output,
    ]


_ALL_RETRIEVE_COMMANDS = (
    "report-status",
    "report-summary",
    "report-endpoints",
    "report-methodology",
    "report-lineage",
    "report-json",
    "report-markdown",
)


# ---------------------------------------------------------------------------
# (b) retrieve report-* -- composition contract, all seven variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", _ALL_RETRIEVE_COMMANDS)
def test_retrieve_report_never_resolves_custody_period(monkeypatch, command):
    _apply_retrieve_patches(monkeypatch)
    exit_code = main(_retrieve_argv(command))
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == []


@pytest.mark.parametrize("command", _ALL_RETRIEVE_COMMANDS)
def test_retrieve_report_never_constructs_hold_repository(monkeypatch, command):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv(command))
    assert _HOLD_REPOSITORY_INIT_CALLS == []


@pytest.mark.parametrize("command", _ALL_RETRIEVE_COMMANDS)
def test_retrieve_report_constructs_dependency_free_repository_and_publisher(monkeypatch, command):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv(command))
    repo = _FakeReportRetrievalService.last_repository
    publisher = _FakeReportRetrievalService.last_publisher
    assert repo is not None
    assert publisher is not None
    assert repo._hold_repository is None
    assert repo._custody_period_days is None
    assert publisher._hold_repository is None


@pytest.mark.parametrize("command", _ALL_RETRIEVE_COMMANDS)
def test_retrieve_report_constructs_dynamodb_and_s3_clients(monkeypatch, command):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv(command))
    assert len(_FakeAwsClientFactory.instances) == 1
    session = _FakeAwsClientFactory.instances[0]._session
    assert "dynamodb" in session.client_calls
    assert "s3" in session.client_calls


@pytest.mark.parametrize("command", _ALL_RETRIEVE_COMMANDS)
def test_retrieve_report_succeeds_with_exit_code_zero(monkeypatch, command):
    _apply_retrieve_patches(monkeypatch)
    exit_code = main(_retrieve_argv(command))
    assert exit_code == 0


def test_retrieve_report_status_makes_zero_s3_api_calls(monkeypatch):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv("report-status"))
    session = _FakeAwsClientFactory.instances[0]._session
    assert session.s3_client.calls == [], (
        "report-status must never invoke S3 get_object/put_object despite "
        "S3 client and ReportPublisher construction"
    )


def test_retrieve_report_status_prints_rendered_unchanged_with_output_json(monkeypatch, capsys):
    _apply_retrieve_patches(monkeypatch)
    exit_code = main(_retrieve_argv("report-status", output="json"))
    assert exit_code == 0
    out = capsys.readouterr().out
    # report-status has no distinct JSON result shape today -- main.py's
    # retrieve-group special case prints result.data["rendered"] directly,
    # bypassing render()/--output json entirely (Technical Design Section
    # 20.7.8). The pre-rendered text, not a JSON envelope, must appear.
    assert "Status:        COMPLETE" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_retrieve_report_status_content_compatible(monkeypatch, capsys):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv("report-status"))
    out = capsys.readouterr().out
    assert "Report ID:             report_fake" in out
    assert "Status:        COMPLETE" in out
    assert "Score Label:   HIGH_CONFIDENCE" in out


def test_retrieve_report_markdown_uses_fake_formatter(monkeypatch, capsys):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv("report-markdown"))
    out = capsys.readouterr().out
    assert "# Fake Markdown Report" in out


def test_retrieve_report_json_returns_pretty_printed_artifact(monkeypatch, capsys):
    _apply_retrieve_patches(monkeypatch)
    main(_retrieve_argv("report-json"))
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == _FAKE_ARTIFACT
