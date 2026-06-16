"""Safe local identifier generation for operator-created config templates."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, date, datetime

from packages.core.exceptions import ValidationError
from packages.core.slug_utils import slugify_client_name
from packages.core.validators import validate_identifier

_SHORTID = re.compile(r"^[a-f0-9]{8,}$")


def _shortid(value: str | None = None) -> str:
    generated = value or secrets.token_hex(4)
    if not isinstance(generated, str) or not _SHORTID.fullmatch(generated):
        raise ValidationError(
            "shortid must be lowercase hex with at least 8 characters", "INVALID_ARGUMENT"
        )
    return generated


def generate_client_id(client_name: str, *, shortid: str | None = None) -> str:
    client_id = f"client_{slugify_client_name(client_name)}_{_shortid(shortid)}"
    return validate_identifier("client_id", client_id)


def generate_audit_id(*, today: date | None = None, shortid: str | None = None) -> str:
    current = today or datetime.now(UTC).date()
    audit_id = f"audit_{current.strftime('%Y%m%d')}_{_shortid(shortid)}"
    return validate_identifier("audit_id", audit_id)
