# backend/app/agent/explore/service.py
"""EXPLORE evidence service - single retrieve_evidence entry point.

Returns EvidenceBundle + SpatialCognitionEvidence. Never returns candidate
BSMs, bbox, or intent. Deterministic (no LLM).
"""
from __future__ import annotations

from typing import List

from app.modules.schema.contracts.evidence_contracts import (
    ExplorationRequest,
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
    SpatialCognitionEvidence,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def retrieve_evidence(
    request: ExplorationRequest,
    session_id: str,
    village_name: str = "",
) -> ExplorationResult:
    """Retrieve evidence from all session sources for a planning stage.

    Searches: session KG, VillageBundle, all AnalysisReports (content +
    【INSTRUCTION】), typed artifacts (placeholder until Wave D/E).

    Returns ExplorationResult with evidence_bundle and spatial_cognition.
    """
    from app.agent.explore.retrievers.report_retriever import retrieve_from_reports
    from app.agent.explore.retrievers.kg_retriever import retrieve_from_kg
    from app.agent.explore.retrievers.bundle_retriever import retrieve_from_bundle
    from app.agent.explore.retrievers.instruction_retriever import retrieve_from_instructions

    all_facts: List[EvidenceFact] = []
    all_sources: List[EvidenceSource] = []

    # 1. Reports
    try:
        r_facts, r_sources = await retrieve_from_reports(
            session_id, request.dimension_key, request.stage,
        )
        all_facts.extend(r_facts)
        all_sources.extend(r_sources)
    except Exception as e:
        logger.warning("[retrieve_evidence] report retriever failed: %s", e)

    # 2. Instructions
    try:
        i_facts, i_sources = await retrieve_from_instructions(
            session_id, request.dimension_key, request.stage,
        )
        all_facts.extend(i_facts)
        all_sources.extend(i_sources)
    except Exception as e:
        logger.warning("[retrieve_evidence] instruction retriever failed: %s", e)

    # 3. KG
    kg_facts: List[EvidenceFact] = []
    cognition = SpatialCognitionEvidence()
    try:
        kg_facts, cognition = await retrieve_from_kg(
            session_id, village_name, request.dimension_key, request.stage,
        )
        all_facts.extend(kg_facts)
        all_sources.append(EvidenceSource(
            source_type="kg",
            reference=f"session_kg:{session_id}",
            confidence=cognition.kg_confidence,
        ))
    except Exception as e:
        logger.warning("[retrieve_evidence] KG retriever failed: %s", e)

    # 4. Bundle
    try:
        b_facts, b_sources = await retrieve_from_bundle(
            session_id, request.entity_scope,
        )
        all_facts.extend(b_facts)
        all_sources.extend(b_sources)
    except Exception as e:
        logger.warning("[retrieve_evidence] bundle retriever failed: %s", e)

    # Deduplicate facts by statement (preserve order)
    seen = set()
    unique_facts: List[EvidenceFact] = []
    for f in all_facts:
        key = f.statement[:80]
        if key not in seen:
            seen.add(key)
            unique_facts.append(f)

    # Deduplicate sources by reference
    seen_src = set()
    unique_sources: List[EvidenceSource] = []
    for s in all_sources:
        if s.reference not in seen_src:
            seen_src.add(s.reference)
            unique_sources.append(s)

    confidence = 0.0
    if unique_facts:
        confidence = sum(f.confidence for f in unique_facts) / len(unique_facts)

    bundle = EvidenceBundle(
        request=request.query,
        facts=unique_facts,
        sources=unique_sources,
        confidence=round(confidence, 3),
        unresolved=list(request.questions) if request.questions else [],
    )
    return ExplorationResult(
        evidence_bundle=bundle,
        spatial_cognition=cognition,
    )


def render_evidence_prompt_section(
    bundle: EvidenceBundle,
    cognition: SpatialCognitionEvidence | None = None,
) -> str:
    """Render an ExplorationResult as a unified markdown prompt section.

    Replaces the old _optimize_semantics + _build_explore_brief output.
    """
    lines = ["## EXPLORE 证据"]

    if cognition and cognition.village_overview:
        lines.append(f"**村域概况**: {cognition.village_overview}")
        if cognition.spatial_pattern:
            lines.append(f"**空间格局**: {cognition.spatial_pattern}")
        if cognition.constraint_coverage:
            lines.append(f"**约束覆盖**: {cognition.constraint_coverage}")
        if cognition.topology_facts:
            lines.append("**拓扑结构**: " + "; ".join(cognition.topology_facts[:5]))
        if cognition.entity_annotations:
            lines.append("**关键实体**: " + "、".join(cognition.entity_annotations[:8]))
        lines.append(f"**KG 置信度**: {cognition.kg_confidence:.2f}")

    if bundle.facts:
        lines.append("")
        lines.append("**空间事实**:")
        for fact in bundle.facts[:12]:
            lines.append(f"- {fact.statement}")

    if bundle.sources:
        src_summary = ", ".join(
            f"{s.source_type}:{s.reference}" for s in bundle.sources[:6]
        )
        lines.append(f"**证据来源**: {src_summary}")

    if bundle.unresolved:
        lines.append("**待查问题**: " + "; ".join(bundle.unresolved[:3]))

    return "\n".join(lines)


__all__ = ["retrieve_evidence", "render_evidence_prompt_section"]
