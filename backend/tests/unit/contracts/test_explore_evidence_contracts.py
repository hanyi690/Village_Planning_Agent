"""EXPLORE evidence contract tests - Wave C enrichment."""
from __future__ import annotations

import pytest
from app.modules.schema.contracts.evidence_contracts import (
    ExplorationRequest,
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    SpatialCognitionEvidence,
    ExplorationResult,
)


def test_exploration_request_has_stage_dimension_purpose():
    req = ExplorationRequest(
        run_id="r1",
        request_type="spatial_lookup",
        query="耕地分布",
        stage="L1",
        dimension_key="land_use",
        query_purpose="context_injection",
        questions=["自然村耕地集中区在哪？"],
        required_facts=["farmland_area_ha"],
        entity_scope=["parcels", "facilities"],
    )
    assert req.stage == "L1"
    assert req.dimension_key == "land_use"
    assert req.query_purpose == "context_injection"
    assert req.questions == ["自然村耕地集中区在哪？"]
    assert req.required_facts == ["farmland_area_ha"]
    assert req.entity_scope == ["parcels", "facilities"]


def test_exploration_request_legacy_fields_preserved():
    req = ExplorationRequest(run_id="r1", request_type="evidence_gap", query="x")
    assert req.context_refs == []
    assert req.evidence_gaps_to_resolve == []


def test_spatial_cognition_evidence_fields():
    sce = SpatialCognitionEvidence(
        village_overview="田坑村位于...",
        spatial_pattern="组团状",
        constraint_coverage="生态红线覆盖30%",
        topology_facts=["道路连通田坑-黄竹"],
        entity_annotations=["田坑", "黄竹"],
        kg_confidence=0.8,
    )
    assert sce.village_overview
    assert sce.topology_facts == ["道路连通田坑-黄竹"]
    assert sce.kg_confidence == 0.8


def test_exploration_result_carries_bundle_and_cognition():
    bundle = EvidenceBundle(
        request="耕地分布",
        facts=[EvidenceFact(statement="耕地120ha", confidence=0.9)],
        sources=[EvidenceSource(source_type="kg", reference="session_kg")],
    )
    sce = SpatialCognitionEvidence(village_overview="overview")
    result = ExplorationResult(
        evidence_bundle=bundle,
        spatial_cognition=sce,
    )
    assert result.evidence_bundle.facts[0].statement == "耕地120ha"
    assert result.spatial_cognition.village_overview == "overview"


def test_exploration_result_cognition_optional():
    bundle = EvidenceBundle(request="x")
    result = ExplorationResult(evidence_bundle=bundle)
    assert result.spatial_cognition is None
