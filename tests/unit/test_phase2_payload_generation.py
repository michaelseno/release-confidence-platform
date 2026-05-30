import hashlib
import threading

import pytest

from packages.data_generation.data_pools import DataPoolError, normalize_data_pool, select_record
from packages.data_generation.duplicate_checker import DuplicateChecker
from packages.data_generation.fingerprints import payload_fingerprint
from packages.data_generation.generator import PayloadPreparationService, RunContext
from packages.data_generation.templates import TemplateContext, render_template
from packages.data_generation.validators import (
    PayloadValidationError,
    validate_endpoint_payload_config,
)


def run_context() -> RunContext:
    return RunContext("client", "audit", "safe_run_123", "release_smoke", "2026-05-18T12:00:00Z")


def checker() -> DuplicateChecker:
    return DuplicateChecker(client_id="client", audit_id="audit", run_id="safe_run_123")


def static_endpoint(**overrides):
    endpoint = {
        "endpoint_id": "static",
        "method": "GET",
        "url": "https://service.test/static",
        "payload_strategy": "static",
        "duplicate_policy": "fail_fast",
        "duplicate_check_scope": "current_run",
        "payload_safety": {},
    }
    endpoint.update(overrides)
    return endpoint


class Loader:
    def load(self, client_id, pool_name):  # noqa: ARG002
        return [{"id": "same"}]


def test_generated_template_replaces_reserved_tokens_deterministically() -> None:
    context = TemplateContext(
        client_id="client",
        audit_id="audit",
        run_id="safe_run_123",
        endpoint_id="ep1",
        iteration=3,
        run_timestamp="2026-05-18T12:00:00Z",
    )
    template = {"id": "{{uuid}}|{{run_id}}|{{uuid}}", "iteration": "{{iteration}}"}

    first = render_template(template, context)
    second = render_template(template, context)

    assert first == second
    left, run_id, right = first["id"].split("|")
    assert run_id == "safe_run_123"
    assert left != right
    assert first["iteration"] == "3"


def test_generated_unknown_token_fails() -> None:
    context = TemplateContext("client", "audit", "safe_run_123", "ep1", 1, "ts")
    with pytest.raises(ValueError):
        render_template({"bad": "{{random}}"}, context)


def test_generated_malformed_token_with_extra_brace_fails() -> None:
    context = TemplateContext("client", "audit", "safe_run_123", "ep1", 1, "ts")
    with pytest.raises(ValueError):
        render_template({"bad": "{{uuid}}}"}, context)


def test_data_pool_template_substitution_and_missing_field() -> None:
    context = TemplateContext(
        "client",
        "audit",
        "safe_run_123",
        "ep1",
        1,
        "ts",
        data_pool_record={"user": {"id": "u1"}, "name": "Ada"},
    )
    assert render_template({"id": "{{user.id}}"}, context, allow_data_pool_tokens=True) == {
        "id": "u1"
    }
    with pytest.raises(ValueError):
        render_template({"id": "{{user.email}}"}, context, allow_data_pool_tokens=True)


def test_fingerprint_canonicalizes_json_and_empty_payload() -> None:
    assert payload_fingerprint({"b": 2, "a": 1}) == payload_fingerprint({"a": 1, "b": 2})
    assert payload_fingerprint(None) == hashlib.sha256(b"EMPTY_PAYLOAD").hexdigest()


def test_duplicate_checker_is_current_run_scoped_and_thread_safe() -> None:
    dup = checker()
    outcomes = []

    def reserve() -> None:
        outcomes.append(
            dup.check_and_reserve(
                scope="current_run",
                fingerprint="abc",
                duplicate_subject_type="payload",
                endpoint_id="ep1",
                iteration=1,
                payload_strategy="static",
            ).duplicate_detected
        )

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [False, True]


def test_validate_safety_and_static_tokens() -> None:
    with pytest.raises(PayloadValidationError):
        validate_endpoint_payload_config(
            {"payload_strategy": "generated", "payload_template": {"x": "{{uuid}}"}}
        )
    with pytest.raises(PayloadValidationError):
        validate_endpoint_payload_config(
            {
                "payload_strategy": "static",
                "payload": {"x": "{{run_id}}"},
                "payload_safety": {"destructive_operation": True},
            }
        )


def test_data_pool_schema_and_assignment() -> None:
    records = normalize_data_pool({"records": [{"id": "a"}, {"id": "b"}]})
    assert normalize_data_pool([{"id": "a"}]) == [{"id": "a"}]
    selected = select_record(
        records,
        client_id="client",
        audit_id="audit",
        run_id="safe_run_123",
        endpoint_id="ep1",
        scenario_type="release_smoke",
        iteration=1,
    )
    assert selected == select_record(
        records,
        client_id="client",
        audit_id="audit",
        run_id="safe_run_123",
        endpoint_id="ep1",
        scenario_type="release_smoke",
        iteration=1,
    )
    with pytest.raises(DataPoolError):
        normalize_data_pool({"metadata": {}})


def test_payload_preparation_duplicate_allow_metadata() -> None:
    service = PayloadPreparationService()
    endpoint = {
        "endpoint_id": "ep1",
        "payload_strategy": "generated",
        "payload_template": {"id": "fixed"},
        "duplicate_policy": "allow",
        "duplicate_check_scope": "current_run",
        "payload_safety": {"allow_generated_payloads": True},
    }
    dup = checker()
    first = service.prepare(
        endpoint=endpoint, run_context=run_context(), iteration=1, duplicate_checker=dup
    )
    second = service.prepare(
        endpoint=endpoint, run_context=run_context(), iteration=1, duplicate_checker=dup
    )
    assert first.metadata["duplicate_allowed"] is False
    assert second.metadata["duplicate_detected"] is True
    assert second.metadata["duplicate_allowed"] is True


def test_payload_preparation_fail_fast_duplicate_error_carries_safe_metadata() -> None:
    service = PayloadPreparationService()
    endpoint = {
        "endpoint_id": "ep1",
        "payload_strategy": "generated",
        "payload_template": {"id": "fixed"},
        "duplicate_policy": "fail_fast",
        "duplicate_check_scope": "current_run",
        "payload_safety": {"allow_generated_payloads": True},
    }
    dup = checker()
    service.prepare(
        endpoint=endpoint, run_context=run_context(), iteration=1, duplicate_checker=dup
    )

    with pytest.raises(PayloadValidationError) as exc_info:
        service.prepare(
            endpoint=endpoint, run_context=run_context(), iteration=1, duplicate_checker=dup
        )

    assert exc_info.value.payload_metadata is not None
    assert exc_info.value.payload_metadata["duplicate_detected"] is True
    assert exc_info.value.payload_metadata["duplicate_policy"] == "fail_fast"
    assert exc_info.value.payload_metadata["duplicate_allowed"] is False


def test_static_get_no_body_bypasses_payload_duplicate_reservation() -> None:
    service = PayloadPreparationService()
    dup = checker()

    first = service.prepare(
        endpoint=static_endpoint(endpoint_id="health_fast"),
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )
    second = service.prepare(
        endpoint=static_endpoint(endpoint_id="health_slow"),
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    assert first.payload is None
    assert second.payload is None
    assert first.payload_fingerprint == hashlib.sha256(b"EMPTY_PAYLOAD").hexdigest()
    assert second.payload_fingerprint == first.payload_fingerprint
    assert first.metadata["duplicate_detected"] is False
    assert second.metadata["duplicate_detected"] is False
    assert first.metadata["duplicate_check_scope"] == "not_applicable"
    assert second.metadata["duplicate_check_scope"] == "not_applicable"


def test_static_head_no_body_bypasses_payload_duplicate_reservation() -> None:
    service = PayloadPreparationService()
    dup = checker()

    first = service.prepare(
        endpoint=static_endpoint(endpoint_id="head_one", method="HEAD"),
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )
    second = service.prepare(
        endpoint=static_endpoint(endpoint_id="head_two", method="HEAD"),
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    assert first.metadata["duplicate_detected"] is False
    assert second.metadata["duplicate_detected"] is False
    assert second.metadata["duplicate_check_scope"] == "not_applicable"


@pytest.mark.parametrize("payload", [{}, ""])
def test_static_get_explicit_empty_body_does_not_bypass_duplicate_check(payload) -> None:
    service = PayloadPreparationService()
    dup = checker()
    endpoint = static_endpoint(payload=payload)
    service.prepare(
        endpoint=endpoint,
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    with pytest.raises(PayloadValidationError) as exc_info:
        service.prepare(
            endpoint=endpoint,
            run_context=run_context(),
            iteration=1,
            duplicate_checker=dup,
        )

    assert exc_info.value.payload_metadata is not None
    assert exc_info.value.payload_metadata["duplicate_detected"] is True
    assert exc_info.value.payload_metadata["duplicate_check_scope"] == "current_run"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_static_no_body_side_effect_methods_do_not_bypass_duplicate_check(method) -> None:
    service = PayloadPreparationService()
    dup = checker()
    endpoint = static_endpoint(method=method)
    service.prepare(
        endpoint=endpoint,
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    with pytest.raises(PayloadValidationError) as exc_info:
        service.prepare(
            endpoint=endpoint,
            run_context=run_context(),
            iteration=1,
            duplicate_checker=dup,
        )

    assert exc_info.value.payload_metadata is not None
    assert exc_info.value.payload_metadata["duplicate_detected"] is True
    assert exc_info.value.payload_metadata["duplicate_check_scope"] == "current_run"


def test_generated_regenerate_duplicate_behavior_unchanged() -> None:
    service = PayloadPreparationService()
    endpoint = {
        "endpoint_id": "generated-regenerate",
        "method": "POST",
        "payload_strategy": "generated",
        "payload_template": {"id": "fixed"},
        "duplicate_policy": "regenerate",
        "duplicate_check_scope": "current_run",
        "payload_safety": {"allow_generated_payloads": True},
    }
    dup = checker()
    service.prepare(
        endpoint=endpoint,
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    with pytest.raises(PayloadValidationError) as exc_info:
        service.prepare(
            endpoint=endpoint,
            run_context=run_context(),
            iteration=1,
            duplicate_checker=dup,
        )

    assert "regeneration exhausted" in str(exc_info.value)
    assert exc_info.value.payload_metadata is not None
    assert exc_info.value.payload_metadata["generation_attempt"] == 5
    assert exc_info.value.payload_metadata["duplicate_detected"] is True


def test_data_pool_duplicate_prevention_unchanged() -> None:
    service = PayloadPreparationService(data_pool_loader=Loader())
    endpoint = {
        "endpoint_id": "pool",
        "method": "POST",
        "payload_strategy": "data_pool",
        "data_pool_name": "users",
        "duplicate_policy": "fail_fast",
        "duplicate_check_scope": "current_run",
        "payload_safety": {},
    }
    dup = checker()
    service.prepare(
        endpoint=endpoint,
        run_context=run_context(),
        iteration=1,
        duplicate_checker=dup,
    )

    with pytest.raises(PayloadValidationError) as exc_info:
        service.prepare(
            endpoint=endpoint,
            run_context=run_context(),
            iteration=1,
            duplicate_checker=dup,
        )

    assert exc_info.value.payload_metadata is not None
    assert exc_info.value.payload_metadata["duplicate_detected"] is True
    assert exc_info.value.payload_metadata["data_pool_record_fingerprint"] is not None
