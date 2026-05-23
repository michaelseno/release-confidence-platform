# Operator CLI `rcp`

Internal operator entry point for Release Confidence Platform audit operations.

Primary invocation:

```bash
python scripts/rcp.py audit validate --client-config client.json --audit-config audit.json --endpoints-config endpoints.json --stage dev
```

Discovery examples:

```bash
python scripts/rcp.py client list --stage dev --limit 100
python scripts/rcp.py audit list --client-id client_demo --stage dev --limit 25 --output json
python scripts/rcp.py config list --client-id client_demo --audit-id audit_001 --stage dev
python scripts/rcp.py config download --client-id client_demo --audit-id audit_001 --output-dir .local-configs/client_demo/audit_001 --stage dev
```

Commands:

- `audit validate`: validate local client/audit/endpoints config files only.
- `audit create`: validate, upload deterministic S3 config objects, and write `DRAFT` audit metadata. Supports `--dry-run` and guarded `--force`.
- `audit schedule`: load persisted audit config/metadata, create enabled schedules, and transition to `SCHEDULED`. Production scheduling requires `--allow-production`.
- `audit run`: manually invoke the orchestrator with `triggered_by=manual`.
- `audit cancel`: record cancellation intent, clean schedules, retain metadata, and exit `3` on partial cleanup failure.
- `client list`: list unique known clients for a stage using a client registry when available, otherwise a temporary bounded audit metadata scan fallback. Supports `--limit` from `1` to `1000` and `--output json`.
- `audit list`: list metadata-only audit summaries for a client. Supports `--limit` from `1` to `1000` and `--output json`.
- `config list`: inspect metadata for the three expected persisted config artifacts without downloading contents.
- `config download`: download only `client_config.json`, `audit_config.json`, and `endpoints.json` to a local directory. Existing files are not replaced unless `--overwrite` is supplied.

Every command requires `--stage dev|staging|prod`. AWS resources resolve from `config/stages/{stage}.json`; non-empty `RCP_*` environment overrides take precedence.

The CLI is internal only and does not accept or print secrets. Discovery commands never access Secrets Manager, raw evidence, or `raw-results/`. Use `--dry-run` for mutating commands before applying changes.

Downloaded configs may contain sensitive operational details. Prefer paths under `.local-configs/`, which is gitignored by this repository, and do not commit downloaded files.

## Setup troubleshooting

Use Python 3.11 for this repository (`pyproject.toml` requires `>=3.11,<3.12`). If an editable install succeeds but `rcp --help` fails with:

```text
ModuleNotFoundError: No module named 'release_confidence_platform'
```

on macOS, hidden file flags on `.venv` can cause Python to skip editable-install `.pth` files. From the repository root, clear the flags and reinstall:

```bash
chflags -R nohidden .venv
.venv/bin/python -m pip install -e .
hash -r
rcp --help
rcp audit --help
```

If that does not resolve the issue, rebuild the virtual environment:

```bash
rm -rf .venv
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip setuptools
.venv/bin/python -m pip install -e .[dev]
hash -r
rcp --help
rcp audit --help
```

Deferred operator workflows are documented for future planning only and are not implemented here: `config delete`, `config archive`, `run list`, `run inspect`, `audit status`, `schedule status`, and version-specific config downloads via `--version-id`.
