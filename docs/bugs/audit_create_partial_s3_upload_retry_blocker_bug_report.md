# Bug Report

## 1. Summary

During HITL validation, `rcp audit create --stage dev` now fails with `CONFIG_OBJECT_EXISTS` after an earlier failed create attempt uploaded S3 config artifacts but did not complete cleanly. The current create flow protects existing config objects, but it does not provide idempotent retry, adopt/reconcile, rollback, or actionable partial-failure recovery when S3 writes succeeded and DynamoDB metadata creation previously failed.

## 2. Investigation Context

- Source of report: HITL validation.
- Branch context: `feature/profile_driven_config_init` remains the active HITL correction branch.
- Related feature/workflow: Enhanced `rcp config init` Default Profile System -> generated local config bundle -> non-dry-run `rcp audit create` against real dev AWS resources.
- Reported command:

```bash
rcp audit create \
  --client-config .local-configs/client_layer_1_validation_client_b5817642/client_config.json \
  --audit-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json \
  --endpoints-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json \
  --stage dev
```

- Reported exported resources:
  - `RCP_AWS_PROFILE=rk-reliability`
  - `RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results`
  - `RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata`
  - `RCP_AWS_REGION=us-east-1`

## 3. Observed Symptoms

Reported current CLI output:

```text
ERROR: audit create failed
stage: dev
code: CONFIG_OBJECT_EXISTS
message: Config object exists
next_step: correct the error and retry
```

Expected behavior for a valid first create is: upload three config artifacts and create one DRAFT audit metadata item.

Expected behavior after a partial prior create is not currently defined well enough for operators. At minimum, the command should identify partial state and provide safe recovery guidance. Preferably, retry should be idempotent or should reconcile/adopt consistent existing objects and finish metadata creation.

## 4. Evidence Collected

Files/configs inspected:

- `src/release_confidence_platform/core/audit_creation_service.py`
  - `config_keys()` builds the persisted S3 keys at lines 19-24.
  - `AuditCreationService.create_from_files()` validates files, reads metadata, rejects existing S3 keys, writes S3 objects, then writes metadata at lines 50-104.
- `src/release_confidence_platform/storage/s3_client.py`
  - `object_exists()` uses `head_object()` at lines 78-89.
  - `write_json()` independently checks existence again and raises `CONFIG_OBJECT_EXISTS` when `overwrite=False` at lines 91-104.
- `src/release_confidence_platform/storage/audit_metadata_client.py`
  - Metadata key shape is `PK=CLIENT#<client_id>`, `SK=AUDIT#<audit_id>` at lines 31-32.
  - `put_audit_metadata_once()` is conditional create-only at lines 141-143 and `_put_conditional()` uses `attribute_not_exists(PK) AND attribute_not_exists(SK)` at lines 291-302.
- `src/release_confidence_platform/operator_cli/result.py`
  - No code-specific next-step guidance exists for `CONFIG_OBJECT_EXISTS`; it falls back to `correct the error and retry` at lines 307-329.
- Local config bundle:
  - client_id: `client_layer_1_validation_client_b5817642`
  - audit_id: `audit_20260524_ec3f2d9b`

Likely S3 objects created by the failed prior attempt:

```text
s3://release-confidence-platform-dev-raw-results/configs/client_layer_1_validation_client_b5817642/client_config.json
s3://release-confidence-platform-dev-raw-results/configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json
s3://release-confidence-platform-dev-raw-results/configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json
```

Likely DynamoDB metadata key, if it exists:

```text
PK = CLIENT#client_layer_1_validation_client_b5817642
SK = AUDIT#audit_20260524_ec3f2d9b
```

## 5. Execution Path / Failure Trace

1. `services.create_command()` loads stage config and validates local runtime files before AWS setup.
2. `AuditCreationService.create_from_files()` validates the same files again and derives the three config keys from `client_id` and `audit_id`.
3. It calls `repository.get_audit_metadata(client_id, audit_id)`.
4. In non-force mode, it checks all three S3 keys with `self.s3.object_exists(key)`.
5. If any config key exists, it raises `StorageError("Config object exists", "CONFIG_OBJECT_EXISTS")` before attempting any write or metadata recovery.
6. On a clean first attempt, the service writes S3 config objects first, then creates DynamoDB metadata last.
7. If metadata creation fails after S3 writes, the next retry sees existing S3 objects and stops at step 5. There is no rollback from the prior failed attempt and no idempotent/adopt path to complete metadata creation.

## 6. Failure Classification

- Primary classification: Application Bug.
- Severity: Blocker.

Severity justification: this blocks HITL completion of the config-init -> audit-create workflow after a real AWS partial write. The workflow is recoverable by manual operator cleanup or by using a completely new client/audit bundle, but the CLI currently gives generic retry guidance that will continue to fail.

## 7. Root Cause Analysis

Confidence label: Most Likely Root Cause.

Immediate failure point:

- `AuditCreationService.create_from_files()` raises `CONFIG_OBJECT_EXISTS` at lines 89-91 when `self.s3.object_exists(key)` returns true for one or more config keys.

Underlying root cause:

- `audit create` performs non-transactional S3 writes before DynamoDB metadata creation, and the retry path treats any existing config object as a duplicate instead of recognizing and recovering from a prior partial create. There is no rollback of S3 objects if metadata creation fails, no idempotent retry for matching artifacts, no adopt/reconcile mode, and `--force` cannot recover the common “S3 objects exist but metadata is absent” state because force requires existing metadata first.

Supporting evidence:

- S3-before-metadata ordering is directly shown in `audit_creation_service.py:95-104`.
- Duplicate-object preflight happens before metadata create in non-force mode at `audit_creation_service.py:88-93`.
- Force mode requires existing metadata at `audit_creation_service.py:78-82`, so it cannot repair missing-metadata partial state.
- Renderer guidance for `CONFIG_OBJECT_EXISTS` is generic and non-actionable (`result.py:307-329`).

Contributing factors:

- The create operation spans S3 and DynamoDB without a transaction boundary.
- The client config key is per-client (`configs/<client_id>/client_config.json`), so even using a new `audit_id` with the same `client_id` can still be blocked by the existing client config object.

## 8. Confidence Level

High for the code-path diagnosis. The exact remote state still needs confirmation: the existing object set and whether the DynamoDB metadata item exists were inferred from the user report and source code, not directly queried during this investigation.

## 9. Recommended Fix

Likely owner: backend/full-stack CLI storage workflow.

Recommended implementation:

1. Update `src/release_confidence_platform/core/audit_creation_service.py` to handle partial create state explicitly before raising `CONFIG_OBJECT_EXISTS`.
2. Add a recovery decision path after metadata lookup and S3 head checks:
   - If metadata exists:
     - In non-force mode, return `AUDIT_EXISTS` or a clearer already-created/idempotent success response if the request config hash and existing metadata match the input contract.
     - Preserve `--force` for DRAFT/FAILED metadata as implemented, but ensure guidance is clear.
   - If metadata is absent and some/all expected S3 config keys exist:
     - Prefer an idempotent retry/adopt path: read existing S3 objects, compare them to the sanitized local configs or compare a deterministic config hash, and if all three artifacts exist and match, create the missing DRAFT metadata instead of failing.
     - If objects are missing or content mismatches, fail with a new structured partial-state error, e.g. `PARTIAL_AUDIT_CREATE_EXISTS`, listing safe key-level diagnostics and recovery options.
3. If idempotent adopt is not desired, add compensating rollback: if any S3 write succeeds and later S3/DynamoDB write fails, delete only the objects written by the current invocation. Be careful not to delete pre-existing objects.
4. Improve `src/release_confidence_platform/operator_cli/result.py` guidance for `CONFIG_OBJECT_EXISTS` / partial-state errors to direct operators to `rcp config list`, metadata inspection, `--force` only when metadata exists in DRAFT/FAILED, or exact S3 cleanup when metadata is absent.
5. Add regression tests in `tests/unit/test_operator_cli_rcp.py` or a dedicated service test for:
   - metadata write failure after S3 writes leaves a retryable partial state;
   - retry with matching existing objects and absent metadata creates metadata successfully, if adopting idempotency;
   - retry with mismatched existing object fails safely;
   - `--force` remains limited to DRAFT/FAILED metadata and does not mask absent metadata accidentally.

## 10. Suggested Validation Steps

- Unit tests for partial S3/upload + missing metadata retry behavior.
- Unit test for `CONFIG_OBJECT_EXISTS` rendering to ensure actionable recovery guidance.
- HITL validation against dev resources:
  1. Confirm current S3 key state with `rcp config list` or AWS CLI.
  2. Confirm metadata key state with DynamoDB `get-item`.
  3. Retry `rcp audit create` using the same bundle.
  4. Expected after fix: either successful DRAFT metadata creation when artifacts match, or a structured partial-state error with exact safe recovery steps.

## 11. Open Questions / Missing Evidence

- Which of the three S3 config objects currently exist in the dev bucket?
- Does the DynamoDB metadata item currently exist for `CLIENT#client_layer_1_validation_client_b5817642` / `AUDIT#audit_20260524_ec3f2d9b`?
- Did the prior failed attempt write all three config objects or only a subset?
- Is product intent to make `audit create` idempotent for matching config artifacts, or should it only provide better manual recovery guidance?

## 12. Final Investigator Decision

Ready for developer fix.
