# Implementation Plan

## A1.LH1 — Authoritative Hold State and DynamoDB Coordination

*Formerly identified in the corrective architecture sequence as “Legal-Hold Correction B1.”*

## 1. Feature Overview

A1.LH1 builds the DynamoDB-side coordination foundation for legal hold: the
authoritative, versioned hold-state model (`hold_version`, `sweep_status`)
on `LegalHold`, the corrected PLACE/RELEASE transition sequences (resumable,
no-op-safe), the required `LegalHoldEvent` SK correction
(`hold_id`+`hold_version`), and a reusable `TransactWriteItems` coordination
mechanism that a future Category 1/2 governed-record write path can condition
against `LegalHold.hold_version`. It is a narrowly-scoped corrective
implementation subphase within Evidence Governance Workstream A1, Decision 9
/ Technical Design §19.

A1.LH1 does not wire any of this into a production write path, and touches no S3
client of any kind.

## 2. Technical Scope

Per the orchestrator's authorized-scope list (Technical Design §19.1–19.4,
§19.5.1's "Required consequence", §19.5.2, §19.10 subphase (b1); ADR
Decision 9, Non-Negotiable Invariants 11, 12, 14, 21, 23, 24, 25):

- `hold_version`/`sweep_status` fields on `LegalHold`.
- `hold_version` (required SK discriminator) and canary-marker plumbing
  fields (`marker_s3_key`, `marker_status`, `marker_confirmed_last_modified`)
  on `LegalHoldEvent`; matching plumbing fields on `LegalHold`.
- Corrected PLACE (§19.2 steps 1–4) and RELEASE (§19.3 steps 1–3) transition
  sequencing: new-episode vs. resume vs. stale no-op (PLACE) / rejection
  (RELEASE).
- Episode-scoped `hold_id` (generated once per episode, reused by the paired
  release).
- The required `LegalHoldEvent` SK fix (`hold_id`+`hold_version`).
- A reusable `TransactWriteItems`/`ConditionCheck` coordination utility
  (§19.4): bounded retry (3 attempts), dual-failure precedence, fail-closed
  retry exhaustion (`HOLD_STATE_CONCURRENCY_EXCEEDED`).
- New `StorageError` subcodes completing §19.15's classification table
  (`HOLD_STATE_CONCURRENCY_EXCEEDED`, `HOLD_MARKER_ESTABLISHMENT_FAILED` —
  the latter defined but never raised by A1.LH1's own code).

Explicitly excluded (unchanged from the orchestrator's brief): S3 canary
marker creation/tagging/reconciliation; any `CustodySweepClient` change;
`RunMetadata`/raw-evidence production write-path correction; Phase 4–7
write-path integration; `RetentionService` (does not exist yet, and is not
built here beyond the `HoldRepository`-level transition logic a future
`RetentionService` will call).

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` — Decision
  9, Non-Negotiable Invariants 11–25.
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  — §18.1 (governed-record categories), §19.1–§19.15 (primary spec for this
  subphase).
- Already-merged code: `evidence_retention/hold_repository.py`,
  `evidence_retention/models.py`, `evidence_retention/identity.py`,
  `evidence_retention/constants.py`, `aggregation/repository.py::put_records_once`,
  `core/exceptions.py`.
- Existing tests: `tests/unit/evidence_retention/test_hold_repository.py`,
  `test_models.py`.

No conflict was found between the architecture documents and the repository
as it currently stands — `HoldRepository`, `LegalHold`/`LegalHoldEvent`, and
`generate_hold_id()` match the ADR/TD's description of the already-merged
A1.1 state exactly.

## 4. API Contracts Affected

No API contract changes. RCP has no HTTP API; the `rcp retention hold
place|release|status` CLI commands are explicitly out of A1.LH1's scope (no
`RetentionService` exists yet to wire a CLI to).

## 5. Data Models / Storage Affected

- `LegalHold` (DynamoDB, `MetadataTable`, `#LEGALHOLD#` SK namespace): adds
  `hold_version` (int, required), `sweep_status` (bounded string, required),
  `marker_s3_key` (optional), `marker_confirmed_last_modified` (optional).
  Additive only — no existing field renamed/removed/reinterpreted.
- `LegalHoldEvent` (DynamoDB, same table/namespace): SK changes from
  `AUDIT#{audit_id}#LEGALHOLD#{hold_id}` to
  `AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}` — a genuine key-shape
  change, but confirmed to have zero existing production callers (grep-verified;
  only this repository's own test file constructs this key), so it carries
  no migration/backfill implication. Adds `hold_version` (int, required),
  `marker_s3_key`/`marker_status`/`marker_confirmed_last_modified`
  (optional, `marker_status` defaults to `PENDING`).
- No S3 object, no other DynamoDB record type, is touched.

## 6. Files Expected to Change

- `src/release_confidence_platform/evidence_retention/constants.py` (modify)
- `src/release_confidence_platform/evidence_retention/models.py` (modify)
- `src/release_confidence_platform/evidence_retention/hold_repository.py` (modify)
- `src/release_confidence_platform/evidence_retention/hold_transitions.py` (new)
- `src/release_confidence_platform/evidence_retention/hold_coordination.py` (new)
- `tests/unit/evidence_retention/test_hold_repository.py` (modify — signature updates)
- `tests/unit/evidence_retention/test_models.py` (modify — new field coverage)
- `tests/unit/evidence_retention/test_hold_transitions.py` (new)
- `tests/unit/evidence_retention/test_hold_coordination.py` (new)

## 7. Security / Authorization Considerations

No new authentication/authorization surface (A1.LH1 has no CLI/API entry point).
`_assert_retention_sk()` (the existing A1.1 SK-write guard) is preserved
unchanged and re-verified against the corrected SK shape (test coverage
added). No secrets, tokens, or sensitive data are introduced or logged. No
new IAM permission is required beyond the existing `dynamodb:TransactWriteItems`
already anticipated by the companion ADR's Consequences section (not newly
granted here, since A1.LH1 wires no real write path to the mechanism yet).

## 8. Dependencies / Constraints

No new third-party dependency. Reuses `botocore.exceptions.ClientError`,
`boto3.dynamodb.types` (via the existing `dynamodb_codec` helpers), and this
codebase's existing `TransactWriteItems` idiom
(`AggregationRepository.put_records_once`). No environment variable, AWS
resource, or infrastructure template is touched.

## 9. Assumptions

**Assumption (non-blocking, does not affect external behavior/security/data
integrity):** `LegalHold.hold_count` increments only on a genuine new PLACE
episode (Technical Design §19.2 step 3), not on RELEASE and not on a
resumed/no-op PLACE re-invocation. The ADR/TD describe `hold_count` only as
"count of place/release cycles" without specifying which transition
increments it; incrementing at PLACE (the start of a cycle) is the smallest
change consistent with existing A1.1 behavior (first placement already sets
`hold_count=1`) and the corrected §19.2 step-4 resume/no-op distinction.
`hold_count` is a display-only counter (never gates any correctness
decision), so this does not affect governed-record eligibility, security, or
data shape guarantees.

**Assumption (implementation-shape only):** the PLACE/RELEASE transition
sequencing lives in a new `hold_transitions.py` module (a
`HoldTransitions` class depending on `HoldRepository` by composition) rather
than as additional methods on `HoldRepository` itself, preserving
`HoldRepository`'s existing "strict CRUD only" scope statement. This is an
architecture/sequencing choice within implementation authority (mirrors the
TD's own "don't bundle structurally different concerns" reasoning for the
b1/b2 subphase split), not a product decision.

## 10. Validation Plan

- `pytest tests/unit/evidence_retention/ -q` — focused suite for the touched
  package.
- `pytest -q` (full canonical suite, per `[tool.pytest.ini_options]` in
  `pyproject.toml`: `testpaths = ["tests"]`).
- `ruff check src/release_confidence_platform/evidence_retention/
  tests/unit/evidence_retention/` — lint.
- `ruff format --check` on the same paths, with any pre-existing baseline
  drift (confirmed via `git stash` before touching these files) called out
  rather than silently reformatted, per scope-control ("avoid unrelated
  formatting churn").
