from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

BASE_URL = os.environ.get("MOCK_TARGET_API_BASE_URL")


pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="MOCK_TARGET_API_BASE_URL is not set; skipping optional HTTP integration tests",
)


def test_fast_http_endpoint() -> None:
    with urlopen(f"{BASE_URL}/health/fast", timeout=5) as response:  # noqa: S310
        assert response.status == 200
        assert json.loads(response.read())["endpoint"] == "fast"


def test_flaky_http_endpoint_intentional_500_json() -> None:
    url = f"{BASE_URL}/health/flaky?{urlencode({'seed': 'seed-4'})}"
    with pytest.raises(HTTPError) as exc_info:
        urlopen(url, timeout=5)  # noqa: S310
    assert exc_info.value.code == 500
    assert json.loads(exc_info.value.read())["status"] == "degraded"
