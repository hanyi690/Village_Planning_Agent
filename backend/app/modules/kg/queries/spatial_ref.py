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

from app.utils.logger import get_logger
from ..ontology import PLN, PLN_NS, EntityTypes, Relations
from ...schema.contracts.spatial_reference_contracts import (
    CandidateSet, SpatialReferenceSpec, RefObject,
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
    if spec.reference is not None:
        ref_ids = _resolve_reference(kg, spec.reference)

    if spec.type == "topological":
        return _resolve_topological(kg, spec, ref_ids)

    attr_bsms = _resolve_attr_filter(kg, spec.attr_filter)
    if not attr_bsms and spec.type == "attributive":
        attr_bsms = _all_parcel_bsms(kg)

    return CandidateSet(bsms=attr_bsms, ref_bsms=ref_ids)


def _resolve_reference(kg, ref: RefObject) -> List[str]:
    if ref.kind in {"entity_type", "place_name"}:
        filt = ref.filter or {}
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
            yield URIRef(eid)
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
