"""Deterministic hashing, delay resolution, and sleep helpers."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SlowDelayDecision:
    delay_ms: int
    delay_source: str


def stable_hash(value: str) -> int:
    """Return a process-stable SHA-256 integer hash for any string value."""
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)


def time_window_seed(prefix: str, window_seconds: int = 60) -> str:
    """Return deterministic bucket seed for manual no-seed exploration."""
    bucket = int(time.time() // window_seconds)
    return f"{prefix}:{bucket}"


def resolve_slow_delay_ms(query_params: dict[str, str | None]) -> SlowDelayDecision:
    delay_value = query_params.get("delay_ms")
    if delay_value is not None and delay_value.isdigit():
        parsed = int(delay_value, 10)
        if 800 <= parsed <= 1500:
            return SlowDelayDecision(delay_ms=parsed, delay_source="query")

    if "seed" in query_params:
        seed = query_params.get("seed") or ""
        return SlowDelayDecision(delay_ms=800 + (stable_hash(seed) % 701), delay_source="seed")

    return SlowDelayDecision(delay_ms=1000, delay_source="default")


def sleep_seconds(seconds: float) -> None:
    """Small wrapper around sleep to allow monkeypatching in tests."""
    time.sleep(seconds)


def sleep_milliseconds(milliseconds: int) -> None:
    sleep_seconds(milliseconds / 1000.0)
