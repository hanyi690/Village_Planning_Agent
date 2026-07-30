"""Cognition completeness tests - design doc §十三 (7 assertions).

Proves the KG provides usable spatial cognition for the LLM using real
jintian data. Run:
  cd F:/project/Village_Planning_Agent
  python -m pytest backend/tests/integration/test_village_cognition.py -v --tb=short
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

_JINTIAN_DATA = _PROJECT_ROOT / "data" / "gis" / "jintian"


@pytest.fixture(scope="module")
def kg_and_bundle():
    from app.modules.data.ingest import ingest_current_landuse, ingest_feature
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import PlanningKG

    bundle = VillageBundle(village_name="jintian")

    parcels, _ = ingest_current_landuse(str(_JINTIAN_DATA / "current" / "landuse.geojson"))
    for p in parcels:
        bundle.add(p)

    roads, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "road.geojson"), "current_road")
    for r in roads:
        bundle.add(r)

    anns, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "annotation.geojson"), "current_annotation")
    for a in anns:
        bundle.add(a)

    for feature_type, filename in [
        ("farmland_protection", "farmland_protection.geojson"),
        ("ecological_redline", "ecological_protection.geojson"),
        ("historical_protection", "historical_protection.geojson"),
    ]:
        path = _JINTIAN_DATA / "planned" / filename
        if path.exists():
            feats, _ = ingest_feature(str(path), feature_type)
            for f in feats:
                bundle.add(f)

    boundary, _ = ingest_feature(str(_JINTIAN_DATA / "current" / "boundary.geojson"), "admin_area")
    for b in boundary:
        bundle.add(b)

    assert bundle.parcel_count > 0
    rel = compute_parcel_relations(
        bundle.polygons.get("landuse_current"), roads=bundle.lines.get("roads_current"))
    ci = build_constraint_index(bundle)
    kg = PlanningKG(village_name="jintian")
    kg.build_from_bundle(bundle=bundle, parcel_relations=rel, constraint_index=ci)
    return kg, bundle


@pytest.fixture(scope="module")
def cognition(kg_and_bundle):
    from app.modules.kg.queries.cognition import get_village_cognition
    kg, _ = kg_and_bundle
    return get_village_cognition(kg, "jintian")


def test_cognition_completeness(cognition):
    semantic = cognition.semantic
    assert "context_block" in semantic
    assert "layer_cards" in semantic
    assert "constraint_block" in semantic
    assert len(semantic["layer_cards"]) == 5, "Expected exactly 5 layer cards"
    assert cognition.token_estimate > 0
    assert cognition.token_estimate <= 6000, "token_estimate must respect hard limit"


def test_bsm_alignment(kg_and_bundle):
    kg, bundle = kg_and_bundle
    bundle_count = len(bundle.polygons.get("landuse_current"))
    kg_count = kg.get_parcel_count()
    assert bundle_count == kg_count, f"BSM misalignment: bundle={bundle_count}, kg={kg_count}"
    assert kg_count == 660


def test_statistics_consistency(kg_and_bundle, cognition):
    kg, bundle = kg_and_bundle
    ctx = cognition.semantic["context_block"]
    assert ctx["parcel_count"] == 660
    assert ctx["total_area_ha"] > 0
    entity_counts = ctx["entity_counts"]
    assert entity_counts.get("Road", 0) > 0


def test_layer_group_coverage(cognition):
    structured = cognition.structured
    layer_bsms = structured.get("layer_group_bsms", {})
    assert len(layer_bsms) == 5, f"Expected exactly 5 layer groups, got {len(layer_bsms)}"
    total = sum(len(v) for v in layer_bsms.values())
    assert total > 0


def test_constraint_coverage(cognition, kg_and_bundle):
    kg, _ = kg_and_bundle
    from app.modules.kg.queries.semantic import get_village_constraint_coverage
    coverage = get_village_constraint_coverage(kg)
    assert isinstance(coverage, list)
    assert len(coverage) > 0
    if len(coverage) > 1:
        summary = coverage[0]
        assert "parcel_count" in summary
    constraint_block = cognition.semantic.get("constraint_block", {})
    assert "adjacency_total" in constraint_block


def test_entity_semantics(kg_and_bundle):
    kg, _ = kg_and_bundle
    from app.modules.kg.queries.semantic import get_entity_semantics
    result = get_entity_semantics(kg, entity_label="\u8015\u5730")
    assert "error" not in result, f"get_entity_semantics failed: {result.get('error')}"
    assert result.get("matching_entities", {}).get("count", 0) > 0, \
        "No matching entities for \u8015\u5730"


def test_token_budget_control(cognition):
    assert cognition.token_estimate > 0
    assert not cognition.truncated or cognition.token_estimate <= 6000
    rep = cognition.structured.get("representative_bsms", [])
    assert len(rep) <= 40, f"representative_bsms must be <= 40, got {len(rep)}"