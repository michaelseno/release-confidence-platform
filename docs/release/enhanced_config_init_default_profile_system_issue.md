# GitHub Issue

## 1. Feature Name

Enhanced `rcp config init` default profile system

## 2. Problem Summary

`rcp config init` currently relies on CLI-side hardcoded defaults for environment-specific starter configuration generation. This makes onboarding behavior harder to maintain, weakens consistency between dev, staging, and production starter configs, and increases the risk that operators generate local workspaces with invalid schemas, unsafe defaults, or unclear override behavior.

This feature enhances `rcp config init` into a reusable, profile-driven, local-only initialization workflow. It loads named or explicit defaults profiles, applies deterministic override precedence, generates validation-safe local client and audit config workspaces, protects existing output directories, and guarantees no AWS, upload, registration, scheduling, Lambda, or production execution side effects.

## 3. Linked Planning Documents

- Product Spec: `docs/product/enhanced_config_init_default_profile_system_product_spec.md`
- Technical Design: `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- UI/UX Spec: `docs/uiux/enhanced_config_init_default_profile_system_design_spec.md`
- QA Test Plan: `docs/qa/enhanced_config_init_default_profile_system_test_plan.md`

## 4. Scope Summary

- In scope
  - Enhance existing `rcp config init` behavior to use defaults profiles instead of CLI-hardcoded environment defaults.
  - Require `--client-name` and support optional `--defaults`, `--output-dir`, `--timezone`, `--include-sample-endpoints`, `--overwrite`, and `--output` arguments.
  - Resolve omitted defaults to `dev`, named profiles to `config/defaults/dev.json`, `config/defaults/staging.json`, and `config/defaults/prod.json`, and path-like or `.json` values to explicit profile files.
  - Add and validate `operator_defaults` profile support with precedence of explicit CLI arguments, then profile defaults, then safe fallbacks.
  - Generate validation-compatible `client_id` and `audit_id` values and local files under `.local-configs/<client_id>/` by default.
  - Generate `client_config.json`, `audits/<audit_id>/audit_config.json`, and `audits/<audit_id>/endpoints.json` with no secrets and no unsafe execution settings.
  - Validate profile content, generated config schemas, audit validation compatibility, overwrite behavior, and local-only safety before reporting success.
- Out of scope
  - Uploading generated configs to S3 or any remote storage.
  - Audit registration, metadata creation, dashboarding, monitoring, or runtime status views.
  - Lambda invocation, schedule creation, schedule activation, or audit execution.
  - Live AWS integration, AWS credential loading requirements, or production execution approval workflows.
  - Interactive profile selection, automatic migration of existing hand-authored configs, or post-generation config editing workflows.

## 5. Implementation Notes

- Frontend expectations
  - No web frontend or customer-facing UI is expected.
  - Operator interaction is CLI-only through `rcp config init`.
  - CLI output must remain readable in text mode and strictly parseable in JSON mode.
- Backend expectations
  - Update the existing operator CLI command and `ConfigInitService` rather than introducing a separate framework.
  - Add defaults profile resolution, loading, validation, and merge logic in repository-local config/operator CLI modules.
  - Add bundled defaults profiles for `dev`, `staging`, and `prod` under `config/defaults/`.
  - Generate configs only after profile validation, resolved input validation, schema validation, audit validation compatibility checks, and overwrite checks pass.
  - Keep all writes constrained to the resolved local workspace under the generated `client_id` directory.
  - Do not instantiate `StageConfigLoader`, `AwsClientFactory`, boto3 clients, upload services, scheduler services, Lambda clients, Secrets Manager clients, DynamoDB clients, or S3 clients.
- Dependencies or blockers
  - Existing validation paths must continue to support local-template validation without weakening runtime execution validation.
  - Profile schema and production-safety validation must be strict enough to reject unsafe or secret-bearing defaults.
  - Packaging/runtime access to bundled profile files may need explicit handling if the CLI is run outside a repository checkout.

## 6. QA Section

- Planned test coverage
  - Unit tests for defaults profile resolution, profile validation, operator default merge behavior, CLI override precedence, ID generation, slug/path safety, and no-AWS enforcement.
  - CLI/API contract tests for omitted defaults, named profiles, explicit profile paths, output formats, generated files, overwrite behavior, validation integration, and failure messaging.
  - Filesystem tests for required nested workspace structure, absence of flat root-level config files, path traversal safety, overwrite protection, and write-failure rollback.
  - Generated config validity and safety tests for schema validation, audit validation compatibility, empty endpoints by default, mock-only sample endpoints, production profile safeguards, and secret scanning.
  - Regression tests for existing `rcp config init` requirements and adjacent CLI/config validation behavior.
- Acceptance criteria mapping
  - AC-001 through AC-004 cover defaults resolution, named/custom profiles, and deterministic precedence.
  - AC-005 through AC-007 cover required directory structure and safe generated IDs.
  - AC-008 through AC-009 cover invalid profile failure behavior and generated validation compatibility.
  - AC-010 through AC-012 cover empty endpoints, safe sample endpoints, and production profile safety.
  - AC-013 through AC-014 cover overwrite protection and explicit overwrite behavior.
  - AC-015 covers no AWS calls on success and failure paths.
  - AC-016 covers operator guidance, text output, and JSON output expectations.
- Key edge cases
  - Unsupported named profiles, missing explicit profile files, invalid JSON, non-object JSON, missing required fields, unsafe production profile values, and secret-bearing profile content.
  - Invalid timezone values, invalid output format values, omitted optional overrides, and profile defaults requiring safe fallback behavior.
  - Client names containing uppercase letters, spaces, punctuation, path separators, traversal sequences, shell metacharacters, unicode symbols, or values that slugify to empty.
  - Existing output directories with and without `--overwrite`, existing files under output parents, partial write failures, and rollback safety.
  - JSON output requiring no stray prose, sanitized errors, no secrets, and stable machine-readable fields.
- Test types expected
  - Unit tests.
  - CLI/API contract tests.
  - Filesystem integration-style tests using temporary directories.
  - Validation contract tests.
  - Security and safety boundary tests.
  - No-AWS side-effect tests.
  - Regression tests.

## 7. Risks / Open Questions

- Profile validation must prevent unsafe defaults, embedded secrets, real production endpoints, or executable production behavior while preserving useful environment-specific defaults.
- Local-template validation must remain isolated from runtime validation so execution-time safety is not weakened.
- Defaults profile file resolution must work both from the repository checkout and any supported installed CLI context.
- Overwrite logic must replace only expected generated files and must not mutate unrelated local content.
- JSON output and error paths must remain parseable, deterministic, and free of leaked profile secrets or raw unsafe values.
- Open question: exact profile schema versioning and migration strategy for future additional profiles.

## 8. Definition of Done

- `rcp config init` supports profile-driven defaults with `dev` as the implicit default and `dev`, `staging`, and `prod` as bundled named profiles.
- Explicit defaults JSON paths are supported and validated before any files are generated.
- CLI overrides for output directory, timezone, and output format take precedence over profile `operator_defaults`.
- Generated workspace structure and files match the product spec and technical design.
- Generated configs validate locally, contain no secrets, and remain non-executable/safe for production-oriented profiles.
- Existing target directories are protected unless `--overwrite` is supplied.
- Text and JSON outputs include profile resolution, effective settings, generated paths, safety statements, and next steps.
- No AWS clients, credentials, uploads, schedules, metadata records, Lambda invocations, or production execution paths are touched.
- Planned QA coverage is implemented and passing.
- Existing CLI/config validation behavior is not regressed.
