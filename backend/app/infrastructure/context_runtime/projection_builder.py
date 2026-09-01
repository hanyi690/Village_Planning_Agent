"""Project cognition and the bounded analysis projection for Evidence contracts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
)
from app.contracts.evidence.evidence_packet_contracts import (
    EvidencePacket,
    SpatialRelationEvidence,
)
from app.contracts.evidence.feature_identity_contracts import FeatureEvidenceRef
from app.contracts.evidence.project_cognition_contracts import ProjectCognitionSnapshot
from app.contracts.evidence.requirement_contracts import EvidenceCoverage


_SOURCE_FAMILY_ALIASES = {
    "kg": "kg",
    "knowledge_graph": "kg",
    "kg_canonical_fact": "kg",
    "kg_relation": "kg",
    "kg_topology": "kg",
    "l1": "l1",
    "l1_fact": "l1",
    "l1_typed_fact": "l1",
    "l1_observation": "l1",
    "l1_semantic_context": "l1",
    "bundle": "bundle",
    "bundle_feature": "bundle",
    "bundle_feature_identity": "bundle",
    "bundle_parcel_identity": "bundle",
    "bundle_layer_stat": "bundle",
    "gis_layer": "bundle",
    "feature_identity": "bundle",
    "spatial": "bundle",
    "text": "text",
    "report": "text",
    "analysis_report": "text",
    "planning_text": "text",
    "professional_text": "text",
    "source_document": "text",
    "bundle_document": "text",
    "local_text": "text",
    "artifact": "artifact",
    "history": "text",
    "integrity": "text",
    "rag": "text",
    "external": "external",
    "external_search": "external",
    "external_claim": "external",
    "external_vector_corpus": "external",
    "external_anchor": "external",
    "web": "external",
    "api": "api",
}

_RAW_KEYS = {
    "body",
    "content",
    "evidence_span",
    "messages",
    "prompt",
    "provider_response",
    "query_trace",
    "raw",
    "raw_candidates",
    "raw_content",
    "retrieval_plan",
    "source_spans",
}

_DEFAULT_ANALYSIS_BUDGET = 48
_MAX_TEXT_LENGTH = 512
_MAX_NESTED_ITEMS = 32

_AUTHORITY_RANK = {
    "authoritative": 6,
    "authoritative_geometry": 6,
    "bundle_source": 5,
    "canonical": 5,
    "verified": 4,
    "kg": 4,
    "derived": 3,
    "needs_review": 2,
    "advisory": 1,
    "": 0,
}


def _context_data(value: Any) -> Any:
    """Read context data for the snapshot builder only."""

    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return value


def _context_get(value: Any, key: str, default: Any = None) -> Any:
    data = _context_data(value)
    if isinstance(data, Mapping) and key in data:
        return data[key]
    return getattr(value, key, default)


def _items(value: Sequence[Any] | set[Any] | Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) or isinstance(value, set):
        return list(value)
    return [value]


def _strings(values: Sequence[Any] | set[Any] | Any) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value).strip()
                for value in _items(values)
                if str(value).strip()
            }
        )
    )


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    """Keep JSON-safe metadata while removing retrieval-only content."""

    if depth > 3:
        return None
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item))[:_MAX_NESTED_ITEMS]:
            key_text = str(key)
            if key_text.casefold().replace(" ", "_") in _RAW_KEYS:
                continue
            item = _safe_value(value[key], depth=depth + 1)
            if item is not None:
                result[key_text] = item
        return result
    if isinstance(value, (list, tuple, set)):
        return [
            item
            for item in (_safe_value(item, depth=depth + 1) for item in list(value)[:_MAX_NESTED_ITEMS])
            if item is not None
        ]
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _safe_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _bound_projection(value: Any, *, key: str = "") -> Any:
    """Apply deterministic output bounds without altering identity references."""
    if isinstance(value, str):
        return value if key.endswith(("_id", "_ref", "_refs")) else value[:_MAX_TEXT_LENGTH]
    if isinstance(value, Mapping):
        return {
            str(item_key): _bound_projection(item_value, key=str(item_key).casefold())
            for item_key, item_value in list(value.items())[:_MAX_NESTED_ITEMS]
        }
    if isinstance(value, list):
        return [_bound_projection(item, key=key) for item in value[:_MAX_NESTED_ITEMS]]
    return value


def _hash_ref(prefix: str, value: Any, length: int = 20) -> str:
    digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:length]}"


def normalize_source_family(value: Any, default: str = "unknown") -> str:
    """Map one exact source kind/type to a source family."""

    normalized = str(value or "").strip().casefold().replace("-", "_")
    return _SOURCE_FAMILY_ALIASES.get(normalized, default) if normalized else default


def _source_family(*values: Any, default: str = "unknown") -> str:
    for value in values:
        family = normalize_source_family(value, default="unknown")
        if family != "unknown":
            return family
    return default


def _field(fields: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = fields.get(name, "")
        if str(value).strip():
            return str(value).strip()
    return ""


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _merge_refs(*values: Sequence[Any] | set[Any] | Any) -> list[str]:
    return list(_strings([item for value in values for item in _items(value)]))


def _project_fact(
    fact: EvidenceFact,
    *,
    source_by_ref: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    fields = dict(fact.fields)
    source_kind = str(fact.source_kind or fact.fact_type or "statement").strip()
    source_refs = _strings(fact.source_refs)
    source_rows = [source_by_ref[ref] for ref in source_refs if ref in source_by_ref]
    family = _source_family(
        fact.source_kind,
        fact.fact_type,
        *(row["source_type"] for row in source_rows),
    )
    evidence_refs = _merge_refs(fact.related_fact_refs, fields.get("evidence_refs", ""))
    locators = _strings(fact.source_locator)
    spatial_refs = _merge_refs(
        fact.spatial_refs,
        fact.feature_bsm,
        fact.related_parcel_bsms,
        _field(fields, "spatial_refs", "entity_refs"),
    )
    subject_ref = _field(fields, "subject_ref", "subject_scope") or fact.feature_bsm.strip()
    predicate = _field(fields, "predicate", "semantic_type", "fact_kind") or fact.fact_type
    value = _field(fields, "value") or fact.statement.strip()
    normalized_value = _field(fields, "normalized_value") or value
    scope = _safe_value(fields.get("scope", fields.get("spatial_scope", {})))
    valid_time = _safe_value(fields.get("valid_time", fields.get("temporal_scope", {})))
    qualifiers = _safe_value(fields.get("qualifiers", fields.get("qualifier", {})))
    scope = scope if isinstance(scope, Mapping) else ({"value": scope} if scope else {})
    valid_time = (
        valid_time
        if isinstance(valid_time, Mapping)
        else ({"value": valid_time} if valid_time else {})
    )
    qualifiers = (
        qualifiers
        if isinstance(qualifiers, Mapping)
        else ({"value": qualifiers} if qualifiers else {})
    )
    geometry_ref = _field(fields, "geometry_ref")
    snapshot_refs = _merge_refs(
        *(source_by_ref[ref]["snapshot_ref"] for ref in source_refs if ref in source_by_ref)
    )
    identity = {
        "subject_ref": subject_ref,
        "predicate": predicate,
        "normalized_value": normalized_value,
        "scope": scope,
        "valid_time": valid_time,
        "qualifiers": qualifiers,
    }
    conflict_identity = dict(identity)
    conflict_identity.pop("normalized_value")
    authority = max(
        (str(row["authority"]) for row in source_rows),
        key=lambda value: _AUTHORITY_RANK.get(value.casefold(), 0),
        default="",
    )
    if not authority:
        authority = "verified" if fact.status == "verified" else "advisory"
    attributes = _safe_value(
        {
            key: value
            for key, value in fields.items()
            if key
            not in {
                "evidence_refs",
                "fact_key",
                "geometry_ref",
                "normalized_value",
                "predicate",
                "qualifier",
                "qualifiers",
                "scope",
                "semantic_type",
                "spatial_refs",
                "spatial_scope",
                "subject_ref",
                "subject_scope",
                "temporal_scope",
                "valid_time",
                "value",
            }
        }
    )
    if not isinstance(attributes, Mapping):
        attributes = {}
    lineage_refs = _merge_refs(source_refs, evidence_refs, locators, snapshot_refs)
    projection = {
        "fact_id": _field(fields, "fact_id") or _hash_ref("fact", identity),
        "fact_key": _field(fields, "fact_key") or _hash_ref("fact-key", identity),
        "statement": fact.statement.strip(),
        "subject_ref": subject_ref,
        "predicate": predicate,
        "value": _safe_value(value),
        "normalized_value": _safe_value(normalized_value),
        "unit": _field(fields, "unit", "metric_unit"),
        "scope": dict(scope),
        "valid_time": dict(valid_time),
        "qualifiers": dict(qualifiers),
        "geometry_ref": geometry_ref,
        "entity_refs": spatial_refs,
        "source_families": [family],
        "source_kinds": [source_kind],
        "source_refs": list(source_refs),
        "evidence_refs": list(evidence_refs),
        "authority": authority,
        "locators": list(locators),
        "snapshot_refs": list(snapshot_refs),
        "conflict_group_id": "",
        "lineage_refs": lineage_refs,
        "attributes": dict(attributes),
        "confidence": _float(fact.confidence),
        "status": str(fact.status or "observed").strip(),
    }
    return projection, _canonical_json(identity), _canonical_json(conflict_identity)


def _candidate_identity(ref: FeatureEvidenceRef) -> dict[str, str]:
    return {
        "bsm": ref.identity.bundle_feature_bsm.strip(),
        "name": ref.identity.canonical_name.strip(),
        "entity_type": ref.identity.entity_type.strip(),
        "role": ref.identity.role.strip(),
        "source_layer": ref.identity.source_layer.strip(),
        "geometry_ref": str(ref.geometry_ref or "").strip(),
    }


def _project_candidate(ref: FeatureEvidenceRef, packet: EvidencePacket) -> tuple[dict[str, Any], str, str] | None:
    identity_data = _candidate_identity(ref)
    bsm = identity_data["bsm"]
    if not bsm:
        return None
    name = identity_data["name"] or identity_data["role"] or identity_data["entity_type"] or bsm
    source_refs = _merge_refs(f"bundle:feature:{bsm}", ref.provenance_refs)
    evidence_refs = _merge_refs(ref.relation_refs, ref.l1_fact_refs)
    snapshot_refs = _merge_refs(
        ref.identity.bundle_snapshot_digest,
        packet.bundle_snapshot_digest,
        ref.l1_snapshot_ref,
        packet.l1_snapshot_ref,
    )
    identity = {
        "subject_ref": bsm,
        "predicate": "feature_identity",
        "normalized_value": name,
        "scope": {},
        "valid_time": {},
        "qualifiers": {},
    }
    conflict_identity = dict(identity)
    conflict_identity.pop("normalized_value")
    projection = {
        "fact_id": f"bundle:feature:{bsm}",
        "fact_key": "bundle_feature_identity",
        "statement": f"{name} 的 bundle feature BSM 为 {bsm}",
        "subject_ref": bsm,
        "predicate": "feature_identity",
        "value": name,
        "normalized_value": name,
        "unit": "",
        "scope": {},
        "valid_time": {},
        "qualifiers": {},
        "geometry_ref": identity_data["geometry_ref"],
        "entity_refs": _merge_refs(ref.entity_refs, ref.related_parcel_bsms, bsm),
        "source_families": ["bundle"],
        "source_kinds": ["bundle_feature"],
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "authority": (
            "authoritative_geometry"
            if ref.geometry_authority in {"bundle", "data_resource_catalog"}
            else "advisory"
        ),
        "locators": [bsm],
        "snapshot_refs": snapshot_refs,
        "conflict_group_id": "",
        "lineage_refs": _merge_refs(source_refs, evidence_refs, [bsm], snapshot_refs),
        "attributes": {
            "canonical_name": ref.identity.canonical_name,
            "entity_type": ref.identity.entity_type,
            "role": ref.identity.role,
            "source_feature_id": ref.identity.source_feature_id,
            "source_layer": ref.identity.source_layer,
            "geometry_authority": ref.geometry_authority,
        },
        "confidence": _float(
            ref.selection_confidence
            if ref.selection_confidence is not None
            else ref.retrieval_score
        ),
        "status": "verified" if ref.identity.bsm_kind == "source" else "observed",
    }
    return projection, _canonical_json(identity), _canonical_json(conflict_identity)


def _project_relation(
    relation: SpatialRelationEvidence,
    packet: EvidencePacket,
) -> tuple[dict[str, Any], str, str] | None:
    subject = _candidate_identity(relation.subject)
    object_data = _candidate_identity(relation.object)
    if not subject["bsm"] or not object_data["bsm"]:
        return None
    relation_id = relation.relation_id.strip()
    predicate = relation.predicate.strip()
    source_refs = _strings(relation.provenance_refs)
    evidence_refs = _strings(relation_id)
    snapshot_refs = _merge_refs(packet.bundle_snapshot_digest, packet.l1_snapshot_ref)
    identity = {
        "subject_ref": subject["bsm"],
        "predicate": predicate,
        "normalized_value": object_data["bsm"],
        "scope": {"object_ref": object_data["bsm"]},
        "valid_time": {},
        "qualifiers": {},
    }
    conflict_identity = dict(identity)
    conflict_identity.pop("normalized_value")
    subject_name = subject["name"] or subject["bsm"]
    object_name = object_data["name"] or object_data["bsm"]
    projection = {
        "fact_id": relation_id or _hash_ref("kg:relation", identity),
        "fact_key": "spatial_relation",
        "statement": f"{subject_name} 与 {object_name} 存在空间关系 {predicate}",
        "subject_ref": subject["bsm"],
        "predicate": predicate,
        "value": object_data["bsm"],
        "normalized_value": object_data["bsm"],
        "unit": str(relation.metric_unit or "").strip(),
        "scope": {"object_ref": object_data["bsm"]},
        "valid_time": {},
        "qualifiers": {},
        "geometry_ref": subject["geometry_ref"],
        "entity_refs": _merge_refs(subject["bsm"], object_data["bsm"]),
        "source_families": ["kg"],
        "source_kinds": ["kg_relation"],
        "source_refs": list(source_refs),
        "evidence_refs": list(evidence_refs),
        "authority": "verified",
        "locators": list(evidence_refs),
        "snapshot_refs": snapshot_refs,
        "conflict_group_id": "",
        "lineage_refs": _merge_refs(source_refs, evidence_refs, snapshot_refs),
        "attributes": {
            "relation_id": relation.relation_id,
            "subject_bsm": subject["bsm"],
            "object_bsm": object_data["bsm"],
            "subject_geometry_ref": subject["geometry_ref"],
            "object_geometry_ref": object_data["geometry_ref"],
            "metric_value": relation.metric_value,
            "metric_unit": relation.metric_unit,
            "tolerance": relation.tolerance,
            "crs": relation.crs,
            "computation_method": relation.computation_method,
        },
        "confidence": 1.0,
        "status": "verified",
    }
    return projection, _canonical_json(identity), _canonical_json(conflict_identity)


def _project_source(source: EvidenceSource) -> dict[str, Any] | None:
    reference = source.reference.strip()
    if not reference:
        return None
    return {
        "source_family": normalize_source_family(source.source_type),
        "source_type": str(source.source_type)[:_MAX_TEXT_LENGTH],
        "reference": reference[:_MAX_TEXT_LENGTH],
        "confidence": _float(source.confidence, default=0.0),
        "evidence_role": str(source.evidence_role)[:_MAX_TEXT_LENGTH],
        "authority": str(source.authority)[:_MAX_TEXT_LENGTH],
        "availability": str(source.availability)[:_MAX_TEXT_LENGTH],
        "supports": list(_strings(source.supports)),
        "snapshot_ref": source.snapshot_ref,
    }


def _merge_fact(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = dict(left)
    for field in (
        "source_families",
        "source_kinds",
        "source_refs",
        "evidence_refs",
        "locators",
        "snapshot_refs",
        "lineage_refs",
        "entity_refs",
    ):
        result[field] = _merge_refs(left.get(field, []), right.get(field, []))
    left_authority = str(left.get("authority") or "")
    right_authority = str(right.get("authority") or "")
    if _AUTHORITY_RANK.get(right_authority.casefold(), 0) > _AUTHORITY_RANK.get(left_authority.casefold(), 0):
        result["authority"] = right_authority
    result["confidence"] = max(_float(left.get("confidence")), _float(right.get("confidence")))
    statuses = {str(left.get("status") or ""), str(right.get("status") or "")}
    result["status"] = "verified" if "verified" in statuses else sorted(statuses)[0]
    attributes = dict(left.get("attributes") or {})
    attributes.update(dict(right.get("attributes") or {}))
    result["attributes"] = attributes
    if len(str(right.get("statement") or "")) > len(str(result.get("statement") or "")):
        result["statement"] = right["statement"]
    if not result.get("geometry_ref") and right.get("geometry_ref"):
        result["geometry_ref"] = right["geometry_ref"]
    return result


def _unique_fact_ids(facts: list[tuple[dict[str, Any], str]]) -> list[dict[str, Any]]:
    used: set[str] = set()
    result: list[dict[str, Any]] = []
    for fact, semantic_key in facts:
        base = str(fact.get("fact_id") or _hash_ref("fact", semantic_key))
        fact_id = base
        ordinal = 0
        while fact_id in used:
            ordinal += 1
            fact_id = _hash_ref(
                "fact",
                {"base": base, "semantic": semantic_key, "ordinal": ordinal},
            )
        used.add(fact_id)
        fact["fact_id"] = fact_id
        result.append(fact)
    return result


def _project_coverage(coverage: EvidenceCoverage | None, packet: EvidencePacket | None) -> dict[str, Any]:
    if coverage is None:
        if packet is None:
            return {}
        return {
            "sufficiency": packet.sufficiency,
            "candidate_total": packet.candidate_total,
            "candidate_offset": packet.candidate_offset,
            "candidate_limit": packet.candidate_limit,
            "candidates_truncated": packet.candidates_truncated,
            "next_candidate_offset": packet.next_candidate_offset,
        }
    return {
        "run_id": coverage.run_id,
        "request_id": coverage.request_id,
        "requirement_set_fingerprint": coverage.requirement_set_fingerprint,
        "source_scope": coverage.source_scope,
        "source_families_queried": list(_strings(coverage.source_families_queried)),
        "unavailable_source_families": list(_strings(coverage.unavailable_source_families)),
        "unresolved_requirements": list(_strings(coverage.unresolved_requirements)),
        "conflict_refs": list(_strings(coverage.conflict_refs)),
        "stop_reason": coverage.stop_reason,
        "requirement_coverage": [
            {
                "requirement_id": row.requirement_id,
                "status": row.status,
                "claim_refs": list(_strings(row.claim_refs)),
                "source_families_covered": list(_strings(row.source_families_covered)),
                "locators_complete": row.locators_complete,
                "conflict_refs": list(_strings(row.conflict_refs)),
                "unresolved_reason": row.unresolved_reason,
            }
            for row in coverage.requirement_coverage
        ],
    }


def _project_gaps(coverage: EvidenceCoverage | None, packet: EvidencePacket | None) -> list[dict[str, str]]:
    values: list[tuple[str, str, str]] = []
    if coverage is not None:
        values.extend(
            (row.requirement_id, row.status, row.unresolved_reason)
            for row in coverage.requirement_coverage
            if row.status != "supported"
        )
        values.extend((requirement_id, "unresolved", "") for requirement_id in coverage.unresolved_requirements)
    if packet is not None:
        values.extend((missing, "unresolved", "") for missing in packet.missing_evidence)
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for gap_id, status, reason in values:
        normalized = str(gap_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        row = {"gap_id": normalized, "status": status}
        if reason:
            row["reason"] = reason
        result.append(row)
    return result


def _snapshot_rows(context: Any) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    context_data = _context_data(context)
    context_data = dict(context_data) if isinstance(context_data, Mapping) else {}
    data_snapshot = context_data.get("data_snapshot") or _context_get(context, "data_snapshot")
    snapshot_data = _context_data(data_snapshot)
    snapshot_data = dict(snapshot_data) if isinstance(snapshot_data, Mapping) else {}
    workspace = context_data.get("workspace") or _context_get(context, "workspace")
    workspace_snapshot = _context_data(_context_get(workspace, "snapshot"))
    workspace_snapshot = dict(workspace_snapshot) if isinstance(workspace_snapshot, Mapping) else {}
    digest = str(
        snapshot_data.get("digest")
        or workspace_snapshot.get("digest")
        or context_data.get("content_hash")
        or _context_get(context, "content_hash", "")
        or ""
    )
    snapshot_id = str(snapshot_data.get("snapshot_id") or workspace_snapshot.get("snapshot_id") or "")
    collections = []
    for item in _items(snapshot_data.get("collections") or workspace_snapshot.get("collections")):
        row = _context_data(item)
        row = dict(row) if isinstance(row, Mapping) else {}
        key = str(row.get("key") or row.get("collection_id") or "").strip()
        if key:
            collections.append(
                {
                    "key": key,
                    "feature_count": int(row.get("feature_count", 0) or 0),
                    "digest": str(row.get("digest") or ""),
                    "crs": str(row.get("crs") or "EPSG:4326"),
                    "source": str(row.get("source") or ""),
                }
            )
    collections.sort(key=lambda row: row["key"])
    return context_data, {"digest": digest, "snapshot_id": snapshot_id, "collections": collections}, digest, snapshot_id


def build_project_cognition(context: Any, scope: Any = None) -> ProjectCognitionSnapshot:
    """Build the immutable project snapshot used by evidence retrieval."""

    context_data, snapshot, data_digest, data_id = _snapshot_rows(context)
    workspace = context_data.get("workspace") or _context_get(context, "workspace")
    collections = snapshot["collections"]
    bundle_layers = [row["key"] for row in collections]
    feature_counts = {row["key"]: row["feature_count"] for row in collections}
    if not bundle_layers:
        for group_name in ("points", "lines", "polygons", "rasters", "tables"):
            group = _context_get(workspace, group_name, {}) or {}
            if hasattr(group, "keys"):
                bundle_layers.extend(f"{group_name}.{key}" for key in group.keys())
        bundle_layers = sorted(set(bundle_layers))

    kg = context_data.get("kg") or _context_get(context, "kg")
    graph = _context_get(kg, "g")
    kg_triple_count = 0
    kg_entity_types: set[str] = set()
    kg_relations: set[str] = set()
    if graph is not None:
        try:
            kg_triple_count = len(graph)
            for _, predicate, obj in graph:
                predicate_name = str(predicate).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                if predicate_name:
                    kg_relations.add(predicate_name)
                if predicate_name == "type":
                    entity_type = str(obj).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                    if entity_type:
                        kg_entity_types.add(entity_type)
        except Exception:
            kg_triple_count = 0

    l1_records = context_data.get("l1_fact_records") or _context_get(context, "l1_fact_records", []) or []
    fact_types = sorted(
        {
            str(_context_get(record, "fact_kind", "") or _context_get(record, "semantic_type", "")).strip()
            for record in l1_records
            if str(_context_get(record, "fact_kind", "") or _context_get(record, "semantic_type", "")).strip()
        }
    )
    snapshots = {
        "bundle": {"id": data_id or data_digest, "digest": data_digest, "collections": collections},
        "kg": {
            "id": str(context_data.get("kg_session_ref") or _context_get(context, "kg_session_ref", "") or ""),
            "version": str(context_data.get("kg_version") or _context_get(context, "kg_version", "") or ""),
            "triple_count": kg_triple_count,
        },
        "l1": {
            "id": str(context_data.get("l1_snapshot_ref") or _context_get(context, "l1_snapshot_ref", "") or ""),
            "fact_count": len(l1_records),
        },
    }
    scope_data = _safe_value(_context_data(scope) or {})
    scope_data = dict(scope_data) if isinstance(scope_data, Mapping) else {}
    spatial_scope = scope_data.get("spatial_scope")
    if not isinstance(spatial_scope, Mapping):
        spatial_scope = {
            key: value
            for key, value in scope_data.items()
            if key in {"spatial_ref", "bbox", "geometry_ref", "entity_scope", "crs", "village_name"}
        }
    time_scope = scope_data.get("time_scope")
    if not isinstance(time_scope, Mapping):
        time_scope = {
            key: value
            for key, value in scope_data.items()
            if key in {"time", "planning_period", "valid_time", "temporal_scope"}
        }
    quality = _safe_value(_context_get(context, "quality", {}) or {})
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    available = {
        "bundle_layers": tuple(sorted(set(bundle_layers))),
        "bundle_feature_counts": feature_counts,
        "fact_types": tuple(fact_types),
        "kg_entity_types": tuple(sorted(kg_entity_types)),
        "kg_relations": tuple(sorted(kg_relations)),
        "source_families": ("bundle", "kg", "l1", "text", "external"),
    }
    payload = {
        "project_ref": str(context_data.get("village_name") or _context_get(context, "village_name", "") or ""),
        "session_id": str(context_data.get("session_id") or _context_get(context, "session_id", "") or ""),
        "revision": str(context_data.get("version") or _context_get(context, "version", "") or ""),
        "spatial_scope": spatial_scope,
        "time_scope": time_scope,
        "snapshots": snapshots,
        "available_data": available,
        "quality": quality,
    }
    digest = "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return ProjectCognitionSnapshot(
        project_ref=payload["project_ref"],
        session_id=payload["session_id"],
        revision=payload["revision"],
        spatial_scope=dict(spatial_scope),
        time_scope=dict(time_scope),
        snapshots=snapshots,
        available_data=available,
        quality=quality,
        cognition_digest=digest,
    )


def render_analysis_evidence(
    result: ExplorationResult,
    budget: int | None = None,
    *,
    include_packet_spatial: bool = True,
) -> dict[str, Any]:
    """Render only safe projections from a real ``ExplorationResult``."""

    if not isinstance(result, ExplorationResult):
        raise TypeError("render_analysis_evidence requires an ExplorationResult")
    limit = _DEFAULT_ANALYSIS_BUDGET if budget is None else budget
    if limit < 0:
        raise ValueError("budget must be non-negative")
    bundle: EvidenceBundle = result.evidence_bundle
    packet: EvidencePacket | None = result.evidence_packet
    coverage: EvidenceCoverage | None = result.coverage
    projected_sources = [
        projected
        for source in bundle.sources
        if (projected := _project_source(source)) is not None
    ]
    source_by_ref = {row["reference"]: row for row in projected_sources}
    raw_facts: list[tuple[dict[str, Any], str, str]] = [
        _project_fact(fact, source_by_ref=source_by_ref) for fact in bundle.facts
    ]
    if packet is not None and include_packet_spatial:
        for candidate in packet.candidate_refs:
            projected = _project_candidate(candidate, packet)
            if projected is not None:
                raw_facts.append(projected)
        for relation in packet.relation_evidence:
            projected = _project_relation(relation, packet)
            if projected is not None:
                raw_facts.append(projected)

    facts_by_semantic: dict[str, dict[str, Any]] = {}
    conflict_members: dict[str, set[str]] = defaultdict(set)
    for fact, semantic_key, conflict_key in raw_facts:
        if semantic_key in facts_by_semantic:
            facts_by_semantic[semantic_key] = _merge_fact(facts_by_semantic[semantic_key], fact)
        else:
            facts_by_semantic[semantic_key] = fact
        conflict_members[conflict_key].add(semantic_key)

    conflict_ids = {
        conflict_key: _hash_ref("conflict", conflict_key, 16)
        for conflict_key, members in conflict_members.items()
        if len(members) > 1
    }
    ordered_facts: list[tuple[dict[str, Any], str]] = []
    for semantic_key in sorted(facts_by_semantic):
        fact = dict(facts_by_semantic[semantic_key])
        conflict_key = next(
            key for key, members in conflict_members.items() if semantic_key in members
        )
        if conflict_key in conflict_ids:
            fact["conflict_group_id"] = conflict_ids[conflict_key]
            fact["status"] = "conflict"
        ordered_facts.append((fact, semantic_key))
    total_fact_count = len(ordered_facts)
    facts = _unique_fact_ids(ordered_facts)
    facts = facts[:limit]

    facts_by_group: dict[str, list[str]] = defaultdict(list)
    for fact in facts:
        group_id = str(fact.get("conflict_group_id") or "")
        if group_id:
            facts_by_group[group_id].append(str(fact["fact_id"]))
    conflicts = [
        {
            "relation": "conflicts",
            "conflict_group_id": group_id,
            "fact_refs": list(_strings(refs)),
            "reason": "multiple variants share one semantic identity",
        }
        for group_id, refs in sorted(facts_by_group.items())
        if len(refs) > 1
    ]
    for conflict in bundle.conflicts:
        refs = list(_strings(conflict.fact_refs))
        if refs:
            conflicts.append(
                {
                    "relation": conflict.relation,
                    "fact_refs": refs,
                    "reason": conflict.reason,
                }
            )

    sources: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str]] = set()

    def append_source(row: dict[str, Any]) -> None:
        key = (str(row["source_family"]), str(row["reference"]))
        if key not in seen_sources:
            seen_sources.add(key)
            sources.append(row)

    for row in projected_sources:
        append_source(row)
    for fact in facts:
        family = str((fact.get("source_families") or ["unknown"])[0])
        for reference in fact.get("source_refs") or []:
            append_source(
                {
                    "source_family": family,
                    "source_type": family,
                    "reference": reference,
                    "confidence": fact["confidence"],
                    "evidence_role": "context",
                    "authority": fact["authority"],
                    "availability": "available",
                    "supports": [fact["fact_id"]],
                    "snapshot_ref": (fact.get("snapshot_refs") or [""])[0],
                }
            )
    if packet is not None:
        for reference in packet.external_refs:
            reference = reference.strip()
            if reference:
                append_source(
                    {
                        "source_family": "external",
                        "source_type": "external",
                        "reference": reference,
                        "confidence": 0.0,
                        "evidence_role": "external_reference",
                        "authority": "advisory",
                        "availability": "available",
                        "supports": [],
                        "snapshot_ref": "",
                    }
                )

    sources = sources[:limit]
    conflicts = conflicts[:limit]
    coverage_projection = _project_coverage(coverage, packet)
    rows = coverage_projection.get("requirement_coverage")
    if isinstance(rows, list):
        coverage_projection["requirement_coverage"] = rows[:limit]
    gap = _project_gaps(coverage, packet)[:limit]
    if total_fact_count > len(facts):
        coverage_projection.update(
            {
                "projection_status": "over_budget",
                "total_fact_count": total_fact_count,
                "next_fact_offset": len(facts),
            }
        )
    return _bound_projection({
        "facts": facts,
        "sources": sources,
        "conflicts": conflicts,
        "coverage": coverage_projection,
        "gap": gap,
    })


_PROMPT_REFERENCE_LIMIT = 4
_PROMPT_REFERENCE_CHARS = 96
_PROMPT_MAP_LIMIT = 4
_PROMPT_ATTRIBUTE_LIMIT = 4


def _prompt_text(value: Any, limit: int = 180) -> str:
    return str(value or "").strip()[:limit]


def _prompt_refs(value: Any) -> list[str]:
    return [
        _prompt_text(item, _PROMPT_REFERENCE_CHARS)
        for item in list(_strings(_items(value)))[:_PROMPT_REFERENCE_LIMIT]
    ]


def _prompt_value(value: Any, *, limit: int = 160) -> Any:
    if isinstance(value, Mapping):
        return _prompt_map(value)
    if isinstance(value, (list, tuple, set)):
        return [_prompt_value(item, limit=limit) for item in list(value)[:6]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _prompt_text(value, limit)


def _prompt_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    excluded = {"bbox", "geometry", "geometry_ref", "coordinates", "wkt"}
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:_PROMPT_MAP_LIMIT]:
        key = str(raw_key).strip()
        if not key or key.casefold() in excluded:
            continue
        result[key[:80]] = _prompt_value(raw_value, limit=120)
    return result


def _prompt_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    priority = (
        "metric",
        "metric_value",
        "metric_unit",
        "entity_type",
        "canonical_name",
        "role",
        "source_feature_id",
        "source_layer",
    )
    keys = [key for key in priority if key in value]
    keys.extend(
        key for key in value
        if key not in keys
    )
    return {
        str(key)[:80]: _prompt_value(value[key], limit=120)
        for key in keys[:_PROMPT_ATTRIBUTE_LIMIT]
    }


def _prompt_fact(raw: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "fact_id": _prompt_text(raw.get("fact_id"), 220),
        "statement": _prompt_text(raw.get("statement"), 240),
        "subject_ref": _prompt_text(raw.get("subject_ref"), 96),
        "predicate": _prompt_text(raw.get("predicate"), 80),
        "value": _prompt_value(raw.get("value"), limit=100),
        "normalized_value": _prompt_value(raw.get("normalized_value"), limit=100),
        "unit": _prompt_text(raw.get("unit"), 48),
        "scope": _prompt_map(raw.get("scope")),
        "entity_refs": _prompt_refs(raw.get("entity_refs")),
        "source_families": _prompt_refs(raw.get("source_families")),
        "source_refs": _prompt_refs(raw.get("source_refs")),
        "evidence_refs": _prompt_refs(raw.get("evidence_refs")),
        "authority": _prompt_text(raw.get("authority"), 64),
        "conflict_group_id": _prompt_text(raw.get("conflict_group_id"), 120),
        "attributes": _prompt_attributes(raw.get("attributes")),
        "confidence": raw.get("confidence"),
        "status": _prompt_text(raw.get("status"), 64),
    }
    return {
        key: value
        for key, value in result.items()
        if value not in (None, "", [], {})
    }


def render_analysis_evidence_for_prompt(
    result: ExplorationResult,
    *,
    budget: int = 16,
    include_packet_spatial: bool = False,
) -> dict[str, Any]:
    """Render the small evidence view allowed into an analysis prompt.

    ``render_analysis_evidence`` is also used by audit/API projections and
    therefore retains useful lineage metadata.  Analysis models need the
    semantic fact and its references, not a second copy of every source row,
    packet counter, or retrieval diagnostic.  This projection keeps the same
    fact identities and coverage status while removing geometry references,
    raw spans, and duplicate source detail before prompt assembly.  Source
    identity stays on each fact; the source table is intentionally omitted.
    """

    if budget <= 0:
        raise ValueError("budget must be positive")
    projected = render_analysis_evidence(
        result,
        budget=budget,
        include_packet_spatial=include_packet_spatial,
    )

    facts = [
        _prompt_fact(raw)
        for raw in projected.get("facts", [])
        if isinstance(raw, Mapping)
    ]

    # Facts carry the source family and stable source references.  Repeating
    # the full source table here adds no reasoning value and was the largest
    # avoidable part of the old analysis context.
    sources: list[dict[str, Any]] = []
    referenced_source_count = len({
        reference
        for fact in facts
        for reference in fact.get("source_refs", [])
    })

    coverage = projected.get("coverage")
    compact_coverage: dict[str, Any] = {}
    if isinstance(coverage, Mapping):
        for key in (
            "sufficiency",
            "source_scope",
            "source_families_queried",
            "unavailable_source_families",
            "unresolved_requirements",
            "conflict_refs",
            "stop_reason",
            "projection_status",
            "total_fact_count",
            "next_fact_offset",
        ):
            if key in coverage:
                value = coverage[key]
                if key in {
                    "source_families_queried",
                    "unavailable_source_families",
                    "unresolved_requirements",
                    "conflict_refs",
                }:
                    compact_coverage[key] = _prompt_refs(value)
                elif key in {
                    "source_scope",
                    "stop_reason",
                    "projection_status",
                }:
                    compact_coverage[key] = _prompt_text(value, 180)
                else:
                    compact_coverage[key] = value
        rows = coverage.get("requirement_coverage")
        if isinstance(rows, list):
            compact_coverage["requirement_coverage"] = [
                {
                    "requirement_id": _prompt_text(row.get("requirement_id"), 160),
                    "status": _prompt_text(row.get("status"), 64),
                    "claim_refs": _prompt_refs(row.get("claim_refs")),
                    "source_families_covered": _prompt_refs(
                        row.get("source_families_covered")
                    ),
                    "locators_complete": bool(row.get("locators_complete")),
                    "unresolved_reason": _prompt_text(
                        row.get("unresolved_reason"),
                        180,
                    ),
                }
                for row in rows[:budget]
                if isinstance(row, Mapping)
            ]

    return _bound_projection({
        "facts": facts,
        "sources": sources,
        "coverage": compact_coverage,
        "gap": [
            {
                "gap_id": _prompt_text(row.get("gap_id"), 160),
                "status": _prompt_text(row.get("status"), 64),
                **(
                    {"reason": _prompt_text(row.get("reason"), 180)}
                    if isinstance(row, Mapping) and row.get("reason")
                    else {}
                ),
            }
            for row in projected.get("gap", [])[:budget]
            if isinstance(row, Mapping)
        ],
        "projection": {
            "fact_budget": budget,
            "fact_count": len(facts),
            "source_count": referenced_source_count,
            "raw_retrieval_content": "excluded",
            "geometry_payload": "excluded",
        },
    })


__all__ = [
    "build_project_cognition",
    "normalize_source_family",
    "render_analysis_evidence",
    "render_analysis_evidence_for_prompt",
]
