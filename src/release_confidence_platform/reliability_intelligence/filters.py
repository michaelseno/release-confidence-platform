"""Filter parsing for Phase 5.7 Intelligence Retrieval Layer."""
from __future__ import annotations

from release_confidence_platform.reliability_intelligence.dtypes import IntelligenceFilter


def parse_intelligence_filters(args) -> IntelligenceFilter:
    return IntelligenceFilter(
        client_id=getattr(args, "client", None) or "",
        audit_id=getattr(args, "audit", None) or "",
        audit_execution_id=getattr(args, "execution", None) or "",
        config_version=getattr(args, "config_version", None) or "cfg_v1",
        aggregation_version=getattr(args, "aggregation_version", None) or "agg_v1",
        intelligence_version=getattr(args, "intelligence_version", None) or "intel_v1",
        endpoint_id=getattr(args, "endpoint", None),
    )
