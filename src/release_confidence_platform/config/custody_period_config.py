"""Authoritative custody-period configuration loading (Evidence Governance
Workstream A1, Subphase A1.3d.1).

Reads the single, checked-in, stage-indexed configuration source
(`config/custody_periods.json`) that ADR Decision 5 (as amended by A1.3d.0)
and Technical Design Section 20.3/20.4 establish as the one authority every
evidentiary custody class's duration is resolved from -- both by
`infra/serverless.yml`'s Serverless-side `${file(...)}` variable resolution
and by this module's CLI/runtime-side consumption. Non-Negotiable Invariant
29 requires both consumers to derive from the same file/schema with
equivalent positive-integer validation and no fallback; Non-Negotiable
Invariant 30 requires this resolution to happen before any AWS-client
construction and to fail closed with `CUSTODY_PERIOD_CONFIG_MISSING` for
every invalid condition, with no environment-variable fallback.

This module is a sibling to `stage_config.py`'s `StageConfigLoader`, not an
extension of it (Technical Design Section 20.4: "composed alongside
StageConfigLoader, not merged into it"). It intentionally shares no base
class or mutable state with `StageConfigLoader` -- only the stage vocabulary
(`STAGES`) and the existing `ConfigError` exception type are reused.

This subphase (A1.3d.1) introduces the loader only. No caller wires it to
any repository, publisher, CLI command, or hold-coordination code path --
that wiring is explicitly deferred to A1.3d.2/.3/.4 (Phase 5/6/7), none of
which is authorized by this change.
"""

from __future__ import annotations

import json
from pathlib import Path

from release_confidence_platform.config.stage_config import STAGES
from release_confidence_platform.core.exceptions import ConfigError

# The five evidentiary custody classes (ADR Decision 5 / Non-Negotiable
# Invariant 29). `retention_marker` is deliberately excluded -- it is an
# operational disposal duration (Technical Design Section 20.3's
# `operational_durations` namespace), not an evidentiary class, and must
# never be resolvable through this method (Technical Design Section 20.4).
EVIDENCE_CLASSES = (
    "raw_evidence",
    "aggregate_metadata",
    "intelligence",
    "report",
    "certificate",
)

_ERROR_TYPE = "CUSTODY_PERIOD_CONFIG_MISSING"


class CustodyPeriodConfigLoader:
    """Resolves a single evidentiary evidence class's custody-period
    duration, for a single stage, from `config/custody_periods.json`.

    Pure local file read plus validation -- no environment-variable
    fallback, no default duration, no cross-class or cross-stage fallback,
    and no AWS dependency of any kind (Technical Design Section 20.4).
    """

    def __init__(self, *, root: Path | None = None):
        self.root = root or self._default_root()

    @staticmethod
    def _default_root() -> Path:
        module_path = Path(__file__).resolve()
        for candidate in (*module_path.parents, Path.cwd(), *Path.cwd().resolve().parents):
            if (candidate / "config" / "custody_periods.json").is_file():
                return candidate
        return module_path.parents[3]

    def resolve(self, evidence_class: str, stage: str) -> int:
        """Resolve the custody-period duration (in days) for a single
        evidentiary evidence class and stage.

        Raises `ConfigError(message, "CUSTODY_PERIOD_CONFIG_MISSING")` for
        every failure condition Technical Design Section 20.4 enumerates --
        missing file, malformed JSON, non-object root, missing/malformed
        `evidentiary_classes`, unknown evidence class, unsupported stage,
        missing stage property, `null`, Boolean, string, float, zero, or
        negative value -- with no distinguishing sub-code and no fallback.
        """
        if evidence_class not in EVIDENCE_CLASSES:
            raise ConfigError(
                "Unrecognized custody evidence class",
                _ERROR_TYPE,
            )
        if stage not in STAGES:
            raise ConfigError(
                "Unsupported custody configuration stage",
                _ERROR_TYPE,
            )

        path = self.root / "config" / "custody_periods.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(
                "Custody period configuration file not found",
                _ERROR_TYPE,
            ) from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(
                "Custody period configuration JSON is invalid",
                _ERROR_TYPE,
            ) from exc

        if not isinstance(raw, dict):
            raise ConfigError(
                "Custody period configuration must be a JSON object",
                _ERROR_TYPE,
            )

        evidentiary_classes = raw.get("evidentiary_classes")
        if not isinstance(evidentiary_classes, dict):
            raise ConfigError(
                "Custody period configuration is missing evidentiary_classes",
                _ERROR_TYPE,
            )

        class_config = evidentiary_classes.get(evidence_class)
        if not isinstance(class_config, dict):
            raise ConfigError(
                "Custody period configuration is missing the requested evidence class",
                _ERROR_TYPE,
            )

        if stage not in class_config:
            raise ConfigError(
                "Custody period configuration is missing the requested stage",
                _ERROR_TYPE,
            )

        value = class_config[stage]

        # Explicit Boolean rejection BEFORE the int check -- Python's `bool`
        # is a subclass of `int`, so `isinstance(True, int)` is True and a
        # naive int check alone would silently accept a Boolean value.
        if value is None or isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(
                "Custody period configuration value is not a valid positive integer",
                _ERROR_TYPE,
            )

        if value <= 0:
            raise ConfigError(
                "Custody period configuration value is not a valid positive integer",
                _ERROR_TYPE,
            )

        return value
