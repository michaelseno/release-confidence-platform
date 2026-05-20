"""Deterministic response body builders for the mock target API."""

from __future__ import annotations

from typing import Any

SERVICE_NAME = "mock-target-api"


def build_fast_response() -> dict[str, Any]:
    return {"service": SERVICE_NAME, "endpoint": "fast", "status": "healthy"}


def build_slow_response(delay_ms: int, delay_source: str) -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "endpoint": "slow",
        "status": "healthy",
        "delay_ms": delay_ms,
        "delay_source": delay_source,
    }


def build_flaky_response(status: str, seed_source: str, hash_mod: int) -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "endpoint": "flaky",
        "status": status,
        "seed_source": seed_source,
        "hash_mod": hash_mod,
    }


def build_inconsistent_response(variant: str) -> dict[str, Any]:
    if variant == "A":
        return {
            "service": SERVICE_NAME,
            "endpoint": "inconsistent",
            "status": "healthy",
            "version": "A",
        }
    return {
        "service": SERVICE_NAME,
        "endpoint": "inconsistent",
        "status": "healthy",
        "metadata": {"variant": "B"},
    }


def build_timeout_response(delay_seconds: int, timeout_mode: str) -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "endpoint": "timeout",
        "status": "healthy",
        "delay_seconds": delay_seconds,
        "timeout_mode": timeout_mode,
    }
