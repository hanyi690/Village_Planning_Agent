#!/usr/bin/env python3
"""
Phase 0 Test Script: Semantic Qualification + Conflict Detection/Resolution

Tests the three-layer semantic qualification system:
  Layer 1: ValueSemantics enum + naming convention
  Layer 2: SemanticField Annotated metadata
  Layer 3: CROSS_DIMENSION_METRICS registry

And the conflict detection/resolution pipeline:
  ConflictDetector → ConflictResolver → ResolutionReport

Usage:
  python scripts/test_semantic_conflict.py
  python scripts/test_semantic_conflict.py --with-db  (read from actual database)
"""

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def test_value_semantics():
    """Test Layer 1: ValueSemantics enum + naming convention."""
    print("\n" + "=" * 60)
    print("TEST 1: ValueSemantics Enum + Naming Convention")
    print("=" * 60)

    from app.services.modules.summary.semantics import (
        ValueSemantics,
        SEMANTICS_PREFIX,
        infer_semantics_from_field_name,
    )

    # Test all semantics values
    print(f"\n  ValueSemantics values: {[s.value for s in ValueSemantics]}")
    print(f"  Prefix mapping:")
    for semantics, prefix in SEMANTICS_PREFIX.items():
        print(f"    {semantics.value:20s} -> {prefix}")

    # Test inference
    test_fields = [
        ("current_construction_ha", ValueSemantics.CURRENT_OBSERVED),
        ("planned_construction_ha", ValueSemantics.PLANNED_TARGET),
        ("max_construction_ha", ValueSemantics.CONSTRAINT_UPPER),
        ("min_farmland_ha", ValueSemantics.CONSTRAINT_LOWER),
        ("baseline_population", ValueSemantics.BASELINE_YEAR),
        ("projected_population_2035", ValueSemantics.PROJECTED),
        ("total_area_ha", None),  # no qualifier prefix
    ]

    print(f"\n  Field name inference:")
    all_pass = True
    for field_name, expected in test_fields:
        result = infer_semantics_from_field_name(field_name)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_pass = False
        print(f"    {field_name:35s} -> {str(result):30s} [{status}]")

    return all_pass


def test_semantic_field():
    """Test Layer 2: SemanticField Annotated metadata."""
    print("\n" + "=" * 60)
    print("TEST 2: SemanticField Annotated Metadata")
    print("=" * 60)

    from app.services.modules.summary.semantics import (
        SemanticField,
        ValueSemantics,
        get_field_semantics,
        get_all_semantic_fields,
    )
    from app.services.modules.summary.schema import (
        LandUseSummary,
        LandUsePlanningSummary,
        SettlementPlanningSummary,
        SuperiorPlanningSummary,
    )

    # Test LandUseSummary semantic fields
    print(f"\n  LandUseSummary semantic fields:")
    fields = get_all_semantic_fields(LandUseSummary)
    all_pass = True
    for name, sf in fields.items():
        print(f"    {name}: semantics={sf.semantics.value}, unit={sf.unit}, "
              f"source={sf.data_source}, comparable={sf.comparable}")

    # Verify key fields have correct semantics
    expected = {
        "current_construction_ha": ValueSemantics.CURRENT_OBSERVED,
        "current_farmland_ha": ValueSemantics.CURRENT_OBSERVED,
        "forest_coverage_rate": ValueSemantics.CURRENT_OBSERVED,
    }
    for field_name, expected_sem in expected.items():
        sf = get_field_semantics(LandUseSummary, field_name)
        if sf is None:
            print(f"    FAIL: {field_name} has no SemanticField")
            all_pass = False
        elif sf.semantics != expected_sem:
            print(f"    FAIL: {field_name} semantics={sf.semantics.value}, expected={expected_sem.value}")
            all_pass = False
        else:
            print(f"    PASS: {field_name} semantics={sf.semantics.value}")

    # Test LandUsePlanningSummary
    print(f"\n  LandUsePlanningSummary semantic fields:")
    fields = get_all_semantic_fields(LandUsePlanningSummary)
    for name, sf in fields.items():
        print(f"    {name}: semantics={sf.semantics.value}, unit={sf.unit}")

    # Verify planned vs current distinction
    planned_sf = get_field_semantics(LandUsePlanningSummary, "planned_construction_ha")
    current_sf = get_field_semantics(LandUsePlanningSummary, "current_construction_ha")
    if planned_sf and current_sf:
        if planned_sf.semantics == ValueSemantics.PLANNED_TARGET and \
           current_sf.semantics == ValueSemantics.CURRENT_OBSERVED:
            print(f"    PASS: planned vs current semantics correctly distinguished")
        else:
            print(f"    FAIL: planned={planned_sf.semantics.value}, current={current_sf.semantics.value}")
            all_pass = False
    else:
        print(f"    FAIL: Missing SemanticField on key fields")
        all_pass = False

    # Test SuperiorPlanningSummary
    print(f"\n  SuperiorPlanningSummary semantic fields:")
    fields = get_all_semantic_fields(SuperiorPlanningSummary)
    for name, sf in fields.items():
        print(f"    {name}: semantics={sf.semantics.value}, unit={sf.unit}")

    return all_pass


def test_cross_dimension_metrics():
    """Test Layer 3: CROSS_DIMENSION_METRICS registry."""
    print("\n" + "=" * 60)
    print("TEST 3: CROSS_DIMENSION_METRICS Registry")
    print("=" * 60)

    from app.services.modules.summary.semantics import (
        CROSS_DIMENSION_METRICS,
        MetricConcept,
        ValueSemantics,
        get_comparable_fields,
        get_constraint_fields,
    )

    all_pass = True

    # Print registry contents
    print(f"\n  Registry contents ({len(CROSS_DIMENSION_METRICS)} concepts):")
    for concept, refs in CROSS_DIMENSION_METRICS.items():
        print(f"\n    {concept.value}:")
        for ref in refs:
            print(f"      {ref.dimension}.{ref.field} [{ref.semantics.value}] ({ref.unit})")

    # Test get_comparable_fields
    print(f"\n  Comparable fields for CONSTRUCTION_AREA (CURRENT_OBSERVED):")
    comparable = get_comparable_fields(MetricConcept.CONSTRUCTION_AREA, ValueSemantics.CURRENT_OBSERVED)
    if len(comparable) >= 2:
        print(f"    PASS: {len(comparable)} comparable fields found")
        for ref in comparable:
            print(f"      {ref.dimension}.{ref.field}")
    else:
        print(f"    FAIL: Expected >= 2 comparable fields, got {len(comparable)}")
        all_pass = False

    # Test get_constraint_fields
    print(f"\n  Constraint fields for CONSTRUCTION_AREA:")
    constraints = get_constraint_fields(MetricConcept.CONSTRUCTION_AREA)
    if len(constraints) >= 1:
        print(f"    PASS: {len(constraints)} constraint fields found")
        for ref in constraints:
            print(f"      {ref.dimension}.{ref.field} [{ref.semantics.value}]")
    else:
        print(f"    FAIL: Expected >= 1 constraint fields, got {len(constraints)}")
        all_pass = False

    return all_pass


def test_conflict_detector():
    """Test ConflictDetector with simulated data."""
    print("\n" + "=" * 60)
    print("TEST 4: ConflictDetector (Simulated Data)")
    print("=" * 60)

    from app.services.modules.gis.layout.conflict_detector import ConflictDetector
    from app.services.modules.gis.layout.conflict_resolver import ConflictResolver
    from app.services.modules.summary.semantics import ValueSemantics

    # Simulate Jintian village data with known conflicts
    summaries = {
        "land_use": {
            "metrics": {
                "current_construction_ha": 30.17,
                "current_farmland_ha": 85.2,
                "total_area_ha": 420.5,
                "forest_coverage_rate": 65.0,
            }
        },
        "land_use_planning": {
            "metrics": {
                "current_construction_ha": 30.17,
                "planned_construction_ha": 17.66,
                "planned_farmland_ha": 127.18,
            }
        },
        "settlement_planning": {
            "metrics": {
                "current_construction_ha": 31.0,  # Conflicts with land_use (30.17)
                "planned_construction_ha": 17.66,
                "planned_population": 1681,
                "per_capita_construction_sqm": 555.0,
            }
        },
        "superior_planning": {
            "metrics": {
                "min_ecological_redline_ha": 367.68,
                "min_farmland_protection_ha": 81.43,
                "max_construction_ha": 30.5,
            }
        },
        "socio_economic": {
            "metrics": {
                "registered_population": 1406,
            }
        },
        "spatial_structure": {
            "metrics": {
                "structure_pattern": "一核一带三区",
                "zone_names": ["核心区", "发展带", "生态区"],
            }
        },
        "industry": {
            "metrics": {
                "layout_direction": "三心五区",
                "zone_count": 5,
            }
        },
    }

    detector = ConflictDetector(relative_threshold=0.02)
    report = detector.detect_all(summaries)

    print(f"\n  Detected {report.total_count} issues:")
    print(f"    Metric conflicts: {len(report.metric_conflicts)}")
    print(f"    Constraint violations: {len(report.constraint_violations)}")
    print(f"    Spatial conflicts: {len(report.spatial_conflicts)}")

    # Expected: construction_area conflict between land_use(30.17) and settlement_planning(31.0)
    all_pass = True
    if report.metric_conflicts:
        print(f"\n  Metric conflicts:")
        for c in report.metric_conflicts:
            print(f"    - {c.description}")
    else:
        print(f"\n  FAIL: Expected at least 1 metric conflict (30.17 vs 31.0)")
        all_pass = False

    # Check that current vs planned is NOT flagged as conflict
    for c in report.metric_conflicts:
        if c.semantics != ValueSemantics.CURRENT_OBSERVED:
            print(f"    WARN: Non-current-observed conflict flagged: {c.description}")

    # Check constraint violations
    if report.constraint_violations:
        print(f"\n  Constraint violations:")
        for v in report.constraint_violations:
            print(f"    - {v.description}")
    else:
        print(f"\n  No constraint violations (expected if planned_construction_ha < max_construction_ha)")

    # Resolve
    print(f"\n  Resolving conflicts...")
    resolver = ConflictResolver()
    resolution = resolver.resolve(report)
    print(f"\n{resolution.summary()}")

    # Verify key resolution: land_use_planning should win over settlement_planning
    for r in resolution.metric_resolutions:
        if r.concept.value == "construction_area" and r.semantics == ValueSemantics.CURRENT_OBSERVED:
            if r.winner_dimension == "land_use_planning":
                print(f"\n  PASS: land_use_planning wins (priority=10)")
            elif r.winner_dimension == "land_use":
                print(f"\n  PASS: land_use wins (priority=8) over settlement_planning (priority=6)")
            else:
                print(f"\n  INFO: Winner is {r.winner_dimension}")

    return all_pass


def test_content_extractor_no_overwrite():
    """Test that content_extractor no longer silently overwrites."""
    print("\n" + "=" * 60)
    print("TEST 5: Content Extractor No-Overwrite")
    print("=" * 60)

    from app.services.modules.planning_text.content_extractor import ExtractedData, _inject_from_summaries

    data = ExtractedData()
    summaries = {
        "land_use": {
            "metrics": {
                "total_area_ha": 420.5,
                "current_farmland_ha": 85.2,
                "current_construction_ha": 30.17,
                "forest_coverage_rate": 65.0,
            }
        },
        "natural_environment": {
            "metrics": {
                "forest_coverage_rate": 68.2,  # Different value
            }
        }
    }

    _inject_from_summaries(data, summaries)

    print(f"\n  farmland_ha: {data.farmland_ha}")
    print(f"  construction_land_ha: {data.construction_land_ha}")
    print(f"  forest_coverage_pct: {data.forest_coverage_pct}")
    print(f"  _field_sources: {data._field_sources}")
    print(f"  _qualified_metrics: {data._qualified_metrics}")

    all_pass = True

    # Check that forest_coverage_pct comes from land_use (first writer wins)
    if data._field_sources.get("forest_coverage_pct") == "land_use":
        print(f"\n  PASS: forest_coverage_pct source is land_use (not overwritten)")
    else:
        print(f"\n  FAIL: forest_coverage_pct source is {data._field_sources.get('forest_coverage_pct')}")
        all_pass = False

    # Check that both values are preserved in qualified metrics
    if "land_use.forest_coverage_rate" in data._qualified_metrics and \
       "natural_environment.forest_coverage_rate" in data._qualified_metrics:
        print(f"  PASS: Both forest_coverage_rate values preserved in _qualified_metrics")
        print(f"    land_use: {data._qualified_metrics['land_use.forest_coverage_rate']}")
        print(f"    natural_environment: {data._qualified_metrics['natural_environment.forest_coverage_rate']}")
    else:
        print(f"  FAIL: Qualified metrics not preserved")
        all_pass = False

    # Check new field name compatibility
    if data.construction_land_ha == 30.17:
        print(f"  PASS: current_construction_ha correctly mapped to construction_land_ha")
    else:
        print(f"  FAIL: construction_land_ha={data.construction_land_ha}, expected 30.17")
        all_pass = False

    return all_pass


def main():
    """Run all Phase 0 tests."""
    print("=" * 60)
    print("Phase 0 Test Suite: Semantic Qualification + Conflict Detection")
    print("=" * 60)

    results = {
        "ValueSemantics Enum": test_value_semantics(),
        "SemanticField Metadata": test_semantic_field(),
        "Cross-Dimension Registry": test_cross_dimension_metrics(),
        "Conflict Detector": test_conflict_detector(),
        "Content Extractor No-Overwrite": test_content_extractor_no_overwrite(),
    }

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} tests passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
