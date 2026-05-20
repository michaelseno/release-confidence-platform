"""Deterministic timeout endpoint delay selection."""

from __future__ import annotations

import os
from dataclasses import dataclass

from utils.deterministic_delay import stable_hash


@dataclass(frozen=True)
class TimeoutDecision:
    delay_seconds: int
    timeout_mode: str


def resolve_timeout_delay_seconds() -> TimeoutDecision:
    short_mode = os.environ.get("MOCK_TARGET_SHORT_TIMEOUT") == "true"
    if short_mode:
        return TimeoutDecision(
            delay_seconds=2 + (stable_hash("timeout:short") % 2),
            timeout_mode="short",
        )
    return TimeoutDecision(
        delay_seconds=35 + (stable_hash("timeout:default") % 11),
        timeout_mode="default",
    )
