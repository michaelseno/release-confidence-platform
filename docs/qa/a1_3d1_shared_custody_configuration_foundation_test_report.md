# Test Report — A1.3d.1 Shared Custody-Configuration Foundation

## 1. Execution Summary

- New suite (`tests/unit/config/test_custody_period_config.py` + `tests/unit/test_infra_configuration.py`): **70 passed, 2 skipped, 0 failed** (72 collected)
- Full repository suite (`uv run pytest -q`): **1811 passed, 2 skipped, 0 failed**
- `ruff check` on new/modified Python files: **All checks passed**
- `ruff format --check` on new/modified Python files: **3 files already formatted**
- Direct `npx sls print --stage dev` invocation (infra/ dir): **fails as expected**, all six `custom.custodyPeriodDays.<class>` references reported unresolved

## 2. Detailed Results — Per Checklist Item

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Scope diff matches expected file set | **PASS** | `git status --short` / `git diff --stat main` show exactly: `config/custody_periods.json` (new), `src/release_confidence_platform/config/custody_period_config.py` (new), `tests/unit/config/` (new, incl. `__init__.py`), `infra/serverless.yml` (modified), `tests/unit/test_infra_configuration.py` (modified), two `docs/backend/a1_3d1_*` files (new), and this QA report itself, `docs/qa/a1_3d1_shared_custody_configuration_foundation_test_report.md` (new — part of the completion package). `AGENTS.md` confirmed untracked, unrelated pre-existing file. No hit for `reliability_intelligence/`, `deterministic_reporting/`, `audit_platform_integrity/`, `operator_cli/`, or `infra/resources/s3.yml` in status output. |
| 2 | `config/custody_periods.json` schema exactness | **PASS** | File read directly: exact `{"evidentiary_classes": {5 classes: {}}, "operational_durations": {"retention_marker": {}}}` shape, zero configured stage keys anywhere. |
| 3 | `custody_period_config.py` correctness | **PASS** | Boolean check (`isinstance(value, bool)`) is a separate `or`-clause evaluated before/alongside the int check on line 139 — `True`/`False` cannot slip through as `1`/`0`. `retention_marker` absent from `EVIDENCE_CLASSES` tuple (lines 41–47), rejected via the class-membership check at line 83. `grep -n "os.environ\|os.getenv"` on the file returned no matches — no env-var fallback anywhere. `ConfigError` is imported from `release_confidence_platform.core.exceptions` (line 34), not redefined in this module; its constructor signature `(message, error_type)` is called consistently in correct positional order. Counted **10 raise sites**, all passing the module constant `_ERROR_TYPE = "CUSTODY_PERIOD_CONFIG_MISSING"` — confirmed by `grep -c "_ERROR_TYPE"` (11 = 1 definition + 10 usages). |
| 4 | New test suite execution + coverage completeness | **PASS** | Ran directly: 70 passed / 2 skipped (both pre-existing/documented boundary skips, not new-code failures). Coverage confirmed present as **distinct** test functions/parametrizations: all 5 evidence classes × positive path (fixture-based), all 3 stages × positive path, `retention_marker` rejection as evidence class, and all 13 failure classifications — missing file, malformed JSON, non-object root, missing `evidentiary_classes` key, malformed `evidentiary_classes` key, unknown class, unsupported stage, missing stage property, null, Boolean (both `True` and `False` parametrized), string, float, zero, negative. No classification was collapsed or skipped. Additional coverage beyond the minimum: error-message path-leak sanitization test, production-file schema/no-configured-value assertion (read-only), and an explicit no-env-fallback test using `monkeypatch`. |
| 5 | No test writes a real value into the production JSON | **PASS** | `grep` of all `write_text`/`_write_custody_periods_json*` calls confirms every write targets `tmp_path`-derived paths only. The two tests that touch the real `config/custody_periods.json` (`test_production_custody_periods_json_has_expected_schema_and_no_configured_values`, `test_production_custody_periods_json_resolves_nothing_for_any_class_or_stage`) only `read_text()`/`json.load()` it — no write path to the tracked file exists anywhere in the test module. |
| 6 | Full existing suite unaffected | **PASS** | `uv run pytest -q` → **1811 passed, 2 skipped, 0 failed**. The 2 skips are the same pre-existing/documented boundary skips seen in the scoped run (`test_serverless_artifact_contains_backend_handler_and_requests_dependencies_if_present` — no packaged artifact present; `test_serverless_variable_resolution_requires_serverless_cli` — deliberately self-skipping documentation test). No new failures, no new skips introduced. |
| 7 | `ruff check` / `ruff format --check` | **PASS** | `ruff check` on the three new/modified Python files → "All checks passed!". `ruff format --check` → "3 files already formatted". |
| 8 | `infra/serverless.yml` diff scope | **PASS** | `git diff main -- infra/serverless.yml`, content-line diff (comments excluded) shows **exactly** the six `custodyPeriodDays.<class>` values changed from inline `{}` literals to `${file(../config/custody_periods.json):...}` references with correct schema paths (`evidentiary_classes.<class>.${self:provider.stage}` for the five evidentiary classes; `operational_durations.retention_marker.${self:provider.stage}` for the marker). Direct line comparison confirms `functions.auditAggregation.environment.CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` is **byte-for-byte identical** between `main` and this branch (`${self:custom.custodyPeriodDays.aggregate_metadata.${self:provider.stage}}` in both). No new `functions:` entry, no new `environment:` block elsewhere in the diff — the full diff is confined to the `custom.custodyPeriodDays` block plus its surrounding comments. |
| 9 | `infra/resources/s3.yml` zero diff vs main | **PASS** | `git diff main -- infra/resources/s3.yml` produced no output. |
| 10 | `sls print` fail-closed verification | **PASS** | `npx` is available in this environment (v11.17.0). Ran `npx sls print --stage dev` directly from `infra/`: fails at variable-resolution time with `Cannot resolve variable at "custom.custodyPeriodDays.<class>": Value not found at "file" source` for **all six** keys (`raw_evidence`, `aggregate_metadata`, `intelligence`, `report`, `certificate`, `retention_marker`). This is the expected, intentional fail-closed behavior (every class/stage left unconfigured), not a defect. The suite's own `test_serverless_print_fails_on_unresolved_custody_period_config_file_references` executed this same check (not skipped, since `npx` was available) and passed. |

## 3. Failed Tests

None. No failures in the new suite or the full suite.

## 4. Failure Classification

Not applicable — zero failures observed.

## 5. Observations

- No flakiness observed; both the scoped and full-suite runs are deterministic pure-local-file-I/O tests (no network, no AWS calls).
- The 2 skips present in both the scoped and full-suite runs are pre-existing/intentional (packaged-artifact-not-present skip, and a documentation-boundary test that always self-skips per its own docstring) — not related to this change and not masking uncovered behavior.
- Test design quality is notably strong: fixtures are fully isolated via `tmp_path`, the production file is only ever read (never mutated) by tests, and the suite goes beyond the minimum required coverage (path-leak sanitization, env-fallback-absence, schema-boundary-separation tests).

## 6. Regression Check

- Full suite: 1811 passed / 2 skipped / 0 failed, identical skip set to what the new/modified files alone produce — no regression introduced.
- `infra/resources/s3.yml`: zero diff vs `main` — confirmed no regression risk in the S3 lifecycle resource template.
- `auditAggregation`'s `CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA` environment binding: byte-for-byte unchanged vs `main`.
- No file under any excluded path (`reliability_intelligence/`, `deterministic_reporting/`, `audit_platform_integrity/`, `operator_cli/`) or any `HoldRepository` injection appears in the diff.
- No reference to issue #118 anywhere in the diff.

## 7. QA Decision

All 10 independently-verified checklist items PASS. No defects found. No scope violations. No regressions. Evidence for every claim was independently re-derived (direct file reads, direct greps, direct test execution, direct `git diff`, direct `sls print` invocation) rather than accepted from the implementation report.

**[QA SIGN-OFF APPROVED]**
