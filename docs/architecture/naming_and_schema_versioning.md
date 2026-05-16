# Naming and Schema Versioning

Mandatory identifiers are reserved exactly as follows:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_id`
- `raw_result_version`

Schema versions must be explicit. Raw evidence uses `raw_result_version` to distinguish future evidence formats. Phase 0 does not define production schemas or persistence behavior.

Resource naming conventions:

- `release-confidence-platform-${stage}-raw-results`
- `release-confidence-platform-${stage}-metadata`

Supported stage values are `dev`, `staging`, and `prod`.
