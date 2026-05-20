from __future__ import annotations

import json

import pytest
from handlers import (
    health_fast,
    health_flaky,
    health_inconsistent,
    health_slow,
    health_timeout,
)


def body(response: dict) -> dict:
    return json.loads(response["body"])


def test_fast_handler_returns_stable_response(http_event) -> None:
    response = health_fast.handler(http_event("/health/fast"), None)
    assert response["statusCode"] == 200
    assert body(response) == {"service": "mock-target-api", "endpoint": "fast", "status": "healthy"}
    assert response["headers"]["Cache-Control"] == "no-store"


def test_slow_handler_uses_sleep_wrapper(monkeypatch, http_event) -> None:
    calls: list[int] = []
    monkeypatch.setattr("utils.deterministic_delay.sleep_milliseconds", calls.append)
    response = health_slow.handler(http_event("/health/slow", {"delay_ms": "800"}), None)
    assert calls == [800]
    assert response["statusCode"] == 200
    assert body(response)["delay_ms"] == 800
    assert body(response)["delay_source"] == "query"


@pytest.mark.parametrize(
    ("query", "headers", "expected_status", "expected_health"),
    [
        ({"seed": "seed-4"}, {}, 500, "degraded"),
        ({"seed": "seed-0"}, {}, 200, "healthy"),
        ({"seed": "seed-0"}, {"X-RCP-Seed": "seed-4"}, 200, "healthy"),
        ({}, {"X-RCP-Seed": "seed-4"}, 500, "degraded"),
    ],
)
def test_flaky_handler_deterministic(
    query, headers, expected_status, expected_health, http_event
) -> None:
    response = health_flaky.handler(http_event("/health/flaky", query, headers), None)
    payload = body(response)
    assert response["statusCode"] == expected_status
    assert payload["service"] == "mock-target-api"
    assert payload["endpoint"] == "flaky"
    assert payload["status"] == expected_health


def test_inconsistent_handler_variants(http_event) -> None:
    variant_a = body(
        health_inconsistent.handler(http_event("/health/inconsistent", {"variant": "A"}), None)
    )
    assert variant_a["version"] == "A"
    assert "metadata" not in variant_a

    variant_b = body(
        health_inconsistent.handler(http_event("/health/inconsistent", {"variant": "B"}), None)
    )
    assert variant_b["metadata"]["variant"] == "B"
    assert "version" not in variant_b


def test_timeout_handler_monkeypatched_sleep(monkeypatch, http_event) -> None:
    calls: list[int] = []
    monkeypatch.delenv("MOCK_TARGET_SHORT_TIMEOUT", raising=False)
    monkeypatch.setattr("utils.deterministic_delay.sleep_seconds", calls.append)
    response = health_timeout.handler(http_event("/health/timeout"), None)
    payload = body(response)
    assert response["statusCode"] == 200
    assert payload["endpoint"] == "timeout"
    assert payload["timeout_mode"] == "default"
    assert 35 <= calls[0] <= 45


def test_timeout_handler_short_mode(monkeypatch, http_event) -> None:
    calls: list[int] = []
    monkeypatch.setenv("MOCK_TARGET_SHORT_TIMEOUT", "true")
    monkeypatch.setattr("utils.deterministic_delay.sleep_seconds", calls.append)
    response = health_timeout.handler(http_event("/health/timeout"), None)
    payload = body(response)
    assert response["statusCode"] == 200
    assert payload["timeout_mode"] == "short"
    assert 2 <= calls[0] <= 3


def test_unexpected_exception_returns_sanitized_error(monkeypatch, http_event) -> None:
    def fail():
        raise RuntimeError("boom")

    monkeypatch.setattr(health_fast, "build_fast_response", fail)
    response = health_fast.handler(http_event("/health/fast"), None)
    payload = body(response)
    assert response["statusCode"] == 500
    assert payload == {
        "service": "mock-target-api",
        "endpoint": "fast",
        "status": "error",
        "error": "internal_error",
    }
