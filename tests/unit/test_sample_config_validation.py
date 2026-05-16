from pathlib import Path

from scripts.validate_config import validate_samples


def test_sample_configs_validate() -> None:
    checked = validate_samples(Path("configs/samples"))

    assert checked == [
        "client_config.sample.json",
        "audit_config.sample.json",
        "endpoints.sample.json",
    ]
