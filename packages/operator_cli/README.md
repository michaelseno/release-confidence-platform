# packages.operator_cli

Compatibility documentation for the internal `rcp` CLI. The implementation now lives under the src-layout package `src/release_confidence_platform/operator_cli`.

Command handlers only translate parsed arguments to shared service calls. Business rules live in shared modules under `src/release_confidence_platform/config`, `core`, `audit_scheduling`, `audit_lifecycle`, `operator_cli/discovery_service.py`, and `storage`.

Operational discovery commands are available through the same `rcp` entry point:

- `rcp client list --stage <stage> [--limit n] [--output json]`
- `rcp audit list --client-id <client_id> --stage <stage> [--limit n] [--output json]`
- `rcp config list --client-id <client_id> --audit-id <audit_id> --stage <stage> [--output json]`
- `rcp config download --client-id <client_id> --audit-id <audit_id> --output-dir <path> --stage <stage> [--overwrite] [--output json]`

Discovery is read-only against AWS. Config downloads write only local files, protect existing files unless `--overwrite` is provided, and should normally be stored under `.local-configs/`.

Future placeholders are not implemented in this package: config delete/archive, run list/inspect, audit status, schedule status, and `--version-id` downloads.
