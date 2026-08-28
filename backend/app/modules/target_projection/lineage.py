"""Projection lineage helpers."""

from app.infrastructure.artifacts.fingerprint import semantic_checksum


def projection_lineage_digest(value) -> str:
    return semantic_checksum(value)


__all__ = ["projection_lineage_digest"]
