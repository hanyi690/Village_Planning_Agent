# backend/app/agent/explore/retrievers/bundle_retriever.py
"""Bundle retriever - bounded feature identity plus layer statistics."""
from __future__ import annotations

import hashlib
from typing import List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.infrastructure.llm.tools.access.shared import resolve_bundle, group_stats
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "bundle-v3"

_SCOPE_TO_GROUPS = {
    "parcels": ["landuse_current", "current_landuse"],
    "facilities": ["facilities_current", "annotations_current", "facility"],
    "hazards": ["geological_hazard_points", "hazards", "disaster"],
    "roads": ["roads_current", "current_road", "external_roads", "transport"],
    "waters": ["water_current", "water", "water_bodies", "water_lines"],
    "annotations": ["annotations_current", "annotations_planned"],
}

_FEATURE_LIMIT = 12


def _is_external_group(group_name: str) -> bool:
    return str(group_name or "").startswith("external_") or group_name == "water_lines"


def _feature_labels(feature: object) -> list[str]:
    """Return source + advisory semantic labels without changing attributes."""
    values: list[str] = []
    for attr in (
        "text", "facility_name", "name", "road_name", "water_name", "label",
        "category", "dlmc", "dlbm", "zone_type", "planning_zone", "primary_zone",
        "primary_code", "ghytmc", "ghytbm", "ghflbm",
    ):
        value = getattr(feature, attr, "")
        if value:
            values.append(str(value).strip())
    dlbm = str(getattr(feature, "dlbm", "") or "").strip()
    if dlbm:
        try:
            from app.data.catalog.advisory_crosswalks import (
                dlbm_to_planning_zone,
                get_zone_type_for_dlbm,
            )

            values.extend([get_zone_type_for_dlbm(dlbm), dlbm_to_planning_zone(dlbm)])
        except Exception:
            pass
        try:
            from app.data.encodings.code_sets import DLBM_TO_DLMC

            values.append(str(DLBM_TO_DLMC.get(dlbm, "") or ""))
        except Exception:
            pass
    return list(dict.fromkeys(value.casefold() for value in values if value))


def _query_matches_feature(feature: object, query: str) -> bool:
    """Match a bounded query against source and land-use semantic labels."""
    text = str(query or "").strip().casefold()
    if not text:
        return True
    labels = _feature_labels(feature)
    return any(label in text or text in label for label in labels)


def _source_feature_id(feature: object) -> str:
    raw = getattr(feature, "_raw", {}) or {}
    if isinstance(raw, dict):
        return str(raw.get("source_feature_id") or "").strip()
    return ""


def _bundle_source_metadata(bundle: object, geometry_kind: str, group_name: str) -> dict[str, str]:
    """Return collection identity without exposing geometry in EvidenceFact."""
    snapshot = ""
    try:
        snapshot = str(bundle.spatial_snapshot_digest() or "").strip()
    except Exception:
        snapshot = ""
    container = getattr(bundle, geometry_kind, None)
    features = container.get(group_name) if container is not None and hasattr(container, "get") else []
    source_ids = sorted(
        value for value in (_source_feature_id(feature) for feature in list(features or [])) if value
    )
    digest = ""
    if source_ids:
        digest = hashlib.sha256("|".join(source_ids).encode("utf-8")).hexdigest()[:24]
    return {
        "source_collection_key": group_name,
        "source_snapshot_ref": snapshot,
        "source_feature_ids": ",".join(source_ids),
        "source_feature_digest": digest,
    }


def _geometry_kind_for_group(group_name: str) -> str:
    if any(token in group_name for token in ("annotation", "facilit", "hazard", "disaster", "point")):
        return "points"
    if "road" in group_name or group_name in {"transport", "water_lines"}:
        return "lines"
    return "polygons"


def _feature_identity_fact(
    bundle: object,
    feature: object,
    group_name: str,
    *,
    geometry_kind: str = "",
) -> EvidenceFact | None:
    bsm = str(getattr(feature, "bsm", "") or "").strip()
    if not bsm:
        return None
    source_feature_id = _source_feature_id(feature)
    source_metadata = _bundle_source_metadata(
        bundle,
        geometry_kind or _geometry_kind_for_group(group_name),
        group_name,
    )
    label = next(
        (
            str(getattr(feature, attr, "") or "").strip()
            for attr in (
                "text", "facility_name", "name", "road_name", "water_name",
                "dlmc", "zone_type", "planning_zone", "dlbm",
            )
            if str(getattr(feature, attr, "") or "").strip()
        ),
        group_name,
    )
    feature_ref = f"bundle://feature/{bsm}"
    source_ref = f"bundle:{group_name}:{bsm}"
    return EvidenceFact(
        statement=f"{label}的 bundle feature BSM 为 {bsm}",
        confidence=0.95,
        source_refs=[source_ref],
        spatial_refs=[feature_ref],
        fact_type="bundle_feature_identity",
        fields={
            "bundle_feature_bsm": bsm,
            "source_feature_id": source_feature_id,
            "source_layer": group_name,
            "geometry_authority": "bundle",
            **source_metadata,
        },
        evidence_span=f"{label} | {bsm}",
        source_locator=feature_ref,
        support_relation="bundle_identity",
        status="verified",
        evidence_role="location_binding",
        source_kind="bundle_feature",
        spatial_granularity="feature",
        planning_use="grounding",
    )


def _feature_facts(bundle: object, scopes: List[str], query: str) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Read actual feature identities without returning geometry payloads."""
    groups: list[tuple[str, str, object]] = []
    if scopes:
        for scope in scopes:
            for group_name in _SCOPE_TO_GROUPS.get(scope, []):
                if group_name in {name for name, _, _ in groups}:
                    continue
                if group_name in {"facility", "transport", "water", "current_landuse"}:
                    continue
                container_name = _geometry_kind_for_group(group_name)
                container = getattr(bundle, container_name, None)
                features = container.get(group_name) if container is not None and hasattr(container, "get") else []
                if features:
                    groups.append((group_name, container_name, features))
    else:
        # An unscoped project query must not depend on the caller knowing the
        # source layer.  Scan the three bounded Bundle collections and let the
        # exact source labels decide whether an identity fact is relevant.
        for container_name in ("points", "lines", "polygons"):
            container = getattr(bundle, container_name, None)
            if container is None or not hasattr(container, "items"):
                continue
            for group_name, features in container.items():
                if features:
                    groups.append((str(group_name), container_name, features))

    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    seen: set[str] = set()
    for group_name, geometry_kind, features in groups:
        for feature in list(features or []):
            if not _query_matches_feature(feature, query):
                continue
            fact = _feature_identity_fact(
                bundle,
                feature,
                group_name,
                geometry_kind=geometry_kind,
            )
            if fact is None:
                continue
            bsm = str(fact.fields.get("bundle_feature_bsm") or "")
            if bsm in seen:
                continue
            seen.add(bsm)
            facts.append(fact)
            sources.append(
                EvidenceSource(
                    source_type="gis_layer",
                    reference=fact.source_refs[0],
                    confidence=fact.confidence,
                )
            )
            if len(facts) >= _FEATURE_LIMIT:
                return facts, sources
    return facts, sources


async def retrieve_from_bundle(
    session_id: str,
    entity_scope: List[str],
    query: str = "",
    required_facts: List[str] | None = None,
) -> Tuple[List[EvidenceFact], List[EvidenceSource]]:
    """Retrieve spatial group statistics from the VillageBundle snapshot.

    Returns (facts, sources). Deterministic; reads bundle snapshot only.
    """
    bundle = await resolve_bundle(session_id)
    if bundle is None:
        return [], []

    stats = group_stats(bundle)
    facts: List[EvidenceFact] = []
    sources: List[EvidenceSource] = []

    feature_facts, feature_sources = _feature_facts(bundle, entity_scope, query)
    facts.extend(feature_facts)
    sources.extend(feature_sources)

    target_groups = set()
    for scope in entity_scope:
        target_groups.update(_SCOPE_TO_GROUPS.get(scope, []))

    # group_stats returns {geom_type: {group: {count, labels}}} nested by
    # geometry type (points/lines/polygons); flatten over each geometry type.
    for geom_type, groups in (stats or {}).items():
        for group_name, stat in (groups or {}).items():
            if target_groups and group_name not in target_groups:
                continue
            count = stat.get("count", 0)
            labels = stat.get("labels", {}) or {}
            label_summary = "、".join(
                f"{label}×{n}" for label, n in list(labels.items())[:5]
            )
            if count or label_summary:
                statement = f"{group_name}: {count}个要素"
                if label_summary:
                    statement += f"（{label_summary}）"
                source_metadata = _bundle_source_metadata(bundle, geom_type, group_name)
                external_group = _is_external_group(group_name)
                fact_confidence = 0.65 if external_group else 0.95
                evidence_role = "external_spatial_context" if external_group else "spatial_fact"
                source_kind = "external_anchor" if external_group else "gis_layer"
                planning_use = "context_only" if external_group else "constraint"
                facts.append(EvidenceFact(
                    statement=statement,
                    confidence=fact_confidence,
                    source_refs=[f"bundle:{geom_type}:{group_name}"],
                    fact_type="bundle_layer_stat",
                    fields={
                        "evidence_role": evidence_role,
                        "source_kind": source_kind,
                        "subject_scope": group_name,
                        # This is a deterministic layer aggregate, not a
                        # claim about a specific feature set.  Requiring
                        # feature IDs here would incorrectly turn every
                        # layer summary into an L1 lineage gap.
                        "counting_basis": "layer_aggregate",
                        "value": str(count),
                        "unit": "source_features",
                        **source_metadata,
                    },
                    support_relation="bundle_layer_stat",
                    evidence_role=evidence_role,
                    source_kind=source_kind,
                    spatial_granularity="layer",
                    planning_use=planning_use,
                ))
                sources.append(EvidenceSource(
                    source_type="external" if external_group else "gis_layer",
                    reference=f"bundle:{geom_type}:{group_name}",
                    confidence=fact_confidence,
                ))
    return facts, sources
