# Implementation Report

## 1. Summary of Changes

Phase 7.6 Certification CLI is fully implemented. Two new command groups are wired into the operator CLI:

- `rcp certify audit` — triggers Phase 7 CertificationEngine for a completed Phase 6 report
- `rcp retrieve cert-status|cert-summary|cert-domains|cert-json` — four read-only retrieval commands

`CertificationPublisher.read_artifact()` was added to support S3 artifact reads in the retrieval path.

## 2. Files Modified

| File | Change |
|---|---|
| `src/.../audit_platform_integrity/publisher.py` | Added `read_artifact()` method mirroring `ReportPublisher.read_artifact()` |
| `src/.../audit_platform_integrity/commands.py` | New file: `build_certify_parser`, `dispatch_certify_audit` |
| `src/.../audit_platform_integrity/cert_retrieve_commands.py` | New file: `CertificationRetrievalService`, `build_cert_retrieve_parser`, `dispatch_cert_retrieve` |
| `src/.../operator_cli/main.py` | Added top-level imports for parsers; certify group in `build_parser()`; `build_cert_retrieve_parser` call; certify dispatch branch; cert-retrieve dispatch block; `_command_name()` certify case |
| `tests/unit/audit_platform_integrity/test_commands.py` | New test file: 35 unit tests |
| `tests/unit/test_operator_cli_certify.py` | New smoke test file: 13 tests |
| `docs/backend/phase_7_6_cli_implementation_plan.md` | Implementation plan |

## 3. API Contract Implementation

**`rcp certify audit`** (new top-level group):
- Required: `--client-id`, `--audit-id`, `--execution`, `--stage`
- Optional: `--config-version` (v1), `--aggregation-version` (agg_v1), `--intelligence-version` (intel_v1), `--report-version` (report_v1), `--cert-version` (cert_v1), `--force`, `--output`
- Wired into `dispatch()` with full engine construction and `dispatch_certify_audit(args, engine)` call
- Returns `CommandResult` with `terminal_state`, `certificate_id`, `s3_cert_ref`, `disclosed_failures`, `domain_results`

**`rcp retrieve cert-*`** (four subcommands under existing `retrieve` group):
- All share the same required/optional arguments as `certify audit`
- All are read-only; wired behind `retrieve_command.startswith("cert-")` check

## 4. Data / Persistence Implementation

No new DynamoDB tables or schema. Read paths:
- `get_cert_status`, `get_cert_summary`: DynamoDB-only via `repository.get_cert_metadata()`
- `get_cert_domains`, `get_cert_json`: DynamoDB for `s3_certificate_ref`, then `publisher.read_artifact(s3_ref)` for S3

Write path: zero writes from any retrieval command or retrieval service method.

## 5. Key Logic Implemented

**`dispatch_certify_audit`**: validates identifiers → calls `engine.certify()` with all identity args → reconstructs S3 key using `build_cert_s3_key(certjob_id=certificate.certjob_id)` → returns summary dict.

**`CertificationRetrievalService`**: `_get_metadata_or_raise()` central helper raises `ValidationError("CERTIFICATION_NOT_FOUND")` when metadata absent; used by all four retrieval methods.

**`dispatch_cert_retrieve`**: validates identifiers at CLI boundary before any downstream call; routes via `_DISPATCH_TABLE` dict; returns pre-rendered string for the main.py "rendered" output path.

**Provenance envelope** (all human-output retrieve commands except `cert-json`): `Certificate ID`, `Certificate Version`, `Terminal State`, `Report ID`, `Generated At` — drawn from `CertificationMetadata.completed_at`.

**`cert-json`**: returns `json.dumps(artifact, indent=2, sort_keys=True)` without a provenance envelope, consistent with `report-json`.

## 6. Security / Authorization Implemented

- `validate_identifier` called on `client_id`, `audit_id`, `execution` in both `dispatch_certify_audit` and `dispatch_cert_retrieve` before any DynamoDB or S3 access
- All retrieval commands are structurally read-only: `CertificationRetrievalService` has no write methods
- Lazy import pattern preserved in `main.py` for all engine/repository/publisher/service classes
- No secrets or sensitive fields logged

## 7. Error Handling Implemented

- `ValidationError("CERTIFICATION_NOT_FOUND")` from all four retrieval service methods when metadata is absent
- `ValidationError` propagates up from identifier validation failures
- `CertificationGateError`, `CertificationAlreadyCertifiedError`, `StorageError` from engine propagate to main.py's `EngineError` handler (exit code 1)
- Unknown command string raises `ValidationError("UNKNOWN_COMMAND")` in `dispatch_cert_retrieve`

## 8. Observability / Logging

No new logging added in CLI layer. Engine logging is handled by `CertificationEngine` itself. `StructuredLogger()` is passed to engine constructor in the `certify` dispatch branch, consistent with Phase 6 `generate report` pattern.

## 9. Assumptions Made

- `build_cert_s3_key()` is called in `dispatch_certify_audit` using `certificate.certjob_id` to reconstruct the S3 key returned to the caller; the engine does not return the S3 key directly from `certify()`.
- `CertificationMetadata.completed_at` is used as the `generated_at` value in the provenance envelope.
- `cert-json` returns the certificate artifact without a separate provenance envelope (consistent with `report-json` behavior; the artifact itself contains all provenance fields).

## 10. Validation Performed

```
uv run pytest tests/unit/audit_platform_integrity/test_commands.py -v
35 passed in 0.10s

uv run pytest tests/unit/test_operator_cli_certify.py -v
13 passed in 1.34s

uv run pytest tests/unit/ -q --tb=no
1204 passed in 2.06s
```

Zero failures. Zero regressions.

## 11. Known Limitations / Follow-Ups

- `cert-json` does not branch on `--output` flag (always returns JSON); this is consistent with `report-json` behavior
- `--output json` for `cert-status`, `cert-summary`, `cert-domains` returns human text via the pre-rendered path; JSON structured output for these commands was not specified in the approved design

## 12. Commit Status

Commit: `978f097` on branch `feature/phase-7-6-operator-cli`

Not pushed to remote.
