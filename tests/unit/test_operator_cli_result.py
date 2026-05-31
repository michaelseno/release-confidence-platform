from __future__ import annotations

from release_confidence_platform.operator_cli.result import render_error


def test_force_recreate_blocked_guidance_is_actionable():
    rendered = render_error(
        "audit create",
        "dev",
        "FORCE_RECREATE_BLOCKED",
        "Audit lifecycle is not eligible for force recreate",
    )

    assert "force recreate is allowed only" in rendered
    assert "DRAFT or FAILED" in rendered
    assert "rcp audit list --client-id <client_id> --stage dev --output json" in rendered
    assert "fresh audit ID/config bundle" in rendered
    assert "Do not manually mutate DynamoDB" in rendered
