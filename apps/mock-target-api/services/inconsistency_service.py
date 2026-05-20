"""Deterministic inconsistent response variant selection."""

from __future__ import annotations

from dataclasses import dataclass

from utils.deterministic_delay import stable_hash, time_window_seed


@dataclass(frozen=True)
class VariantDecision:
    variant: str
    variant_source: str


def resolve_variant(
    query_params: dict[str, str | None], headers: dict[str, str]
) -> VariantDecision:  # noqa: ARG001
    forced = query_params.get("variant")
    if forced in {"A", "B"}:
        return VariantDecision(variant=forced, variant_source="query")

    if "seed" in query_params:
        seed = query_params.get("seed") or ""
        return VariantDecision(
            variant="A" if stable_hash(seed) % 2 == 0 else "B",
            variant_source="seed",
        )

    fallback_seed = time_window_seed("inconsistent")
    return VariantDecision(
        variant="A" if stable_hash(fallback_seed) % 2 == 0 else "B",
        variant_source="time_window",
    )
