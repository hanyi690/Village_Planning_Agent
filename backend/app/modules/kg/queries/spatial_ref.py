"""KG-side candidate BSM resolution for spatial reference specs.

resolve_candidates takes a SpatialReferenceSpec (produced by PARSE via
instructor) and returns a CandidateSet of BSMs from the KG. This is the
"KG returns coarse-range BSM" half of the two-stage parse (KG candidates
-> spatial_ops precision). Does NOT perform geometric computation.

See docs/gis/integration/PARSE_SPATIAL_GROUNDING_DESIGN.md §3.1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdflib import Literal, RDF, URIRef

from app.utils.logger import get_logger
from ..ontology import PLN, PLN_NS, EntityTypes, Relations
from ...schema.contracts.spatial_ref_contracts import (
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
    ref_bsms: List[str] = []
    if spec.reference is not None:
        ref_bsms = _resolve_reference(kg, spec.reference)

    if spec.type == "topological":
        result = _resolve_topological(kg, spec, ref_bsms)
        return result

    attr_bsms = _resolve_attr_filter(kg, spec.attr_filter)
    if not attr_bsms and spec.type == "attributive":
        attr_bsms = _all_parcel_bsms(kg)

    return CandidateSet(bsms=attr_bsms, ref_bsms=ref_bsms)


def _resolve_reference(kg, ref: RefObject) -> List[str]:
    if ref.kind == "entity_type":
        filt = ref.filter or {}
        rdf_type = filt.get("rdf_type", "")
        label_contains = filt.get("label_contains", "")
        if rdf_type and rdf_type in _RDF_TYPE_TO_PLN:
            return _bsms_by_type(kg, _RDF_TYPE_TO_PLN[rdf_type], label_contains)
        if label_contains:
            return _bsms_by_label(kg, label_contains)
        return []
    elif ref.kind == "layer_group":
        group = (ref.filter or {}).get("group", "")
        if group:
            return _layer_group_member_bsms(kg, group)
        return []
    elif ref.kind == "bsm":
        bsm = (ref.filter or {}).get("bsm", "")
        return [bsm] if bsm else []
    elif ref.kind == "village":
        return []
    return []


def _resolve_topological(kg, spec: SpatialReferenceSpec, ref_bsms: List[str]) -> CandidateSet:
    if not spec.topo or spec.topo not in _TOPO_PREDICATE:
        return CandidateSet(bsms=[], ref_bsms=ref_bsms)
    pred = _TOPO_PREDICATE[spec.topo]
    result_bsms: List[str] = []

    for ref_uri in _bsms_to_uris(kg, ref_bsms):
        for _, _, obj in kg.g.triples((ref_uri, pred, None)):
            bsm = _uri_to_bsm(kg, obj)
            if bsm:
                result_bsms.append(bsm)
        for subj, _, _ in kg.g.triples((None, pred, ref_uri)):
            bsm = _uri_to_bsm(kg, subj)
            if bsm:
                result_bsms.append(bsm)
    seen = set()
    dedup = []
    for b in result_bsms:
        if b not in seen:
            seen.add(b)
            dedup.append(b)
    return CandidateSet(bsms=dedup, ref_bsms=ref_bsms)


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


def _bsms_by_type(kg, rdf_type: URIRef, label_contains: str = "") -> List[str]:
    bsms = []
    for s in kg.g.subjects(RDF.type, rdf_type):
        name = ""
        for _, _, o in kg.g.triples((s, PLN.name, None)):
            name = str(o)
            break
        if label_contains and label_contains not in name:
            continue
        for _, _, o in kg.g.triples((s, PLN.bsm, None)):
            bsms.append(str(o))
            break
        if not label_contains:
            for _, _, o in kg.g.triples((s, PLN.name, None)):
                break
    return bsms


def _bsms_by_label(kg, label_contains: str) -> List[str]:
    bsms = []
    for s in kg.g.subjects(None, None):
        for _, _, o in kg.g.triples((s, PLN.name, None)):
            if label_contains in str(o):
                for _, _, bsm in kg.g.triples((s, PLN.bsm, None)):
                    bsms.append(str(bsm))
                    break
                break
    return bsms


def _layer_group_member_bsms(kg, group: str) -> List[str]:
    lg_uri = PLN[f"GisLayerSet_{group}"]
    bsms = []
    for _, _, member in kg.g.triples((lg_uri, PLN.contains_entity, None)):
        for _, _, o in kg.g.triples((member, PLN.bsm, None)):
            bsms.append(str(o))
            break
    return bsms


def _bsms_to_uris(kg, bsms: List[str]):
    for bsm in bsms:
        for s, _, _ in kg.g.triples((None, PLN.bsm, Literal(bsm))):
            yield s


def _uri_to_bsm(kg, uri) -> Optional[str]:
    for _, _, o in kg.g.triples((uri, PLN.bsm, None)):
        return str(o)
    return None


__all__ = ["resolve_candidates"]