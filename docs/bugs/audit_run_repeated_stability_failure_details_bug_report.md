# Bug Report

## 1. Summary
During HITL validation, `rcp audit run --scenario-type repeated_stability --stage dev` exits as failed but text output only says `summary: orchestrator execution failed` and `next_step: none`. The CLI does not surface the sanitized handler failure summary, error code, generated `run_id`, scenario context, or diagnostic next step.

## 2. Investigation Context
- Source of report: HITL validation.
- Branch context: `feature/profile_driven_config_init` remains the active correction branch.
- Related feature/workflow: Enhanced `rcp config init` default profile system and manual `rcp audit run` Lambda execution diagnostics.
- User command:

```bash
rcp audit run \
  --client-id client_layer_1_validation_client_b5817642 \
  --audit-id audit_20260524_ec3f2d9b \
  --scenario-type repeated_stability \
  --stage dev
```

## 3. Observed Symptoms
- Observed CLI text output:

```text
FAILED: audit run
stage: dev
client_id: client_layer_1_validation_client_b5817642
audit_id: audit_20260524_ec3f2d9b
summary: orchestrator execution failed
next_step: none
```

- Expected behavior: failed manual runs should display safe actionable failure details, including at least the handler `failure_summary.error_type`, safe message, generated `run_id` when available, scenario type, and a next step pointing to JSON output / CloudWatch / config validation depending on error class.
- Actual behavior: text renderer reports only generic failure and `next_step: none`.

## 4. Evidence Collected
Files inspected:
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/storage/lambda_client.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/orchestrator/service.py`
- `packages/config/loaders.py`
- `packages/config/validators.py`
- `packages/storage/s3_client.py`
- `packages/audit_scheduling/constants.py`
- `src/release_confidence_platform/config/generators/audit_config_generator.py`
- `src/release_confidence_platform/config/generators/endpoints_generator.py`
- `config/defaults/dev.json`

Key evidence:
- Manual run sends `scenario_type`, `triggered_by: manual`, `schedule_type: manual`, and `stage`, then invokes Lambda synchronously with `invocation_type="RequestResponse"` (`manual_run_service.py:29-58`).
- The Lambda wrapper decodes synchronous handler payload into `invocation.handler_response` and copies only `handler_status` to `invocation.handler_status` (`lambda_client.py:50-64`). It does not promote `failure_summary`, `run_id`, or handler error details to the command's top-level data.
- `run_command` marks handler failure and changes the summary to `orchestrator execution failed`, but returns nested invocation data without extracting handler failure fields (`operator_cli/services.py:258-274`).
- Text rendering only prints selected top-level fields (`client_id`, `audit_id`, etc.), `summary`, and generic `next_step: none` for normal commands (`operator_cli/result.py:45-59`, `result.py:92-107`). It does not inspect `payload`, `invocation.handler_response`, `failure_summary`, `error_type`, `handler_status`, or nested `run_id`.
- Backend orchestrator failure responses include sanitized `failure_summary` when execution reaches `CoreEngineOrchestrator.run()` failure handling (`apps/backend/orchestrator/service.py:209-256`). The response shape is `{client_id, audit_id, run_id, status: FAILED, failure_summary: {error_type, message}}` when event validation has succeeded.
- Generic unhandled orchestrator exceptions are intentionally collapsed to `EngineError("ORCHESTRATION_ERROR", "Orchestration failed")`, losing the specific exception type from the handler response (`apps/backend/orchestrator/service.py:142-147`).
- The orchestrator does not branch on `repeated_stability` schedule configuration. It validates only basic event identifiers, loads client/audit/endpoints config, validates audit/endpoints, runs each endpoint for `payload_iterations`, writes raw results, and marks metadata completed (`apps/backend/orchestrator/service.py:45-133`, `service.py:163-170`).
- `repeated_stability` is a supported taxonomy value (`packages/audit_scheduling/constants.py:26-48`) and default generated audit config enables `repeated_schedule` with `scenario_type: repeated_stability` (`audit_config_generator.py:51-57`, `config/defaults/dev.json:37-42`).
- Endpoint execution failures are captured as raw `RunnerOutcome` failure rows rather than handler failures (`apps/backend/runner/api_runner.py:122-152`). Therefore the observed `status=failed` most likely occurred before/after endpoint execution, not from an HTTP assertion/connection failure.
- Config load errors are currently generic: `S3StorageClient.read_json()` raises `ConfigError("Config object could not be loaded", "CONFIG_LOAD_ERROR")` without the missing key or AWS error code (`packages/storage/s3_client.py:20-29`). This can make missing client/audit/endpoints objects indistinguishable in the handler failure summary.
- Empty endpoints are invalid for backend execution: `packages/config/validators.py:46-53` raises `CONFIG_VALIDATION_ERROR` with message `Endpoint config must include at least one endpoint`.

## 5. Execution Path / Failure Trace
1. CLI `audit run` builds a manual payload with the supplied `client_id`, `audit_id`, and `scenario_type=repeated_stability`.
2. CLI invokes the configured orchestrator Lambda synchronously.
3. Lambda handler creates S3/DynamoDB/Secrets clients and calls `CoreEngineOrchestrator.run(event)`.
4. Orchestrator validates the event, generates a `run_id` if absent, checks duplicate raw result / metadata, writes STARTED metadata, loads client/audit/endpoints config from S3, validates configs, resolves secrets, executes endpoints, writes raw results, and updates terminal metadata.
5. On an `EngineError`, orchestrator returns sanitized `{status: FAILED, failure_summary: {error_type, message}, ...}`. On non-`EngineError`, it returns generic `ORCHESTRATION_ERROR` / `Orchestration failed`.
6. CLI receives the handler failure through `invocation.handler_response` but text rendering ignores nested failure details and always prints `next_step: none`.

## 6. Failure Classification
- Primary category: Application Bug.
- Severity: High.

Justification: HITL validation can detect handler failure, but operators receive no actionable safe error code, message, run id, or next step. This blocks efficient diagnosis of a core manual audit workflow even though the backend likely returned some sanitized details.

## 7. Root Cause Analysis
Confidence label: Most Likely Root Cause.

Immediate failure point:
- CLI text rendering for failed `audit run` results does not render nested synchronous Lambda handler failure details.

Underlying root cause:
- The synchronous response contract is nested under `data.invocation.handler_response`, while `render()` only displays a small fixed set of top-level fields and emits `next_step: none` for failed audit runs. `ManualRunInvocationService` / `run_command` do not promote safe handler fields (`failure_summary`, `run_id`, `handler_status`) into top-level `CommandResult.data` for text output.

Likely backend failure source for this specific run:
- Cannot be confirmed without `--output json` or CloudWatch logs. Code evidence rules out unsupported `repeated_stability` and repeated schedule lookup as primary causes: the orchestrator does not perform scenario-specific schedule lookup during manual execution, and `repeated_stability` is supported by taxonomy/defaults.
- Most likely backend failure classes are config/storage/metadata issues before/after endpoint execution, such as missing S3 config objects, empty endpoints config, invalid endpoint config, duplicate run metadata/raw result, secret resolution failure, or raw-result/metadata write failure.
- If the audit was created from default `config init` output without adding endpoints, backend execution would fail with `CONFIG_VALIDATION_ERROR: Endpoint config must include at least one endpoint`; however normal `rcp audit create` validation should also reject that unless bypassed or legacy state exists.

Contributing factors:
- Generic `S3StorageClient.read_json()` message (`Config object could not be loaded`) hides which config key failed to load.
- Generic top-level `except Exception` in the orchestrator collapses non-`EngineError` details to `ORCHESTRATION_ERROR`, so some safe diagnostics may be unavailable from the handler response and require CloudWatch.

## 8. Confidence Level
High for the CLI diagnostics/rendering defect because the relevant code path directly shows nested handler failure data is not rendered.

Medium for the actual backend execution cause because no `--output json` payload or CloudWatch log excerpt was provided.

## 9. Recommended Fix
Likely owner: full-stack / CLI + backend.

Concrete fix guidance:
1. In `src/release_confidence_platform/core/manual_run_service.py` and/or `src/release_confidence_platform/operator_cli/services.py`, extract safe fields from `response["handler_response"]` when `handler_status` is failed:
   - `handler_response.run_id`
   - `handler_response.failure_summary.error_type`
   - `handler_response.failure_summary.message`
   - submitted `scenario_type`
   - `handler_status`
2. Promote those fields to top-level `CommandResult.data` under safe names such as `run_id`, `scenario_type`, `error_code`, `failure_message`, and `failure_summary`.
3. In `src/release_confidence_platform/operator_cli/result.py`, add audit-run failure rendering that prints these fields and an actionable next step instead of `next_step: none`.
4. Preserve `--output json` with the full sanitized nested invocation payload, but make text output sufficient for common failures.
5. Backend improvement: in `packages/storage/s3_client.py`, make `read_json(key)` raise sanitized `CONFIG_LOAD_ERROR` context that identifies the config object label/key or missing-object class without exposing secrets. This will distinguish missing `client_config`, `audit_config`, and `endpoints.json` in handler failure summaries.
6. Backend improvement: if acceptable under sanitization rules, log and/or include a safe `cause_type` for unexpected orchestrator exceptions while preserving the public `ORCHESTRATION_ERROR` message.

Cautions:
- Do not expose endpoint payloads, headers, secret refs, full URLs with sensitive query strings, AWS principals, or credentials.
- Keep failure responses sanitized and bounded.

## 10. Suggested Validation Steps
- Unit tests for failed `audit run` text rendering where fake Lambda returns:
  - `handler_response.status = "FAILED"`
  - `handler_response.run_id = "safe_run_123"`
  - `handler_response.failure_summary = {"error_type": "CONFIG_LOAD_ERROR", "message": "Config object could not be loaded"}`
- Assert text output includes `run_id`, `scenario_type`, `error_code`, safe message, and a non-`none` next step.
- Unit test that `--output json` still contains sanitized `invocation.handler_response`.
- Backend unit test for missing endpoints/config object producing a safe, specific `CONFIG_LOAD_ERROR` context.
- Manual HITL rerun with `--scenario-type repeated_stability` after deployment; expected behavior is either success or failed output with actionable details.
- CloudWatch verification that the same generated `run_id` appears in `run_started` / `run_failed` logs and DynamoDB run metadata.

## 11. Open Questions / Missing Evidence
- Need the `rcp audit run ... --output json` response to confirm whether `invocation.handler_response.failure_summary` already contains the backend error.
- Need CloudWatch log excerpt for the matching Lambda invocation to identify the actual backend failure (`CONFIG_LOAD_ERROR`, `CONFIG_VALIDATION_ERROR`, `STORAGE_ERROR`, etc.).
- Need confirmation that deployed Lambda code matches this branch's current handler/orchestrator changes.
- Need confirmation whether the uploaded `endpoints.json` for `client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b` contains at least one executable endpoint.

## 12. Final Investigator Decision
Ready for developer fix for the CLI failure-detail rendering defect.

Needs more evidence to identify the exact backend cause of this specific `repeated_stability` failed run.
