"""CLI command definitions for Phase 6.3 Report Generation.

Provides parser registration and dispatch for the `rcp generate report` subcommand.
Phase 6.4 will complete the infrastructure wiring; Phase 6.3 registers the parser
and import contract so the CLI shape is established.
"""

from __future__ import annotations

import argparse
from typing import Any


def build_report_generate_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the `generate report` subparser on the provided subparsers action."""
    p = sub.add_parser("report", help="Generate a deterministic release confidence report")
    p.add_argument("--client", required=True, help="Client identifier")
    p.add_argument("--audit", required=True, help="Audit identifier")
    p.add_argument("--execution", required=True, help="Audit execution identity")
    p.add_argument(
        "--stage", required=True, choices=("dev", "staging", "prod"),
        help="Deployment stage",
    )
    p.add_argument(
        "--output", choices=("json", "human"), default="human",
        help="Output format (default: human)",
    )
    p.add_argument(
        "--config-version", default="v1", dest="config_version",
        help="Configuration version (default: v1)",
    )
    p.add_argument(
        "--aggregation-version", default="agg_v1", dest="aggregation_version",
        help="Aggregation version to consume (default: agg_v1)",
    )
    p.add_argument(
        "--intelligence-version", default="intel_v1", dest="intelligence_version",
        help="Intelligence version to consume (default: intel_v1)",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-generate even if COMPLETE report already exists",
    )


def dispatch_report_generate(args: argparse.Namespace, engine: Any) -> dict[str, Any]:
    """Dispatch `generate report` arguments to the ReportingEngine.

    Args:
        args: Parsed argparse namespace from `build_report_generate_parser`.
        engine: A ReportingEngine instance with repository and publisher wired.

    Returns:
        The result dict from engine.generate().
    """
    return engine.generate(
        client_id=args.client,
        audit_id=args.audit,
        audit_execution_id=args.execution,
        config_version=args.config_version,
        aggregation_version=args.aggregation_version,
        intelligence_version=args.intelligence_version,
        force=getattr(args, "force", False),
    )
