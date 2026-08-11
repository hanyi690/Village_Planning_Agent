from app.modules.schema.types.canonical import VillageBundle, from_bundle_dict, to_bundle_dict
from app.modules.schema.types.spatial_types import CurrentLandUseParcel


def _parcel(bsm=""):
    return CurrentLandUseParcel(
        bsm=bsm,
        geometry={
            "type": "Polygon",
            "coordinates": [[[116.0, 24.0], [116.001, 24.0], [116.001, 24.001], [116.0, 24.0]]],
        },
        dlbm="1100",
    )


def test_bundle_preserves_source_bsm_identity():
    source_bsm = "441426211000049104"
    parcel = _parcel(source_bsm)

    bundle = VillageBundle(village_name="test")
    bundle.add(parcel)

    assert bundle.polygons.get("landuse_current")[0].bsm == source_bsm


def test_fifteen_digit_bsm_is_preserved():
    source_bsm = "441426211004910"
    parcel = _parcel(source_bsm)

    bundle = VillageBundle(village_name="test")
    bundle.add(parcel)

    assert bundle.polygons.get("landuse_current")[0].bsm == source_bsm


def test_missing_bsm_generates_synthetic():
    bundle = VillageBundle(village_name="test")
    bundle.add(_parcel(""))

    synthetic = bundle.polygons.get("landuse_current")[0].bsm
    assert len(synthetic) == 20
    assert synthetic.isdigit()


def test_bsm_counter_restored_after_deserialization():
    bundle = VillageBundle(village_name="test")
    for i in range(5):
        bundle.add(_parcel(f"441426211000{49100 + i}"))

    restored = from_bundle_dict(to_bundle_dict(bundle))
    restored.add(_parcel(""))

    bounds = {bundle.polygons.get("landuse_current")[i].bsm for i in range(5)}
    new_bsm = restored.polygons.get("landuse_current")[5].bsm
    assert new_bsm not in bounds
    assert len(new_bsm) == 20
    assert new_bsm.isdigit()
