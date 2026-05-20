"""Deterministic flaky endpoint behavior."""

from __future__ import annotations

from dataclasses import dataclass

from utils.deterministic_delay import stable_hash, time_window_seed


@dataclass(frozen=True)
class FlakyDecision:
    seed: str
    seed_source: str
    hash_mod: int
    http_status: int
    status: str


def resolve_seed(query_params: dict[str, str | None], headers: dict[str, str]) -> tuple[str, str]:
    if "seed" in query_params:
        return query_params.get("seed") or "", "query"
    if "x-rcp-seed" in headers:
        return headers["x-rcp-seed"], "header"
    return time_window_seed("flaky"), "time_window"


def evaluate_flaky_status(seed: str, seed_source: str) -> FlakyDecision:
    hash_mod = stable_hash(seed) % 5
    degraded = hash_mod == 0
    return FlakyDecision(
        seed=seed,
        seed_source=seed_source,
        hash_mod=hash_mod,
        http_status=500 if degraded else 200,
        status="degraded" if degraded else "healthy",
    )
