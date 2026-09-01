"""Deterministic closed-set candidates for arbitrary DATA schemas."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


_PROPERTY_ALIASES: dict[str, tuple[str, ...]] = {
    "dlbm": ("land_use_code", "planning_land_use_code"),
    "ghytbm": ("planned_land_use_code",),
    "name": ("canonical_name",),
    "label": ("canonical_name",),
    "road_name": ("canonical_name",),
    "road_ref": ("entity_ref",),
    "entity_id": ("entity_ref",),
    "physical_id": ("entity_ref",),
    "area": ("area",),
    "面积": ("area",),
    "roadname": ("canonical_name",),
    "watername": ("canonical_name",),
    "djzqmc": ("canonical_name",),
    "text": ("observed_label",),
    "category": ("concept_type",),
    "layer_type": ("source_classification",),
    "source_feature_id": ("source_identifier",),
    "source_uri": ("source_provenance",),
    "source_content_digest": ("source_provenance",),
    "filename": ("source_provenance",),
    "upload_filename": ("source_provenance",),
    "document_name": ("source_provenance",),
}

_SOURCE_METADATA_FIELDS = frozenset(
    {
        "filename",
        "upload_filename",
        "document_name",
        "source_dataset_ref",
        "source_feature_ref",
        "source_record_id",
        "source_uri",
        "source_digest",
        "content_ref",
        "content_digest",
        "resource_kind",
        "input_role",
        "admission_status",
        "admission_reason",
        "admission_signals",
        "parse_status",
        "parse_error",
        "layer_ref",
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fold(value: Any) -> str:
    return "".join(_text(value).casefold().replace("-", "_").split())


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def property_candidates(field_name: str, *, physical_type: str = "", samples: Sequence[Any] = ()) -> list[str]:
    """Return stable closed-set property IDs; never trusts a raw LLM ID."""

    key = _fold(field_name)
    candidates = list(_PROPERTY_ALIASES.get(key, ()))
    if key in _SOURCE_METADATA_FIELDS:
        if candidates:
            return sorted(set(candidates))[:12]
        if key.endswith(("_ref", "_id")) or key == "layer_ref":
            return ["source_identifier"]
        return []
    if not candidates:
        if any(token in key for token in ("name", "label", "名称", "注记")):
            candidates.append("canonical_name")
        if any(token in key for token in ("type", "class", "category", "用途", "类型")):
            candidates.append("concept_type")
        if any(token in key for token in ("id", "编号", "code", "编码", "ref")):
            candidates.append("source_identifier")
        if any(token in key for token in ("area", "面积", "mj")):
            candidates.append("area")
    # A numeric sample can support area only when the field name itself is an
    # area hint; values never override a conflicting semantic name.
    if not candidates and _fold(physical_type) in {"float", "double", "number", "numeric"}:
        if any(token in key for token in ("area", "面积", "mj")):
            candidates.append("area")
    return sorted(set(candidates))[:12]


def concept_candidates(*, layer_name: str = "", geometry_kind: str = "", attributes: Mapping[str, Any] | None = None) -> list[str]:
    """Infer only generic concepts; source-specific labels stay unresolved."""

    values = {str(value).casefold() for value in (attributes or {}).values() if value not in (None, "")}
    layer = _fold(layer_name)
    result: set[str] = set()
    if geometry_kind.casefold() in {"point", "multipoint"}:
        result.add("facility_candidate")
    elif geometry_kind.casefold() in {"line", "linestring", "multilinestring"}:
        result.add("linear_feature_candidate")
    elif geometry_kind.casefold() in {"polygon", "multipolygon", "multipatch"}:
        result.add("area_feature_candidate")
    if "road" in layer or "道路" in layer or any("road" in value or "道路" in value for value in values):
        result.add("road_candidate")
    if "water" in layer or "水" in layer or any("river" in value or "河" in value or "水" in value for value in values):
        result.add("water_candidate")
    return sorted(result)[:8]


def collection_concept_candidates(
    *,
    layer_name: str = "",
    geometry_kinds: Sequence[str] = (),
    field_names: Sequence[str] = (),
    sample_values: Sequence[Any] = (),
) -> list[str]:
    """Return a geometry-compatible closed concept vocabulary.

    Lexical material only changes candidate order; it never accepts a
    mapping.  Consequently an unseen layer remains classifiable by the LLM
    and can also safely abstain without a filename becoming business truth.
    """

    kinds = {_fold(value) for value in geometry_kinds if _text(value)}
    tokens = " ".join(
        _fold(value)
        for value in (layer_name, *field_names, *sample_values)
        if _text(value)
    )
    generic: list[str]
    if (
        kinds.intersection({"point", "multipoint"})
        and kinds.intersection({"polygon", "multipolygon", "multipatch"})
    ):
        generic = [
            "place",
            "facility",
            "area_feature",
            "place_observation",
            "place_extent",
        ]
    elif kinds.intersection({"point", "multipoint"}):
        generic = [
            "place_observation",
            "facility",
            "hazard_observation",
            "annotation",
        ]
    elif kinds.intersection({"line", "linestring", "multilinestring"}):
        generic = [
            "linear_feature",
            "road",
            "administrative_boundary",
            "watercourse",
            "contour_line",
        ]
    elif kinds.intersection({"polygon", "multipolygon", "multipatch"}):
        generic = [
            "area_feature",
            "land_area",
            "water_body",
            "administrative_area",
            "constraint_area",
            "place_extent",
        ]
    elif "raster" in kinds:
        generic = ["raster_dataset", "terrain_surface", "imagery_surface"]
    else:
        generic = ["document_evidence", "non_spatial_observation"]
    lexical: list[str] = []
    hints = (
        (("road", "道路", "路网", "公路"), "road"),
        (("water", "river", "河", "水系", "水域"), "water_body"),
        (("admin", "boundary", "行政", "边界", "界线"), "administrative_boundary"),
        (("farmland", "农田", "耕地", "红线", "保护"), "constraint_area"),
        (("hazard", "灾害", "隐患"), "hazard_observation"),
        (("annotation", "label", "注记", "标注"), "annotation"),
        (("dem", "elevation", "高程", "地形"), "terrain_surface"),
    )
    for needles, candidate in hints:
        if any(_fold(needle) in tokens for needle in needles) and candidate in generic:
            lexical.append(candidate)
    return list(dict.fromkeys([*lexical, *generic]))[:8]


def representation_role_candidates(geometry_kinds: Sequence[str]) -> list[str]:
    kinds = {_fold(value) for value in geometry_kinds if _text(value)}
    if kinds.intersection({"point", "multipoint"}):
        return ["locator", "label_anchor", "observation_point"]
    if kinds.intersection({"line", "linestring", "multilinestring"}):
        return ["centerline", "boundary", "network_edge"]
    if kinds.intersection({"polygon", "multipolygon", "multipatch"}):
        return [
            "physical_extent",
            "administrative_extent",
            "constraint_extent",
            "service_extent",
        ]
    if "raster" in kinds:
        return ["surface"]
    return []


def candidate_digest(candidates: Mapping[str, Sequence[str]]) -> str:
    return _digest({key: sorted(set(values)) for key, values in sorted(candidates.items())})


def validate_proposals(
    proposals: Sequence[Mapping[str, Any] | Any],
    candidate_membership: Mapping[tuple[str, str], Sequence[str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Verify LLM proposals against current collection/field candidate sets."""

    decisions: list[dict[str, Any]] = []
    findings: list[str] = []
    for raw in proposals:
        proposal = raw if isinstance(raw, Mapping) else getattr(raw, "model_dump", lambda: {})()
        collection_ref = _text(proposal.get("collection_ref"))
        field_name = _text(proposal.get("field_name"))
        key = (collection_ref, field_name)
        if key not in candidate_membership:
            findings.append(
                f"{collection_ref}:{field_name}:unexpected_proposal_key"
            )
            decisions.append({
                "collection_ref": collection_ref,
                "field_name": field_name,
                "candidate_property_ref": "",
                "candidate_concept_ref": "",
                "representation_role_ref": "",
                "status": "rejected",
                "confidence": 0.0,
                "candidate_refs": (),
                "reason": "proposal_key_outside_input_membership",
            })
            continue
        allowed = set(str(item) for item in candidate_membership.get(key, ()))
        property_ref = _text(proposal.get("candidate_property_ref"))
        concept_ref = _text(proposal.get("candidate_concept_ref"))
        role_ref = _text(proposal.get("representation_role_ref"))
        proposed = [value for value in (property_ref, concept_ref, role_ref) if value]
        unknown = [value for value in proposed if value not in allowed]
        confidence = float(proposal.get("confidence") or 0.0)
        target_mismatch = (
            (field_name == "__concept__" and bool(property_ref or role_ref))
            or (
                field_name.startswith("__representation__:")
                and bool(property_ref or concept_ref)
            )
            or (
                field_name not in {"__concept__"}
                and not field_name.startswith("__representation__:")
                and bool(concept_ref or role_ref)
            )
        )
        if target_mismatch or len(proposed) > 1:
            status, reason = "rejected", "proposal_target_kind_mismatch"
            findings.append(f"{collection_ref}:{field_name}:target_kind_mismatch")
        elif unknown:
            status, reason = "rejected", "proposal_outside_closed_candidate_set"
            findings.append(f"{collection_ref}:{field_name}:unknown_candidate")
        elif not proposed:
            status, reason = "unresolved", "model_abstained"
        elif len(allowed) > 1 and confidence < 0.8:
            status, reason = "ambiguous", "multiple_candidates_low_confidence"
        else:
            status, reason = "accepted", "verified_candidate_membership"
        decisions.append({
            "collection_ref": collection_ref,
            "field_name": field_name,
            "candidate_property_ref": property_ref if property_ref in allowed else "",
            "candidate_concept_ref": concept_ref if concept_ref in allowed else "",
            "representation_role_ref": role_ref if role_ref in allowed else "",
            "status": status,
            "confidence": max(0.0, min(confidence, 1.0)),
            "candidate_refs": tuple(sorted(allowed)),
            "reason": reason,
        })
    return decisions, findings


__all__ = [
    "candidate_digest",
    "collection_concept_candidates",
    "concept_candidates",
    "property_candidates",
    "representation_role_candidates",
    "validate_proposals",
]
