"""External bundle layers remain advisory evidence, never local constraints."""

from __future__ import annotations

import pytest

from app.data.catalog.external_anchors import (
    ExternalAnchorPipeline,
    ExternalFeature,
    FeatureCategory,
)
from app.data.model.canonical import VillageBundle
from app.evidence.retrieval.retrievers import bundle_retriever


def _feature(category: FeatureCategory, geometry: dict) -> ExternalFeature:
    return ExternalFeature(
        name="外部水系/道路",
        name_norm="外部水系道路",
        lon=113.0,
        lat=23.0,
        coord_system="wgs84",
        category=category,
        source="fixture",
        raw={"name": "外部水系道路"},
        geometry=geometry,
    )


@pytest.mark.asyncio
async def test_external_bundle_layers_are_context_only(monkeypatch) -> None:
    bundle = VillageBundle(village_name="测试村")
    ExternalAnchorPipeline()._stage5_inject(
        bundle,
        [
            _feature(FeatureCategory.ROAD_LINE, {
                "type": "LineString",
                "coordinates": [[113.0, 23.0], [113.01, 23.01]],
            }),
            _feature(FeatureCategory.WATER_LINE, {
                "type": "LineString",
                "coordinates": [[113.0, 23.0], [113.02, 23.02]],
            }),
        ],
    )

    async def _bundle(_session_id: str):
        return bundle

    monkeypatch.setattr(bundle_retriever, "resolve_bundle", _bundle)
    facts, sources = await bundle_retriever.retrieve_from_bundle(
        "external-role-test",
        ["roads", "waters"],
        query="外部",
    )

    external_facts = [
        fact for fact in facts
        if fact.fields.get("source_kind") == "external_anchor"
    ]
    assert {fact.fields["subject_scope"] for fact in external_facts} == {
        "external_roads",
        "water_lines",
    }
    assert all(fact.evidence_role == "external_spatial_context" for fact in external_facts)
    assert all(fact.planning_use == "context_only" for fact in external_facts)
    assert all(fact.confidence == 0.65 for fact in external_facts)
    external_sources = [source for source in sources if source.source_type == "external"]
    assert len(external_sources) == 2
