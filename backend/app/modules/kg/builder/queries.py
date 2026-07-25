"""Semantic query methods for PlanningKG.

All functions are module-level and assigned to PlanningKG in base.py.
"""
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Literal, RDF, URIRef

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


def query(self, sparql: str) -> List[Dict[str, Any]]:
    try:
        results = self.g.query(sparql)
        rows = []
        for row in results:
            if hasattr(row, 'asdict'):
                rows.append({str(k): str(v) if v is not None else None for k, v in row.asdict().items()})
            elif isinstance(row, (tuple, list)):
                rd = {}
                if hasattr(results, 'vars'):
                    for i, var in enumerate(results.vars):
                        if i < len(row):
                            rd[str(var)] = str(row[i]) if row[i] is not None else None
                rows.append(rd)
        return rows
    except Exception as e:
        logger.error("SPARQL query failed: %s", e)
        return []


def get_constraints(self) -> List[Dict[str, Any]]:
    return self.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?id ?field ?op ?value ?source WHERE { "
        "?c a pln:Constraint ; pln:constraint_id ?id ; pln:field ?field ; "
        "pln:operator ?op ; pln:value ?value ; pln:source ?source . }"
    )


def get_adjacency_map(self) -> Dict[str, set]:
    adj: Dict[str, set] = {}
    prefix = str(PLN) + "parcel_"
    for s, _, o in self.g.triples((None, PLN.touches, None)):
        ks, ko = str(s), str(o)
        if ks.startswith(prefix) and ko.startswith(prefix):
            adj.setdefault(ks[len(prefix):], set()).add(ko[len(prefix):])
            adj.setdefault(ko[len(prefix):], set()).add(ks[len(prefix):])
    return adj


def get_parcel_count(self) -> int:
    return self._parcel_count


def get_triple_count(self) -> int:
    return len(self.g)


def serialize(self, filepath: str, fmt: str = "turtle"):
    self.g.serialize(destination=filepath, format=fmt)
    logger.info("Saved to %s (%s)", filepath, fmt)


def to_turtle(self) -> str:
    return self.g.serialize(format="turtle")


def from_turtle(cls, turtle_str: str, village_name: str = "") -> "PlanningKG":
    kg = cls(village_name=village_name)
    kg.g.parse(data=turtle_str, format="turtle")
    kg._parcel_count = len(list(kg.g.subjects(RDF.type, PLN.Parcel)))
    return kg


def get_parcels_within_distance_of_entity(self, entity_uri: str, max_distance_m: float) -> List[str]:
    entity = URIRef(entity_uri) if isinstance(entity_uri, str) else entity_uri
    bsms = set()
    for rel in (PLN.nearby, PLN.touches):
        for s, _, _ in self.g.triples((None, rel, entity)):
            for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
        for s, _, _ in self.g.triples((entity, rel, None)):
            for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
                bsms.add(str(bsm))
    return list(bsms)


def get_adjacent_parcels_with_length(self, bsm: str) -> List[Tuple[str, float]]:
    results = []
    for s, _, _ in self.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, PLN.Parcel) not in self.g:
            continue
        for _, _, neighbor in self.g.triples((s, PLN.touches, None)):
            for _, _, nbsm in self.g.triples((neighbor, PLN.bsm, None)):
                length = 0.0
                for _, _, lo in self.g.triples((s, PLN.shared_boundary_length, None)):
                    length = float(lo)
                results.append((str(nbsm), length))
    return results


def get_connected_parcels(self, parcel_uri: str, max_path_length: float = float("inf")) -> List[str]:
    """Return BSMs of parcels connected to parcel_uri via road network (L3)."""
    from rdflib import URIRef
    uri = URIRef(parcel_uri) if isinstance(parcel_uri, str) else parcel_uri
    bsms = set()
    for _, _, neighbor in self.g.triples((uri, PLN.connected_via_road, None)):
        for _, _, bsm in self.g.triples((neighbor, PLN.bsm, None)):
            bsms.add(str(bsm))
    for s, _, _ in self.g.triples((None, PLN.connected_via_road, uri)):
        for _, _, bsm in self.g.triples((s, PLN.bsm, None)):
            bsms.add(str(bsm))
    return list(bsms)


def validate_intent(self, intent: Any) -> List[Dict[str, Any]]:
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, FacilityTarget
    if not isinstance(intent, SpatialPlanningIntent):
        return []
    conflicts = []
    for ft in intent.facilities:
        if ft.semantic and ft.semantic.spatial_hint:
            for bsm in self.get_parcels_within_distance_of_entity(ft.semantic.spatial_hint, 500):
                if _is_in_protected_zone(self, bsm):
                    conflicts.append({"description": f"设施 {ft.type} 的候选地块 {bsm} 在保护区内",
                                      "severity": "high", "facility": ft.type, "bsm": bsm})
    return conflicts


def _is_in_protected_zone(self, bsm: str) -> bool:
    for s, _, _ in self.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, PLN.Parcel) not in self.g:
            continue
        for _, _, zone in self.g.triples((s, Relations.within_zone, None)):
            if (zone, RDF.type, PLN.ThreeLine) in self.g:
                return True
    return False
