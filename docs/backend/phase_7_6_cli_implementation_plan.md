# Implementation Plan

## 1. Feature Overview

Phase 7.6 Certification CLI adds two new command groups to the operator CLI:
- `rcp certify audit` — triggers the Phase 7 CertificationEngine for a completed Phase 6 report
- `rcp retrieve cert-*` — four read-only retrieval commands for CertificationMetadata and certificate artifacts

## 2. Technical Scope

- Parser registration and dispatch for `certify audit`
- `CertificationRetrievalService` with four retrieval methods
- Parser registration and dispatch for four `cert-*` retrieve subcommands
- Wiring both command groups into `main.py`
- `read_artifact()` method on `CertificationPublisher` (needed for cert-domains, cert-json)
- Unit tests and smoke tests

## 3. Source Inputs

- `docs/product/phase_7_audit_platform_integrity_product_spec.md` Section 6 (CLI spec)
- `src/release_confidence_platform/audit_platform_integrity/engine.py` — CertificationEngine.certify() signature
- `src/release_confidence_platform/audit_platform_integrity/repository.py` — CertificationRepository
- `src/release_confidence_platform/audit_platform_integrity/publisher.py` — CertificationPublisher
- `src/release_confidence_platform/deterministic_reporting/commands.py` — parser pattern reference
- `src/release_confidence_platform/deterministic_reporting/report_retrieve_commands.py` — retrieval pattern reference
- `src/release_confidence_platform/operator_cli/main.py` — CLI wiring pattern

## 4. API Contracts Affected

No HTTP API changes. CLI command surface additions only:

`rcp certify audit` — new top-level group with one subcommand
- Required: `--client-id`, `--audit-id`, `--execution`, `--stage`
- Optional with defaults: `--config-version` (v1), `--aggregation-version` (agg_v1), `--intelligence-version` (intel_v1), `--report-version` (report_v1), `--cert-version` (cert_v1)
- Flags: `--force`, `--output (json|human, default: human)`
- Raises `ValidationError` on invalid identifiers; raises `CertificationGateError`, `CertificationAlreadyCertifiedError`, `StorageError` from engine

`rcp retrieve cert-status` — DynamoDB-only read
`rcp retrieve cert-summary` — DynamoDB-only read
`rcp retrieve cert-domains` — DynamoDB for s3_cert_ref, S3 for domain_results array
`rcp retrieve cert-json` — DynamoDB for s3_cert_ref, S3 for full certificate artifact

All retrieve commands: read-only, no writes under any condition.

## 5. Data Models / Storage Affected

No new DynamoDB tables or schema changes.

`CertificationPublisher.read_artifact()` — adds S3 GetObject read path to the publisher. This is consistent with `ReportPublisher.read_artifact()` pattern.

## 6. Files Expected to Change

New files:
- `src/release_confidence_platform/audit_platform_integrity/commands.py`
- `src/release_confidence_platform/audit_platform_integrity/cert_retrieve_commands.py`
- `tests/unit/audit_platform_integrity/test_commands.py`
- `tests/unit/test_operator_cli_certify.py`

Modified files:
- `src/release_confidence_platform/audit_platform_integrity/publisher.py` — add `read_artifact()`
- `src/release_confidence_platform/operator_cli/main.py` — add certify group, cert-retrieve parser, dispatch branches, _command_name() update

## 7. Security / Authorization Considerations

- `validate_identifier` called on `client_id`, `audit_id`, `execution` before any downstream DynamoDB or S3 call
- All retrieve commands are unconditionally read-only
- No secrets or credentials are logged
- Follows existing lazy-import pattern in main.py (no top-level module imports for engine/service classes)

## 8. Dependencies / Constraints

- `CertificationRepository(table_name, dynamodb_client, s3_client, bucket_name)` — note: takes both dynamodb_client and s3_client
- `CertificationPublisher(bucket_name, s3_client)` — only has write_artifact(); adding read_artifact()
- `CertificationEngine(repository, publisher, logger, platform_version)` — certify() returns PlatformIntegrityCertificate
- `validate_identifier` from `release_confidence_platform.core.validators`
- `build_cert_s3_key` from `release_confidence_platform.audit_platform_integrity.identity` — used to reconstruct S3 key from certjob_id
- No new package dependencies

## 9. Assumptions

- `CertificationPublisher.read_artifact()` is safe to add as it mirrors `ReportPublisher.read_artifact()` exactly and is needed by `CertificationRetrievalService`
- For `cert-json` output, the full certificate artifact JSON is returned without a separate provenance envelope (consistent with `report-json` behavior)
- `dispatch_certify_audit` constructs the S3 key by calling `build_cert_s3_key()` using `certificate.certjob_id` from the returned `PlatformIntegrityCertificate`; the engine does not return the S3 key directly
- The `completed_at` field of `CertificationMetadata` is used as `generated_at` in the provenance envelope

## 10. Validation Plan

```bash
uv run pytest tests/unit/audit_platform_integrity/test_commands.py -v
uv run pytest tests/unit/test_operator_cli_certify.py -v
uv run pytest tests/unit/ -q --tb=no
```
