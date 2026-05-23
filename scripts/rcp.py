#!/usr/bin/env python3
"""Executable shim for the rcp operator CLI."""

from __future__ import annotations

import sys

from release_confidence_platform.operator_cli.main import main

if __name__ == "__main__":
    sys.exit(main())
