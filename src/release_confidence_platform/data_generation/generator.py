"""Runner-facing Phase 2 payload preparation service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.data_generation.data_pools import DataPoolLoader, select_record
from release_confidence_platform.data_generation.duplicate_checker import (
    MAX_GENERATION_ATTEMPTS,
    DuplicateChecker,
)
from release_confidence_platform.data_generation.fingerprints import (
    fingerprint,
    payload_fingerprint,
)
from release_confidence_platform.data_generation.templates import (
    TemplateContext,
    TemplateResolutionError,
    render_template,
)
from release_confidence_platform.data_generation.validators import (
    PayloadValidationError,
    validate_endpoint_payload_config,
)


@dataclass(frozen=True)
class RunContext:
    client_id: str
    audit_id: str
    run_id: str
    scenario_type: str
    run_timestamp: str


@dataclass(frozen=True)
class PreparedPayloadResult:
    payload: Any
    payload_fingerprint: str
    metadata: dict[str, Any]


class PayloadPreparationService:
    def __init__(self, *, data_pool_loader: DataPoolLoader | None = None):
        self.data_pool_loader = data_pool_loader

    def prepare(
        self,
        *,
        endpoint: dict[str, Any],
        run_context: RunContext,
        iteration: int,
        duplicate_checker: DuplicateChecker,
    ) -> PreparedPayloadResult:
        endpoint = validate_endpoint_payload_config(endpoint)
        policy = endpoint["duplicate_policy"]
        max_attempts = MAX_GENERATION_ATTEMPTS if policy == "regenerate" else 1
        duplicate_seen = False
        for attempt in range(1, max_attempts + 1):
            payload, pool_record_fingerprint = self._build_payload(
                endpoint=endpoint,
                run_context=run_context,
                iteration=iteration,
                generation_attempt=attempt,
            )
            fp = payload_fingerprint(payload)
            duplicate = False
            bypass_payload_duplicate_check = self._is_static_no_body_safe_method(endpoint, payload)
            if endpoint["payload_strategy"] == "data_pool" and pool_record_fingerprint is not None:
                if endpoint["payload_safety"].get("allow_data_pool_reuse") is not True:
                    duplicate = duplicate_checker.check_and_reserve(
                        scope=endpoint["duplicate_check_scope"],
                        fingerprint=pool_record_fingerprint,
                        duplicate_subject_type="data_pool_record",
                        endpoint_id=endpoint["endpoint_id"],
                        iteration=iteration,
                        payload_strategy=endpoint["payload_strategy"],
                    ).duplicate_detected
            payload_duplicate = False
            if not bypass_payload_duplicate_check:
                payload_duplicate = duplicate_checker.check_and_reserve(
                    scope=endpoint["duplicate_check_scope"],
                    fingerprint=fp,
                    duplicate_subject_type="payload",
                    endpoint_id=endpoint["endpoint_id"],
                    iteration=iteration,
                    payload_strategy=endpoint["payload_strategy"],
                ).duplicate_detected
            duplicate = duplicate or payload_duplicate
            duplicate_seen = duplicate_seen or duplicate
            metadata = self._metadata(
                endpoint,
                fp,
                duplicate_seen,
                attempt,
                pool_record_fingerprint,
                bypass_payload_duplicate_check=bypass_payload_duplicate_check,
            )
            if not duplicate:
                return PreparedPayloadResult(payload, fp, metadata)
            if policy == "allow":
                metadata["duplicate_allowed"] = True
                return PreparedPayloadResult(payload, fp, metadata)
            if policy == "fail_fast":
                raise PayloadValidationError(
                    "Duplicate payload detected", payload_metadata=metadata
                )
        raise PayloadValidationError(
            "Duplicate payload regeneration exhausted", payload_metadata=metadata
        ) from None

    def _build_payload(
        self,
        *,
        endpoint: dict[str, Any],
        run_context: RunContext,
        iteration: int,
        generation_attempt: int,
    ) -> tuple[Any, str | None]:
        strategy = endpoint["payload_strategy"]
        context = TemplateContext(
            client_id=run_context.client_id,
            audit_id=run_context.audit_id,
            run_id=run_context.run_id,
            endpoint_id=endpoint["endpoint_id"],
            iteration=iteration,
            run_timestamp=run_context.run_timestamp,
            generation_attempt=generation_attempt,
        )
        try:
            if strategy == "static":
                return endpoint.get("payload"), None
            if strategy == "generated":
                return render_template(endpoint.get("payload_template"), context), None
            if self.data_pool_loader is None:
                raise PayloadValidationError("Data-pool loader is unavailable")
            records = self.data_pool_loader.load(run_context.client_id, endpoint["data_pool_name"])
            record = select_record(
                records,
                client_id=run_context.client_id,
                audit_id=run_context.audit_id,
                run_id=run_context.run_id,
                endpoint_id=endpoint["endpoint_id"],
                scenario_type=run_context.scenario_type,
                iteration=iteration,
            )
            record_fp = fingerprint(record)
            if endpoint.get("payload_template") is None:
                return record, record_fp
            data_context = TemplateContext(**{**context.__dict__, "data_pool_record": record})
            return render_template(
                endpoint.get("payload_template"), data_context, allow_data_pool_tokens=True
            ), record_fp
        except (TemplateResolutionError, EngineError) as exc:
            raise PayloadValidationError(str(exc)) from exc

    def _metadata(
        self,
        endpoint: dict[str, Any],
        fp: str,
        duplicate_detected: bool,
        attempt: int,
        pool_record_fingerprint: str | None,
        *,
        bypass_payload_duplicate_check: bool = False,
    ) -> dict[str, Any]:
        return {
            "payload_fingerprint": fp,
            "duplicate_check_scope": "not_applicable"
            if bypass_payload_duplicate_check
            else endpoint["duplicate_check_scope"],
            "duplicate_detected": duplicate_detected,
            "duplicate_policy": endpoint["duplicate_policy"],
            "generation_attempt": attempt,
            "data_pool_name": endpoint.get("data_pool_name")
            if endpoint["payload_strategy"] == "data_pool"
            else None,
            "data_pool_record_fingerprint": pool_record_fingerprint,
            "duplicate_allowed": False,
        }

    @staticmethod
    def _is_static_no_body_safe_method(endpoint: dict[str, Any], payload: Any) -> bool:
        return (
            endpoint["payload_strategy"] == "static"
            and payload is None
            and str(endpoint.get("method", "")).upper() in {"GET", "HEAD"}
        )
