"""Audited source-collection bindings for existing planning features.

Numeric quantities are descriptive evidence only.  They never prove that a
planning target refers to a GIS feature set.  Identity requires either an
explicit member-ID subset or an explicit source collection key and a single
source snapshot.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from app.contracts.evidence.identity_contracts import SourceFeatureSetBinding


_SOURCE_GROUP_BY_TARGET_TYPE = {
    "公交站": "公交站",
    "公交站点": "公交站",
    "公交站亭": "公交站",
    "文化展示设施": "祠堂",
    "文化活动中心": "祠堂",
    "祠堂": "祠堂",
}


def _requirements(intervention: Any) -> dict[str, Any]:
    return dict(getattr(intervention, "spatial_requirements", {}) or {})


def _typed_action(intervention: Any) -> str:
    params = getattr(intervention, "facility_parameters", None)
    if getattr(intervention, "category", "") in {"road", "axis"}:
        params = (
            getattr(intervention, "road_parameters", None)
            or getattr(intervention, "axis_parameters", None)
            or getattr(intervention, "linear_parameters", None)
        )
    return str(
        getattr(intervention, "intervention_action", "")
        or getattr(params, "action", "")
        or ""
    ).strip().lower()


def _operation(intervention: Any) -> str:
    action = _typed_action(intervention)
    if action in {"preserve", "upgrade", "repair", "widen", "harden"}:
        return "harden" if action == "upgrade" else action
    # A new facility may still be explicitly placed from an existing
    # facility/landmark anchor (for example, a planned cultural-service point
    # located at an L1-identified ancestral hall).  ``reference`` records that
    # the source feature is an anchor only; EXECUTE still creates a new
    # planned feature and never mutates or reuses the current feature.
    if (
        action == "new"
        and getattr(intervention, "category", "") == "facility"
        and _requirements(intervention).get("source_fact_refs")
    ):
        return "reference"
    return "reference" if action == "reference" else ""


def _feature_identity(feature: Any) -> tuple[str, str, str, str]:
    raw = getattr(feature, "_raw", {}) or {}
    source_id = str(raw.get("source_feature_id") or "").strip()
    snapshot = str(
        raw.get("source_snapshot_ref")
        or raw.get("source_content_digest")
        or ""
    ).strip()
    dataset = str(raw.get("source_dataset") or raw.get("source_uri") or "").strip()
    geometry = getattr(feature, "geometry", None)
    geometry_type = (
        str(geometry.get("type") or "")
        if isinstance(geometry, dict)
        else ""
    )
    return source_id, snapshot, dataset, geometry_type


def _accepted_semantic_type(
    feature: Any,
    semantic_decisions: Mapping[str, Any] | None = None,
) -> str:
    """Read only a current exact label or an explicitly accepted overlay."""
    raw = getattr(feature, "_raw", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    source_id = str(raw.get("source_feature_id") or "").strip()
    decision = (semantic_decisions or {}).get(source_id)
    if decision is not None:
        status = str(
            getattr(decision, "status", "")
            or (decision.get("status", "") if isinstance(decision, dict) else "")
        ).strip()
        if status == "accepted":
            return str(
                getattr(decision, "semantic_type", "")
                or (decision.get("semantic_type", "") if isinstance(decision, dict) else "")
            ).strip()
    return str(raw.get("source_label") or raw.get("text") or getattr(feature, "text", "") or "").strip()


def _explicit_ids(intervention: Any) -> list[str] | None:
    requirements = _requirements(intervention)
    for key in ("source_feature_ids", "existing_road_feature_ids", "road_feature_ids"):
        if key not in requirements:
            continue
        value = requirements.get(key)
        if not isinstance(value, (list, tuple, set)):
            return []
        return list(dict.fromkeys(
            str(item).strip() for item in value if str(item).strip()
        ))
    return None


def _source_collection_key(intervention: Any, default: str) -> str:
    value = _requirements(intervention).get("source_collection_key")
    return str(value or default).strip()


def _source_fact_refs(
    intervention: Any,
    *,
    collection_key: str,
    snapshot: str,
) -> list[str]:
    raw = _requirements(intervention).get("source_fact_refs")
    if isinstance(raw, (list, tuple, set)):
        refs = [str(item).strip() for item in raw if str(item).strip()]
        if refs:
            return list(dict.fromkeys(refs))
    # This is a source-collection citation, not a fabricated business count.
    return [f"bundle:collection:{collection_key}:{snapshot}"]


def _build_binding(
    intervention: Any,
    source_features: Sequence[Any],
    *,
    collection_key: str,
    expected_geometry: set[str],
    semantic_group: str = "",
    semantic_decisions: Mapping[str, Any] | None = None,
) -> SourceFeatureSetBinding | None:
    operation = _operation(intervention)
    if not operation:
        return None

    valid: dict[str, tuple[Any, str]] = {}
    for feature in source_features:
        source_id, snapshot, _dataset, geometry_type = _feature_identity(feature)
        if not source_id or not snapshot or geometry_type not in expected_geometry:
            continue
        if semantic_group:
            if _accepted_semantic_type(feature, semantic_decisions) != semantic_group:
                continue
        valid.setdefault(source_id, (feature, snapshot))
    if not valid:
        return None

    required_fact_refs = {
        str(item).strip()
        for item in (_requirements(intervention).get("source_fact_refs") or [])
        if str(item).strip()
    }
    if required_fact_refs:
        fact_bound: dict[str, tuple[Any, str]] = {}
        for source_id, item in valid.items():
            decision = (semantic_decisions or {}).get(source_id)
            if decision is None:
                continue
            status = str(
                getattr(decision, "status", "")
                or (decision.get("status", "") if isinstance(decision, dict) else "")
            ).strip()
            if status != "accepted":
                continue
            supporting_refs = getattr(decision, "supporting_fact_refs", None)
            if supporting_refs is None and isinstance(decision, dict):
                supporting_refs = decision.get("supporting_fact_refs")
            if required_fact_refs.intersection(
                str(ref).strip() for ref in (supporting_refs or [])
            ):
                fact_bound[source_id] = item
        valid = fact_bound
        if not valid:
            return None

    requested = _explicit_ids(intervention)
    if requested is not None:
        if not requested or any(item not in valid for item in requested):
            return None
        member_ids = requested
        binding_mode = "explicit_subset"
    else:
        declared_collection = str(
            _requirements(intervention).get("source_collection_key") or ""
        ).strip()
        # A broad existing-asset binding must name its collection.  In
        # particular, a quantity such as “275 roads” cannot select 131 lines.
        if declared_collection != collection_key and not required_fact_refs:
            return None
        member_ids = sorted(valid)
        binding_mode = (
            "semantic_fact_subset" if required_fact_refs else "all_in_scope"
        )

    snapshots = {
        valid[source_id][1]
        for source_id in member_ids
    }
    if len(snapshots) != 1:
        return None
    snapshot = next(iter(snapshots))
    requirements = _requirements(intervention)
    raw_membership = str(requirements.get("membership") or "required").strip()
    if raw_membership not in {"required", "alternative", "eligible_subset"}:
        return None
    digest_payload = "|".join([collection_key, snapshot, *sorted(member_ids)])
    source_feature_digest = hashlib.sha256(
        digest_payload.encode("utf-8")
    ).hexdigest()
    binding_seed = {
        "target_id": str(getattr(intervention, "target_id", "") or ""),
        "collection": collection_key,
        "snapshot": snapshot,
        "ids": sorted(member_ids),
        "operation": operation,
    }
    binding_id = "source-binding:" + hashlib.sha256(
        json.dumps(binding_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    semantic_refs = requirements.get("source_semantic_decision_refs") or []
    if not isinstance(semantic_refs, (list, tuple, set)):
        semantic_refs = []
    return SourceFeatureSetBinding(
        binding_id=binding_id,
        target_id=str(getattr(intervention, "target_id", "") or ""),
        source_collection_key=collection_key,
        source_snapshot_ref=snapshot,
        source_feature_digest=source_feature_digest,
        source_feature_ids=member_ids,
        binding_mode=binding_mode,
        membership=raw_membership,
        operation=operation,
        source_fact_refs=_source_fact_refs(
            intervention,
            collection_key=collection_key,
            snapshot=snapshot,
        ),
        source_semantic_decision_refs=[str(item) for item in semantic_refs],
    )


def build_existing_facility_source_binding(
    intervention: Any,
    source_features: Sequence[Any] = (),
    semantic_decisions: Mapping[str, Any] | None = None,
) -> SourceFeatureSetBinding | None:
    if getattr(intervention, "category", "") != "facility":
        return None
    params = getattr(intervention, "facility_parameters", None)
    expected_group = _SOURCE_GROUP_BY_TARGET_TYPE.get(
        str(getattr(params, "facility_type", "") or "").strip()
    )
    # Generic planned facility types (for example, 公共文化服务设施) may be
    # anchored by a typed L1 fact whose accepted source decision already
    # identifies the concrete current Point.  Do not require that the
    # planning type itself appear in the current annotation label; without a
    # source fact, the generic type remains unresolved and must not bind every
    # facility point in the bundle.
    has_fact_scope = bool(_requirements(intervention).get("source_fact_refs"))
    if not expected_group and not has_fact_scope:
        return None
    return _build_binding(
        intervention,
        source_features,
        collection_key=_source_collection_key(intervention, "current_facility"),
        expected_geometry={"Point", "MultiPoint"},
        semantic_group=expected_group or "",
        semantic_decisions=semantic_decisions,
    )


def build_existing_road_source_binding(
    intervention: Any,
    source_features: Sequence[Any] = (),
    semantic_decisions: Mapping[str, Any] | None = None,
) -> SourceFeatureSetBinding | None:
    if getattr(intervention, "category", "") not in {"road", "axis"}:
        return None
    return _build_binding(
        intervention,
        source_features,
        collection_key=_source_collection_key(intervention, "current_road"),
        expected_geometry={"LineString", "MultiLineString"},
        semantic_decisions=semantic_decisions,
    )


def bind_existing_facility_source_features(
    intervention: Any,
    source_features: Sequence[Any] = (),
    semantic_decisions: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return IDs from an explicit facility subset or named collection only."""
    binding = build_existing_facility_source_binding(
        intervention, source_features, semantic_decisions
    )
    return list(binding.source_feature_ids) if binding is not None else []


def bind_existing_road_source_features(
    intervention: Any,
    source_features: Sequence[Any] = (),
    semantic_decisions: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return IDs without using quantity equality as an identity gate."""
    binding = build_existing_road_source_binding(
        intervention, source_features, semantic_decisions
    )
    return list(binding.source_feature_ids) if binding is not None else []


__all__ = [
    "build_existing_facility_source_binding",
    "build_existing_road_source_binding",
    "bind_existing_facility_source_features",
    "bind_existing_road_source_features",
]
