import json

import pytest

from apps.backend.runner.api_runner import ApiRunner
from packages.config.validators import validate_endpoint_config as validate_runtime_endpoint_config
from packages.core.constants.engine import FAILURE_ASSERTION, FAILURE_PASS
from packages.core.exceptions import ConfigError as RuntimeConfigError
from release_confidence_platform.config.validators import (
    validate_endpoint_config as validate_source_endpoint_config,
)
from release_confidence_platform.core.exceptions import ConfigError as SourceConfigError
from release_confidence_platform.operator_cli.config_init import ConfigInitService

VALIDATOR_MIRRORS = [
    ("runtime", validate_runtime_endpoint_config, RuntimeConfigError),
    ("source", validate_source_endpoint_config, SourceConfigError),
]


def endpoint_config_with(overrides):
    endpoint = {
        "endpoint_id": "health_check",
        "method": "GET",
        "url": "https://example.test/health",
        "headers": {},
        "payload_strategy": "static",
    }
    endpoint.update(overrides)
    return {"endpoints": [endpoint]}


@pytest.mark.parametrize("_name,validator,_error_cls", VALIDATOR_MIRRORS)
def test_expected_status_aliases_normalize_to_nested_assertions(_name, validator, _error_cls):
    cases = [
        ({"assertions": {"expected_status_codes": [200]}}, [200]),
        ({"expected_status_codes": [200]}, [200]),
        ({"expected_status_code": 200}, [200]),
        (
            {"expected_status_codes": [200], "assertions": {"expected_status_codes": [200]}},
            [200],
        ),
    ]

    for overrides, expected_codes in cases:
        normalized = validator(endpoint_config_with(overrides))[0]
        assert normalized["assertions"]["expected_status_codes"] == expected_codes
        assert "expected_status_codes" not in normalized
        assert "expected_status_code" not in normalized


@pytest.mark.parametrize("_name,validator,error_cls", VALIDATOR_MIRRORS)
def test_expected_status_conflicts_are_rejected_consistently(_name, validator, error_cls):
    conflict_cases = [
        {"expected_status_codes": [201], "assertions": {"expected_status_codes": [200]}},
        {"expected_status_code": 201, "assertions": {"expected_status_codes": [200]}},
        {"expected_status_codes": [200], "expected_status_code": 201},
    ]

    for overrides in conflict_cases:
        with pytest.raises(error_cls) as exc:
            validator(endpoint_config_with(overrides))
        assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"
        assert "Conflicting expected status assertions" in str(exc.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_status_codes": []},
        {"expected_status_codes": [True]},
        {"expected_status_codes": ["200"]},
        {"expected_status_codes": [200.0]},
        {"expected_status_codes": [99]},
        {"expected_status_codes": [600]},
        {"expected_status_code": True},
        {"assertions": {"expected_status_codes": []}},
        {"assertions": {"expected_status_codes": [True]}},
        {"assertions": {"expected_status_codes": ["200"]}},
        {"assertions": {"expected_status_codes": [99]}},
        {"assertions": {"expected_status_codes": [600]}},
    ],
)
@pytest.mark.parametrize("_name,validator,error_cls", VALIDATOR_MIRRORS)
def test_invalid_expected_status_values_are_rejected(_name, validator, error_cls, overrides):
    with pytest.raises(error_cls) as exc:
        validator(endpoint_config_with(overrides))

    assert exc.value.error_type == "CONFIG_VALIDATION_ERROR"


def test_runner_uses_configured_status_set_in_assertion_results_and_rejects_302():
    class Response:
        status_code = 302

    class Session:
        def request(self, **kwargs):  # noqa: ARG002
            return Response()

    endpoint = validate_runtime_endpoint_config(
        endpoint_config_with({"expected_status_codes": [200]})
    )[0]
    outcome = ApiRunner(Session()).execute(endpoint)

    assert outcome.failure_type == FAILURE_ASSERTION
    assert outcome.assertion_results["expected_status_codes"] == [200]
    assert outcome.assertion_results["status_code_matched"] is False


def test_runner_missing_status_assertion_intentionally_defaults_to_200_through_399():
    class Response:
        status_code = 302

    class Session:
        def request(self, **kwargs):  # noqa: ARG002
            return Response()

    endpoint = validate_runtime_endpoint_config(endpoint_config_with({}))[0]
    outcome = ApiRunner(Session()).execute(endpoint)

    assert outcome.failure_type == FAILURE_PASS
    assert outcome.assertion_results["expected_status_codes"] == list(range(200, 400))
    assert outcome.assertion_results["status_code_matched"] is True


def test_config_init_sample_endpoints_emit_preferred_nested_assertions(tmp_path):
    result = ConfigInitService(client_shortid="abcd1234", audit_shortid="abcd5678").init(
        client_name="QA Client",
        defaults="dev",
        output_dir=tmp_path,
        include_sample_endpoints=True,
    )
    endpoints_path = (
        tmp_path / result["client_id"] / "audits" / result["audit_id"] / "endpoints.json"
    )
    sample_endpoint = json.loads(endpoints_path.read_text(encoding="utf-8"))["endpoints"][0]

    assert sample_endpoint["assertions"]["expected_status_codes"] == [200]
    assert "expected_status_codes" not in sample_endpoint
    assert "expected_status_code" not in sample_endpoint
