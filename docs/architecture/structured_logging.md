# Structured Logging Standard

Future application logs must be JSON-compatible and use stable field names.

Standard fields:

- `timestamp`
- `level`
- `message`
- `service`
- `stage`
- `event_type`

Correlation fields when available:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_id`
- `raw_result_version`

Logs must not include secrets, credentials, authorization headers, cookies, tokens, passwords, or sensitive request/response payloads.
