# Bug Report

## 1. Summary

QA contract validation for the Operator CLI `rcp` implementation found two blocking implementation defects:

1. Whitespace-only `RCP_*` stage config overrides are accepted as valid resolved stage values.
2. `audit schedule` dry-run infers a `finalization` schedule when the persisted `audit_config.json` does not contain a `finalization_schedule` block.

## 2. Investigation Context

- Source of report: QA validation.
- Branch context: `feature/operator_cli_rcp`.
- QA report: `docs/qa/operator_cli_rcp_test_report.md`.
- Added contract tests: `tests/api/test_operator_cli_rcp_contract.py`.
- Failing command reported by QA:
  `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/api/test_operator_cli_rcp_contract.py`
- Result reported by QA: `2 failed`.
- Related workflows:
  - Stage resource resolution before AWS client construction.
  - Operator CLI scheduling from persisted audit source-of-truth config.

## 3. Observed Symptoms

### Failure 1: whitespace-only stage override accepted

- Failing test: `test_stage_config_whitespace_env_override_is_rejected`.
- Test setup: writes valid `config/stages/dev.json`, then sets `RCP_CONFIG_BUCKET="   "`.
- Expected behavior: `StageConfigLoader(root=tmp_path).load("dev")` raises `EngineError`/`ConfigError` before any AWS client construction.
- Actual behavior: no exception is raised; a `StageConfig` is returned with `config_bucket` set to whitespace.
- Exact QA error evidence: `Failed: DID NOT RAISE <class 'packages.core.exceptions.EngineError'>`.

### Failure 2: missing finalization schedule block inferred

- Failing test: `test_schedule_missing_finalization_block_does_not_infer_finalization_schedule`.
- Test setup: persisted audit config includes `baseline_schedule` only; `finalization_schedule` is absent.
- Expected behavior: dry-run planned schedule types are `['baseline']`.
- Actual behavior: dry-run planned schedule types are `['baseline', 'finalization']`.
- Exact QA error evidence: `AssertionError: assert ['baseline', 'finalization'] == ['baseline']`.

## 4. Evidence Collected

Files inspected:

- `docs/qa/operator_cli_rcp_test_report.md`
- `tests/api/test_operator_cli_rcp_contract.py`
- `packages/config/stage_config.py`
- `packages/audit_scheduling/service.py`
- `packages/audit_scheduling/builders.py`
- `packages/audit_scheduling/validators.py`
- `packages/config/audit_validation_service.py`
- `docs/architecture/operator_cli_rcp_technical_design.md`
- `docs/product/operator_cli_rcp_spec.md`

Relevant code evidence:

- `packages/config/stage_config.py:67-74` rejects only an exact empty string for env overrides:
  `if env[env_name] == "": raise ConfigError(...)`; otherwise it assigns `resolved[field] = env[env_name]`.
- `packages/config/stage_config.py:75-77` validates required fields with `not value`, which does not reject whitespace-only strings.
- `packages/audit_scheduling/service.py:261-264` correctly maps `baseline_schedule` to `baseline` and disables baseline when absent for persisted configs.
- `packages/audit_scheduling/service.py:265-269` maps `repeated_schedule` to `repeated` and disables repeated when absent.
- `packages/audit_scheduling/service.py:249-270` does not normalize absent `finalization_schedule` to disabled for persisted configs.
- `packages/audit_scheduling/builders.py:93-94` defaults absent `finalization_schedule` to enabled: `(config.get("finalization_schedule") or {"enabled": True}).get("enabled", True)`.

Specification evidence:

- `docs/architecture/operator_cli_rcp_technical_design.md:169-170`: non-empty environment values override stage config values; required fields are validated before client construction.
- `docs/architecture/operator_cli_rcp_technical_design.md:192`: empty override values are invalid and must not mask JSON config values.
- `docs/architecture/operator_cli_rcp_technical_design.md:237`: `finalization_schedule` controls whether finalization is built; the builder must skip when missing or disabled for CLI scheduling.
- `docs/architecture/operator_cli_rcp_technical_design.md:656`: `audit schedule` loads schedule definitions only from persisted `audit_config.json`; missing/disabled blocks are skipped and no replacement schedules are inferred.
- `docs/product/operator_cli_rcp_spec.md:135`: missing required stage values must fail fast before AWS client construction.
- `docs/product/operator_cli_rcp_spec.md:387-389`: scheduling creates only schedules defined and enabled in `audit_config.json`.

## 5. Execution Path / Failure Trace

### Failure 1

1. Operator CLI/service path calls `StageConfigLoader.load(stage)`.
2. Loader reads `config/stages/{stage}.json` into `raw`.
3. Loader applies environment overrides in `ENV_OVERRIDES`.
4. For `RCP_CONFIG_BUCKET="   "`, the explicit empty-string check at `stage_config.py:69` does not fire because the value is not exactly `""`.
5. The whitespace string is assigned into `resolved['config_bucket']`.
6. Required-field validation at `stage_config.py:75-77` only checks type and truthiness, so whitespace passes.
7. Loader returns `StageConfig`, allowing invalid AWS resource configuration to proceed past the pre-client validation boundary.

### Failure 2

1. `AuditSchedulingService.schedule_from_persisted_audit(...)` reads persisted `audit_config.json` from S3 storage.
2. `_normalize_product_schedule_config(...)` maps product field names to builder inputs.
3. The persisted config contains `baseline_schedule`, so `config['baseline']` is enabled.
4. The persisted config does not contain `finalization_schedule`; normalization leaves the key absent.
5. `validate_schedule_config(...)` does not add or reject finalization schedule state.
6. `ScheduleBuilder.build_all(...)` evaluates absent `finalization_schedule` as `{'enabled': True}` and calls `build_finalization(...)`.
7. Dry-run output includes an inferred `finalization` schedule not present in persisted source-of-truth config.

## 6. Failure Classification

- Primary classification: Application Bug.
- Severity: Blocker.

Severity justification: QA sign-off is not approved. The failures violate explicit Operator CLI contract requirements for safe stage config validation and source-of-truth schedule creation. The schedule defect can create unexpected EventBridge finalization schedules in non-dry-run execution.

## 7. Root Cause Analysis

Confidence label: Confirmed Root Cause.

### Failure 1 root cause

- Immediate failure point: `StageConfigLoader.load()` returns a `StageConfig` for `RCP_CONFIG_BUCKET="   "`.
- Underlying root cause: env override validation treats only `""` as empty and required-field validation uses truthiness instead of stripped content.
- Supporting evidence: `packages/config/stage_config.py:69-76` contains exact-empty check and `not value` validation, neither of which rejects whitespace-only strings.

### Failure 2 root cause

- Immediate failure point: `ScheduleBuilder.build_all()` appends finalization when `finalization_schedule` is absent.
- Underlying root cause: the builder preserves the Phase 3 default of inferred finalization via `(config.get("finalization_schedule") or {"enabled": True})`, while the Operator CLI persisted-config contract requires missing blocks to be skipped.
- Supporting evidence: `packages/audit_scheduling/builders.py:93-94` directly defaults absent `finalization_schedule` to enabled; `packages/audit_scheduling/service.py:249-270` does not override this default for persisted audit configs.

Plausible contributing factor: existing unit coverage validated other Operator CLI paths but did not include whitespace-only env overrides or absent finalization schedule block behavior before QA added `tests/api/test_operator_cli_rcp_contract.py`.

## 8. Confidence Level

High.

The failing assertions map directly to inspected code paths. The observed behavior is explained by explicit conditions in `stage_config.py` and `builders.py`, and the expected behavior is documented in the product/architecture specs.

## 9. Recommended Fix

Likely owner: backend/full-stack developer owning Operator CLI shared services.

### Fix 1: reject whitespace-only stage overrides and required values

- Likely file/function: `packages/config/stage_config.py`, `StageConfigLoader.load`.
- Expected correction:
  - Treat any explicit env override whose value is empty after `strip()` as invalid.
  - Apply the same non-blank string validation to resolved required fields from both JSON and env overrides.
  - Do not silently fall back to file values when an override is explicitly set but blank/whitespace.
- Caution:
  - Preserve precedence for valid non-empty env overrides.
  - Keep failure as controlled `ConfigError`/`EngineError` with existing error code pattern `STAGE_CONFIG_ERROR`.

### Fix 2: do not infer finalization schedule for persisted CLI scheduling

- Likely files/functions:
  - `packages/audit_scheduling/builders.py`, `ScheduleBuilder.build_all`.
  - `packages/audit_scheduling/service.py`, `_normalize_product_schedule_config` if compatibility separation is needed.
- Expected correction:
  - For persisted product schedule blocks, missing `finalization_schedule` must be treated as disabled.
  - Only call `build_finalization(...)` when `finalization_schedule` is present and `enabled` is true.
  - If existing non-CLI Phase 3 behavior still requires inferred finalization, introduce an explicit compatibility flag or normalized field rather than keeping implicit default behavior in `build_all` for all callers.
- Caution:
  - Existing behavior for `baseline` may also default to enabled in the builder, but `_normalize_product_schedule_config` already disables absent `baseline_schedule`; avoid regressing Phase 3 tests while satisfying the Operator CLI source-of-truth contract.

## 10. Suggested Validation Steps

After the fix, run targeted validation:

1. `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/api/test_operator_cli_rcp_contract.py`
   - Expected: both QA contract tests pass.
2. `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit/test_operator_cli_rcp.py`
   - Expected: existing Operator CLI unit coverage remains green.
3. `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit`
   - Expected: no regressions to Phase 1/2/3 shared scheduling and lifecycle behavior.
4. Add/confirm unit coverage for every explicit `RCP_*` override set to `""` and whitespace-only strings.
5. Add/confirm scheduling coverage for absent and disabled `finalization_schedule` in persisted `audit_config.json`, plus present/enabled finalization.

## 11. Open Questions / Missing Evidence

- Whether legacy non-CLI scheduling callers intentionally depend on inferred finalization when no `finalization_schedule` key is provided. If yes, the fix should isolate persisted Operator CLI semantics through normalization or an explicit builder option rather than globally changing all scheduling callers without regression review.

## 12. Final Investigator Decision

Ready for developer fix.
