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
from app.contracts.spatial.spatial_reference_contracts import normalize_spatial_role
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.infrastructure.artifacts.runtime import load_artifact, store_artifact
from app.evidence.identity.observation_store import ObservationStore


class BindingStore:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir

    @staticmethod
    def from_context(context: Any) -> list[GroundedEntityBinding]:
        facts = list(
            getattr(context, "location_mentions", None)
            or getattr(context, "location_facts", None)
            or []
        )
        if not facts:
            facts = list(getattr(context, "l1_fact_records", None) or [])
        observations = ObservationStore.from_location_mentions(facts)
        obs_by_name: dict[str, list[Any]] = {}
        for observation in observations:
            obs_by_name.setdefault(
                str(observation.normalized_name or observation.mention).strip(),
                [],
            ).append(observation)
        graph = getattr(context, "evidence_graph", None)
        bindings: list[GroundedEntityBinding] = []

        def scope_names(fact: Any) -> list[str]:
            raw = getattr(fact, "scopes", None)
            if raw in (None, "", []):
                raw = getattr(fact, "scope_mentions", None)
            if raw in (None, "", []):
                raw = [
                    {"name": value, "role": "natural_village"}
                    for value in (getattr(fact, "village_scopes", None) or [])
                ]
                raw.extend(
                    {"name": value, "role": "place"}
                    for value in (getattr(fact, "place_scopes", None) or [])
                )
            result_names: list[str] = []
            for scope in raw or []:
                if isinstance(scope, dict):
                    role = str(scope.get("role", "") or "").casefold()
                    value = str(
                        scope.get("normalized_name")
                        or scope.get("name")
                        or ""
                    ).strip()
                else:
                    role = str(getattr(scope, "role", "") or "").casefold()
                    value = str(
                        getattr(scope, "normalized_name", "")
                        or getattr(scope, "name", "")
                        or ""
                    ).strip()
                if value and normalize_spatial_role(role) not in {"unknown", "target"}:
                    result_names.append(value)
            return list(dict.fromkeys(result_names))

        def scope_refs(fact: Any) -> list[str]:
            refs: list[str] = []
            for scope in getattr(fact, "scopes", None) or getattr(fact, "scope_mentions", None) or []:
                values = (
                    scope.get("source_refs", []) + scope.get("source_segment_ids", [])
                    if isinstance(scope, dict)
                    else [
                        *list(getattr(scope, "source_refs", []) or []),
                        *list(getattr(scope, "source_segment_ids", []) or []),
                    ]
                )
                refs.extend(str(value).strip() for value in values if str(value).strip())
            return list(dict.fromkeys(refs))

        def candidate_has_feature(candidate: Any) -> bool:
            return bool(
                str(getattr(candidate, "feature_bsm", "") or "").strip()
                or str(getattr(candidate, "source_feature_id", "") or "").strip()
                or str(getattr(candidate, "geometry_ref", "") or "").strip()
            )

        for fact in facts:
            name = str(
                getattr(fact, "normalized_name", "")
                or getattr(fact, "mention", "")
                or getattr(fact, "subject_scope", "")
                or ""
            ).strip()
            if not name:
                continue
            observation = (obs_by_name.get(name) or [None])[0]
            observation_ref = observation.observation_id if observation else f"obs:{name}"
            role = normalize_spatial_role(
                getattr(fact, "role", "")
                or getattr(fact, "semantic_type", "")
                or "unknown"
            )
            typed_scope_names = scope_names(fact)
            typed_scope_refs = scope_refs(fact)
            result = None
            search_scope = None
            if graph is not None:
                try:
                    search_scope_builder = getattr(graph, "search_scope_for_mentions", None)
                    if callable(search_scope_builder) and typed_scope_names:
                        search_scope = search_scope_builder([fact])
                except Exception:
                    search_scope = None
                try:
                    hints = " ".join(
                        value
                        for value in (
                            *typed_scope_names,
                            getattr(fact, "spatial_hint", ""),
                            getattr(fact, "source_span", ""),
                        )
                        if str(value or "").strip()
                    )
                    scoped_resolver = getattr(graph, "query_facility_bsms", None)
                    if (
                        typed_scope_names
                        and role in {"facility", "landmark"}
                        and callable(scoped_resolver)
                    ):
                        result = scoped_resolver(
                            "、".join(typed_scope_names),
                            name,
                            role=role,
                            hints=hints,
                        )
                    else:
                        result = graph.resolve_mention(name, role=role, hints=hints)
                except Exception:
                    result = None

            if search_scope is None and result is not None:
                search_scope = getattr(result, "search_scope", None)
            candidates = list(getattr(result, "candidates", []) or []) if result else []
            feature_candidates = [candidate for candidate in candidates if candidate_has_feature(candidate)]
            source_candidate = None
            selected_ref = str(getattr(result, "selected_entity_ref", "") or "") if result else ""
            if selected_ref:
                source_candidate = next(
                    (candidate for candidate in candidates if str(getattr(candidate, "entity_ref", "") or "") == selected_ref),
                    None,
                )
            if source_candidate is None and len(feature_candidates) == 1:
                source_candidate = feature_candidates[0]

            result_status = str(getattr(result, "status", "") or "unresolved") if result else "unresolved"
            if typed_scope_names and search_scope is not None and not feature_candidates:
                status = "inferred_scope"
                selected = None
                entity_ref = ""
                source_bsms: list[str] = []
                geometry_ref = None
                confidence = float(getattr(search_scope, "confidence", 0.0) or 0.0)
            elif source_candidate is not None and (
                result_status == "resolved"
                or bool(getattr(fact, "source_feature_ids", None))
            ):
                status = "exact_feature" if len(feature_candidates) <= 1 else "feature_set"
                selected = source_candidate if status == "exact_feature" else None
                entity_ref = str(getattr(selected, "entity_ref", "") or "") if selected else ""
                source_bsms = [
                    str(value).strip()
                    for candidate in (feature_candidates if status == "feature_set" else [source_candidate])
                    for value in (getattr(candidate, "source_bsms", None) or [])
                    if str(value).strip()
                ]
                geometry_ref = getattr(selected, "geometry_ref", None) if selected else None
                confidence = max(
                    (float(getattr(candidate, "score", 0.0) or 0.0) for candidate in feature_candidates),
                    default=0.0,
                )
            elif search_scope is not None and not feature_candidates:
                status = "inferred_scope"
                selected = None
                entity_ref = ""
                source_bsms = []
                geometry_ref = None
                confidence = 0.0
            elif result_status == "ambiguous":
                status = "ambiguous"
                selected = None
                entity_ref = ""
                source_bsms = []
                geometry_ref = None
                confidence = 0.0
            elif candidates:
                status = "name_only"
                selected = None
                entity_ref = ""
                source_bsms = []
                geometry_ref = None
                confidence = max(
                    (float(getattr(candidate, "score", 0.0) or 0.0) for candidate in candidates),
                    default=0.0,
                )
            else:
                status = "unresolved"
                selected = None
                entity_ref = ""
                source_bsms = []
                geometry_ref = None
                confidence = 0.0

            candidate_refs = list(dict.fromkeys(
                str(getattr(candidate, "entity_ref", "") or "")
                for candidate in candidates
                if str(getattr(candidate, "entity_ref", "") or "").strip()
            ))
            evidence_refs = list(dict.fromkeys(
                str(ref)
                for candidate in candidates
                for ref in (getattr(candidate, "evidence_refs", None) or [])
                if str(ref).strip()
            ))
            relation_refs = list(dict.fromkeys(
                str(ref)
                for candidate in candidates
                for ref in (getattr(candidate, "relation_refs", None) or [])
                if str(ref).strip()
            ))
            binding_source_feature_ids = list(dict.fromkeys(
                str(getattr(candidate, "source_feature_id", "") or "").strip()
                for candidate in feature_candidates
                if str(getattr(candidate, "source_feature_id", "") or "").strip()
            ))
            explicit_source_ids = [
                str(value).strip()
                for value in (getattr(fact, "source_feature_ids", None) or [])
                if str(value).strip()
            ]
            binding_source_feature_ids = list(dict.fromkeys([
                *binding_source_feature_ids,
                *explicit_source_ids,
            ]))
            query_trace = list(getattr(result, "query_trace", []) or []) if result else []
            uncertainty_reason = str(
                getattr(result, "unresolved_reason", "") or ""
            ) if result else "no_evidence_graph"
            if status == "inferred_scope" and search_scope is not None:
                uncertainty_reason = str(
                    getattr(search_scope, "reason", "") or "scope_only_resolution"
                )
            if typed_scope_refs:
                query_trace.append({"step": "typed_scope", "scope_refs": typed_scope_refs})

            binding_seed = {
                "observation_ref": observation_ref,
                "entity_ref": entity_ref,
                "candidate_refs": candidate_refs,
                "status": status,
                "search_scope": search_scope.model_dump(mode="json") if search_scope is not None else None,
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
                    geometry_granularity=(
                        "settlement"
                        if status == "inferred_scope"
                        else infer_geometry_granularity(
                            geometry_ref,
                            entity_ref=entity_ref,
                            source_bsms=list(dict.fromkeys(source_bsms)),
                        )
                    ),
                    geometry_ref=geometry_ref,
                    source_feature_ids=binding_source_feature_ids,
                    source_bsms=list(dict.fromkeys(source_bsms)) if status != "inferred_scope" else [],
                    candidate_refs=candidate_refs,
                    evidence_refs=evidence_refs,
                    relation_evidence_refs=relation_refs,
                    confidence=confidence,
                    uncertainty_reason=uncertainty_reason,
                    query_trace=query_trace,
                    search_scope=search_scope,
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
