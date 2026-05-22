#!/usr/bin/env python3
"""Executable shim for the rcp operator CLI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_confidence_platform.operator_cli.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
