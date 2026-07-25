"""Evidence Governance Workstream A1.3b -- packages/storage/s3_client.py
raw-evidence S3 tagging tests.

Covers Technical Design Section 18.1 (Category 1 -- governed evidence) and
Section 11 row 3 (write_raw_results_once, the sole PutObject call site for
raw execution evidence): every write must be tagged rcp-legal-hold=false and
rcp-evidence-class=raw_evidence at PutObject time (ADR Decision 2).
"""

from __future__ import annotations

from urllib.parse import parse_qs

from botocore.exceptions import ClientError

from packages.storage.s3_client import S3StorageClient


def _not_found_error() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")


class CapturingS3Api:
    """Fake S3 API: object never pre-exists, records every put_object call."""

    def __init__(self) -> None:
        self.put_object_calls: list[dict[str, object]] = []

    def head_object(self, **kwargs):  # noqa: ARG002
        raise _not_found_error()

    def put_object(self, **kwargs):
        self.put_object_calls.append(kwargs)
        return {}


def _tags_from_tagging_string(tagging: str) -> dict[str, str]:
    parsed = parse_qs(tagging)
    return {key: values[0] for key, values in parsed.items()}


def test_write_raw_results_once_tags_object_legal_hold_false_and_raw_evidence_class():
    api = CapturingS3Api()
    storage = S3StorageClient("bucket", api)

    storage.write_raw_results_once(
        "raw-results/client1/audit1/run1/results.json", {"results": []}
    )

    assert len(api.put_object_calls) == 1
    call = api.put_object_calls[0]
    assert "Tagging" in call
    tags = _tags_from_tagging_string(call["Tagging"])
    assert tags == {"rcp-legal-hold": "false", "rcp-evidence-class": "raw_evidence"}


def test_write_raw_results_once_evidence_class_tag_is_fixed_regardless_of_key():
    """rcp-evidence-class is a hardcoded constant on this method -- every
    call site writes raw evidence (confirmed by the Technical Design) -- so
    the tag value must not vary with the key or payload."""
    api = CapturingS3Api()
    storage = S3StorageClient("bucket", api)

    storage.write_raw_results_once(
        "raw-results/other-client/other-audit/run9/results.json", {"anything": True}
    )

    tags = _tags_from_tagging_string(api.put_object_calls[0]["Tagging"])
    assert tags["rcp-evidence-class"] == "raw_evidence"


def test_write_raw_results_once_preserves_existing_content_type_and_body():
    """Adding Tagging must not disturb the pre-existing PutObject shape."""
    api = CapturingS3Api()
    storage = S3StorageClient("bucket", api)

    storage.write_raw_results_once("raw-results/c/a/r/results.json", {"k": "v"})

    call = api.put_object_calls[0]
    assert call["ContentType"] == "application/json"
    assert b'"k": "v"' in call["Body"] or b'"k":"v"' in call["Body"]
