from packages.core.constants.identifiers import MANDATORY_IDENTIFIERS
from packages.core.constants.resources import SUPPORTED_STAGES, build_resource_names
from packages.core.logging import CORRELATION_LOG_FIELDS, FORBIDDEN_LOG_FIELDS, STANDARD_LOG_FIELDS


def test_mandatory_identifiers_are_exact() -> None:
    assert MANDATORY_IDENTIFIERS == (
        "client_id",
        "audit_id",
        "run_id",
        "endpoint_id",
        "scenario_id",
        "raw_result_version",
    )


def test_stage_resource_names_are_exact() -> None:
    assert SUPPORTED_STAGES == ("dev", "staging", "prod")
    for stage in SUPPORTED_STAGES:
        names = build_resource_names(stage)
        assert names["raw_results"] == f"release-confidence-platform-{stage}-raw-results"
        assert names["metadata"] == f"release-confidence-platform-{stage}-metadata"


def test_unsupported_stage_is_rejected() -> None:
    try:
        build_resource_names("qa")
    except ValueError as exc:
        assert "Unsupported stage" in str(exc)
    else:
        raise AssertionError("unsupported stage should be rejected")


def test_logging_standard_fields_are_reserved() -> None:
    assert {"timestamp", "level", "message", "service", "stage", "event_type"}.issubset(
        STANDARD_LOG_FIELDS
    )
    assert CORRELATION_LOG_FIELDS == MANDATORY_IDENTIFIERS
    assert {"authorization", "cookie", "password", "secret", "token"}.issubset(FORBIDDEN_LOG_FIELDS)
