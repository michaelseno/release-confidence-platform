# Implementation Report

## 1. Summary of Changes

Implemented Subphase A1.3d.1: the shared, authoritative custody-period
configuration foundation. Introduced `config/custody_periods.json` (fixed
schema, no duration values), `CustodyPeriodConfigLoader.resolve(evidence_class,
stage) -> int` (`src/release_confidence_platform/config/custody_period_config.py`),
and migrated `infra/serverless.yml`'s `custom.custodyPeriodDays` block
(all six keys) from inline empty-mapping literals to
`${file(../config/custody_periods.json):...}` external-file references.
No phase-specific (Phase 5/6/7) wiring, repository/publisher change, CLI
dispatch change, or Lambda infrastructure was introduced -- consistent
with Technical Design Section 20.12's A1.3d.1 scope and ADR Decision
10/Invariant 28.

## 2. Files Modified

- `config/custody_periods.json` (new, 12 lines) -- fixed schema per
  Technical Design Section 20.3; every evidentiary class and the
  `retention_marker` operational duration ship as empty objects.
- `src/release_confidence_platform/config/custody_period_config.py` (new,
  151 lines) -- `CustodyPeriodConfigLoader` class and `resolve()` method.
- `infra/serverless.yml` (modified, net +/- within a 214-line file) --
  `custom.custodyPeriodDays` block migrated to six `${file(...)}`
  references; explanatory comment block rewritten to document the
  consolidation. No other section of the file was touched.
- `tests/unit/config/__init__.py` (new, empty) -- package marker,
  mirroring the existing `tests/unit/<subpackage>/__init__.py` convention.
- `tests/unit/config/test_custody_period_config.py` (new, 336 lines) --
  43 unit tests for `CustodyPeriodConfigLoader`.
- `tests/unit/test_infra_configuration.py` (modified, 610 lines total) --
  replaced the now-obsolete `test_custody_period_days_config_defines_no_value_for_any_stage`
  test (which asserted the prior inline-`{}` shape) with reference-shape
  and schema-boundary tests matching the migrated file-reference shape;
  rewrote `test_serverless_print_fails_on_unresolved_aggregate_metadata_custody_period`
  (renamed `test_serverless_print_fails_on_unresolved_custody_period_config_file_references`)
  to match the new, earlier failure surface (see Section 10); added a
  production-file structural/unconfigured-state test.

## 3. API Contract Implementation

No API contract changes.

## 4. Data / Persistence Implementation

No data model or storage changes. `CustodyPeriodConfigLoader` is a pure
local file read plus validation with zero AWS interaction.

## 5. Key Logic Implemented

- `CustodyPeriodConfigLoader.resolve(evidence_class, stage)`:
  1. Rejects any `evidence_class` not in the five-member `EVIDENCE_CLASSES`
     tuple (`raw_evidence`, `aggregate_metadata`, `intelligence`, `report`,
     `certificate`) -- `retention_marker` is deliberately excluded here,
     since it is an operational duration (Technical Design's
     `operational_durations` namespace), not an evidentiary class.
  2. Rejects any `stage` not in `stage_config.STAGES` (`dev`, `staging`,
     `prod`) -- reuses the project's existing stage vocabulary rather than
     inventing a new one.
  3. Reads `config/custody_periods.json` from the resolved repo root
     (found by walking the module's own parent directories, mirroring
     `StageConfigLoader._default_root()`'s pattern), raising
     `CUSTODY_PERIOD_CONFIG_MISSING` for a missing file or malformed JSON.
  4. Validates the parsed root is a JSON object, that `evidentiary_classes`
     is present and itself an object, that the requested class's nested
     object is present, and that the requested stage key exists on it --
     each failure raises the same `CUSTODY_PERIOD_CONFIG_MISSING` code,
     with no distinguishing sub-code, per Technical Design Section 20.4.
  5. Validates the resolved value: explicitly rejects `None` and `bool`
     *before* the `int` check (Python's `bool` is an `int` subclass, so the
     Boolean check is ordered first to avoid `isinstance(True, int)`
     silently passing), then rejects any non-`int` value (strings, floats),
     then rejects `<= 0`.
  6. Returns the validated positive integer.
- `infra/serverless.yml` migration: all six `custom.custodyPeriodDays.<class>`
  keys now read `${file(../config/custody_periods.json):evidentiary_classes.<class>.${self:provider.stage}}`
  (`retention_marker` reads `operational_durations.retention_marker.${self:provider.stage}}`
  instead). The `auditAggregation` function's
  `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` environment binding text is
  byte-for-byte unchanged -- only the value `custom.custodyPeriodDays.aggregate_metadata`
  itself resolves from changed (inline literal to file reference).

## 6. Security / Authorization Implemented

No authentication/authorization surface introduced. Error messages
contain no raw file paths, no raw JSON content, and no stack traces
(verified by a dedicated regression test,
`test_error_message_does_not_leak_raw_file_path`). No environment-variable
fallback exists anywhere in the loader (verified by
`test_no_environment_variable_fallback_exists`, which sets plausible
fallback-named env vars and confirms they have zero effect on resolution).

## 7. Error Handling Implemented

Every condition Technical Design Section 20.4's exception contract lists
raises `ConfigError(<sanitized message>, "CUSTODY_PERIOD_CONFIG_MISSING")`
with no distinguishing sub-code: missing file, malformed JSON, non-object
root, missing/malformed `evidentiary_classes`, unknown evidence class,
unsupported stage, missing stage property, `null`, Boolean (both `True`
and `False` explicitly tested), string, float (including an integral-value
float, e.g. `30.0`), zero, and negative integer. All 12+ conditions have a
dedicated regression test in `tests/unit/config/test_custody_period_config.py`.

## 8. Observability / Logging

No logging added -- this is a synchronous, exception-raising
configuration-resolution utility with no side effects to log, consistent
with `stage_config.py`'s own logging-free convention.

## 9. Assumptions Made

- `config/custody_periods.json` lives at the repo root (sibling to the
  pre-existing `config/defaults/` and `config/stages/`), matching Technical
  Design Section 20.3/20.12's explicit path with no ambiguity.
- `tests/unit/config/` follows the `__init__.py` package-directory
  convention already established by sibling test packages
  (`tests/unit/reliability_intelligence/`, etc.).

Neither assumption affects external behavior, data shape, security,
billing, permissions, or API contracts; both are directly confirmed
against existing repository convention, not invented.

## 10. Validation Performed

- `pytest tests/unit/config/test_custody_period_config.py -v` -- **43
  passed**, 0 failed, 0 skipped.
- `pytest tests/unit/test_infra_configuration.py -v` -- **27 passed, 2
  skipped** (the 2 skips are pre-existing and unrelated: one documents the
  Serverless-CLI-required boundary by design, the other skips a
  packaged-artifact test when no `.serverless/*.zip` artifact is present
  locally -- both skip for the same reason before this change).
  Critically, `test_serverless_print_fails_on_unresolved_custody_period_config_file_references`
  **executed for real** (Node/`npx` toolchain is available in this
  environment) rather than skipping, and confirmed `npx sls print --stage
  dev` fails with all six `custom.custodyPeriodDays.<class>` references
  named as unresolved.
- `pytest -q` (full existing suite) -- **1811 passed, 2 skipped** (same 2
  pre-existing skips as above). No regression introduced anywhere else in
  the suite.
- Manual `npx sls print --stage dev` invocation (both before and after the
  `infra/serverless.yml` edit) to directly observe and correctly assert
  against the exact fail-closed error text the migration produces (see
  Section 11 for the specific finding this surfaced).

## 11. Known Limitations / Follow-Ups

- **Observation, not a defect in this subphase's scope**: prior to this
  migration, `sls print`'s resolution failure surfaced at the *downstream
  consumer* reference paths (e.g.
  `functions.auditAggregation.environment.CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA`,
  and each of `resources.0.Resources.RawResultsBucket.Properties.LifecycleConfiguration.Rules.N.Expiration.Days`).
  After this migration, the failure surfaces one level earlier, directly
  at `custom.custodyPeriodDays.<class>` itself, because the
  `${file(...)}` lookup inside `custom.custodyPeriodDays.<class>` now
  fails before Serverless ever attempts to resolve any downstream
  reference into it. This is confirmed, by direct `npx sls print`
  invocation, to still be a full, equally fail-closed failure covering all
  six keys -- it is an earlier and equally strict failure point, not a
  weaker one. `infra/resources/s3.yml` itself is unmodified per this
  subphase's explicit scope (`Do NOT touch infra/resources/s3.yml`), so no
  action was taken on this observation; it is noted here for
  architecture/QA awareness ahead of a real duration value ever being
  supplied to `config/custody_periods.json` (a separate, later Product
  Strategy decision, out of scope for A1.3d.1 through A1.3d.4 alike).
- This subphase intentionally leaves every custody-period value
  unconfigured. `sls print --stage dev` (or any stage) is **expected to
  fail** at variable-resolution time right now -- this is correct
  fail-closed behavior per ADR Decision 5/Invariant 3, not a defect, and
  is not something a later subphase needs to "fix" as part of A1.3d.2/.3/.4.
- No phase-specific wiring (A1.3d.2/.3/.4) is included, by design --
  `IntelligenceRepository`/`ReportRepository`/`CertificationRepository`,
  their publishers, and `operator_cli/main.py`'s dispatch blocks remain
  entirely untouched and unaware of `CustodyPeriodConfigLoader`.

## 12. Commit Status

Not committed. Per explicit instruction, all changes are left
uncommitted/staged on branch `feature/a1-3d1-shared-custody-configuration`
for QA review. No push, no PR.
