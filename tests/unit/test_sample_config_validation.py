import subprocess
import sys
from pathlib import Path

from scripts.validate_config import validate_samples

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_sample_configs_validate() -> None:
    checked = validate_samples(Path("configs/samples"))

    assert checked == [
        "client_config.sample.json",
        "audit_config.sample.json",
        "endpoints.sample.json",
    ]


def test_validate_config_supports_direct_script_and_module_execution() -> None:
    commands = (
        (sys.executable, "scripts/validate_config.py", "--samples-dir", "configs/samples"),
        (sys.executable, "-m", "scripts.validate_config", "--samples-dir", "configs/samples"),
    )

    for command in commands:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert "Validated Phase 0 sample configs" in completed.stdout
