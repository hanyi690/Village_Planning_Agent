"""KG retriever - session KG cognition + topology facts for L2/L3."""
from __future__ import annotations

from typing import List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    SpatialCognitionEvidence,
)
from app.tools.access.shared import session_kg
from app.infrastructure.kg.queries.cognition import get_village_cognition
from app.infrastructure.kg.queries.sparql import query_kg
from app.infrastructure.logging import get_logger

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

        # Promote bounded, dimension-relevant layer cards instead of only the
        # single overview sentence.  The KG may contain tens of thousands of
        # triples; L1 receives a human-readable summary with provenance, not a
        # raw graph dump.  This is the canonical KG -> L1 evidence boundary.
        cards = result.semantic.get("layer_cards") or []
        terms_by_dimension = {
            "traffic": ("transport", "road", "道路", "交通"),
            "infrastructure": ("infrastructure", "utility", "water", "electric", "基础", "供水"),
            "public_services": ("facility", "public", "service", "公共", "服务"),
            "public_service": ("facility", "public", "service", "公共", "服务"),
            "ecological_green": ("ecology", "green", "water", "protection", "生态", "绿"),
            "historical_culture": ("history", "culture", "heritage", "历史", "文化"),
            "land_use": ("land", "use", "farmland", "current", "用地", "地类"),
            "location": ("boundary", "admin", "village", "location", "区位"),
            "socio_economic": ("village", "settlement", "residential", "村", "居民"),
        }
        terms = terms_by_dimension.get(dimension_key, ())
        selected_cards = []
        for card in cards:
            haystack = " ".join(str(card.get(key, "")) for key in ("group", "dominant_label", "distribution", "description"))
            if dimension_key in {"l1_snapshot", ""} or not terms or any(term.lower() in haystack.lower() for term in terms):
                selected_cards.append(card)
        # Keep the audit and prompt bounded while retaining all distinct groups
        # that match the dimension.  The card count is a deterministic KG fact.
        for card in selected_cards[:12]:
            group = str(card.get("group") or "未命名图层")
            count = int(card.get("count") or 0)
            geometry = str(card.get("geometry") or "")
            label = str(card.get("dominant_label") or "")
            detail = str(card.get("distribution") or card.get("description") or "").strip()
            statement = f"KG图层 {group}: {count} 个{geometry or '要素'}"
            if label:
                statement += f"，主类别={label}"
            if detail:
                statement += f"；{detail[:180]}"
            facts.append(EvidenceFact(
                statement=statement,
                confidence=max(0.65, kg_confidence),
                source_refs=[f"kg:layer:{group}"],
            ))

        entity_counts = ctx.get("entity_counts") or {}
        for entity_type, label in (("Parcel", "地块"), ("Road", "道路"), ("Facility", "设施"), ("WaterBody", "水域")):
            if entity_type not in entity_counts:
                continue
            facts.append(EvidenceFact(
                statement=f"KG实体统计: {label} {int(entity_counts[entity_type])} 个",
                confidence=max(0.7, kg_confidence),
                source_refs=["kg:entity_counts"],
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
        from app.infrastructure.kg import get_semantic_memory

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
