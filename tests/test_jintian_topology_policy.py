from __future__ import annotations

import json
from pathlib import Path

from app.data.resource_catalog import DataResourceCatalog


def test_jintian_landuse_repair_keeps_strict_type_and_audits_feature_343():
    payload = json.loads(
        Path("data/gis/jintian/current/landuse.geojson").read_text(
            encoding="utf-8-sig"
        )
    )
    raw = payload["features"][343]
    catalog = DataResourceCatalog.from_records(
        [{"geometry": raw["geometry"], "properties": raw.get("properties") or {}}],
        dataset_ref="jintian:current:landuse",
        crs="EPSG:4326",
    )
    feature = catalog.snapshot.features[0]
    audit = feature.topology_repair_audit
    assert audit["policy"] == "strict_geometry_type"
    assert audit["source_geometry_type"] == audit["repaired_geometry_type"]
    assert audit["source_part_count"] != audit["repaired_part_count"]
    assert audit["review_required"] is True
    assert feature.normalized_geometry is not None
