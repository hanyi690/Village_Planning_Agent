"""KG retriever - session KG cognition + topology facts for L2/L3."""
from __future__ import annotations

from typing import List, Tuple

from app.modules.schema.contracts.evidence_contracts import (
    EvidenceFact,
    SpatialCognitionEvidence,
)
from app.tools.access.shared import session_kg
from app.modules.kg.queries.cognition import get_village_cognition
from app.modules.kg.queries.sparql import query_kg
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def retrieve_from_kg(
    session_id: str,
    village_name: str,
    dimension_key: str,
    stage: str,
) -> Tuple[List[EvidenceFact], SpatialCognitionEvidence]:
    """Retrieve KG three-layer cognition + topology facts.

    Returns (facts, cognition). Deterministic; no LLM. Returns empty on failure.
    """
    kg = session_kg(session_id)
    if kg is None:
        return [], SpatialCognitionEvidence()

    overview = ""
    pattern = ""
    constraint = ""
    kg_confidence = 0.0
    facts: List[EvidenceFact] = []

    try:
        result = get_village_cognition(kg, village_name or "", mode="full")
        ctx = result.semantic.get("context_block") or {}
        overview = str(ctx.get("overview", ""))
        pattern = str(ctx.get("spatial_pattern", ""))
        cb = result.semantic.get("constraint_block") or {}
        constraint = str(cb.get("constraint_coverage", ""))
        kg_confidence = 0.8 if ctx.get("parcel_count") else 0.3
        if overview:
            facts.append(EvidenceFact(
                statement=f"村域概况: {overview}",
                confidence=kg_confidence,
                source_refs=["kg:cognition"],
            ))
    except Exception as e:
        logger.warning("[kg_retriever] cognition failed: %s", e)

    topology_facts: List[str] = []
    stage_layer = int(stage.lstrip("Ll")) if stage else 1
    if stage_layer >= 2:
        try:
            if stage_layer == 3:
                roads = query_kg(kg, "get_road_network") or []
                if roads:
                    names = [str(r.get("name") or "") for r in roads if r.get("name")]
                    topology_facts.append(f"现状道路: {'、'.join(names[:8])}（{len(roads)}条）")
                waters = query_kg(kg, "get_water_bodies") or []
                if waters:
                    wnames = [str(w.get("name") or "") for w in waters if w.get("name")]
                    topology_facts.append(f"现状水系: {'、'.join(wnames[:6])}（{len(waters)}处）")
        except Exception as e:
            logger.debug("[kg_retriever] topology failed: %s", e)

    entity_annotations: List[str] = []
    try:
        from app.modules.kg import get_semantic_memory

        mem = get_semantic_memory()
        for uri, ann in mem.entity_annotations.items():
            label = (ann.description or uri)[:20]
            if label not in entity_annotations:
                entity_annotations.append(label)
    except Exception:
        pass

    cognition = SpatialCognitionEvidence(
        village_overview=overview,
        spatial_pattern=pattern,
        constraint_coverage=constraint,
        topology_facts=topology_facts,
        entity_annotations=entity_annotations[:10],
        kg_confidence=kg_confidence,
    )
    return facts, cognition
