"""Tests for BSM normalization in VillageBundle.add().

Non-empty BSMs are preserved as-is. Empty BSMs get a synthetic 20-digit ID.

Note: These tests focus on ingest alias mapping (chinese field -> english)
and L4 planned-state URI uniqueness, which are the non-trivial BSM behaviors.
"""
import pytest
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.base import PolygonFeature


class _DummyPolygon(PolygonFeature):
    layer_type: str = "farmland_protection"


class TestIngestFeatureAliasMapping:
    def test_annotation_chinese_fields_mapped(self):
        from app.modules.data.ingest import ingest_feature
        import tempfile, json, os

        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.0, 24.8]},
                "properties": {"注记": "篮", "分类": "现状设施点"},
            }],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False, encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
            f.flush()
            filepath = f.name

        try:
            feats, _ = ingest_feature(filepath, "current_annotation")
            assert len(feats) == 1
            assert feats[0].text == "篮"
            assert feats[0].category == "现状设施点"
        finally:
            os.unlink(filepath)


class TestL4PlannedStateUniqueIDs:
    def test_planned_parcel_all_unique_uris(self):
        from app.modules.kg.builder.layer4 import PlannedParcelEntry, PlannedState
        from app.modules.kg.ontology import EntityIdPolicy

        entries = []
        for i in range(582):
            if i < 125:
                entries.append(PlannedParcelEntry(bsm=""))
            elif i < 125 + 96:
                entries.append(PlannedParcelEntry(bsm="3020550"))
            else:
                entries.append(PlannedParcelEntry(bsm=f"unique_{i}"))

        state = PlannedState(parcels=entries)
        uris = set()
        bsm_seq: dict[str, int] = {}
        for p in state.parcels:
            bsm = p.bsm
            seq = bsm_seq.get(bsm, 0)
            bsm_seq[bsm] = seq + 1
            uri = str(EntityIdPolicy.uri_with_seq("planned_parcel", bsm, seq, "current"))
            uris.add(uri)
        assert len(uris) == 582, f"Expected 582 unique URIs, got {len(uris)}"

    def test_planned_zone_all_unique_uris(self):
        from app.modules.kg.builder.layer4 import PlannedZoneEntry, PlannedState
        from app.modules.kg.ontology import EntityIdPolicy

        entries = [PlannedZoneEntry(zone_type="有条件建设区", name="建设区") for _ in range(139)]
        state = PlannedState(zones=entries)
        uris = set()
        zone_seq: dict[str, int] = {}
        for i, z in enumerate(state.zones):
            zone_id = z.zone_type or z.name or f"idx{i}"
            seq = zone_seq.get(zone_id, 0)
            zone_seq[zone_id] = seq + 1
            uri = str(EntityIdPolicy.uri_with_seq("planned_zone", zone_id, seq, "current"))
            uris.add(uri)
        assert len(uris) == 139, f"Expected 139 unique URIs, got {len(uris)}"