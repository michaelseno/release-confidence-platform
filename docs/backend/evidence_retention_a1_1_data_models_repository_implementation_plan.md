# Implementation Plan

## 1. Feature Overview

Workstream A1.1 — Evidence Retention: Data Models & Repository Layer (GitHub
Issue #93). Implements the foundational `evidence_retention/` package: the
three Pydantic record models (`LegalHold`, `LegalHoldEvent`, `DisposalRecord`)
and the two SK-guarded DynamoDB repositories (`HoldRepository`,
`DisposalRepository`) that later subphases (A1.2 infra, A1.3 write-path
integration, A1.4 Lambda/CLI/backfill) will build on. No infrastructure,
service orchestration, CLI, or Lambda handler is implemented in this
subphase.

## 2. Technical Scope

- New package `src/release_confidence_platform/evidence_retention/` with
  `__init__.py`, `constants.py`, `identity.py`, `models.py`,
  `hold_repository.py`, `disposal_repository.py`.
- `HoldRepository`: DynamoDB read/write access scoped exclusively to the
  `#LEGALHOLD` SK namespace (`LegalHold` current-state record,
  `LegalHoldEvent` immutable log), guarded by `_assert_retention_sk()`.
- `DisposalRepository`: DynamoDB read/write access scoped exclusively to the
  `#DISPOSAL` SK namespace (`DisposalRecord`), guarded by
  `_assert_disposal_sk()`.
- No `RetentionService`, no CLI, no Lambda, no infra/CFN changes, no
  write-path integration into Phase 1–7 persistence code, no custody-period
  value. All out of scope per the dispatch brief and deferred to A1.2/A1.3/A1.4.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` (ADR;
  Non-Negotiable Invariants 1 and 6 are directly enforced by this subphase).
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  (Technical Design; Sections 5.2, 6, 7.1–7.4, 11, 12, 13, 17).
- `docs/product/evidence_governance_workstream_a_product_spec.md` (Sections
  7–8; AC-A1-5 — no custody-period value hardcoded — and AC-A1-6 — durable,
  queryable disposal record shape — are the criteria this subphase's models
  satisfy the data shape for; full end-to-end satisfaction of AC-A1-5/AC-A1-6
  requires the later infra/write-path/Lambda subphases).
- Existing pattern reference (read-only, not modified):
  `src/release_confidence_platform/audit_platform_integrity/repository.py`
  (`_assert_phase7_sk`), `.../models.py`, `.../identity.py`;
  `src/release_confidence_platform/deterministic_reporting/repository.py`
  (`_assert_phase6_sk`); `tests/unit/audit_platform_integrity/test_repository.py`,
  `test_models.py`.

## 4. API Contracts Affected

No API contract changes. This subphase introduces no CLI commands, HTTP
endpoints, or Lambda handlers — those belong to `commands.py` /
`disposal_recorder.py`, explicitly out of scope here per Technical Design
Section 11 and the dispatch brief.

## 5. Data Models / Storage Affected

New DynamoDB record types (no schema-breaking change to any existing table
or record — additive only, per `naming_and_schema_versioning.md`):

- `LegalHold` — PK `CLIENT#{client_id}`, SK `AUDIT#{audit_id}#LEGALHOLD`.
- `LegalHoldEvent` — PK `CLIENT#{client_id}`, SK
  `AUDIT#{audit_id}#LEGALHOLD#{hold_id}`.
- `DisposalRecord` — PK `CLIENT#{client_id}`, SK
  `AUDIT#{audit_id}#DISPOSAL#{disposal_id}`.

No `MetadataTable` schema change (TTL attribute, streams) is made in this
subphase — that is A1.2 infra scope. No S3 change.

## 6. Files Expected to Change

New files only, all under `evidence_retention/` and its test directory:

- `src/release_confidence_platform/evidence_retention/__init__.py`
- `src/release_confidence_platform/evidence_retention/constants.py`
- `src/release_confidence_platform/evidence_retention/identity.py`
- `src/release_confidence_platform/evidence_retention/models.py`
- `src/release_confidence_platform/evidence_retention/hold_repository.py`
- `src/release_confidence_platform/evidence_retention/disposal_repository.py`
- `tests/unit/evidence_retention/__init__.py`
- `tests/unit/evidence_retention/test_models.py`
- `tests/unit/evidence_retention/test_hold_repository.py`
- `tests/unit/evidence_retention/test_disposal_repository.py`

No existing file is modified.

## 7. Security / Authorization Considerations

- No new external attack surface (no CLI, no network endpoint in this
  subphase).
- `_assert_retention_sk()` / `_assert_disposal_sk()` are the code-level
  enforcement of ADR Non-Negotiable Invariant 6 (mutually exclusive SK-write
  guards), modeled directly on `_assert_phase7_sk`.
- `DisposalRecord` never carries `ttl_disposal_at` (ADR Non-Negotiable
  Invariant 1) — enforced structurally: `put_disposal_record()`'s item dict
  has no such key, and no code path in this package can add one.
- Per ADR Traceability / Technical Design Section 12 (sanitization boundary
  ADR): `sanitize()` is never called on persistence-bound dicts in either
  repository — `client_id`/`audit_id` and all PK/SK-constructing fields are
  passed through unmodified, consistent with `audit_platform_integrity/repository.py`
  and `deterministic_reporting/repository.py`'s established convention.
- No sensitive data introduced: all model fields are identifiers, timestamps,
  and free-text operator justification, per Technical Design Section 12.

## 8. Dependencies / Constraints

- No new third-party dependency. Uses existing `pydantic`, `boto3`/`botocore`
  (via `storage/dynamodb_codec.py`), matching every existing repository
  module in this codebase.
- No custody-period duration value is defined, assumed, or hardcoded
  anywhere in this package, per AC-A1-5 / ADR Non-Negotiable Invariant 3.

## 9. Assumptions

See implementation report Section 9 for the full list, including a resolved
ambiguity between Technical Design Section 6 and Section 11 on where SK
marker/tag constants live, and a scope clarification on which repository
methods TD Section 6 attributes to `HoldRepository` that are deferred to a
later subphase because implementing them here would require weakening the
`_assert_retention_sk()` guard.

## 10. Validation Plan

- `uv run pytest tests/unit/evidence_retention/ -v` — new unit tests for
  both SK guards (positive + negative cases per marker combination), model
  construction/validation/`to_dict()`, and repository put/get behavior.
- `uv run pytest` (full suite) — confirm no regression in any existing test.
- `uv run ruff check src/release_confidence_platform/evidence_retention/ tests/unit/evidence_retention/`
  — lint clean.
- `uv run ruff format --check` on the new files — checked; pre-existing
  repo-wide formatting drift noted (see report), not treated as a blocking
  regression since it is not unique to these new files.
