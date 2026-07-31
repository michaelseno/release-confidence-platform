# Implementation Plan

## 1. Feature Overview

Subphase A1.3d.1 builds the shared, authoritative custody-period
configuration foundation that later, separately authorized subphases
(A1.3d.2/.3/.4) will consume to wire Phase 5 (Intelligence), Phase 6
(Report), and Phase 7 (Certificate) to legal-hold coordination and
custody-field computation. This subphase introduces no repository,
publisher, CLI dispatch, or hold-coordination wiring changes -- it is
foundation-only, per Technical Design Section 20.12's explicit
per-subphase inventory.

## 2. Technical Scope

- New authoritative, checked-in, stage-indexed configuration file
  (`config/custody_periods.json`) covering all five evidentiary custody
  classes plus the `retention_marker` operational duration, per the fixed
  schema ADR Decision 5 (A1.3d.0 amendment) and Technical Design Section
  20.3 define. Ships with every class/stage left unconfigured.
- New Python loader (`CustodyPeriodConfigLoader.resolve(evidence_class,
  stage) -> int`) that reads and validates this file, raising
  `ConfigError(..., "CUSTODY_PERIOD_CONFIG_MISSING")` for every invalid or
  missing condition Technical Design Section 20.4 enumerates.
- Migration of `infra/serverless.yml`'s existing `custom.custodyPeriodDays`
  block (all six keys) from inline empty-mapping literals to
  `${file(../config/custody_periods.json):...}` external-file references,
  consolidating what was previously two authorities (inline YAML for five
  classes, plus `aggregate_metadata`'s own A1.3c.1 inline entry) onto the
  one file this subphase introduces.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md` --
  Decision 5 (as amended by the A1.3d.0 consolidation), Decision 10,
  Non-Negotiable Invariants 27-30.
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  -- Section 20.3 (Authoritative Custody Configuration Source), Section
  20.4 (Command-Scoped CLI Resolution), Section 20.12 (Per-Subphase
  Implementation Inventory, A1.3d.1 entry).
- `src/release_confidence_platform/config/stage_config.py` -- sibling
  loader pattern (`StageConfigLoader`), reused for structural conventions
  (error handling style, `root` constructor override, module layout) and
  for the `STAGES` stage vocabulary; not extended or subclassed.
- `src/release_confidence_platform/core/exceptions.py` -- existing
  `ConfigError(message, error_type)` exception, reused as-is.

## 4. API Contracts Affected

No API contract changes. This subphase adds no CLI dispatch wiring, no
repository/publisher constructor changes, and no Lambda handler or
`environment:` binding beyond the pre-existing `auditAggregation` binding
(left textually unchanged).

## 5. Data Models / Storage Affected

No data model or storage changes. No DynamoDB, S3, or AWS interaction of
any kind is introduced -- `CustodyPeriodConfigLoader` is a pure local
JSON-file read plus validation.

## 6. Files Expected to Change

- New: `config/custody_periods.json`
- New: `src/release_confidence_platform/config/custody_period_config.py`
- Modified: `infra/serverless.yml` (`custom.custodyPeriodDays` block only;
  `infra/resources/s3.yml` and every function's `environment:` block other
  than the pre-existing `auditAggregation` binding are untouched)
- New: `tests/unit/config/__init__.py`,
  `tests/unit/config/test_custody_period_config.py`
- Modified: `tests/unit/test_infra_configuration.py`

## 7. Security / Authorization Considerations

No authentication, authorization, secrets, or AWS-credential surface is
introduced. `CustodyPeriodConfigLoader` performs no AWS client
construction, no network call, and no environment-variable fallback --
Invariant 30's "resolve before any AWS-client construction, no env-var
fallback" requirement is satisfied by construction, since this loader has
no AWS dependency to sequence against at all. Error messages are
sanitized: no raw file paths, no raw JSON content, and no stack traces are
embedded in any raised `ConfigError` message, mirroring
`stage_config.py`'s existing convention.

## 8. Dependencies / Constraints

No new third-party dependency. Reuses the standard library `json` module,
the existing `ConfigError` exception, and the existing `STAGES` tuple from
`stage_config.py`. Constrained by ADR Decision 10 / Invariant 28 (no
Lambda infrastructure for Phase 5-7) and Invariant 29 (exactly one
authoritative configuration source for all five evidentiary classes).

## 9. Assumptions

- Assumption: the repo-root `config/` directory (already containing
  `defaults/` and `stages/`) is the correct sibling location for
  `custody_periods.json`, per the technical design's own
  `config/custody_periods.json` path (no ambiguity here -- confirmed
  directly against Section 20.3/20.12's exact path).
- Assumption: `tests/unit/config/` follows the same `__init__.py`
  package-directory convention already used by
  `tests/unit/reliability_intelligence/`, `tests/unit/aggregation/`, etc.
    Neither assumption affects external behavior, data shape, security,
    billing, permissions, or API contracts.

## 10. Validation Plan

- `pytest tests/unit/config/test_custody_period_config.py -v` -- every
  condition in Technical Design Section 20.4's exception contract, plus
  positive-class/positive-stage resolution, `retention_marker` rejection,
  production-file structural/unconfigured-state proof, and no-env-fallback
  proof.
- `pytest tests/unit/test_infra_configuration.py -v` -- migrated
  `custom.custodyPeriodDays` reference-shape assertions, schema-boundary
  assertions, and the live `sls print --stage dev` fail-closed regression
  (executed for real, not skipped, since the Serverless CLI/Node toolchain
  is available in this environment).
- Full existing suite (`pytest -q`) to confirm no regression elsewhere.
