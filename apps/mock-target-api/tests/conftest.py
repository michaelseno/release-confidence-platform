from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture
def http_event():
    def build(
        path: str,
        query: dict[str, str | None] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        return {
            "version": "2.0",
            "rawPath": path,
            "queryStringParameters": query,
            "headers": headers or {},
            "requestContext": {"http": {"method": "GET", "path": path}},
        }

    return build
