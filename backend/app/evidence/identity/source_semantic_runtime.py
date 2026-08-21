"""Runtime wiring for snapshot-scoped source semantic overlays.

This module owns only source-feature collection, descriptor projection, and
installation of an already verified classification snapshot.  It never owns
geometry and it never invents semantic candidates.
"""

from __future__ import annotations

from typing import Any

from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureDescriptor,
    SourceSemanticCandidate,
    SourceSemanticClassificationSnapshot,
)
from app.infrastructure.kg.ontology import EntityTypes


_L1_ROLE_TO_KG_TYPE = {
    "facility": str(EntityTypes.Facility),
    "设施": str(EntityTypes.Facility),
    "service": str(EntityTypes.Facility),
    "服务点": str(EntityTypes.Facility),
    "road": str(EntityTypes.Road),
    "道路": str(EntityTypes.Road),
    "axis": str(EntityTypes.Road),
    "轴线": str(EntityTypes.Road),
    "water": str(EntityTypes.WaterBody),
    "水体": str(EntityTypes.WaterBody),
}

_KG_TYPE_TO_SOURCE_SHAPE = {
    str(EntityTypes.Facility): (("annotations_current", "facilities_current"), ("Point", "MultiPoint")),
    str(EntityTypes.Road): (("roads_current", "current_road"), ("LineString", "MultiLineString")),
    str(EntityTypes.WaterBody): (("water_current", "water"), ("Polygon", "MultiPolygon", "LineString", "MultiLineString")),
}

MAX_KG_SEMANTIC_CANDIDATES = 128


_RUNTIME_STORE: Any | None = None


def _runtime_store() -> Any:
    global _RUNTIME_STORE
    if _RUNTIME_STORE is None:
        from app.evidence.identity.source_semantic_store import SourceSemanticStore

        _RUNTIME_STORE = SourceSemanticStore(max_entries=16)
    return _RUNTIME_STORE


def collect_authoritative_source_features(context: Any) -> dict[str, list[object]]:
    """Collect current facility/road source features with bounded identity."""
    workspace = getattr(context, "workspace", None)
    point_layers = getattr(workspace, "points", None)
    line_layers = getattr(workspace, "lines", None)

    def collect(group: Any, layer_names: tuple[str, ...]) -> list[object]:
        get = getattr(group, "get", None)
        result: list[object] = []
        seen: set[str] = set()
        for layer_name in layer_names:
            values = get(layer_name) if callable(get) else []
            for feature in values or []:
                raw = getattr(feature, "_raw", {}) or {}
                source_id = str(
                    raw.get("source_feature_id") if isinstance(raw, dict) else ""
                ).strip()
                identity = source_id or f"object:{id(feature)}"
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(feature)
        return result

    return {
        "facility": collect(
            point_layers,
            ("annotations_current", "facilities_current"),
        ),
        "road": collect(line_layers, ("roads_current",)),
    }


def source_feature_descriptor(
    feature: object,
    group_key: str,
) -> SourceFeatureDescriptor | None:
    """Project one feature to semantic metadata without copying geometry."""
    raw = getattr(feature, "_raw", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    source_feature_id = str(raw.get("source_feature_id") or "").strip()
    if not source_feature_id:
        return None
    label = ""
    for attr in ("text", "name", "label", "road_name", "facility_name", "注记"):
        value = getattr(feature, attr, "")
        if not value and isinstance(getattr(feature, "properties", None), dict):
            value = feature.properties.get(attr, "")
        if str(value or "").strip():
            label = str(value).strip()
            break
    geometry = getattr(feature, "geometry", {}) or {}
    geometry_kind = str(geometry.get("type") or "") if isinstance(geometry, dict) else ""
    properties = {
        key: str(raw[key])
        for key in ("source_label", "source_dataset", "category", "分类")
        if str(raw.get(key) or "").strip()
    }
    descriptor_layer_key = {
        "facility": "annotations_current",
        "road": "roads_current",
    }.get(group_key, group_key)
    return SourceFeatureDescriptor(
        source_feature_id=source_feature_id,
        raw_label=label,
        layer_key=descriptor_layer_key,
        geometry_kind=geometry_kind,
        minimal_properties=properties,
    )


def source_descriptors(
    source_features: dict[str, list[object]],
) -> tuple[list[SourceFeatureDescriptor], int]:
    """Return durable descriptors and count features lacking source identity."""
    descriptors: list[SourceFeatureDescriptor] = []
    missing_identity = 0
    for group_key, features in source_features.items():
        for feature in features:
            descriptor = source_feature_descriptor(feature, group_key)
            if descriptor is None:
                missing_identity += 1
                continue
            descriptors.append(descriptor)
    return descriptors, missing_identity


def kg_semantic_candidates(
    context: Any,
    l1_facts: list[Any],
) -> list[SourceSemanticCandidate]:
    """Project a bounded KG vocabulary for the current L1 semantic facts.

    The KG contributes only a canonical concept that is already linked to the
    same current snapshot and the same L1 phrase/type.  It does not contribute
    geometry, arbitrary names, or a fallback candidate.  Querying the KG by
    each L1 phrase keeps the vocabulary small even when the bundle contains
    hundreds of roads or parcels.
    """
    kg = getattr(context, "kg", None)
    finder = getattr(kg, "find_entities", None)
    if not callable(finder):
        return []

    candidates: list[SourceSemanticCandidate] = []
    seen: set[tuple[str, str]] = set()
    query_cache: dict[tuple[str, str], list[Any]] = {}
    for fact in l1_facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        attributes = getattr(fact, "attributes", None) or {}
        if not isinstance(attributes, dict):
            attributes = {}
        phrase = ""
        for key in ("canonical_name", "normalized_name", "mention", "entity_name"):
            phrase = str(attributes.get(key, "") or "").strip()
            if phrase:
                break
        if not phrase:
            phrase = str(getattr(fact, "subject_scope", "") or "").strip()
        role = str(getattr(fact, "semantic_type", "") or "").strip().casefold()
        kg_type = _L1_ROLE_TO_KG_TYPE.get(role, "")
        shape = _KG_TYPE_TO_SOURCE_SHAPE.get(kg_type)
        if not fact_id or not phrase or not kg_type or shape is None:
            continue
        layers, geometry_kinds = shape
        query_key = (phrase, str(kg_type))
        if query_key not in query_cache:
            try:
                query_cache[query_key] = list(
                    finder(
                        name=phrase,
                        entity_type=kg_type,
                        limit=8,
                    )
                    or []
                )
            except Exception:
                query_cache[query_key] = []
        entities = query_cache[query_key]
        entity_refs = sorted({
            str(getattr(entity, "entity_ref", "") or "").strip()
            for entity in entities
            if str(getattr(entity, "entity_ref", "") or "").strip()
        })
        if not entity_refs:
            continue
        # Multiple current entities with the same canonical name prove only
        # that the KG knows the concept/type; selecting one entity here would
        # silently turn a class-level match into an exact spatial identity.
        concept_ref = entity_refs[0] if len(entity_refs) == 1 else str(kg_type)
        key = (fact_id, concept_ref)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            SourceSemanticCandidate(
                candidate_ref=f"kg:{fact_id}:{concept_ref}",
                display_phrase=phrase,
                origin="kg_snapshot",
                supporting_fact_refs=[fact_id],
                optional_kg_concept_ref=concept_ref,
                compatible_layers=list(layers),
                compatible_geometry_kinds=list(geometry_kinds),
            )
        )
        if len(candidates) >= MAX_KG_SEMANTIC_CANDIDATES:
            return candidates
    return candidates


def install_source_semantic_snapshot(
    context: Any,
    snapshot: SourceSemanticClassificationSnapshot,
) -> None:
    """Install a verified snapshot and rebuild the single spatial boundary."""
    current_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    if (
        current_digest
        and snapshot.source_snapshot_digest
        and current_digest != snapshot.source_snapshot_digest
    ):
        raise ValueError(
            "source semantic snapshot digest mismatch: "
            f"artifact={snapshot.source_snapshot_digest} current={current_digest}"
        )
    context.source_semantic_decisions = {
        decision.source_feature_id: decision
        for decision in snapshot.decisions
    }
    context.source_semantic_fingerprint = snapshot.fingerprint
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    context.evidence_graph = EvidenceGraph.build(context)
    context.evidence_graph_key = (
        f"{getattr(context, 'evidence_graph_key', '')}:"
        f"source-semantic:{snapshot.fingerprint}"
    )


def _as_enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def classify_source_semantics(
    context: Any,
    *,
    enabled: Any = None,
    source_features: dict[str, list[object]] | None = None,
    classifier: Any = None,
) -> tuple[SourceSemanticClassificationSnapshot | None, dict[str, Any], list[dict[str, str]]]:
    """Classify one current context through the explicit MiniMax boundary.

    Workflow stages may persist the returned snapshot; read-only queries use
    the same function without persistence.  The only in-process cache is a
    bounded LRU owned here, so repeated queries cannot retain unbounded model
    outputs or create a second semantic registry.
    """
    features = source_features or collect_authoritative_source_features(context)
    descriptors, missing_identity = source_descriptors(features)
    diagnostics: list[dict[str, str]] = []
    if missing_identity:
        diagnostics.append({
            "code": "SOURCE_FEATURE_ID_REQUIRED",
            "message": (
                f"{missing_identity} source feature(s) have no durable source_feature_id; "
                "semantic binding remains unresolved"
            ),
        })
    if not descriptors:
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_INPUT_EMPTY",
            "message": "no durable current source features were available for semantic classification",
        })
        context.source_semantic_diagnostics = list(diagnostics)
        return None, {}, diagnostics
    if enabled is None:
        from app.core.settings import SOURCE_SEMANTIC_LLM_ENABLED

        enabled = SOURCE_SEMANTIC_LLM_ENABLED
    if not _as_enabled(enabled):
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_LLM_DISABLED",
            "message": (
                "MiniMax source-semantic classification is disabled; raw labels are not "
                "promoted and no compatibility mapping is used"
            ),
        })
        context.source_semantic_diagnostics = list(diagnostics)
        return None, {}, diagnostics

    from app.evidence.identity.flash_source_semantic_classifier import (
        SourceSemanticClassifier,
        accepted_semantic_decisions,
        create_minimax_source_semantic_classifier,
    )

    provider_error = ""
    if classifier is None:
        try:
            classifier = create_minimax_source_semantic_classifier()
        except Exception as exc:
            provider_error = f"{type(exc).__name__}: {exc}"
            classifier = SourceSemanticClassifier(
                llm=None,
                model_id="minimax-source-semantic",
                effective_temperature=0.01,
            )
            diagnostics.append({
                "code": "SOURCE_SEMANTIC_PROVIDER_UNAVAILABLE",
                "message": f"MiniMax classifier construction failed: {provider_error}",
            })
    data_snapshot = getattr(context, "data_snapshot", None)
    snapshot_ref = str(
        getattr(data_snapshot, "snapshot_id", "")
        or getattr(context, "l1_snapshot_ref", "")
        or f"context:{getattr(context, 'session_id', '')}:v{getattr(context, 'version', '')}"
    )
    snapshot_digest = str(
        getattr(data_snapshot, "digest", "")
        or getattr(context, "content_hash", "")
        or snapshot_ref
    )
    snapshot = await classifier.classify(
        source_snapshot_ref=snapshot_ref,
        source_snapshot_digest=snapshot_digest,
        source_items=descriptors,
        l1_facts=list(getattr(context, "l1_fact_records", []) or []),
        kg_candidates=kg_semantic_candidates(
            context,
            list(getattr(context, "l1_fact_records", []) or []),
        ),
        store=_runtime_store(),
    )
    if provider_error:
        snapshot = snapshot.model_copy(update={
            "verifier_findings": [
                *snapshot.verifier_findings,
                f"provider construction failed:{provider_error}",
            ],
        })
    try:
        install_source_semantic_snapshot(context, snapshot)
    except Exception as exc:
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_GRAPH_REBUILD_FAILED",
            "message": f"accepted overlay was not installed into EvidenceGraph: {exc}",
        })
    accepted = accepted_semantic_decisions(snapshot)
    nonaccepted = [
        decision.source_feature_id
        for decision in snapshot.decisions
        if decision.status != "accepted"
    ]
    if nonaccepted:
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_DECISION_NOT_ACCEPTED",
            "message": (
                f"{len(nonaccepted)} source feature(s) remain ambiguous/unresolved and "
                "cannot be used for exact binding"
            ),
        })
    context.source_semantic_diagnostics = list(diagnostics)
    return snapshot, accepted, diagnostics


__all__ = [
    "collect_authoritative_source_features",
    "classify_source_semantics",
    "kg_semantic_candidates",
    "MAX_KG_SEMANTIC_CANDIDATES",
    "install_source_semantic_snapshot",
    "source_descriptors",
    "source_feature_descriptor",
]
