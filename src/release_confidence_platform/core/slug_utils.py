"""Filesystem-safe slug helpers for local operator workflows."""

from __future__ import annotations

import re
import unicodedata

from release_confidence_platform.core.exceptions import ValidationError

_UNSAFE_BOUNDARY = re.compile(r"[^a-z0-9]+")
_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def slugify_client_name(value: str) -> str:
    """Convert an operator-provided client name to a safe lowercase slug."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("client name must not be empty", "INVALID_ARGUMENT")
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _UNSAFE_BOUNDARY.sub("_", normalized.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug or not _SAFE_SLUG.fullmatch(slug) or ".." in slug:
        raise ValidationError("client name must contain safe slug characters", "INVALID_ARGUMENT")
    return slug
