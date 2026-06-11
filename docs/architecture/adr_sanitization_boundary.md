# ADR: Sanitization Boundary — Permitted and Prohibited Call Sites for `sanitize()`

## Status

Accepted

## Date

2026-06-12

## Context

The shared `sanitize()` function in `packages/sanitization/sanitizer.py` (and `src/release_confidence_platform/sanitization/sanitizer.py`) applies PII redaction rules — including `PHONE_PATTERN` — recursively to all values in a dict. This function exists to prevent PII from appearing in logs, structured log events, user-visible CLI output, and diagnostic API response payloads.

The incident documented in `docs/bugs/phase_3_phase_4_execution_integrity_rca.md` established that `sanitize()` was being applied to DynamoDB item dicts before persistence. UUID v4 values whose hex digit sequences contain a ten-digit substring matching `PHONE_PATTERN` (e.g., `48a87626-e2f9-4f81-82ff-2475004829ec`, where `2475004829` matches) are silently mutated before being written to DynamoDB. Specifically:

- `packages/storage/dynamodb_client.py:33` — `put_started_once()` passes `Item=sanitize(item)`, mutating `PK`, `SK`, and `run_id` before persistence.
- `packages/storage/dynamodb_client.py:45` — `update_terminal()` passes `sanitize(updates).values()` into the expression values, mutating update field values before the DynamoDB update expression is built.
- `apps/backend/orchestrator/service.py:~599` — `_started_item()` wraps the returned dict in `sanitize(...)`, mutating canonical identifier fields (`PK`, `SK`, `run_id`) before they are returned to callers.

Because `update_terminal()` uses the unsanitized key for the DynamoDB condition expression (`attribute_exists(PK) AND attribute_exists(SK)`) but `put_started_once()` persisted the item under a sanitized key, the `ConditionalCheckFailedException` is thrown for every terminal update on an affected UUID. The RUN record is left permanently in `STARTED` state.

The root issue is not that `PHONE_PATTERN` is wrong, nor that the sanitizer logic is incorrect for its intended scope. The issue is that `sanitize()` is being called at a trust boundary where its effect is harmful: persistence paths that write canonical identifier material to durable storage.

## Decision

`sanitize()` is scoped to the following output paths only:

- Structured log events (any call through `StructuredLogger` or equivalent logging helpers)
- User-visible CLI output
- Diagnostic API response payloads (HTTP responses, health check bodies, error response bodies intended for human or operator consumption)

`sanitize()` MUST NOT be applied to any field that will be used as a DynamoDB primary key (`PK`), sort key (`SK`), or any component of a composite key, nor to any canonical identifier field. Canonical identifier fields include, but are not limited to:

- `run_id`
- `audit_id`
- `client_id`
- S3 object key paths (any field whose value is used to construct or match an S3 key)
- Lineage identifier fields (`schedule_occurrence_id`, `claim_key`, and equivalent correlation identifiers)

Persistence functions (`put_started_once()`, `update_terminal()`, and any future DynamoDB write function) must receive item dicts and update dicts with canonical identifier values intact. The persistence layer is not a sanitization boundary.

## Rationale

`sanitize()` is a lossy, one-way transformation. Once a value is mutated by `sanitize()`, the original value cannot be recovered from the persisted record. DynamoDB primary keys and sort keys are the sole addressing mechanism for items; a key written under a sanitized value cannot be matched by any subsequent operation using the canonical (unsanitized) identifier. The terminal update, S3 key construction, and all downstream phases reference the canonical identifier. Any divergence between the persisted key and the canonical identifier produces a permanent, silent inconsistency that cannot be corrected without administrative recovery.

The sanitizer's purpose — preventing PII from appearing in observable output — is legitimate and must be preserved for all output paths. The sanitizer's scope must be constrained so it does not cross the persistence boundary.

## Alternatives Considered

### Narrow `PHONE_PATTERN` to exclude UUID hex digit sequences

Rejected. Changing `PHONE_PATTERN` alters `sanitize()` behavior for all callers, including legitimate log and output sanitization paths that currently rely on the existing pattern. A UUID-aware pattern exclusion would require characterizing all UUID formats used across the platform and would be fragile to any change in ID generation strategy. This is a change to sanitizer behavior, not a boundary problem — and the boundary problem exists independently of the specific pattern that triggered the incident.

### Use a separate persistence-safe serializer for DynamoDB writes

Rejected. The correct fix is not to build a second serializer; it is to not call `sanitize()` at the persistence boundary at all. A separate serializer would duplicate responsibility and would need to be maintained in parallel with the sanitizer. It also would not prevent future callers from incorrectly routing persistence writes through `sanitize()`.

### Annotate fields as PII-safe to allow `sanitize()` to skip them

Rejected. Annotation-based skip logic is fragile at scale: it requires every field added to a persistence dict to be correctly annotated, and a missing annotation silently applies sanitization. The invariant "persistence paths must not call `sanitize()`" is simpler, statically checkable, and does not degrade with codebase growth.

## Consequences

### Positive

- Canonical identifiers (`run_id`, `audit_id`, `client_id`, S3 keys) are written byte-identical to their generated values at all persistence sites.
- Terminal update keys always match the initially persisted item keys, eliminating the `ConditionalCheckFailedException` failure mode for phone-pattern UUIDs.
- S3 key paths constructed from `run_id` match the S3 key segment used in the finalization gate's Check 3 and Check 4, because the same unsanitized identifier is used at both write time and query time.
- The regression test (see below) provides a permanent guard against re-introduction of this defect.

### Constraints introduced

- `put_started_once()` in `packages/storage/dynamodb_client.py:33` must not call `sanitize(item)`. The call must be removed. The `Item` argument must be the raw item dict.
- `update_terminal()` in `packages/storage/dynamodb_client.py:45` must not call `sanitize(updates)`. The expression values must be built from the raw `updates` dict values.
- `_started_item()` in `apps/backend/orchestrator/service.py:~599` must not wrap the returned dict in `sanitize(...)`. Callers that pass the started item to log output must apply `sanitize()` at the logging call site, not at the item-construction site.
- Any future persistence function that writes a DynamoDB item or update expression must not call `sanitize()` on the item dict or on any field used as a key component. This constraint must be reviewed at every code review that introduces a DynamoDB write.
- Output and logging paths remain required to use `sanitize()`. Removing `sanitize()` from persistence paths does not relax any sanitization requirement for logs, CLI output, or API responses.

### Canonical regression test

The following assertion must exist as a permanent, non-skippable regression test in the test suite:

```
assert put_started_once(run_id="48a87626-e2f9-4f81-82ff-2475004829ec")
       persists SK byte-identical to "AUDIT#{audit_id}#RUN#48a87626-e2f9-4f81-82ff-2475004829ec"
```

This specific UUID (`48a87626-e2f9-4f81-82ff-2475004829ec`) must be used because `PHONE_PATTERN` is confirmed to match its digit sequence (`2475004829`). The regression test must verify that the persisted `SK` contains `2475004829ec` without redaction, not `[REDACTED]ec`.

## References

- RCA: `docs/bugs/phase_3_phase_4_execution_integrity_rca.md`
- Remediation plan (WS-A): `docs/bugs/execution_integrity_remediation_plan.md`
- Sanitizer: `packages/sanitization/sanitizer.py`
- DynamoDB client (packages): `packages/storage/dynamodb_client.py`
- DynamoDB client (src): `src/release_confidence_platform/storage/dynamodb_client.py`
- Orchestrator service: `apps/backend/orchestrator/service.py`
- Logging (StructuredLogger confirms unconditional sanitize call): `packages/core/logging.py`
- Finalization gate design: `docs/architecture/finalization_integrity_gate_design.md`
- Evidence source of truth ADR: `docs/architecture/adr_execution_evidence_source_of_truth.md`
