"""KG retry-response validation for road spatial preprocessing.

Stage 2.6 writes ``kg_retry_requests.json`` when the spatial evaluator needs
additional KG help.  This module validates a KG adapter response and normalises
it into the same confirmation shape consumed by Stage 2.6.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


SCHEMA_VERSION = "1.0"
ALLOWED_STATUSES = {"confirmed", "candidate", "unresolved"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> List[str]:
    values: List[str] = []
    for item in _as_list(value):
        if isinstance(item, (list, tuple, set)):
            values.extend(_string_list(list(item)))
        elif str(item or "").strip():
            values.append(str(item))
    return sorted(set(values))


def _bbox_list(value: Any) -> Optional[List[float]]:
    raw = value
    if isinstance(value, Mapping):
        raw = value.get("bbox") or value.get("bounds")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        minx, miny, maxx, maxy = [float(item) for item in raw]
    except (TypeError, ValueError):
        return None
    if minx >= maxx or miny >= maxy:
        return None
    return [minx, miny, maxx, maxy]


def _records(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, Mapping) and payload.get("type") == "FeatureCollection":
        records = []
        for feature in payload.get("features") or []:
            if not isinstance(feature, Mapping):
                continue
            props = dict(feature.get("properties") or {})
            props["geometry"] = feature.get("geometry")
            records.append(props)
        return records
    if isinstance(payload, Mapping):
        raw = payload.get("responses") or payload.get("confirmations") or payload.get("items") or []
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    return []


def _request_index(payload: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("requests") or []:
        if not isinstance(item, Mapping):
            continue
        retry_id = str(item.get("retry_request_id") or "")
        target_id = str(item.get("target_id") or "")
        copied = dict(item)
        if retry_id:
            result[retry_id] = copied
        if target_id:
            result[target_id] = copied
    return result


def _geometry_valid(geometry: Any) -> bool:
    if not isinstance(geometry, Mapping):
        return False
    geometry_type = str(geometry.get("type") or "")
    if geometry_type not in {
        "Point",
        "LineString",
        "Polygon",
        "MultiPoint",
        "MultiLineString",
        "MultiPolygon",
    }:
        return False
    return "coordinates" in geometry


def _normalise_record(
    record: Mapping[str, Any],
    request_lookup: Mapping[str, Mapping[str, Any]],
    index: int,
) -> Tuple[Optional[Dict[str, Any]], List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    retry_id = str(record.get("retry_request_id") or record.get("request_id") or "")
    request = request_lookup.get(retry_id) or request_lookup.get(str(record.get("target_id") or "")) or {}
    target_id = str(record.get("target_id") or request.get("target_id") or "")
    if not target_id:
        errors.append(f"response[{index}] missing target_id")
        return None, errors, warnings

    status = str(record.get("confirmation_status") or record.get("status") or "candidate").lower()
    if status not in ALLOWED_STATUSES:
        errors.append(f"response[{index}] has unsupported confirmation_status: {status}")
        return None, errors, warnings

    try:
        confidence = float(record.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0 if status == "unresolved" else 0.5
        warnings.append(f"response[{index}] missing numeric confidence; defaulted to {confidence}")
    if not 0 <= confidence <= 1:
        errors.append(f"response[{index}] confidence must be between 0 and 1")
        return None, errors, warnings

    bsm_list = _string_list(
        record.get("bsm_list")
        or record.get("candidate_bsms")
        or record.get("source_bsms")
        or record.get("path_bsms")
        or record.get("bsm")
    )
    geometry = record.get("geometry")
    if geometry is not None and not _geometry_valid(geometry):
        errors.append(f"response[{index}] geometry is not valid GeoJSON geometry")
        return None, errors, warnings
    candidate_bbox = _bbox_list(record.get("candidate_bbox") or record.get("bbox") or record.get("bounds"))

    if status == "confirmed" and not bsm_list and geometry is None and candidate_bbox is not None:
        status = "candidate"
        warnings.append(f"response[{index}] downgraded to candidate because only bbox was returned")
    if status == "confirmed" and not bsm_list and geometry is None:
        errors.append(f"response[{index}] confirmed response must include bsm_list or geometry")
        return None, errors, warnings

    confirmation = {
        "target_id": target_id,
        "name": record.get("name") or request.get("name") or target_id,
        "entity_id": record.get("entity_id") or record.get("kg_entity_id"),
        "kg_entity_id": record.get("kg_entity_id") or record.get("entity_id"),
        "confirmation_status": status,
        "bsm_list": bsm_list,
        "geometry": geometry,
        "candidate_bbox": candidate_bbox,
        "confidence": confidence,
        "source": str(record.get("source") or "knowledge_graph"),
        "spatial_context": record.get("spatial_context") or {},
        "retry_request_id": retry_id or None,
        "normalised_from": "kg_retry_response",
    }
    return confirmation, errors, warnings


def normalise_kg_retry_response(
    response_path: Path,
    output_path: Path,
    retry_requests_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate a KG retry response and write Stage-2.6 confirmations."""

    response_payload = _read_json(response_path)
    request_lookup = _request_index(_read_json(retry_requests_path)) if retry_requests_path else {}
    confirmations: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []
    for index, record in enumerate(_records(response_payload), start=1):
        confirmation, item_errors, item_warnings = _normalise_record(record, request_lookup, index)
        errors.extend(item_errors)
        warnings.extend(item_warnings)
        if confirmation is not None:
            confirmations.append(confirmation)
    if errors:
        raise ValueError("; ".join(errors))

    payload = {
        "type": "RoadKGRetryConfirmationCollection",
        "schema_version": SCHEMA_VERSION,
        "confirmations": confirmations,
        "confirmation_count": len(confirmations),
        "warnings": warnings,
        "source_response_path": str(response_path),
        "source_retry_requests_path": str(retry_requests_path) if retry_requests_path else None,
    }
    _write_json(output_path, payload)
    return payload


def build_planning_nodes_with_kg_retry_response(
    config: Any,
    kg_retry_response_path: Optional[Path] = None,
) -> Any:
    """Run Stage 2.6 once, normalise KG response, then rerun with confirmations.

    The first pass writes to ``<output_dir>/kg_retry_round1`` so the final pass
    can keep the standard Stage-2.6 output directory shape used by Stage 3/4.
    """

    from .planning_nodes import build_planning_nodes

    if kg_retry_response_path is None:
        return build_planning_nodes(config)

    output_dir = Path(config.output_dir)
    round1_dir = output_dir / "kg_retry_round1"
    round1_config = replace(config, output_dir=round1_dir)
    round1_result = build_planning_nodes(round1_config)
    normalised_path = output_dir / "kg_retry_confirmations.normalized.json"
    normalised_payload = normalise_kg_retry_response(
        kg_retry_response_path,
        normalised_path,
        round1_result.kg_retry_requests_path,
    )
    final_config = replace(config, manual_confirmation_path=normalised_path)
    final_result = build_planning_nodes(final_config)
    loop_report = {
        "type": "RoadStage2_6KGRetryLoopReport",
        "schema_version": SCHEMA_VERSION,
        "round_count": 2,
        "round1_output_dir": str(round1_result.output_dir),
        "final_output_dir": str(final_result.output_dir),
        "kg_retry_response_path": str(kg_retry_response_path),
        "normalised_confirmation_path": str(normalised_path),
        "round1_retry_request_count": round1_result.report.get("kg_retry_request_count"),
        "normalised_confirmation_count": normalised_payload.get("confirmation_count"),
        "final_retry_queue_count": final_result.report.get("retry_queue_count"),
        "final_human_review_count": final_result.report.get("human_review_count"),
    }
    _write_json(output_dir / "kg_retry_loop_report.json", loop_report)
    return final_result


def _adapter_response_to_file(response: Any, output_path: Path) -> Path:
    if isinstance(response, (str, Path)):
        path = Path(response)
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    if isinstance(response, (Mapping, list)):
        _write_json(output_path, response)
        return output_path
    raise TypeError("KG retry adapter must return a path, mapping, or list response payload")


def build_planning_nodes_with_kg_retry_adapter(
    config: Any,
    adapter: Callable[[Dict[str, Any]], Any],
) -> Any:
    """Run Stage 2.6, call a KG adapter with retry requests, then rerun.

    Adapter signature:

    ``adapter(kg_retry_requests_payload) -> response_payload | response_path``
    """

    from .planning_nodes import build_planning_nodes

    output_dir = Path(config.output_dir)
    round1_dir = output_dir / "kg_retry_round1"
    round1_config = replace(config, output_dir=round1_dir)
    round1_result = build_planning_nodes(round1_config)
    retry_requests = _read_json(round1_result.kg_retry_requests_path)
    request_count = int(retry_requests.get("request_count") or 0)
    if request_count <= 0:
        final_result = build_planning_nodes(config)
        loop_report = {
            "type": "RoadStage2_6KGRetryLoopReport",
            "schema_version": SCHEMA_VERSION,
            "round_count": 2,
            "round1_output_dir": str(round1_result.output_dir),
            "final_output_dir": str(final_result.output_dir),
            "adapter_called": False,
            "round1_retry_request_count": 0,
            "normalised_confirmation_count": 0,
            "final_retry_queue_count": final_result.report.get("retry_queue_count"),
            "final_human_review_count": final_result.report.get("human_review_count"),
        }
        _write_json(output_dir / "kg_retry_loop_report.json", loop_report)
        return final_result

    adapter_payload = adapter(retry_requests)
    response_path = _adapter_response_to_file(
        adapter_payload,
        output_dir / "kg_retry_response.from_adapter.json",
    )
    normalised_path = output_dir / "kg_retry_confirmations.normalized.json"
    normalised_payload = normalise_kg_retry_response(
        response_path,
        normalised_path,
        round1_result.kg_retry_requests_path,
    )
    final_config = replace(config, manual_confirmation_path=normalised_path)
    final_result = build_planning_nodes(final_config)
    loop_report = {
        "type": "RoadStage2_6KGRetryLoopReport",
        "schema_version": SCHEMA_VERSION,
        "round_count": 2,
        "round1_output_dir": str(round1_result.output_dir),
        "final_output_dir": str(final_result.output_dir),
        "adapter_called": True,
        "adapter_response_path": str(response_path),
        "normalised_confirmation_path": str(normalised_path),
        "round1_retry_request_count": request_count,
        "normalised_confirmation_count": normalised_payload.get("confirmation_count"),
        "final_retry_queue_count": final_result.report.get("retry_queue_count"),
        "final_human_review_count": final_result.report.get("human_review_count"),
    }
    _write_json(output_dir / "kg_retry_loop_report.json", loop_report)
    return final_result


__all__ = [
    "build_planning_nodes_with_kg_retry_adapter",
    "build_planning_nodes_with_kg_retry_response",
    "normalise_kg_retry_response",
]
