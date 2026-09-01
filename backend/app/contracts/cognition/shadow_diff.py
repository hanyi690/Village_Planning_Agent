"""Closed, auditable comparison contract for migration shadow runs."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from app.contracts.base import StrictContractModel


ShadowDimension = Literal[
    "entity_candidates",
    "selected_entity",
    "selected_representation",
    "source_lineage",
    "ambiguity",
    "constraint_result",
]


class ShadowDiffItem(StrictContractModel):
    """One fixed comparison dimension; refs are opaque and never geometry."""

    dimension: ShadowDimension
    status: Literal["match", "v1_only", "v2_only", "conflict", "failure"]
    v1_refs: tuple[str, ...] = ()
    v2_refs: tuple[str, ...] = ()
    details: str = ""


class ShadowStageObservation(StrictContractModel):
    """Bounded per-stage comparison; payloads stay in their own artifacts."""

    stage: str
    dimension_key: str = ""
    status: Literal["match", "v1_only", "v2_only", "conflict", "failure"]
    v1_refs: tuple[str, ...] = ()
    v2_refs: tuple[str, ...] = ()
    details: str = ""


class CognitionShadowDiff(StrictContractModel):
    """Deterministic V1/V2 comparison persisted by a shadow run."""

    session_id: str
    v1_snapshot_ref: str = ""
    v1_snapshot_digest: str = ""
    v2_snapshot_ref: str = ""
    v2_snapshot_digest: str = ""
    items: tuple[ShadowDiffItem, ...] = ()
    stage_observations: tuple[ShadowStageObservation, ...] = ()
    status: Literal["match", "different", "failed"] = "match"

    def model_post_init(self, __context: object) -> None:
        payload = {
            "session_id": self.session_id,
            "v1_snapshot_ref": self.v1_snapshot_ref,
            "v1_snapshot_digest": self.v1_snapshot_digest,
            "v2_snapshot_ref": self.v2_snapshot_ref,
            "v2_snapshot_digest": self.v2_snapshot_digest,
            "items": [item.model_dump(mode="json") for item in self.items],
            "stage_observations": [item.model_dump(mode="json") for item in self.stage_observations],
            "status": self.status,
        }
        digest = "sha256:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "digest", digest)


__all__ = ["CognitionShadowDiff", "ShadowDiffItem", "ShadowStageObservation", "ShadowDimension"]
