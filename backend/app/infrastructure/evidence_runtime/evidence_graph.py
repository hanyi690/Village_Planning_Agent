"""Join L1 semantics, KG identity, bundle references, and KG topology.

This module is the only place-resolution boundary used by GROUND, SELECT and
LLM evidence tools. The session bundle is the retrieval projection that
provides spatial identity and source refs; ``PlaceEvidenceIndex`` is only an
implementation detail of this graph. Callers receive typed resolution
results or bounded evidence packets and never need to know how candidates
were indexed. The graph does not own geometry and does not copy report text.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from copy import copy, deepcopy
from typing import Any

from app.contracts.evidence.evidence_packet_contracts import (
    EvidencePacket,
    SpatialRelationEvidence,
)
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
)
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)
from app.contracts.ports.place_resolution_contracts import PlaceResolutionCandidate
from app.contracts.ground.spatial_reference_contracts import (
    GeometryRef,
    SearchScopeRef,
    normalize_spatial_role,
)
from app.infrastructure.evidence_runtime.index.evidence_scorer import WEIGHTS
from app.infrastructure.kg.ontology import EntityTypes
from app.infrastructure.kg.spatial_store import SpatialKGEntity


_MAX_CANDIDATES = 12
_MAX_CANDIDATE_PAGE = 64
_MAX_RECALL_CANDIDATES = 4096
_MAX_RELATIONS = 24
_RESOLUTION_CACHE_MAXSIZE = 128
_QUERY_DELIMITERS = set(",，、;；:：|/\\()（）[]【】<>《》。.!！？?")
_SCOPE_TARGET_ROLES = frozenset({
    "scope",
    "village",
    "natural_village",
    "administrative_village",
    "settlement",
    "place",
    "area",
    "行政村",
    "自然村",
    "村庄",
    "聚落",
    "地点",
    "区域",
})
_DYNAMIC_SCOPE_SOURCES = frozenset({
    "amap",
    "amap_map",
    "bundle_annotation",
    "external_anchors",
    "tencent",
    "tencent_map",
    "tianditu",
    "uploaded_annotation",
})


def _is_bsm(value: object) -> bool:
    text = str(value or "")
    return len(text) == 20 and all(char in "0123456789" for char in text)


def _source_semantic_trace(context: Any) -> dict[str, Any]:
    return {
        "step": "source_semantic_overlay",
        "fingerprint": str(
            getattr(context, "source_semantic_fingerprint", "") or ""
        ),
        "decision_count": len(
            getattr(context, "source_semantic_decisions", {}) or {}
        ),
        "diagnostics": list(
            getattr(context, "source_semantic_diagnostics", []) or []
        )[-8:],
    }


def _fold_query(*values: object) -> str:
    return "".join(
        char
        for char in "".join(str(value or "") for value in values).casefold()
        if not char.isspace() and char not in _QUERY_DELIMITERS
    )


_GENERIC_SCOPE_NAMES = frozenset({"村", "村庄", "行政村", "自然村"})


def _is_specific_scope_name(value: object) -> bool:
    """Reject gazetteer type labels that are not a spatial scope name."""
    folded = _fold_query(value)
    return bool(folded) and len(folded) >= 2 and folded not in _GENERIC_SCOPE_NAMES


def _context_location_mentions(context: Any) -> list[Any]:
    """Read the canonical L1 mention collection with old-context fallback."""

    mentions = getattr(context, "location_mentions", None)
    if mentions:
        return list(mentions)
    return list(getattr(context, "location_facts", None) or [])


def _context_l1_items(context: Any) -> list[Any]:
    collections = [
        _context_location_mentions(context),
        list(getattr(context, "l1_fact_records", None) or []),
    ]
    result: list[Any] = []
    seen_objects: set[int] = set()
    seen_fact_ids: set[str] = set()
    for collection in collections:
        for item in collection:
            object_id = id(item)
            fact_id = str(getattr(item, "fact_id", "") or "").strip()
            if object_id in seen_objects or (fact_id and fact_id in seen_fact_ids):
                continue
            seen_objects.add(object_id)
            if fact_id:
                seen_fact_ids.add(fact_id)
            result.append(item)
    return result


def _scope_mentions_for_fact(fact: Any) -> list[Any]:
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
    return [] if isinstance(raw, str) else list(raw or [])


def _scope_value(scope: Any, field: str, default: str = "") -> str:
    if isinstance(scope, dict):
        return str(scope.get(field, default) or "").strip()
    return str(getattr(scope, field, default) or "").strip()


def _fact_scope_names(fact: Any) -> list[str]:
    return list(dict.fromkeys(
        _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
        for scope in _scope_mentions_for_fact(fact)
        if _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
    ))


def _is_explicit_scope_role(value: Any) -> bool:
    role = normalize_spatial_role(value).casefold()
    return bool(role and role not in {"unknown", "target"})


def _is_scope_target_role(value: Any) -> bool:
    role = normalize_spatial_role(value)
    return role in _SCOPE_TARGET_ROLES


def _scope_type_for_role(value: Any) -> str:
    role = normalize_spatial_role(value)
    if role in {
        "village",
        "natural_village",
        "administrative_village",
        "settlement",
        "行政村",
        "自然村",
        "村庄",
        "聚落",
    }:
        return "village_scope"
    return "unknown"


def _typed_l1_feature_context(
    context: Any,
    mention: str,
) -> tuple[str, list[str]]:
    """Return an L1-declared target role and its explicitly typed scopes."""
    mention_key = _fold_query(mention)
    if not mention_key:
        return "", []
    for fact in _context_l1_items(context):
        names = [
            str(getattr(fact, "normalized_name", "") or "").strip(),
            str(getattr(fact, "mention", "") or "").strip(),
        ]
        if mention_key not in {
            _fold_query(name)
            for name in names
            if _fold_query(name)
        }:
            continue
        role = normalize_spatial_role(
            getattr(fact, "role", "")
            or getattr(fact, "observed_type", "")
            or getattr(fact, "semantic_type", "")
        )
        scope_names = [
            _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
            for scope in _scope_mentions_for_fact(fact)
            if _is_explicit_scope_role(_scope_value(scope, "role"))
            and (
                _scope_value(scope, "normalized_name")
                or _scope_value(scope, "name")
            )
        ]
        if role != "unknown" or scope_names:
            return role, list(dict.fromkeys(scope_names))
    return "", []


def _is_dynamic_scope_entry(entry: Any) -> bool:
    source = str(getattr(entry, "source", "") or "").strip().casefold()
    entity_uri = str(getattr(entry, "entity_uri", "") or "").strip().casefold()
    return (
        source in _DYNAMIC_SCOPE_SOURCES
        or entity_uri.startswith("pln:external_")
        or "external_natural_village" in entity_uri
    )


def _context_parcels(context: Any) -> list[Any]:
    try:
        parcels = getattr(context, "current_parcels", None)
        if callable(parcels):
            return list(parcels() or [])
    except Exception:
        pass
    workspace = getattr(context, "workspace", None)
    try:
        parcels = getattr(workspace, "current_parcels", None)
        if callable(parcels):
            return list(parcels() or [])
    except Exception:
        pass
    polygons = getattr(workspace, "polygons", None)
    if polygons is not None and hasattr(polygons, "get"):
        return list(polygons.get("landuse_current") or [])
    return []


def _parcel_source_feature_id(parcel: Any) -> str:
    raw = getattr(parcel, "_raw", {}) or {}
    if isinstance(raw, dict):
        return str(raw.get("source_feature_id") or "").strip()
    return str(getattr(parcel, "source_feature_id", "") or "").strip()


def _parcel_semantic_labels(parcel: Any) -> list[str]:
    values: list[str] = []
    for attr in (
        "name", "dlmc", "dlbm", "zone_type", "planning_zone", "primary_zone",
        "primary_code", "ghytmc", "ghytbm", "ghflbm",
    ):
        value = getattr(parcel, attr, "")
        if value:
            values.append(str(value))
    dlbm = str(getattr(parcel, "dlbm", "") or "").strip()
    if dlbm:
        try:
            from app.data.catalog.advisory_crosswalks import (
                dlbm_to_planning_zone,
                get_zone_type_for_dlbm,
            )

            values.extend([get_zone_type_for_dlbm(dlbm), dlbm_to_planning_zone(dlbm)])
        except Exception:
            pass
        try:
            from app.data.encodings.code_sets import DLBM_TO_DLMC

            values.append(str(DLBM_TO_DLMC.get(dlbm, "") or ""))
        except Exception:
            pass
    return list(dict.fromkeys(_fold_query(value) for value in values if _fold_query(value)))


def _query_scope_bsms(
    context: Any,
    folded_query: str,
    graph: "EvidenceGraph" | None = None,
) -> set[str]:
    scope_names = _query_scope_names(context, folded_query)
    graph = graph or getattr(context, "evidence_graph", None)
    index = getattr(graph, "_index", None)
    indexed_scope_bsms = getattr(index, "scope_bsms_for_names", None)
    if callable(indexed_scope_bsms):
        try:
            return set(indexed_scope_bsms(scope_names) or set())
        except Exception:
            pass
    gazetteer = getattr(context, "gazetteer", None)
    if gazetteer is None:
        return set()
    matched: list[tuple[int, set[str]]] = []
    for entry in getattr(gazetteer, "entries", []) or []:
        if not _is_dynamic_scope_entry(entry):
            continue
        name = _fold_query(getattr(entry, "name", ""))
        if (
            not _is_specific_scope_name(name)
            or name not in folded_query
        ):
            continue
        bsms = {
            str(value).strip()
            for value in (getattr(entry, "bsms", None) or [])
            if str(value).strip()
        }
        if bsms:
            matched.append((len(name), bsms))
    if not matched:
        return set()
    return max(matched, key=lambda item: item[0])[1]


def _query_scope_names(context: Any, folded_query: str) -> list[str]:
    """Return explicit village scope names present in a query."""
    names: list[str] = []
    gazetteer = getattr(context, "gazetteer", None)
    for entry in getattr(gazetteer, "entries", []) or []:
        if not _is_dynamic_scope_entry(entry):
            continue
        values = [
            getattr(entry, "name", ""),
            *(getattr(entry, "aliases", None) or []),
        ]
        for value in values:
            text = str(value or "").strip()
            folded = _fold_query(text)
            entry_role = str(getattr(entry, "role", "") or "").casefold()
            if (
                _is_specific_scope_name(text)
                and folded in folded_query
                and (
                    not entry_role
                    or _is_scope_target_role(entry_role)
                )
            ):
                names.append(text)
    for fact in _context_l1_items(context):
        for scope in _scope_mentions_for_fact(fact):
            value = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
            folded = _fold_query(value)
            role = _scope_value(scope, "role").casefold()
            if (
                folded
                and folded in folded_query
                and _is_explicit_scope_role(role)
            ):
                names.append(value)
        role = str(getattr(fact, "role", "") or "").casefold()
        value = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        folded = _fold_query(value)
        if folded and folded in folded_query and _is_scope_target_role(role):
            names.append(value)
    context_village = str(getattr(context, "village_name", "") or "").strip()
    # The request is already scoped to one administrative village by the
    # session context.  Use it as the default only when the query did not name
    # a more specific report-backed settlement/object scope.
    if not names and context_village:
        names.append(context_village)
    return list(dict.fromkeys(names))


def _iter_spatial_spec(spec: Any) -> list[Any]:
    if spec is None:
        return []
    children = list(getattr(spec, "children", None) or [])
    return [spec, *(item for child in children for item in _iter_spatial_spec(child))]


def _spatial_spec_terms(spec: Any) -> list[str]:
    terms: list[str] = []
    for item in _iter_spatial_spec(spec):
        reference = getattr(item, "reference", None)
        filters = getattr(reference, "filter", None) or {}
        for key in ("label_contains", "rdf_type"):
            value = str(filters.get(key) or "").strip()
            if value:
                terms.append(value)
        for value in (getattr(item, "attr_filter", None) or {}).values():
            if isinstance(value, str) and value.strip():
                terms.append(value.strip())
        terms.extend(
            str(value).strip()
            for value in (getattr(item, "semantic_terms", None) or [])
            if str(value).strip()
        )
    return list(dict.fromkeys(terms))


def _query_direction(query: str, spatial_spec: Any = None) -> str:
    """Extract a directional area qualifier without treating line orientation as area."""
    folded = _fold_query(query)
    if not folded or any(token in folded for token in ("东西向", "南北向")):
        return ""
    for item in _iter_spatial_spec(spatial_spec):
        direction = str(getattr(item, "direction", "") or "").upper()
        if direction in {
            "N", "NE", "E", "SE", "S", "SW", "W", "NW"
        }:
            return {
                "N": "north",
                "NE": "northeast",
                "E": "east",
                "SE": "southeast",
                "S": "south",
                "SW": "southwest",
                "W": "west",
                "NW": "northwest",
            }[direction]
    patterns = (
        ("northeast", ("村东北", "东北侧", "东北部", "northeast", "north-east")),
        ("southeast", ("村东南", "东南侧", "东南部", "southeast", "south-east")),
        ("northwest", ("村西北", "西北侧", "西北部", "northwest", "north-west")),
        ("southwest", ("村西南", "西南侧", "西南部", "southwest", "south-west")),
        ("north", ("村北", "北侧", "北部", "北边", "north")),
        ("south", ("村南", "南侧", "南部", "南边", "south")),
        ("east", ("村东", "东侧", "东部", "东边", "east")),
        ("west", ("村西", "西侧", "西部", "西边", "west")),
    )
    for direction, terms in patterns:
        if any(_fold_query(term) in folded for term in terms):
            return direction
    return ""


def _scope_centroid(
    context: Any,
    scope_names: list[str],
    graph: "EvidenceGraph" | None = None,
) -> tuple[float, float] | None:
    """Estimate a directional center from current scoped parcel evidence."""

    graph = graph or getattr(context, "evidence_graph", None)
    index = getattr(graph, "_index", None)
    scope_bsms_for_names = getattr(index, "scope_bsms_for_names", None)
    if not callable(scope_bsms_for_names):
        return None
    try:
        scope_bsms = set(scope_bsms_for_names(scope_names) or set())
    except Exception:
        return None
    if not scope_bsms:
        return None
    geometries = []
    for parcel in _context_parcels(context):
        bsm = str(getattr(parcel, "bsm", "") or "").strip()
        if bsm not in scope_bsms:
            continue
        raw = getattr(parcel, "geometry", None)
        if raw is None:
            continue
        try:
            from shapely.geometry import shape

            geometry = shape(raw) if isinstance(raw, dict) else raw
            if geometry is not None and not geometry.is_empty:
                geometries.append(geometry)
        except Exception:
            continue
    if not geometries:
        return None
    try:
        from shapely.ops import unary_union

        centroid = unary_union(geometries).centroid
        return float(centroid.x), float(centroid.y)
    except Exception:
        return None


def _directional_parcel_bsms(
    context: Any,
    query: str,
    scope_names: list[str],
    graph: "EvidenceGraph",
    spatial_spec: Any = None,
) -> tuple[str, set[str]]:
    """Resolve a coarse directional qualifier to bundle parcel BSMs."""
    direction = _query_direction(query, spatial_spec)
    if not direction:
        return "", set()
    center = _scope_centroid(context, scope_names, graph=graph)
    if center is None:
        return direction, set()
    try:
        from app.spatial.grounding.grounding import resolve_directional_bbox

        bbox = resolve_directional_bbox(center, direction, radius_m=1500)
        if not bbox:
            return direction, set()
        return direction, set(graph.query_parcel_bsms_in_bbox(bbox))
    except Exception:
        return direction, set()


def _kg_scope_refs(context: Any, scope_names: list[str]) -> set[str]:
    """Resolve scope names to KG entity refs without scanning RDF triples."""
    kg = getattr(context, "kg", None)
    if kg is None or not hasattr(kg, "find_entities"):
        return set()
    refs: set[str] = set()
    for name in scope_names:
        try:
            entities = kg.find_entities(name=name, limit=12) or []
        except Exception:
            entities = []
        for entity in entities:
            entity_ref = str(getattr(entity, "entity_ref", "") or "").strip()
            entity_type = str(getattr(entity, "entity_type", "") or "").casefold()
            if not entity_ref:
                continue
            if "residentialcluster" in entity_ref.casefold() or "residential_cluster" in entity_ref.casefold():
                continue
            if "residentialcluster" in entity_type or "residential_cluster" in entity_type:
                continue
            refs.add(entity_ref)
    return refs


def _entry_matches_kg_scope(context: Any, entry: Any, scope_refs: set[str]) -> bool:
    """Check an indexed feature's direct KG topology against scope refs."""
    if not scope_refs:
        return False
    kg = getattr(context, "kg", None)
    if kg is None or not hasattr(kg, "find_relations"):
        return False
    entry_refs = {
        str(value).strip()
        for value in (getattr(entry, "entity_refs", None) or [])
        if str(value).strip()
    }
    for entity_ref in entry_refs:
        try:
            relations = [
                *list(kg.find_relations(subject_ref=entity_ref, limit=40) or []),
                *list(kg.find_relations(object_ref=entity_ref, limit=40) or []),
            ]
        except Exception:
            continue
        if any(
            str(getattr(relation, "subject_ref", "") or "") in scope_refs
            or str(getattr(relation, "object_ref", "") or "") in scope_refs
            for relation in relations
        ):
            return True
    return False


def _candidate_spatial_bsms(candidate: Any) -> set[str]:
    return {
        str(value).strip()
        for value in [
            *(getattr(candidate, "anchor_bsms", None) or []),
            *(getattr(candidate, "related_parcel_bsms", None) or []),
        ]
        if str(value).strip()
    }


_KG_REFERENCE_TYPES: dict[str, str] = {
    "Facility": str(EntityTypes.Facility),
    "Parcel": str(EntityTypes.Parcel),
    "Road": str(EntityTypes.Road),
    "WaterBody": str(EntityTypes.WaterBody),
    "Zone": str(EntityTypes.Zone),
}


def _predicate_local_name(predicate: Any) -> str:
    value = str(predicate or "")
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _spatial_topology_items(spec: Any) -> list[Any]:
    return [item for item in _iter_spatial_spec(spec) if getattr(item, "topo", None)]


def _reference_entity_refs(
    context: Any,
    graph: "EvidenceGraph",
    item: Any,
) -> set[str]:
    """Resolve a topology anchor through indexed KG identity only.

    ``label_contains`` is an LLM semantic hint, not an identity.  Exact
    indexed names/aliases are preferred; the private bundle index is used as
    a bounded bridge for substring-labelled anchors.  Neither path reads or
    manufactures geometry.
    """
    reference = getattr(item, "reference", None)
    if reference is None:
        return set()
    filters = getattr(reference, "filter", None) or {}
    kg = getattr(context, "kg", None)
    refs: set[str] = set()

    if kg is not None and callable(getattr(kg, "find_entities", None)):
        explicit_ids = filters.get("source_feature_ids") or filters.get("exact_feature_ids")
        if isinstance(explicit_ids, (list, tuple, set)):
            for value in explicit_ids:
                try:
                    refs.update(
                        str(getattr(entity, "entity_ref", "") or "").strip()
                        for entity in kg.find_entities(
                            source_feature_id=str(value).strip(), limit=12
                        )
                        if str(getattr(entity, "entity_ref", "") or "").strip()
                    )
                except Exception:
                    continue

        bsm = str(filters.get("bsm") or "").strip()
        if bsm:
            try:
                refs.update(
                    str(getattr(entity, "entity_ref", "") or "").strip()
                    for entity in kg.find_entities(feature_bsm=bsm, limit=12)
                    if str(getattr(entity, "entity_ref", "") or "").strip()
                )
            except Exception:
                pass

        label = str(filters.get("label_contains") or "").strip()
        if label:
            try:
                entities = kg.find_entities(name=label, limit=50) or []
            except Exception:
                entities = []
            refs.update(
                str(getattr(entity, "entity_ref", "") or "").strip()
                for entity in entities
                if str(getattr(entity, "entity_ref", "") or "").strip()
            )

        rdf_type = str(filters.get("rdf_type") or "").strip()
        entity_type = _KG_REFERENCE_TYPES.get(rdf_type, "")
        if entity_type:
            try:
                entities = kg.find_entities(entity_type=entity_type, limit=50) or []
            except Exception:
                entities = []
            if label:
                entities = [
                    entity
                    for entity in entities
                    if label.casefold() in str(
                        getattr(entity, "canonical_name", "") or ""
                    ).casefold()
                ]
            refs.update(
                str(getattr(entity, "entity_ref", "") or "").strip()
                for entity in entities
                if str(getattr(entity, "entity_ref", "") or "").strip()
            )

    # A source-backed index entry can retain an entity ref when a compact
    # PostGIS projection has no substring search operator in this request.
    label = str(filters.get("label_contains") or "").strip().casefold()
    if label:
        for entry in graph.iter_entries():
            names = [
                str(getattr(entry, "canonical_name", "") or ""),
                *(str(value) for value in (getattr(entry, "aliases", None) or [])),
            ]
            if not any(label in name.casefold() for name in names if name):
                continue
            refs.update(
                str(value).strip()
                for value in (getattr(entry, "entity_refs", None) or [])
                if str(value).strip()
            )
    return refs


def _topology_target_keys(
    context: Any,
    graph: "EvidenceGraph",
    item: Any,
) -> tuple[set[str], set[str]]:
    """Return KG relation targets as identity keys and a diagnostic set."""
    kg = getattr(context, "kg", None)
    if kg is None or not callable(getattr(kg, "find_relations", None)):
        return set(), set()
    anchor_refs = _reference_entity_refs(context, graph, item)
    if not anchor_refs:
        return set(), set()
    topo = str(getattr(item, "topo", "") or "")
    target_keys: set[str] = set()
    relation_ids: set[str] = set()
    for anchor_ref in anchor_refs:
        try:
            relations = [
                *list(kg.find_relations(subject_ref=anchor_ref, limit=_MAX_RELATIONS) or []),
                *list(kg.find_relations(object_ref=anchor_ref, limit=_MAX_RELATIONS) or []),
            ]
        except Exception:
            relations = []
        for relation in relations:
            if _predicate_local_name(getattr(relation, "predicate", "")) != topo:
                continue
            relation_ids.add(str(getattr(relation, "relation_id", "") or ""))
            subject_ref = str(getattr(relation, "subject_ref", "") or "").strip()
            object_ref = str(getattr(relation, "object_ref", "") or "").strip()
            other_ref = object_ref if subject_ref == anchor_ref else subject_ref
            if other_ref:
                target_keys.add(other_ref)
            try:
                entities = kg.find_entities(entity_ref=other_ref, limit=1) or []
            except Exception:
                entities = []
            if entities:
                entity = entities[0]
                for value in (
                    getattr(entity, "feature_bsm", None),
                    getattr(entity, "source_feature_id", None),
                ):
                    if str(value or "").strip():
                        target_keys.add(str(value).strip())

    return target_keys, relation_ids


def _filter_candidates_by_topology(
    candidates: list[Any],
    context: Any,
    graph: "EvidenceGraph",
    item: Any,
) -> tuple[list[Any], dict[str, Any]]:
    target_keys, relation_ids = _topology_target_keys(context, graph, item)
    topo = str(getattr(item, "topo", "") or "")
    if not target_keys:
        return [], {
            "topology": topo,
            "relation_count": len(relation_ids),
            "anchor_bound": bool(getattr(item, "reference", None)),
            "evidence_available": False,
        }
    matched: list[Any] = []
    for candidate in candidates:
        candidate_keys = {
            str(value).strip()
            for value in [
                getattr(candidate, "entity_ref", ""),
                getattr(candidate, "feature_bsm", ""),
                getattr(candidate, "source_bsm", ""),
                *(getattr(candidate, "source_bsms", None) or []),
                *(getattr(candidate, "related_parcel_bsms", None) or []),
            ]
            if str(value).strip()
        }
        if candidate_keys.intersection(target_keys):
            matched.append(candidate)
    return matched, {
        "topology": topo,
        "relation_count": len(relation_ids),
        "anchor_bound": True,
        "evidence_available": True,
    }


def _apply_topology_to_candidates(
    candidates: list[Any],
    context: Any,
    graph: "EvidenceGraph",
    spatial_spec: Any,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Apply composed topology semantics to an already generated candidate list."""
    topology_items = _spatial_topology_items(spatial_spec)
    if not topology_items or not candidates:
        return candidates, []
    groups: list[list[Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for item in topology_items:
        matched, diagnostic = _filter_candidates_by_topology(
            candidates,
            context,
            graph,
            item,
        )
        groups.append(matched)
        diagnostics.append(diagnostic)
    if str(getattr(spatial_spec, "op", "") or "").casefold() == "or":
        unique: dict[str, Any] = {}
        for group in groups:
            for candidate in group:
                key = str(
                    getattr(candidate, "feature_bsm", "")
                    or getattr(candidate, "source_bsm", "")
                    or getattr(candidate, "entity_ref", "")
                )
                unique.setdefault(key, candidate)
        return list(unique.values()), diagnostics
    available_groups = [
        group
        for group, diagnostic in zip(groups, diagnostics)
        if diagnostic.get("evidence_available")
    ]
    if not available_groups:
        return candidates, diagnostics
    return [
        candidate
        for candidate in candidates
        if all(candidate in group for group in available_groups)
    ], diagnostics


def _filter_result_by_spatial_spec(
    result: Any,
    context: Any,
    query: str,
    graph: "EvidenceGraph",
    spatial_spec: Any,
) -> Any:
    """Apply LLM-derived spatial qualifiers only to existing candidates."""
    if spatial_spec is None:
        return result
    semantic_query = " ".join([str(query or ""), *_spatial_spec_terms(spatial_spec)])
    candidates = list(getattr(result, "candidates", []) or [])
    trace = list(getattr(result, "query_trace", []) or [])
    topology_items = _spatial_topology_items(spatial_spec)
    topology_evidence_incomplete = False
    if topology_items and candidates:
        topology_candidates, topology_diagnostics = _apply_topology_to_candidates(
            candidates,
            context,
            graph,
            spatial_spec,
        )
        trace.append({
            "step": "kg_topology_qualifier",
            "items": topology_diagnostics,
            "candidate_count_before": len(candidates),
            "candidate_count_after": len(topology_candidates),
        })
        topology_evidence_incomplete = bool(
            str(getattr(spatial_spec, "op", "") or "").casefold() != "or"
            and any(
                not item.get("evidence_available")
                for item in topology_diagnostics
            )
        )
        if topology_candidates:
            candidates = topology_candidates
        elif any(item.get("evidence_available") for item in topology_diagnostics):
            candidates = []
            updates = {
                "candidates": [],
                "selected_entity_ref": None,
                "status": "unresolved",
                "unresolved_reason": "no candidates satisfy KG topology",
                "query_trace": trace[-16:],
                "evidence_refs": [],
            }
            return result.model_copy(update=updates) if hasattr(result, "model_copy") else result
    scope_names = _query_scope_names(context, _fold_query(semantic_query))
    direction, directional_bsms = _directional_parcel_bsms(
        context,
        semantic_query,
        scope_names,
        graph,
        spatial_spec,
    )
    if not direction or not directional_bsms:
        if trace != list(getattr(result, "query_trace", []) or []):
            updates = {"candidates": candidates, "query_trace": trace[-16:]}
            if topology_evidence_incomplete:
                updates.update({
                    "selected_entity_ref": None,
                    "status": "ambiguous" if candidates else "unresolved",
                    "unresolved_reason": "KG topology evidence unavailable",
                    "evidence_refs": [candidate.entity_ref for candidate in candidates],
                })
            elif len(candidates) == 1:
                updates.update({
                    "selected_entity_ref": candidates[0].entity_ref,
                    "status": "resolved",
                    "unresolved_reason": "",
                    "evidence_refs": [candidates[0].entity_ref],
                })
            elif candidates:
                updates.update({
                    "selected_entity_ref": None,
                    "status": "ambiguous",
                    "unresolved_reason": "multiple candidates satisfy spatial qualifiers",
                    "evidence_refs": [candidate.entity_ref for candidate in candidates],
                })
            return result.model_copy(update=updates) if hasattr(result, "model_copy") else result
        return result
    matched = [
        candidate
        for candidate in candidates
        if _candidate_spatial_bsms(candidate).intersection(directional_bsms)
    ]
    trace.append({
        "step": "llm_spatial_qualifier",
        "direction": direction,
        "directional_parcel_count": len(directional_bsms),
        "candidate_count_before": len(candidates),
        "candidate_count_after": len(matched),
    })
    if not matched:
        if candidates:
            return result.model_copy(update={
                "candidates": [],
                "selected_entity_ref": None,
                "status": "unresolved",
                "unresolved_reason": "no candidates satisfy directional scope",
                "evidence_refs": [],
                "query_trace": trace[-16:],
            }) if hasattr(result, "model_copy") else result
        return result.model_copy(update={"query_trace": trace[-16:]}) if hasattr(result, "model_copy") else result
    updates = {
        "candidates": matched,
        "selected_entity_ref": (
            matched[0].entity_ref
            if len(matched) == 1 and not topology_evidence_incomplete
            else None
        ),
        "status": (
            "resolved"
            if len(matched) == 1 and not topology_evidence_incomplete
            else "ambiguous"
        ),
        "unresolved_reason": (
            "KG topology evidence unavailable"
            if topology_evidence_incomplete
            else "" if len(matched) == 1
            else "multiple candidates in directional scope"
        ),
        "query_trace": trace[-16:],
        "evidence_refs": [candidate.entity_ref for candidate in matched],
    }
    return result.model_copy(update=updates) if hasattr(result, "model_copy") else result


class EvidenceGraph:
    """Session-scoped evidence graph facade.

    The private deterministic index performs name/candidate generation.  This
    facade is the authoritative join boundary: it applies the session scope,
    keeps L1 provenance on the result, and exposes KG relations as part of a
    bounded packet.  GROUND must depend on this class, never on the index.
    """

    def __init__(self, context: Any, *, index: Any | None = None) -> None:
        self.context = context
        if index is None:
            from app.infrastructure.evidence_runtime.index.place_evidence_index import PlaceEvidenceIndex

            index = PlaceEvidenceIndex.build(context)
        self._index = index
        # Only the production PlaceEvidenceIndex is deterministic for a given
        # versioned context.  Injected indexes are also used by grounding
        # tests and adapters that may intentionally yield different candidates
        # for repeated calls; caching those results would change semantics.
        self._resolution_cache_enabled = (
            type(index).__module__ == "app.infrastructure.evidence_runtime.index.place_evidence_index"
            and type(index).__name__ == "PlaceEvidenceIndex"
        )
        # Compact semantic parcel index: BSM/labels/source id only.  Geometry
        # stays in the bundle and is never duplicated here.
        self._parcel_semantic_index: dict[str, list[tuple[str, str, str]]] | None = None
        self._resolution_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

    @classmethod
    def build(cls, context: Any) -> "EvidenceGraph":
        return cls(context)

    def _resolution_cache_key(
        self,
        mention: str,
        role: str,
        hints: str,
    ) -> tuple[Any, ...]:
        context = self.context
        decisions = getattr(context, "source_semantic_decisions", {}) or {}
        decision_shape = tuple(sorted(
            (
                str(source_id),
                str(getattr(decision, "status", "") or ""),
                str(getattr(decision, "semantic_type", "") or ""),
            )
            for source_id, decision in decisions.items()
        ))
        return (
            str(mention or ""),
            str(role or "unknown").casefold(),
            str(hints or ""),
            str(getattr(getattr(context, "data_snapshot", None), "digest", "") or ""),
            str(getattr(context, "kg_version", 0) or 0),
            str(getattr(context, "l1_snapshot_ref", "") or ""),
            str(getattr(context, "source_semantic_fingerprint", "") or ""),
            decision_shape,
        )

    @staticmethod
    def _clone_resolution(value: Any) -> Any:
        if hasattr(value, "model_copy"):
            return value.model_copy(deep=True)
        return deepcopy(value)

    def _cached_resolution(self, key: tuple[Any, ...]) -> Any | None:
        value = self._resolution_cache.pop(key, None)
        if value is None:
            return None
        self._resolution_cache[key] = value
        return self._clone_resolution(value)

    def _cache_resolution(self, key: tuple[Any, ...], value: Any) -> Any:
        self._resolution_cache[key] = self._clone_resolution(value)
        self._resolution_cache.move_to_end(key)
        while len(self._resolution_cache) > _RESOLUTION_CACHE_MAXSIZE:
            self._resolution_cache.popitem(last=False)
        return self._clone_resolution(value)

    @property
    def semantic_scopes(self) -> list[Any]:
        return list(getattr(self._index, "semantic_scopes", []) or [])

    def iter_entries(self, role: str = "") -> list[Any]:
        entries = list(getattr(self._index, "entries", []) or [])
        if role:
            entries = [entry for entry in entries if getattr(entry, "role", "") == role]
        return entries

    def semantic_label_probes(
        self,
        mention: str,
        *,
        roles: set[str] | frozenset[str] | tuple[str, ...] = (),
        max_probes: int = _MAX_CANDIDATES,
    ) -> list[tuple[str, str]]:
        """Expose bounded partial-name recall without exposing the index.

        EvidenceGraph remains the only caller-facing retrieval boundary.  The
        private index supplies source-backed n-gram probes; the caller still
        resolves each probe through this graph so KG relations, L1 refs and
        Bundle feature identities are joined by the normal path.
        """
        resolver = getattr(self._index, "semantic_label_probes", None)
        if not callable(resolver):
            return []
        probes = resolver(
            mention,
            roles=roles,
            max_probes=max_probes,
        )
        return list(
            dict.fromkeys(
                (
                    str(probe).strip(),
                    str(role).strip(),
                )
                for probe, role in probes
                if str(probe).strip() and str(role).strip()
            )
        )[: max(1, int(max_probes or 1))]

    def expand_supporting_evidence(
        self,
        mention: str,
        *,
        role: str = "unknown",
        hints: str = "",
        scope_names: list[str] | tuple[str, ...] = (),
        source_feature_ids: list[str] | tuple[str, ...] = (),
        direct_result: Any | None = None,
        max_candidates: int = _MAX_CANDIDATES,
    ) -> dict[str, Any]:
        """Expand one work item through bounded, source-backed joins.

        Exact and scoped resolution is attempted first. Partial labels from
        other indexed source roles are then resolved one by one. Cross-role
        candidates can support only a coarse village/settlement scope; they
        never become the requested facility, road, or water feature.
        """
        query = str(mention or "").strip()
        expected_role = str(role or "unknown").strip().casefold() or "unknown"
        try:
            requested_limit = int(max_candidates or 1)
        except (TypeError, ValueError):
            requested_limit = _MAX_CANDIDATES
        limit = min(_MAX_CANDIDATES, max(1, requested_limit))
        explicit_scopes = list(dict.fromkeys(
            str(value).strip()
            for value in (scope_names or ())
            if str(value).strip()
        ))
        scope_truncated = len(explicit_scopes) > _MAX_CANDIDATES
        if not explicit_scopes and hints:
            folded_hints = _fold_query(hints)
            explicit_scopes.extend(
                _query_scope_names(self.context, folded_hints)
            )
            explicit_scopes = list(dict.fromkeys(explicit_scopes))
            scope_truncated = (
                scope_truncated or len(explicit_scopes) > _MAX_CANDIDATES
            )
        explicit_scopes = explicit_scopes[:_MAX_CANDIDATES]

        trace: list[dict[str, Any]] = [{
            "step": "supporting_evidence_start",
            "mention": query,
            "role": expected_role,
            "scope_names": explicit_scopes,
            "candidate_limit": limit,
            "scope_truncated": scope_truncated,
        }]

        def bounded_query_trace() -> list[dict[str, Any]]:
            if len(trace) <= 24:
                return list(trace)
            return [trace[0], *trace[-23:]]
        feature_id_filter = {
            str(value).strip()
            for value in (source_feature_ids or ())
            if str(value).strip()
        }

        def candidate_key(candidate: Any) -> tuple[str, ...]:
            return (
                str(getattr(candidate, "entity_ref", "") or ""),
                str(getattr(candidate, "feature_bsm", "") or ""),
                str(getattr(candidate, "source_feature_id", "") or ""),
                str(getattr(candidate, "geometry_ref", "") or ""),
            )

        def feature_id_matches(candidate: Any) -> bool:
            if not feature_id_filter:
                return True
            values = {
                str(getattr(candidate, "source_feature_id", "") or "").strip(),
                str(getattr(candidate, "entity_ref", "") or "").strip(),
                *(
                    str(value).strip()
                    for value in (getattr(candidate, "evidence_refs", None) or [])
                    if str(value).strip()
                ),
            }
            return bool(values.intersection(feature_id_filter))

        def has_source(candidate: Any) -> bool:
            return bool(
                str(getattr(candidate, "feature_bsm", "") or "").strip()
                or str(getattr(candidate, "source_feature_id", "") or "").strip()
                or str(getattr(candidate, "geometry_ref", "") or "").strip()
                or getattr(candidate, "source_bsms", None)
                or getattr(candidate, "related_parcel_bsms", None)
            )

        def add_candidates(
            target: dict[tuple[str, ...], Any],
            values: list[Any],
            *,
            source_step: str,
            probe: str = "",
            probe_role: str = "",
        ) -> None:
            accepted = 0
            for candidate in values[:limit]:
                if not feature_id_matches(candidate) or not has_source(candidate):
                    continue
                key = candidate_key(candidate)
                if not any(key):
                    continue
                if key not in target:
                    target[key] = candidate
                    accepted += 1
            trace.append({
                "step": source_step,
                "probe": probe,
                "source_role": probe_role,
                "candidate_count": len(values),
                "accepted_count": accepted,
                "candidate_refs": [
                    str(getattr(candidate, "entity_ref", "") or "")
                    for candidate in values[:limit]
                    if str(getattr(candidate, "entity_ref", "") or "").strip()
                ],
            })

        strict_candidates: dict[tuple[str, ...], Any] = {}
        strict_statuses: list[str] = []
        if expected_role in {"facility", "landmark"} and explicit_scopes:
            for scope in explicit_scopes:
                try:
                    scoped_result = self.query_facility_bsms(
                        scope,
                        query,
                        role=expected_role,
                        hints=hints,
                    )
                except Exception as exc:  # noqa: BLE001
                    trace.append({
                        "step": "strict_facility_scope_error",
                        "scope": scope,
                        "error": type(exc).__name__,
                    })
                    continue
                strict_statuses.append(
                    str(getattr(scoped_result, "status", "unresolved") or "unresolved")
                )
                add_candidates(
                    strict_candidates,
                    (
                        list(getattr(scoped_result, "candidates", []) or [])
                        if getattr(scoped_result, "status", "unresolved")
                        != "unresolved"
                        else []
                    ),
                    source_step="strict_facility_scope",
                    probe=query,
                    probe_role=expected_role,
                )
            if strict_candidates:
                candidates = list(strict_candidates.values())[
                    :limit
                ]
                trace.append({
                    "step": "supporting_evidence_complete",
                    "mode": "strict_scope",
                    "candidate_count": len(candidates),
                })
                return {
                    "candidates": candidates,
                    "inferred_scope_candidate": None,
                    "status": (
                        "resolved"
                        if len(candidates) == 1
                        and not any(status == "ambiguous" for status in strict_statuses)
                        else "ambiguous"
                    ),
                    "resolution_mode": "strict_scope",
                    "query_trace": bounded_query_trace(),
                }

        direct_candidates: dict[tuple[str, ...], Any] = {}
        direct_status = "unresolved"
        try:
            resolved_result = direct_result
            if resolved_result is None:
                resolved_result = self.resolve_mention(
                    query,
                    role=expected_role,
                    hints=hints,
                )
            direct_status = str(
                getattr(resolved_result, "status", "unresolved") or "unresolved"
            )
            add_candidates(
                direct_candidates,
                list(getattr(resolved_result, "candidates", []) or []),
                source_step="direct_source_resolution",
                probe=query,
                probe_role=expected_role,
            )
        except Exception as exc:  # noqa: BLE001
            trace.append({
                "step": "direct_source_resolution_error",
                "error": type(exc).__name__,
            })

        direct_values = list(direct_candidates.values())[
            :limit
        ]
        all_roles = tuple(dict.fromkeys((
            *_SCOPE_TARGET_ROLES,
            "facility", "landmark", "hazard", "road", "axis", "water",
            "zone", "parcel",
        )))
        role_probe_map = {
            "facility": ("facility", "landmark"),
            "landmark": ("landmark", "facility"),
            "road": ("road", "axis"),
            "axis": ("axis", "road"),
            "water": ("water",),
            "hazard": ("hazard",),
            "scope": all_roles,
            "village": all_roles,
            "natural_village": all_roles,
            "administrative_village": all_roles,
            "settlement": all_roles,
            "place": all_roles,
            "area": all_roles,
            "unknown": all_roles,
        }
        probe_roles = role_probe_map.get(expected_role, all_roles)
        supporting_candidates: dict[tuple[str, ...], Any] = {}
        probes = self.semantic_label_probes(
            query,
            roles=probe_roles,
            max_probes=limit,
        )
        probes = list(probes)[:limit]
        trace.append({
            "step": "semantic_label_probe_batch",
            "probe_count": len(probes),
            "roles": list(probe_roles),
            "probes": [
                {"label": label, "role": probe_role}
                for label, probe_role in probes
            ],
        })
        strict_probe_statuses: list[str] = []
        for probe, probe_role in probes:
            if expected_role in {"facility", "landmark"} and explicit_scopes:
                for scope in explicit_scopes:
                    try:
                        scoped_probe_result = self.query_facility_bsms(
                            scope,
                            probe,
                            role=probe_role,
                            hints=hints,
                        )
                    except Exception as exc:  # noqa: BLE001
                        trace.append({
                            "step": "strict_facility_probe_scope_error",
                            "scope": scope,
                            "probe": probe,
                            "error": type(exc).__name__,
                        })
                        continue
                    strict_probe_statuses.append(
                        str(
                            getattr(
                                scoped_probe_result,
                                "status",
                                "unresolved",
                            )
                            or "unresolved"
                        )
                    )
                    add_candidates(
                        supporting_candidates,
                        (
                            list(
                                getattr(scoped_probe_result, "candidates", [])
                                or []
                            )
                            if getattr(
                                scoped_probe_result,
                                "status",
                                "unresolved",
                            )
                            != "unresolved"
                            else []
                        ),
                        source_step="strict_facility_probe_scope",
                        probe=probe,
                        probe_role=probe_role,
                    )
                continue
            try:
                probe_result = self.resolve_mention(
                    probe,
                    role=probe_role,
                    hints=hints,
                )
            except Exception as exc:  # noqa: BLE001
                trace.append({
                    "step": "semantic_label_probe_error",
                    "probe": probe,
                    "source_role": probe_role,
                    "error": type(exc).__name__,
                })
                continue
            add_candidates(
                supporting_candidates,
                list(getattr(probe_result, "candidates", []) or []),
                source_step="semantic_label_probe_resolution",
                probe=probe,
                probe_role=probe_role,
            )

        if expected_role in {"facility", "landmark"} and explicit_scopes:
            scoped_values = list(supporting_candidates.values())[
                :limit
            ]
            if scoped_values:
                trace.append({
                    "step": "supporting_evidence_complete",
                    "mode": "strict_scope_probe",
                    "candidate_count": len(scoped_values),
                })
                search_scope = self.search_scope_for_names(
                    explicit_scopes,
                    reason="typed_l1_scope_retrieval",
                )
                return {
                    "candidates": scoped_values,
                    "inferred_scope_candidate": None,
                    "search_scope": search_scope,
                    "status": (
                        "resolved"
                        if len(scoped_values) == 1
                        and not any(
                            status == "ambiguous"
                            for status in strict_probe_statuses
                        )
                        else "ambiguous"
                    ),
                    "resolution_mode": "strict_scope_probe",
                    "query_trace": bounded_query_trace(),
                }
            trace.append({
                "step": "supporting_evidence_unresolved",
                "reason": "strict facility scope has no source-backed candidate",
            })
            recovery_candidates, recovery_trace = self.recover_scoped_candidates(
                query,
                role=expected_role,
                scope_names=explicit_scopes,
                hints=hints,
                source_feature_ids=source_feature_ids,
                max_candidates=limit,
            )
            trace.extend(recovery_trace)
            if recovery_candidates:
                trace.append({
                    "step": "scoped_candidate_recovery_ready",
                    "role": expected_role,
                    "candidate_count": len(recovery_candidates),
                    "selection": "llm_closed_set",
                })
            search_scope = self.search_scope_for_names(
                explicit_scopes,
                reason="typed_l1_scope_retrieval",
            )
            return {
                "candidates": [],
                "inferred_scope_candidate": None,
                "search_scope": search_scope,
                "status": "inferred_scope" if search_scope is not None else "unresolved",
                "scope_candidates": recovery_candidates,
                "query_trace": bounded_query_trace(),
            }

        if direct_values and not _is_scope_target_role(expected_role) and expected_role != "unknown":
            trace.append({
                "step": "supporting_evidence_complete",
                "mode": "direct_source",
                "candidate_count": len(direct_values),
            })
            return {
                "candidates": direct_values,
                "inferred_scope_candidate": None,
                "status": (
                    "resolved"
                    if direct_status == "resolved" and len(direct_values) == 1
                    else "ambiguous"
                    if direct_values
                    else "unresolved"
                ),
                "query_trace": bounded_query_trace(),
            }

        if _is_scope_target_role(expected_role):
            scope_names = explicit_scopes or _query_scope_names(
                self.context,
                _fold_query(query, hints),
            )
            search_scope = self.search_scope_for_names(
                scope_names,
                reason="typed_l1_scope_retrieval",
            )
            if search_scope is not None:
                trace.append({
                    "step": "search_scope_ready",
                    "scope_names": scope_names,
                    "scope_bsms": list(search_scope.scope_bsms),
                    "candidate_materialization": "forbidden",
                })
                return {
                    "candidates": [],
                    "inferred_scope_candidate": None,
                    "search_scope": search_scope,
                    "status": "inferred_scope",
                    "query_trace": bounded_query_trace(),
                }

        scope_candidates: list[Any] = []
        if explicit_scopes and not _is_scope_target_role(expected_role) and expected_role != "unknown":
            scope_candidates, recovery_trace = self.recover_scoped_candidates(
                query,
                role=expected_role,
                scope_names=explicit_scopes,
                hints=hints,
                source_feature_ids=source_feature_ids,
                max_candidates=limit,
            )
            trace.extend(recovery_trace)
            if scope_candidates:
                trace.append({
                    "step": "scoped_candidate_recovery_ready",
                    "role": expected_role,
                    "candidate_count": len(scope_candidates),
                    "selection": "llm_closed_set",
                })
        trace.append({
            "step": "supporting_evidence_unresolved",
            "reason": "no source-backed candidate or related parcel set",
        })
        search_scope = self.search_scope_for_names(
            explicit_scopes,
            reason="typed_l1_scope_retrieval",
        ) if explicit_scopes else None
        return {
            "candidates": direct_values,
            "inferred_scope_candidate": None,
            "search_scope": search_scope,
            "status": (
                "inferred_scope"
                if search_scope is not None and not direct_values
                else "unresolved" if not direct_values else "ambiguous"
            ),
            "scope_candidates": scope_candidates,
            "query_trace": bounded_query_trace(),
        }

    def recover_scoped_candidates(
        self,
        mention: str,
        *,
        role: str = "unknown",
        scope_names: list[str] | tuple[str, ...] = (),
        hints: str = "",
        source_feature_ids: list[str] | tuple[str, ...] = (),
        max_candidates: int = _MAX_CANDIDATES,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Find a bounded typed candidate pool inside known scopes.

        This is a recovery query, not an exact resolution.  It lets the
        grounding LLM reason over existing Bundle/GIS features after another
        work item or the village mapper has established a scope.  A candidate
        must still carry scope topology evidence; a project-wide first match
        is never promoted into the pool.
        """
        query = str(mention or "").strip()
        expected_role = str(role or "unknown").strip().casefold() or "unknown"
        try:
            limit = min(_MAX_CANDIDATES, max(1, int(max_candidates or 1)))
        except (TypeError, ValueError):
            limit = _MAX_CANDIDATES
        scopes = list(dict.fromkeys(
            str(value).strip()
            for value in (scope_names or ())
            if str(value).strip()
        ))[:_MAX_CANDIDATES]
        collection_by_role = {
            "facility": "facilities",
            "landmark": "facilities",
            "hazard": "hazards",
            "road": "roads",
            "axis": "roads",
            "water": "waters",
            "parcel": "parcels",
            "zone": "zones",
        }
        collection = collection_by_role.get(expected_role)
        if not query or not scopes or not collection:
            return [], []
        allowed_roles = {
            "facility": {"facility", "landmark", "project"},
            "landmark": {"facility", "landmark"},
            "hazard": {"hazard"},
            "road": {"road", "axis"},
            "axis": {"road", "axis"},
            "water": {"water"},
            "parcel": {"parcel"},
            "zone": {"zone", "parcel"},
        }.get(expected_role, {expected_role})
        source_id_filter = {
            str(value).strip()
            for value in (source_feature_ids or ())
            if str(value).strip()
        }
        collected: dict[tuple[str, ...], Any] = {}
        trace: list[dict[str, Any]] = []
        for scope in scopes:
            scope_bsms = _query_scope_bsms(self.context, _fold_query(scope), graph=self)
            scope_refs = _kg_scope_refs(self.context, [scope])
            if not scope_bsms and not scope_refs:
                trace.append({
                    "step": "scoped_candidate_recovery",
                    "scope": scope,
                    "role": expected_role,
                    "status": "scope_unresolved",
                    "candidate_count": 0,
                })
                continue
            scoped_query = " ".join(value for value in (scope, query, hints) if value)
            try:
                values = self.query_scope_candidates(
                    scoped_query,
                    entity_scope=[collection],
                    max_candidates=limit,
                )
            except Exception as exc:  # noqa: BLE001
                trace.append({
                    "step": "scoped_candidate_recovery_error",
                    "scope": scope,
                    "role": expected_role,
                    "error": type(exc).__name__,
                })
                continue
            accepted: list[str] = []
            for candidate in values[:limit]:
                candidate_role = str(
                    getattr(candidate, "role", "") or ""
                ).strip().casefold()
                if candidate_role not in allowed_roles:
                    continue
                candidate_source_ids = {
                    str(getattr(candidate, "source_feature_id", "") or "").strip(),
                    str(getattr(candidate, "entity_ref", "") or "").strip(),
                    *(
                        str(value).strip()
                        for value in (getattr(candidate, "evidence_refs", None) or [])
                        if str(value).strip()
                    ),
                }
                if source_id_filter and not candidate_source_ids.intersection(
                    source_id_filter
                ):
                    continue
                candidate_scope_bsms = {
                    str(value).strip()
                    for value in [
                        *(getattr(candidate, "source_bsms", None) or []),
                        *(getattr(candidate, "related_parcel_bsms", None) or []),
                    ]
                    if str(value).strip()
                }
                evidence = getattr(candidate, "evidence", None) or {}
                scope_match = bool(
                    float(evidence.get("scope_topology", 0.0) or 0.0) > 0.0
                    or candidate_scope_bsms.intersection(scope_bsms)
                    or (
                        scope_refs
                        and str(getattr(candidate, "entity_ref", "") or "")
                        in scope_refs
                    )
                )
                if not scope_match:
                    continue
                key = (
                    str(getattr(candidate, "entity_ref", "") or ""),
                    str(getattr(candidate, "feature_bsm", "") or ""),
                    str(getattr(candidate, "source_feature_id", "") or ""),
                    str(getattr(candidate, "geometry_ref", "") or ""),
                )
                if not any(key):
                    continue
                collected.setdefault(key, candidate)
                accepted.append(str(getattr(candidate, "entity_ref", "") or ""))
            trace.append({
                "step": "scoped_candidate_recovery",
                "scope": scope,
                "role": expected_role,
                "source_collection": collection,
                "scope_bsm_count": len(scope_bsms),
                "scope_entity_count": len(scope_refs),
                "candidate_count": len(values),
                "accepted_count": len(accepted),
                "candidate_refs": accepted[:limit],
            })
            if len(collected) >= limit:
                break
        return list(collected.values())[:limit], trace

    def query_parcel_bsms_in_bbox(
        self,
        bbox: tuple[float, float, float, float],
    ) -> list[str]:
        """Return bundle parcel identities intersecting a query bbox.

        EvidenceGraph remains the public retrieval boundary.  The private
        index owns only the bounded spatial lookup; geometry is still read
        from the authoritative bundle by GROUND and later execution stages.
        """
        query = getattr(self._index, "query_parcel_bsms_in_bbox", None)
        if not callable(query):
            return []
        return list(
            dict.fromkeys(
                str(value) for value in query(bbox) if str(value).strip()
            )
        )

    def search_scope_for_names(
        self,
        scope_names: list[str] | tuple[str, ...],
        *,
        provenance_refs: list[str] | tuple[str, ...] = (),
        reason: str = "typed_l1_scope",
    ) -> SearchScopeRef | None:
        """Build a non-materializable search scope from explicit place names."""

        names = list(dict.fromkeys(
            str(value).strip() for value in (scope_names or ()) if str(value).strip()
        ))
        if not names:
            return None
        scope_bsms: set[str] = set()
        indexed_scope_bsms = getattr(self._index, "scope_bsms_for_names", None)
        if callable(indexed_scope_bsms):
            try:
                scope_bsms.update(indexed_scope_bsms(names) or set())
            except Exception:
                pass
        scope_refs = _kg_scope_refs(self.context, names)
        if not scope_bsms and not scope_refs:
            return None
        source_refs = list(dict.fromkeys(
            str(value).strip()
            for value in (provenance_refs or ())
            if str(value).strip()
        ))
        missing_requirements: list[str] = []
        if not scope_bsms:
            missing_requirements.append("bundle_scope_bsms")
        if not source_refs and not str(getattr(self.context, "l1_snapshot_ref", "") or ""):
            missing_requirements.append("l1_scope_provenance")
        scope_type = "unknown"
        requested_keys = {_fold_query(value) for value in names}
        for fact in _context_l1_items(self.context):
            for scope in _scope_mentions_for_fact(fact):
                scope_name = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
                if _fold_query(scope_name) not in requested_keys:
                    continue
                inferred_type = _scope_type_for_role(_scope_value(scope, "role"))
                if inferred_type != "unknown":
                    scope_type = inferred_type
                    break
            if scope_type != "unknown":
                break
        return SearchScopeRef(
            scope_bsms=sorted(scope_bsms),
            scope_type=scope_type,
            source="evidence_graph:l1_scope",
            reason=reason,
            provenance_refs=source_refs,
            missing_requirements=missing_requirements,
            source_snapshot_ref=str(
                getattr(self.context, "l1_snapshot_ref", "") or ""
            ),
            bundle_snapshot_digest=str(
                getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                or ""
            ),
            diagnostics={
                "scope_names": names,
                "kg_scope_refs": sorted(scope_refs),
                "candidate_materialization": "forbidden",
            },
        )

    def search_scope_for_mentions(self, mentions: Any) -> SearchScopeRef | None:
        """Project typed L1 scope objects into one bounded search scope."""

        names: list[str] = []
        refs: list[str] = []
        for mention in mentions or []:
            for scope in _scope_mentions_for_fact(mention):
                role = _scope_value(scope, "role").casefold()
                if not _is_explicit_scope_role(role):
                    continue
                name = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
                if name:
                    names.append(name)
                if isinstance(scope, dict):
                    refs.extend(str(value).strip() for value in (scope.get("source_refs") or []) if str(value).strip())
                    refs.extend(str(value).strip() for value in (scope.get("source_segment_ids") or []) if str(value).strip())
                else:
                    refs.extend(str(value).strip() for value in getattr(scope, "source_refs", []) if str(value).strip())
                    refs.extend(str(value).strip() for value in getattr(scope, "source_segment_ids", []) if str(value).strip())
        return self.search_scope_for_names(
            list(dict.fromkeys(names)),
            provenance_refs=list(dict.fromkeys(refs)),
        )

    def resolve_mention(
        self, mention: str, role: str = "unknown", hints: str = ""
    ) -> Any:
        cache_key = None
        if self._resolution_cache_enabled:
            cache_key = self._resolution_cache_key(mention, role, hints)
            cached = self._cached_resolution(cache_key)
            if cached is not None:
                return cached
        typed_role, typed_scopes = _typed_l1_feature_context(
            self.context,
            mention,
        )
        effective_role = normalize_spatial_role(role or "unknown")
        if effective_role == "unknown" and typed_role != "unknown":
            effective_role = typed_role
        typed_scope_trace: dict[str, Any] | None = None
        result = None
        if (
            effective_role in {"facility", "landmark"}
            and typed_scopes
            and callable(getattr(self._index, "query_facility_bsms", None))
        ):
            scoped_candidates: dict[tuple[str, str, str], Any] = {}
            scoped_statuses: list[str] = []
            scoped_results: list[Any] = []
            for scope_name in typed_scopes[:_MAX_CANDIDATES]:
                scoped_result = self._index.query_facility_bsms(
                    scope_name,
                    mention,
                    role=effective_role,
                    hints=hints,
                )
                scoped_results.append(scoped_result)
                scoped_status = str(
                    getattr(scoped_result, "status", "unresolved") or "unresolved"
                )
                scoped_statuses.append(scoped_status)
                for candidate in (
                    getattr(scoped_result, "candidates", []) or []
                    if scoped_status != "unresolved"
                    else []
                ):
                    if not any(
                        str(getattr(candidate, field, "") or "").strip()
                        for field in ("feature_bsm", "source_bsm", "geometry_ref")
                    ):
                        continue
                    key = (
                        str(getattr(candidate, "entity_ref", "") or ""),
                        str(getattr(candidate, "feature_bsm", "") or ""),
                        str(getattr(candidate, "geometry_ref", "") or ""),
                    )
                    if any(key):
                        scoped_candidates.setdefault(key, candidate)
            if scoped_results:
                base_result = scoped_results[0]
                selected_candidates = list(scoped_candidates.values())
                if selected_candidates:
                    selected_ref = (
                        selected_candidates[0].entity_ref
                        if len(selected_candidates) == 1
                        and all(status != "ambiguous" for status in scoped_statuses)
                        else None
                    )
                    updates = {
                        "status": (
                            "resolved"
                            if selected_ref
                            else "ambiguous"
                        ),
                        "selected_entity_ref": selected_ref,
                        "candidates": selected_candidates,
                        "evidence_refs": [
                            candidate.entity_ref
                            for candidate in selected_candidates
                        ],
                        "unresolved_reason": None if selected_ref else "multiple scoped features remain",
                    }
                else:
                    updates = {
                        "status": "unresolved",
                        "selected_entity_ref": None,
                        "candidates": [],
                        "evidence_refs": [],
                        "unresolved_reason": "no candidate carries the typed L1 scope",
                    }
                if hasattr(base_result, "model_copy"):
                    result = base_result.model_copy(update=updates)
                else:
                    result = copy(base_result)
                    for key, value in updates.items():
                        setattr(result, key, value)
                typed_scope_trace = {
                    "step": "typed_l1_scoped_feature",
                    "role": effective_role,
                    "scope_names": typed_scopes,
                    "candidate_count": len(selected_candidates),
                }
        if result is None:
            result = self._index.resolve_mention(
                mention,
                role=effective_role,
                hints=hints,
            )
        trace = list(getattr(result, "query_trace", []) or [])
        bundle_digest = str(
            getattr(getattr(self.context, "data_snapshot", None), "digest", "") or ""
        )
        candidates = list(getattr(result, "candidates", []) or [])
        feature_refs = [
            feature_ref_from_candidate(candidate, bundle_digest=bundle_digest)
            for candidate in candidates[:_MAX_CANDIDATES]
            if (
                getattr(candidate, "source_bsms", None)
                or getattr(candidate, "feature_bsm", None)
                or getattr(candidate, "geometry_ref", None)
            )
        ]
        relations = _kg_relations(self.context, feature_refs)
        relation_ids_by_entity: dict[str, list[str]] = {}
        for relation in relations:
            for ref in (relation.subject, relation.object):
                for entity_ref in ref.entity_refs:
                    relation_ids_by_entity.setdefault(entity_ref, []).append(
                        relation.relation_id
                    )
        if relation_ids_by_entity and hasattr(result, "model_copy"):
            enriched_candidates = [
                candidate.model_copy(
                    update={
                        "relation_refs": list(
                            dict.fromkeys(
                                [
                                    *getattr(candidate, "relation_refs", []),
                                    *relation_ids_by_entity.get(
                                        getattr(candidate, "entity_ref", ""), []
                                    ),
                                ]
                            )
                        )[:_MAX_RELATIONS]
                    }
                )
                for candidate in candidates
            ]
            result = result.model_copy(update={"candidates": enriched_candidates})
        trace.append({
            "step": "evidence_graph_join",
            "candidate_count": len(result.candidates),
            "feature_ref_count": len(feature_refs),
            "relation_count": len(relations),
            "kg_version": str(getattr(self.context, "kg_version", 0) or 0),
            "l1_snapshot_ref": str(getattr(self.context, "l1_snapshot_ref", "") or ""),
        })
        if typed_scope_trace is not None:
            trace.append(typed_scope_trace)
        trace.append(_source_semantic_trace(self.context))
        if hasattr(result, "model_copy"):
            updates = {"query_trace": trace[-16:]}
            if typed_scopes:
                scope = self.search_scope_for_names(
                    typed_scopes,
                    reason="typed_l1_scope_retrieval",
                )
                if scope is not None:
                    updates["search_scope"] = scope
            result = result.model_copy(update=updates)
            if _is_scope_target_role(effective_role):
                scope = self.search_scope_for_names(
                    [str(mention).strip()],
                    reason="place_mention_scope",
                )
                if scope is not None:
                    result = result.model_copy(update={"search_scope": scope})
        else:
            result = copy(result)
            result.query_trace = trace[-16:]
        if cache_key is None:
            return result
        return self._cache_resolution(cache_key, result)

    def query_facility_bsms(
        self,
        village_name: str,
        label: str,
        *,
        role: str = "facility",
        hints: str = "",
        spatial_spec: Any = None,
    ) -> Any:
        result = self._index.query_facility_bsms(
            village_name,
            label,
            role=role,
            hints=hints,
        )
        result = _filter_result_by_spatial_spec(
            result,
            self.context,
            " ".join(value for value in (village_name, label, hints) if value),
            self,
            spatial_spec,
        )
        scope_names = _query_scope_names(
            self.context,
            _fold_query(village_name),
        ) or [str(village_name).strip()]
        search_scope = self.search_scope_for_names(
            scope_names,
            reason="facility_scope_retrieval",
        )
        if search_scope is not None and hasattr(result, "model_copy"):
            result = result.model_copy(update={"search_scope": search_scope})
        trace = list(getattr(result, "query_trace", []) or [])
        bundle_digest = str(
            getattr(getattr(self.context, "data_snapshot", None), "digest", "") or ""
        )
        candidates = list(getattr(result, "candidates", []) or [])
        feature_refs = [
            feature_ref_from_candidate(candidate, bundle_digest=bundle_digest)
            for candidate in candidates[:_MAX_CANDIDATES]
            if (
                getattr(candidate, "source_bsms", None)
                or getattr(candidate, "feature_bsm", None)
                or getattr(candidate, "geometry_ref", None)
            )
        ]
        relations = _kg_relations(self.context, feature_refs)
        relation_ids_by_entity: dict[str, list[str]] = {}
        for relation in relations:
            for ref in (relation.subject, relation.object):
                for entity_ref in ref.entity_refs:
                    relation_ids_by_entity.setdefault(entity_ref, []).append(
                        relation.relation_id
                    )
        if relation_ids_by_entity and hasattr(result, "model_copy"):
            result = result.model_copy(update={
                "candidates": [
                    candidate.model_copy(update={
                        "relation_refs": list(
                            dict.fromkeys([
                                *getattr(candidate, "relation_refs", []),
                                *relation_ids_by_entity.get(
                                    getattr(candidate, "entity_ref", ""), []
                                ),
                            ])
                        )[:_MAX_RELATIONS]
                    })
                    for candidate in candidates
                ]
            })
        trace.append({
            "step": "evidence_graph_facility_join",
            "village": village_name,
            "label": label,
            "hints": hints,
            "candidate_count": len(result.candidates),
            "feature_ref_count": len(feature_refs),
            "relation_count": len(relations),
        })
        trace.append(_source_semantic_trace(self.context))
        if hasattr(result, "model_copy"):
            return result.model_copy(update={"query_trace": trace[-16:]})
        result_copy = copy(result)
        result_copy.query_trace = trace[-16:]
        return result_copy

    def candidate_bsms(
        self,
        mention: str,
        *,
        include_ambiguous: bool = False,
        max_candidates: int = 8,
        role: str = "unknown",
        hints: str = "",
    ) -> list[str]:
        """Return bundle parcel evidence for a grounding domain.

        Answer retrieval keeps the old exact-only behavior by default.  GROUND
        can opt into ``include_ambiguous`` so a fuzzy or multi-match mention
        becomes a bounded candidate domain instead of disappearing before
        geometry refinement.  The graph still returns only BSMs already
        attached to indexed evidence; it never invents a coordinate or
        chooses the first ambiguous feature.
        """
        result = self.resolve_mention(mention, role=role, hints=hints)
        candidates = list(getattr(result, "candidates", []) or [])
        if _is_scope_target_role(role):
            return []
        if candidates and all(
            str(getattr(candidate, "role", "") or "").casefold()
            in _SCOPE_TARGET_ROLES
            for candidate in candidates
        ):
            return []
        if result.status == "resolved":
            candidates = candidates[:1]
        elif not include_ambiguous:
            # Keep the candidate set empty, but continue to the parcel
            # attribute branch below.  Queries such as ``耕地``
            # are expected to have no named-place result first.
            candidates = []
        else:
            candidates = candidates[: max(1, int(max_candidates or 1))]
        bsms: list[str] = []
        for candidate in candidates:
            bsms.extend(getattr(candidate, "source_bsms", []) or [])
            # Some facility/landmark candidates retain the nearby parcel set
            # only in this explicit field.  It is spatial context, not a
            # replacement for the feature identity.
            bsms.extend(getattr(candidate, "related_parcel_bsms", []) or [])
        if not bsms and role in {"unknown", "parcel", "zone"}:
            bsms.extend(
                candidate.identity.bundle_feature_bsm
                for candidate in self.query_parcel_candidates(
                    mention,
                    max_candidates=max_candidates,
                    hints=hints,
                )
                if candidate.identity.bundle_feature_bsm
            )
        return list(dict.fromkeys(str(bsm) for bsm in bsms if str(bsm).strip()))

    def query_parcel_candidates(
        self,
        query: str,
        *,
        max_candidates: int = _MAX_CANDIDATES,
        hints: str = "",
    ) -> list[PlaceResolutionCandidate]:
        """Resolve land-use semantics to bounded bundle parcel identities.

        This is intentionally separate from named-place resolution.  A term
        such as ``耕地`` is a class/attribute, not a place name, so it must be
        matched against parcel land-use semantics and then projected to
        existing BSMs.  The compact index stores no geometry; callers use the
        bundle reference to retrieve authoritative geometry later.
        """
        self._ensure_parcel_semantic_index()
        if not self._parcel_semantic_index:
            return []
        folded_query = _fold_query(query, hints)
        if not folded_query:
            return []
        matching_labels = [
            label
            for label in self._parcel_semantic_index
            if label and (label in folded_query or folded_query in label)
        ]
        if not matching_labels:
            return []
        scope_bsms = _query_scope_bsms(self.context, folded_query, graph=self)
        rows: dict[str, tuple[int, str, str, str]] = {}
        for label in matching_labels:
            label_score = len(label)
            for bsm, source_layer, source_feature_id in self._parcel_semantic_index[label]:
                if scope_bsms and bsm not in scope_bsms:
                    continue
                previous = rows.get(bsm)
                value = (label_score, source_layer, source_feature_id, label)
                if previous is None or value > previous:
                    rows[bsm] = value
        ordered = sorted(
            rows.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[: max(1, int(max_candidates or 1))]
        return [
            PlaceResolutionCandidate(
                entity_ref=f"bundle:parcel:{bsm}",
                entity_type="parcel",
                canonical_name=label,
                geometry_ref=f"bundle://feature/{bsm}",
                feature_bsm=bsm,
                source_feature_id=source_feature_id,
                source_layer=source_layer,
                source_bsm=bsm,
                source_bsms=[bsm],
                score=min(0.95, 0.55 + min(label_score, 12) / 100.0),
                evidence_refs=[f"bundle:{source_layer}:{bsm}"],
                bundle_snapshot_digest=str(
                    getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                    or ""
                ),
                evidence={"within_bundle": 0.5, "parcel_semantic_match": 1.0},
            )
            for bsm, (label_score, source_layer, source_feature_id, label) in ordered
        ]

    def _ensure_parcel_semantic_index(self) -> None:
        if self._parcel_semantic_index is not None:
            return
        self._parcel_semantic_index = {}
        parcels = _context_parcels(self.context)
        for parcel in parcels:
            bsm = str(getattr(parcel, "bsm", "") or "").strip()
            if not bsm:
                continue
            layer = str(getattr(parcel, "layer_type", "landuse_current") or "landuse_current")
            source_feature_id = _parcel_source_feature_id(parcel)
            for label in _parcel_semantic_labels(parcel):
                self._parcel_semantic_index.setdefault(label, []).append(
                    (bsm, layer, source_feature_id)
                )

    def query_scope_candidates(
        self,
        query: str,
        entity_scope: list[str] | tuple[str, ...] = (),
        *,
        max_candidates: int = _MAX_CANDIDATES,
        spatial_spec: Any = None,
    ) -> list[PlaceResolutionCandidate]:
        """Return bounded bundle-backed features for a scope-only query.

        A query such as ``社前村的道路`` names a spatial class but no road
        label.  Named-place resolution cannot discover that class by exact
        label alone.  This method uses only the private index's semantic
        labels and opaque bundle refs, then leaves geometry retrieval to the
        normal bundle boundary.
        """
        scopes = {
            str(value or "").strip().casefold()
            for value in (entity_scope or ())
            if str(value or "").strip()
        }
        semantic_query = " ".join(
            [str(query or ""), *_spatial_spec_terms(spatial_spec)]
        ).strip()
        folded_query = _fold_query(semantic_query)
        if not folded_query:
            return []
        allowed_roles: set[str] = set()
        for scope in scopes:
            allowed_roles.update(_SCOPE_ROLES.get(scope, ()))
        scope_bsms = _query_scope_bsms(self.context, folded_query, graph=self)
        scope_names = _query_scope_names(self.context, folded_query)
        scope_refs = _kg_scope_refs(self.context, scope_names)
        scope_evidence_available = bool(scope_bsms or scope_refs)
        direction, directional_bsms = _directional_parcel_bsms(
            self.context,
            query,
            scope_names,
            self,
            spatial_spec,
        )
        role_terms = {
            "facility": ("设施", "服务点", "祠堂", "庙", "学校"),
            "landmark": ("地标", "遗址"),
            "project": ("项目",),
            "road": ("道路", "公路", "路", "交通", "road", "transport"),
            "water": ("水体", "河", "溪", "水库", "水", "water", "hydro"),
            "parcel": ("地块", "耕地", "用地", "农田", "parcel"),
            "zone": ("规划区", "分区", "保护区", "zone"),
            "hazard": ("地质灾害", "灾害点", "崩塌", "滑坡", "泥石流", "hazard"),
        }
        if not allowed_roles:
            allowed_roles.update(
                role
                for role, terms in role_terms.items()
                if any(_fold_query(term) in folded_query for term in terms)
            )
        # An unscoped query is still a project-wide evidence query.  Discover
        # the role from indexed Bundle/KG/L1 labels instead of requiring the
        # caller to know that a name such as ``炉池`` appears in a hazard-point
        # layer.  The probe is bounded and source-backed; it does not infer a
        # role from a regular expression or manufacture an entity.
        semantic_probe_candidates = self.semantic_label_probes(
            semantic_query,
            roles=allowed_roles,
            max_probes=_MAX_RECALL_CANDIDATES,
        )
        if not allowed_roles:
            allowed_roles.update(
                str(role).strip()
                for _probe, role in semantic_probe_candidates
                if str(role).strip()
            )
        if not allowed_roles:
            return []
        scope_is_selective = bool(scopes) and len(allowed_roles) <= 3
        # Scope retrieval must share the same bounded partial-name recall as
        # the unified candidate map.  A village prefix such as ``炉池`` is
        # often embedded in a source label such as ``炉池赖木生``; requiring
        # the whole source label here would make a public EvidenceGraph query
        # silently miss the very hazard point that the index already knows.
        semantic_probe_pairs = {
            (_fold_query(probe), str(role or "").strip())
            for probe, role in semantic_probe_candidates
            if _fold_query(probe) and str(role or "").strip()
        }
        generic_probe_terms = {
            role: {
                _fold_query(term)
                for term in role_terms.get(role, ())
                if _fold_query(term)
            }
            for role in allowed_roles
        }
        specific_probe_roles = {
            probe_role
            for probe, probe_role in semantic_probe_pairs
            if probe not in generic_probe_terms.get(probe_role, set())
        }
        candidates: list[PlaceResolutionCandidate] = []
        for entry in self.iter_entries():
            role = str(getattr(entry, "role", "") or "").strip()
            if role not in allowed_roles:
                continue
            labels = [
                str(getattr(entry, "canonical_name", "") or ""),
                *(str(value) for value in (getattr(entry, "aliases", None) or [])),
                str(getattr(entry, "source_layer", "") or ""),
            ]
            label_match = any(
                _fold_query(label) and _fold_query(label) in folded_query
                for label in labels
            )
            label_match = label_match or any(
                probe == _fold_query(label)
                or probe in _fold_query(label)
                for probe, probe_role in semantic_probe_pairs
                if probe_role == role
                for label in labels
                if _fold_query(label)
            )
            has_specific_probe = role in specific_probe_roles
            role_match = (scope_is_selective and not has_specific_probe) or any(
                _fold_query(term) in folded_query
                for term in role_terms.get(role, ())
            )
            if not label_match and not role_match:
                continue
            source_bsms = list(
                dict.fromkeys(
                    str(value)
                    for value in [
                        *(getattr(entry, "source_bsms", None) or []),
                        getattr(entry, "feature_bsm", "") or "",
                    ]
                    if str(value).strip()
                )
            )
            geometry_ref = str(getattr(entry, "geometry_ref", "") or "").strip()
            feature_bsm = str(getattr(entry, "feature_bsm", "") or "").strip()
            source_bsm = str(getattr(entry, "source_bsm", "") or "").strip()
            if not (
                feature_bsm
                or source_bsm
                or geometry_ref.startswith("bundle://feature/")
            ):
                continue
            entry_scope_bsms = {
                str(value).strip()
                for value in [
                    *(getattr(entry, "anchor_bsms", None) or []),
                    *(getattr(entry, "related_parcel_bsms", None) or []),
                ]
                if str(value).strip()
            }
            parcel_scope_match = bool(
                scope_bsms and entry_scope_bsms.intersection(scope_bsms)
            )
            kg_scope_match = _entry_matches_kg_scope(
                self.context,
                entry,
                scope_refs,
            )
            scope_match = parcel_scope_match or kg_scope_match
            directional_match = bool(
                directional_bsms
                and entry_scope_bsms.intersection(directional_bsms)
            )
            canonical_name = str(getattr(entry, "canonical_name", "") or "").strip()
            score = 0.65
            if label_match:
                score += 0.15
            if scope_match:
                score += 0.12
            if directional_match:
                score += 0.08
            candidates.append(
                PlaceResolutionCandidate(
                    entity_ref=(
                        str((getattr(entry, "entity_refs", None) or [""])[0])
                        or f"bundle:{role}:{source_bsms[0]}"
                    ),
                    entity_type=str(
                        (getattr(entry, "entity_types", None) or [role])[0]
                        or role
                    ),
                    role=role,
                    canonical_name=canonical_name or role,
                    aliases=list(getattr(entry, "aliases", None) or []),
                    geometry_ref=geometry_ref or None,
                    feature_bsm=feature_bsm or None,
                    source_feature_id=getattr(entry, "source_feature_id", None),
                    source_layer=getattr(entry, "source_layer", None),
                    source_bsm=source_bsm or None,
                    source_bsms=source_bsms,
                    related_parcel_bsms=list(
                        getattr(entry, "related_parcel_bsms", None) or []
                    ),
                    score=score,
                    evidence_refs=list(getattr(entry, "provenance", None) or []),
                    relation_refs=list(getattr(entry, "relation_refs", None) or []),
                    l1_fact_refs=list(getattr(entry, "l1_fact_refs", None) or []),
                    l1_snapshot_ref=str(getattr(entry, "l1_snapshot_ref", "") or ""),
                    bundle_snapshot_digest=str(
                        getattr(entry, "bundle_snapshot_digest", "")
                        or getattr(getattr(self.context, "data_snapshot", None), "digest", "")
                        or ""
                    ),
                    evidence={
                        "within_bundle": 1.0,
                        "entity_type_role": 1.0,
                        "exact_canonical_alias": 1.0 if label_match else 0.0,
                        "scope_topology": 1.0 if scope_match else 0.0,
                        "directional_topology": 1.0 if directional_match else 0.0,
                    },
                )
            )
        unique: dict[str, PlaceResolutionCandidate] = {}
        for candidate in candidates:
            key = str(
                candidate.feature_bsm
                or candidate.source_bsm
                or candidate.entity_ref
            )
            unique.setdefault(key, candidate)
        scoped_candidates = [
            candidate
            for candidate in unique.values()
            if float(candidate.evidence.get("scope_topology", 0.0) or 0.0) > 0.0
        ]
        if scope_evidence_available and scoped_candidates:
            unique = {
                str(
                    candidate.feature_bsm
                    or candidate.source_bsm
                    or candidate.entity_ref
                ): candidate
                for candidate in scoped_candidates
            }
        directional_candidates = [
            candidate
            for candidate in unique.values()
            if float(candidate.evidence.get("directional_topology", 0.0) or 0.0) > 0.0
        ]
        if directional_bsms and directional_candidates:
            unique = {
                str(
                    candidate.feature_bsm
                    or candidate.source_bsm
                    or candidate.entity_ref
                ): candidate
                for candidate in directional_candidates
            }
        ordered_candidates = sorted(
            unique.values(),
            key=lambda item: (-float(item.score or 0.0), item.canonical_name, item.entity_ref),
        )[: max(1, int(max_candidates or 1))]
        ordered_candidates, _ = _apply_topology_to_candidates(
            ordered_candidates,
            self.context,
            self,
            spatial_spec,
        )
        return ordered_candidates[: max(1, int(max_candidates or 1))]

    def packet_for_mention(
        self, mention: str, *, role: str = "unknown", hints: str = ""
    ) -> EvidencePacket:
        """Return the detailed graph view for one grounding mention."""
        result = self.resolve_mention(mention, role=role, hints=hints)
        bundle_digest = str(
            getattr(getattr(self.context, "data_snapshot", None), "digest", "") or ""
        )
        scope_only = _is_scope_target_role(role) or bool(
            result.candidates
            and all(
                _is_scope_target_role(getattr(candidate, "role", ""))
                for candidate in result.candidates
            )
        )
        spatial_candidates = [
            candidate
            for candidate in result.candidates
            if (
                not scope_only
                and not (
                    _is_scope_target_role(getattr(candidate, "role", ""))
                    and not str(getattr(candidate, "feature_bsm", "") or "").strip()
                    and not str(getattr(candidate, "geometry_ref", "") or "").strip()
                )
                and (
                    getattr(candidate, "source_bsms", None)
                    or getattr(candidate, "feature_bsm", None)
                    or getattr(candidate, "geometry_ref", None)
                )
            )
        ]
        refs = [
            feature_ref_from_candidate(candidate, bundle_digest=bundle_digest)
            for candidate in spatial_candidates[:_MAX_CANDIDATES]
        ]
        relations = _kg_relations(self.context, refs)
        return EvidencePacket(
            request=mention,
            bundle_snapshot_digest=bundle_digest,
            kg_version=str(getattr(self.context, "kg_version", 0) or 0),
            l1_snapshot_ref=str(getattr(self.context, "l1_snapshot_ref", "") or ""),
            l1_scope_refs=(
                list(getattr(result.search_scope, "provenance_refs", None) or [])
                if getattr(result, "search_scope", None) is not None
                else []
            ),
            candidate_refs=refs,
            candidate_total=0 if scope_only else len(spatial_candidates),
            candidate_offset=0,
            candidate_limit=_MAX_CANDIDATES,
            candidates_truncated=(
                not scope_only and len(spatial_candidates) > _MAX_CANDIDATES
            ),
            next_candidate_offset=(
                _MAX_CANDIDATES
                if not scope_only and len(spatial_candidates) > _MAX_CANDIDATES
                else None
            ),
            relation_evidence=relations,
            ambiguity_status=(
                "resolved" if result.status == "resolved"
                else "multiple" if result.status == "ambiguous"
                else "unresolved"
            ),
            sufficiency=("sufficient" if refs else "insufficient"),
            missing_evidence=[] if refs else ["bundle_feature_identity"],
            query_trace=list(result.query_trace),
        )


def _identity_for_candidate(
    candidate: PlaceResolutionCandidate,
    *,
    bundle_digest: str,
) -> BundleFeatureIdentity:
    """Build a stable feature identity without making geometry authoritative."""
    source_bsm = str(
        getattr(candidate, "source_bsm", "")
        or getattr(candidate, "feature_bsm", "")
        or ""
    ).strip()
    if source_bsm:
        bsm = source_bsm
        bsm_kind = "source" if _is_bsm(source_bsm) else "unknown"
    else:
        raw = str(
            getattr(candidate, "entity_ref", "")
            or getattr(candidate, "canonical_name", "")
        ).encode("utf-8")
        bsm = f"synthetic:{hashlib.sha256(raw).hexdigest()[:16]}"
        bsm_kind = "synthetic"

    admin_code = bsm[:12] if _is_bsm(bsm) else ""
    sequence_code = bsm[12:] if _is_bsm(bsm) else ""
    return BundleFeatureIdentity(
        bundle_feature_bsm=bsm,
        canonical_name=str(getattr(candidate, "canonical_name", "") or ""),
        entity_type=str(getattr(candidate, "entity_type", "") or ""),
        role=str(getattr(candidate, "role", "") or ""),
        aliases=[
            str(value)
            for value in (getattr(candidate, "aliases", None) or [])
            if str(value).strip()
        ][:12],
        admin_code_12=admin_code,
        sequence_code_8=sequence_code,
        source_feature_id=str(getattr(candidate, "source_feature_id", "") or ""),
        source_layer=str(getattr(candidate, "source_layer", "") or ""),
        source_bsm=source_bsm or None,
        bsm_kind=bsm_kind,
        bundle_snapshot_digest=bundle_digest,
    )


def feature_ref_from_candidate(
    candidate: PlaceResolutionCandidate,
    *,
    bundle_digest: str = "",
) -> FeatureEvidenceRef:
    """Convert a resolver candidate to a non-geometric evidence reference."""
    identity = _identity_for_candidate(candidate, bundle_digest=bundle_digest)
    geometry_ref = (
        f"bundle://feature/{identity.bundle_feature_bsm}"
        if getattr(candidate, "geometry_ref", None) and identity.bundle_feature_bsm
        else None
    )
    raw_score = float(getattr(candidate, "score", 0.0) or 0.0)
    evidence_dimensions = {
        str(key): float(value)
        for key, value in dict(
            getattr(candidate, "evidence", None) or {}
        ).items()
    }
    # Keep distinct meanings distinct.  The old generic ``confidence`` mixed
    # source authority, semantic matching and spatial support, causing a real
    # Bundle feature to look like a 100%-certain answer even when several
    # same-name candidates remained.  These normalized groups are retrieval
    # diagnostics only; final spatial selection confidence stays unset until
    # GROUND actually chooses a candidate or cluster.
    score_ceiling = sum(
        float(weight)
        for dimension, weight in WEIGHTS.items()
        if float(weight) > 0.0
    )
    retrieval_score = (
        max(0.0, min(1.0, raw_score / score_ceiling))
        if score_ceiling
        else 0.0
    )
    semantic_match_score = min(
        1.0,
        sum(
            evidence_dimensions.get(key, 0.0)
            for key in (
                "exact_canonical_alias",
                "l1_fact_exact",
                "entity_type_role",
            )
        ) / 2.5,
    )
    spatial_support_score = min(
        1.0,
        sum(
            evidence_dimensions.get(key, 0.0)
            for key in (
                "relation_topology",
                "within_bundle",
                "geometry_near_anchor",
            )
        ) / 1.5,
    )
    external_support_score = min(
        1.0,
        evidence_dimensions.get("external_geocoder", 0.0) / 0.3,
    )
    return FeatureEvidenceRef(
        identity=identity,
        entity_refs=[getattr(candidate, "entity_ref", "")] if getattr(candidate, "entity_ref", "") else [],
        geometry_ref=geometry_ref,
        geometry_authority="bundle" if geometry_ref else "none",
        relation_refs=list(dict.fromkeys(getattr(candidate, "relation_refs", [])))[:12],
        related_parcel_bsms=list(
            dict.fromkeys(
                [
                    *(getattr(candidate, "anchor_bsms", None) or []),
                    *(getattr(candidate, "related_parcel_bsms", None) or []),
                    *(getattr(candidate, "source_bsms", None) or []),
                ]
            )
        )[:24],
        provenance_refs=list(dict.fromkeys(getattr(candidate, "evidence_refs", [])))[:12],
        l1_fact_refs=list(dict.fromkeys(getattr(candidate, "l1_fact_refs", [])))[:24],
        l1_snapshot_ref=str(getattr(candidate, "l1_snapshot_ref", "") or ""),
        selection_evidence=evidence_dimensions,
        source_authority_score=1.0 if geometry_ref else 0.0,
        semantic_match_score=round(semantic_match_score, 4),
        spatial_support_score=round(spatial_support_score, 4),
        external_support_score=round(external_support_score, 4),
        retrieval_score=round(retrieval_score, 4),
        selection_confidence=None,
    )


def _bundle_feature_records(context: Any):
    workspace = getattr(context, "workspace", None)
    if workspace is None:
        return
    for group_name in ("points", "lines", "polygons"):
        group = getattr(workspace, group_name, None)
        if group is None:
            continue
        layer_names = list(group.keys()) if hasattr(group, "keys") else []
        if not layer_names and hasattr(group, "get"):
            layer_names = [
                "facilities_current",
                "annotations_current",
                "roads_current",
                "water_bodies",
                "landuse_current",
            ]
        for layer_name in layer_names:
            for feature in list(group.get(layer_name) or []):
                yield group_name, str(layer_name), feature


def _geometry_ref_for_bundle_feature(
    context: Any,
    feature_ref: FeatureEvidenceRef,
) -> GeometryRef | None:
    """Fetch one verified packet ref from the current bundle snapshot.

    EvidencePacket deliberately carries only an opaque ``bundle://`` ref.
    GROUND is the first boundary allowed to request the authoritative WKT;
    the WKT is never accepted from the packet or from an LLM response.
    """
    bsm = str(
        getattr(getattr(feature_ref, "identity", None), "bundle_feature_bsm", "")
        or ""
    ).strip()
    if not bsm or not str(getattr(feature_ref, "geometry_ref", "") or "").startswith(
        "bundle://feature/"
    ):
        return None
    workspace = getattr(context, "workspace", None)
    metadata = getattr(workspace, "metadata", None)
    crs = str(getattr(metadata, "crs", "") or "EPSG:4326")
    indexed = None
    finder = getattr(workspace, "find_feature_by_bsm", None)
    if callable(finder):
        try:
            indexed = finder(bsm)
        except Exception:
            indexed = None
    records = [indexed] if indexed is not None else (
        record for record in (_bundle_feature_records(context) or ())
        if str(getattr(record[2], "bsm", "") or "").strip() == bsm
    )
    for group_name, layer_name, feature in records:
        raw_geometry = getattr(feature, "geometry", None)
        try:
            from shapely.geometry import shape

            geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                return None
        except Exception:
            return None
        identity = getattr(feature_ref, "identity", None)
        source_feature_id = str(
            getattr(identity, "source_feature_id", "")
            or getattr(feature, "source_feature_id", "")
            or getattr(feature, "ysdm", "")
            or ""
        )
        source_ref = f"bundle:{layer_name}:{bsm}"
        source_refs = list(
            dict.fromkeys(
                [
                    source_ref,
                    str(getattr(feature_ref, "geometry_ref", "") or ""),
                    *(getattr(feature_ref, "provenance_refs", None) or []),
                    *(getattr(feature_ref, "l1_fact_refs", None) or []),
                ]
            )
        )
        return GeometryRef(
            wkt=geometry.wkt,
            crs=crs,
            bbox=tuple(float(value) for value in geometry.bounds),
            source_feature_id=source_feature_id,
            l1_fact_refs=list(
                dict.fromkeys(
                    str(value)
                    for value in (getattr(feature_ref, "l1_fact_refs", None) or [])
                    if str(value).strip()
                )
            ),
            source_ref=source_ref,
            source_refs=[str(value) for value in source_refs if str(value).strip()],
            feature_bsms=[bsm],
            source_bsms=list(
                dict.fromkeys(
                    [
                        *(getattr(feature_ref, "related_parcel_bsms", None) or []),
                        bsm if group_name == "polygons" and layer_name.startswith("landuse") else "",
                    ]
                )
            ),
            feature_kind=f"{group_name}:{layer_name}",
        )
    return None


def geometry_refs_from_evidence_packet(
    context: Any,
    packet: EvidencePacket | None,
    *,
    max_refs: int = _MAX_CANDIDATES,
) -> list[GeometryRef]:
    """Resolve bounded packet refs to independent bundle-owned geometries."""
    if packet is None:
        return []
    refs: list[GeometryRef] = []
    seen: set[str] = set()
    for feature_ref in list(getattr(packet, "candidate_refs", None) or [])[:max_refs]:
        identity = getattr(feature_ref, "identity", None)
        bsm = str(getattr(identity, "bundle_feature_bsm", "") or "").strip()
        if not bsm or bsm in seen:
            continue
        resolved = _geometry_ref_for_bundle_feature(context, feature_ref)
        if resolved is None:
            continue
        seen.add(bsm)
        refs.append(resolved)
    return refs


_SCOPE_ROLES: dict[str, frozenset[str]] = {
    "facilities": frozenset({"facility", "landmark", "project"}),
    "annotations": frozenset({"facility", "landmark", "unknown"}),
    "hazards": frozenset({"hazard"}),
    "hazard_points": frozenset({"hazard"}),
    "roads": frozenset({"road"}),
    "waters": frozenset({"water"}),
    "parcels": frozenset({"zone", "parcel"}),
    "zones": frozenset({"zone", "parcel"}),
}


_L1_SPATIAL_ROLES: dict[str, str] = {
    "facility": "facility",
    "设施": "facility",
    "现状设施": "facility",
    "landmark": "landmark",
    "地标": "landmark",
    "road": "road",
    "道路": "road",
    "road_segment": "road",
    "water": "water",
    "水体": "water",
    "河流": "water",
    "parcel": "parcel",
    "地块": "parcel",
    "landuse": "parcel",
    "zone": "zone",
    "规划区": "zone",
    "village": "village",
    "村庄": "village",
    "natural_village": "village",
    "scope": "scope",
    "administrative_village": "scope",
    "settlement": "scope",
    "place": "scope",
    "area": "scope",
    "行政村": "scope",
    "自然村": "scope",
    "聚落": "scope",
    "地点": "scope",
    "区域": "scope",
    "hazard": "hazard",
    "hazard_point": "hazard",
    "geological_hazard_point": "hazard",
    "地质灾害点": "hazard",
    "地灾点": "hazard",
}


def _l1_record_values(record: Any) -> dict[str, str]:
    attributes = getattr(record, "attributes", None) or {}
    if not isinstance(attributes, dict):
        attributes = {}
    values: dict[str, str] = {}
    for key in (
        "normalized_name",
        "mention",
        "name",
        "target_name",
        "location",
        "spatial_hint",
        "village",
        "settlement",
        "natural_village",
        "related_place",
    ):
        value = getattr(record, key, "") or attributes.get(key, "")
        if isinstance(value, (list, tuple, set)):
            value = "、".join(str(item).strip() for item in value if str(item).strip())
        text = str(value or "").strip()
        if text:
            values[key] = text
    subject_scope = str(getattr(record, "subject_scope", "") or "").strip()
    if subject_scope:
        values.setdefault("subject_scope", subject_scope)
    scope_names = [
        _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
        for scope in _scope_mentions_for_fact(record)
        if _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
    ]
    if scope_names:
        values.setdefault("location", "、".join(dict.fromkeys(scope_names)))
        values.setdefault("scope", "、".join(dict.fromkeys(scope_names)))
    return values


def _l1_record_role(record: Any, values: dict[str, str]) -> str:
    attributes = getattr(record, "attributes", None) or {}
    raw_role = str(
        getattr(record, "role", "")
        or (attributes.get("role", "") if isinstance(attributes, dict) else "")
        or getattr(record, "semantic_type", "")
        or ""
    )
    raw_role = normalize_spatial_role(raw_role)
    return _L1_SPATIAL_ROLES.get(raw_role, "unknown")


def _typed_l1_spatial_records(
    context: Any,
    query: str,
) -> list[tuple[str, str, Any, dict[str, str]]]:
    """Return query-matching typed L1 spatial records.

    L1 records contribute semantic labels, scope attributes and provenance
    hints only. They never contribute a BSM or geometry; those must still be
    joined from the bundle/KG candidate boundary.
    """
    folded_query = _fold_query(query)
    if not folded_query:
        return []
    result: list[tuple[str, str, Any, dict[str, str]]] = []
    for record in _context_l1_items(context):
        values = _l1_record_values(record)
        role = _l1_record_role(record, values)
        if role == "unknown" and not any(
            values.get(key, "")
            for key in ("location", "spatial_hint", "village", "settlement", "natural_village")
        ):
            continue
        label_values = [
            values.get("normalized_name", ""),
            values.get("mention", ""),
            values.get("name", ""),
            values.get("subject_scope", ""),
        ]
        label = next(
            (
                value
                for value in label_values
                if value and _fold_query(value) in folded_query
            ),
            "",
        )
        if label:
            result.append((label, role, record, values))
    return result


_GENERIC_LABEL_PROBES: dict[str, frozenset[str]] = {
    "facility": frozenset({"设施", "服务点", "祠堂", "庙", "学校"}),
    "landmark": frozenset({"地标", "遗址"}),
    "project": frozenset({"项目"}),
    "road": frozenset({"道路", "公路", "路", "交通", "road", "transport"}),
    "water": frozenset({"水体", "河", "溪", "水库", "水", "water", "hydro"}),
    "parcel": frozenset({"地块", "耕地", "用地", "农田", "parcel"}),
    "zone": frozenset({"规划区", "分区", "保护区", "zone"}),
    "hazard": frozenset({"地质灾害", "灾害点", "崩塌", "滑坡", "泥石流", "hazard"}),
}


def _query_labels(
    graph: EvidenceGraph,
    query: str,
    village_name: str,
    entity_scope: list[str] | tuple[str, ...] = (),
    probe_terms: list[str] | tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Find bounded locatable labels that occur in a user query.

    The old implementation only admitted facilities/landmarks.  That made
    road, water and zone entities invisible to the same EvidenceGraph even
    though KG and bundle already carried their identities.  Scope controls
    the role set so a query mentioning a village does not accidentally return
    the village boundary as a facility candidate.
    """
    query_folded = str(query or "").casefold()
    requested_scopes = {
        str(value or "").strip().casefold()
        for value in (entity_scope or ())
        if str(value or "").strip()
    }
    allowed_roles: set[str] = set()
    for scope in requested_scopes:
        allowed_roles.update(_SCOPE_ROLES.get(scope, ()))
    if not allowed_roles:
        allowed_roles.update({
            "facility", "landmark", "project", "hazard", "unknown",
            "road", "water", "zone", "parcel",
        })
    labels: list[tuple[str, str]] = []
    for entry in graph.iter_entries():
        role = str(getattr(entry, "role", "") or "")
        if role not in allowed_roles:
            continue
        labels_for_entry = [
            str(getattr(entry, "canonical_name", "") or "").strip(),
            *[
                str(value).strip()
                for value in (getattr(entry, "aliases", None) or [])
                if str(value).strip()
            ],
        ]
        label = next(
            (
                value
                for value in labels_for_entry
                if value and value.casefold() in query_folded
            ),
            "",
        )
        if not label:
            # Structured spatial terms are produced by the query LLM/spec,
            # not by regex tokenization.  They may occur inside a richer
            # source attribute such as a hazard-point address.  Reuse the
            # term as the bounded index probe while retaining the point's
            # real Bundle identity and related parcels.
            label = next(
                (
                    str(term).strip()
                    for term in probe_terms
                    if _fold_query(term)
                    and any(
                        _fold_query(term) in _fold_query(value)
                        for value in labels_for_entry
                        if value
                    )
                ),
                "",
            )
        if not label:
            continue
        pair = (label, role)
        if pair not in labels:
            labels.append(pair)
        if len(labels) >= _MAX_CANDIDATES:
            break
    for label, role in graph.semantic_label_probes(
        query,
        roles=allowed_roles,
        max_probes=_MAX_CANDIDATES,
    ):
        if _fold_query(label) in {
            _fold_query(value)
            for value in _GENERIC_LABEL_PROBES.get(role, ())
        }:
            # A class word such as “道路” belongs to scope retrieval.  It is
            # not a named feature probe: keeping it here would route every
            # same-scope road through resolve_mention and skip directional
            # parcel/topology narrowing.
            continue
        pair = (label, role)
        if pair not in labels:
            labels.append(pair)
        if len(labels) >= _MAX_CANDIDATES:
            break
    for label, role, _record, _values in _typed_l1_spatial_records(
        graph.context,
        query,
    ):
        if role not in allowed_roles and role != "unknown":
            continue
        pair = (label, role)
        if pair not in labels:
            labels.append(pair)
        if len(labels) >= _MAX_CANDIDATES:
            break
    return labels


def _query_scope_hint(graph: EvidenceGraph, context: Any, query: str, default: str) -> str:
    """Prefer a report-named settlement/object scope explicitly in the query.

    ``context.village_name`` is the single administrative village/project
    scope.  A question may additionally name a natural village or settlement
    label (for example, ``社前村`` in a report about ``金田村``), but this is a
    semantic place anchor, not a second administrative level.  Selecting the
    longest matching report-backed mention keeps the facility join bounded and
    avoids requiring the project scope to be repeated by the user.
    """
    query_folded = str(query or "").casefold()
    hints: list[str] = []
    for scope in graph.semantic_scopes:
        scope_items = list(getattr(scope, "scope_mentions", None) or [])
        if not scope_items:
            scope_items = list(getattr(scope, "village_mentions", None) or [])
        for mention in scope_items:
            value = str(
                getattr(mention, "normalized_name", mention) or ""
            ).strip()
            if value and value.casefold() in query_folded:
                hints.append(value)
    for fact in _context_l1_items(context):
        for scope in _scope_mentions_for_fact(fact):
            value = _scope_value(scope, "normalized_name") or _scope_value(scope, "name")
            role = _scope_value(scope, "role").casefold()
            if (
                _is_specific_scope_name(value)
                and _is_scope_target_role(role)
                and _fold_query(value) in _fold_query(query_folded)
            ):
                hints.append(value)
    for _label, _role, _record, values in _typed_l1_spatial_records(
        context,
        query,
    ):
        for key in (
            "location",
            "spatial_hint",
            "village",
            "settlement",
            "natural_village",
            "related_place",
        ):
            value = values.get(key, "")
            if _is_specific_scope_name(value) and value.casefold() in query_folded:
                hints.append(value)
    gazetteer = getattr(context, "gazetteer", None)
    for entry in getattr(gazetteer, "entries", []) or []:
        if not _is_dynamic_scope_entry(entry):
            continue
        value = str(getattr(entry, "name", "") or "").strip()
        entry_role = str(getattr(entry, "role", "") or "").casefold()
        if (
            _is_specific_scope_name(value)
            and (not entry_role or _is_scope_target_role(entry_role))
            and _fold_query(value) in _fold_query(query_folded)
        ):
            hints.append(value)
    if not hints:
        return str(default or "")
    unique = list(dict.fromkeys(hints))
    if len(unique) == 1:
        return unique[0]
    return "、".join(sorted(unique, key=lambda value: (-len(value), value)))


def _candidate_map(
    context: Any,
    *,
    query: str,
    village_name: str,
    entity_scope: list[str] | tuple[str, ...] = (),
    spatial_spec: Any = None,
    candidate_offset: int = 0,
    candidate_limit: int = _MAX_CANDIDATES,
) -> tuple[list[PlaceResolutionCandidate], set[str], list[str], int]:
    graph = getattr(context, "evidence_graph", None)
    if graph is None:
        return [], set(), [], 0
    page_offset = max(0, int(candidate_offset or 0))
    page_limit = min(
        _MAX_CANDIDATE_PAGE,
        max(1, int(candidate_limit or _MAX_CANDIDATES)),
    )
    resolved: list[PlaceResolutionCandidate] = []
    semantic_query = " ".join([str(query or ""), *_spatial_spec_terms(spatial_spec)]).strip()
    labels = _query_labels(
        graph,
        semantic_query,
        village_name,
        entity_scope,
        probe_terms=_spatial_spec_terms(spatial_spec),
    )
    scope_hint = _query_scope_hint(graph, context, semantic_query, village_name)
    l1_hints = [query, semantic_query, scope_hint]
    query_folded = _fold_query(semantic_query)
    for fact in _context_location_mentions(context):
        mention = _fold_query(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        )
        if mention and mention in query_folded:
            for field in (
                "spatial_hint",
                "related_mentions",
                "source_span",
                "scopes",
            ):
                value = getattr(fact, field, "")
                if isinstance(value, (list, tuple)):
                    for item in value:
                        if field == "scopes":
                            l1_hints.extend(
                                str(getattr(item, key, "") or "")
                                for key in ("name", "normalized_name", "role")
                                if str(getattr(item, key, "") or "").strip()
                            )
                        elif str(item).strip():
                            l1_hints.append(str(item))
                elif str(value or "").strip():
                    l1_hints.append(str(value)[:240])
    for _label, _role, record, values in _typed_l1_spatial_records(
        context,
        semantic_query,
    ):
        l1_hints.extend(
            value
            for value in (
                str(getattr(record, "statement", "") or "").strip(),
                str(getattr(record, "source_span", "") or "").strip(),
                *values.values(),
            )
            if value
        )
    retrieval_hints = " ".join(dict.fromkeys(value for value in l1_hints if value))
    result_statuses: set[str] = set()
    unresolved_reasons: list[str] = []
    for label, role in labels:
        if role in {"facility", "landmark", "project", "hazard", "unknown"}:
            result = graph.query_facility_bsms(
                scope_hint,
                label,
                role=role,
                hints=retrieval_hints,
                spatial_spec=spatial_spec,
            )
        else:
            result = graph.resolve_mention(
                label,
                role=role,
                hints=retrieval_hints,
            )
            result = _filter_result_by_spatial_spec(
                result,
                context,
                semantic_query,
                graph,
                spatial_spec,
            )
        # Candidate generation and final selection are separate boundaries.
        # A result can be unresolved because the requested village relation
        # is not yet proven, while still carrying valid bundle-backed source
        # candidates that the planning LLM must inspect.
        if result.candidates:
            resolved.extend(result.candidates)
            result_statuses.add(str(result.status or "unresolved"))
            reason = str(result.unresolved_reason or "").strip()
            if reason and reason not in unresolved_reasons:
                unresolved_reasons.append(reason)
    if not labels:
        resolved.extend(
            graph.query_scope_candidates(
                query,
                entity_scope,
                max_candidates=_MAX_RECALL_CANDIDATES,
                spatial_spec=spatial_spec,
            )
        )
    if any(
        str(scope or "").strip().casefold() in {"parcels", "zones"}
        for scope in (entity_scope or ())
    ):
        resolved.extend(
            graph.query_parcel_candidates(
                query,
                max_candidates=_MAX_RECALL_CANDIDATES,
                hints=scope_hint,
            )
        )
    unique: dict[str, PlaceResolutionCandidate] = {}
    kg = getattr(context, "kg", None)
    for candidate in resolved:
        # An L1 mention without a bound feature is semantic scope only.  It
        # must not become a synthetic spatial candidate when a real bundle
        # feature with the same label is available.
        if (
            _is_scope_target_role(candidate.role)
            and not str(candidate.feature_bsm or "").strip()
            and not str(candidate.geometry_ref or "").strip()
        ):
            continue
        if not (
            str(candidate.feature_bsm or "").strip()
            or str(candidate.source_bsm or "").strip()
            or str(candidate.geometry_ref or "").strip()
        ):
            continue
        bsm = str(candidate.feature_bsm or candidate.source_bsm or "").strip()
        key = bsm or f"{candidate.entity_ref}:{candidate.canonical_name}"
        existing = unique.get(key)
        if existing is None:
            unique[key] = candidate
            continue
        existing_in_kg = bool(
            kg is not None
            and kg.find_entities(entity_ref=existing.entity_ref, limit=1)
        )
        candidate_in_kg = bool(
            kg is not None
            and kg.find_entities(entity_ref=candidate.entity_ref, limit=1)
        )
        existing_rank = (
            existing_in_kg,
            len(existing.relation_refs),
            float(existing.score or 0.0),
        )
        candidate_rank = (
            candidate_in_kg,
            len(candidate.relation_refs),
            float(candidate.score or 0.0),
        )
        if candidate_rank > existing_rank:
            unique[key] = candidate
    ordered = sorted(
        unique.values(),
        key=lambda item: (-float(item.score or 0.0), item.canonical_name, item.entity_ref),
    )
    candidate_total = len(ordered)
    ordered = ordered[page_offset : page_offset + page_limit]
    ordered, _ = _apply_topology_to_candidates(
        ordered,
        context,
        graph,
        spatial_spec,
    )
    return ordered[:page_limit], result_statuses, unresolved_reasons, candidate_total


def _feature_ref_from_kg_entity(
    entity: SpatialKGEntity,
    *,
    bundle_digest: str,
) -> FeatureEvidenceRef:
    source_bsm = str(entity.feature_bsm or "").strip()
    if source_bsm and _is_bsm(source_bsm):
        bsm = source_bsm
        bsm_kind = "source"
        admin_code = bsm[:12]
        sequence_code = bsm[12:]
    else:
        raw = str(entity.entity_ref).encode("utf-8")
        bsm = f"synthetic:{hashlib.sha256(raw).hexdigest()[:16]}"
        bsm_kind = "synthetic"
        admin_code = ""
        sequence_code = ""
    return FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm=bsm,
            canonical_name=str(entity.canonical_name or ""),
            entity_type=str(entity.entity_type or ""),
            role=str(entity.entity_type or ""),
            aliases=[str(value) for value in entity.aliases if str(value).strip()][:12],
            admin_code_12=admin_code,
            sequence_code_8=sequence_code,
            source_feature_id=str(entity.source_feature_id or ""),
            source_layer=str(entity.source_layer or ""),
            source_bsm=source_bsm or None,
            bsm_kind=bsm_kind,
            bundle_snapshot_digest=bundle_digest,
        ),
        entity_refs=[entity.entity_ref],
        geometry_ref=None,
        geometry_authority="none",
    )


def _kg_relations(context: Any, candidates: list[FeatureEvidenceRef]) -> list[SpatialRelationEvidence]:
    kg = getattr(context, "kg", None)
    if kg is None or not hasattr(kg, "find_relations"):
        return []
    refs = {ref.entity_refs[0]: ref for ref in candidates if ref.entity_refs}
    bundle_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    relations: list[SpatialRelationEvidence] = []
    seen: set[str] = set()
    for candidate_ref in refs:
        relations_for_candidate = [
            *kg.find_relations(subject_ref=candidate_ref, limit=_MAX_RELATIONS),
            *kg.find_relations(object_ref=candidate_ref, limit=_MAX_RELATIONS),
        ]
        for relation in relations_for_candidate:
            if relation.relation_id in seen:
                continue
            subject = refs.get(relation.subject_ref)
            if subject is None:
                entities = kg.find_entities(entity_ref=relation.subject_ref, limit=1)
                subject = (
                    _feature_ref_from_kg_entity(
                        entities[0], bundle_digest=bundle_digest
                    )
                    if entities
                    else None
                )
            object_evidence_ref = refs.get(relation.object_ref)
            if object_evidence_ref is None:
                entities = kg.find_entities(entity_ref=relation.object_ref, limit=1)
                object_evidence_ref = (
                    _feature_ref_from_kg_entity(
                        entities[0], bundle_digest=bundle_digest
                    )
                    if entities
                    else None
                )
            if subject is None or object_evidence_ref is None:
                continue
            relations.append(
                SpatialRelationEvidence(
                    relation_id=relation.relation_id,
                    subject=subject,
                    predicate=relation.predicate,
                    object=object_evidence_ref,
                    metric_value=relation.metric_value,
                    metric_unit=relation.metric_unit,
                    tolerance=relation.tolerance,
                    crs=relation.crs,
                    computation_method=relation.method,
                    provenance_refs=list(relation.provenance_refs),
                )
            )
            seen.add(relation.relation_id)
            if len(relations) >= _MAX_RELATIONS:
                return relations
    return relations


def enrich_evidence_packet_with_spatial_graph(
    packet: EvidencePacket,
    context: Any,
    *,
    query: str,
    village_name: str = "",
    entity_scope: list[str] | tuple[str, ...] = (),
    spatial_spec: Any = None,
    candidate_offset: int = 0,
    candidate_limit: int = _MAX_CANDIDATES,
) -> EvidencePacket:
    """Attach bounded feature and relation references when context is ready."""
    village = village_name or str(getattr(context, "village_name", "") or "")
    (
        candidates,
        candidate_statuses,
        candidate_reasons,
        candidate_total,
    ) = _candidate_map(
        context,
        query=query,
        village_name=village,
        entity_scope=entity_scope,
        spatial_spec=spatial_spec,
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
    )
    bundle_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    feature_refs = [
        feature_ref_from_candidate(candidate, bundle_digest=bundle_digest)
        for candidate in candidates
    ]
    relations = _kg_relations(context, feature_refs)
    scope_refs = []
    graph = getattr(context, "evidence_graph", None)
    for scope in graph.semantic_scopes if graph is not None else []:
        scope_items = list(getattr(scope, "scope_mentions", None) or [])
        mentions = [
            str(
                getattr(item, "normalized_name", "")
                or getattr(item, "name", "")
                or item
            ).casefold()
            for item in scope_items
        ]
        mentions.extend(
            str(value).casefold()
            for value in getattr(scope, "village_mentions", []) or []
        )
        if village.casefold() in mentions:
            scope_refs.append(str(scope.scope_id))

    trace = [*packet.query_trace]
    trace.extend(
        [
            {"step": "l1_to_evidence_graph", "candidate_count": len(candidates)},
            {
                "step": "candidate_generation_status",
                "statuses": sorted(candidate_statuses),
                "reasons": candidate_reasons[:6],
            },
            {
                "step": "candidate_pagination",
                "offset": max(0, int(candidate_offset or 0)),
                "limit": min(
                    _MAX_CANDIDATE_PAGE,
                    max(1, int(candidate_limit or _MAX_CANDIDATES)),
                ),
                "returned": len(candidates),
                "total": candidate_total,
                "has_next": (
                    max(0, int(candidate_offset or 0)) + len(candidates)
                    < candidate_total
                ),
            },
            {"step": "village_scope_hint", "value": _query_scope_hint(
                graph, context, query, village
            ) if graph is not None else village, "scope_kind": "generic"},
            {
                "step": "directional_scope_hint",
                "value": _query_direction(query, spatial_spec),
                "parser": "llm_structured" if spatial_spec is not None else "deterministic_scope",
            },
            {"step": "kg_topology_join", "relation_count": len(relations)},
            _source_semantic_trace(context),
        ]
    )
    ambiguity_status = (
        "multiple"
        if len(feature_refs) > 1 or "ambiguous" in candidate_statuses
        else "unresolved"
        if "unresolved" in candidate_statuses
        else "resolved"
        if len(feature_refs) == 1
        else "unresolved"
    )
    return packet.model_copy(
        update={
            "bundle_snapshot_digest": bundle_digest or packet.bundle_snapshot_digest,
            "kg_version": str(getattr(context, "kg_version", "") or packet.kg_version),
            "l1_snapshot_ref": str(
                getattr(context, "l1_snapshot_ref", "") or packet.l1_snapshot_ref
            ),
            "l1_scope_refs": list(dict.fromkeys(scope_refs))[:12],
            "candidate_refs": feature_refs,
            "candidate_total": candidate_total,
            "candidate_offset": max(0, int(candidate_offset or 0)),
            "candidate_limit": min(
                _MAX_CANDIDATE_PAGE,
                max(1, int(candidate_limit or _MAX_CANDIDATES)),
            ),
            "candidates_truncated": (
                max(0, int(candidate_offset or 0)) + len(feature_refs)
                < candidate_total
            ),
            "next_candidate_offset": (
                max(0, int(candidate_offset or 0)) + len(feature_refs)
                if max(0, int(candidate_offset or 0)) + len(feature_refs) < candidate_total
                else None
            ),
            "relation_evidence": relations,
            # Sufficiency means that evidence exists; ambiguity is computed
            # from the final spatial candidate set after graph enrichment.
            # They must not share the old local-retrieval status.
            "ambiguity_status": ambiguity_status,
            "query_trace": trace[-24:],
        }
    )


def append_feature_identity_facts(
    bundle: EvidenceBundle,
    packet: EvidencePacket,
    context: Any = None,
) -> EvidenceBundle:
    """Expose identity and KG topology as typed facts without copying geometry.

    ``EvidencePacket`` is the detailed graph view, while ``EvidenceBundle`` is
    the answer-facing fact view.  Keeping the identity in both views avoids a
    caller having to understand packet internals just to answer ``某村祠堂的
    BSM``.  The fact carries only bundle refs and identity fields; coordinates
    remain behind ``geometry_ref`` and the bundle authority boundary.
    """
    facts = list(bundle.facts)
    seen = {
        (fact.fact_type, str(fact.fields.get("bundle_feature_bsm", "")))
        for fact in facts
    }
    existing_indexes = {
        (fact.fact_type, str(fact.fields.get("bundle_feature_bsm", ""))): index
        for index, fact in enumerate(facts)
    }
    for ref in packet.candidate_refs[:_MAX_CANDIDATES]:
        identity = ref.identity
        bsm = str(identity.bundle_feature_bsm or "").strip()
        if not bsm:
            continue
        key = ("bundle_feature_identity", bsm)
        if key in seen:
            index = existing_indexes.get(key)
            existing = facts[index] if index is not None else None
            if existing is not None:
                merged_fields = dict(existing.fields or {})
                semantic_name = str(identity.canonical_name or "").strip()
                if semantic_name:
                    merged_fields["canonical_name"] = semantic_name
                merged_fields["entity_type"] = str(identity.entity_type or "")
                merged_fields["role"] = str(identity.role or identity.entity_type or "")
                facts[index] = existing.model_copy(update={"fields": merged_fields})
            continue
        seen.add(key)
        source_layer = str(identity.source_layer or "")
        if "road" in source_layer or "transport" in source_layer:
            feature_kind = "道路"
        elif "water" in source_layer or "hydro" in source_layer:
            feature_kind = "水体"
        elif "landuse" in source_layer or "parcel" in source_layer:
            feature_kind = "地块"
        elif "zone" in source_layer or "planning" in source_layer:
            feature_kind = "规划区"
        elif "facilit" in source_layer or "annotation" in source_layer:
            feature_kind = "设施"
        else:
            feature_kind = "空间要素"
        related_parcels = list(
            dict.fromkeys(
                str(value)
                for value in (ref.related_parcel_bsms or [])
                if str(value).strip()
            )
        )
        semantic_name = str(identity.canonical_name or "").strip()
        role = str(identity.role or identity.entity_type or "").strip()
        descriptor = semantic_name or feature_kind
        if role and role not in descriptor:
            descriptor = f"{descriptor}（{role}）"
        statement = f"{descriptor} BSM 为 {bsm}"
        if related_parcels:
            statement += "；关联地块 BSM 为 " + ", ".join(related_parcels)
        source_refs = list(
            dict.fromkeys(
                [
                    *ref.provenance_refs,
                    *( [f"bundle:snapshot:{identity.bundle_snapshot_digest}"]
                       if identity.bundle_snapshot_digest else [] ),
                ]
            )
        )
        spatial_refs = [ref.geometry_ref] if ref.geometry_ref else []
        facts.append(
            EvidenceFact(
                statement=statement,
                confidence=max(
                    0.5,
                    min(1.0, float(ref.retrieval_score or 0.0)),
                ),
                source_refs=source_refs,
                spatial_refs=spatial_refs,
                fact_type="bundle_feature_identity",
                feature_bsm=bsm,
                related_parcel_bsms=related_parcels,
                fields={
                    "bundle_feature_bsm": bsm,
                    "canonical_name": semantic_name,
                    "entity_type": str(identity.entity_type or ""),
                    "role": role,
                    "source_feature_id": str(identity.source_feature_id or ""),
                    "source_layer": str(identity.source_layer or ""),
                    "geometry_authority": str(ref.geometry_authority or "bundle"),
                },
                evidence_span=statement,
                source_locator=ref.geometry_ref or "",
                support_relation="bundle_identity",
                status="verified" if identity.bsm_kind == "source" else "needs_review",
                evidence_role="location_binding",
                source_kind="bundle_feature",
                spatial_granularity="feature",
                planning_use="grounding",
            )
        )

    if context is not None:
        facts, sources = _append_related_parcel_evidence(
            facts,
            list(bundle.sources),
            packet,
            context,
            seen=seen,
        )
    else:
        sources = list(bundle.sources)

    existing_relations = {
        str(fact.fields.get("relation_id", ""))
        for fact in facts
        if fact.fact_type == "spatial_relation"
    }
    for relation in packet.relation_evidence[:_MAX_RELATIONS]:
        relation_id = str(getattr(relation, "relation_id", "") or "").strip()
        if not relation_id or relation_id in existing_relations:
            continue
        subject_identity = relation.subject.identity
        object_identity = relation.object.identity
        subject_name = str(
            subject_identity.canonical_name
            or subject_identity.bundle_feature_bsm
            or "subject"
        ).strip()
        object_name = str(
            object_identity.canonical_name
            or object_identity.bundle_feature_bsm
            or "object"
        ).strip()
        predicate = str(getattr(relation, "predicate", "") or "")
        predicate_name = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        statement = f"{subject_name} 与 {object_name} 存在空间关系 {predicate_name}"
        subject_bsm = str(subject_identity.bundle_feature_bsm or "").strip()
        object_bsm = str(object_identity.bundle_feature_bsm or "").strip()
        source_refs = list(
            dict.fromkeys(
                [
                    f"kg:relation:{relation_id}",
                    *(str(value) for value in (relation.provenance_refs or []) if str(value).strip()),
                ]
            )
        )
        spatial_refs = [
            str(value)
            for value in (
                relation.subject.geometry_ref,
                relation.object.geometry_ref,
            )
            if str(value or "").strip()
        ]
        facts.append(
            EvidenceFact(
                statement=statement,
                confidence=1.0,
                source_refs=source_refs,
                spatial_refs=list(dict.fromkeys(spatial_refs)),
                fact_type="spatial_relation",
                fields={
                    "evidence_role": "spatial_topology",
                    "source_kind": "kg",
                    "relation_id": relation_id,
                    "predicate": predicate_name,
                    "subject_bsm": subject_bsm,
                    "object_bsm": object_bsm,
                    "subject_geometry_ref": str(relation.subject.geometry_ref or ""),
                    "object_geometry_ref": str(relation.object.geometry_ref or ""),
                },
                evidence_span=statement,
                source_locator=f"kg:relation:{relation_id}",
                support_relation=predicate_name,
                status="verified",
                evidence_role="spatial_topology",
                source_kind="kg",
                spatial_granularity="relation",
                planning_use="constraint",
            )
        )
        existing_relations.add(relation_id)
        for source_ref in source_refs:
            source_ref = str(source_ref or "").strip()
            if not source_ref:
                continue
            if any(str(source.reference or "").strip() == source_ref for source in sources):
                continue
            source_type = (
                "kg"
                if source_ref.startswith("kg:")
                else "gis_layer"
                if source_ref.startswith("bundle:")
                else "context"
            )
            sources.append(
                EvidenceSource(
                    source_type=source_type,
                    reference=source_ref,
                    confidence=1.0,
                )
            )
    return bundle.model_copy(update={"facts": facts, "sources": sources})


def _append_related_parcel_evidence(
    facts: list[EvidenceFact],
    sources: list[EvidenceSource],
    packet: EvidencePacket,
    context: Any,
    *,
    seen: set[tuple[str, str]],
    max_parcels: int = 48,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Expose related current parcels as bounded planning evidence.

    A point/line candidate often intersects a large current parcel.  The
    candidate's ``related_parcel_bsms`` is enough for audit, but it is too
    thin for a planning model to decide whether a target can occupy only a
    sub-area.  This projection adds the parcel's authoritative Bundle ref,
    current land-use labels and source area.  It deliberately does not copy
    coordinates or WKT; SELECT remains responsible for deriving a planning
    subgeometry from the verified ref and target area.
    """
    workspace = getattr(context, "workspace", None)
    current_parcels = []
    try:
        current_parcels = list(context.current_parcels() or [])
    except Exception:
        current_parcels = []
    parcels_by_bsm = {
        str(getattr(parcel, "bsm", "") or "").strip(): parcel
        for parcel in current_parcels
        if str(getattr(parcel, "bsm", "") or "").strip()
    }
    source_keys = {
        (str(source.source_type or "").strip().lower(), str(source.reference or "").strip())
        for source in sources
    }
    emitted = 0
    parent_bsms: dict[str, list[str]] = {}
    for candidate in packet.candidate_refs[:_MAX_CANDIDATES]:
        parent_bsm = str(
            getattr(getattr(candidate, "identity", None), "bundle_feature_bsm", "")
            or ""
        ).strip()
        for value in getattr(candidate, "related_parcel_bsms", None) or []:
            bsm = str(value or "").strip()
            if bsm:
                parent_bsms.setdefault(bsm, []).append(parent_bsm)

    for bsm, parent_refs in parent_bsms.items():
        if emitted >= max(1, int(max_parcels)):
            break
        key = ("bundle_parcel_identity", bsm)
        parcel = parcels_by_bsm.get(bsm)
        if parcel is None and callable(getattr(workspace, "find_feature_by_bsm", None)):
            try:
                found = workspace.find_feature_by_bsm(bsm)
                if found is not None and str(found[0]) == "polygons":
                    parcel = found[2]
            except Exception:
                parcel = None
        if parcel is None or key in seen:
            continue

        labels: list[str] = []
        for attr in (
            "name", "dlmc", "dlbm", "zone_type", "planning_zone",
            "primary_zone", "ghytmc", "ghytbm", "ghflbm",
        ):
            value = str(getattr(parcel, attr, "") or "").strip()
            if value and value not in labels:
                labels.append(value)
        area_ha = 0.0
        try:
            area_ha = float(getattr(parcel, "area_sqm", 0.0) or 0.0) / 10000.0
        except (TypeError, ValueError):
            area_ha = 0.0
        if area_ha <= 0.0:
            try:
                from shapely.geometry import shape
                from app.spatial.model.area_engine import calculate_area_ha

                raw_geometry = getattr(parcel, "geometry", None)
                geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
                area_ha = float(calculate_area_ha(geometry)) if geometry is not None else 0.0
            except Exception:
                area_ha = 0.0
        source_layer = str(getattr(parcel, "layer_type", "landuse_current") or "landuse_current")
        source_feature_id = ""
        raw = getattr(parcel, "_raw", {}) or {}
        if isinstance(raw, dict):
            source_feature_id = str(raw.get("source_feature_id") or "").strip()
        geometry_ref = f"bundle://feature/{bsm}"
        source_ref = f"bundle:{source_layer}:{bsm}"
        label = "、".join(labels[:4]) or "现状地块"
        area_text = f"；源面积约 {area_ha:.4f} ha" if area_ha > 0 else ""
        statement = (
            f"关联现状地块 {bsm}：{label}{area_text}；"
            "可在 SELECT 阶段依据规划目标面积生成子几何"
        )
        facts.append(EvidenceFact(
            statement=statement,
            confidence=0.98,
            source_refs=[source_ref],
            spatial_refs=[geometry_ref],
            fact_type="bundle_parcel_identity",
            fields={
                "bundle_feature_bsm": bsm,
                "source_feature_id": source_feature_id,
                "source_layer": source_layer,
                "current_land_use_labels": "、".join(labels[:8]),
                "source_area_ha": f"{area_ha:.6f}" if area_ha > 0 else "",
                "parent_feature_bsms": ",".join(list(dict.fromkeys(parent_refs))[:8]),
                "geometry_authority": "bundle",
                "planning_geometry_policy": "select_subgeometry_from_bundle_ref",
            },
            feature_bsm=bsm,
            evidence_span=statement,
            source_locator=geometry_ref,
            support_relation="bundle_related_parcel",
            status="verified",
            evidence_role="location_binding",
            source_kind="bundle_feature",
            spatial_granularity="feature",
            planning_use="candidate_site",
        ))
        seen.add(key)
        if ("gis_layer", source_ref) not in source_keys:
            sources.append(EvidenceSource(
                source_type="gis_layer",
                reference=source_ref,
                confidence=0.98,
            ))
            source_keys.add(("gis_layer", source_ref))
        emitted += 1
    return facts, sources


__all__ = [
    "append_feature_identity_facts",
    "enrich_evidence_packet_with_spatial_graph",
    "feature_ref_from_candidate",
    "geometry_refs_from_evidence_packet",
]
