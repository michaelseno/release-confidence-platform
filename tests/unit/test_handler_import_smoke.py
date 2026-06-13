"""Smoke tests: verify all Lambda handler modules import cleanly.

These tests fail at pytest collection time if any handler has a module-level
ImportError or ModuleNotFoundError, providing a CI guard against
packaging / PYTHONPATH regressions like the round-3 Lambda packaging defect
(Runtime.ImportModuleError: No module named 'release_confidence_platform').

Do not move imports inside test functions — the collection-time failure is the
intended behaviour.
"""
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
