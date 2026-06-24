"""Phase 4 aggregation orchestrator."""

from __future__ import annotations

import json
import re
from typing import Any

from release_confidence_platform.aggregation.constants import (
    EVIDENCE_PRODUCING_REASON_CODES,
    EVIDENCE_TRANSFORMING_REASON_CODES,
    FAILURE_CATEGORY_EVIDENCE_PRODUCING,
    FAILURE_CATEGORY_EVIDENCE_TRANSFORMING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_CONFLICT,
    JOB_STATUS_DUPLICATE_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_INELIGIBLE,
    JOB_STATUS_INTENT_RECORDED,
    JOB_STATUS_INVOCATION_FAILED,
    JOB_STATUS_INVOCATION_REQUESTED,
    JOB_STATUS_STARTED,
    LINEAGE_PAGE_SIZE,
    MAX_AGGREGATE_ITEM_BYTES,
    MAX_AGGREGATE_RECORDS,
    MAX_AGGREGATE_TRANSACTION_BYTES,
    MAX_ENDPOINT_ID_LENGTH,
    MAX_MANIFEST_BYTES,
    UNKNOWN_ENDPOINT,
)
from release_confidence_platform.aggregation.eligibility import (
    AggregationIneligibleError,
    resolve_config_version,
)
from release_confidence_platform.aggregation.engine import build_aggregates, normalize_failure_type
from release_confidence_platform.aggregation.identity import AuditExecutionIdentityResolver
from release_confidence_platform.aggregation.integrity import validate_evidence_integrity
from release_confidence_platform.aggregation.lineage import (
    build_manifest_header_v2,
    build_manifest_page,
    manifest_ref,
    paginate_records,
)
from release_confidence_platform.aggregation.models import RawAggregationRecord
from release_confidence_platform.aggregation.repository import (
    AggregationRepository,
    ConditionalWriteError,
)
from release_confidence_platform.core.constants.engine import (
    LOG_CATEGORY_INTERNAL,
    RAW_RESULT_VERSION,
)
from release_confidence_platform.core.exceptions import EngineError, ValidationError
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.core.validators import validate_identifier
from release_confidence_platform.sanitization.sanitizer import sanitize


class AggregationOrchestrator:
    def __init__(
        self,
        *,
        repository: AggregationRepository,
        s3_storage: Any,
        logger: StructuredLogger | None = None,
    ):
        self.repository = repository
        self.s3_storage = s3_storage
        self.logger = logger or StructuredLogger()
        self.identity_resolver = AuditExecutionIdentityResolver(repository)

    def run(self, event: dict[str, Any]) -> dict[str, Any]:
        client_id = event["client_id"]
        audit_id = event["audit_id"]
        aggregation_version = event["aggregation_version"]
        job_id = (
            event.get("aggregation_job_id")
            or f"aggjob_{utc_now_iso().replace(':', '').replace('-', '').replace('.', '')}"
        )
        job_key = self.repository.job_keys(client_id, audit_id, job_id)
        started_at = utc_now_iso()
        _diagnostic_run_count = 0
        _diagnostic_record_count = 0
        try:
            try:
                self.repository.put_job_once(
                    {
                        **job_key,
                        "client_id": client_id,
                        "audit_id": audit_id,
                        "aggregation_job_id": job_id,
                        "aggregation_version": aggregation_version,
                        "status": JOB_STATUS_STARTED,
                        "reason_code": None,
                        "failure_category": None,
                        "started_at": started_at,
                        "completed_at": None,
                        "audit_execution_id": None,
                        "config_version": None,
                    }
                )
            except ConditionalWriteError:
                existing = (
                    self.repository.get_job(job_key)
                    if hasattr(self.repository, "get_job")
                    else None
                )
                if existing and existing.get("status") in {
                    JOB_STATUS_INTENT_RECORDED,
                    JOB_STATUS_INVOCATION_REQUESTED,
                    JOB_STATUS_INVOCATION_FAILED,
                }:
                    self.repository.update_job(
                        job_key,
                        {
                            "status": JOB_STATUS_STARTED,
                            "started_at": started_at,
                            "reason_code": None,
                            "failure_category": None,
                        },
                    )
                else:
                    return self._handle_duplicate_job(
                        job_key, client_id, audit_id, aggregation_version, job_id
                    )
            self.logger.log(
                "aggregation_job_claimed",
                event_type="aggregation_job_claimed",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                aggregation_version=aggregation_version,
            )
            audit = self.repository.get_audit_metadata(client_id, audit_id)
            audit_execution_id = self.identity_resolver.resolve_or_assign(
                client_id, audit_id, audit
            )
            config_version = resolve_config_version(audit)
            self.repository.update_job(
                job_key,
                {"audit_execution_id": audit_execution_id, "config_version": config_version},
            )
            if self.repository.aggregate_set_exists(
                client_id, audit_id, audit_execution_id, config_version, aggregation_version
            ):
                return self._complete_job(
                    job_key,
                    client_id,
                    audit_id,
                    audit_execution_id,
                    config_version,
                    aggregation_version,
                    job_id,
                    JOB_STATUS_DUPLICATE_COMPLETED,
                    "DUPLICATE_COMPLETED",
                    0,
                    0,
                    0,
                    None,
                    None,
                )
            runs = self.repository.list_completed_runs(client_id, audit_id)
            _diagnostic_run_count = len(runs)
            records = self._load_records(runs, client_id=client_id, audit_id=audit_id)
            _diagnostic_record_count = len(records)
            self.logger.log(
                "aggregation_eligibility_evaluated",
                event_type="aggregation_eligibility_evaluated",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                result="eligible",
                reason_code=None,
                source_run_count=len(runs),
            )
            integrity = validate_evidence_integrity(
                audit=audit,
                runs=runs,
                records=records,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
            )
            self.logger.log(
                "aggregation_integrity_gate_evaluated",
                event_type="aggregation_integrity_gate_evaluated",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                result="pass",
                expected_count=integrity.expected_execution_count,
                observed_count=integrity.source_run_count,
                reason_code=None,
            )
            all_items, lineage_pages = self._build_persisted_records(
                client_id,
                audit_id,
                audit_execution_id,
                config_version,
                aggregation_version,
                job_id,
                utc_now_iso(),
                records,
                integrity.expected_execution_count,
                integrity.source_run_count,
                integrity.source_raw_result_count,
            )
            self.logger.log(
                "aggregation_manifest_write_started",
                event_type="aggregation_manifest_write_started",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                manifest_scope="audit",
                source_ref_count=len(records),
            )
            self._write_lineage_pages(lineage_pages)
            try:
                self.repository.put_records_once(all_items)
            except ConditionalWriteError:
                if self.repository.aggregate_set_exists(
                    client_id, audit_id, audit_execution_id, config_version, aggregation_version
                ):
                    return self._complete_job(
                        job_key,
                        client_id,
                        audit_id,
                        audit_execution_id,
                        config_version,
                        aggregation_version,
                        job_id,
                        JOB_STATUS_DUPLICATE_COMPLETED,
                        "DUPLICATE_COMPLETED",
                        len(runs),
                        len(records),
                        0,
                        None,
                        None,
                    )
                return self._complete_job(
                    job_key,
                    client_id,
                    audit_id,
                    audit_execution_id,
                    config_version,
                    aggregation_version,
                    job_id,
                    JOB_STATUS_CONFLICT,
                    "AGGREGATE_SET_INCOMPLETE_CONFLICT",
                    len(runs),
                    len(records),
                    0,
                    None,
                    FAILURE_CATEGORY_EVIDENCE_TRANSFORMING,
                )
            aggregate_count = sum(1 for item in all_items if item.get("record_kind") == "aggregate")
            aggregate_set = next(
                (
                    item
                    for item in all_items
                    if item.get("aggregate_type") == "aggregate_set_completion"
                ),
                None,
            )
            audit_aggregate = next(
                (
                    item
                    for item in all_items
                    if item.get("aggregate_type") == "audit"
                ),
                {},
            )
            self.logger.log(
                "aggregation_set_completed",
                event_type="aggregation_set_completed",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                aggregate_record_count=aggregate_count,
                endpoint_count=len(
                    {
                        item.get("endpoint_id")
                        for item in all_items
                        if item.get("aggregate_type") == "endpoint"
                    }
                ),
                manifest_count=sum(
                    1 for item in all_items if item.get("record_kind") == "lineage_manifest"
                ),
            )
            return self._complete_job(
                job_key,
                client_id,
                audit_id,
                audit_execution_id,
                config_version,
                aggregation_version,
                job_id,
                JOB_STATUS_COMPLETED,
                None,
                len(runs),
                len(records),
                aggregate_count,
                audit_aggregate.get("lineage_manifest_ref"),
                None,
                aggregate_set_ref=aggregate_set,
            )
        except AggregationIneligibleError as exc:
            self.logger.log(
                "aggregation_eligibility_evaluated",
                event_type="aggregation_eligibility_evaluated",
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                result="ineligible",
                reason_code=exc.error_type,
                source_run_count=0,
            )
            return self._complete_job(
                job_key,
                client_id,
                audit_id,
                None,
                None,
                aggregation_version,
                job_id,
                JOB_STATUS_INELIGIBLE,
                exc.error_type,
                0,
                0,
                0,
                None,
                None,
            )
        except (ValidationError, ConditionalWriteError, EngineError) as exc:
            reason = getattr(exc, "error_type", "AGGREGATION_FAILED")
            failure_category = _failure_category_for_reason(reason)
            diagnostic_context = getattr(exc, "context", {}) or {}
            self.repository.update_job(
                job_key,
                {
                    "status": JOB_STATUS_FAILED,
                    "reason_code": reason,
                    "failure_category": failure_category,
                    "completed_at": utc_now_iso(),
                    "source_run_count": _diagnostic_run_count,
                    "source_raw_result_count": _diagnostic_record_count,
                    "error_summary": {
                        "reason_code": reason,
                        "component": "AggregationOrchestrator",
                        "aggregation_job_id": job_id,
                        **diagnostic_context,
                    },
                },
            )
            self.logger.log(
                "aggregation_job_failed",
                event_type="aggregation_job_failed",
                log_category=LOG_CATEGORY_INTERNAL,
                level="ERROR",
                service="AggregationOrchestrator",
                stage="aggregation",
                client_id=client_id,
                audit_id=audit_id,
                aggregation_job_id=job_id,
                failure_category=failure_category,
                reason_code=reason,
                component="AggregationOrchestrator",
                **diagnostic_context,
            )
            self._log("aggregation_failed", client_id, audit_id, job_id, reason)
            return sanitize(
                {
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "audit_execution_id": None,
                    "config_version": None,
                    "aggregation_version": aggregation_version,
                    "aggregation_job_id": job_id,
                    "status": JOB_STATUS_FAILED,
                    "aggregate_record_count": 0,
                    "source_raw_result_count": 0,
                    "reason_code": reason,
                }
            )

    def _load_records(
        self, runs: list[dict[str, Any]], *, client_id: str, audit_id: str
    ) -> list[RawAggregationRecord]:
        records: list[RawAggregationRecord] = []
        for run in runs:
            key = run["raw_result_s3_key"]
            _validate_raw_result_s3_key(key, client_id=client_id, audit_id=audit_id)
            try:
                envelope = self.s3_storage.read_json(key)
            except Exception as exc:
                raise ValidationError("Missing raw evidence", "MISSING_RAW_EVIDENCE") from exc
            if (
                envelope.get("raw_result_version") != RAW_RESULT_VERSION
                or envelope.get("client_id") != client_id
                or envelope.get("audit_id") != audit_id
                or envelope.get("run_id") != run.get("run_id")
            ):
                raise ValidationError("Invalid raw result envelope", "INVALID_RAW_RESULT_ENVELOPE")
            results = envelope.get("results")
            if not isinstance(results, list):
                raise ValidationError("Invalid raw result records", "INVALID_RAW_RESULT_ENVELOPE")
            for index, result in enumerate(results):
                if not isinstance(result, dict):
                    raise ValidationError("Invalid raw result record", "INVALID_RAW_RESULT_RECORD")
                records.append(
                    RawAggregationRecord(
                        RAW_RESULT_VERSION,
                        validate_identifier("run_id", run["run_id"]),
                        key,
                        run.get("s3_version_id"),
                        index,
                        _safe_endpoint_id(result.get("endpoint_id")),
                        result.get("timestamp")
                        if isinstance(result.get("timestamp"), str)
                        else None,
                        result.get("duration_ms"),
                        result.get("status_code")
                        if isinstance(result.get("status_code"), int)
                        and not isinstance(result.get("status_code"), bool)
                        else None,
                        normalize_failure_type(result.get("failure_type")),
                    )
                )
        return records

    def _build_lineage_scope(
        self,
        *,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        job_id: str,
        timestamp: str,
        manifest_scope: str,
        records: list[RawAggregationRecord],
        pk: str,
        manifest_sk: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        common = dict(
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            config_version=config_version,
            aggregation_version=aggregation_version,
            aggregation_job_id=job_id,
            created_at=timestamp,
        )
        pages: list[dict[str, Any]] = []
        page_hashes: list[str] = []
        for page_index, page_records in enumerate(
            paginate_records(records, page_size=LINEAGE_PAGE_SIZE)
        ):
            page = build_manifest_page(
                **common,
                manifest_scope=manifest_scope,
                page_index=page_index,
                page_records=page_records,
            )
            _fail_if_too_large(
                page,
                MAX_MANIFEST_BYTES,
                "LINEAGE_MANIFEST_TOO_LARGE",
                context={
                    "manifest_scope": manifest_scope,
                    "source_ref_count": len(records),
                    "page_size": LINEAGE_PAGE_SIZE,
                    "page_index": page_index,
                },
            )
            pages.append({"PK": pk, "SK": f"{manifest_sk}#PAGE#{page_index}", **page})
            page_hashes.append(page["page_hash"])
        header = build_manifest_header_v2(
            **common,
            manifest_scope=manifest_scope,
            source_ref_count=len(records),
            page_size=LINEAGE_PAGE_SIZE,
            page_hashes=page_hashes,
        )
        _fail_if_too_large(
            header,
            MAX_MANIFEST_BYTES,
            "LINEAGE_MANIFEST_TOO_LARGE",
            context={
                "manifest_scope": manifest_scope,
                "source_ref_count": len(records),
                "page_size": LINEAGE_PAGE_SIZE,
            },
        )
        ref = manifest_ref(header, pk=pk, sk=manifest_sk)
        return header, ref, pages

    def _write_lineage_pages(self, pages: list[dict[str, Any]]) -> None:
        for page in pages:
            try:
                self.repository.put_lineage_page_once(page)
            except ConditionalWriteError as exc:
                existing = self.repository.get_lineage_page({"PK": page["PK"], "SK": page["SK"]})
                if not existing or existing.get("page_hash") != page.get("page_hash"):
                    raise ValidationError(
                        "Lineage page hash mismatch",
                        "LINEAGE_PAGE_HASH_MISMATCH",
                        context={
                            "manifest_scope": page.get("manifest_scope"),
                            "page_index": page.get("page_index"),
                        },
                    ) from exc

    def _build_persisted_records(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        job_id: str,
        timestamp: str,
        records: list[RawAggregationRecord],
        expected_execution_count: int,
        source_run_count: int,
        source_raw_result_count: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prefix = self.repository.aggregate_prefix(
            client_id, audit_id, audit_execution_id, config_version, aggregation_version
        )
        pk = f"CLIENT#{client_id}"
        manifest_sk = f"{prefix}#LINEAGE#audit"
        header, ref, lineage_pages = self._build_lineage_scope(
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            config_version=config_version,
            aggregation_version=aggregation_version,
            job_id=job_id,
            timestamp=timestamp,
            manifest_scope="audit",
            records=records,
            pk=pk,
            manifest_sk=manifest_sk,
        )
        lineage = {
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "aggregation_job_id": job_id,
            "aggregation_timestamp": timestamp,
            "lineage_manifest_ref": ref,
            "source_ref_count": len(records),
            "lineage_manifest_hash": header["manifest_hash"],
        }
        aggregates = build_aggregates(records)
        items = [
            {
                "PK": pk,
                "SK": manifest_sk,
                "record_kind": "lineage_manifest",
                **header,
            }
        ]
        records_by_endpoint: dict[str, list[RawAggregationRecord]] = {}
        for record in records:
            records_by_endpoint.setdefault(record.endpoint_id, []).append(record)
        endpoint_lineages: dict[str, dict[str, Any]] = {}
        for endpoint_id, endpoint_records in sorted(records_by_endpoint.items()):
            endpoint_manifest_sk = f"{prefix}#LINEAGE#endpoint:{endpoint_id}"
            endpoint_header, endpoint_ref, endpoint_pages = self._build_lineage_scope(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                job_id=job_id,
                timestamp=timestamp,
                manifest_scope=f"endpoint:{endpoint_id}",
                records=endpoint_records,
                pk=pk,
                manifest_sk=endpoint_manifest_sk,
            )
            lineage_pages.extend(endpoint_pages)
            endpoint_lineages[endpoint_id] = {
                "client_id": client_id,
                "audit_id": audit_id,
                "audit_execution_id": audit_execution_id,
                "config_version": config_version,
                "aggregation_version": aggregation_version,
                "aggregation_job_id": job_id,
                "aggregation_timestamp": timestamp,
                "lineage_manifest_ref": endpoint_ref,
                "source_ref_count": len(endpoint_records),
                "lineage_manifest_hash": endpoint_header["manifest_hash"],
            }
            items.append(
                {
                    "PK": pk,
                    "SK": endpoint_manifest_sk,
                    "record_kind": "lineage_manifest",
                    **endpoint_header,
                }
            )
        audit_item = {
            "PK": pk,
            "SK": f"{prefix}#AUDIT",
            "record_kind": "aggregate",
            "aggregate_type": "audit",
            "client_id": client_id,
            "audit_id": audit_id,
            "aggregation_version": aggregation_version,
            "lineage": lineage,
            "lineage_manifest_ref": ref,
            "created_at": timestamp,
            **aggregates["audit"],
        }
        audit_item.pop("failure_classification_counts")
        items.append(audit_item)
        items.append(
            {
                "PK": pk,
                "SK": f"{prefix}#FAILURE_CLASSIFICATION",
                "record_kind": "aggregate",
                "aggregate_type": "failure_classification",
                "scope": "audit",
                "endpoint_id": None,
                "classification_counts": aggregates["audit"]["failure_classification_counts"],
                "lineage": lineage,
            }
        )
        for endpoint_id, endpoint in aggregates["endpoints"].items():
            endpoint_lineage = endpoint_lineages[endpoint_id]
            items.append(
                {
                    "PK": pk,
                    "SK": f"{prefix}#ENDPOINT#{endpoint_id}",
                    "record_kind": "aggregate",
                    "aggregate_type": "endpoint",
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "aggregation_version": aggregation_version,
                    "lineage": endpoint_lineage,
                    "lineage_manifest_ref": endpoint_lineage["lineage_manifest_ref"],
                    **endpoint,
                }
            )
            items.append(
                {
                    "PK": pk,
                    "SK": f"{prefix}#ENDPOINT#{endpoint_id}#FAILURE_CLASSIFICATION",
                    "record_kind": "aggregate",
                    "aggregate_type": "failure_classification",
                    "scope": "endpoint",
                    "endpoint_id": endpoint_id,
                    "classification_counts": endpoint["failure_classification_counts"],
                    "lineage": endpoint_lineage,
                }
            )
        aggregate_count = sum(1 for item in items if item.get("record_kind") == "aggregate")
        completion = {
            "PK": pk,
            "SK": f"{prefix}#SET",
            "record_kind": "aggregate_set_completion",
            "aggregate_type": "aggregate_set_completion",
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "aggregation_job_id": job_id,
            "completion_status": "COMPLETE",
            "created_at": timestamp,
            "expected_execution_count": expected_execution_count,
            "source_run_count": source_run_count,
            "source_raw_result_count": source_raw_result_count,
            "aggregate_record_count": aggregate_count,
            "endpoint_aggregate_count": len(aggregates["endpoints"]),
            "manifest_count": 1 + len(endpoint_lineages),
            "audit_lineage_manifest_ref": ref,
        }
        completion["aggregate_set_hash"] = __import__("hashlib").sha256(
            json.dumps(completion, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        items.append(completion)
        if len(items) > MAX_AGGREGATE_RECORDS:
            raise ValidationError("Aggregate set too large", "AGGREGATE_SET_TOO_LARGE")
        total_bytes = 0
        for item in items:
            _fail_if_too_large(item, MAX_AGGREGATE_ITEM_BYTES, "AGGREGATE_SET_TOO_LARGE")
            total_bytes += len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
        if total_bytes > MAX_AGGREGATE_TRANSACTION_BYTES:
            raise ValidationError("Aggregate set too large", "AGGREGATE_SET_TOO_LARGE")
        return items, lineage_pages

    def _validate_duplicate_refs(self, records: list[RawAggregationRecord]) -> None:
        seen = set()
        for record in records:
            if record.ref_identity in seen:
                raise ValidationError(
                    "Duplicate raw result reference", "DUPLICATE_RAW_RESULT_REFERENCE"
                )
            seen.add(record.ref_identity)

    def _complete_job(
        self,
        key: dict[str, str],
        client_id: str,
        audit_id: str,
        audit_execution_id: str | None,
        config_version: str | None,
        aggregation_version: str,
        job_id: str,
        status: str,
        reason: str | None,
        run_count: int,
        raw_count: int,
        aggregate_count: int,
        manifest_ref_value: dict[str, Any] | None,
        failure_category: str | None,
        *,
        aggregate_set_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.repository.update_job(
            key,
            {
                "status": status,
                "reason_code": reason,
                "failure_category": failure_category,
                "completed_at": utc_now_iso(),
                "source_run_count": run_count,
                "source_raw_result_count": raw_count,
                "aggregate_record_count": aggregate_count,
                "lineage_manifest_ref": manifest_ref_value,
                "aggregate_set_ref": _aggregate_set_ref(aggregate_set_ref),
            },
        )
        self._log(
            "aggregation_completed" if status == JOB_STATUS_COMPLETED else "aggregation_outcome",
            client_id,
            audit_id,
            job_id,
            reason,
        )
        return sanitize(
            {
                "client_id": client_id,
                "audit_id": audit_id,
                "audit_execution_id": audit_execution_id,
                "config_version": config_version,
                "aggregation_version": aggregation_version,
                "aggregation_job_id": job_id,
                "status": status,
                "aggregate_record_count": aggregate_count,
                "source_raw_result_count": raw_count,
                "reason_code": reason,
            }
        )

    def _handle_duplicate_job(
        self,
        key: dict[str, str],
        client_id: str,
        audit_id: str,
        aggregation_version: str,
        job_id: str,
    ) -> dict[str, Any]:
        existing = self.repository.get_job(key) if hasattr(self.repository, "get_job") else None
        if existing and existing.get("status") in {
            JOB_STATUS_COMPLETED,
            JOB_STATUS_DUPLICATE_COMPLETED,
        }:
            return self._complete_job(
                key,
                client_id,
                audit_id,
                existing.get("audit_execution_id"),
                existing.get("config_version"),
                aggregation_version,
                job_id,
                JOB_STATUS_DUPLICATE_COMPLETED,
                "DUPLICATE_COMPLETED",
                existing.get("source_run_count") or 0,
                existing.get("source_raw_result_count") or 0,
                0,
                existing.get("lineage_manifest_ref"),
                None,
            )
        return self._complete_job(
            key,
            client_id,
            audit_id,
            existing.get("audit_execution_id") if existing else None,
            existing.get("config_version") if existing else None,
            aggregation_version,
            job_id,
            JOB_STATUS_CONFLICT,
            "AGGREGATE_WRITE_CONFLICT",
            existing.get("source_run_count") if existing else 0,
            existing.get("source_raw_result_count") if existing else 0,
            0,
            None,
            FAILURE_CATEGORY_EVIDENCE_TRANSFORMING,
        )

    def _log(
        self, message: str, client_id: str, audit_id: str, job_id: str, reason: str | None
    ) -> None:
        self.logger.log(
            message,
            log_category=LOG_CATEGORY_INTERNAL,
            client_id=client_id,
            audit_id=audit_id,
            aggregation_job_id=job_id,
            reason_code=reason,
        )


def _safe_endpoint_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return UNKNOWN_ENDPOINT
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "http://",
            "https://",
            "?",
            "token",
            "secret",
            "password",
            "cookie",
            "authorization",
            "@",
        )
    ):
        return UNKNOWN_ENDPOINT
    try:
        safe = validate_identifier("endpoint_id", value)
    except ValidationError:
        return UNKNOWN_ENDPOINT
    if len(safe) <= MAX_ENDPOINT_ID_LENGTH:
        return safe
    return "endpoint_hash_" + __import__("hashlib").sha256(safe.encode()).hexdigest()[:32]


_SAFE_RAW_RESULT_KEY_PATTERN = re.compile(
    r"\Araw-results/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./=-]+\Z"
)
_UNSAFE_RAW_KEY_MARKERS = (
    "http://",
    "https://",
    "?",
    "#",
    "&",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "authorization",
    "credential",
    "api_key",
    "apikey",
    "header",
    "payload",
    "request_body",
    "response_body",
    "body",
    "ssn",
)


def _validate_raw_result_s3_key(key: Any, *, client_id: str, audit_id: str) -> str:
    if not isinstance(key, str) or not key:
        raise ValidationError("Unsafe raw result key", "UNSAFE_RAW_RESULT_S3_KEY")
    expected_prefix = f"raw-results/{client_id}/{audit_id}/"
    lowered = key.lower()
    if (
        not key.startswith(expected_prefix)
        or not _SAFE_RAW_RESULT_KEY_PATTERN.fullmatch(key)
        or ".." in key
        or any(marker in lowered for marker in _UNSAFE_RAW_KEY_MARKERS)
    ):
        raise ValidationError("Unsafe raw result key", "UNSAFE_RAW_RESULT_S3_KEY")
    return key


def _fail_if_too_large(
    item: dict[str, Any],
    max_bytes: int,
    reason: str,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    size = len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
    if size > max_bytes:
        raise ValidationError(
            "Aggregation item too large",
            reason,
            context={**(context or {}), "estimated_size_bytes": size, "max_bytes": max_bytes},
        )


def _failure_category_for_reason(reason: str) -> str:
    if reason in EVIDENCE_PRODUCING_REASON_CODES:
        return FAILURE_CATEGORY_EVIDENCE_PRODUCING
    if reason in EVIDENCE_TRANSFORMING_REASON_CODES:
        return FAILURE_CATEGORY_EVIDENCE_TRANSFORMING
    return FAILURE_CATEGORY_EVIDENCE_TRANSFORMING


def _aggregate_set_ref(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "PK": item["PK"],
        "SK": item["SK"],
        "aggregate_set_hash": item.get("aggregate_set_hash"),
        "completion_status": item.get("completion_status"),
    }
