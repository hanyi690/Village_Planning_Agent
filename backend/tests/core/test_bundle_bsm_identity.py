from app.data.model.canonical import VillageBundle, from_bundle_dict, to_bundle_dict
from app.data.model.spatial_types import CurrentLandUseParcel


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


def test_bundle_serializes_report_manifest_without_report_bodies():
    bundle = VillageBundle(village_name="test")
    bundle.documents.document_refs = [{
        "source": "task_description",
        "name": "任务描述",
        "record_id": "session-1",
        "content_digest": "sha256:abc",
        "char_count": 12,
    }]
    bundle.documents.report_refs = [{
        "layer": 1,
        "dimension_key": "location",
        "report_id": "report-1",
        "version": 2,
        "summary": "compact summary",
    }]

    payload = to_bundle_dict(bundle)

    assert "layer_reports" not in payload
    assert "l3_reports" not in payload["documents"]
    assert "content" not in payload["documents"]["document_refs"][0]
    assert payload["documents"]["document_refs"][0]["content_digest"] == "sha256:abc"
    assert payload["documents"]["report_refs"][0]["report_id"] == "report-1"
    assert "content" not in payload["documents"]["report_refs"][0]


def test_bundle_bsm_lookup_is_indexed_and_invalidated_on_add():
    bundle = VillageBundle(village_name="test")
    first = _parcel("441426211000049104")
    bundle.add(first)

    group, layer, feature = bundle.find_feature_by_bsm(first.bsm)
    assert (group, layer, feature) == ("polygons", "landuse_current", first)

    second = _parcel("441426211000049105")
    bundle.add(second)
    assert bundle.find_feature_by_bsm(second.bsm)[2] is second
