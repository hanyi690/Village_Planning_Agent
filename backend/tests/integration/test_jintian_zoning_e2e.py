"""End-to-end smoke test: ingest jintian → derive zone_types → emit control_code + planning_zone + custom functional zone.

Exercises the 4 blocks of the zoning refactor:
  Block A: encoding detection on jintian DLBM=1340 (already in appendix5)
  Block B: zone_type deriver (DLBM → 5-tier)
  Block C: THREE_LINE builder + control_code + planning_zone generators
  Block D: CustomZoningGenerator with jintian_industry vocabulary
"""
from pathlib import Path

from shapely.geometry import box, shape

from app.modules.data.ingest import ingest_current_landuse
from app.modules.data.encoding_detector import detect_encoding
from app.modules.kg.builder.layer1_three_lines import build_three_line_entities
from app.modules.kg.ontology import ThreeLineSubtypes
from app.modules.schema.provenance import ProvenanceSource
from app.tools.gis._generation.custom_zone_generator import (
    CustomZoningGenerator,
)
from app.tools.gis._generation.vector_overlay_zoning import (
    compute_control_codes,
    compute_planning_zones,
)
from app.tools.gis._generation.zone_type_deriver import derive_zone_types


JINTIAN_CURRENT = (
    Path(__file__).parent.parent.parent / "data" / "gis" / "jintian" / "current" / "landuse.geojson"
)
JINTIAN_BOUNDARY_BOX = box(115.5, 24.5, 116.5, 25.5)  # bounding box around jintian coordinates


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


def test_jintian_derives_zone_types_for_all_parcels():
    parcels, _ = ingest_current_landuse(str(JINTIAN_CURRENT))
    parcel_dicts = _to_dicts(parcels)
    out = derive_zone_types(parcel_dicts)
    unique_bsms = {p["bsm"] for p in parcel_dicts}
    assert len(out) == len(unique_bsms)
    nonempty = [v for v in out.values() if v["zone_type"]]
    assert len(nonempty) > 0
    provenances = {v["encoding_provenance"] for v in out.values()}
    assert any(p.startswith("practical:appendix5") or p.startswith("derived:") for p in provenances)


def test_jintian_three_line_builder_records_missing_sources():
    three_lines = {
        ThreeLineSubtypes.ECOLOGICAL_REDLINE: [{"bsm": f"E{i}", "geometry": "stub"} for i in range(5)],
        ThreeLineSubtypes.FARMLAND_REDLINE: [{"bsm": f"F{i}", "geometry": "stub"} for i in range(88)],
    }
    entities, audit = build_three_line_entities(three_lines)
    assert len(entities) == 93
    missing = audit.missing_layers()
    sources = {e.source for e in missing}
    assert "missing:gd_urban_dev_boundary" in sources


def test_jintian_emits_all_four_block_outputs():
    """Smoke: all four block APIs run without raising on jintian data."""
    parcels, _ = ingest_current_landuse(str(JINTIAN_CURRENT))
    parcel_dicts = _to_dicts(parcels)
    assert len(parcel_dicts) > 100

    # Block B
    zone_types = derive_zone_types(parcel_dicts)
    assert isinstance(zone_types, dict)

    # Block C (control_code needs three_lines; jintian has none of the right
    # ones with valid geometry, so we test the audit path)
    codes, audit = compute_control_codes(parcel_dicts, {}, boundary=JINTIAN_BOUNDARY_BOX)
    assert isinstance(codes, dict)
    missing = {e.source for e in audit.missing_layers()}
    assert "missing:gd_urban_dev_boundary" in missing
    assert "missing:three_line" in missing

    # Block C (planning_zone)
    pz_map, pz_audit = compute_planning_zones(parcel_dicts, {})
    assert pz_map == {}
    assert any("upper_plan" in e.source for e in pz_audit.missing_layers())

    # Block D
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