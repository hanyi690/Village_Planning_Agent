"""Ingest behavior after removing current-landuse planning derivation.

Verifies that:
  (a) a current-landuse feature produces a parcel WITHOUT derived
      planning_zone / primary_zone / zone_type (absent unless user-provided), and
  (b) a planned-landuse feature preserves a user-provided planning_zone and
      defaults to "preserve" when absent.
"""

from app.modules.data.ingest import ingest_landuse


def _feature(bsm: str, extra: dict) -> dict:
    props = {"BSM": bsm, "DLBM": "0110", **extra}
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": props,
    }


def _geojson(*features) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def test_current_landuse_has_no_derived_planning_zones():
    parcels, _ = ingest_landuse(
        _geojson(_feature("001", {"DLMC": "水田"})),
        layer_type="current_landuse",
    )
    assert len(parcels) == 1
    p = parcels[0]
    assert p.planning_zone == ""
    assert p.primary_zone == ""
    assert p.zone_type == ""


def test_current_landuse_preserves_user_provided_zone_fields():
    parcels, _ = ingest_landuse(
        _geojson(_feature("002", {"planning_zone": "村庄建设区", "zone_type": "居住用地", "primary_zone": "城镇空间"})),
        layer_type="current_landuse",
    )
    assert len(parcels) == 1
    p = parcels[0]
    assert p.planning_zone == "村庄建设区"
    assert p.zone_type == "居住用地"
    assert p.primary_zone == "城镇空间"


def test_planned_landuse_preserves_user_provided_planning_zone():
    parcels, _ = ingest_landuse(
        _geojson(_feature("003", {"GHYTBM": "1100", "planning_zone": "农田保护区"})),
        layer_type="planned_landuse",
    )
    assert len(parcels) == 1
    p = parcels[0]
    assert p.planning_zone == "农田保护区"


def test_planned_landuse_defaults_to_preserve_when_absent():
    parcels, _ = ingest_landuse(
        _geojson(_feature("004", {"GHYTBM": "1100"})),
        layer_type="planned_landuse",
    )
    assert len(parcels) == 1
    p = parcels[0]
    assert p.planning_zone == "preserve"
    assert p.zone_type == "preserve"
    assert p.primary_zone == "preserve"
