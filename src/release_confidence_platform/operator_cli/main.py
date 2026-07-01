"""Internal Release Confidence Platform operator CLI."""

from __future__ import annotations

import argparse
import sys

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.operator_cli import services
from release_confidence_platform.operator_cli.result import CommandResult, render, render_error
from release_confidence_platform.reliability_intelligence.commands import (
    build_intelligence_retrieve_parser,
    dispatch_intelligence_retrieve,
)
from release_confidence_platform.retrieval.commands import build_retrieve_parser, dispatch_retrieve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rcp", description="Internal Release Confidence Platform operator CLI."
    )
    sub = parser.add_subparsers(
        dest="group", required=True, metavar="{client,audit,config,retrieve}"
    )
    client = sub.add_parser("client", help="Discover clients available to operators")
    client_sub = client.add_subparsers(dest="client_command", required=True)
    p = client_sub.add_parser("list", help="List clients visible in a stage")
    _add_stage_output(p)
    _add_limit(p)
    audit = sub.add_parser(
        "audit",
        help=(
            "Audit validation, creation, scheduling, manual run, cancellation, "
            "and discovery commands"
        ),
    )
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    p = audit_sub.add_parser("list", help="List audits for a client without exposing raw evidence")
    p.add_argument("--client-id", required=True)
    _add_stage_output(p)
    _add_limit(p)
    for name in ("validate", "create"):
        p = audit_sub.add_parser(name)
        _add_config_args(p)
        _add_stage_output(p)
        if name == "create":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--force", action="store_true")
    p = audit_sub.add_parser("schedule")
    _add_ids(p)
    _add_stage_output(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-production", action="store_true")
    p = audit_sub.add_parser("run")
    _add_ids(p)
    _add_stage_output(p)
    p.add_argument(
        "--scenario-type",
        required=True,
        choices=(
            "baseline_health",
            "burst_stability",
            "repeated_stability",
            "response_consistency",
        ),
    )
    p.add_argument("--run-id")
    p.add_argument("--schedule-type", choices=("manual", "baseline", "burst", "repeated"))
    p.add_argument("--dry-run", action="store_true")
    p = audit_sub.add_parser("cancel")
    _add_ids(p)
    _add_stage_output(p)
    p.add_argument("--reason", default="operator_cancelled")
    p.add_argument("--dry-run", action="store_true")
    config = sub.add_parser(
        "config", help="Discover and download persisted audit configuration artifacts"
    )
    config_sub = config.add_subparsers(dest="config_command", required=True)
    p = config_sub.add_parser("list", help="List persisted configuration artifacts for an audit")
    _add_ids(p)
    _add_stage_output(p)
    p = config_sub.add_parser(
        "download", help="Download persisted audit configuration artifacts to a local directory"
    )
    _add_ids(p)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--overwrite", action="store_true")
    _add_stage_output(p)
    p = config_sub.add_parser(
        "stage-info", help="Show resolved local stage resource configuration without AWS calls"
    )
    _add_stage_output(p)
    p = config_sub.add_parser("init", help="Generate local starter audit configuration files")
    p.add_argument("--client-name", required=True)
    p.add_argument("--defaults", default="dev")
    p.add_argument("--output-dir")
    p.add_argument("--timezone")
    p.add_argument("--include-sample-endpoints", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--output", choices=("text", "json"), default=None)
    retrieve = sub.add_parser(
        "retrieve",
        help="Engineering retrieval commands for operational debugging (read-only)",
    )
    retrieve_sub = retrieve.add_subparsers(dest="retrieve_command", required=True)
    build_retrieve_parser(retrieve_sub)
    build_intelligence_retrieve_parser(retrieve_sub)
    generate = sub.add_parser("generate", help="Generate intelligence artifacts")
    generate_sub = generate.add_subparsers(dest="generate_command", required=True)
    intel_gen = generate_sub.add_parser(
        "intelligence", help="Generate reliability intelligence from Phase 4 aggregate set"
    )
    intel_gen.add_argument("--client", required=True, help="Client identifier")
    intel_gen.add_argument("--audit", required=True, help="Audit identifier")
    intel_gen.add_argument(
        "--execution", required=True, help="Audit execution identity"
    )
    intel_gen.add_argument(
        "--config-version", required=True, dest="config_version",
        help="Configuration version (e.g., cfg_v1)"
    )
    intel_gen.add_argument(
        "--aggregation-version", default="agg_v1", dest="aggregation_version",
        help="Aggregation version to consume (default: agg_v1)"
    )
    intel_gen.add_argument(
        "--stage", required=True, choices=("dev", "staging", "prod"),
        help="Deployment stage"
    )
    intel_gen.add_argument(
        "--force", action="store_true",
        help="Re-generate even if COMPLETE intelligence already exists"
    )
    intel_gen.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Run computation pipeline without writing to DynamoDB or S3"
    )
    intel_gen.add_argument(
        "--output", default="json", choices=("json", "human"),
        help="Output format (default: json)"
    )
    return parser


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--client-config", required=True)
    parser.add_argument("--audit-config", required=True)
    parser.add_argument("--endpoints-config", required=True)


def _add_ids(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--audit-id", required=True)


def _add_stage_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stage", required=True, choices=("dev", "staging", "prod"))
    parser.add_argument("--output", choices=("text", "json"), default="text")


def _add_limit(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=_limit_arg, default=100)


def _limit_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit must be an integer between 1 and 1000") from exc
    if parsed < 1 or parsed > 1000:
        raise argparse.ArgumentTypeError("--limit must be an integer between 1 and 1000")
    return parsed


def dispatch(args: argparse.Namespace) -> CommandResult:
    if args.group == "retrieve":
        from release_confidence_platform.config.stage_config import (
            StageConfigLoader,  # noqa: PLC0415
        )
        from release_confidence_platform.retrieval.repository import (
            RetrievalRepository,  # noqa: PLC0415, F401
        )
        from release_confidence_platform.retrieval.service import (
            RetrievalService,  # noqa: PLC0415, F401
        )
        from release_confidence_platform.storage.aws_client_factory import (
            AwsClientFactory,  # noqa: PLC0415
        )

        stage_config = StageConfigLoader().load(args.stage)
        factory = AwsClientFactory(stage_config)
        dynamodb_client = factory._session.client("dynamodb")

        retrieve_command = getattr(args, "retrieve_command", "") or ""
        if retrieve_command.startswith("intelligence-"):
            from release_confidence_platform.reliability_intelligence.formatter import (  # noqa: PLC0415
                IntelligenceFormatter,
            )
            from release_confidence_platform.reliability_intelligence.intelligence_service import (  # noqa: PLC0415
                IntelligenceRetrievalService,
            )
            from release_confidence_platform.reliability_intelligence.publisher import (  # noqa: PLC0415
                IntelligencePublisher,
            )
            from release_confidence_platform.reliability_intelligence.repository import (  # noqa: PLC0415
                IntelligenceRepository,
            )

            intel_repo = IntelligenceRepository(
                stage_config.audit_metadata_table, dynamodb_client
            )
            s3_client = factory._session.client("s3")
            intel_publisher = IntelligencePublisher(stage_config.config_bucket, s3_client)
            intel_svc = IntelligenceRetrievalService(intel_repo, intel_publisher)
            intel_formatter = IntelligenceFormatter()
            rendered = dispatch_intelligence_retrieve(args, intel_svc, intel_formatter)
            return CommandResult(data={"rendered": rendered}, exit_code=0)

        repo = RetrievalRepository(stage_config.audit_metadata_table, dynamodb_client)
        svc = RetrievalService(repo)
        return dispatch_retrieve(args, svc)

    if args.group == "generate":
        from release_confidence_platform.config.stage_config import (
            StageConfigLoader,  # noqa: PLC0415
        )
        from release_confidence_platform.core.logging import StructuredLogger  # noqa: PLC0415
        from release_confidence_platform.reliability_intelligence.engine import (  # noqa: PLC0415
            IntelligenceEngine,
        )
        from release_confidence_platform.reliability_intelligence.publisher import (  # noqa: PLC0415
            IntelligencePublisher,
        )
        from release_confidence_platform.reliability_intelligence.repository import (  # noqa: PLC0415
            IntelligenceRepository,
        )
        from release_confidence_platform.storage.aws_client_factory import (
            AwsClientFactory,  # noqa: PLC0415
        )

        generate_command = getattr(args, "generate_command", "") or ""
        if generate_command == "intelligence":
            stage_config = StageConfigLoader().load(args.stage)
            factory = AwsClientFactory(stage_config)
            dynamodb_client = factory._session.client("dynamodb")
            s3_client = factory._session.client("s3")

            intel_repo = IntelligenceRepository(
                stage_config.audit_metadata_table, dynamodb_client
            )
            intel_publisher = IntelligencePublisher(stage_config.config_bucket, s3_client)
            engine = IntelligenceEngine(
                intel_repo, intel_publisher, logger=StructuredLogger()
            )
            result = engine.generate(
                client_id=args.client,
                audit_id=args.audit,
                audit_execution_id=args.execution,
                config_version=args.config_version,
                aggregation_version=args.aggregation_version,
                force=getattr(args, "force", False),
                dry_run=getattr(args, "dry_run", False),
            )
            status_val = result.get("status", "COMPLETE")
            cli_status = (
                "success" if status_val in {"COMPLETE", "ALREADY_COMPLETE"}
                else status_val.lower()
            )
            return CommandResult(
                command="generate intelligence",
                stage=args.stage,
                status=cli_status,
                summary=f"Intelligence generation {status_val.lower()} for {args.audit}",
                data=result,
                exit_code=0,
            )
        raise AssertionError(f"generate {generate_command}")
    if args.group == "client":
        if args.client_command == "list":
            return services.client_list_command(args)
        raise AssertionError(f"client {args.client_command}")
    if args.group == "config":
        if args.config_command == "list":
            return services.config_list_command(args)
        if args.config_command == "download":
            return services.config_download_command(args)
        if args.config_command == "stage-info":
            return services.config_stage_info_command(args)
        if args.config_command == "init":
            return services.config_init_command(args)
        raise AssertionError(f"config {args.config_command}")
    command = f"audit {args.audit_command}"
    if args.audit_command == "list":
        return services.audit_list_command(args)
    if args.audit_command == "validate":
        return services.validate_command(args)
    if args.audit_command == "create":
        return services.create_command(args)
    if args.audit_command == "schedule":
        return services.schedule_command(args)
    if args.audit_command == "run":
        return services.run_command(args)
    if args.audit_command == "cancel":
        return services.cancel_command(args)
    raise AssertionError(command)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = _command_name(args)
    try:
        result = dispatch(args)
    except EngineError as exc:
        print(
            render_error(
                command,
                getattr(args, "stage", None),
                exc.error_type,
                exc.message,
                output=getattr(args, "output", "text"),
            )
        )
        return 1
    except Exception:
        print(
            render_error(
                command,
                getattr(args, "stage", None),
                "UNEXPECTED_ERROR",
                "Unexpected operator CLI failure",
                output=getattr(args, "output", "text"),
            )
        )
        return 1
    # Retrieve commands pre-render their output; print it directly.
    if getattr(args, "group", None) == "retrieve" and result.data.get("rendered") is not None:
        print(result.data["rendered"])
        return result.exit_code
    output = result.data.get("output_format") or getattr(args, "output", None) or "text"
    print(render(result, output=output))
    return result.exit_code


def _command_name(args: argparse.Namespace) -> str:
    if getattr(args, "group", None) == "client":
        return f"client {getattr(args, 'client_command', 'unknown')}"
    if getattr(args, "group", None) == "config":
        return f"config {getattr(args, 'config_command', 'unknown')}"
    if getattr(args, "group", None) == "retrieve":
        return f"retrieve {getattr(args, 'retrieve_command', 'unknown')}"
    if getattr(args, "group", None) == "generate":
        return f"generate {getattr(args, 'generate_command', 'unknown')}"
    return f"audit {getattr(args, 'audit_command', 'unknown')}"


if __name__ == "__main__":
    sys.exit(main())
