"""Stage-aware resource naming helpers for Phase 0 validation."""

SUPPORTED_STAGES: tuple[str, ...] = ("dev", "staging", "prod")
RESOURCE_PREFIX = "release-confidence-platform"


def build_resource_names(stage: str) -> dict[str, str]:
    """Return required resource names for a supported stage.

    This helper performs deterministic local string validation only. It does not call AWS or
    imply runtime persistence behavior.
    """
    if stage not in SUPPORTED_STAGES:
        allowed = ", ".join(SUPPORTED_STAGES)
        raise ValueError(f"Unsupported stage '{stage}'. Expected one of: {allowed}")

    return {
        "raw_results": f"{RESOURCE_PREFIX}-{stage}-raw-results",
        "metadata": f"{RESOURCE_PREFIX}-{stage}-metadata",
    }
