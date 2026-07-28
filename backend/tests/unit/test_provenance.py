"""Tests for mapping provenance on parcel features."""

from __future__ import annotations

import pytest


class TestParcelProvenanceModel:
    def test_mapping_provenance_default(self):
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel
        p = CurrentLandUseParcel(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            dlbm="0110",
        )
        assert p.mapping_provenance == {}

    def test_mapping_provenance_stored(self):
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel
        provenance = {
            "DLBM": {
                "decided_by": "rule",
                "confidence": "exact",
                "system": "gbt21010",
            }
        }
        p = CurrentLandUseParcel(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            dlbm="0110",
            mapping_provenance=provenance,
        )
        assert p.mapping_provenance["DLBM"]["decided_by"] == "rule"
        assert p.mapping_provenance["DLBM"]["system"] == "gbt21010"

    def test_planned_parcel_provenance(self):
        from app.modules.schema.types.spatial_types import PlannedLandUseParcel
        p = PlannedLandUseParcel(
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            dlbm="0110",
            mapping_provenance={"GHYTBM": {"decided_by": "rule", "confidence": "exact", "system": "appendix5"}},
        )
        assert p.mapping_provenance["GHYTBM"]["system"] == "appendix5"


class TestParcelProvenanceIngest:
    def test_ingest_stores_provenance_for_all_code_fields(self):
        from app.modules.data.ingest import ingest_landuse
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {
                    "BSM": "001",
                    "DLBM": "0110",
                    "SDDLBM": "0110",
                    "DLMC": "水田",
                },
            }],
        }
        parcels, warnings = ingest_landuse(geojson, layer_type="current_landuse")
        assert len(parcels) == 1
        p = parcels[0]
        assert "DLBM" in p.mapping_provenance
        prov = p.mapping_provenance["DLBM"]
        assert prov["decided_by"] == "rule"
        assert prov["confidence"] == "exact"
        assert "SDDLBM" in p.mapping_provenance

    def test_ingest_planned_parcel_provenance(self):
        from app.modules.data.ingest import ingest_landuse
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {
                    "BSM": "002",
                    "DLBM": "0110",
                    "GHYTBM": "0101",
                    "GHFLBM": "01",
                    "DLMC": "水田",
                },
            }],
        }
        parcels, warnings = ingest_landuse(geojson, layer_type="planned_landuse")
        assert len(parcels) == 1
        p = parcels[0]
        assert "DLBM" in p.mapping_provenance
        assert "GHYTBM" in p.mapping_provenance
        assert "GHFLBM" in p.mapping_provenance