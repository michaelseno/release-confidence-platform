"""Unit tests for Phase 7 cert_v1 constants (Phase 7.2).

Covers:
  CONST-01  CERT_DOMAIN_IDENTIFIERS has exactly 8 members
  CONST-02  CERTIFICATION_SUMMARY_MAP has exactly 3 keys, one per terminal state
  CONST-03  TERMINAL_STATES has exactly 3 members
  CONST-04  DOMAIN_STATUSES has exactly 3 members
  CONST-05  Each key in CERTIFICATION_SUMMARY_MAP is a member of TERMINAL_STATES
"""

from __future__ import annotations

from release_confidence_platform.audit_platform_integrity.constants import (
    CERT_DOMAIN_IDENTIFIERS,
    CERTIFICATION_SUMMARY_MAP,
    DOMAIN_STATUSES,
    TERMINAL_STATES,
)


# ---------------------------------------------------------------------------
# CONST-01: CERT_DOMAIN_IDENTIFIERS has exactly 8 members
# ---------------------------------------------------------------------------


def test_const_01_cert_domain_identifiers_has_8_members() -> None:
    """CONST-01: CERT_DOMAIN_IDENTIFIERS must contain exactly 8 domain identifiers."""
    assert len(CERT_DOMAIN_IDENTIFIERS) == 8


def test_const_01b_cert_domain_identifiers_expected_values() -> None:
    """CONST-01b: CERT_DOMAIN_IDENTIFIERS contains all expected domain names."""
    expected = {
        "RUNNER_HEALTH",
        "EVIDENCE_COMPLETENESS",
        "EVIDENCE_INTEGRITY",
        "EVIDENCE_LINEAGE",
        "OBSERVATION_COVERAGE",
        "SCHEDULER_INTEGRITY",
        "METHODOLOGY_COMPLIANCE",
        "REPORT_INTEGRITY",
    }
    assert set(CERT_DOMAIN_IDENTIFIERS) == expected


def test_const_01c_cert_domain_identifiers_no_duplicates() -> None:
    """CONST-01c: CERT_DOMAIN_IDENTIFIERS must contain no duplicate values."""
    assert len(CERT_DOMAIN_IDENTIFIERS) == len(set(CERT_DOMAIN_IDENTIFIERS))


# ---------------------------------------------------------------------------
# CONST-02: CERTIFICATION_SUMMARY_MAP has exactly 3 keys
# ---------------------------------------------------------------------------


def test_const_02_certification_summary_map_has_3_keys() -> None:
    """CONST-02: CERTIFICATION_SUMMARY_MAP must have exactly 3 keys."""
    assert len(CERTIFICATION_SUMMARY_MAP) == 3


def test_const_02b_certification_summary_map_keys() -> None:
    """CONST-02b: CERTIFICATION_SUMMARY_MAP contains keys for all terminal states."""
    assert set(CERTIFICATION_SUMMARY_MAP.keys()) == {
        "CERTIFIED",
        "CERTIFICATION_FAILED",
        "CERTIFICATION_BLOCKED",
    }


def test_const_02c_certification_summary_map_values_non_empty() -> None:
    """CONST-02c: All CERTIFICATION_SUMMARY_MAP values are non-empty strings."""
    for key, value in CERTIFICATION_SUMMARY_MAP.items():
        assert isinstance(value, str), f"Map value for {key!r} must be a string"
        assert len(value) > 0, f"Map value for {key!r} must not be empty"


# ---------------------------------------------------------------------------
# CONST-03: TERMINAL_STATES has exactly 3 members
# ---------------------------------------------------------------------------


def test_const_03_terminal_states_has_3_members() -> None:
    """CONST-03: TERMINAL_STATES must contain exactly 3 members."""
    assert len(TERMINAL_STATES) == 3


def test_const_03b_terminal_states_expected_values() -> None:
    """CONST-03b: TERMINAL_STATES contains the expected state identifiers."""
    assert TERMINAL_STATES == frozenset({
        "CERTIFIED",
        "CERTIFICATION_FAILED",
        "CERTIFICATION_BLOCKED",
    })


# ---------------------------------------------------------------------------
# CONST-04: DOMAIN_STATUSES has exactly 3 members
# ---------------------------------------------------------------------------


def test_const_04_domain_statuses_has_3_members() -> None:
    """CONST-04: DOMAIN_STATUSES must contain exactly 3 members."""
    assert len(DOMAIN_STATUSES) == 3


def test_const_04b_domain_statuses_expected_values() -> None:
    """CONST-04b: DOMAIN_STATUSES contains the expected status values."""
    assert DOMAIN_STATUSES == frozenset({"PASSED", "FAILED", "BLOCKED"})


# ---------------------------------------------------------------------------
# CONST-05: Each key in CERTIFICATION_SUMMARY_MAP is in TERMINAL_STATES
# ---------------------------------------------------------------------------


def test_const_05_summary_map_keys_are_terminal_states() -> None:
    """CONST-05: Every key in CERTIFICATION_SUMMARY_MAP must be a member of TERMINAL_STATES."""
    for key in CERTIFICATION_SUMMARY_MAP:
        assert key in TERMINAL_STATES, (
            f"CERTIFICATION_SUMMARY_MAP key {key!r} is not in TERMINAL_STATES"
        )
