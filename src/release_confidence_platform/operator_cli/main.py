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
    sub = parser.add_subparsers(dest="group", required=True, metavar="{audit}")
    audit = sub.add_parser(
        "audit",
        help="Audit validation, creation, scheduling, manual run, and cancellation commands",
    )
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
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


def dispatch(args: argparse.Namespace) -> CommandResult:
    command = f"audit {args.audit_command}"
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
    command = f"audit {getattr(args, 'audit_command', 'unknown')}"
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


if __name__ == "__main__":
    sys.exit(main())
