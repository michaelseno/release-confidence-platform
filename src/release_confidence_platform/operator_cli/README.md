# packages.operator_cli

Thin argparse and rendering layer for the internal `rcp` CLI.

Command handlers only translate parsed arguments to shared service calls. Business rules live in shared modules under `packages/config`, `packages/core`, `packages/audit_scheduling`, `packages/audit_lifecycle`, and `packages/storage`.
