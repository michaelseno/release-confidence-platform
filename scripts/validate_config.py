"""Phase 0 local sample configuration validator.

This script validates committed sample JSON files only. It does not load production config,
perform network calls, read secrets, or execute audits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.core.constants.identifiers import MANDATORY_IDENTIFIERS  # noqa: E402

EXPECTED_SAMPLE_FILES = (
    "client_config.sample.json",
    "audit_config.sample.json",
    "endpoints.sample.json",
)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as sample_file:
        payload = json.load(sample_file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def validate_samples(samples_dir: Path) -> list[str]:
    """Validate the Phase 0 sample config files and return checked file names."""
    missing = [name for name in EXPECTED_SAMPLE_FILES if not (samples_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing sample config files: {', '.join(missing)}")

    checked: list[str] = []
    client_config = _load_json(samples_dir / "client_config.sample.json")
    audit_config = _load_json(samples_dir / "audit_config.sample.json")
    endpoints_config = _load_json(samples_dir / "endpoints.sample.json")

    if "client_id" not in client_config:
        raise ValueError("client_config.sample.json must include client_id")

    for identifier in ("client_id", "audit_id", "raw_result_version"):
        if identifier not in audit_config:
            raise ValueError(f"audit_config.sample.json must include {identifier}")

    endpoints = endpoints_config.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("endpoints.sample.json must include a non-empty endpoints list")
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise ValueError("each endpoint sample must be a JSON object")
        for identifier in ("endpoint_id", "scenario_id"):
            if identifier not in endpoint:
                raise ValueError(f"each endpoint sample must include {identifier}")

    observed_identifiers = set(client_config) | set(audit_config) | set(endpoints_config)
    for endpoint in endpoints:
        observed_identifiers.update(endpoint)
    required_present = set(MANDATORY_IDENTIFIERS) - {"run_id"}
    if not required_present.issubset(observed_identifiers):
        missing_required = sorted(required_present - observed_identifiers)
        raise ValueError(f"Sample configs are missing identifiers: {', '.join(missing_required)}")

    checked.extend(EXPECTED_SAMPLE_FILES)
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 0 sample config files.")
    parser.add_argument("--samples-dir", default="configs/samples", type=Path)
    args = parser.parse_args()

    checked = validate_samples(args.samples_dir)
    print(f"Validated Phase 0 sample configs: {', '.join(checked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
