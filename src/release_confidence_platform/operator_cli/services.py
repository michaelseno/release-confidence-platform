"""Thin command-to-service adapters for the operator CLI."""

from __future__ import annotations

from argparse import Namespace

from release_confidence_platform.audit_lifecycle.cancellation import AuditCancellationService
from release_confidence_platform.audit_scheduling.service import AuditSchedulingService
from release_confidence_platform.config.audit_validation_service import AuditConfigValidationService
from release_confidence_platform.config.stage_config import StageConfigLoader
from release_confidence_platform.core.audit_creation_service import AuditCreationService
from release_confidence_platform.core.manual_run_service import ManualRunInvocationService
from release_confidence_platform.operator_cli.config_init import ConfigInitService
from release_confidence_platform.operator_cli.discovery_service import (
    ConfigDiscoveryService,
    DiscoveryListService,
)
from release_confidence_platform.operator_cli.result import CommandResult
from release_confidence_platform.storage.aws_client_factory import AwsClientFactory


class _DryRunS3:
    def object_exists(self, key: str) -> bool:
        return False

    def write_json(self, key: str, payload: dict, *, overwrite: bool = False) -> None:
        raise AssertionError("dry-run S3 write attempted")


class _DryRunRepository:
    def audit_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict:
        raise AssertionError("dry-run metadata read attempted")


def _stage(args: Namespace):
    return StageConfigLoader().load(args.stage)


def validate_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    result = AuditConfigValidationService().validate_files(
        client_config_path=args.client_config,
        audit_config_path=args.audit_config,
        endpoints_config_path=args.endpoints_config,
        stage=stage_config.stage,
    )
    return CommandResult(
        command="audit validate",
        stage=stage_config.stage,
        status="success",
        summary="validation passed; no mutations performed",
        data={"client_id": result.client_id, "audit_id": result.audit_id},
    )


def client_list_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = AwsClientFactory(stage_config)
    data = DiscoveryListService(factory.audit_metadata_repository()).list_clients(limit=args.limit)
    return CommandResult(
        command="client list",
        stage=stage_config.stage,
        status="success",
        summary="no clients found" if data["count"] == 0 else f"found {data['count']} clients",
        data=data,
    )


def audit_list_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = AwsClientFactory(stage_config)
    data = DiscoveryListService(factory.audit_metadata_repository()).list_audits(
        client_id=args.client_id, limit=args.limit
    )
    return CommandResult(
        command="audit list",
        stage=stage_config.stage,
        status="success",
        summary=(
            "no audits found for client" if data["count"] == 0 else f"found {data['count']} audits"
        ),
        data=data,
    )


def config_list_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = AwsClientFactory(stage_config)
    data = ConfigDiscoveryService(factory.s3_storage(), stage=stage_config.stage).list_config_keys(
        client_id=args.client_id, audit_id=args.audit_id
    )
    return CommandResult(
        command="config list",
        stage=stage_config.stage,
        status="success",
        summary=(
            "no config artifacts found"
            if data["count"] == 0
            else f"found {data['count']} config artifacts"
        ),
        data=data,
    )


def config_download_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = AwsClientFactory(stage_config)
    data = ConfigDiscoveryService(
        factory.s3_storage(), stage=stage_config.stage
    ).download_audit_config_set(
        client_id=args.client_id,
        audit_id=args.audit_id,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
    )
    return CommandResult(
        command="config download",
        stage=stage_config.stage,
        status="success",
        summary=(
            f"downloaded {data['count']} config files; existing local files were overwritten"
            if args.overwrite
            else f"downloaded {data['count']} config files"
        ),
        data=data,
    )


def config_stage_info_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    return CommandResult(
        command="config stage-info",
        stage=stage_config.stage,
        status="success",
        summary="resolved local stage configuration; no AWS calls performed",
        data={
            "stage": stage_config.stage,
            "region": stage_config.region,
            "aws_profile": stage_config.aws_profile,
            "config_bucket": stage_config.config_bucket,
            "audit_metadata_table": stage_config.audit_metadata_table,
            "orchestrator_function_name": stage_config.orchestrator_function_name,
            "scheduler_group": stage_config.scheduler_group_name,
            "scheduler_group_name": stage_config.scheduler_group_name,
            "schedule_name_prefix": stage_config.schedule_name_prefix,
            "scheduler_execution_target_arn": stage_config.scheduler_execution_target_arn,
            "scheduler_finalization_target_arn": stage_config.scheduler_finalization_target_arn,
            "scheduler_role_arn": stage_config.scheduler_role_arn,
            "live_aws_check": False,
            "source_guidance": [
                "Stage values are loaded from config/stages/<stage>.json and overridden "
                "only by exported RCP_* environment variables visible to the rcp subprocess.",
                "Use export RCP_CONFIG_BUCKET=... before running rcp audit create.",
                "Use export RCP_AUDIT_METADATA_TABLE=... before running rcp audit create.",
                "Use export RCP_AWS_PROFILE=... before running rcp audit create.",
                "Use export RCP_AWS_REGION=... before running rcp audit create.",
                "Use export RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name> before "
                "running rcp audit run.",
                "Use export RCP_SCHEDULER_GROUP_NAME=<deployed-scheduler-group> before "
                "running rcp audit schedule.",
                "Use export RCP_SCHEDULER_EXECUTION_TARGET_ARN=<scheduled-execution-lambda-arn> "
                "before running rcp audit schedule.",
                "Use export RCP_SCHEDULER_FINALIZATION_TARGET_ARN=<audit-finalization-lambda-arn> "
                "before running rcp audit schedule.",
                "Use export RCP_SCHEDULER_ROLE_ARN=<scheduler-invocation-role-arn> before "
                "running rcp audit schedule.",
                "Use export RCP_SCHEDULE_NAME_PREFIX=<schedule-name-prefix> only when the "
                "deployed scheduler naming prefix differs from config/stages/<stage>.json.",
                "Shell-local assignments that are not exported do not affect child rcp processes.",
            ],
        },
    )


def config_init_command(args: Namespace) -> CommandResult:
    data = ConfigInitService().init(
        client_name=args.client_name,
        defaults=args.defaults,
        output_dir=args.output_dir,
        timezone=args.timezone,
        output=args.output,
        include_sample_endpoints=args.include_sample_endpoints,
        overwrite=args.overwrite,
    )
    args.output = data.get("output_format")
    return CommandResult(
        command="config init",
        stage=None,
        status="success",
        summary="generated local starter config files; local only, no upload performed",
        data=data,
    )


def create_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    # Runtime config validation must happen before any AWS session/client setup so local
    # starter-template defects (for example empty generated endpoints) are reported as
    # actionable config validation errors instead of being masked by AWS profile issues.
    AuditConfigValidationService().validate_files(
        client_config_path=args.client_config,
        audit_config_path=args.audit_config,
        endpoints_config_path=args.endpoints_config,
        stage=stage_config.stage,
    )
    factory = None if args.dry_run else AwsClientFactory(stage_config)
    data = AuditCreationService(
        stage_config=stage_config,
        s3_storage=_DryRunS3() if args.dry_run else factory.s3_storage(),
        repository=_DryRunRepository() if args.dry_run else factory.audit_metadata_repository(),
    ).create_from_files(
        client_config_path=args.client_config,
        audit_config_path=args.audit_config,
        endpoints_config_path=args.endpoints_config,
        dry_run=args.dry_run,
        force=args.force,
    )
    return CommandResult(
        command="audit create",
        stage=stage_config.stage,
        status=data.get("status", "success"),
        summary="validation passed; no mutations performed"
        if args.dry_run
        else "audit draft created",
        data=data,
    )


def schedule_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    if not args.dry_run:
        stage_config.validate_scheduler_config()
    factory = AwsClientFactory(stage_config)
    data = AuditSchedulingService(
        repository=factory.audit_metadata_repository(),
        scheduler_client=factory.scheduler(),
        stage=stage_config.stage,
        schedule_name_prefix=stage_config.schedule_name_prefix,
    ).schedule_from_persisted_audit(
        client_id=args.client_id,
        audit_id=args.audit_id,
        s3_storage=factory.s3_storage(),
        allow_production=args.allow_production,
        dry_run=args.dry_run,
    )
    return CommandResult(
        command="audit schedule",
        stage=stage_config.stage,
        status=data.get("status", "success"),
        summary="validation passed; no mutations performed" if args.dry_run else "audit scheduled",
        data=data,
    )


def run_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = None
    if not args.dry_run:
        stage_config.validate_orchestrator_function_name()
        factory = AwsClientFactory(stage_config)
    data = ManualRunInvocationService(
        stage_config=stage_config,
        lambda_client=None if args.dry_run else factory.lambda_invocation(),
    ).run(
        client_id=args.client_id,
        audit_id=args.audit_id,
        scenario_type=args.scenario_type,
        run_id=args.run_id,
        schedule_type=args.schedule_type,
        dry_run=args.dry_run,
    )
    handler_failed = data.get("status") == "failed"
    summary = (
        "validation passed; no invocation performed"
        if args.dry_run
        else "orchestrator execution failed"
        if handler_failed
        else "orchestrator execution completed"
        if data.get("status") == "completed"
        else "orchestrator invocation completed"
    )
    return CommandResult(
        command="audit run",
        stage=stage_config.stage,
        status=data.get("status", "success"),
        summary=summary,
        data={"client_id": args.client_id, "audit_id": args.audit_id, **data},
        exit_code=1 if handler_failed else 0,
    )


def cancel_command(args: Namespace) -> CommandResult:
    stage_config = _stage(args)
    factory = AwsClientFactory(stage_config)
    data = AuditCancellationService(
        repository=factory.audit_metadata_repository(), scheduler_client=factory.scheduler()
    ).cancel_for_operator(
        client_id=args.client_id, audit_id=args.audit_id, reason=args.reason, dry_run=args.dry_run
    )
    warning = data.get("status") == "cancelled_with_cleanup_warnings"
    return CommandResult(
        command="audit cancel",
        stage=stage_config.stage,
        status=data.get("status", "success"),
        summary="audit cancelled with cleanup warnings"
        if warning
        else ("validation passed; no mutations performed" if args.dry_run else "audit cancelled"),
        data=data,
        exit_code=3 if warning else 0,
    )
