"""S3-backed Phase 1 config loaders."""

from typing import Any

from release_confidence_platform.core.constants.engine import (
    AUDIT_CONFIG_KEY_TEMPLATE,
    CLIENT_CONFIG_KEY_TEMPLATE,
    ENDPOINTS_CONFIG_KEY_TEMPLATE,
)


class ClientConfigLoader:
    def __init__(self, s3_client: Any):
        self.s3_client = s3_client

    def load(self, client_id: str) -> dict[str, Any]:
        return self.s3_client.read_json(CLIENT_CONFIG_KEY_TEMPLATE.format(client_id=client_id))


class AuditConfigLoader:
    def __init__(self, s3_client: Any):
        self.s3_client = s3_client

    def load(self, client_id: str, audit_id: str) -> dict[str, Any]:
        return self.s3_client.read_json(
            AUDIT_CONFIG_KEY_TEMPLATE.format(client_id=client_id, audit_id=audit_id)
        )


class EndpointConfigLoader:
    def __init__(self, s3_client: Any):
        self.s3_client = s3_client

    def load(self, client_id: str, audit_id: str) -> dict[str, Any]:
        return self.s3_client.read_json(
            ENDPOINTS_CONFIG_KEY_TEMPLATE.format(client_id=client_id, audit_id=audit_id)
        )
