"""KG-side candidate BSM resolution for spatial reference specs.

resolve_candidates takes a SpatialReferenceSpec (produced by PARSE via
instructor) and returns a CandidateSet of entity identifiers from the KG.
This is the "KG returns coarse-range BSM" half of the two-stage parse
(KG candidates -> spatial_ops precision). Does NOT perform geometric
computation.

See docs/gis/integration/PARSE_SPATIAL_GROUNDING_DESIGN.md §3.1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdflib import Literal, RDF, URIRef

from app.infrastructure.logging import get_logger
from ..ontology import PLN, PLN_NS, EntityTypes, GeoPredicates, Relations
from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSet, GeometryRef, SpatialReferenceSpec, RefObject,
)

logger = get_logger(__name__)

_TOPO_PREDICATE = {
    "sfTouches": Relations.sfTouches,
    "sfWithin": Relations.sfWithin,
    "sfIntersects": Relations.sfIntersects,
    "sfContains": Relations.sfContains,
    "nearby": Relations.nearby,
    "connected_via_road": Relations.connected_via_road,
}

_RDF_TYPE_TO_PLN = {
    "Facility": EntityTypes.Facility,
    "Parcel": EntityTypes.Parcel,
    "Road": EntityTypes.Road,
    "WaterBody": EntityTypes.WaterBody,
    "Zone": EntityTypes.Zone,
}


def resolve_candidates(kg, spec: SpatialReferenceSpec) -> CandidateSet:
    ref_ids: List[str] = []
    ref_geometry_wkt: Optional[str] = None
    ref_geometries: list[GeometryRef] = []
    if spec.reference is not None:
        ref_ids = _resolve_reference(kg, spec.reference)
        ref_geometries = _resolve_exact_reference_geometries(
            kg,
            spec,
            spec.reference,
            ref_ids,
        )
        if len(ref_geometries) == 1:
            ref_geometry_wkt = ref_geometries[0].wkt

    if spec.type == "topological":
        result = _resolve_topological(kg, spec, ref_ids)
        result.ref_geometry_wkt = ref_geometry_wkt
        result.ref_geometries = ref_geometries
        return result

    attr_bsms = _resolve_attr_filter(kg, spec.attr_filter)
    if not attr_bsms and spec.type == "attributive":
        attr_bsms = _all_parcel_bsms(kg)

    return CandidateSet(
        bsms=attr_bsms,
        ref_bsms=ref_ids,
        ref_geometry_wkt=ref_geometry_wkt,
        ref_geometries=ref_geometries,
    )


def _resolve_exact_reference_geometry(
    kg,
    spec: SpatialReferenceSpec,
    ref: RefObject,
    ref_ids: List[str],
) -> Optional[str]:
    """Backward-compatible singular source geometry lookup."""
    geometries = _resolve_exact_reference_geometries(kg, spec, ref, ref_ids)
    return geometries[0].wkt if len(geometries) == 1 else None


def _resolve_exact_reference_geometries(
    kg,
    spec: SpatialReferenceSpec,
    ref: RefObject,
    ref_ids: List[str],
) -> list[GeometryRef]:
    """Return full source geometry for one explicitly named KG feature.

    A unique result is not enough: an unconstrained entity-type query, a BSM,
    or a layer group still describes a candidate domain.  Only a named entity
    reference may cross the exact-feature boundary, and only through its
    authoritative ``geo:hasGeometry`` value.  Centroids and bounding boxes are
    intentionally excluded because they have different spatial semantics.
    """
    # Attributive/composed specs describe candidate domains, while
    # topological/distance references are relation anchors.  Promoting those
    # geometries would materialize the anchor as the target.  The current
    # contract has no exact-feature flag, so retain only the narrow directional
    # request shape with a uniquely and exactly named source feature.
    if spec.type != "directional":
        return []
    if ref.kind not in {"entity_type", "place_name"}:
        return []
    filters = ref.filter or {}
    label_contains = str(filters.get("label_contains") or "").strip()
    explicit_ids = filters.get("source_feature_ids") or filters.get("exact_feature_ids")
    explicit_id_list = (
        [str(item).strip() for item in explicit_ids if str(item).strip()]
        if isinstance(explicit_ids, (list, tuple, set))
        else []
    )
    if isinstance(explicit_ids, set):
        explicit_id_list = sorted(explicit_id_list)
    if explicit_ids is not None:
        if not isinstance(explicit_ids, (list, tuple, set)):
            return []
        requested = {str(item).strip() for item in explicit_ids if str(item).strip()}
        if not requested or requested != {str(item) for item in ref_ids}:
            return []
    elif len(ref_ids) > 1 and not bool(filters.get("allow_multiple_exact")):
        # A generic multi-match remains a recall domain.  It cannot cross the
        # exact-feature boundary without an explicit source-backed opt-in.
        return []
    if not label_contains and explicit_ids is None:
        return []

    entity_uris = list(_ids_to_uris(kg, ref_ids))
    if len(entity_uris) != len(set(entity_uris)) or len(entity_uris) != len(ref_ids):
        return []
    rdf_type = str(filters.get("rdf_type") or "").strip()
    expected_type = _RDF_TYPE_TO_PLN.get(rdf_type) if rdf_type else None
    records: list[GeometryRef] = []
    for index, entity_uri in enumerate(entity_uris):
        if expected_type is not None and (entity_uri, RDF.type, expected_type) not in kg.g:
            return []
        entity_name = str(kg.g.value(entity_uri, PLN.name) or "").strip()
        if label_contains and len(ref_ids) == 1 and entity_name != label_contains:
            return []
        if label_contains and len(ref_ids) > 1 and bool(filters.get("allow_multiple_exact")):
            # Explicit multi-feature mode still requires exact names; a
            # substring query such as “道路” remains candidate-only.
            if entity_name != label_contains:
                return []
        geometry_node = kg.g.value(entity_uri, GeoPredicates.hasGeometry)
        literal = kg.g.value(geometry_node, GeoPredicates.asWKT) if geometry_node is not None else None
        text = str(literal or "").strip()
        if not text:
            return []
        try:
            from shapely import wkt as shapely_wkt

            geometry = shapely_wkt.loads(text)
        except Exception:
            return []
        if geometry.is_empty or not geometry.is_valid:
            return []
        if geometry.geom_type not in {
            "Point", "MultiPoint", "LineString", "MultiLineString",
            "Polygon", "MultiPolygon",
        }:
            return []
        source_bsms = [
            str(value)
            for value in kg.g.objects(entity_uri, PLN.bsm)
            if str(value).strip()
        ]
        source_feature_id = (
            explicit_id_list[index]
            if explicit_id_list and index < len(explicit_id_list)
            else str(entity_uri)
        )
        records.append(
            GeometryRef(
                wkt=geometry.wkt,
                crs=str(filters.get("crs") or "EPSG:4326"),
                source_ref=source_feature_id,
                source_feature_id=(
                    explicit_id_list[index]
                    if explicit_id_list and index < len(explicit_id_list)
                    else ""
                ),
                source_refs=[source_feature_id, str(entity_uri)],
                source_bsms=source_bsms,
                feature_kind=str(filters.get("rdf_type") or ""),
            )
        )
    return records


def _resolve_reference(kg, ref: RefObject) -> List[str]:
    if ref.kind in {"entity_type", "place_name"}:
        filt = ref.filter or {}
        explicit_ids = filt.get("source_feature_ids") or filt.get("exact_feature_ids")
        if explicit_ids is not None:
            if not isinstance(explicit_ids, (list, tuple, set)):
                return []
            return [str(item).strip() for item in explicit_ids if str(item).strip()]
        rdf_type = filt.get("rdf_type", "")
        label_contains = filt.get("label_contains", "")
        if rdf_type and rdf_type in _RDF_TYPE_TO_PLN:
            return _entity_ids_by_type(kg, _RDF_TYPE_TO_PLN[rdf_type], label_contains)
        if label_contains:
            return _entity_ids_by_label(kg, label_contains)
        return []
    elif ref.kind == "layer_group":
        group = (ref.filter or {}).get("group", "")
        if group:
            return _layer_group_member_ids(kg, group)
        return []
    elif ref.kind == "bsm":
        bsm = (ref.filter or {}).get("bsm", "")
        return [bsm] if bsm else []
    elif ref.kind == "village":
        return []
    return []


def _resolve_topological(kg, spec: SpatialReferenceSpec, ref_ids: List[str]) -> CandidateSet:
    if not spec.topo or spec.topo not in _TOPO_PREDICATE:
        return CandidateSet(bsms=[], ref_bsms=ref_ids)
    pred = _TOPO_PREDICATE[spec.topo]
    result_ids: List[str] = []

    for ref_uri in _ids_to_uris(kg, ref_ids):
        for _, _, obj in kg.g.triples((ref_uri, pred, None)):
            vid = _uri_to_id(kg, obj)
            if vid:
                result_ids.append(vid)
        for subj, _, _ in kg.g.triples((None, pred, ref_uri)):
            vid = _uri_to_id(kg, subj)
            if vid:
                result_ids.append(vid)
    seen = set()
    dedup = []
    for vid in result_ids:
        if vid not in seen:
            seen.add(vid)
            dedup.append(vid)
    return CandidateSet(bsms=dedup, ref_bsms=ref_ids)


def _resolve_attr_filter(kg, attr_filter: Optional[Dict[str, Any]]) -> List[str]:
    if not attr_filter:
        return []
    dlbm_in = attr_filter.get("dlbm_in")
    if dlbm_in:
        values = " ".join(f'"{d}"' for d in dlbm_in)
        rows = kg.query(
            "PREFIX pln: <http://village-planning.org/ontology#> "
            f"SELECT ?bsm WHERE {{ ?p a pln:Parcel ; pln:bsm ?bsm ; pln:dlbm ?d . "
            f"FILTER(?d IN ({values})) }}"
        )
        return [r["bsm"] for r in rows if r.get("bsm")]
    return []


def _all_parcel_bsms(kg) -> List[str]:
    rows = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?bsm WHERE { ?p a pln:Parcel ; pln:bsm ?bsm . }"
    )
    return [r["bsm"] for r in rows if r.get("bsm")]


def _entity_ids_by_type(kg, rdf_type: URIRef, label_contains: str = "") -> List[str]:
    ids = []
    for s in kg.g.subjects(RDF.type, rdf_type):
        name = ""
        for _, _, o in kg.g.triples((s, PLN.name, None)):
            name = str(o)
            break
        if label_contains and label_contains not in name:
            continue
        ids.append(str(s))
    return ids


def _entity_ids_by_label(kg, label_contains: str) -> List[str]:
    ids = []
    for s in kg.g.subjects(None, None):
        for _, _, o in kg.g.triples((s, PLN.name, None)):
            if label_contains in str(o):
                ids.append(str(s))
                break
    return ids


def _layer_group_member_ids(kg, group: str) -> List[str]:
    lg_uri = PLN[f"GisLayerSet_{group}"]
    ids = []
    for _, _, member in kg.g.triples((lg_uri, PLN.contains_entity, None)):
        ids.append(str(member))
    return ids


def _ids_to_uris(kg, ids: List[str]):
    for eid in ids:
        if eid.startswith("http"):
            direct = URIRef(eid)
            if (direct, None, None) in kg.g:
                yield direct
                continue
            matched = next(
                kg.g.subjects(PLN.source_feature_id, Literal(eid)),
                None,
            )
            if matched is not None:
                yield matched
        elif eid.startswith("pln:"):
            yield URIRef(PLN_NS + eid[4:])
        else:
            for s, _, _ in kg.g.triples((None, PLN.bsm, Literal(eid))):
                yield s
                break


def _uri_to_id(kg, uri) -> Optional[str]:
    for _, _, o in kg.g.triples((uri, PLN.bsm, None)):
        return str(o)
    return str(uri)


__all__ = [
    "resolve_candidates",
    "_entity_ids_by_type",
    "_entity_ids_by_label",
    "_resolve_topological",
    "_ids_to_uris",
    "_uri_to_id",
]
