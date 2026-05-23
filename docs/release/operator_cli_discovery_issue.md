# GitHub Issue

GitHub Issue: #13
GitHub Issue URL: https://github.com/michaelseno/release-confidence-platform/issues/13
## 1. Feature Name

Operator CLI Discovery

## 2. Problem Summary

Operators need a safe, stage-aware way to discover clients, audits, and persisted configuration artifacts without manually querying DynamoDB or S3. The feature adds read-only internal `rcp` commands for operational discovery and controlled config download while avoiding raw evidence, secrets, customer-facing workflows, and unsupported future placeholders.

## 3. Linked Planning Documents

- Product Spec: `docs/product/operator_cli_discovery_spec.md`
- Technical Design: `docs/architecture/operator_cli_discovery_technical_design.md`
- UI/UX Spec: `docs/uiux/operator_cli_discovery_design_spec.md`
- QA Test Plan: `docs/qa/operator_cli_discovery_test_plan.md`

## 4. Scope Summary

- In scope
  - Add read-only operational discovery commands:
    - `rcp client list`
    - `rcp audit list`
    - `rcp config list`
    - `rcp config download`
  - Support stage-aware execution using existing stage configuration resolution.
  - Support concise human-readable output and JSON output where specified.
  - Use bounded pagination/limits for discovery operations.
  - Inspect S3 config artifact metadata without downloading contents for `config list`.
  - Download only the expected runtime config artifacts for `config download`.
  - Protect local files from overwrite unless explicitly requested.
  - Keep implementation as internal operator tooling only.
  - Ensure `.local-configs/` is ignored if used for downloaded configs.
- Out of scope
  - Customer-facing UI, API, dashboard, or self-service workflow.
  - Core Operator CLI creation work already covered by the separate Operator CLI PR.
  - Future placeholder commands such as config delete/archive, run inspection, audit status, or schedule status.
  - `--version-id` support for config download.
  - Secrets Manager retrieval, secret printing, raw evidence access, raw-results inspection, or mutation of audit/config resources.
  - Live AWS calls in unit tests.

## 5. Implementation Notes

- Frontend expectations
  - No web frontend or customer-facing UI is required.
  - CLI help and terminal output must be deterministic, accessible, and concise.
  - Default output should be human-readable; JSON output must be stable and sanitized.
  - Download output must warn that config files may contain sensitive operational details and recommend `.local-configs/`.
- Backend expectations
  - Extend the existing internal `rcp` CLI rather than creating a separate CLI.
  - Keep CLI handlers thin; delegate DynamoDB access, S3 access, config path construction, pagination, validation, and rendering to shared services/wrappers.
  - Resolve DynamoDB tables, S3 buckets, regions, and environment details through existing stage configuration and environment override mechanisms.
  - Use read-only AWS operations for discovery and config retrieval.
  - Do not hardcode AWS resource names or duplicate shared storage/business logic in command handlers.
  - Do not expose or access Secrets Manager values, raw evidence, or raw-results objects.
- Dependencies or blockers
  - Depends on the existing core Operator CLI entry point, parser style, stage config loader, AWS client factory, storage wrappers, and output renderer.
  - Client discovery may require a temporary bounded DynamoDB scan fallback if no registry/index exists.
  - Implementation must remain separate from the core Operator CLI PR and must not introduce unsupported future command behavior.

## 6. QA Section

- Planned test coverage
  - CLI parser and command dispatch tests for `client list`, `audit list`, `config list`, and `config download`.
  - DynamoDB query/index and bounded fallback behavior tests for client discovery.
  - DynamoDB audit list query tests by client ID and limit.
  - S3 metadata-only tests for `config list`.
  - S3 and filesystem tests for `config download`, including exact artifact set, output directory creation, filename preservation, missing-file handling, and overwrite protection.
  - Renderer and sanitization tests for human and JSON output.
  - Stage configuration and environment override tests.
  - Mocked AWS-only safeguards to prevent live AWS access.
- Acceptance criteria mapping
  - Parser exposes all intended command groups and rejects unsupported commands/options.
  - `--version-id` is not exposed or accepted.
  - Default limit is `100`; hard maximum is `1000` where applicable.
  - All scans/listing behavior is bounded and stage-aware.
  - `config list` never downloads object content.
  - `config download` downloads only `client_config.json`, `audit_config.json`, and `endpoints.json`.
  - No Secrets Manager, raw evidence, or raw-results access occurs.
  - Outputs are sanitized and do not leak secrets or sensitive raw content.
- Key edge cases
  - Missing required `--stage`, `--client-id`, `--audit-id`, or `--output-dir` arguments.
  - Invalid limits, including zero, negative, and values above `1000`.
  - Empty client/audit/config results.
  - Missing config artifacts in S3.
  - Existing local files with and without `--overwrite`.
  - Suspicious or sensitive provider error strings requiring sanitization.
  - Unavailable client registry/index requiring bounded fallback scan.
- Test types expected
  - Unit tests.
  - CLI parser/contract tests.
  - Mocked DynamoDB and S3 repository/service tests.
  - Filesystem-isolated config download tests.
  - Renderer/sanitization tests.
  - No live AWS integration tests.

## 7. Risks / Open Questions

- Client discovery may rely on a temporary bounded scan if no client registry/index exists, which should be documented and replaced later with a first-class registry/index.
- Downloaded config files may contain sensitive operational details; operator guidance and `.local-configs/` gitignore protection are required.
- Output schemas should remain stable enough for automation without expanding into customer-facing API guarantees.
- Existing Operator CLI commands must not regress when adding `audit list` and new `client`/`config` command groups.
- Confirm whether explicit `--output text` is required for consistency with the existing CLI or whether default text output is sufficient.

## 8. Definition of Done

- Planning artifacts are linked and implementation remains aligned with product, technical, UI/UX, and QA specifications.
- `rcp client list`, `rcp audit list`, `rcp config list`, and `rcp config download` are implemented as internal read-only operator commands.
- Commands use existing stage configuration resolution and shared service/storage layers.
- No future placeholders or `--version-id` behavior is implemented.
- No secrets, raw evidence, or raw-results content is accessed or printed.
- Config download writes only the expected config artifacts and protects existing files unless `--overwrite` is supplied.
- `.local-configs/` is gitignored if needed.
- Required unit, parser, service, renderer, filesystem, and mocked AWS tests pass.
- QA sign-off and HITL validation are obtained before any push or PR creation.
