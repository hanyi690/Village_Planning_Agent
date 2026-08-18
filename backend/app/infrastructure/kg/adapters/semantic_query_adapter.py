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
        from app.infrastructure.kg.ontology import SemanticPredicates

        entities = self.query_entities(run_id, scope, limit=50)
        rows: list[dict[str, Any]] = []
        for entity in entities:
            entity_ref = str(entity.get("entity_ref", "") or "")
            if not entity_ref:
                continue
            uri = URIRef(entity_ref)
            values: list[dict[str, str]] = []
            for predicate, kind in (
                (SemanticPredicates.legal_constraint, "legal_constraint"),
                (SemanticPredicates.allowed_operations, "allowed_operation"),
            ):
                for value in self._kg.g.objects(uri, predicate):
                    values.append({"kind": kind, "value": str(value)})
            if values:
                rows.append({"entity_ref": entity_ref, "constraints": values})
        return rows

    def resolve_ambiguous(self, run_id: str, name: str, candidates: list[str]) -> str | None:
        normalized = str(name or "").strip().lower()
        if not normalized or not candidates:
            return None
        scored: list[tuple[int, str]] = []
        for candidate in candidates:
            info = self._entity_info(str(candidate))
            if info is None:
                continue
            labels = [str(info.get("name", "") or "").strip().lower()]
            labels.extend(str(alias).strip().lower() for alias in info.get("aliases", []) or [])
            score = 0
            for label in labels:
                if label and label == normalized:
                    score = max(score, 3)
                elif label and (label in normalized or normalized in label):
                    score = max(score, 1)
            if score:
                scored.append((score, str(candidate)))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]

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
