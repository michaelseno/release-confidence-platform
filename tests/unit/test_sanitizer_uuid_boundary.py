"""Regression test: confirm PHONE_PATTERN matches the canonical phone-like UUID fixture."""

from __future__ import annotations

import pytest

from packages.sanitization.sanitizer import PHONE_PATTERN, sanitize

# The canonical UUID whose digit sequence "2475004829" matches PHONE_PATTERN.
PHONE_LIKE_UUID = "48a87626-e2f9-4f81-82ff-2475004829ec"

STRUCTURAL_IDENTIFIER_KEYS = (
    "run_id",
    "client_id",
    "audit_id",
    "audit_execution_id",
    "job_id",
    "aggregation_job_id",
    "config_version",
    "aggregation_version",
)


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


@pytest.mark.parametrize("module_path", ["packages", "release_confidence_platform"])
@pytest.mark.parametrize("key", STRUCTURAL_IDENTIFIER_KEYS)
def test_sanitize_does_not_redact_structural_identifier_values(module_path, key):
    """B-01: structural identifier fields must survive sanitize() byte-identical, even when
    their value coincidentally contains a PHONE_PATTERN-matching digit run.

    This is the root cause of the INVALID_RAW_RESULT_ENVELOPE defect: the raw result
    envelope written by the runner embeds run_id/client_id/audit_id under these exact
    keys, and aggregation's _load_records performs a strict equality check against the
    unsanitized DynamoDB copy. Any redaction here breaks that contract.
    """
    sanitizer = __import__(f"{module_path}.sanitization.sanitizer", fromlist=["sanitize"])

    envelope = {key: PHONE_LIKE_UUID, "other_field": PHONE_LIKE_UUID}
    sanitized = sanitizer.sanitize(envelope)

    assert sanitized[key] == PHONE_LIKE_UUID, (
        f"{module_path}: structural identifier key '{key}' was redacted: {sanitized[key]!r}"
    )


@pytest.mark.parametrize("module_path", ["packages", "release_confidence_platform"])
def test_sanitize_preserves_structural_identifiers_nested_in_result_lists(module_path):
    """B-02: identifier keys nested inside list-of-dict structures (e.g. the 'results'
    array of a raw result envelope) must also be protected, not just top-level keys."""
    sanitizer = __import__(f"{module_path}.sanitization.sanitizer", fromlist=["sanitize"])

    envelope = {
        "run_id": PHONE_LIKE_UUID,
        "results": [
            {"run_id": PHONE_LIKE_UUID, "endpoint_id": "ep1", "status_code": 200},
        ],
    }
    sanitized = sanitizer.sanitize(envelope)

    assert sanitized["run_id"] == PHONE_LIKE_UUID
    assert sanitized["results"][0]["run_id"] == PHONE_LIKE_UUID


@pytest.mark.parametrize("module_path", ["packages", "release_confidence_platform"])
def test_sanitize_does_not_redact_intelligence_job_id(module_path):
    """Phase 5 structural identifier intelligence_job_id must survive sanitize() byte-identical.

    A UUID-derived intelligence_job_id whose hex segment contains a 10-digit run
    matching PHONE_PATTERN (e.g. "2475004829") must not be redacted. This protects
    the SK and s3_artifact_ref from corruption at write time.
    """
    sanitizer = __import__(f"{module_path}.sanitization.sanitizer", fromlist=["sanitize"])

    # The value "intjob_48a87626e2f9-4f81-82ff-2475004829ec" contains the digit
    # sequence "2475004829" which matches PHONE_PATTERN.
    intel_job_id = "intjob_48a87626e2f9-4f81-82ff-2475004829ec"
    result = sanitizer.sanitize({"intelligence_job_id": intel_job_id})

    assert result["intelligence_job_id"] == intel_job_id, (
        f"{module_path}: intelligence_job_id was redacted: {result['intelligence_job_id']!r}"
    )


@pytest.mark.parametrize("module_path", ["packages", "release_confidence_platform"])
def test_sanitize_still_redacts_sensitive_keys_alongside_identifiers(module_path):
    """B-03: the identifier allowlist must not weaken unrelated PII/secret redaction —
    sensitive keys redact regardless of which other keys are present in the same dict."""
    sanitizer = __import__(f"{module_path}.sanitization.sanitizer", fromlist=["sanitize"])

    envelope = {
        "run_id": PHONE_LIKE_UUID,
        "auth_token": "Bearer abc123",
        "headers": {"Authorization": "Bearer abc123"},
    }
    sanitized = sanitizer.sanitize(envelope)

    assert sanitized["run_id"] == PHONE_LIKE_UUID
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["headers"]["Authorization"] == "[REDACTED]"
