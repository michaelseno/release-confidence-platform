"""Unit tests for `CustodyPeriodConfigLoader` (Evidence Governance
Workstream A1, Subphase A1.3d.1).

Covers every condition Technical Design Section 20.4's exception contract
enumerates, the five accepted evidentiary evidence classes, every supported
stage, `retention_marker`'s exclusion as a non-evidentiary class, the
production `config/custody_periods.json` file's current unconfigured state,
and the absence of any environment-variable fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_confidence_platform.config.custody_period_config import (
    EVIDENCE_CLASSES,
    CustodyPeriodConfigLoader,
)
from release_confidence_platform.config.stage_config import STAGES
from release_confidence_platform.core.exceptions import ConfigError

_ERROR_TYPE = "CUSTODY_PERIOD_CONFIG_MISSING"


def _write_custody_periods_json(root: Path, payload: dict) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "custody_periods.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid_payload(evidence_class: str, stage: str, value: int) -> dict:
    return {
        "evidentiary_classes": {
            "raw_evidence": {},
            "aggregate_metadata": {},
            "intelligence": {},
            "report": {},
            "certificate": {},
            evidence_class: {stage: value},
        },
        "operational_durations": {"retention_marker": {}},
    }


# ---------------------------------------------------------------------------
# Positive cases -- every accepted evidence class, every supported stage.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evidence_class", EVIDENCE_CLASSES)
def test_resolves_every_accepted_evidence_class(tmp_path: Path, evidence_class: str) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload(evidence_class, "dev", 30))

    resolved = CustodyPeriodConfigLoader(root=tmp_path).resolve(evidence_class, "dev")

    assert resolved == 30


@pytest.mark.parametrize("stage", STAGES)
def test_resolves_every_supported_stage(tmp_path: Path, stage: str) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", stage, 45))

    resolved = CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", stage)

    assert resolved == 45


def test_evidence_classes_constant_contains_exactly_the_five_evidentiary_classes() -> None:
    assert set(EVIDENCE_CLASSES) == {
        "raw_evidence",
        "aggregate_metadata",
        "intelligence",
        "report",
        "certificate",
    }


# ---------------------------------------------------------------------------
# retention_marker exclusion -- it is an operational duration, not an
# evidentiary class, and must never be accepted through resolve().
# ---------------------------------------------------------------------------


def test_retention_marker_is_rejected_as_evidence_class(tmp_path: Path) -> None:
    payload = {
        "evidentiary_classes": {
            "raw_evidence": {},
            "aggregate_metadata": {},
            "intelligence": {},
            "report": {},
            "certificate": {},
        },
        "operational_durations": {"retention_marker": {"dev": 7}},
    }
    _write_custody_periods_json(tmp_path, payload)

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("retention_marker", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


# ---------------------------------------------------------------------------
# Failure classifications -- every condition raises ConfigError with
# CUSTODY_PERIOD_CONFIG_MISSING and no distinguishing sub-code.
# ---------------------------------------------------------------------------


def test_missing_file_raises_custody_period_config_missing(tmp_path: Path) -> None:
    # tmp_path/config/custody_periods.json intentionally never written.
    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_malformed_json_raises_custody_period_config_missing(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "custody_periods.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_non_object_root_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json_raw(tmp_path, json.dumps([1, 2, 3]))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def _write_custody_periods_json_raw(root: Path, raw_text: str) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "custody_periods.json").write_text(raw_text, encoding="utf-8")


def test_missing_evidentiary_classes_key_raises_custody_period_config_missing(
    tmp_path: Path,
) -> None:
    _write_custody_periods_json(tmp_path, {"operational_durations": {"retention_marker": {}}})

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_malformed_evidentiary_classes_key_raises_custody_period_config_missing(
    tmp_path: Path,
) -> None:
    _write_custody_periods_json(
        tmp_path,
        {
            "evidentiary_classes": "not-an-object",
            "operational_durations": {"retention_marker": {}},
        },
    )

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_unknown_evidence_class_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 30))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("not_a_real_class", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_unsupported_stage_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 30))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "qa")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_missing_stage_property_raises_custody_period_config_missing(tmp_path: Path) -> None:
    # "dev" is configured, but "staging" is absent for this class.
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 30))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "staging")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_null_value_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", None))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


@pytest.mark.parametrize("boolean_value", [True, False])
def test_boolean_value_raises_custody_period_config_missing(
    tmp_path: Path, boolean_value: bool
) -> None:
    """Python's bool is an int subclass (isinstance(True, int) is True), so
    this proves the loader explicitly rejects Booleans rather than silently
    accepting them via a naive isinstance(value, int) check.
    """
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", boolean_value))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_string_value_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", "30"))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_float_value_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 30.0))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_zero_value_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 0))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


def test_negative_value_raises_custody_period_config_missing(tmp_path: Path) -> None:
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", -5))

    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert exc_info.value.error_type == _ERROR_TYPE


# ---------------------------------------------------------------------------
# Error message sanitization -- no raw file paths, no raw JSON content, no
# stack traces embedded in the message.
# ---------------------------------------------------------------------------


def test_error_message_does_not_leak_raw_file_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")

    assert str(tmp_path) not in exc_info.value.message


# ---------------------------------------------------------------------------
# Production file: ships with no configured stage values anywhere.
# ---------------------------------------------------------------------------


def test_production_custody_periods_json_has_expected_schema_and_no_configured_values() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    production_file = repo_root / "config" / "custody_periods.json"
    assert production_file.is_file(), "config/custody_periods.json must exist at the repo root"

    payload = json.loads(production_file.read_text(encoding="utf-8"))
    assert set(payload) == {"evidentiary_classes", "operational_durations"}
    assert set(payload["evidentiary_classes"]) == set(EVIDENCE_CLASSES)
    for evidence_class, stage_values in payload["evidentiary_classes"].items():
        assert stage_values == {}, f"{evidence_class} must be unconfigured, got {stage_values!r}"
    assert payload["operational_durations"] == {"retention_marker": {}}


@pytest.mark.parametrize("evidence_class", EVIDENCE_CLASSES)
@pytest.mark.parametrize("stage", STAGES)
def test_production_custody_periods_json_resolves_nothing_for_any_class_or_stage(
    evidence_class: str, stage: str
) -> None:
    """Resolving any evidence class against the real, checked-in production
    file must raise CUSTODY_PERIOD_CONFIG_MISSING for every stage -- proving
    the production file itself is not the source of a real duration value
    for this subphase. Uses the default (unpatched) root, deliberately
    reading the actual repo-root config/custody_periods.json rather than a
    tmp_path fixture.
    """
    with pytest.raises(ConfigError) as exc_info:
        CustodyPeriodConfigLoader().resolve(evidence_class, stage)

    assert exc_info.value.error_type == _ERROR_TYPE


# ---------------------------------------------------------------------------
# No environment-variable fallback exists.
# ---------------------------------------------------------------------------


def test_no_environment_variable_fallback_exists(tmp_path: Path, monkeypatch) -> None:
    """Setting a plausible fallback-named environment variable must have no
    effect -- resolution still fails closed against the fixture file's
    genuinely-missing stage property.
    """
    _write_custody_periods_json(tmp_path, _valid_payload("raw_evidence", "dev", 30))
    monkeypatch.setenv("CUSTODY_PERIOD_DAYS_RAW_EVIDENCE", "99")
    monkeypatch.setenv("RCP_CUSTODY_PERIOD_DAYS", "99")

    with pytest.raises(ConfigError) as exc_info:
        # "staging" is genuinely absent for raw_evidence in this fixture.
        CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "staging")

    assert exc_info.value.error_type == _ERROR_TYPE

    monkeypatch.setenv("CUSTODY_PERIOD_DAYS_RAW_EVIDENCE", "99")
    resolved = CustodyPeriodConfigLoader(root=tmp_path).resolve("raw_evidence", "dev")
    assert resolved == 30, "the fixture's own configured value (30) must win, not the env var"
