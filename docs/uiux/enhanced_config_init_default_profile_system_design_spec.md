# Design Specification

## 1. Feature Overview

Enhanced `rcp config init` is a local-only operator workflow that creates validation-safe starter configuration files from reusable defaults profiles. It supports a minimal path using the implicit `dev` profile, named profile selection, explicit custom profile paths, deterministic CLI overrides, human-readable output, and machine-readable JSON output.

Primary minimal workflow:

```bash
rcp config init --client-name "Acme"
```

This specification covers terminal/operator UX only. No web UI, remote onboarding, AWS upload, schedule creation, or runtime execution behavior is in scope.

## 2. User Goal

Operators need to generate a safe local workspace for a client and initial audit with minimal input, understand exactly which defaults were applied, and receive clear next steps for validation/review without risking production execution or AWS-side effects.

## 3. UX Rationale

- Use a minimal required input (`--client-name`) so normal dev bootstrap is fast.
- Make profile resolution visible so operators can confirm whether `dev`, `staging`, `prod`, or a custom file was used.
- Show override precedence in output for values commonly controlled by operators: output directory, timezone, and output format.
- Treat production-oriented profiles as allowed but non-executable by default, with prominent safety copy.
- Keep stdout deterministic and readable for terminal logs, screen readers, CI assertions, and copy/paste.
- Keep `--output json` strictly parseable by emitting only JSON on stdout.

## 4. User Flow

### Minimal dev initialization

1. Operator runs `rcp config init --client-name "Acme"`.
2. CLI resolves omitted `--defaults` to named profile `dev`.
3. CLI validates client name, profile existence/content, resolved defaults, target directory availability, and generated config schemas.
4. CLI writes files under `.local-configs/<client_id>/`.
5. CLI prints a success summary with IDs, selected profile, file paths, safety status, and next steps.
6. CLI exits `0`.

### Named profile workflow

1. Operator runs `rcp config init --client-name "Acme" --defaults staging` or `--defaults prod`.
2. CLI resolves `dev`, `staging`, or `prod` as bundled named profiles, not relative paths.
3. CLI applies profile `operator_defaults`, then explicit CLI overrides, then safe fallbacks for unresolved values.
4. CLI reports the selected profile and target environment in output.
5. If the profile target environment is production-oriented, CLI includes production safety warnings while still generating safe local configs.

### Custom profile path workflow

1. Operator runs `rcp config init --client-name "Enterprise Client" --defaults config/defaults/high-volume-staging.json`.
2. CLI treats `--defaults` as a path when the value contains a path separator or ends with `.json`.
3. CLI validates file existence, JSON syntax, and required profile fields before writing any generated files.
4. CLI output labels the source as `custom profile path` and prints the resolved path.

### Explicit override workflow

1. Operator runs:

   ```bash
   rcp config init --client-name "Acme" --defaults staging --output-dir ./tmp-configs --timezone Asia/Hong_Kong --output json
   ```

2. CLI resolves the staging profile.
3. CLI applies explicit `--output-dir`, `--timezone`, and `--output` over profile defaults.
4. CLI emits valid JSON only, with fields equivalent to the human-readable summary.

## 5. Information Hierarchy

Human-readable output must order information as follows:

1. Result banner: `SUCCESS`, `ERROR`, or `WARNING`.
2. Command outcome: generated local config workspace or failed before generation.
3. Generated identifiers: `client_id`, `audit_id`.
4. Profile resolution: profile name/source, target environment, custom path when applicable.
5. Effective operator inputs: workspace root, timezone, sample endpoint mode, overwrite mode.
6. Override hierarchy summary for resolved values.
7. Generated directory and file paths.
8. Safety statement: local-only, no AWS access, no upload, no schedules, no production execution.
9. Warnings, especially production target environment and safe sample endpoint limitations.
10. Next steps.
11. Diagnostic code/details for failures.

## 6. Layout Structure

### Command structure

```text
rcp config init \
  --client-name TEXT \
  [--defaults dev|staging|prod|PATH.json] \
  [--output-dir PATH] \
  [--timezone IANA_TIMEZONE] \
  [--include-sample-endpoints] \
  [--overwrite] \
  [--output text|json]
```

### Human-readable success output template

```text
SUCCESS: Local config workspace generated.

Identifiers
  client_id: client_acme_ab12cd
  audit_id:  audit_20260524_ef34gh

Defaults profile
  source: named profile
  name:   dev
  target_environment: dev

Effective settings
  workspace_root: .local-configs/client_acme_ab12cd
  timezone:       UTC
  endpoints:      empty endpoints array
  overwrite:      false

Resolution order
  1. explicit CLI arguments
  2. profile operator_defaults
  3. safe fallback values

Generated files
  .local-configs/client_acme_ab12cd/client_config.json
  .local-configs/client_acme_ab12cd/audits/audit_20260524_ef34gh/audit_config.json
  .local-configs/client_acme_ab12cd/audits/audit_20260524_ef34gh/endpoints.json

Safety
  Local files only. No AWS calls were made. No configs were uploaded.
  No schedules, metadata records, or production execution were created.

Next steps
  1. Review generated JSON files.
  2. Run local validation before onboarding or upload workflows.
  3. Add real endpoints only after review; do not store secrets in generated config files.
```

### Production-oriented success warning template

When selected profile name is `prod` or profile `target_environment` is production-oriented, include this block after `Safety` and before `Next steps`:

```text
WARNING: Production target defaults selected.
  Generated configs remain local and non-executable by default.
  allow_production_execution=false
  allow_destructive_operation=false
  No real endpoints were generated.
  Separate approval and validation are required before any production execution workflow.
```

### Overwrite success copy

When `--overwrite` is supplied and target directory existed, include:

```text
WARNING: Existing workspace was overwritten.
  overwritten_path: <workspace_root>
```

Do not show this warning if the directory did not previously exist.

### Generated directory structure messaging

Use the label `Generated files` and list one path per line in stable order:

1. `<workspace_root>/client_config.json`
2. `<workspace_root>/audits/<audit_id>/audit_config.json`
3. `<workspace_root>/audits/<audit_id>/endpoints.json`

The default `workspace_root` is `.local-configs/<client_id>`. If `--output-dir` or profile `operator_defaults.output_dir` changes the output root, output must still show the exact resolved path.

## 7. Components

- Command parser/help text.
- Profile resolver status model: named profile, custom path, missing/invalid.
- Input validation messages for client name, timezone, output format, output path, and overwrite protection.
- Merge/precedence summary renderer.
- Human-readable text renderer.
- JSON output renderer.
- Error renderer with stable code, summary, details, and next action.
- Safety/warning renderer for production-oriented profiles and sample endpoints.

## 8. Interaction Behavior

### Profile resolution

- Trigger: command execution with omitted or provided `--defaults`.
- System response:
  - Omitted value resolves to named profile `dev`.
  - `dev`, `staging`, `prod` resolve as bundled named profiles.
  - Values containing path separators or ending in `.json` resolve as explicit file paths.
- UI feedback: success output states `source`, `name`, `target_environment`, and `path` for custom profiles.
- Failure behavior: fail non-zero before file generation and print a profile-specific error.

### Override hierarchy

- Trigger: any generation run.
- System response: resolve values in this order: explicit CLI argument → profile `operator_defaults` → safe fallback.
- UI feedback: human output includes the `Resolution order` block; JSON output includes `resolution_order` and `effective_settings`.
- Failure behavior: if no safe valid value can be resolved, fail before file generation with an actionable validation error.

### Output mode

- Trigger: `--output text`/default or `--output json`.
- Text response: human-readable blocks as specified above.
- JSON response: stdout contains valid JSON only. Warnings and errors must be represented inside the JSON object, not printed as additional text.
- Failure behavior: invalid output format fails before file generation.

### Include sample endpoints

- Trigger: `--include-sample-endpoints`.
- System response: generate safe mock sample endpoints only.
- UI feedback: `endpoints: safe mock sample endpoints` in text output; JSON `effective_settings.include_sample_endpoints=true` and `sample_endpoint_safety="mock_only"`.
- Failure behavior: if safe samples cannot be generated, fail rather than generating real or unsafe endpoints.

### Overwrite protection

- Trigger: target workspace already exists.
- System response: without `--overwrite`, fail before modifying files. With `--overwrite`, replace generated files according to backend implementation rules.
- UI feedback: failure clearly says the path exists and names `--overwrite`; success with actual overwrite includes the overwrite warning.

## 9. Component States

### Command parser/help

- Default: accepts required `--client-name` and optional flags.
- Focus: not applicable to CLI; terminal cursor/focus is controlled by shell.
- Disabled: not applicable.
- Loading: no spinner required; if generation is slow, print no partial success before validation completes.
- Success: renders success text or JSON and exits `0`.
- Error: renders stable error and exits non-zero.
- Empty: missing required `--client-name` shows usage plus concise required-argument error.

### Profile resolver

- Default: omitted `--defaults` resolves to `dev`.
- Active: while resolving, do not write files.
- Success: output includes selected profile source/name/path and target environment.
- Error: missing file, invalid JSON, or missing required fields fail before generation.
- Empty: empty `--defaults` value is invalid and must not silently resolve to `dev`.

### Human-readable renderer

- Default: plain text with stable headings and indentation.
- Success: prints the success template.
- Warning: prints warning blocks after safety context and before next steps.
- Error: prints error template with code, reason, and next action.
- Loading/disabled/hover/focus/active: not applicable for static terminal output.

### JSON renderer

- Default: valid JSON object only.
- Success: includes generated IDs, paths, profile metadata, effective settings, warnings, safety, and next steps.
- Error: includes `status="error"`, stable `error.code`, message, details, and next action; no extra stdout text.
- Empty: arrays such as `warnings` and `generated_files` should be empty arrays rather than omitted when known to be empty.
- Loading/disabled/hover/focus/active: not applicable.

### Error renderer

- Default: concise summary first, details second, next action third.
- Success: not shown.
- Error: never exposes secrets, tokens, stack traces, or raw filesystem internals beyond relevant paths.
- Focus/loading/disabled/hover/active: not applicable.

## 10. Responsive Design Rules

CLI output is not viewport-responsive in the web sense. It must remain readable on narrow terminals:

- Use short headings and one field per line.
- Avoid tables that depend on column alignment across long paths.
- Do not use color as the only carrier of status; status words must be present.
- Avoid Unicode-only icons; ASCII text must communicate all meaning.
- JSON output must not wrap intentionally or include decorative formatting requirements.

Desktop, tablet, and mobile terminal behavior is equivalent because this is a command-line workflow. Operators on small terminal widths should still receive complete information through line wrapping.

## 11. Visual Design Tokens

No visual design tokens are required. Terminal output should use:

- Plain ASCII headings.
- Two-space indentation for field rows.
- Stable lowercase snake_case field names where they correspond to config/JSON fields.
- Uppercase status labels: `SUCCESS`, `WARNING`, `ERROR`.
- No required ANSI color. If color is later added, it must be supplemental and disabled automatically when output is non-interactive or JSON.

## 12. Accessibility Requirements

- Output must be understandable without color, icons, animation, or cursor movement.
- Use explicit text labels instead of symbolic-only indicators.
- Keep headings stable so screen reader users can navigate logs predictably.
- Print one semantic item per line for generated paths, IDs, warnings, and next steps.
- Error messages must identify the failed input, the reason, and the corrective action.
- JSON mode must be valid for assistive tooling and automation parsers.
- Do not emit progress spinners, carriage-return updates, or transient terminal-only status as required information.
- Avoid ambiguous phrasing such as “done” without the concrete generated workspace path.

## 13. Edge Cases

### Error message guidance

Use this text structure for human-readable errors:

```text
ERROR: <short failure summary>.

Reason
  <specific sanitized reason>

No files were generated or modified.

Next step
  <actionable operator instruction>

Diagnostic
  code: <STABLE_ERROR_CODE>
```

If failure occurs after partial writes, replace the no-files line with:

```text
Generation did not complete successfully. Do not use partial files.
```

and include any cleanup result if available.

Required error cases:

- Missing profile: `PROFILE_NOT_FOUND`; next step: verify `--defaults` name/path or use `dev`, `staging`, or `prod`.
- Invalid profile JSON: `PROFILE_INVALID_JSON`; next step: fix JSON syntax and rerun.
- Profile missing required fields: `PROFILE_INVALID_SCHEMA`; next step: add required profile fields, including `profile_name`, `target_environment`, and `operator_defaults`.
- Invalid generated config: `GENERATED_CONFIG_INVALID`; next step: inspect profile defaults and generated field diagnostics; command must not report success.
- Existing output directory without `--overwrite`: `OUTPUT_DIR_EXISTS`; next step: choose a new `--output-dir` or rerun with `--overwrite`.
- Unsafe profile values: `UNSAFE_PROFILE_VALUES`; next step: remove secrets, real production endpoints, destructive settings, aggressive production concurrency, or executable production flags.
- Invalid client name: `INVALID_CLIENT_NAME`; next step: provide a name that slugifies to a non-empty safe value and does not rely on path separators.
- Filesystem failure: `FILESYSTEM_ERROR`; next step: check path permissions, disk availability, and parent directory existence.
- Invalid timezone: `INVALID_TIMEZONE`; next step: provide a valid IANA timezone such as `UTC` or `Asia/Hong_Kong`.
- Invalid output format: `INVALID_OUTPUT_FORMAT`; next step: use `text` or `json`.

### JSON output shape

Successful `--output json` must use this shape, with no additional stdout content:

```json
{
  "status": "success",
  "command": "config init",
  "client_id": "client_acme_ab12cd",
  "audit_id": "audit_20260524_ef34gh",
  "profile": {
    "source": "named",
    "name": "dev",
    "path": "config/defaults/dev.json",
    "target_environment": "dev"
  },
  "effective_settings": {
    "workspace_root": ".local-configs/client_acme_ab12cd",
    "timezone": "UTC",
    "include_sample_endpoints": false,
    "sample_endpoint_safety": "empty_endpoints_array",
    "overwrite": false,
    "output_format": "json"
  },
  "resolution_order": [
    "explicit_cli_argument",
    "profile_operator_defaults",
    "safe_fallback"
  ],
  "generated_files": {
    "client_config": ".local-configs/client_acme_ab12cd/client_config.json",
    "audit_config": ".local-configs/client_acme_ab12cd/audits/audit_20260524_ef34gh/audit_config.json",
    "endpoints": ".local-configs/client_acme_ab12cd/audits/audit_20260524_ef34gh/endpoints.json"
  },
  "safety": {
    "local_only": true,
    "aws_calls_made": false,
    "configs_uploaded": false,
    "schedules_created": false,
    "allow_production_execution": false,
    "allow_destructive_operation": false
  },
  "warnings": [],
  "next_steps": [
    "Review generated JSON files.",
    "Run local validation before onboarding or upload workflows.",
    "Add real endpoints only after review; do not store secrets in generated config files."
  ]
}
```

For custom profiles, use `profile.source="path"` and include the resolved path. For production-oriented runs, include warning objects such as:

```json
{
  "code": "PRODUCTION_TARGET_SAFE_LOCAL_ONLY",
  "message": "Production target defaults selected; generated configs remain local and non-executable by default."
}
```

JSON errors must use this shape:

```json
{
  "status": "error",
  "command": "config init",
  "error": {
    "code": "OUTPUT_DIR_EXISTS",
    "message": "Target workspace already exists.",
    "details": {
      "path": ".local-configs/client_acme_ab12cd"
    },
    "next_step": "Choose a new --output-dir or rerun with --overwrite."
  },
  "generated_files": {},
  "safety": {
    "aws_calls_made": false,
    "configs_uploaded": false,
    "schedules_created": false
  }
}
```

## 14. Developer Handoff Notes

- Do not print human-readable text to stdout in `--output json` mode. If diagnostic logging is unavoidable, use stderr and ensure tests parse stdout as JSON.
- Preserve stable ordering of human-readable blocks and generated file paths for QA assertions.
- Validate all fail-fast conditions before reporting success. Missing/invalid profiles and existing output directories without `--overwrite` must not modify files.
- Production profile generation is permitted, but output must clearly state that configs remain local, non-executable, and safe by default.
- Never imply that AWS resources, schedules, uploads, metadata, approvals, or production execution were created.
- Do not include secrets, tokens, credentials, real customer endpoints, or stack traces in output.
- Use stable error codes listed in this specification so QA can assert behavior.

### UX Acceptance Criteria

- Minimal command output identifies the implicit `dev` profile and generated workspace.
- Named and custom profile outputs distinguish `source: named profile` from `source: custom profile path`.
- Output communicates override precedence as explicit CLI argument → profile `operator_defaults` → safe fallback.
- Human-readable success output includes IDs, workspace path, all generated file paths, selected profile, safety copy, and next steps.
- `--output json` stdout is valid JSON with equivalent non-secret content and no surrounding prose.
- Errors for required failure cases include a stable code, reason, next step, and no misleading success language.
- Existing output directory without `--overwrite` fails before modification.
- Production-oriented profile output includes warning/safety copy while generating safe local configs.
- CLI output remains readable without color and with terminal line wrapping.
