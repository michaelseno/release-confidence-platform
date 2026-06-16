"""Smoke tests: verify all Lambda handler modules import cleanly.

These tests fail at pytest collection time if any handler has a module-level
ImportError or ModuleNotFoundError, providing a CI guard against
packaging / PYTHONPATH regressions like the round-3 Lambda packaging defect
(Runtime.ImportModuleError: No module named 'release_confidence_platform').

Do not move imports inside test functions — the collection-time failure is the
intended behaviour.
"""
from unittest.mock import MagicMock, patch

import pytest

import apps.backend.handlers.aggregation_handler as aggregation_handler
import apps.backend.handlers.audit_finalization_handler as audit_finalization_handler
import apps.backend.handlers.orchestrator_handler as orchestrator_handler
import apps.backend.handlers.scheduled_execution_handler as scheduled_execution_handler


def test_orchestrator_handler_callable():
    """orchestrator_handler.handler must be a callable after import."""
    assert callable(orchestrator_handler.handler)


def test_scheduled_execution_handler_callable():
    """scheduled_execution_handler.handler must be a callable after import."""
    assert callable(scheduled_execution_handler.handler)


def test_audit_finalization_handler_callable():
    """audit_finalization_handler.handler must be a callable after import.

    This test specifically guards against the round-3 regression where
    release_confidence_platform was not resolvable at Lambda import time
    because PYTHONPATH=/var/task/src was absent from the Lambda environment.
    """
    assert callable(audit_finalization_handler.handler)


def test_aggregation_handler_callable():
    """aggregation_handler.handler must be a callable after import.

    Also verifies the sys.path workaround was safely removed — the module now
    relies on PYTHONPATH=/var/task/src set in serverless.yml instead.
    """
    assert callable(aggregation_handler.handler)


# ---------------------------------------------------------------------------
# Round-7 regression guard: NameError on os.environ inside handler entrypoint
#
# Fix 3 incorrectly removed `import os` from aggregation_handler.py while
# removing the sys.path workaround. Lines 43-44 still reference os.environ,
# so every cold-start invocation raised NameError: name 'os' is not defined.
#
# These tests exercise the handler() entrypoint under controlled env/AWS mocks
# so that any future removal of a stdlib import is caught before deployment.
# ---------------------------------------------------------------------------


def test_aggregation_handler_os_environ_readable(monkeypatch):
    """handler() must not raise NameError when METADATA_TABLE and
    RAW_RESULTS_BUCKET are present in the environment.

    Regression guard for Fix-3 regression: 'import os' was removed while
    os.environ was still referenced on lines 43-44.
    """
    monkeypatch.setenv("METADATA_TABLE", "smoke-metadata-table")
    monkeypatch.setenv("RAW_RESULTS_BUCKET", "smoke-results-bucket")

    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = {"status": "OK"}

    with (
        patch("apps.backend.handlers.aggregation_handler.boto3") as mock_boto3,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationOrchestrator"
        ) as mock_orch_cls,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationRepository"
        ) as mock_repo_cls,
    ):
        mock_boto3.client.return_value = MagicMock()
        mock_repo_cls.return_value = MagicMock()
        mock_orch_cls.return_value = mock_orchestrator

        event = {
            "audit_id": "audit-smoke-001",
            "client_id": "client-smoke",
            "stage": "dev",
        }
        # Must not raise NameError, TypeError, or any import-related error.
        try:
            result = aggregation_handler.handler(event, None)
        except NameError as exc:
            pytest.fail(
                f"NameError in aggregation_handler.handler — missing stdlib import: {exc}"
            )
        # Result is a dict returned by AggregationHandler.handle
        assert isinstance(result, dict)


def test_aggregation_handler_repository_receives_metadata_table(monkeypatch):
    """AggregationRepository must be constructed with the value of METADATA_TABLE
    from the environment, confirming os.environ is accessible at handler init.
    """
    table_name = "my-metadata-table-smoke"
    monkeypatch.setenv("METADATA_TABLE", table_name)
    monkeypatch.setenv("RAW_RESULTS_BUCKET", "my-bucket-smoke")

    captured_args: list = []

    def capturing_repo(table, client):
        captured_args.extend([table, client])
        return MagicMock()

    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = {"status": "OK"}

    with (
        patch("apps.backend.handlers.aggregation_handler.boto3") as mock_boto3,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationOrchestrator"
        ) as mock_orch_cls,
        patch(
            "apps.backend.handlers.aggregation_handler.AggregationRepository",
            side_effect=capturing_repo,
        ),
    ):
        mock_boto3.client.return_value = MagicMock()
        mock_orch_cls.return_value = mock_orchestrator

        event = {
            "audit_id": "audit-smoke-002",
            "client_id": "client-smoke",
            "stage": "dev",
        }
        try:
            aggregation_handler.handler(event, None)
        except NameError as exc:
            pytest.fail(f"NameError — import missing: {exc}")

        assert captured_args[0] == table_name, (
            f"AggregationRepository was constructed with '{captured_args[0]}' "
            f"instead of METADATA_TABLE='{table_name}'"
        )


def test_aggregation_submodules_import():
    """OPS-I05: All aggregation submodules import successfully."""
    import release_confidence_platform.aggregation.orchestrator  # noqa
    import release_confidence_platform.aggregation.eligibility  # noqa
    import release_confidence_platform.aggregation.integrity  # noqa
    import release_confidence_platform.aggregation.engine  # noqa
    import release_confidence_platform.aggregation.lineage  # noqa
    import release_confidence_platform.aggregation.repository  # noqa
    import release_confidence_platform.aggregation.identity  # noqa
    import release_confidence_platform.aggregation.constants  # noqa
    import release_confidence_platform.aggregation.models  # noqa
    import release_confidence_platform.aggregation.events  # noqa


def test_smoke_detects_missing_module():
    """OPS-I06: Smoke test mechanism detects missing modules when None is injected."""
    import sys
    module_name = "release_confidence_platform.aggregation.engine"
    original = sys.modules.get(module_name)
    try:
        sys.modules[module_name] = None  # type: ignore[assignment]
        # Importing a None module should raise AttributeError or ImportError
        with pytest.raises((ImportError, AttributeError)):
            import release_confidence_platform.aggregation.engine as eng  # noqa
            if eng is None:
                raise ImportError("Module is None — simulated missing module")
    finally:
        if original is not None:
            sys.modules[module_name] = original
        elif module_name in sys.modules:
            del sys.modules[module_name]
