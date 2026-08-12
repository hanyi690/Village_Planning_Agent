from types import SimpleNamespace

from app.data.model.snapshot import SessionDataSnapshot
from app.spatial.model.workspace import SpatialWorkspace


def test_data_snapshot_is_manifest_only_and_workspace_is_spatial_input():
    current = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"BSM": "P1"}, "geometry": {}}],
    }
    bundle = SimpleNamespace(
        village_name="金田",
        metadata=SimpleNamespace(),
        points=SimpleNamespace(),
        lines=SimpleNamespace(),
        polygons=SimpleNamespace(get=lambda key: []),
        rasters=SimpleNamespace(),
        tables=SimpleNamespace(),
        to_geojson_dict=lambda: {"landuse_current_geojson": current},
    )

    snapshot = SessionDataSnapshot.from_bundle(bundle, session_id="s1")
    workspace = SpatialWorkspace(snapshot, bundle)

    assert snapshot.collection("landuse_current_geojson").feature_count == 1
    assert snapshot.digest.startswith("sha256:")
    assert "features" not in snapshot.model_dump(mode="json")
    assert workspace.snapshot.digest == snapshot.digest
    assert workspace.to_delivery_inputs()["landuse_current_geojson"] == current
