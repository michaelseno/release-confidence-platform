from __future__ import annotations

import json

import pytest

from release_confidence_platform.operator_cli import config_init
from release_confidence_platform.operator_cli.main import build_parser, main


def test_config_init_parser_accepts_required_and_optional_args(tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        [
            "config",
            "init",
            "--client-name",
            "Demo Client",
            "--target-environment",
            "production",
            "--output-dir",
            str(tmp_path),
            "--timezone",
            "America/New_York",
            "--include-sample-endpoints",
            "--overwrite",
            "--output",
            "json",
        ]
    )
    assert args.config_command == "init"
    assert args.target_environment == "production"
    assert args.output == "json"
    assert args.stage if hasattr(args, "stage") else True


def test_config_init_parser_rejects_missing_required_args(tmp_path):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            ["config", "init", "--client-name", "Demo", "--output-dir", str(tmp_path)]
        )
    assert exc.value.code == 2


@pytest.mark.parametrize("target_environment", ["dev", "staging", "prod", "production"])
def test_config_init_parser_target_environment_choices(tmp_path, target_environment):
    args = build_parser().parse_args(
        [
            "config",
            "init",
            "--client-name",
            "Demo",
            "--target-environment",
            target_environment,
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert args.target_environment == target_environment


def test_config_init_text_output_includes_required_information(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--target-environment",
                "dev",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "client_demo_a8f3c2d1" in out
    assert "audit_20260523_ef56ab78" in out
    assert "client_config.json" in out and "audit_config.json" in out and "endpoints.json" in out
    assert ".local-configs/" in out and ".gitignore" in out


def test_config_init_json_output_is_parseable_and_complete(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--target-environment",
                "prod",
                "--output-dir",
                str(tmp_path),
                "--include-sample-endpoints",
                "--output",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config init"
    assert payload["stage"] is None
    assert payload["client_id"] == "client_demo_a8f3c2d1"
    assert payload["audit_id"] == "audit_20260523_ef56ab78"
    assert len(payload["generated_files"]) == 3
    assert ".gitignore" in payload["warning"]


def test_config_init_json_error_output_is_parseable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        config_init, "generate_client_id", lambda client_name, shortid=None: "client_demo_a8f3c2d1"
    )
    monkeypatch.setattr(
        config_init, "generate_audit_id", lambda today=None, shortid=None: "audit_20260523_ef56ab78"
    )
    root = tmp_path / "client_demo_a8f3c2d1"
    root.mkdir()
    assert (
        main(
            [
                "config",
                "init",
                "--client-name",
                "Demo",
                "--target-environment",
                "dev",
                "--output-dir",
                str(tmp_path),
                "--output",
                "json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["code"] == "LOCAL_FILE_EXISTS"
