# Implementation Plan

## 1. Feature Overview

Wire Phase 6 (Deterministic Reporting) `ReportMetadata` CREATE and
regeneration writes, and the Phase 6 report S3 artifact write, to
Evidence Governance Workstream A1's legal-hold coordination and
custody-field computation, mirroring the already-merged A1.3d.2 Phase 5
(Reliability Intelligence) implementation exactly. `ReportJob` (Category 3,
operational coordination metadata) is explicitly excluded and must never
receive custody fields, evidence-class tags, or hold coordination.

## 2. Technical Scope

- `ReportRepository.put_report_metadata_once`: rewritten from a plain
  conditional `put_item` into a hold-coordinated `TransactWriteItems` CREATE.
- New `ReportRepository.regenerate_report_metadata`: dedicated,
  explicitly-typed regeneration operation with a forbidden-governance-field
  guard, replacing the current regen-PENDING call site's reuse of
  `update_report_metadata_fields`.
- `ReportRepository.update_report_metadata_fields`: unchanged behavior,
  gains a forbidden-governance-field rejection guard as its first action.
- `ReportPublisher.write_artifact`: gains a hold-state read and write-time
  `rcp-legal-hold`/`rcp-evidence-class` S3 object tagging.
- `ReportingEngine.generate`: one call-site relocation (line 289's regen
  branch moves from `update_report_metadata_fields` to
  `regenerate_report_metadata`).
- `operator_cli/main.py`'s `generate report` construction block: resolves
  `report`'s custody-period duration once, constructs a shared
  `HoldRepository`, and injects both governance dependencies into
  `ReportRepository`/`ReportPublisher`.

## 3. Source Inputs

- `docs/architecture/adr_evidence_retention_disposal_enforcement.md`
  (Decision 11, Non-Negotiable Invariant 31, and the A1.3d.3
  pre-implementation correction governance note).
- `docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`
  §20.4, §20.7.1–§20.7.11 (Phase 6 CREATE, regeneration, ordinary-transition,
  S3 key contract, Phase 7 consumer-contract preservation, error matrix,
  file inventory).
- Already-merged Phase 5 implementation
  (`reliability_intelligence/repository.py`, `publisher.py`) as the exact
  structural template, per the orchestrator's task brief.
- Already-merged `evidence_retention/hold_coordination.py` (unmodified
  reused mechanism) and `aggregation/repository.py`'s
  `_RETENTION_GOVERNED_FIELD_NAMES` guard (direct precedent for the new
  forbidden-field guards).

## 4. API Contracts Affected

No externally-facing HTTP/REST API. CLI contract changes:

- `rcp generate report`: now resolves `report`'s custody-period duration
  before AWS-client construction and fails closed
  (`CUSTODY_PERIOD_CONFIG_MISSING`) if missing/invalid; constructs a
  `HoldRepository` shared between `ReportRepository` and `ReportPublisher`.
  Existing success-path output shape (`CommandResult` fields) is unchanged.
- `rcp retrieve report-*` (all seven variants): unchanged — no custody
  resolution, no `HoldRepository` construction, dependency-free
  `ReportRepository`/`ReportPublisher` construction (both governance params
  remain at their `None` default), identical to current behavior.
- New reason codes reachable on the `generate report` path:
  `CUSTODY_PERIOD_CONFIG_MISSING`, `HOLD_COORDINATION_NOT_CONFIGURED`,
  `HOLD_STATE_CONCURRENCY_EXCEEDED` — all already-locked, reused codes from
  A1.LH1/A1.3c.1/A1.3d.2, no new reason code introduced.

## 5. Data Models / Storage Affected

- `ReportMetadata` (DynamoDB): gains `custody_expires_at` (always),
  `evidence_class="report"` (always), `ttl_disposal_at` (present only when
  no active hold is observed at write time) on CREATE and regeneration.
  Regeneration additionally issues an explicit `REMOVE ttl_disposal_at`
  when an active hold is observed, rather than merely omitting it.
- `ReportJob` (DynamoDB): no schema change — remains Category 3, excluded.
- Phase 6 report S3 artifact (`reports/` prefix): gains
  `rcp-legal-hold`/`rcp-evidence-class=report` object tags at write time.
- No migration or backfill — this only affects newly-written/regenerated
  records; existing records are unaffected until their own next write.

## 6. Files Expected to Change

Production (4):
- `src/release_confidence_platform/deterministic_reporting/repository.py`
- `src/release_confidence_platform/deterministic_reporting/publisher.py`
- `src/release_confidence_platform/deterministic_reporting/engine.py`
- `src/release_confidence_platform/operator_cli/main.py`

Tests, modified (5):
- `tests/unit/deterministic_reporting/test_repository.py`
- `tests/unit/deterministic_reporting/test_engine.py`
- `tests/unit/deterministic_reporting/test_engine_no_phase5_mutation.py`
- `tests/unit/deterministic_reporting/test_publisher.py`
- `tests/unit/test_operator_cli_result.py`

Tests, new (2):
- `tests/unit/deterministic_reporting/test_hold_coordination.py`
- `tests/unit/test_operator_cli_generate_report.py`

## 7. Security / Authorization Considerations

- Fail-closed governance preflight (hold-repository presence, then
  custody-duration presence/validity) on every governed write, before any
  hold-state read or AWS mutation — mirrors the locked Invariant 31 pattern.
- Governed-condition-wins precedence preserved for CREATE: the record's own
  `attribute_not_exists` collision is never masked behind a hold-version
  retry.
- `sanitize()` is never called on a full persistence-bound `ReportMetadata`
  item (PK/SK are not in `STRUCTURAL_IDENTIFIER_KEYS`, so sanitizing risks
  corrupting the composite key) — the same locked A1.3d.2 correction.
- No new AWS IAM permissions required (reuses the existing
  `TransactWriteItems`/`GetItem`/`PutObject` permission surface already
  granted to Phase 5).
- No secrets, tokens, or credentials touched.

## 8. Dependencies / Constraints

- No new third-party dependency.
- Reuses `evidence_retention/hold_coordination.py`
  (`HoldCoordinatedTransactionRunner`, `build_hold_version_condition_check_item`,
  `compute_ttl_disposal_at`) unmodified.
- Reuses `config/custody_period_config.py`'s `CustodyPeriodConfigLoader`
  unmodified — `report`'s custody-period duration value in
  `config/custody_periods.json` remains an empty object; no duration value
  is introduced by this change (out of scope, per ADR Decision 5).
- CLI-only invocation boundary preserved (ADR Decision 10) — no Lambda
  infrastructure change.

## 9. Assumptions

None requiring escalation. The technical design's Phase 6 contract
(§20.7.1–§20.7.3) is fully specified, including the exact regeneration
`SET`/`REMOVE` semantics and the exact forbidden-field guard shape, leaving
no ambiguous product-behavior decision to the implementer.

## 10. Validation Plan

- `uv run pytest -q` — full suite must pass with no regressions.
- `uv run ruff check <touched files>` — no new findings beyond the
  documented pre-implementation baseline (69 pre-existing repo-wide errors;
  7 in `main.py`, 4 in `test_engine.py`, 2 in
  `test_engine_no_phase5_mutation.py`, 0 elsewhere).
- `uv run ruff format --check <touched files>` — files clean before this
  change (`publisher.py`, `test_publisher.py`, `test_operator_cli_result.py`,
  plus both new files) must remain clean; files already needing
  reformatting before this change may remain so (no unrelated reformatting).
- `git diff --check` — no whitespace errors.
- Confirm `audit_platform_integrity/`'s four test files
  (`test_engine.py`, `test_repository.py`, `test_domains.py`,
  `test_engine_no_phase6_mutation.py`) pass unmodified (Phase 7
  consumer-contract preservation, §20.7.7).
