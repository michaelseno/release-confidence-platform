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
    for key in ("client_id", "audit_id", "output_dir", "lifecycle_state"):
        if payload.get(key) is not None:
            lines.append(f"{key}: {payload[key]}")
    lines.append(f"summary: {result.summary}")
    if payload.get("count") is not None:
        lines.append(f"count: {payload['count']}")
    if payload.get("truncated") is not None:
        lines.append(f"truncated: {str(payload['truncated']).lower()}")
    if result.command in {"client list", "audit list"}:
        _append_rows(lines, payload.get("items", []))
    if result.command == "config list":
        _append_config_keys(lines, payload.get("config_keys", []))
    if result.command == "config download":
        if payload.get("warning"):
            lines.append("")
            lines.append(f"WARNING: {payload['warning']}")
        files = payload.get("downloaded_files", [])
        if files:
            lines.append("")
            lines.append("files:")
            for file_info in files:
                lines.append(f"  - {file_info.get('file_name') or file_info.get('path')}")
    if result.command == "config init":
        lines.append(f"overwritten: {str(bool(payload.get('overwritten'))).lower()}")
        files = payload.get("generated_files", [])
        if files:
            lines.append("")
            lines.append("files:")
            for file_info in files:
                lines.append(f"  - {file_info.get('path') or file_info.get('file_name')}")
        if payload.get("warning"):
            lines.append("")
            lines.append(f"WARNING: {payload['warning']}")
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
    elif result.command == "config download":
        lines.append(
            "next_step: keep files under .local-configs/, do not commit them, "
            "and delete them when no longer needed"
        )
    elif result.command == "config init":
        lines.append(
            "next_step: run rcp audit validate with the generated file paths before onboarding; "
            "keep files under .local-configs/ and do not commit them"
        )
    else:
        lines.append("next_step: none")
    return "\n".join(lines)


def _append_rows(lines: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    lines.append("")
    keys = [
        "client_id",
        "audit_id",
        "lifecycle_state",
        "created_at",
        "updated_at",
        "active_audit_count",
    ]
    shown = [key for key in keys if any(key in row for row in rows)]
    lines.append("  ".join(shown))
    for row in rows:
        lines.append("  ".join(str(row.get(key, "-")) for key in shown))


def _append_config_keys(lines: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    lines.append("")
    lines.append("file_name  type  exists  size_bytes  last_modified  version_id")
    for row in rows:
        lines.append(
            "  ".join(
                str(row.get(key, "-"))
                for key in (
                    "file_name",
                    "type",
                    "exists",
                    "size_bytes",
                    "last_modified",
                    "version_id",
                )
            )
        )


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
