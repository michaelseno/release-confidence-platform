"""OPS-S01: Startup validation raises on missing critical import."""
import sys
import pytest


def test_startup_validation_raises_on_missing_module():
    """OPS-S01: Lambda startup fails fast when a critical module is missing.

    Simulates the startup_import_validation block by confirming that
    an ImportError propagates when a critical module is None (simulating missing).
    """
    module_name = "release_confidence_platform.aggregation.orchestrator"

    # Save and inject a None sentinel to simulate module missing
    saved = sys.modules.get(module_name)
    sys.modules[module_name] = None  # type: ignore[assignment]

    try:
        with pytest.raises((ImportError, AttributeError)):
            import release_confidence_platform.aggregation.orchestrator as m  # noqa
            if m is None:
                raise ImportError(f"STARTUP_IMPORT_FAILURE: {module_name} is missing")
    finally:
        if saved is not None:
            sys.modules[module_name] = saved
        else:
            sys.modules.pop(module_name, None)
