from datetime import UTC, datetime, timedelta

import pytest

from packages.audit_scheduling.safeguards import validate_token_metadata
from packages.core.exceptions import ValidationError


def test_token_metadata_reference_only_and_expiration():
    future = (datetime.now(UTC) + timedelta(hours=49)).isoformat().replace("+00:00", "Z")
    token = validate_token_metadata(
        {"token_ref": "arn:token-ref", "expires_at": future, "scope": "audit"},
        {"end_time": future},
    )
    assert token["token_ref"] == "arn:token-ref"
    with pytest.raises(ValidationError):
        validate_token_metadata({"token": "secret", "expires_at": future}, {"end_time": future})
    with pytest.raises(ValidationError):
        validate_token_metadata(
            {"token_ref": "arn", "expires_at": "2020-01-01T00:00:00Z"}, {"end_time": future}
        )
