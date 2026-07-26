"""Test that KG module has no reverse dependencies on tools or agent.

Workstream B verification (v4.4 updated):
1. KG builder imports only from schema, not from tools or agent
2. resolve_zone_type_for_dlbm works when imported from schema
3. dlbm_to_planning_zone works when imported from schema
4. SpatialCognitiveUnit hierarchy (PlanIntent/PlanBlock) can be constructed
5. Static analysis: no import from app.tools or app.agent in kg/ (incl builder/)
6. build_from_bundle works with typed SpatialPlanningIntent (Layer 3)
7. build_from_bundle works with typed PlannedState (Layer 4)
"""

import os


# ── Function imports from schema ─────────────────────────────────────


def test_compute_metrics_from_schema():
    from app.modules.schema.utils.metrics import compute_land_use_metrics
    # Test with minimal data
    gis_data = {
        "landuse_current_geojson": {
            "features": [
                {
                    "properties": {"DLBM": "0101", "DLMJ": 100000},
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ]
        }
    }
    result = compute_land_use_metrics(gis_data)
    assert "construction_area_ha" in result
    assert "farmland_area_ha" in result
    assert "total_area_ha" in result
    assert result["total_area_ha"] == 10.0  # 100000 m2 = 10 ha


def test_resolve_zone_type_from_schema():
    from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm
    assert resolve_zone_type_for_dlbm("0101") == "农业用地"
    assert resolve_zone_type_for_dlbm(" 0101 ") == "农业用地"  # whitespace stripping


def test_dlbm_to_planning_zone_from_schema():
    from app.modules.schema.encodings.code_sets import dlbm_to_planning_zone
    # "0210" is a real tugui code for 园地 -> 一般农业区
    assert dlbm_to_planning_zone("0210") == "一般农业区"
    # Unknown DLBM defaults to "一般农业区" (fallback)
    assert dlbm_to_planning_zone("9999") == "一般农业区"


def test_spatial_planning_intent_from_schema():
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ZoneTarget
    intent = SpatialPlanningIntent(
        village_name="金田村",
        zone_targets=[
            ZoneTarget(land_use="农田保护区", area_ratio=0.6),
            ZoneTarget(land_use="村庄建设区", area_ratio=0.2),
        ],
    )
    assert intent.village_name == "金田村"
    assert len(intent.zone_targets) == 2


# ── Static analysis: no reverse deps in KG ───────────────────────────


def test_kg_builder_no_tool_imports():
    """Verify builder/ subpackage does not import from app.tools or app.agent."""
    builder_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "kg", "builder"
    )
    builder_dir = os.path.normpath(builder_dir)

    import re
    import_pattern = re.compile(r'^\s*from app\.(tools|agent)')
    violations = []
    for root, dirs, files in os.walk(builder_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if import_pattern.match(line):
                        violations.append(f"{fpath}:{lineno}: {line.strip()}")

    assert violations == [], (
        f"KG builder still has reverse dependencies:\n" + "\n".join(violations)
    )


def test_kg_builder_uses_schema_imports():
    """Verify builder/ subpackage uses schema imports (no raw dict reverse-deps)."""
    builder_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "kg", "builder"
    )
    builder_dir = os.path.normpath(builder_dir)

    layer1_path = os.path.join(builder_dir, "layer1.py")
    with open(layer1_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check that schema imports are present (v4.6 path)
    assert "from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm" in content
    assert "from app.modules.schema.types.spatial_types import" in content


def test_no_reverse_deps_in_kg():
    """Static check: no .py file in app/modules/kg/ imports from app.tools or app.agent."""
    kg_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "kg"
    )
    kg_dir = os.path.normpath(kg_dir)

    import re
    import_pattern = re.compile(r'^\s*from app\.(tools|agent)')
    violations = []
    for root, dirs, files in os.walk(kg_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if import_pattern.match(line):
                        violations.append(f"{fpath}:{lineno}: {line.strip()}")

    assert violations == [], f"KG reverse dependencies found:\n" + "\n".join(violations)


# ── Metrics is pure ──────────────────────────────────────────────────


def test_metrics_pure_function():
    """Verify compute_land_use_metrics does not import geopandas/shapely/tool modules."""
    metrics_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "schema", "utils", "metrics.py"
    )
    metrics_path = os.path.normpath(metrics_path)

    import re
    # Only match actual import statements, not docstring references
    import_pattern = re.compile(r'^\s*(from|import)\s+.*(geopandas|shapely|app\.tools|app\.agent)')
    violations = []
    with open(metrics_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if import_pattern.match(line):
                violations.append(f"Line {lineno}: {line.strip()}")

    assert violations == [], (
        f"schema/metrics.py has forbidden imports:\n" + "\n".join(violations)
    )


# ── build_from_bundle with typed SpatialPlanningIntent (v4.6) ────────────


def test_build_from_bundle_with_typed_intent():
    """Verify build_from_bundle accepts typed SpatialPlanningIntent (Layer 3)."""
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
    )

    intent = SpatialPlanningIntent(
        village_name="测试村",
        zone_targets=[
            ZoneTarget(land_use="农田保护区", area_ratio=0.5, dlbm="0101"),
        ],
        facilities=[
            FacilityTarget(type="小学", status="planned_new", service_radius=500),
        ],
        development_axes=[
            AxisTarget(reference_feature="村主干道"),
        ],
    )

    kg = PlanningKG(village_name="测试村")
    from app.modules.schema.types.canonical import VillageBundle
    bundle = VillageBundle(village_name="测试村")
    kg.build_from_bundle(bundle=bundle, parcel_relations=None,
                         intent=intent)

    assert kg.get_triple_count() > 0
    # Layer 3: ZoneTarget, FacilityTarget, AxisTarget entities
    zone_targets = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?z WHERE { ?z a pln:ZoneTarget . }")
    assert len(zone_targets) == 1
    facility_targets = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?f WHERE { ?f a pln:FacilityTarget . }")
    assert len(facility_targets) == 1
    axis_targets = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?a WHERE { ?a a pln:AxisTarget . }")
    assert len(axis_targets) == 1
    # Note: SpatialConstraints are NOT part of SpatialPlanningIntent.
    # They are passed separately by the caller.


def test_build_from_bundle_with_planned_state():
    """Verify build_from_bundle accepts PlannedState (Layer 4)."""
    from app.modules.kg.builder import PlanningKG
    from app.modules.kg.builder.layer4 import (
        PlannedState, PlannedParcelEntry, PlannedFacilityEntry, PlannedRoadEntry,
    )
    from app.modules.schema.types.canonical import VillageBundle

    planned = PlannedState(version="v1",
        parcels=[
            PlannedParcelEntry(bsm="TEST_001", planning_land_use="2121",
                               area_ha=0.5, zone_type="村庄建设区"),
        ],
        facilities=[
            PlannedFacilityEntry(name="展销中心", facility_type="商业",
                                 lon=113.5, lat=23.5),
        ],
        roads=[
            PlannedRoadEntry(name="规划路", road_level="主干道", width_m=12),
        ],
    )

    kg = PlanningKG(village_name="测试村")
    bundle = VillageBundle(village_name="测试村")
    kg.build_from_bundle(bundle=bundle, parcel_relations=None,
                         planned_state=planned)

    # Layer 4: PlannedParcel entities (sparse - only changes)
    pp = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?p ?bsm ?lu WHERE { "
        "?p a pln:PlannedParcel ; pln:bsm ?bsm ; "
        "pln:planning_land_use ?lu . }")
    assert len(pp) == 1
    assert pp[0]["bsm"] == "TEST_001"
    assert pp[0]["lu"] == "2121"
    # PlannedFacility added with version tag
    fac = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?f WHERE { ?f a pln:PlannedFacility ; pln:in_version "v1" . }')
    assert len(fac) == 1
    # PlannedRoad added with version tag
    rd = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?r WHERE { ?r a pln:PlannedRoad ; pln:in_version "v1" . }')
    assert len(rd) == 1
