"""PlanningKG - RDF knowledge graph data container + query methods.

Construction logic lives in KGBuilder (composition pattern).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from rdflib import Graph, Literal, RDF, URIRef
from rdflib.namespace import XSD

from ..ontology import PLN, GEO, EntityTypes, Relations, SemanticPredicates
from ..memory import SemanticMemoryStore


@dataclass
class KGInputParcels:
    """Container for typed parcels consumed by KG builder."""
    parcels: List[Any] = field(default_factory=list)


class PlanningKG:
    """RDF knowledge graph data container. No build logic."""

    def __init__(self, village_name: str = ""):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.g.bind("geo", GEO)
        self.village_name = village_name
        self._parcel_count = 0
        self._constraint_index = None
        self.memory = SemanticMemoryStore()

    def _reset_graph(self, constraint_index=None):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.g.bind("geo", GEO)
        self._parcel_count = 0
        self._constraint_index = constraint_index

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
        except Exception:
            return []

    def get_parcel_count(self) -> int:
        return self._parcel_count

    def get_triple_count(self) -> int:
        return len(self.g)

    def to_turtle(self) -> str:
        return self.g.serialize(format="turtle")

    @classmethod
    def from_turtle(cls, turtle_str: str, village_name: str = "") -> "PlanningKG":
        kg = cls(village_name=village_name)
        kg.g.parse(data=turtle_str, format="turtle")
        kg._parcel_count = len(list(kg.g.subjects(RDF.type, EntityTypes.Parcel)))
        return kg

    def get_adjacency_map(self) -> Dict[str, set]:
        adj: Dict[str, set] = {}
        for s, _, o in self.g.triples((None, Relations.sfTouches, None)):
            bsm_s = None
            bsm_o = None
            for _, _, lit in self.g.triples((s, PLN.bsm, None)):
                bsm_s = str(lit)
            for _, _, lit in self.g.triples((o, PLN.bsm, None)):
                bsm_o = str(lit)
            if bsm_s and bsm_o:
                adj.setdefault(bsm_s, set()).add(bsm_o)
                adj.setdefault(bsm_o, set()).add(bsm_s)
        return adj

    def get_constraints(self) -> list:
        constraints = []
        for s in self.g.subjects(RDF.type, EntityTypes.Zone):
            item = {}
            for p, o in self.g.predicate_objects(s):
                pn = str(p).split("#")[-1] if "#" in str(p) else str(p).split("/")[-1]
                item[pn] = str(o)
            if item:
                constraints.append(item)
        return constraints

    def clone_static_layer(self) -> "PlanningKG":
        new_kg = PlanningKG(village_name=self.village_name)
        new_kg.g = Graph()
        new_kg.g.bind("pln", PLN)
        new_kg.g.bind("geo", GEO)
        new_kg._constraint_index = self._constraint_index

        l1_subjects = set()
        for t in EntityTypes.l1_static():
            for s in self.g.subjects(RDF.type, t):
                l1_subjects.add(s)
        l1_subjects.add(PLN.village)

        clone_predicates = Relations.spatial() | SemanticPredicates.cognition_predicates()

        for s, p, o in self.g.triples((None, None, None)):
            if s in l1_subjects or p in clone_predicates:
                new_kg.g.add((s, p, o))
        new_kg._parcel_count = self._parcel_count
        return new_kg

    def print_summary(self):
        print(f"\n=== Planning KG Summary ===")
        print(f"  Parcels: {self._parcel_count}")
        print(f"  Total triples: {len(self.g)}")