"""Packaged entry point for the internal operator CLI.

The CLI implementation currently lives in the historical ``packages`` source
tree. This module provides a conventional, project-specific console-script
target and delegates to the shared implementation without changing command
behavior.
"""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType


def _ensure_legacy_packages_importable() -> None:
    """Allow source-tree script execution while keeping installed imports normal."""
    try:
        import_module("packages")
        return
    except ModuleNotFoundError as exc:
        if exc.name != "packages":
            raise

    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "packages" / "operator_cli" / "main.py").is_file():
        repo_root_text = str(repo_root)
        if repo_root_text not in sys.path:
            sys.path.insert(0, repo_root_text)


def _legacy_main() -> ModuleType:
    _ensure_legacy_packages_importable()
    return import_module("packages.operator_cli.main")


def build_parser() -> argparse.ArgumentParser:
    return _legacy_main().build_parser()


def main(argv: list[str] | None = None) -> int:
    return _legacy_main().main(argv)
