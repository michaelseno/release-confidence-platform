"""Internal Release Confidence Platform operator CLI."""

from __future__ import annotations

import argparse
import sys

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.operator_cli import services
from release_confidence_platform.operator_cli.result import CommandResult, render, render_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rcp", description="Internal Release Confidence Platform operator CLI."
    )
    sub = parser.add_subparsers(dest="group", required=True, metavar="{client,audit,config}")
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
    p = audit_sub.add_parser(
        "list", help="List audits for a client without exposing raw evidence"
    )
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
    p = config_sub.add_parser("init", help="Generate local starter audit configuration files")
    p.add_argument("--client-name", required=True)
    p.add_argument(
        "--target-environment", required=True, choices=("dev", "staging", "prod", "production")
    )
    p.add_argument("--output-dir", required=True)
    p.add_argument("--timezone", default="UTC")
    p.add_argument("--include-sample-endpoints", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--output", choices=("text", "json"), default="text")
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
    if args.group == "client":
        if args.client_command == "list":
            return services.client_list_command(args)
        raise AssertionError(f"client {args.client_command}")
    if args.group == "config":
        if args.config_command == "list":
            return services.config_list_command(args)
        if args.config_command == "download":
            return services.config_download_command(args)
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
    print(render(result, output=args.output))
    return result.exit_code


def _command_name(args: argparse.Namespace) -> str:
    if getattr(args, "group", None) == "client":
        return f"client {getattr(args, 'client_command', 'unknown')}"
    if getattr(args, "group", None) == "config":
        return f"config {getattr(args, 'config_command', 'unknown')}"
    return f"audit {getattr(args, 'audit_command', 'unknown')}"


if __name__ == "__main__":
    sys.exit(main())
