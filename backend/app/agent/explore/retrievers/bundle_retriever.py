# backend/app/agent/explore/retrievers/bundle_retriever.py
"""Bundle retriever - VillageBundle spatial group statistics as evidence."""
from __future__ import annotations

from typing import List, Tuple

from app.modules.schema.contracts.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.tools.access.shared import resolve_bundle, group_stats
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SCOPE_TO_GROUPS = {
    "parcels": ["current_landuse"],
    "facilities": ["facility"],
    "roads": ["transport"],
    "waters": ["water"],
    "annotations": ["annotations_current", "annotations_planned"],
}


async def retrieve_from_bundle(
    session_id: str,
    entity_scope: List[str],
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
                facts.append(EvidenceFact(
                    statement=statement,
                    confidence=0.95,
                    source_refs=[f"bundle:{geom_type}:{group_name}"],
                ))
                sources.append(EvidenceSource(
                    source_type="gis_layer",
                    reference=f"bundle:{geom_type}:{group_name}",
                    confidence=0.95,
                ))
    return facts, sources
