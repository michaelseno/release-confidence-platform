"""CLI result and rendering helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from release_confidence_platform.sanitization.sanitizer import sanitize


@dataclass(frozen=True)
class CommandResult:
    command: str
    stage: str | None
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0


def render(result: CommandResult, *, output: str = "text") -> str:
    payload = sanitize(
        {
            "command": result.command,
            "stage": result.stage,
            "status": result.status,
            "summary": result.summary,
            **result.data,
        }
    )
    if output == "json":
        return json.dumps(payload, sort_keys=True)
    label = (
        "DRY-RUN"
        if result.status == "dry_run"
        else "WARNING"
        if result.exit_code == 3
        else "SUCCESS"
    )
    lines = [f"{label}: {result.command}"]
    if result.stage:
        lines.append(f"stage: {result.stage}")
    for key in ("client_id", "audit_id", "lifecycle_state"):
        if payload.get(key) is not None:
            lines.append(f"{key}: {payload[key]}")
    lines.append(f"summary: {result.summary}")
    actions = (
        payload.get("planned_actions")
        or payload.get("planned_schedules")
        or payload.get("schedules")
        or payload.get("cleanup_results")
    )
    if actions:
        lines.append("actions:")
        for action in actions:
            lines.append(f"  - {action}")
    if result.exit_code == 3:
        lines.append("next_step: review cleanup_errors and reconcile schedules manually")
    elif result.status == "dry_run":
        lines.append("next_step: rerun without --dry-run to apply these actions")
    else:
        lines.append("next_step: none")
    return "\n".join(lines)


def render_error(
    command: str, stage: str | None, code: str, message: str, *, output: str = "text"
) -> str:
    payload = sanitize({"command": command, "stage": stage, "code": code, "message": message})
    if output == "json":
        return json.dumps({"status": "error", **payload}, sort_keys=True)
    lines = [f"ERROR: {command} failed"]
    if stage:
        lines.append(f"stage: {stage}")
    lines.extend(
        [
            f"code: {payload['code']}",
            f"message: {payload['message']}",
            "next_step: correct the error and retry",
        ]
    )
    return "\n".join(lines)
