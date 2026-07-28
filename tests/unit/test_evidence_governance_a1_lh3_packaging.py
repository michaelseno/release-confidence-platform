"""Evidence Governance Workstream A1.LH3 -- packaging sufficiency regression
(structural check, not a deploy).

The implementation report for this subphase claims infra/serverless.yml's
package.patterns block requires no change: the new production dependencies
this subphase introduces (release_confidence_platform.evidence_retention.
hold_repository / hold_coordination, and release_confidence_platform.
storage.dynamodb_codec, imported by packages/storage/dynamodb_client.py and
packages/storage/s3_client.py) are already covered by the existing, single,
global pattern list -- confirmed by direct inspection this session, not
assumed. This test makes that claim durable: it fails if a future change
narrows or removes any of the required patterns, without requiring an actual
`serverless package`/deploy run.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_SERVERLESS_YML = Path(__file__).resolve().parents[2] / "infra" / "serverless.yml"

# Every production import path this subphase's code depends on, expressed as
# the exact package.patterns entry (relative to infra/, matching
# infra/serverless.yml's own convention) that must include it:
#   - packages/storage/dynamodb_client.py, packages/storage/s3_client.py
#     (this subphase's own changed files) -- packages/storage/**
#   - release_confidence_platform.evidence_retention.hold_repository /
#     hold_coordination / constants / identity (A1.LH1, reused not
#     reinvented) -- src/release_confidence_platform/evidence_retention/**
#   - release_confidence_platform.storage.dynamodb_codec (encode_item/
#     encode_value/decode_item, used by both hold_coordination.py and this
#     subphase's own dynamodb_client.py) --
#     src/release_confidence_platform/storage/**
#   - release_confidence_platform.core.exceptions (StorageError base class
#     hold_coordination.py/hold_repository.py raise, re-wrapped by this
#     subphase's dynamodb_client.py/s3_client.py) --
#     src/release_confidence_platform/core/**
_REQUIRED_PATTERNS = (
    "../packages/storage/**",
    "../src/release_confidence_platform/evidence_retention/**",
    "../src/release_confidence_platform/storage/**",
    "../src/release_confidence_platform/core/**",
)


def _load_patterns() -> list[str]:
    with _SERVERLESS_YML.open() as f:
        config = yaml.safe_load(f)
    return config["package"]["patterns"]


def test_serverless_yml_exists_and_is_parseable():
    assert _SERVERLESS_YML.is_file()
    patterns = _load_patterns()
    assert isinstance(patterns, list)
    assert patterns  # non-empty


def test_package_patterns_include_every_a1_lh3_production_dependency():
    patterns = _load_patterns()
    missing = [pattern for pattern in _REQUIRED_PATTERNS if pattern not in patterns]
    assert not missing, (
        f"infra/serverless.yml's package.patterns no longer includes {missing} -- "
        "A1.LH3's production code (packages/storage/dynamodb_client.py, "
        "packages/storage/s3_client.py) imports "
        "release_confidence_platform.evidence_retention.hold_repository/"
        "hold_coordination, release_confidence_platform.storage.dynamodb_codec, "
        "and release_confidence_platform.core.exceptions -- all three are "
        "required for the Lambda package to import successfully at runtime."
    )


def test_package_patterns_use_single_global_block_not_per_function_override():
    """Evidence Governance Workstream A1.LH3's implementation report claims
    packaging is a single, global pattern block with no per-function
    override that could exclude coreEngineOrchestrator/scheduledExecution
    specifically -- confirmed this session, made durable here. If a future
    change introduces a per-function `package.patterns` override on either
    function, this test must be revisited (a global-only assumption would no
    longer hold)."""
    with _SERVERLESS_YML.open() as f:
        config = yaml.safe_load(f)

    functions = config.get("functions", {})
    assert "coreEngineOrchestrator" in functions
    assert "scheduledExecution" in functions
    for function_name in ("coreEngineOrchestrator", "scheduledExecution"):
        assert "package" not in functions[function_name], (
            f"{function_name} defines its own package.patterns override -- "
            "the global package.patterns coverage this test relies on no "
            "longer applies uniformly; re-verify that function's own "
            "pattern list separately."
        )


def test_orchestrator_and_scheduled_execution_handlers_are_packaged_functions():
    """Both production call sites this subphase wires (orchestrator_handler.py
    and scheduled_execution_handler.py) must actually be deployed Lambda
    functions referencing the handlers this subphase modified."""
    with _SERVERLESS_YML.open() as f:
        config = yaml.safe_load(f)

    functions = config["functions"]
    assert (
        functions["coreEngineOrchestrator"]["handler"]
        == "apps.backend.handlers.orchestrator_handler.handler"
    )
    assert (
        functions["scheduledExecution"]["handler"]
        == "apps.backend.handlers.scheduled_execution_handler.handler"
    )
