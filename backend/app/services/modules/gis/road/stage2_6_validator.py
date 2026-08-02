"""Structural contract validation for Stage-2.6 road preprocessing outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


SCHEMA_VERSION = "1.0"

REQUIRED_FILES = (
    "road_intents.json",
    "planning_kg_updates.json",
    "located_planning_entities.geojson",
    "planning_nodes.geojson",
    "road_planning_requests.json",
    "road_constraints.json",
    "spatial_quality_gates.json",
    "human_review_queue.json",
    "human_confirmation_template.json",
    "kg_retry_requests.json",
    "stage2_6_report.json",
)

REQUIRED_INTENT_FIELDS = (
    "intent_id",
    "task_type",
    "action",
    "start_place",
    "end_place",
    "mentioned_places",
    "served_objects",
    "constraints",
    "evidence_text",
    "source_chunk_id",
    "confidence",
    "requires_human_confirmation",
)

REQUIRED_ENTITY_FIELDS = (
    "entity_id",
    "name",
    "entity_type",
    "location_status",
    "confidence",
    "source",
    "candidate_count",
    "inside_village_boundary",
    "distance_to_current_road_m",
    "requires_human_confirmation",
    "source_chunk_ids",
    "evidence_texts",
)

REQUIRED_NODE_FIELDS = (
    "planning_node_id",
    "node_type",
    "source_entity_ids",
    "source_intent_ids",
    "service_weight",
    "priority",
    "road_service_status",
    "nearest_road_id",
    "distance_to_current_road_m",
    "recommended_action",
    "confidence",
    "requires_human_confirmation",
)

REQUIRED_REQUEST_FIELDS = (
    "request_id",
    "request_type",
    "priority",
    "start_node_id",
    "end_node_id",
    "served_node_ids",
    "related_intent_ids",
    "recommended_road_class",
    "recommended_width_m",
    "avoid_constraints",
    "allow_reuse_existing",
    "requires_human_confirmation",
    "reason",
)

REQUIRED_KG_TRIPLE_FIELDS = (
    "subject",
    "predicate",
    "object",
    "confidence",
)

KG_ENTITY_REFERENCE_PREDICATES = {"aggregates_entity"}
KG_BSM_REFERENCE_PREDICATES = {"candidate_bsm", "derived_from_bsm"}
KG_KNOWN_PREDICATES = {
    "has_action",
    "mentions_place",
    "has_location_status",
    "candidate_bsm",
    "aggregates_entity",
    "derived_from_bsm",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _features(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [feature for feature in payload.get("features") or [] if isinstance(feature, Mapping)]


def _props(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    return feature.get("properties") or {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _missing_fields(record: Mapping[str, Any], required: Sequence[str]) -> List[str]:
    return [field for field in required if field not in record]


def _require_fields(
    errors: List[str],
    label: str,
    record: Mapping[str, Any],
    required: Sequence[str],
) -> None:
    missing = _missing_fields(record, required)
    if missing:
        errors.append(f"{label} missing fields: {', '.join(missing)}")


def _pn_ref(value: Any) -> Optional[str]:
    text = str(value or "")
    return text if text.startswith("PN-") else None


def _ids(records: Iterable[Mapping[str, Any]], field: str) -> set[str]:
    return {str(record.get(field)) for record in records if str(record.get(field) or "").strip()}


def validate_stage2_6_outputs(output_dir: Path, *, raise_on_error: bool = True) -> Dict[str, Any]:
    """Validate Stage-2.6 artifact presence, required fields, and references."""

    output_dir = Path(output_dir)
    errors: List[str] = []
    warnings: List[str] = []
    payloads: Dict[str, Any] = {}
    for filename in REQUIRED_FILES:
        path = output_dir / filename
        if not path.exists():
            errors.append(f"missing required artifact: {filename}")
            continue
        try:
            payloads[filename] = _read_json(path)
        except json.JSONDecodeError as exc:
            errors.append(f"{filename} is not valid JSON: {exc}")

    if errors:
        report = _validation_report(output_dir, errors, warnings, payloads)
        if raise_on_error:
            raise ValueError("; ".join(errors))
        return report

    intents_payload = payloads["road_intents.json"]
    kg_updates_payload = payloads["planning_kg_updates.json"]
    located_payload = payloads["located_planning_entities.geojson"]
    nodes_payload = payloads["planning_nodes.geojson"]
    requests_payload = payloads["road_planning_requests.json"]
    constraints_payload = payloads["road_constraints.json"]
    gates_payload = payloads["spatial_quality_gates.json"]
    review_payload = payloads["human_review_queue.json"]
    template_payload = payloads["human_confirmation_template.json"]
    retry_payload = payloads["kg_retry_requests.json"]
    report_payload = payloads["stage2_6_report.json"]

    intents = [item for item in intents_payload.get("intents") or [] if isinstance(item, Mapping)]
    located = _features(located_payload)
    nodes = _features(nodes_payload)
    requests = [item for item in requests_payload.get("requests") or [] if isinstance(item, Mapping)]
    constraints = [item for item in constraints_payload.get("constraints") or [] if isinstance(item, Mapping)]
    gates = [item for item in gates_payload.get("nodes") or [] if isinstance(item, Mapping)]
    review_items = [item for item in review_payload.get("items") or [] if isinstance(item, Mapping)]
    template_items = [item for item in template_payload.get("confirmations") or [] if isinstance(item, Mapping)]
    retry_requests = [item for item in retry_payload.get("requests") or [] if isinstance(item, Mapping)]
    kg_triples = [item for item in kg_updates_payload.get("triples") or [] if isinstance(item, Mapping)]

    if kg_updates_payload.get("type") != "PlanningKnowledgeGraphUpdate":
        errors.append("planning_kg_updates has unexpected type")
    if str(kg_updates_payload.get("schema_version") or "") != SCHEMA_VERSION:
        errors.append("planning_kg_updates has unexpected schema_version")
    if int(kg_updates_payload.get("triple_count") or 0) != len(kg_triples):
        errors.append("planning_kg_updates triple_count does not match triples")

    for index, intent in enumerate(intents, start=1):
        _require_fields(errors, f"road_intents[{index}]", intent, REQUIRED_INTENT_FIELDS)
        if not str(intent.get("evidence_text") or "").strip():
            errors.append(f"road_intents[{index}] has no evidence_text")
        has_source_locator = bool(
            str(intent.get("source_chunk_id") or "").strip()
            or str(intent.get("section_title") or "").strip()
            or intent.get("source_page") is not None
        )
        if not has_source_locator:
            errors.append(f"road_intents[{index}] has no source chunk, section, or page")
        try:
            intent_confidence = float(intent.get("confidence"))
        except (TypeError, ValueError):
            errors.append(f"road_intents[{index}] has non-numeric confidence")
        else:
            if not 0 <= intent_confidence <= 1:
                errors.append(f"road_intents[{index}] confidence must be between 0 and 1")
    for index, feature in enumerate(located, start=1):
        _require_fields(errors, f"located_entities[{index}]", _props(feature), REQUIRED_ENTITY_FIELDS)
    for index, feature in enumerate(nodes, start=1):
        _require_fields(errors, f"planning_nodes[{index}]", _props(feature), REQUIRED_NODE_FIELDS)
        if feature.get("geometry") is None and str(_props(feature).get("node_type")) != "unresolved_node":
            errors.append(f"planning_nodes[{index}] has no geometry")
    for index, request in enumerate(requests, start=1):
        _require_fields(errors, f"road_planning_requests[{index}]", request, REQUIRED_REQUEST_FIELDS)

    intent_ids = _ids(intents, "intent_id")
    entity_ids = _ids((_props(feature) for feature in located), "entity_id")
    node_ids = _ids((_props(feature) for feature in nodes), "planning_node_id")
    request_ids = _ids(requests, "request_id")
    review_target_ids = _ids(review_items, "target_id")
    entity_bsm_ids = {
        str(bsm)
        for feature in located
        for bsm in _as_list(_props(feature).get("candidate_bsm_list"))
        if str(bsm or "").strip()
    }
    node_bsm_ids = {
        str(bsm)
        for feature in nodes
        for bsm in _as_list(_props(feature).get("source_bsm_list"))
        if str(bsm or "").strip()
    }
    bsm_ids = entity_bsm_ids | node_bsm_ids

    for index, triple in enumerate(kg_triples, start=1):
        _require_fields(errors, f"planning_kg_updates.triples[{index}]", triple, REQUIRED_KG_TRIPLE_FIELDS)
        predicate = str(triple.get("predicate") or "")
        subject = str(triple.get("subject") or "")
        object_value = str(triple.get("object") or "")
        if not subject:
            errors.append(f"planning_kg_updates.triples[{index}] has empty subject")
        if not predicate:
            errors.append(f"planning_kg_updates.triples[{index}] has empty predicate")
        if not object_value:
            errors.append(f"planning_kg_updates.triples[{index}] has empty object")
        try:
            confidence = float(triple.get("confidence"))
        except (TypeError, ValueError):
            errors.append(f"planning_kg_updates.triples[{index}] has non-numeric confidence")
        else:
            if not 0 <= confidence <= 1:
                errors.append(f"planning_kg_updates.triples[{index}] confidence must be between 0 and 1")
        if predicate not in KG_KNOWN_PREDICATES:
            warnings.append(f"planning_kg_updates.triples[{index}] uses extension predicate: {predicate}")
        if predicate in {"has_action", "mentions_place"} and subject not in intent_ids:
            errors.append(f"planning_kg_updates.triples[{index}] references unknown intent subject: {subject}")
        if predicate in {"has_location_status", "candidate_bsm"} and subject not in entity_ids:
            errors.append(f"planning_kg_updates.triples[{index}] references unknown entity subject: {subject}")
        if predicate in {"aggregates_entity", "derived_from_bsm"} and subject not in node_ids:
            errors.append(f"planning_kg_updates.triples[{index}] references unknown planning node subject: {subject}")
        if predicate in KG_ENTITY_REFERENCE_PREDICATES and object_value not in entity_ids:
            errors.append(f"planning_kg_updates.triples[{index}] references unknown entity object: {object_value}")
        if predicate in KG_BSM_REFERENCE_PREDICATES and object_value not in bsm_ids:
            errors.append(f"planning_kg_updates.triples[{index}] references unknown BSM object: {object_value}")

    for index, feature in enumerate(nodes, start=1):
        props = _props(feature)
        for entity_id in _as_list(props.get("source_entity_ids")):
            if str(entity_id) not in entity_ids:
                errors.append(f"planning_nodes[{index}] references unknown entity: {entity_id}")
        for intent_id in _as_list(props.get("source_intent_ids")):
            if str(intent_id) and str(intent_id) not in intent_ids:
                errors.append(f"planning_nodes[{index}] references unknown intent: {intent_id}")

    for index, request in enumerate(requests, start=1):
        start_ref = _pn_ref(request.get("start_node_id"))
        end_ref = _pn_ref(request.get("end_node_id"))
        if start_ref and start_ref not in node_ids:
            errors.append(f"road_planning_requests[{index}] references unknown start_node_id: {start_ref}")
        if end_ref and end_ref not in node_ids:
            errors.append(f"road_planning_requests[{index}] references unknown end_node_id: {end_ref}")
        for node_id in _as_list(request.get("served_node_ids")):
            if str(node_id) not in node_ids:
                errors.append(f"road_planning_requests[{index}] references unknown served_node_id: {node_id}")
        for intent_id in _as_list(request.get("related_intent_ids")):
            if str(intent_id) and str(intent_id) not in intent_ids:
                errors.append(f"road_planning_requests[{index}] references unknown intent: {intent_id}")

    for index, gate in enumerate(gates, start=1):
        node_id = str(gate.get("planning_node_id") or "")
        if node_id not in node_ids:
            errors.append(f"spatial_quality_gates[{index}] references unknown planning_node_id: {node_id}")
        gate_status = str(gate.get("gate_status") or "")
        if gate_status in {"needs_review", "needs_kg_retry", "blocked_constraint"} and not gate.get(
            "blocking_reasons"
        ):
            errors.append(f"spatial_quality_gates[{index}] has blocking gate_status without reasons")
        if gate_status in {"needs_review", "needs_kg_retry", "blocked_constraint"} and gate.get(
            "next_action"
        ) == "ready_for_stage3_stage4":
            errors.append(f"spatial_quality_gates[{index}] is blocked but next_action is ready")

    for index, item in enumerate(template_items, start=1):
        target_id = str(item.get("target_id") or "")
        if not target_id:
            errors.append(f"human_confirmation_template[{index}] missing target_id")
            continue
        if target_id not in review_target_ids and target_id not in entity_ids and target_id not in node_ids:
            errors.append(f"human_confirmation_template[{index}] references unknown target_id: {target_id}")
        status = str(item.get("confirmation_status") or "")
        if status != "pending":
            warnings.append(f"human_confirmation_template[{index}] is not pending: {status}")

    gate_allows = bool(gates_payload.get("automatic_route_generation_allowed"))
    review_count = int(review_payload.get("review_count") or 0)
    retry_count = int(retry_payload.get("request_count") or 0)
    if gate_allows and (review_count > 0 or retry_count > 0):
        errors.append("automatic route generation is allowed despite review or KG retry items")
    if int(report_payload.get("human_review_count") or 0) != review_count:
        errors.append("stage2_6_report human_review_count does not match human_review_queue")
    if int(report_payload.get("kg_retry_request_count") or 0) != retry_count:
        errors.append("stage2_6_report kg_retry_request_count does not match kg_retry_requests")
    if int(report_payload.get("road_planning_request_count") or 0) != len(requests):
        errors.append("stage2_6_report road_planning_request_count does not match request collection")
    derived_constraint_count = len(
        [
            item
            for item in constraints
            if item.get("derived_from") == "stage2_6_restricted_planning_entity"
        ]
    )
    if int(report_payload.get("stage2_6_derived_constraint_count") or 0) != derived_constraint_count:
        errors.append("stage2_6_report stage2_6_derived_constraint_count does not match road_constraints")
    if int(report_payload.get("human_confirmation_template_count") or 0) != len(template_items):
        errors.append("stage2_6_report human_confirmation_template_count does not match template")
    if int(report_payload.get("planning_kg_update_triple_count") or 0) != len(kg_triples):
        errors.append("stage2_6_report planning_kg_update_triple_count does not match planning_kg_updates")

    report = _validation_report(output_dir, errors, warnings, payloads)
    report["counts"] = {
        "road_intents": len(intents),
        "planning_kg_update_triples": len(kg_triples),
        "located_entities": len(located),
        "planning_nodes": len(nodes),
        "road_planning_requests": len(requests),
        "road_constraints": len(constraints),
        "stage2_6_derived_constraints": derived_constraint_count,
        "quality_gates": len(gates),
        "human_review_items": len(review_items),
        "human_confirmation_template_items": len(template_items),
        "kg_retry_requests": len(retry_requests),
    }
    if errors and raise_on_error:
        raise ValueError("; ".join(errors))
    return report


def _validation_report(
    output_dir: Path,
    errors: Sequence[str],
    warnings: Sequence[str],
    payloads: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "type": "RoadStage2_6OutputValidationReport",
        "schema_version": SCHEMA_VERSION,
        "output_dir": str(output_dir),
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": list(errors),
        "warnings": list(warnings),
        "checked_files": sorted(payloads),
    }


__all__ = ["validate_stage2_6_outputs"]
