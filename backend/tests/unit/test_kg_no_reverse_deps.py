"""Test that KG module has no reverse dependencies on tools or agent.

Workstream B verification:
1. KG builder imports only from schema, not from tools or agent
2. compute_land_use_metrics works when imported from schema
3. resolve_zone_type_for_dlbm works when imported from schema
4. dlbm_to_planning_zone works when imported from schema
5. SpatialPlanningIntent can be constructed from schema
6. Static analysis: no import from app.tools or app.agent in kg/
7. build_from_intent works with typed SpatialPlanningIntent
8. build_from_intent works with dict auto-convert
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
    """Verify builder.py does not import from app.tools or app.agent."""
    builder_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "kg", "builder.py"
    )
    builder_path = os.path.normpath(builder_path)

    import re
    import_pattern = re.compile(r'^\s*from app\.(tools|agent)')
    violations = []
    with open(builder_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if import_pattern.match(line):
                violations.append(f"Line {lineno}: {line.strip()}")

    assert violations == [], (
        f"KG builder still has reverse dependencies:\n" + "\n".join(violations)
    )


def test_kg_builder_uses_schema_imports():
    """Verify builder.py uses schema imports for the previously reverse-dep functions."""
    builder_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "kg", "builder.py"
    )
    builder_path = os.path.normpath(builder_path)

    with open(builder_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check that schema imports are present
    assert "from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent" in content
    assert "from app.modules.schema.utils.metrics import compute_land_use_metrics" in content
    assert "from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm" in content
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


# ── build_from_intent with typed model ───────────────────────────────


def test_build_from_intent_typed():
    """Verify build_from_intent works with typed SpatialPlanningIntent."""
    from app.modules.kg.builder import PlanningKG
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
        ThreeZonesThreeLines, ThreeLineItem,
    )

    intent = SpatialPlanningIntent(
        village_name="测试村",
        zone_targets=[
            ZoneTarget(land_use="农田保护区", area_ratio=0.6, density="low"),
            ZoneTarget(land_use="村庄建设区", area_ratio=0.2, density="high"),
        ],
        facilities=[
            FacilityTarget(type="小学", status="existing_preserve", location_hint="村中心"),
        ],
        development_axes=[
            AxisTarget(direction="east-west", reference_feature="主干道", connects=["村庄建设区"]),
        ],
        construction_area_ha=50.0,
        farmland_area_ha=200.0,
        ecological_area_ha=100.0,
        three_zones_three_lines=ThreeZonesThreeLines(
            lines=[
                ThreeLineItem(line_type="ecological_redline", name="生态保护红线", area_ha=80.0),
            ]
        ),
    )

    kg = PlanningKG(village_name="测试村")
    kg.build_from_intent(intent, gis_data={"landuse_current_geojson": {"features": []}})

    assert kg.get_triple_count() > 0
    constraints = kg.get_constraints()
    # Should have intent-derived constraints (construction_cap, farmland_min, ecological_min, + three-line)
    constraint_ids = [c.get("id", "") for c in constraints]
    assert "intent_construction_cap" in constraint_ids
    assert "intent_farmland_min" in constraint_ids
    assert "intent_ecological_redline" in constraint_ids


def test_build_from_intent_dict_auto_convert():
    """Verify build_from_intent auto-converts dict to SpatialPlanningIntent."""
    from app.modules.kg.builder import PlanningKG

    intent_dict = {
        "village_name": "测试村",
        "zone_targets": [
            {"land_use": "农田保护区", "area_ratio": 0.6},
        ],
        "construction_area_ha": 30.0,
    }

    kg = PlanningKG(village_name="测试村")
    kg.build_from_intent(intent_dict, gis_data={"landuse_current_geojson": {"features": []}})

    assert kg.get_triple_count() > 0
    constraints = kg.get_constraints()
    constraint_ids = [c.get("id", "") for c in constraints]
    assert "intent_construction_cap" in constraint_ids
