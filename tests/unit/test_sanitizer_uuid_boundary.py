"""Regression test: confirm PHONE_PATTERN matches the canonical phone-like UUID fixture."""

from __future__ import annotations

from packages.sanitization.sanitizer import PHONE_PATTERN, sanitize

# The canonical UUID whose digit sequence "2475004829" matches PHONE_PATTERN.
PHONE_LIKE_UUID = "48a87626-e2f9-4f81-82ff-2475004829ec"


def test_sanitizer_redacts_phone_in_value_strings():
    """A-02: PHONE_PATTERN must match the canonical UUID, and sanitize() must redact it."""
    match = PHONE_PATTERN.search(PHONE_LIKE_UUID)
    assert match is not None, (
        f"PHONE_PATTERN did not match '{PHONE_LIKE_UUID}' — "
        "the canonical regression fixture UUID may have changed or PHONE_PATTERN was altered"
    )

    sanitized = sanitize(PHONE_LIKE_UUID)
    assert "[REDACTED]" in sanitized, (
        f"sanitize() did not redact the phone-like sequence in '{PHONE_LIKE_UUID}'; "
        f"got: {sanitized!r}"
    )
