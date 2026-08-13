"""Stable caller identities for idempotent seed ingestion."""

from hashlib import sha256
from uuid import UUID

_IDENTITY_PREFIX = "nocturne-seed-v1\0"


def seed_batch_uid(source_name: str, markdown: str) -> UUID:
    """Mint the same RFC 9562 UUIDv8 for the same named Markdown document."""

    source_digest = sha256(markdown.encode("utf-8")).hexdigest()
    digest = sha256(f"{_IDENTITY_PREFIX}{source_name}\0{source_digest}".encode()).digest()
    value = bytearray(digest[:16])
    value[6] = (value[6] & 0x0F) | 0x80
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))
