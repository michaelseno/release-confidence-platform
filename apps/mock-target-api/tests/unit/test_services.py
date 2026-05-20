from __future__ import annotations

import hashlib

from services.flaky_service import evaluate_flaky_status, resolve_seed
from services.inconsistency_service import resolve_variant
from services.timeout_service import resolve_timeout_delay_seconds
from utils.deterministic_delay import resolve_slow_delay_ms, stable_hash


def test_stable_hash_uses_sha256_integer() -> None:
    expected = int(hashlib.sha256(b"abc").hexdigest(), 16)
    assert stable_hash("abc") == expected
    assert stable_hash("") == stable_hash("")


def test_slow_delay_resolution_boundaries_and_fallbacks() -> None:
    assert resolve_slow_delay_ms({"delay_ms": "800"}).delay_ms == 800
    assert resolve_slow_delay_ms({"delay_ms": "1500"}).delay_ms == 1500

    seed_fallback = resolve_slow_delay_ms({"delay_ms": "799", "seed": "abc"})
    assert seed_fallback.delay_ms == 1234
    assert seed_fallback.delay_source == "seed"

    default = resolve_slow_delay_ms({})
    assert default.delay_ms == 1000
    assert default.delay_source == "default"


def test_flaky_seed_precedence_and_decision() -> None:
    seed, source = resolve_seed({"seed": "seed-0"}, {"x-rcp-seed": "seed-4"})
    assert (seed, source) == ("seed-0", "query")
    assert evaluate_flaky_status(seed, source).http_status == 200

    seed, source = resolve_seed({}, {"x-rcp-seed": "seed-4"})
    failure = evaluate_flaky_status(seed, source)
    assert failure.http_status == 500
    assert failure.status == "degraded"
    assert failure.hash_mod == 0


def test_empty_seed_is_deterministic() -> None:
    seed, source = resolve_seed({"seed": ""}, {})
    decision = evaluate_flaky_status(seed, source)
    assert decision.hash_mod == 4
    assert decision.http_status == 200


def test_inconsistent_forced_and_seed_variants() -> None:
    assert resolve_variant({"variant": "A"}, {}).variant == "A"
    assert resolve_variant({"variant": "B"}, {}).variant == "B"
    assert resolve_variant({"seed": "seed-3"}, {}).variant == "A"
    assert resolve_variant({"seed": "seed-0"}, {}).variant == "B"
    invalid = resolve_variant({"variant": "C", "seed": "seed-3"}, {})
    assert invalid.variant == "A"
    assert invalid.variant_source == "seed"


def test_timeout_resolution_default_and_short(monkeypatch) -> None:
    monkeypatch.delenv("MOCK_TARGET_SHORT_TIMEOUT", raising=False)
    default = resolve_timeout_delay_seconds()
    assert default.timeout_mode == "default"
    assert 35 <= default.delay_seconds <= 45

    monkeypatch.setenv("MOCK_TARGET_SHORT_TIMEOUT", "true")
    short = resolve_timeout_delay_seconds()
    assert short.timeout_mode == "short"
    assert 2 <= short.delay_seconds <= 3
