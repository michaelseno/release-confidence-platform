"""Constants for Phase 4 aggregation."""

AGGREGATION_VERSION = "agg_v1"
AGGREGATION_EVENT_TYPE = "aggregate_audit"
AGGREGATION_EVENT_SCHEMA_VERSION = "phase4.aggregation_event.v1"
LINEAGE_MANIFEST_VERSION_V1 = "lineage_manifest_v1"
LINEAGE_MANIFEST_VERSION_V2 = "lineage_manifest_v2"

JOB_STATUS_STARTED = "STARTED"
JOB_STATUS_INTENT_RECORDED = "INTENT_RECORDED"
JOB_STATUS_INVOCATION_REQUESTED = "INVOCATION_REQUESTED"
JOB_STATUS_INVOCATION_FAILED = "INVOCATION_FAILED"
JOB_STATUS_COMPLETED = "COMPLETED"
JOB_STATUS_FAILED = "FAILED"
JOB_STATUS_INELIGIBLE = "INELIGIBLE"
JOB_STATUS_DUPLICATE_COMPLETED = "DUPLICATE_COMPLETED"
JOB_STATUS_CONFLICT = "CONFLICT"

FAILURE_CATEGORY_EVIDENCE_PRODUCING = "EVIDENCE_PRODUCING"
FAILURE_CATEGORY_EVIDENCE_TRANSFORMING = "EVIDENCE_TRANSFORMING"

EVIDENCE_PRODUCING_REASON_CODES = frozenset(
    {
        "EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS",
        "EXECUTION_COUNT_MISMATCH_RAW_RESULTS",
        "ORPHANED_RAW_RESULT_RECORDS",
        "MISSING_RAW_EVIDENCE",
        "NO_COMPLETED_RUN_EVIDENCE",
        "NO_RAW_RESULT_EVIDENCE",
        "INCOMPLETE_EXECUTION_EVIDENCE",
        "LINEAGE_INCOMPLETE",
        "LINEAGE_CORRUPT",
        "DUPLICATE_RAW_RESULT_REFERENCE",
        "MISSING_AUDIT_EXECUTION_ID",
        "MISSING_CONFIG_VERSION",
        "INVALID_RAW_RESULT_ENVELOPE",
        "INVALID_RAW_RESULT_RECORD",
        "UNSAFE_RAW_RESULT_S3_KEY",
        "LINEAGE_PAGE_HASH_MISMATCH",
    }
)

EVIDENCE_TRANSFORMING_REASON_CODES = frozenset(
    {
        "AGGREGATION_TRIGGER_INVOCATION_FAILED",
        "AGGREGATION_TIMEOUT",
        "TRANSIENT_STORAGE_FAILURE",
        "WORKER_FAILURE",
        "AGGREGATE_WRITE_CONFLICT",
        "AGGREGATE_SET_INCOMPLETE_CONFLICT",
        "CONDITIONAL_WRITE_FAILED",
        "AGGREGATE_SET_TOO_LARGE",
        "LINEAGE_MANIFEST_TOO_LARGE",
    }
)

MISSING_CLASSIFICATION = "MISSING_FAILURE_CLASSIFICATION"
UNKNOWN_CLASSIFICATION = "UNKNOWN_FAILURE_CLASSIFICATION"
NO_STATUS = "NO_STATUS"
UNKNOWN_ENDPOINT = "unknown"

MAX_MANIFEST_BYTES = 300_000

# Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.16.1):
# DynamoDB's TransactWriteItems hard cap is 100 items total, counting every
# item type in the request (Put, ConditionCheck, or otherwise). Transaction
# splitting across multiple TransactWriteItems calls is not authorized
# (Product Strategy decision) -- instead, one slot is permanently reserved
# for the appended LegalHold.hold_version ConditionCheck (Technical Design
# Section 19.4 step 3 Item A), so the governed-record ceiling is the hard
# cap minus that one reserved slot.
_DYNAMODB_TRANSACT_WRITE_ITEMS_HARD_CAP = 100
HOLD_CHECK_RESERVED_TRANSACTION_ITEMS = 1
MAX_AGGREGATE_RECORDS = (
    _DYNAMODB_TRANSACT_WRITE_ITEMS_HARD_CAP - HOLD_CHECK_RESERVED_TRANSACTION_ITEMS
)
MAX_AGGREGATE_ITEM_BYTES = 300_000
MAX_AGGREGATE_TRANSACTION_BYTES = 3_800_000
MAX_ENDPOINT_ID_LENGTH = 128

# Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.16.5;
# ADR Decision 5 amendment / Non-Negotiable Invariant 26): the runtime
# environment variable AggregationRepository's governed write paths
# (put_records_once, put_lineage_page_once) read to resolve the
# aggregate_metadata evidence class's custody-period duration. Mirrors
# packages/storage/dynamodb_client.py's CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR
# naming convention. No default value is defined here -- see
# repository.py::_resolve_aggregate_metadata_custody_period_days for the
# fail-closed resolution logic.
CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA_ENV_VAR = "CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA"

# Validated worst-case ceiling (every identifier field — client_id, audit_id,
# run_id, endpoint_id, audit_execution_id, config_version, aggregation_job_id —
# at its IDENTIFIER_PATTERN-enforced 128-char max; s3_version_id assumed 200
# chars) for refs in one lineage_manifest_v2 page. Pinned by
# test_worst_case_page_at_documented_ceiling_stays_under_byte_cap — see
# docs/architecture/phase_4a_lineage_manifest_pagination_technical_design.md §1.
MAX_MANIFEST_PAGE_REF_COUNT = 275
LINEAGE_PAGE_SIZE = 200
