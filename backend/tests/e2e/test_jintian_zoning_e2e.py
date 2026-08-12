"""End-to-end smoke test: ingest jintian → emit control_code + planning_zone + custom functional zone.

Exercises the zoning refactor blocks:
  Block A: encoding detection on jintian DLBM=1340 (already in appendix5)
  Block C: THREE_LINE builder + control_code + planning_zone generators
  Block D: CustomZoningGenerator with jintian_industry vocabulary
  (Block B zone_type deriver was removed in Wave I — legacy mapping module deleted)
"""
from pathlib import Path

import pytest
from shapely.geometry import box, shape

from app.data.ingestion.ingest import ingest_current_landuse
from app.data.ingestion.encoding_detector import detect_encoding
from app.infrastructure.kg.builder.layer1_control_lines import build_control_line_entities
from app.infrastructure.kg.ontology import EntityTypes
from app.data.model.audit import ProvenanceSource
from app.domain.materialization.zoning.custom_zone_generator import (
    CustomZoningGenerator,
)


JINTIAN_CURRENT = (
Path(__file__).resolve().parents[2].parent / "data" / "gis" / "jintian" / "current" / "landuse.geojson"
)
JINTIAN_BOUNDARY_BOX = box(115.5, 24.5, 116.5, 25.5)  # bounding box around jintian coordinates


@pytest.fixture(autouse=True)
def _legacy_switch(monkeypatch):
    """Keep the explicit legacy switch for comparison-oriented mapping output."""
    monkeypatch.setenv("GIS_LEGACY_MAPPING", "1")


def _to_dicts(parcels):
    out = []
    for p in parcels:
        if p.geometry is None:
            continue
        try:
            geom = shape(p.geometry) if isinstance(p.geometry, dict) else p.geometry
        except Exception:
            continue
        out.append(
            {
                "bsm": p.bsm,
                "dlbm": p.dlbm,
                "current_landuse_code": p.sddlbm or None,
                "geometry": geom,
            }
        )
    return out


def test_jintian_ingest_routes_dlbm_through_detector():
    parcels, _ = ingest_current_landuse(str(JINTIAN_CURRENT))
    assert len(parcels) > 0
    sample = parcels[0]
    enc = detect_encoding(sample.dlbm)
    assert enc in {
        ProvenanceSource.GBT21010,
        ProvenanceSource.PRACTICAL_APPENDIX5,
    }


def test_jintian_control_line_builder_records_missing_three_lines():
    bundle = {
        "ecological_redline": [{"bsm": f"E{i}", "geometry": "stub"} for i in range(5)],
        "farmland_redline": [{"bsm": f"F{i}", "geometry": "stub"} for i in range(88)],
    }
    entities, audit = build_control_line_entities(bundle)
    assert len(entities) == 93
    assert all(e["entity_type"] == EntityTypes.ControlLine for e in entities)
    subtypes = {e["subtype"] for e in entities}
    assert subtypes == {"EcologicalRedline", "FarmlandProtection"}
    missing = audit.missing_layers()
    sources = {e.source for e in missing}
    assert "missing:gd_urban_dev_boundary" in sources


def test_jintian_emits_all_four_block_outputs():
    """Smoke: the remaining block APIs run without raising on jintian data."""
    parcels, _ = ingest_current_landuse(str(JINTIAN_CURRENT))
    parcel_dicts = _to_dicts(parcels)
    assert len(parcel_dicts) > 100

    # Block D (vocabulary moved from YAML to session registration in 9c0a1ade)
    from app.contracts.domain.custom_zone_contracts import (
        TypingRule, Vocabulary, VocabularyCategory,
    )
    from app.data.encodings.dicts.vocabularies.loader import register_vocabulary

    register_vocabulary(
        "jintian_industry",
        Vocabulary(
            name="jintian_industry",
            categories=[
                VocabularyCategory(
                    code="IND_LEAD",
                    name_zh="主导产业区",
                    color="#CC5500",
                    typing_rules=[TypingRule(kind="dlbm_in", value=["2124", "2125"])],
                )
            ],
        ),
    )
    intent = {
        "vocabulary_name": "jintian_industry",
        "custom_zone_targets": [
            {
                "vocabulary_name": "jintian_industry",
                "category_code": "IND_LEAD",
                "target_bsms": [parcel_dicts[0]["bsm"]],
                "decided_by": "llm",
            }
        ],
    }
    gen = CustomZoningGenerator(parcels=parcel_dicts, intent=intent)
    zones = gen.generate()
    assert isinstance(zones, list)