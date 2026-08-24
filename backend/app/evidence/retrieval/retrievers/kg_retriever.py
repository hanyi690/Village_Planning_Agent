"""KG retriever - session KG cognition + topology facts for L2/L3."""
from __future__ import annotations

import hashlib
from typing import List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    SpatialCognitionEvidence,
)
from app.infrastructure.llm.tools.access.shared import session_kg
from app.infrastructure.kg.queries.cognition import get_village_cognition
from app.infrastructure.kg.queries.sparql import query_kg
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "kg-v2"


async def retrieve_from_kg(
    session_id: str,
    village_name: str,
    dimension_key: str,
    stage: str,
    query: str = "",
    required_facts: list[str] | None = None,
    entity_scope: list[str] | None = None,
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
                fact_type="kg_canonical_fact",
                fields={
                    "evidence_role": "spatial_fact",
                    "source_kind": "kg",
                    "counting_basis": "derived_metric",
                    "subject_scope": village_name or "session_village",
                },
                support_relation="kg_cognition",
            ))

        # Typed KG facts are the canonical machine-facing boundary.  Layer
        # cards remain available as cognition for the LLM, but are not emitted
        # as a second, untraceable count when typed records exist.
        typed_records = list(result.structured.get("fact_records") or [])
        for record in typed_records:
            source_ids = [str(item) for item in record.get("source_feature_ids") or []]
            source_digest = hashlib.sha256(
                "|".join(sorted(source_ids)).encode("utf-8")
            ).hexdigest()[:24]
            source_refs = [str(item) for item in record.get("source_refs") or []]
            facts.append(EvidenceFact(
                statement=str(record.get("statement") or ""),
                confidence=float(record.get("confidence") or 0.0),
                source_refs=source_refs or [str(record.get("fact_id") or "")],
                fact_type="kg_canonical_fact",
                fields={
                    "evidence_role": "spatial_fact",
                    "source_kind": "kg",
                    "counting_basis": str(record.get("counting_basis") or ""),
                    "subject_scope": str(record.get("subject_scope") or ""),
                    "semantic_group": str(record.get("semantic_group") or ""),
                    "source_collection_key": str(record.get("source_collection_key") or ""),
                    "source_snapshot_ref": str(record.get("source_snapshot_ref") or ""),
                    "source_feature_count": str(len(source_ids)),
                    "source_feature_digest": source_digest,
                    "source_feature_sample": ",".join(source_ids[:8]),
                    "geometry_kind": str(record.get("geometry_kind") or ""),
                    "value": str(record.get("value") or ""),
                    "unit": str(record.get("unit") or ""),
                    "fact_id": str(record.get("fact_id") or ""),
                },
                support_relation="kg_typed_fact",
            ))

        # Promote bounded, dimension-relevant layer cards only for legacy KGs
        # that have not yet emitted typed records.
        cards = [] if typed_records else (result.semantic.get("layer_cards") or [])
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
        query_terms = tuple(
            token.lower() for token in (query or "").replace("；", " ").split()
            if len(token.strip()) > 1
        )
        terms = tuple(dict.fromkeys((*terms_by_dimension.get(dimension_key, ()), *query_terms)))
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
                fact_type="kg_canonical_fact",
                fields={
                    "evidence_role": "spatial_fact",
                    "source_kind": "kg",
                    # Layer cards aggregate a collection; they do not carry
                    # the member feature IDs needed by the source-feature
                    # lineage contract.
                    "counting_basis": "layer_aggregate",
                    "subject_scope": group,
                    "semantic_group": str(card.get("semantic_group") or ""),
                    "geometry_kind": geometry,
                    "layer_group": group,
                    "value": str(count),
                    "unit": "source_features",
                },
                support_relation="kg_layer_card",
            ))

        entity_counts = {} if typed_records else (ctx.get("entity_counts") or {})
        for entity_type, label in (("Parcel", "地块"), ("Road", "道路"), ("Facility", "设施"), ("WaterBody", "水域")):
            if entity_type not in entity_counts:
                continue
            facts.append(EvidenceFact(
                statement=f"KG源要素统计: {label} {int(entity_counts[entity_type])} 个",
                confidence=max(0.7, kg_confidence),
                source_refs=[f"kg:entity_counts:{entity_type}"],
                fact_type="kg_canonical_fact",
                fields={
                    "evidence_role": "spatial_fact",
                    "source_kind": "kg",
                    # Entity totals are KG aggregates.  Feature-level facts
                    # below retain the stricter source_feature basis.
                    "counting_basis": "layer_aggregate",
                    "subject_scope": entity_type,
                    "value": str(int(entity_counts[entity_type])),
                    "unit": "source_features",
                },
                support_relation="kg_typed_entity_count",
            ))
    except Exception as e:
        logger.warning("[kg_retriever] cognition failed: %s", e)

    topology_facts: List[str] = []
    stage_value = str(stage or "").strip().upper()
    stage_layer = {
        "": 1,
        "L1": 1,
        "L2": 2,
        "L3": 3,
        "GROUND": 2,
        "SELECT": 2,
        "EXECUTE": 3,
        "VALIDATE": 3,
        "RECONCILE": 3,
        "DELIVER": 3,
    }.get(stage_value, 1)
    if stage_layer >= 2:
        try:
            if stage_layer == 3:
                roads = query_kg(kg, "get_road_network") or []
                if roads:
                    names = [str(r.get("name") or "") for r in roads if r.get("name")]
                    statement = f"现状道路拓扑源集合：{'、'.join(names[:8])}（{len(roads)}条记录）"
                    topology_facts.append(statement)
                    facts.append(EvidenceFact(
                        statement=statement,
                        confidence=0.8,
                        source_refs=["kg:topology:road_network"],
                        fact_type="spatial_relation",
                        fields={
                            "evidence_role": "spatial_topology",
                            "source_kind": "kg",
                            "counting_basis": "topology_edge",
                            "subject_scope": "road_network",
                            "value": str(len(roads)),
                            "unit": "topology_records",
                        },
                        support_relation="kg_network_query",
                    ))
                waters = query_kg(kg, "get_water_bodies") or []
                if waters:
                    wnames = [str(w.get("name") or "") for w in waters if w.get("name")]
                    statement = f"现状水系源集合：{'、'.join(wnames[:6])}（{len(waters)}条记录）"
                    topology_facts.append(statement)
                    facts.append(EvidenceFact(
                        statement=statement,
                        confidence=0.8,
                        source_refs=["kg:topology:water_network"],
                        fact_type="spatial_relation",
                        fields={
                            "evidence_role": "spatial_topology",
                            "source_kind": "kg",
                            "counting_basis": "topology_edge",
                            "subject_scope": "water_network",
                            "value": str(len(waters)),
                            "unit": "topology_records",
                        },
                        support_relation="kg_network_query",
                    ))
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
