"""RDFLib/PlanningKG adapter for Stage-2.6 spatial retry requests.

The road workflow speaks JSON.  The team KG already keeps entity names, BSM
identifiers, coordinates, and topology in RDFLib.  This adapter translates
only uniquely supported KG evidence into the retry-response contract; it never
selects an arbitrary parcel from multiple name matches.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Sequence

from rdflib import RDF


PLN_NS = "http://village-planning.org/ontology#"


def _normalise(value: Any) -> str:
    return re.sub(r"[\s_()\-/,.;:]+", "", str(value or "")).lower()


def _local_name(value: Any) -> str:
    text = str(value or "")
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _strings(values: Sequence[Any]) -> List[str]:
    return sorted({str(value) for value in values if str(value or "").strip()})


class RDFLibKGSpatialRetryAdapter:
    """Resolve Stage-2.6 retry targets against an in-memory RDFLib KG.

    ``kg`` can be a ``PlanningKG`` instance or a bare RDFLib ``Graph``.  The
    adapter returns raw response JSON accepted by ``normalise_kg_retry_response``.
    """

    def __init__(self, kg: Any, *, confirmed_confidence: float = 0.94) -> None:
        self.graph = getattr(kg, "g", kg)
        if not hasattr(self.graph, "predicate_objects"):
            raise TypeError("kg must be a PlanningKG or RDFLib Graph")
        if not 0 < confirmed_confidence <= 1:
            raise ValueError("confirmed_confidence must be in (0, 1]")
        self.confirmed_confidence = confirmed_confidence
        self._records = self._build_records()

    def __call__(self, retry_payload: Mapping[str, Any]) -> Dict[str, Any]:
        responses = [
            self._resolve_request(request)
            for request in retry_payload.get("requests") or []
            if isinstance(request, Mapping)
        ]
        return {
            "type": "RoadRDFLibKGRetryResponseCollection",
            "schema_version": "1.0",
            "source": "rdflib_kg",
            "responses": responses,
        }

    def _build_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        subjects = set(self.graph.subjects())
        for subject in subjects:
            attributes: Dict[str, List[str]] = defaultdict(list)
            types = []
            for predicate, obj in self.graph.predicate_objects(subject):
                if predicate == RDF.type:
                    types.append(_local_name(obj))
                else:
                    attributes[_local_name(predicate)].append(str(obj))
            names = _strings(
                [
                    *attributes.get("name", []),
                    *attributes.get("dlmc", []),
                    *attributes.get("label", []),
                ]
            )
            bsms = _strings(attributes.get("bsm", []))
            if not names and not bsms:
                continue
            records.append(
                {
                    "kg_entity_id": str(subject),
                    "names": names,
                    "bsms": bsms,
                    "attributes": attributes,
                    "types": _strings(types),
                }
            )
        return records

    def _resolve_request(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        query_input = request.get("query_input") or {}
        requested_bsms = _strings(query_input.get("candidate_bsm_list") or [])
        name = str(query_input.get("name") or request.get("name") or "")
        candidates = self._bsm_matches(requested_bsms) if requested_bsms else self._name_matches(name)
        base = {
            "retry_request_id": request.get("retry_request_id"),
            "target_id": request.get("target_id"),
            "name": name or request.get("target_id"),
            "source": "rdflib_kg",
        }
        if len(candidates) != 1:
            candidate_bsms = _strings([bsm for item in candidates for bsm in item["bsms"]])
            return {
                **base,
                "confirmation_status": "candidate" if candidates else "unresolved",
                "candidate_bsms": candidate_bsms,
                "confidence": 0.55 if candidates else 0.0,
                "reason": "multiple_kg_entity_matches" if candidates else "no_kg_entity_match",
            }

        record = candidates[0]
        response = {
            **base,
            "entity_id": record["kg_entity_id"],
            "kg_entity_id": record["kg_entity_id"],
            "spatial_context": self._spatial_context(record),
        }
        if record["bsms"]:
            return {
                **response,
                "confirmation_status": "confirmed",
                "bsm_list": record["bsms"],
                "confidence": self.confirmed_confidence,
            }
        point = self._point_geometry(record)
        if point is not None:
            return {
                **response,
                "confirmation_status": "confirmed",
                "geometry": point,
                "confidence": self.confirmed_confidence,
            }
        return {
            **response,
            "confirmation_status": "unresolved",
            "confidence": 0.0,
            "reason": "kg_entity_has_no_bsm_or_geometry",
        }

    def _bsm_matches(self, requested_bsms: Sequence[str]) -> List[Dict[str, Any]]:
        requested = set(requested_bsms)
        return [item for item in self._records if requested.intersection(item["bsms"])]

    def _name_matches(self, name: str) -> List[Dict[str, Any]]:
        key = _normalise(name)
        if not key:
            return []
        return [
            item
            for item in self._records
            if any(_normalise(candidate) == key for candidate in item["names"])
        ]

    @staticmethod
    def _point_geometry(record: Mapping[str, Any]) -> Dict[str, Any] | None:
        attributes = record["attributes"]
        try:
            lon = float((attributes.get("lon") or [None])[0])
            lat = float((attributes.get("lat") or [None])[0])
        except (TypeError, ValueError):
            return None
        return {"type": "Point", "coordinates": [lon, lat]}

    @staticmethod
    def _spatial_context(record: Mapping[str, Any]) -> Dict[str, Any]:
        attributes = record["attributes"]
        entity_type = (record["types"] or ["other"])[0].lower()
        context: Dict[str, Any] = {"entity_type": entity_type}
        for source, target in (
            ("current_zone_type", "planning_zone"),
            ("planning_zone", "planning_zone"),
            ("construction_permission", "construction_permission"),
        ):
            values = attributes.get(source) or []
            if values:
                context[target] = values[0]
        if attributes.get("connected_via_road") or attributes.get("via_road"):
            context["road_relation"] = "connected"
        return context


__all__ = ["RDFLibKGSpatialRetryAdapter"]
