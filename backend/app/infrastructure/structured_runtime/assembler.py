"""Deterministic artifact assembly metadata for structured stage results."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class ArtifactAssembler:
    """Build stable semantic metadata before CAS persistence."""

    @staticmethod
    def digest(value: Any) -> str:
        payload = json.dumps(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def assemble(
        self,
        *,
        stage: str,
        artifact_key: str,
        value: Any,
        parent_digests: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "artifact_key": artifact_key,
            "semantic_digest": self.digest(value),
            "parent_digests": dict(parent_digests or {}),
            "value": value,
        }


__all__ = ["ArtifactAssembler"]
