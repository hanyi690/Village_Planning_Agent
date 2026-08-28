"""Bounded semantic projections of Evidence requirements for stage reasoning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.contracts.evidence.requirement_contracts import EvidenceRequirement


def build_requirement_projection(
    requirements: Iterable[EvidenceRequirement],
    *,
    max_items: int = 16,
) -> dict[str, Any]:
    rows = [
        {
            "requirement_id": item.requirement_id,
            "statement": item.statement,
            "kind": item.kind,
            "scope": list(item.scope),
            "evidence_role": item.evidence_role,
            "allowed_inference": item.allowed_inference,
        }
        for item in requirements
    ][:max(1, max_items)]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "rows": rows,
        "projection_digest": "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


__all__ = ["build_requirement_projection"]
