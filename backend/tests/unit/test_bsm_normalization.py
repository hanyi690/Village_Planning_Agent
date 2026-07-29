"""Tests for BSM normalization in VillageBundle.add().

Every feature entering the bundle must have a unique non-empty BSM.
Empty or duplicate BSMs are replaced with synthetic unique IDs.
"""
import pytest
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.base import PolygonFeature


class _DummyPolygon(PolygonFeature):
    layer_type: str = "farmland_protection"


def _make_polygon(bsm: str = ""):
    return _DummyPolygon(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm=bsm,
    )


class TestBSMNormalization:
    def test_empty_bsm_gets_synthetic_id(self):
        bundle = VillageBundle(village_name="test")
        f = _make_polygon(bsm="")
        bundle.add(f)
        assert f.bsm != ""
        assert "farmland_protection" in f.bsm

    def test_duplicate_bsm_gets_disambiguated(self):
        bundle = VillageBundle(village_name="test")
        f1 = _make_polygon(bsm="12345")
        f2 = _make_polygon(bsm="12345")
        bundle.add(f1)
        bundle.add(f2)
        assert f1.bsm == "12345"
        assert f2.bsm != "12345"
        assert f2.bsm != ""

    def test_unique_bsm_preserved(self):
        bundle = VillageBundle(village_name="test")
        f1 = _make_polygon(bsm="AAA")
        f2 = _make_polygon(bsm="BBB")
        bundle.add(f1)
        bundle.add(f2)
        assert f1.bsm == "AAA"
        assert f2.bsm == "BBB"

    def test_cross_layer_type_bsm_independence(self):
        bundle = VillageBundle(village_name="test")
        p = _make_polygon(bsm="999")
        from app.modules.schema.types.spatial_types import CurrentRoad
        r = CurrentRoad(
            geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            bsm="999",
        )
        bundle.add(p)
        bundle.add(r)
        assert p.bsm == "999"
        assert r.bsm == "999"

    def test_all_features_unique_after_batch_add(self):
        bundle = VillageBundle(village_name="test")
        bsms_out = set()
        for i in range(10):
            f = _make_polygon(bsm="" if i < 3 else "dup")
            bundle.add(f)
            bsms_out.add(f.bsm)
        assert len(bsms_out) == 10
        assert "" not in bsms_out


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