"""Smoke tests for Phase 7.6/7.7 operator CLI certify and cert-retrieve commands.

Confirms:
- rcp certify audit --help exits 0 (parser is registered)
- rcp retrieve cert-status --help exits 0 (retrieval parser is registered)
- rcp retrieve cert-summary --help exits 0
- rcp retrieve cert-domains --help exits 0
- rcp retrieve cert-json --help exits 0
- Missing required args for certify audit exits non-zero
- Missing required args for cert-status exits non-zero

Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.4, 20.8;
ADR Non-Negotiable Invariants 30-31): the tests below add composition-level
coverage for `certify audit`'s write-capable custody/hold-dependency wiring
(resolver-called-exactly-once, before-AwsClientFactory, injected-integer,
shared-HoldRepository-identity via `is`, publisher-receives-no-duration,
no-AWS-client-construction-on-resolution-failure) and prove `retrieve cert-*`
remains fully custody-independent. Mocking style follows
test_operator_cli_generate_report.py: patching the attribute on the *source*
module is what takes effect, since `from module import Name` inside
dispatch() resolves `module.Name` fresh on every call.
"""

from __future__ import annotations

import types

import pytest

import release_confidence_platform.audit_platform_integrity.engine as cert_engine_module
import release_confidence_platform.audit_platform_integrity.publisher as cert_publisher_module
import release_confidence_platform.audit_platform_integrity.repository as cert_repository_module
import release_confidence_platform.config.custody_period_config as custody_period_config_module
import release_confidence_platform.config.stage_config as stage_config_module
import release_confidence_platform.storage.aws_client_factory as aws_client_factory_module
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.exceptions import ConfigError
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.operator_cli.main import build_parser, main

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> int:
    """Run the CLI via main() and return the exit code."""
    return main(argv)


# ---------------------------------------------------------------------------
# 1. certify audit --help exits 0
# ---------------------------------------------------------------------------


def test_certify_audit_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 2. retrieve cert-status --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_status_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 3. retrieve cert-summary --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_summary_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-summary", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 4. retrieve cert-domains --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_domains_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-domains", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 5. retrieve cert-json --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_json_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-json", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 6. Missing required args for certify audit exits non-zero
# ---------------------------------------------------------------------------


def test_certify_audit_missing_client_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_audit_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_execution_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--audit-id", "a1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_stage_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 7. Missing required args for cert-status exits non-zero
# ---------------------------------------------------------------------------


def test_cert_status_missing_client_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_cert_status_missing_stage_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 8. Parser build does not raise
# ---------------------------------------------------------------------------


def test_build_parser_does_not_raise():
    parser = build_parser()
    assert parser is not None


def test_certify_group_present_in_parser():
    """Certify group is registered as a subcommand of the main parser."""
    parser = build_parser()
    # Access the subparsers action to inspect registered commands
    # Build a minimal parse to confirm certify audit is recognized
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["certify", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Evidence Governance Workstream A1.3d.4 -- composition contract tests
# ---------------------------------------------------------------------------

CLIENT_ID = "client_certify_sentinel_2e9b"
AUDIT_ID = "audit_certify_sentinel_7f4c"

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


def _fake_certificate() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        certjob_id="certjob_fake",
        identity=types.SimpleNamespace(certificate_id="cert_fake"),
        result=types.SimpleNamespace(terminal_state="CERTIFIED", disclosed_failures=[]),
        domain_results=[],
    )


class _CapturingEngine:
    last_repository = None
    last_publisher = None
    last_logger = None
    certify_kwargs: dict | None = None
    result: types.SimpleNamespace = _fake_certificate()
    raises: Exception | None = None

    def __init__(self, repository, publisher, logger=None, platform_version="unknown"):
        _CapturingEngine.last_repository = repository
        _CapturingEngine.last_publisher = publisher
        _CapturingEngine.last_logger = logger
        _CALL_ORDER.append("engine_init")

    def certify(self, **kwargs):
        _CapturingEngine.certify_kwargs = kwargs
        if _CapturingEngine.raises is not None:
            raise _CapturingEngine.raises
        return _CapturingEngine.result


def _spy_hold_repository_init(self, *args, **kwargs):
    _HOLD_REPOSITORY_INIT_CALLS.append((args, kwargs))
    _CALL_ORDER.append("hold_repository_init")
    _ORIGINAL_HOLD_REPOSITORY_INIT(self, *args, **kwargs)


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
    _CapturingEngine.certify_kwargs = None
    _CapturingEngine.result = _fake_certificate()
    _CapturingEngine.raises = None
    yield


def _apply_certify_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(
        custody_period_config_module, "CustodyPeriodConfigLoader", _FakeCustodyPeriodConfigLoader
    )
    monkeypatch.setattr(cert_engine_module, "CertificationEngine", _CapturingEngine)
    monkeypatch.setattr(HoldRepository, "__init__", _spy_hold_repository_init)


def _certify_argv(*, output: str = "json") -> list[str]:
    return [
        "certify",
        "audit",
        "--client-id",
        CLIENT_ID,
        "--audit-id",
        AUDIT_ID,
        "--execution",
        "exec1",
        "--stage",
        "dev",
        "--output",
        output,
    ]


def test_certify_audit_resolves_certificate_custody_exactly_once(monkeypatch):
    _apply_certify_patches(monkeypatch)
    exit_code = main(_certify_argv())
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == [("certificate", "dev")]


def test_certify_audit_resolves_before_aws_client_factory_construction(monkeypatch):
    _apply_certify_patches(monkeypatch)
    main(_certify_argv())
    assert "custody_resolve" in _CALL_ORDER
    assert "aws_client_factory_init" in _CALL_ORDER
    assert _CALL_ORDER.index("custody_resolve") < _CALL_ORDER.index("aws_client_factory_init")


def test_certify_audit_zero_aws_activity_on_resolution_failure(monkeypatch):
    _apply_certify_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.raises = ConfigError(
        "Custody period configuration value is not a valid positive integer",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    )
    exit_code = main(_certify_argv())
    assert exit_code != 0
    assert _FakeAwsClientFactory.instances == []
    assert _HOLD_REPOSITORY_INIT_CALLS == []
    assert _CapturingEngine.last_repository is None
    assert _CapturingEngine.last_publisher is None


def test_certify_audit_constructs_one_hold_repository(monkeypatch):
    _apply_certify_patches(monkeypatch)
    main(_certify_argv())
    assert len(_HOLD_REPOSITORY_INIT_CALLS) == 1


def test_certify_audit_shares_hold_repository_identity_between_repo_and_publisher(monkeypatch):
    _apply_certify_patches(monkeypatch)
    main(_certify_argv())
    repo_hold = _CapturingEngine.last_repository._hold_repository
    pub_hold = _CapturingEngine.last_publisher._hold_repository
    assert repo_hold is not None
    assert repo_hold is pub_hold
    assert isinstance(repo_hold, HoldRepository)


def test_certify_audit_injects_duration_into_repository_only(monkeypatch):
    _apply_certify_patches(monkeypatch)
    _FakeCustodyPeriodConfigLoader.return_value = 45
    main(_certify_argv())
    assert _CapturingEngine.last_repository._custody_period_days == 45
    publisher = _CapturingEngine.last_publisher
    assert not hasattr(publisher, "_custody_period_days")
    assert not hasattr(publisher, "custody_period_days")


# ---------------------------------------------------------------------------
# retrieve cert-* -- custody-independence composition
# ---------------------------------------------------------------------------


class _SpyCertRepository:
    write_calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def get_cert_metadata(self, *a, **k):
        return {
            "terminal_state": "CERTIFIED",
            "certificate_id": "cert_fake",
            "certjob_id": "certjob_fake",
            "s3_certificate_ref": "integrity/x/artifact.json",
            "s3_report_artifact_ref": "reports/x/artifact.json",
            "certificate_version": "cert_v1",
            "report_id": "report_fake",
            "completed_at": "2026-07-05T12:00:00Z",
        }

    def write_cert_metadata_complete(self, **kwargs):
        _SpyCertRepository.write_calls.append("write_cert_metadata_complete")

    def write_certjob_pending(self, *a, **k):
        _SpyCertRepository.write_calls.append("write_certjob_pending")

    def update_certjob_in_progress(self, *a, **k):
        _SpyCertRepository.write_calls.append("update_certjob_in_progress")

    def update_certjob_complete(self, *a, **k):
        _SpyCertRepository.write_calls.append("update_certjob_complete")

    def update_certjob_failed(self, *a, **k):
        _SpyCertRepository.write_calls.append("update_certjob_failed")


class _SpyCertPublisher:
    write_calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    def write_artifact(self, *a, **k):
        _SpyCertPublisher.write_calls.append("write_artifact")

    def read_artifact(self, key):
        return {"domain_results": []}


def _apply_retrieve_cert_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_config_module, "StageConfigLoader", _FakeStageConfigLoader)
    monkeypatch.setattr(aws_client_factory_module, "AwsClientFactory", _FakeAwsClientFactory)
    monkeypatch.setattr(
        custody_period_config_module, "CustodyPeriodConfigLoader", _FakeCustodyPeriodConfigLoader
    )
    monkeypatch.setattr(cert_repository_module, "CertificationRepository", _SpyCertRepository)
    monkeypatch.setattr(cert_publisher_module, "CertificationPublisher", _SpyCertPublisher)
    monkeypatch.setattr(HoldRepository, "__init__", _spy_hold_repository_init)
    _SpyCertRepository.write_calls = []
    _SpyCertPublisher.write_calls = []


def _retrieve_cert_argv(*, output: str = "json") -> list[str]:
    return [
        "retrieve",
        "cert-status",
        "--client-id",
        CLIENT_ID,
        "--audit-id",
        AUDIT_ID,
        "--execution",
        "exec1",
        "--stage",
        "dev",
        "--output",
        output,
    ]


def test_retrieve_cert_zero_custody_period_config_loader_calls(monkeypatch):
    _apply_retrieve_cert_patches(monkeypatch)
    exit_code = main(_retrieve_cert_argv())
    assert exit_code == 0
    assert _FakeCustodyPeriodConfigLoader.calls == []
    assert _HOLD_REPOSITORY_INIT_CALLS == []


def test_retrieve_cert_unaffected_by_certificate_configuration(monkeypatch):
    """retrieve cert-* must perform zero governed writes -- a spy
    repository/publisher double is injected into the retrieve dispatch
    path and asserted to have recorded zero write calls of any kind."""
    _apply_retrieve_cert_patches(monkeypatch)
    exit_code = main(_retrieve_cert_argv())
    assert exit_code == 0
    assert _SpyCertRepository.write_calls == []
    assert _SpyCertPublisher.write_calls == []
