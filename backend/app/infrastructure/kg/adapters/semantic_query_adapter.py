"""KGSemanticQueryAdapter - KG-side implementation of the SemanticQueryPort.

Wraps a PlanningKG instance and exposes structured entity/relation queries
by reusing the private helpers from spatial_ref.py (KG-side candidate
resolution). Keeps the resolver decoupled from raw template-name callbacks.
"""
from __future__ import annotations

from typing import Any

from rdflib import Literal, RDF, URIRef

from app.contracts.ports.semantic_query import SemanticQueryPort
from app.infrastructure.kg.ontology import PLN
from app.infrastructure.kg.queries.spatial_ref import (
    _entity_ids_by_label,
    _entity_ids_by_type,
    _resolve_topological,
)


class KGSemanticQueryAdapter(SemanticQueryPort):
    def __init__(self, kg):
        self._kg = kg

    def query_entities(self, run_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        ids = _entity_ids_by_label(self._kg, query)
        result = []
        for eid in ids:
            info = self._entity_info(eid)
            if info:
                result.append(info)
            if len(result) >= limit:
                break
        return result

    def find_entities(self, run_id: str, name: str, entity_type: str | None = None) -> list[dict[str, Any]]:
        if entity_type:
            try:
                rdf_type = URIRef(entity_type)
            except Exception:
                rdf_type = None
            if rdf_type is not None:
                ids = _entity_ids_by_type(self._kg, rdf_type, name)
                matches = [self._entity_info(eid) for eid in ids]
                return [m for m in matches if m]
        return self.query_entities(run_id, name)

    def query_relations(self, run_id: str, entity_id: str, relation: str) -> list[dict[str, Any]]:
        from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec

        spec = SpatialReferenceSpec(type="topological", topo=relation)
        result = _resolve_topological(self._kg, spec, [entity_id])
        return [
            {"entity_ref": bsm, "bsm": bsm, "relation": relation}
            for bsm in result.bsms
        ]

    def get_constraints(self, run_id: str, scope: str) -> list[dict[str, Any]]:
        return []

    def resolve_ambiguous(self, run_id: str, name: str, candidates: list[str]) -> str | None:
        return None

    def _entity_info(self, eid: str) -> dict[str, Any] | None:
        kg = self._kg
        uri = None
        if eid.startswith("http"):
            uri = URIRef(eid)
        else:
            for s, _, _ in kg.g.triples((None, PLN.bsm, Literal(eid))):
                uri = s
                break
        if uri is None:
            return None
        name = ""
        for _, _, o in kg.g.triples((uri, PLN.name, None)):
            name = str(o)
            break
        entity_type = ""
        for _, _, o in kg.g.triples((uri, RDF.type, None)):
            entity_type = str(o)
            break
        bsm = ""
        for _, _, o in kg.g.triples((uri, PLN.bsm, None)):
            bsm = str(o)
            break
        aliases = _aliases(kg, uri)
        return {
            "entity_ref": str(uri),
            "name": name,
            "entity_type": entity_type,
            "bsm": bsm,
            "aliases": aliases,
        }


def _aliases(kg, uri: URIRef) -> list[str]:
    aliases = []
    for _, _, o in kg.g.triples((uri, PLN.name, None)):
        if str(o) not in aliases:
            aliases.append(str(o))
    return aliases