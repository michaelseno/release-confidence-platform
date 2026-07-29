"""Shared pytest fixtures for the full test suite.

Evidence Governance Workstream A1.3b (Technical Design Section 18.1 /
Section 3; ADR Non-Negotiable Invariant 3) made
``packages.storage.dynamodb_client.DynamoDBMetadataClient.put_started_once``
fail closed (raise ``StorageError`` / ``CUSTODY_PERIOD_CONFIG_MISSING``) when
``CUSTODY_PERIOD_DAYS_RAW_EVIDENCE`` is unresolvable at runtime -- see that
module's docstring for the full rationale. This env var is intentionally
*not* wired into ``infra/serverless.yml`` by A1.3b (infra changes are out of
that subphase's authorized scope), so it is unset in every real environment
today.

This autouse fixture gives every test in the suite a deterministic,
arbitrary placeholder value (90 days) purely so pre-existing tests that
exercise ``put_started_once`` indirectly (e.g. the full
``CoreEngineOrchestrator.run()`` flow) continue to pass without every one of
them individually setting the variable. **This value has no product
meaning** -- it is not a Product Strategy custody-period decision and must
never be read as one; the real duration remains a separate, unset
configuration input (ADR Decision 5). Tests that specifically need to
exercise the fail-closed path should
``monkeypatch.delenv("CUSTODY_PERIOD_DAYS_RAW_EVIDENCE", raising=False)`` to
override this default.

Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.16.5;
ADR Decision 5 amendment / Non-Negotiable Invariant 26) adds the identical
pattern for Phase 4's evidence class:
``release_confidence_platform.aggregation.repository.AggregationRepository
.put_records_once``/``.put_lineage_page_once`` fail closed (``StorageError``
/ ``CUSTODY_PERIOD_CONFIG_MISSING``) when
``CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA`` is unresolvable at runtime. Same
placeholder-value rationale, same override mechanism
(``monkeypatch.delenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", raising=False)``
or ``monkeypatch.setenv(..., "")``/``"0"``/``"-1"``/``"not-a-number"`` for
tests that specifically exercise the fail-closed path).
"""

from __future__ import annotations

import pytest

_TEST_ONLY_CUSTODY_PERIOD_DAYS_RAW_EVIDENCE = "90"
_TEST_ONLY_CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA = "90"


@pytest.fixture(autouse=True)
def _default_custody_period_days_raw_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CUSTODY_PERIOD_DAYS_RAW_EVIDENCE",
        _TEST_ONLY_CUSTODY_PERIOD_DAYS_RAW_EVIDENCE,
    )


@pytest.fixture(autouse=True)
def _default_custody_period_days_aggregate_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA",
        _TEST_ONLY_CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA,
    )
