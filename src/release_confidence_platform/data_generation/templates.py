"""Deterministic Phase 2 payload template resolver."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

TOKEN_PATTERN = re.compile(r"{{([^{}]+)}}")
RESERVED_TOKENS = {"run_id", "iteration", "timestamp", "uuid"}
PROJECT_NAMESPACE = uuid.UUID("2dd44ab8-16f2-5ac9-a8ed-b2173f2b9632")


class TemplateResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateContext:
    client_id: str
    audit_id: str
    run_id: str
    endpoint_id: str
    iteration: int
    run_timestamp: str
    generation_attempt: int = 1
    data_pool_record: dict[str, Any] | None = None


def deterministic_uuid(context: TemplateContext, field_path: str, token_index: int) -> str:
    seed = (
        "phase2.uuid.v1|"
        f"{context.client_id}|{context.audit_id}|{context.run_id}|{context.endpoint_id}|"
        f"{context.iteration}|{field_path}|token_index={token_index}|"
        f"attempt={context.generation_attempt}"
    )
    return str(uuid.uuid5(PROJECT_NAMESPACE, seed))


def contains_template_token(value: Any) -> bool:
    if isinstance(value, str):
        return "{{" in value or "}}" in value
    if isinstance(value, dict):
        return any(contains_template_token(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_template_token(item) for item in value)
    return False


def render_template(
    value: Any, context: TemplateContext, *, allow_data_pool_tokens: bool = False
) -> Any:
    return _render(value, context, "$", allow_data_pool_tokens=allow_data_pool_tokens)


def _render(
    value: Any, context: TemplateContext, path: str, *, allow_data_pool_tokens: bool
) -> Any:
    if isinstance(value, dict):
        return {
            key: _render(
                item,
                context,
                _child_path(path, key),
                allow_data_pool_tokens=allow_data_pool_tokens,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _render(
                item,
                context,
                f"{path}[{index}]",
                allow_data_pool_tokens=allow_data_pool_tokens,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        return _render_string(value, context, path, allow_data_pool_tokens=allow_data_pool_tokens)
    return value


def _render_string(
    value: str, context: TemplateContext, path: str, *, allow_data_pool_tokens: bool
) -> str:
    if ("{{" in value or "}}" in value) and not _balanced_tokens(value):
        raise TemplateResolutionError("Malformed template token")
    uuid_index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal uuid_index
        token = match.group(1)
        if token != token.strip() or not token:
            raise TemplateResolutionError("Malformed template token")
        if token == "run_id":
            return context.run_id
        if token == "iteration":
            return str(context.iteration)
        if token == "timestamp":
            return context.run_timestamp
        if token == "uuid":
            rendered = deterministic_uuid(context, path, uuid_index)
            uuid_index += 1
            return rendered
        if allow_data_pool_tokens:
            return str(_lookup_data_pool_token(context.data_pool_record, token))
        raise TemplateResolutionError(f"Unknown template token: {token}")

    return TOKEN_PATTERN.sub(replace, value)


def _balanced_tokens(value: str) -> bool:
    stripped = TOKEN_PATTERN.sub("", value)
    return "{" not in stripped and "}" not in stripped


def _lookup_data_pool_token(record: dict[str, Any] | None, token: str) -> Any:
    if token in RESERVED_TOKENS:
        raise TemplateResolutionError(f"Reserved token cannot be data-pool field: {token}")
    if record is None or not isinstance(record, dict):
        raise TemplateResolutionError("Data-pool record is not available")
    current: Any = record
    for part in token.split("."):
        if not part or not isinstance(current, dict) or part not in current:
            raise TemplateResolutionError(f"Missing data-pool field: {token}")
        current = current[part]
    if isinstance(current, dict | list):
        raise TemplateResolutionError(f"Data-pool field is not scalar: {token}")
    return current


def _child_path(parent: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", str(key)):
        return f"{parent}.{key}"
    escaped = str(key).replace("\\", "\\\\").replace("'", "\\'")
    return f"{parent}['{escaped}']"
