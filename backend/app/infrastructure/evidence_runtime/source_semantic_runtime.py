"""Runtime wiring for snapshot-scoped source semantic overlays.

This module owns only source-feature collection, descriptor projection, and
installation of an already verified classification snapshot.  It never owns
geometry and it never invents semantic candidates.
"""

from __future__ import annotations

import json
from typing import Any

from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureDescriptor,
    SourceSemanticCandidate,
    SourceSemanticClassificationSnapshot,
)
from app.workflow.validation.l1_fact_catalog import is_canonical_l1_fact_id
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
    str(EntityTypes.WaterBody): (("water_bodies", "water_current", "water"), ("Polygon", "MultiPolygon", "LineString", "MultiLineString")),
}

MAX_KG_SEMANTIC_CANDIDATES = 128

_NON_SEMANTIC_PROPERTY_TOKENS = (
    "geometry", "coordinate", "longitude", "latitude", "经度", "纬度",
    "wkt", "shape", "source_feature_id", "source_uri", "source_path",
    "feature_bsm", "source_bsm", "snapshot_digest", "source_dataset",
    "source_dataset_ref", "source_feature_ref", "source_feature_digest",
    "source_content_digest", "source_label", "source_feature_index",
    "content_digest", "feature_index", "validity_status", "diagnostics",
    "objectid", "fid", "layer_type",
    "source_layer", "source_crs", "crs", "geometry_field", "bsm",
)


_RUNTIME_STORE: Any | None = None


def _runtime_store() -> Any:
    global _RUNTIME_STORE
    if _RUNTIME_STORE is None:
        from app.infrastructure.evidence_runtime.source_semantic_store import SourceSemanticStore

        _RUNTIME_STORE = SourceSemanticStore(max_entries=16)
    return _RUNTIME_STORE


def _property_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        if isinstance(value, (list, tuple, set)) and all(
            isinstance(item, (str, int, float, bool)) for item in value
        ):
            return ", ".join(str(item) for item in value)
        return ""
    return str(value).strip()


def _semantic_property_key(key: Any) -> str:
    return str(key or "").strip()


def _is_semantic_property(key: str) -> bool:
    folded = key.casefold().replace("-", "_").replace(" ", "_")
    return bool(folded) and not folded.startswith("_") and not any(
        token in folded for token in _NON_SEMANTIC_PROPERTY_TOKENS
    )


def _feature_property_sources(feature: object) -> list[tuple[str, dict[str, Any]]]:
    sources: list[tuple[str, dict[str, Any]]] = []
    for prefix, value in (
        ("gis", getattr(feature, "properties", None)),
        ("raw", getattr(feature, "_raw", None)),
        ("data", getattr(feature, "raw_attributes", None)),
        ("normalized", getattr(feature, "normalized_claims", None)),
    ):
        if isinstance(value, dict):
            sources.append((prefix, value))
    dumper = getattr(feature, "model_dump", None)
    if callable(dumper):
        try:
            dumped = dumper(mode="python")
        except TypeError:
            dumped = dumper()
        if isinstance(dumped, dict):
            sources.append(("model", dumped))
    values = getattr(feature, "__dict__", None)
    if isinstance(values, dict):
        sources.append(("object", values))
    return sources


def _feature_source_id(feature: object) -> str:
    raw = getattr(feature, "_raw", None)
    properties = getattr(feature, "properties", None)
    for source in (raw, properties):
        if isinstance(source, dict) and str(source.get("source_feature_id") or "").strip():
            return str(source["source_feature_id"]).strip()
    for key in ("source_feature_ref", "source_feature_id"):
        value = str(getattr(feature, key, "") or "").strip()
        if value:
            return value
    return str(getattr(feature, "source_feature_id", "") or "").strip()


def _semantic_properties(feature: object) -> tuple[str, dict[str, str]]:
    properties: dict[str, str] = {}
    seen_field_names: set[str] = set()
    for prefix, source in _feature_property_sources(feature):
        for raw_key, raw_value in source.items():
            key = _semantic_property_key(raw_key)
            value = _property_text(raw_value)
            if not value or not _is_semantic_property(key):
                continue
            field_name = key.casefold().replace("-", "_").replace(" ", "_")
            if field_name in seen_field_names:
                continue
            seen_field_names.add(field_name)
            properties.setdefault(f"{prefix}.{key}", value)
    label = ""
    label_keys = {
        "text", "name", "label", "road_name", "facility_name", "water_name",
        "注记", "名称", "地质灾害点名称", "source_label",
    }
    for key, value in properties.items():
        field_name = key.rsplit(".", 1)[-1].casefold().replace("-", "_").replace(" ", "_")
        if field_name in label_keys:
            label = value
            break
    return label, properties


def collect_authoritative_source_features(context: Any) -> dict[str, list[object]]:
    """Collect source features with bounded identity.

    Compatibility layer groups are retained, then generic DATA features are
    added by geometry kind.  No configured layer name is required; arbitrary
    point/line/polygon resources therefore participate in semantic binding.
    """
    workspace = getattr(context, "workspace", None)
    point_layers = getattr(workspace, "points", None)
    line_layers = getattr(workspace, "lines", None)
    polygon_layers = getattr(workspace, "polygons", None)

    def collect(group: Any, layer_names: tuple[str, ...]) -> list[object]:
        get = getattr(group, "get", None)
        result: list[object] = []
        seen: set[str] = set()
        for layer_name in layer_names:
            values = get(layer_name) if callable(get) else []
            for feature in values or []:
                source_id = _feature_source_id(feature) or str(
                    getattr(feature, "bsm", "") or ""
                ).strip()
                identity = source_id or f"object:{id(feature)}"
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(feature)
        return result

    result = {
        "facility": collect(
            point_layers,
            ("annotations_current", "facilities_current"),
        ),
        "road": collect(line_layers, ("roads_current",)),
        "water": collect(polygon_layers, ("water_bodies", "water_current", "water")),
    }
    catalog = getattr(context, "data_resource_catalog", None)
    snapshot = getattr(catalog, "snapshot", None)
    if snapshot is not None:
        from app.data.admission import assert_current_world_catalog

        assert_current_world_catalog(snapshot)
    for feature in list(getattr(snapshot, "features", ()) or ()):
        kind = str(getattr(feature, "geometry_kind", "") or "").casefold()
        if kind in {"", "unknown"}:
            geometry = getattr(feature, "geometry", None) or {}
            geometry_type = str(
                geometry.get("type", "") if isinstance(geometry, dict) else ""
            ).casefold()
            kind = {
                "point": "point",
                "multipoint": "point",
                "linestring": "line",
                "multilinestring": "line",
                "polygon": "polygon",
                "multipolygon": "polygon",
            }.get(geometry_type, kind)
        if kind == "point":
            group_key = "facility"
        elif kind == "line":
            group_key = "road"
        elif kind == "polygon":
            # The descriptor bucket is only a transport shape. Semantic
            # classification still decides whether an area is water, parcel,
            # hazard, or another domain object.
            group_key = "water"
        else:
            continue
        source_id = _feature_source_id(feature)
        if not source_id:
            continue
        existing_ids = {_feature_source_id(item) for item in result[group_key]}
        if source_id not in existing_ids:
            result[group_key].append(feature)
    return result


def source_feature_descriptor(
    feature: object,
    group_key: str,
) -> SourceFeatureDescriptor | None:
    """Project one feature to semantic metadata without copying geometry."""
    raw = getattr(feature, "_raw", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    source_feature_id = _feature_source_id(feature)
    if not source_feature_id:
        feature_bsm = str(getattr(feature, "bsm", "") or "").strip()
        if feature_bsm:
            source_feature_id = f"bundle:{group_key}:{feature_bsm}"
    if not source_feature_id:
        return None
    label, semantic_properties = _semantic_properties(feature)
    geometry = getattr(feature, "geometry", {}) or {}
    geometry_kind = str(geometry.get("type") or "") if isinstance(geometry, dict) else ""
    if not geometry_kind:
        geometry_kind = {
            "point": "Point",
            "line": "LineString",
            "polygon": "Polygon",
            "multipatch": "MultiPolygon",
        }.get(str(getattr(feature, "geometry_kind", "") or "").casefold(), "")
    properties = semantic_properties
    descriptor_layer_key = str(getattr(feature, "layer_ref", "") or "").strip() or {
        "facility": "annotations_current",
        "road": "roads_current",
        "water": "water_bodies",
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


def _kg_entity_attributes(entity: Any) -> dict[str, str]:
    def value(name: str, default: Any = "") -> Any:
        if isinstance(entity, dict):
            return entity.get(name, default)
        return getattr(entity, name, default)

    values: dict[str, str] = {}
    for key in ("canonical_name", "entity_type"):
        item = str(value(key) or "").strip()
        if item:
            values[key] = item
    concept_types = [
        str(item).strip()
        for item in (value("concept_types", None) or [])
        if str(item).strip()
    ]
    if concept_types and "entity_type" not in values:
        values["entity_type"] = concept_types[0]
    aliases = [str(item).strip() for item in (value("aliases", None) or []) if str(item).strip()]
    if aliases:
        values["aliases"] = ", ".join(dict.fromkeys(aliases))
    properties = value("properties", None) or ()
    if isinstance(properties, dict):
        properties = properties.items()
    for key, item in properties:
        key_text = str(key).strip()
        value_text = str(item).strip()
        if key_text and value_text and _is_semantic_property(key_text):
            values.setdefault(key_text, value_text)
    return values


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
    mode = str(getattr(context, "world_model_mode", "") or "").strip().casefold()
    if mode == "shadow":
        kg = getattr(context, "world_model_shadow", None)
    else:
        kg = getattr(getattr(context, "ports", None), "world_model", None)
        kg = kg or getattr(context, "kg", None)
    kg = getattr(kg, "read_port", kg)
    finder = getattr(kg, "find_entities", None)
    if not callable(finder):
        return []

    candidates: list[SourceSemanticCandidate] = []
    seen: set[tuple[str, str]] = set()
    query_cache: dict[tuple[str, str], list[Any]] = {}
    for fact in l1_facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        if not is_canonical_l1_fact_id(fact_id):
            continue
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
        def entity_ref(entity: Any) -> str:
            raw = (
                entity.get("entity_ref", "")
                if isinstance(entity, dict)
                else getattr(entity, "entity_ref", "")
            )
            return str(raw or "").strip()

        entity_refs = sorted({
            entity_ref(entity)
            for entity in entities
            if entity_ref(entity)
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
                supporting_attributes={
                    key: value
                    for entity in entities[:8]
                    for key, value in _kg_entity_attributes(entity).items()
                },
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
    from app.infrastructure.evidence_runtime.evidence_graph import EvidenceGraph

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

    from app.infrastructure.evidence_runtime.source_semantic_classifier import (
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
        l1_mentions=list(getattr(context, "location_mentions", []) or []),
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
