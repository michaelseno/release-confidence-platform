# Test Plan

## 1. Feature Overview
Validate the backend fix for the HITL `rcp audit run --scenario-type repeated_stability` blocker where Lambda raw-result S3 existence checks returned generic `STORAGE_ERROR: S3 existence check failed`. Scope is repository-only validation; no AWS deploy or live HITL execution is performed.

## 2. Acceptance Criteria Mapping
| ID | Acceptance criterion | Validation approach |
|---|---|---|
| AC1 | `infra/serverless.yml` grants bucket-level `s3:ListBucket` for the runtime/config bucket restricted to `raw-results/*`, `configs/*`, and `data-pools/*`. | Static review and `tests/unit/test_infra_configuration.py`. |
| AC2 | Object permissions remain scoped and are not broadened unnecessarily. | Static review and object-scope infra regression test. |
| AC3 | Backend runtime `head_object` not-found maps to `False`. | Unit tests in `tests/unit/test_backend_s3_storage_client.py`. |
| AC4 | Backend runtime `head_object` AccessDenied/Forbidden maps to actionable structured permission error. | Unit tests and message sanitation assertions. |
| AC5 | Backend runtime `head_object` NoSuchBucket maps to actionable structured config error. | Unit tests and message context assertions. |
| AC6 | Backend runtime `put_object` AccessDenied/NoSuchBucket/generic errors map safely and are sanitized. | Unit tests for known and generic put failures plus full pytest regression. |
| AC7 | Generic backend S3 `put_object` and `head_object` `ClientError` diagnostics do not leak bucket names, full keys, client IDs, audit IDs, token/secret/API key/password-like fragments, or raw `aws_error_message`; useful allowlisted fields remain. | Dedicated QA sanitization probe plus explicit negative/positive assertions in storage tests. |
| AC8 | Prior HITL fixes still pass: config-init, audit-create, stage-info, Lambda packaging, orchestrator sync response/failure detail rendering. | Targeted regression pytest subset plus full pytest. |
| AC9 | Ruff/format quality gates and full pytest pass. | Execute Ruff check/format check and full pytest. |

## 3. Test Scenarios
1. Verify S3 IAM ListBucket policy has only bucket ARN and prefix-restricted `s3:prefix` values.
2. Verify S3 object IAM resources are prefix scoped and `PutObject` remains raw-results-only.
3. Simulate `HeadObject` not-found variants (`404`, `NoSuchKey`, `NotFound`).
4. Simulate `HeadObject` permission denied variants (`AccessDenied`, `Forbidden`).
5. Simulate `HeadObject` missing bucket.
6. Simulate `PutObject` known storage failures (`AccessDenied`, `NoSuchBucket`) and generic AWS failures.
7. Simulate generic `HeadObject` and `PutObject` `ClientError` messages containing prohibited bucket/key/client/audit/token/API-key/password values and verify only allowlisted diagnostics are emitted.
8. Validate sanitized messages exclude sensitive identifiers and secret-like values while preserving safe AWS error code, operation, key prefix/class, and required permission guidance.
9. Regression-check operator CLI config init/stage-info/audit run synchronous failure detail rendering and Lambda packaging tests.
10. Run repository-wide static and automated test gates.

## 4. Edge Cases
- Missing object must remain a non-error duplicate-check result.
- S3 permission failure must include operation, top-level key prefix, AWS code, and required permission guidance without revealing full key/bucket.
- Generic S3 failure must not expose Authorization headers, tokens, client IDs, audit IDs, or raw secret values.
- Serverless policy must not revert to `arn:aws:s3:::.../*` broad object access.

## 5. Test Types Covered
- Static infrastructure review
- Unit tests
- API/CLI contract regression tests
- Security/sanitization checks
- Formatting/lint checks
- Full automated regression suite

## 6. Coverage Justification
The selected coverage directly exercises every changed runtime behavior and IAM policy constraint, then protects prior HITL fixes through targeted and full regression suites. Live AWS redeploy/HITL execution is explicitly out of scope per instruction.
