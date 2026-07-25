"""Test that KG module has no reverse dependencies on tools or agent.

Workstream B verification (v4.4 updated):
1. KG builder imports only from schema, not from tools or agent
2. resolve_zone_type_for_dlbm works when imported from schema
3. dlbm_to_planning_zone works when imported from schema
4. SpatialCognitiveUnit hierarchy (PlanIntent/PlanBlock) can be constructed
5. Static analysis: no import from app.tools or app.agent in kg/ (incl builder/)
6. build_from_blocks works with typed PlanIntent (Layer 3)
7. build_from_blocks works with typed PlanBlock (Layer 4)
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
    assert dlbm_to_planning_zone("0101") == "一般农业区"


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

    # Check that schema imports are present (v4.4 path)
    assert "from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm" in content
    assert "from app.modules.schema.contracts.context_contracts import" in content
    assert "from app.modules.schema.encodings.code_sets import dlbm_to_planning_zone" in content


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


# ── build_from_blocks with typed PlanIntent (v4.4) ──────────────────


def test_build_from_blocks_with_typed_intent():
    """Verify build_from_blocks accepts typed PlanIntent (Layer 3)."""
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.context_contracts import (
        PlanIntent, ZoneTarget, FacilityTarget, RoadTarget,
        PlanningConstraint,
    )

    intent = PlanIntent(
        targets=[
            ZoneTarget(land_use_code="0101", target_area_ha=100.0,
                       min_area_ha=80.0, priority=1),
            FacilityTarget(name="小学", facility_type="教育",
                           min_area_sqm=400, priority=2),
            RoadTarget(name="规划路", road_level="村道", width_m=6, priority=3),
        ],
        hard_constraints=[
            PlanningConstraint(constraint_type="hard",
                               rule="耕地保有量不得减少", source="上位规划"),
        ],
    )

    kg = PlanningKG(village_name="测试村")
    # build_from_blocks with empty bundle/blocks but typed intent
    from app.modules.schema.types.canonical import VillageBundle
    bundle = VillageBundle(village_name="测试村")
    kg.build_from_blocks(blocks=[], bundle=bundle, parcel_relations=None,
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
    # Hard constraint written (Layer 3 hard_constraints use pln:description, not pln:field)
    hard = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?c ?desc ?src WHERE { "
        "?c a pln:Constraint ; pln:description ?desc ; pln:source ?src . }")
    assert len(hard) >= 1
    assert any("耕地" in h.get("desc", "") for h in hard)


def test_build_from_blocks_with_plan_block():
    """Verify build_from_blocks accepts typed PlanBlock (Layer 4 delta)."""
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.context_contracts import (
        PlanBlock, ParcelChange, FacilityChange, RoadChange,
    )
    from app.modules.schema.types.canonical import VillageBundle

    planned = PlanBlock(version="v1",
        parcel_changes=[
            ParcelChange(bsm="TEST_001", action="reclassify",
                               new_planning_land_use="2121",
                               new_area_ha=0.5, new_zone_type="村庄建设区"),
        ],
        facility_changes=[
            FacilityChange(name="展销中心", facility_type="商业",
                                 area_sqm=400, center=(113.5, 23.5)),
        ],
        road_changes=[
            RoadChange(name="规划路", road_level="主干道", width_m=12),
        ],
    )

    kg = PlanningKG(village_name="测试村")
    bundle = VillageBundle(village_name="测试村")
    kg.build_from_blocks(blocks=[], bundle=bundle, parcel_relations=None,
                         plan_block=planned)

    # Layer 4: PlannedParcel entities (sparse - only changes)
    pp = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        "SELECT ?p ?bsm ?action WHERE { "
        "?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:change_action ?action . }")
    assert len(pp) == 1
    assert pp[0]["bsm"] == "TEST_001"
    assert pp[0]["action"] == "reclassify"
    # Facility added with version tag
    fac = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?f WHERE { ?f a pln:Facility ; pln:in_version "v1" . }')
    assert len(fac) == 1
    # Road added with version tag
    rd = kg.query(
        "PREFIX pln: <http://village-planning.org/ontology#> "
        'SELECT ?r WHERE { ?r a pln:Road ; pln:in_version "v1" . }')
    assert len(rd) == 1
