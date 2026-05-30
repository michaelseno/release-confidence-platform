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
        if result.command == "config init" and result.status == "success":
            return json.dumps(_config_init_json_payload(payload), sort_keys=True)
        return json.dumps(payload, sort_keys=True)
    label = (
        "DRY-RUN"
        if result.status == "dry_run"
        else "WARNING"
        if result.exit_code == 3
        else "FAILED"
        if result.exit_code != 0 or result.status == "failed"
        else "SUCCESS"
    )
    lines = [f"{label}: {result.command}"]
    if result.stage:
        lines.append(f"stage: {result.stage}")
    for key in (
        "client_id",
        "audit_id",
        "defaults_profile",
        "defaults_source",
        "target_environment",
        "output_dir",
        "lifecycle_state",
    ):
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
        return _render_config_init_text(result, payload)
    if result.command == "config stage-info":
        return _render_config_stage_info_text(result, payload)
    if result.command == "audit run" and (result.exit_code != 0 or result.status == "failed"):
        _append_audit_run_failure_details(lines, payload)
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
    elif result.command == "audit run" and (result.exit_code != 0 or result.status == "failed"):
        lines.append(f"next_step: {_audit_run_failure_next_step(payload, result.stage)}")
    else:
        lines.append("next_step: none")
    return "\n".join(lines)


def _render_config_init_text(result: CommandResult, payload: dict[str, Any]) -> str:
    profile = payload.get("profile") or {}
    effective_settings = payload.get("effective_settings") or {}
    safety = payload.get("safety") or {}
    warnings = payload.get("warnings") or []
    next_steps = payload.get("next_steps") or []
    source_label = "custom profile path" if profile.get("source") == "path" else "named profile"
    lines = ["SUCCESS: Local config workspace generated.", ""]
    lines.extend(
        [
            "Identifiers",
            f"  client_id: {payload.get('client_id')}",
            f"  audit_id:  {payload.get('audit_id')}",
            "",
            "Defaults profile",
            f"  source: {source_label}",
            f"  name:   {profile.get('name') or payload.get('defaults_profile')}",
        ]
    )
    if profile.get("source") == "path" and profile.get("path"):
        lines.append(f"  path:   {profile['path']}")
    lines.extend(
        [
            "  target_environment: "
            f"{profile.get('target_environment') or payload.get('target_environment')}",
            "",
            "Effective settings",
            "  workspace_root: "
            f"{effective_settings.get('workspace_root') or payload.get('output_dir')}",
            f"  timezone:       {effective_settings.get('timezone')}",
            "  endpoints:      "
            + (
                "safe mock sample endpoints"
                if effective_settings.get("include_sample_endpoints")
                else "empty endpoints array"
            ),
            f"  overwrite:      {str(bool(effective_settings.get('overwrite'))).lower()}",
            "",
            "Resolution order",
            "  1. explicit CLI arguments",
            "  2. profile operator_defaults",
            "  3. safe fallback values",
            "",
            "Generated files",
        ]
    )
    for file_info in payload.get("generated_files", []):
        lines.append(f"  {file_info.get('path') or file_info.get('file_name')}")
    lines.extend(
        [
            "",
            "Safety",
            "  Local files only. No AWS calls were made. No configs were uploaded.",
            "  No schedules, metadata records, or production execution were created.",
        ]
    )
    if safety.get("allow_production_execution") is False and _has_production_warning(warnings):
        lines.extend(
            [
                "",
                "WARNING: Production target defaults selected.",
                "  Generated configs remain local and non-executable by default.",
                "  allow_production_execution=false",
                "  allow_destructive_operation=false",
                "  No real endpoints were generated.",
                "  Separate approval and validation are required before any production "
                "execution workflow.",
            ]
        )
    for warning in warnings:
        if warning.get("code") == "OUTPUT_WORKSPACE_OVERWRITTEN":
            lines.extend(
                [
                    "",
                    "WARNING: Existing workspace was overwritten.",
                    f"  overwritten_path: {warning.get('path')}",
                ]
            )
    if payload.get("warning"):
        lines.extend(["", f"WARNING: {payload['warning']}"])
    lines.extend(["", "Next steps"])
    for index, step in enumerate(next_steps, start=1):
        lines.append(f"  {index}. {step}")
    return "\n".join(lines)


def _render_config_stage_info_text(result: CommandResult, payload: dict[str, Any]) -> str:
    lines = ["SUCCESS: config stage-info"]
    for key in (
        "stage",
        "region",
        "aws_profile",
        "config_bucket",
        "audit_metadata_table",
        "orchestrator_function_name",
        "scheduler_group",
        "scheduler_group_name",
        "schedule_name_prefix",
        "scheduler_execution_target_arn",
        "scheduler_finalization_target_arn",
        "scheduler_role_arn",
    ):
        if payload.get(key) is not None:
            lines.append(f"{key}: {payload[key]}")
    lines.extend(
        [
            f"summary: {result.summary}",
            f"live_aws_check: {str(bool(payload.get('live_aws_check'))).lower()}",
            "source_guidance:",
        ]
    )
    for item in payload.get("source_guidance", []):
        lines.append(f"  - {item}")
    lines.append(
        "next_step: export required RCP_* overrides, then rerun rcp config stage-info "
        "and rcp audit create or rcp audit run from the same shell"
    )
    return "\n".join(lines)


def _config_init_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get("generated_files", [])
    files_by_type = {item.get("type"): item.get("path") for item in files if isinstance(item, dict)}
    return {
        "status": payload.get("status"),
        "command": payload.get("command"),
        "client_id": payload.get("client_id"),
        "audit_id": payload.get("audit_id"),
        "profile": payload.get("profile") or {},
        "effective_settings": payload.get("effective_settings") or {},
        "resolution_order": payload.get("resolution_order") or [],
        "generated_files": {
            "client_config": files_by_type.get("client"),
            "audit_config": files_by_type.get("audit"),
            "endpoints": files_by_type.get("endpoints"),
        },
        "safety": payload.get("safety") or {},
        "warnings": payload.get("warnings") or [],
        "next_steps": payload.get("next_steps") or [],
    }


def _has_production_warning(warnings: list[dict[str, Any]]) -> bool:
    return any(warning.get("code") == "PRODUCTION_TARGET_SAFE_LOCAL_ONLY" for warning in warnings)


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


def _append_audit_run_failure_details(lines: list[str], payload: dict[str, Any]) -> None:
    for key in ("run_id", "scenario_type", "handler_status", "error_code", "failure_type"):
        if payload.get(key) is not None:
            lines.append(f"{key}: {payload[key]}")
    if payload.get("failure_message") is not None:
        lines.append(f"failure_message: {payload['failure_message']}")


def _audit_run_failure_next_step(payload: dict[str, Any], stage: str | None) -> str:
    explicit_next_step = payload.get("next_step")
    if explicit_next_step:
        return str(explicit_next_step)
    error_code = payload.get("error_code") or payload.get("failure_type")
    run_id = payload.get("run_id") or "<run_id>"
    stage_name = stage or payload.get("stage") or "<stage>"
    if error_code in {"CONFIG_LOAD_ERROR", "CONFIG_VALIDATION_ERROR"}:
        return (
            "review the reported config object or validation message, run the same command with "
            f"--output json for structured invocation details, and inspect CloudWatch logs for "
            f"stage {stage_name} run_id {run_id} if the config issue is not clear"
        )
    if error_code in {"ORCHESTRATION_ERROR", None}:
        return (
            "rerun with --output json to inspect sanitized handler_response, then inspect "
            f"CloudWatch orchestrator logs for stage {stage_name} run_id {run_id}"
        )
    return (
        f"address {error_code}, rerun with --output json for structured invocation details, "
        f"and inspect CloudWatch orchestrator logs for stage {stage_name} run_id {run_id}"
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
            f"next_step: {_error_next_step(payload['code'], payload['message'], stage)}",
        ]
    )
    return "\n".join(lines)


def _error_next_step(code: str, message: str, stage: str | None) -> str:
    if code == "INVALID_LIFECYCLE_STATE":
        stage_name = stage or "<stage>"
        return (
            "scheduling is only valid when audit lifecycle_state is DRAFT; inspect current "
            f"metadata with rcp audit list --client-id <client_id> --stage {stage_name} "
            "--output json, then use a fresh audit ID/config bundle as the safest recovery. "
            "Use audit create --force only when existing metadata is DRAFT or FAILED and you "
            "have confirmed there are no active orphaned schedules. Do not manually mutate "
            "lifecycle metadata except during controlled dev/test remediation."
        )
    if code == "AWS_PROFILE_ERROR":
        stage_name = stage or "<stage>"
        return (
            f"check config/stages/{stage_name}.json aws_profile or set "
            "RCP_AWS_PROFILE to a loadable AWS profile, then retry"
        )
    if code in {
        "SCHEDULER_CONFIG_ERROR",
        "SCHEDULE_CONFIG_ERROR",
        "SCHEDULE_PERMISSION_ERROR",
        "SCHEDULE_REQUEST_VALIDATION_ERROR",
        "SCHEDULE_PROVIDER_ERROR",
        "SCHEDULE_CREATE_FAILED",
    }:
        stage_name = stage or "<stage>"
        return (
            f"run rcp config stage-info --stage {stage_name} --output text and verify "
            "scheduler_group_name, scheduler_execution_target_arn, "
            "scheduler_finalization_target_arn, and scheduler_role_arn; export "
            "RCP_SCHEDULER_GROUP_NAME, RCP_SCHEDULER_EXECUTION_TARGET_ARN, "
            "RCP_SCHEDULER_FINALIZATION_TARGET_ARN, and RCP_SCHEDULER_ROLE_ARN from deployed "
            "scheduler outputs, then verify EventBridge Scheduler permissions and retry"
        )
    if code in {"STORAGE_CONFIG_ERROR", "STORAGE_PERMISSION_ERROR"} or (
        code == "STORAGE_ERROR" and "S3 config" in message
    ):
        stage_name = stage or "<stage>"
        return (
            f"check config/stages/{stage_name}.json config_bucket or set "
            "export RCP_CONFIG_BUCKET=<real-dev-bucket>; exported RCP_* overrides must be visible "
            "to the rcp subprocess, not just assigned as shell-local variables. Also export "
            "RCP_AUDIT_METADATA_TABLE=<real-metadata-table>, RCP_AWS_PROFILE=<aws-profile>, and "
            "RCP_AWS_REGION=<aws-region>; confirm the bucket exists in the configured region and "
            "the selected AWS profile has s3:PutObject and s3:HeadObject permissions for the "
            "configs/<client_id>/* prefix plus DynamoDB metadata permissions "
            "dynamodb:GetItem, dynamodb:PutItem, dynamodb:UpdateItem, dynamodb:Query, and "
            "dynamodb:Scan on the audit metadata table"
        )
    if code in {
        "LAMBDA_CONFIG_ERROR",
        "LAMBDA_PERMISSION_ERROR",
        "LAMBDA_INVOCATION_FAILED",
        "LAMBDA_DEPENDENCY_IMPORT_ERROR",
        "LAMBDA_RUNTIME_ERROR",
    }:
        stage_name = stage or "<stage>"
        permission_hint = (
            " verify aws lambda get-function and lambda:InvokeFunction permissions "
            "for the selected AWS profile/region"
        )
        if code == "LAMBDA_CONFIG_ERROR":
            return (
                f"check config/stages/{stage_name}.json orchestrator_function_name or export "
                "RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>; verify aws lambda "
                "get-function for the selected AWS profile/region"
            )
        if code == "LAMBDA_PERMISSION_ERROR":
            return (
                f"check config/stages/{stage_name}.json orchestrator_function_name or export "
                "RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>;" + permission_hint
            )
        if code == "LAMBDA_DEPENDENCY_IMPORT_ERROR":
            return (
                "redeploy the backend Lambda package with "
                "apps/backend/requirements.txt dependencies; async Lambda invocation "
                "may report acceptance before runtime import failures appear, "
                "so confirm CloudWatch no longer shows Runtime.ImportModuleError after deploy"
            )
        if code == "LAMBDA_RUNTIME_ERROR":
            return (
                "inspect sanitized Lambda invoke diagnostics and CloudWatch logs for "
                "the orchestrator; "
                "async Lambda invocation may report acceptance before runtime failures appear"
            )
        return (
            f"check config/stages/{stage_name}.json orchestrator_function_name or export "
            "RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name>; verify aws lambda "
            "get-function and Lambda invoke permissions for the selected AWS profile/region"
        )
    if code == "CONFIG_OBJECT_EXISTS":
        return (
            "an expected config object already exists; check whether matching audit "
            "metadata exists. "
            "Use --force only for existing DRAFT/FAILED metadata, or choose a new bundle/new IDs, "
            "or delete exact stale config objects only after confirming metadata is absent"
        )
    if code == "PARTIAL_AUDIT_CREATE_EXISTS":
        return (
            "partial audit create state detected; inspect artifact diagnostics in "
            "the message. "
            "Retry with a new bundle/new IDs, delete only the exact stale config objects after "
            "confirming metadata is absent, or use --force only when metadata "
            "exists in DRAFT/FAILED"
        )
    return "correct the error and retry"
