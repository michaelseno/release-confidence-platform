# Operator CLI `rcp`

Internal operator entry point for Release Confidence Platform audit operations.

Primary invocation:

```bash
python scripts/rcp.py audit validate --client-config client.json --audit-config audit.json --endpoints-config endpoints.json --stage dev
```

Commands:

- `audit validate`: validate local client/audit/endpoints config files only.
- `audit create`: validate, upload deterministic S3 config objects, and write `DRAFT` audit metadata. Supports `--dry-run` and guarded `--force`.
- `audit schedule`: load persisted audit config/metadata, create enabled schedules, and transition to `SCHEDULED`. Production scheduling requires `--allow-production`.
- `audit run`: manually invoke the orchestrator with `triggered_by=manual`.
- `audit cancel`: record cancellation intent, clean schedules, retain metadata, and exit `3` on partial cleanup failure.

Every command requires `--stage dev|staging|prod`. AWS resources resolve from `config/stages/{stage}.json`; non-empty `RCP_*` environment overrides take precedence.

The CLI is internal only and does not accept or print secrets. Use `--dry-run` for mutating commands before applying changes.
