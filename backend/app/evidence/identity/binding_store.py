"""Persistence and deterministic construction of L1 entity bindings."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.contracts.evidence.identity_contracts import (
    GroundedEntityBinding,
    GroundedEntityBindingSnapshot,
    infer_geometry_granularity,
)
from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
from app.infrastructure.artifacts.runtime import load_artifact, store_artifact
from app.evidence.identity.observation_store import ObservationStore


class BindingStore:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir

    @staticmethod
    def from_context(context: Any, anchors: list[Any] | None = None) -> list[GroundedEntityBinding]:
        def source_feature_ids(refs: list[str]) -> list[str]:
            return list(dict.fromkeys(
                str(ref).strip()
                for ref in refs
                if str(ref).strip().startswith(
                    "http://village-planning.org/source-feature/"
                )
            ))

        facts = list(getattr(context, "location_facts", []) or [])
        observations = ObservationStore.from_location_facts(facts)
        obs_by_name = {}
        for observation in observations:
            obs_by_name.setdefault(
                str(observation.normalized_name or observation.mention).strip(),
                observation,
            )
        anchors_by_name = {}
        for anchor in list(anchors or []):
            name = str(
                getattr(anchor, "normalized_name", "")
                or getattr(anchor, "mention", "")
                or ""
            ).strip()
            if name:
                anchors_by_name.setdefault(name, anchor)

        index = getattr(context, "evidence_index", None)
        bindings: list[GroundedEntityBinding] = []
        for fact in facts:
            name = str(
                getattr(fact, "normalized_name", "")
                or getattr(fact, "mention", "")
                or ""
            ).strip()
            if not name:
                continue
            observation = obs_by_name.get(name)
            observation_ref = observation.observation_id if observation else f"obs:{name}"
            anchor = anchors_by_name.get(name)
            result = None
            if anchor is None and index is not None:
                try:
                    result = index.resolve_mention(
                        name,
                        role=str(getattr(fact, "role", "unknown") or "unknown"),
                        hints=str(
                            getattr(fact, "spatial_hint", "")
                            or getattr(fact, "source_span", "")
                            or ""
                        ),
                    )
                except Exception:
                    result = None

            if anchor is not None:
                candidate_refs = [str(getattr(anchor, "entity_ref", "") or "")]
                candidate_refs = [ref for ref in candidate_refs if ref]
                entity_ref = candidate_refs[0] if candidate_refs else ""
                source_bsms = list(getattr(anchor, "source_bsms", []) or [])
                geometry_ref = getattr(anchor, "geometry_ref", None)
                evidence_refs = list(getattr(anchor, "topology_evidence", []) or [])
                relation_refs = list(getattr(anchor, "relation_refs", []) or [])
                status = str(getattr(anchor, "status", "unresolved") or "unresolved")
                confidence = float(getattr(anchor, "confidence", 0.0) or 0.0)
                query_trace = list(getattr(anchor, "query_trace", []) or [])
                binding_source_feature_ids = source_feature_ids(candidate_refs)
                uncertainty_reason = (
                    "best_effort_anchor" if getattr(anchor, "best_effort", False) else ""
                )
            else:
                candidates = list(getattr(result, "candidates", []) or []) if result else []
                selected = candidates[0] if result and getattr(result, "status", "") == "resolved" and candidates else None
                candidate_refs = [str(getattr(c, "entity_ref", "") or "") for c in candidates]
                candidate_refs = [ref for ref in candidate_refs if ref]
                entity_ref = str(getattr(result, "selected_entity_ref", "") or "") if result else ""
                source_bsms = list(getattr(selected, "source_bsms", []) or []) if selected else []
                geometry_ref = getattr(selected, "geometry_ref", None) if selected else None
                evidence_refs = [
                    ref for candidate in candidates
                    for ref in list(getattr(candidate, "evidence_refs", []) or [])
                ]
                relation_refs = [
                    ref for candidate in candidates
                    for ref in list(getattr(candidate, "relation_refs", []) or [])
                ]
                status = str(getattr(result, "status", "unresolved") or "unresolved") if result else "unresolved"
                confidence = float(getattr(selected, "score", 0.0) or 0.0) if selected else 0.0
                query_trace = list(getattr(result, "query_trace", []) or []) if result else []
                uncertainty_reason = str(getattr(result, "unresolved_reason", "") or "") if result else "no_evidence_index"
                binding_source_feature_ids = source_feature_ids(
                    [entity_ref] if status == "resolved" else []
                )

            binding_seed = {
                "observation_ref": observation_ref,
                "entity_ref": entity_ref,
                "candidate_refs": candidate_refs,
                "status": status,
            }
            binding_id = "binding:" + hashlib.sha256(
                json.dumps(binding_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:20]
            bindings.append(
                GroundedEntityBinding(
                    binding_id=binding_id,
                    mention_ref=observation_ref,
                    canonical_entity_ref=entity_ref,
                    observation_refs=[observation_ref],
                    status=status,
                    geometry_granularity=infer_geometry_granularity(
                        geometry_ref,
                        entity_ref=entity_ref,
                        source_bsms=source_bsms,
                    ),
                    geometry_ref=geometry_ref,
                    source_feature_ids=binding_source_feature_ids,
                    source_bsms=list(dict.fromkeys(source_bsms)),
                    candidate_refs=list(dict.fromkeys(candidate_refs)),
                    evidence_refs=list(dict.fromkeys(evidence_refs)),
                    relation_evidence_refs=list(dict.fromkeys(relation_refs)),
                    confidence=confidence,
                    uncertainty_reason=uncertainty_reason,
                    query_trace=query_trace,
                )
            )
        return bindings

    def put_snapshot(
        self,
        state: dict[str, Any],
        bindings: list[GroundedEntityBinding],
        *,
        observation_snapshot_ref: str = "",
        parent_digest: str = "",
    ) -> ArtifactDescriptor:
        payload = GroundedEntityBindingSnapshot(
            bindings=bindings,
            observation_snapshot_ref=observation_snapshot_ref,
            parent_digest=parent_digest,
        )
        return ArtifactDescriptor.model_validate(
            store_artifact(
                state,
                "l1_bindings",
                "l1_identity",
                "GroundedEntityBindingSnapshot",
                payload.model_dump(mode="json"),
                base_dir=self.base_dir,
            )
        )

    def load_snapshot(self, state: dict[str, Any]) -> list[GroundedEntityBinding]:
        payload = load_artifact(state, "l1_bindings", base_dir=self.base_dir)
        snapshot = payload if isinstance(payload, GroundedEntityBindingSnapshot) else GroundedEntityBindingSnapshot.model_validate(payload)
        return list(snapshot.bindings)


__all__ = ["BindingStore"]
