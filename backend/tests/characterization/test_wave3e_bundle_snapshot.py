from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.data.model.canonical import VillageBundle
from app.data.model.snapshot import SessionDataSnapshot
from app.data.ingestion.adapters import ADAPTERS
from app.infrastructure.storage.bundle_store import BundleStore


ROOT = Path(__file__).resolve().parents[3]
ANNOTATION_PATH = ROOT / "data/gis/jintian/current/annotation.geojson"
ROAD_PATH = ROOT / "data/gis/jintian/current/road.geojson"


def _source_bundle() -> VillageBundle:
    """Build only from checked-in local vector sources; no DB/API/enrichment."""
    from app.data.model.layer_registry import GIS_LAYER_REGISTRY

    bundle = VillageBundle(village_name="金田")
    for path, layer_type in (
        (ANNOTATION_PATH, "current_annotation"),
        (ROAD_PATH, "current_road"),
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = GIS_LAYER_REGISTRY[layer_type]
        result = ADAPTERS[entry.ingest.adapter].load(
            payload,
            entry,
            source_uri=path.resolve().as_uri(),
        )
        for feature in result.features:
            bundle.add(feature)
    return bundle


def test_real_jintian_source_bundle_has_auditable_point_line_manifest() -> None:
    bundle = _source_bundle()

    assert len(bundle.points.get("annotations_current")) == 34
    assert len(bundle.lines.get("roads_current")) == 131
    snapshot = SessionDataSnapshot.from_bundle(
        bundle,
        session_id="wave3e-local",
        source="data_catalog",
    )

    annotation = snapshot.collection("annotation_geojson")
    road = snapshot.collection("road_geojson")
    assert annotation is not None and road is not None
    assert annotation.source_feature_count == 34
    assert road.source_feature_count == 131
    assert annotation.source_uris == (ANNOTATION_PATH.resolve().as_uri(),)
    assert road.source_uris == (ROAD_PATH.resolve().as_uri(),)
    assert len(annotation.source_feature_ids) == 34
    assert len(road.source_feature_ids) == 131
    assert all(item.startswith("http://village-planning.org/source-feature/v1/")
               for item in annotation.source_feature_ids + road.source_feature_ids)
    assert snapshot.digest.startswith("sha256:")
    assert ANNOTATION_PATH.resolve().as_uri() in snapshot.source_refs
    assert ROAD_PATH.resolve().as_uri() in snapshot.source_refs


def test_bundle_store_round_trip_restores_source_manifest_and_geometry() -> None:
    bundle = _source_bundle()
    bundle.metadata.session_id = "wave3e-local"
    serialized = BundleStore.serialize(bundle)
    restored = BundleStore.deserialize(serialized)

    persisted = getattr(restored, "source_snapshot", None)
    assert persisted is not None
    assert persisted.digest == SessionDataSnapshot.from_bundle(
        restored,
        session_id="wave3e-local",
    ).digest
    assert persisted.collection("annotation_geojson").source_feature_count == 34
    assert persisted.collection("road_geojson").source_feature_count == 131
    assert (
        restored.points.get("annotations_current")[0]._raw["source_feature_id"]
        == bundle.points.get("annotations_current")[0]._raw["source_feature_id"]
    )
    assert (
        restored.lines.get("roads_current")[0].geometry
        == bundle.lines.get("roads_current")[0].geometry
    )


def test_context_ref_carries_restored_snapshot_identity() -> None:
    bundle = _source_bundle()
    snapshot = SessionDataSnapshot.from_bundle(
        bundle,
        session_id="wave3e-local",
    )
    context = SimpleNamespace(
        version=7,
        data_snapshot=snapshot,
        snapshot_meta=lambda: {
            "data_snapshot_id": snapshot.snapshot_id,
            "data_snapshot_digest": snapshot.digest,
            "source_feature_manifest": [
                {
                    "key": item.key,
                    "source_feature_count": item.source_feature_count,
                    "source_feature_digest": item.source_feature_digest,
                }
                for item in snapshot.collections
            ],
        },
    )
    from app.workflow.stages.support import _adopt_context

    state = {"session_id": "wave3e-local"}
    patch = _adopt_context(state, context)
    assert patch["context_ref"]["snapshot_id"] == snapshot.snapshot_id
    assert patch["context_ref"]["snapshot_digest"] == snapshot.digest
