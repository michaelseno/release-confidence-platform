"""Smoke tests for Phase 7.6/7.7 operator CLI certify and cert-retrieve commands.

Confirms:
- rcp certify audit --help exits 0 (parser is registered)
- rcp retrieve cert-status --help exits 0 (retrieval parser is registered)
- rcp retrieve cert-summary --help exits 0
- rcp retrieve cert-domains --help exits 0
- rcp retrieve cert-json --help exits 0
- Missing required args for certify audit exits non-zero
- Missing required args for cert-status exits non-zero
"""

from __future__ import annotations

import pytest

from release_confidence_platform.operator_cli.main import build_parser, main


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> int:
    """Run the CLI via main() and return the exit code."""
    return main(argv)


# ---------------------------------------------------------------------------
# 1. certify audit --help exits 0
# ---------------------------------------------------------------------------


def test_certify_audit_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 2. retrieve cert-status --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_status_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 3. retrieve cert-summary --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_summary_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-summary", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 4. retrieve cert-domains --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_domains_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-domains", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 5. retrieve cert-json --help exits 0
# ---------------------------------------------------------------------------


def test_retrieve_cert_json_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-json", "--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 6. Missing required args for certify audit exits non-zero
# ---------------------------------------------------------------------------


def test_certify_audit_missing_client_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_audit_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_execution_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--audit-id", "a1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_certify_audit_missing_stage_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["certify", "audit", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 7. Missing required args for cert-status exits non-zero
# ---------------------------------------------------------------------------


def test_cert_status_missing_client_id_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--audit-id", "a1", "--execution", "e1", "--stage", "dev"])
    assert exc_info.value.code != 0


def test_cert_status_missing_stage_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        main(["retrieve", "cert-status", "--client-id", "c1", "--audit-id", "a1", "--execution", "e1"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# 8. Parser build does not raise
# ---------------------------------------------------------------------------


def test_build_parser_does_not_raise():
    parser = build_parser()
    assert parser is not None


def test_certify_group_present_in_parser():
    """Certify group is registered as a subcommand of the main parser."""
    parser = build_parser()
    # Access the subparsers action to inspect registered commands
    # Build a minimal parse to confirm certify audit is recognized
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["certify", "--help"])
    assert exc_info.value.code == 0
