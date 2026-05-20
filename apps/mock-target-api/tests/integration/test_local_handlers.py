from __future__ import annotations

import json

from handlers import health_fast, health_flaky, health_inconsistent


def test_local_handler_integration_smoke(http_event) -> None:
    fast = health_fast.handler(http_event("/health/fast"), None)
    assert fast["statusCode"] == 200
    assert json.loads(fast["body"])["service"] == "mock-target-api"

    flaky = health_flaky.handler(http_event("/health/flaky", {"seed": "seed-0"}), None)
    assert flaky["statusCode"] == 200

    inconsistent = health_inconsistent.handler(
        http_event("/health/inconsistent", {"variant": "B"}), None
    )
    assert json.loads(inconsistent["body"])["metadata"]["variant"] == "B"
