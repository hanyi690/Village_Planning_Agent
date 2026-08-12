"""Deterministic semantic binding to immutable bundle geometry.

This module is a spatial-operation primitive.  It accepts plain instruction
mappings so it can be shared by Explore, PARSE and road-planning flows without
depending on an agent state implementation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

def _features(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        yield from (item for item in payload.get("features", []) if isinstance(item, dict))
    elif isinstance(payload, Mapping):
        for value in payload.values():
            yield from _features(value)


def _bsm(properties: Mapping[str, Any]) -> str:
    for key in ("BSM", "bsm", "Bsm", "parcel_bsm", "entity_bsm"):
        value = properties.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _context(properties: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if properties.get(key) not in (None, ""):
            return properties[key]
    return None


class DeterministicBundleBinder:
    """Bind by BSM first; never select an ambiguous candidate or mutate bundle."""

    def __init__(self, bundle: Any, kg_results: Optional[Mapping[str, Any]] = None):
        self.bundle = bundle
        raw = (
            bundle.to_delivery_inputs()
            if hasattr(bundle, "to_delivery_inputs")
            else bundle.to_geojson_dict()
            if hasattr(bundle, "to_geojson_dict")
            else bundle
        )
        self._bundle_payload = copy.deepcopy(raw or {})  # defensive: binding is read-only
        self.kg_results = dict(kg_results or {})
        self.by_bsm: Dict[str, Dict[str, Any]] = {}
        for feature in _features(self._bundle_payload):
            props = feature.get("properties") or {}
            value = _bsm(props)
            if value:
                self.by_bsm[value] = copy.deepcopy(feature)

    def bind(self, instructions: Any, gazetteer: Any = None) -> Dict[str, Any]:
        payload = instructions.model_dump() if hasattr(instructions, "model_dump") else dict(instructions)
        output: List[Dict[str, Any]] = []
        for record in payload.get("instructions", []):
            instruction = dict(record)
            source_bsms = list(dict.fromkeys(str(v) for v in instruction.get("candidate_bsm_list", []) if str(v)))
            matched = [self.by_bsm[bsm] for bsm in source_bsms if bsm in self.by_bsm]
            unresolved_bsms = [bsm for bsm in source_bsms if bsm not in self.by_bsm]
            status = "unresolved"
            geometry = None
            geometry_source = "none"
            confirmation = True
            if len(source_bsms) == 1 and len(matched) == 1:
                status, geometry, geometry_source, confirmation = "confirmed", copy.deepcopy(matched[0].get("geometry")), "bundle_bsm", False
            elif len(matched) > 1 or len(source_bsms) > 1:
                status, geometry_source = "candidate", "multiple_bsm_candidates"
            else:
                # A KG entity is usable only when the caller established it is unique.
                unique = (self.kg_results.get("unique_entities") or {}).get(instruction.get("instruction_id"))
                if isinstance(unique, Mapping) and unique.get("bsm") in self.by_bsm:
                    feature = self.by_bsm[str(unique["bsm"])]
                    status, geometry, geometry_source, confirmation = "confirmed", copy.deepcopy(feature.get("geometry")), "unique_kg_entity_bsm", False
                elif instruction.get("candidate_bbox"):
                    status, geometry_source = "candidate_bbox", "bbox_candidate"

            # A2 语义绑定：无 BSM 时，实体提及村名 → gazetteer（调用方注入）→ 候选 BSM 集
            if status == "unresolved" and not source_bsms:
                if gazetteer is not None and getattr(gazetteer, "entries", None):
                    for mention in (instruction.get("entity_mentions") or []):
                        entry = gazetteer.resolve(str(mention))
                        if entry is not None and entry.bsms:
                            source_bsms = list(entry.bsms)
                            matched = [self.by_bsm[b] for b in source_bsms if b in self.by_bsm]
                            status = "candidate_semantic"
                            geometry_source = "gazetteer"
                            confirmation = True
                            break
            reference = matched[0] if len(matched) == 1 else {}
            props = (reference.get("properties") or {}) if reference else {}
            output.append({
                "type": "Feature",
                "id": instruction.get("instruction_id"),
                "geometry": geometry,
                "properties": {
                    "entity_id": instruction.get("instruction_id"),
                    "name": (instruction.get("entity_mentions") or [instruction.get("instruction_id")])[0],
                    "binding_status": status,
                    "source_instruction_ids": [instruction.get("instruction_id")],
                    "source_chunk_ids": [instruction.get("source_chunk_id")],
                    "evidence_text": instruction.get("evidence_text", ""),
                    "source_bsm_list": source_bsms,
                    "unresolved_bsm_list": unresolved_bsms,
                    "geometry_source": geometry_source,
                    "geometry_type": (geometry or {}).get("type"),
                    "planning_zone": _context(props, ("planning_zone", "GHYTMC", "zone_name")),
                    "construction_permission": _context(props, ("construction_permission", "permission", "allowed_construction")),
                    "road_relation": _context(props, ("road_relation", "road_connectivity", "connected_via_road")),
                    "candidate_bbox": instruction.get("candidate_bbox"),
                    "domain": instruction.get("domain"),
                    "action": instruction.get("action"),
                    "confidence": instruction.get("confidence", 0.0),
                    "requires_human_confirmation": bool(instruction.get("requires_human_confirmation")) or confirmation,
                },
            })
        return {"type": "FeatureCollection", "name": "bound_spatial_entities", "features": output}


def bind_exploration_to_bundle(
    instructions: Any, bundle: Any, *, output_path: Optional[Path] = None,
    kg_results: Optional[Mapping[str, Any]] = None,
    gazetteer: Any = None,
) -> Dict[str, Any]:
    result = DeterministicBundleBinder(bundle, kg_results).bind(
        instructions, gazetteer=gazetteer
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
