"""Golden KG snapshot regression test.

Builds KG from jintian real data and compares Turtle output against
a checked-in golden snapshot. Drift = test failure -> review required.

This is Phase 0 of the v4 proposal (baseline freeze).

Data loading note:
  The DataCatalog.load_village_bundle() path is currently broken for the
  jintian village (urban_dev_boundary WMS source returns image data that
  the features adapter rejects as non-GeoJSON). Until that is fixed, this
  test builds the VillageBundle directly from the checked-in local GeoJSON
  files via the ingest_* helpers, which is the same typed pipeline the
  catalog uses for file_vector sources. This yields the same KG that the
  E2E test (test_kg_jintian_e2e.py) intends to build.

Usage:
  cd F:/project/Village_Planning_Agent
  python -m pytest backend/tests/integration/test_golden_kg_snapshot.py -v --tb=short

  Or directly:
  cd backend
  python -m pytest tests/integration/test_golden_kg_snapshot.py -v --tb=short
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure backend is on path when run as script
# tests/integration/test_golden_kg_snapshot.py -> parents[2] = backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Project root must be cwd for relative data paths (data/gis/jintian/...)
_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

# Path to the checked-in jintian GeoJSON data.
_JINTIAN_DATA = _PROJECT_ROOT / "data" / "gis" / "jintian"


# ── Module-scoped fixture (built once, shared across tests) ──────────


@pytest.fixture(scope="module")
def golden_kg():
    """Build KG from jintian local GeoJSON files.

    Mirrors the kg_main fixture in test_kg_jintian_e2e.py: Layer 1+2 only
    (no L3 intent, no L4 planned state). Uses direct ingest_* calls instead
    of DataCatalog because the catalog's urban_dev_boundary WMS source is
    currently broken (see module docstring).
    """
    from app.modules.data.ingest import ingest_current_landuse, ingest_feature
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import PlanningKG
    from app.modules.kg.builder.layer4 import ingest_planned_state_from_geojson

    bundle = VillageBundle(village_name="jintian")

    # Layer 1: current landuse parcels (660 parcels)
    parcels, _ = ingest_current_landuse(str(_JINTIAN_DATA / "current" / "landuse.geojson"))
    for p in parcels:
        bundle.add(p)

    # Layer 1: current roads (131 roads)
    roads, _ = ingest_feature(
        str(_JINTIAN_DATA / "current" / "road.geojson"), "current_road"
    )
    for r in roads:
        bundle.add(r)

    # Layer 1: current annotations (34 annotations)
    anns, _ = ingest_feature(
        str(_JINTIAN_DATA / "current" / "annotation.geojson"), "current_annotation"
    )
    for a in anns:
        bundle.add(a)

    # Constraint reference polygons (planned/ folder)
    for feature_type, filename in [
        ("farmland_protection", "farmland_protection.geojson"),
        ("ecological_redline", "ecological_protection.geojson"),
        ("historical_protection", "historical_protection.geojson"),
    ]:
        feats, _ = ingest_feature(
            str(_JINTIAN_DATA / "planned" / filename), feature_type
        )
        for f in feats:
            bundle.add(f)

    # Admin boundary
    boundary, _ = ingest_feature(
        str(_JINTIAN_DATA / "current" / "boundary.geojson"), "admin_area"
    )
    for b in boundary:
        bundle.add(b)

    assert bundle.parcel_count > 0, "No parcels loaded from jintian GeoJSON"

    # Spatial relations + constraint index (same as E2E kg_main fixture)
    parcel_relations = compute_parcel_relations(
        bundle.polygons.get("landuse_current"),
        roads=bundle.lines.get("roads_current"),
    )
    constraint_index = build_constraint_index(bundle)

    # L4 planned state from GeoJSON
    planned_state = ingest_planned_state_from_geojson(_JINTIAN_DATA)

    # Assign BSMs to planned parcels using bundle's counter
    for p in planned_state.parcels:
        bundle._assign_bsm(p)

    kg = PlanningKG(village_name="jintian")
    kg.build_from_bundle(
        bundle=bundle,
        parcel_relations=parcel_relations,
        constraint_index=constraint_index,
        planned_state=planned_state,
    )
    return kg


class TestGoldenKGSnapshot:
    """Golden bundle + golden KG snapshot regression.

    On first run (no snapshot checked in) the tests CREATE the snapshot
    files and SKIP. Review the generated artifacts, commit them, and
    re-run to verify the baseline passes. Any subsequent drift fails
    the test until the snapshot is intentionally updated.
    """

    def test_golden_turtle_matches_snapshot(self, golden_kg):
        """KG Turtle output must match checked-in golden snapshot.

        If this test fails on the first run (snapshot doesn't exist),
        it creates the snapshot and skips. Review the snapshot, commit
        it, then re-run to verify it passes.

        rdflib Turtle serialization is deterministic (sorted subjects /
        predicates / objects), so identical data + identical builder code
        produces byte-identical output across runs.
        """
        golden_dir = Path(__file__).parent / "fixtures" / "golden"
        golden_dir.mkdir(parents=True, exist_ok=True)
        golden_path = golden_dir / "jintian_kg_snapshot.ttl"

        actual = golden_kg.to_turtle()

        if not golden_path.exists():
            golden_path.write_text(actual, encoding="utf-8")
            pytest.skip(
                f"Golden snapshot created at {golden_path}. "
                "Review the content, then re-run this test to verify it passes."
            )

        expected = golden_path.read_text(encoding="utf-8")
        assert actual == expected, (
            "KG snapshot drift detected! The Turtle output has changed.\n"
            "If this is intentional (e.g. you changed the KG builder), "
            f"update the golden snapshot: {golden_path}\n"
            "If unexpected, investigate what changed in the KG build pipeline."
        )

    def test_golden_triple_count(self, golden_kg):
        """Triple count must match golden baseline."""
        golden_dir = Path(__file__).parent / "fixtures" / "golden"
        golden_path = golden_dir / "jintian_triple_count.txt"

        count = golden_kg.get_triple_count()

        if not golden_path.exists():
            golden_path.write_text(str(count))
            pytest.skip(f"Triple count baseline created: {count}")

        expected = int(golden_path.read_text().strip())
        assert count == expected, (
            f"Triple count drift: {count} != {expected} (golden baseline). "
            "If intentional, update the baseline file."
        )

    def test_golden_parcel_count(self, golden_kg):
        """Parcel count (pln:Parcel entities) must match golden baseline."""
        from rdflib import RDF
        from app.modules.kg.ontology import EntityTypes

        golden_dir = Path(__file__).parent / "fixtures" / "golden"
        golden_path = golden_dir / "jintian_parcel_count.txt"

        count = len(list(golden_kg.g.subjects(RDF.type, EntityTypes.Parcel)))

        if not golden_path.exists():
            golden_path.write_text(str(count))
            pytest.skip(f"Parcel count baseline created: {count}")

        expected = int(golden_path.read_text().strip())
        assert count == expected, (
            f"Parcel count drift: {count} != {expected}. "
            "If intentional, update the baseline file."
        )

    def test_golden_predicate_distribution(self, golden_kg):
        from rdflib import Namespace
        from app.modules.kg.ontology import Relations

        GEO = Namespace("http://www.opengis.net/ont/geosparql#")

        def _count(pred):
            return len(list(golden_kg.g.triples((None, pred, None))))

        assert _count(Relations.sfTouches) == 3382, "sfTouches drift"
        assert _count(Relations.nearby) == 6048, "nearby drift"
        assert _count(Relations.connected_via_road) == 361, "connected_via_road drift"
        assert _count(Relations.sfWithin) == 1190, "sfWithin drift"
        assert _count(Relations.sfIntersects) == 1261, "sfIntersects drift"
        assert _count(Relations.sfContains) == 0, "sfContains drift"
        assert _count(Relations.derived_from) == 0, "derived_from drift (L1 snapshot has no L4)"
        assert _count(Relations.serves) == 0, "serves drift"

        assert _count(GEO.hasGeometry) == 0, "geo:hasGeometry must be 0 (VKG decision)"
        assert _count(GEO.asWKT) == 0, "geo:asWKT must be 0 (VKG decision)"
