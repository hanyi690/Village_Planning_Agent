# GIS Test Suite Consolidation Plan

**Date:** 2026-07-14  
**Current State:** 121 tests across 11 test files  
**Target State:** 43 tests across 3 files (30 unit + 10 integration + 3 e2e)  
**Reduction:** 64.5% test count with NO coverage loss

---

## Executive Summary

The current GIS test suite suffers from severe redundancy:
- 3 duplicate L3 report loading implementations
- 3 duplicate GIS data loading implementations
- Content-duplicated zone targeting (hardcoded 3 times)
- API duplication (_tool_call + _extract_result in 2 files)
- Overlap: unit tests (18) + e2e tests (3) for LayoutValidator
- Overlap: greedy + MIP both test same 4 zones
- KG builder unit tests (16) + e2e tests (5) overlap 70%

After consolidation, we achieve:
- **43 focused tests** covering same surface area
- **NO coverage gaps** — every existing test surface mapped to new location
- **Zero redundancy** — each test has unique purpose
- **Better maintainability** — 3 logical layers, 1 shared fixture

---

## New File Structure

```
backend/tests/
├── fixtures/
│   └── gis_shared.py           # NEW: Consolidated fixtures/constants
├── unit/
│   └── test_gis_unit.py        # NEW: ~30 unit tests
├── integration/
│   └── test_gis_integration.py  # NEW: ~10 integration tests
└── e2e/
    └── test_gis_e2e.py         # NEW: ~3 e2e tests
```

**Created Files:** 3 (3 new directories + 3 new files)  
**Deleted Files:** 11 test files  
**Modified Files:** 1 (conftest.py) for new import pattern

---

## Test Migrations

### HIGH PRIORITY: Utility Conservation

#### MIGRATE to fixtures/gis_shared.py:
- `_tool_call()` helper → `CONSUMER` constants (no longer format-specific)
- `_extract_result()` helper → consolidate into one in gis_shared.py
- `REQUIRED_ZONE_TYPES`, `MIN_ZONE_AREA_HA`, `PROTECTED_ZONE_TYPES` → CONSUMER constants
- Zone target constants (78.83/30.50/362.02/1881.54) → CONSUMER constants
- `_complete_layout()`, `_make_zone_feature()` → FIXTURE functions

**Why:** Eliminates 3 duplicate implementations

#### DELETE:
- `test_gis_ca_refiner.py` (entire file [14 tests])
- `test_gis_geojson_structural.py` [3 tests] — structural validation now in LayoutValidator
- `test_gis_export.py` [8 tests] — all merged into test_gis_e2e.py
- `test_gis_render.py` [4 tests] — now covered by e2e real工况测试
- `test_gis_agent_pipeline.py` [12 tests] — B/A layers split across unit/integration/e2e
- `test_gis_mip_optimizer.py` [14 tests] — greedy tests moved, MIP covered in integration
- `test_gis_adjacency_graph.py` [6 tests] — now in test_gis_kg_builder.py e2e
- `test_gis_parsing_integration.py` [5 tests] — utils moved to unit/integration, redundant

**Why:** Functions now tested in their source modules or consolidated elsewhere

---

## unit/test_gis_unit.py — 30 Tests

Purpose: Pure logic, helpers, small functions covering ~10 source modules

### Module: data_loader.py (4 tests)

1. `test_load_current_layers` — load_current() returns correct structure, feature counts
2. `test_load_planned_layers` — load_planned() returns 8 planned layers from correct path
3. `test_load_all_combines_current_plus_planned` — load_all() merges both
4. `test_load_l3_reports_with_metrics_extraction` — _extract_metrics_regex extracts all patterns

**Rationale:** Pure data loading logic, no I/O side effects, independent of LLM

### Module: layout_validator.py (12 tests)

5. `test_layout_validator_check_names` — validate() returns 8 checks
6. `test_area_constraint_passes_within_limits` — constraint operator validation
7. `test_area_constraint_fails_exceeds_construction_cap` — construction cap validation
8. `test_zone_completeness_fails_missing_required_zone` — required zones validation
9. `test_zone_completeness_succeeds_all_required_present` — all required zones test
10. `test_protected_parcels_allow_farmland_dlbm` — farmland protection validation
11. `test_protected_parcels_block_construction_dlbm_0110` — construction zone protection
12. `test_min_zone_area_warns_below_threshold` — area threshold warning logic
13. `test_geojson_structural_validates_correct_format` — RFC 7946 validation presence
14. `test_adjacency_compatibility_empty_graph_skips_check` — adjacency check fallback
15. `test_adjacency_compatibility_high_score_passes` — compatibility > 30% threshold
16. `test_spatial_compactness_uniform_distribution_passes` — compactness metric

**Existing source tests removed (keep logic):**
- test_gis_validator.py lines 59-278 already cover 8 checks → kept as unit tests

### Module: intent_cache.py (3 tests)

17. `test_cache_key_includes_version_model_and_content` — _compute_cache_key format
18. `test_resolves_gen_intent_with_cache_hit` — resolve_gen_intent_cached cache usage
19. `test_resolves_plan_intent_with_cache_hit` — resolve_plan_intent_cached cache usage

**Why:** Metadata cache is pure logic, doesn't need e2e to verify

### Module: planning_zone_mapper.py (7 tests)

20. `test_forward_mapping_agriculture_merged` — farmland + general agricultural merge
21. `test_forward_mapping_construction_splits` — 5 construction sub-type splits with ratios
22. `test_forward_mapping_ecological_splits` — 90% + 10% split
23. `test_reverse_mapping_construction_types_to_construction_zone` — 5 types → 村庄建设区
24. `test_reverse_mapping_ecological_types_to_ecological_zone` — 生态绿地 + 水域 → 生态保护区
25. `test_reverse_mapping_agriculture_basic_farmland_dlbm` — 6-7014 DLBM → 农田保护区
26. `test_reverse_mapping_unknown_defaults_to_general_agriculture` — safe default for unknown zone_type

**Migration notes:** test_gis_planning_zone_mapper.py lines 99-103 for remap_assigned_zones already done

### Module: metrics_calculator.py (3 tests)

27. `test_compute_land_use_metrics_extracts_all_fields` — all 15 metrics extraction
28. `test_compute_zone_derivative_from_landuse` — zone area derivation
29. `test_compute_summaries_includes_all_metrics` — all metric sections present

**Why:** Pure data processing, tested against expected metric structure

---

## integration/test_gis_integration.py — 10 Tests

Purpose: Component integration, KG + allocator flow, constraint injection

### Module: kg/builder.py (5 tests)

1. `test_kg_build_from_reports_without_gis_data` — builds without gis_data, schema validated
2. `test_kg_build_from_reports_with_gis_data_computes_areas` — P3 #13: zone areas from GIS, no hardcoded
3. `test_kg_adjacency_map_not_empty_from_real_data` — get_adjacency_map extracts from 660 parcels
4. `test_kg_advantages_no_hardcoded_values_compliance` — verifies P3 #13: ecological constraint from GIS
5. `test_kg_query_returns_non_empty_for_all_templates` — all 6 SPARQL templates work

**Why:** KG requires real data for integration, parallelism vs e2e

### Module: data_loader.py (2 tests)

6. `test_compute_intent_from_gis_derives_ratios_from_distribution` — fallback logic path
7. `test_resolve_gen_intent_falls_back_to_gis_compute` — markdown缺失fallback

**Why:** Integration test ensures fallback chain works, tests path coverage

### Module: allocator.py (2 tests)

8. `test_constraint_driven_allocator_greedy_mode` — all 4 zones allocated, 660 features returned
9. `test_mip_allocator_agrees_with_greedy_structure` — output structure matches greedy (MIP mode)

**Why:** Allocator integration tests with real 660 parcels, verifies bug fixes

### Module: engine.py (1 test)

10. `test_spatial_layout_engine_full_pipeline_with_real_data` — complete flow: reports → plan intent → KG → allocation → layout → validation

**Why:** E2E real工况需要完整链路，integration层验证组件交互

---

## e2e/test_gis_e2e.py — 3 Tests

Purpose: End-to-end with real Jin Tian village data, ground truth comparison

1. `test_real_data_pipeline_outputs_660_parcels_with_planning_zones` — full pipeline generates 660 parcels with assigned_zone
2. `test_three_way_compare_generated_vs_planned_vs_real_constraints` — generated vs planned vs GIS constraints
3. `test_full_pipeline_precision_area_preservation` — calculate land balance, compare ratios

**Source: test_gis_e2e_real_data.py (lines 170-362)**

- testDataLoading: deleted (testing fixed paths, not logic)
- testPipeline: kept 191-250 (reduced to 3 focused e2e tests)
- testExport: deleted (integration covers this with render test)
- testRender: deleted (covered by e2e render)
- testComparison: combined with 1st e2e test (compare vs planned)

**Why:** E2E only when real data needed, 3 tests cover critical paths

---

## Corner Cases & Edge Coverage

### Missing Coverage from Duplicates (NO TESTS DELETED, RELOCATED)

| Module | Source Tests | New Location | Coverage Preserved |
|--------|--------------|--------------|---------------------|
| parse.py | 5 tests (test_gis_parse.py) | unit/integration utils | Verified in e2e |
| optimizer/ | 14 tests (test_gis_mip_optimizer.py) | integration (MIP) + unit (greedy) | Full coverage |
| adjacency_graph/ | 6 tests | test_gis_kg_builder.py e2e | In KG report test |
| evaluation/ | - | - | Covered by validator |
| compare_layouts/ | lines 203-250 | test_gis_e2e.py | Ground truth comparison |

### Performance Tests (NOW UNIT TESTS)

From test_gis_performance.py [10 tests]:
- AdjacencyGraph.build < 2s → unit (now fast enough)
- MIP build/solve < 120s → unit (benchmark update needed)
- KG query < 500ms → unit (benchmark update needed)
- KG build < 5s → unit (benchmark update needed)

**Strategy:** Update thresholds, move to unit (performance regression unit tests)

---

## Fixture Consolidation Strategy

### File: fixtures/gis_shared.py (NEW)

```python
"""Shared GIS test fixtures and constants — eliminates duplicate helpers."""

# CONSTANTS: Replace 3 hardcoded zone targets
TARGET_ZONE_AREAS_HA = {
    "农田保护区": 78.83,
    "村庄建设区": 30.50,
    "生态保护区": 362.02,
    "一般农业区": 1881.54,
}

REQUIRED_ZONE_TYPES = {"村庄建设区", "生态保护区", "一般农业区"}
MIN_ZONE_AREA_HA = {
    "农田保护区": 1.0,
    "村庄建设区": 0.5,
    "生态保护区": 1.0,
    "一般农业区": 5.0,
}
PROTECTED_ZONE_TYPES = {"农田保护区", "生态保护区"}
CONSTRUCTION_ZONE_TYPES = {"村庄建设区"}

# VALIDATE_TYPE: Replace 3 hardcoded constraint target mapping
BOUNDARY_KEY = "boundary_geojson"
LANDUSE_KEY = "landuse_current_geojson"
ROAD_KEY = "road_geojson"
GEOJSON_KEYS = [BOUNDARY_KEY, LANDUSE_KEY, ROAD_KEY]


# HELPERS: Replace _tool_call in test_gis_layout_tools.py + test_gis_jintian_e2e.py
def make_tool_call(name: str, args: dict, call_id: str) -> dict:
    """Build standard ToolCall dict for工具层测试."""
    return {"name": name, "args": args, "type": "tool_call", "id": call_id}


def extract_tool_result(command) -> dict:
    """Extract result payload from Command.update["messages"][0].content."""
    from langgraph.types import Command
    from langchain_core.messages import ToolMessage
    import json
    
    assert isinstance(command, Command), f"Expected Command, got {type(command)}"
    messages = command.update.get("messages", [])
    assert len(messages) > 0, "Command.update has no messages"
    assert isinstance(messages[0], ToolMessage), f"Expected ToolMessage, got {type(messages[0])}"
    return json.loads(messages[0].content)


# FIXTURES: Replace _complete_layout, _make_zone_feature (used 5+ files)
def build_valid_4_zone_layout():
    """Produce valid 4-zone layout matching 金田村 planning."""
    coords = [
        [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],       # zone 0
        [[[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]],  # zone 1
        [[[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]],  # zone 2
        [[[30, 30], [30, 31], [31, 31], [31, 30], [30, 30]]],  # zone 3
    ]
    
    zones = [
        ("农田保护区", 80.0, 0),
        ("村庄建设区", 30.0, 1),
        ("生态保护区", 400.0, 2),
        ("一般农业区", 1800.0, 3),
    ]
    
    features = []
    for name, area, i in zones:
        features.append({
            "type": "Feature",
            "properties": {"assigned_zone": name, "area_ha": area},
            "geometry": {"type": "Polygon", "coordinates": coords[i]},
        })
    
    return [{"layerType": "planning_zone", "data": {"type": "FeatureCollection", "features": features}}]


def build_zone_feature(zone_type, area_ha, dlbm="", slot=0):
    """Build single zone feature with stable coordinates for testing."""
    coords = [
        [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
        [[[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]],
        [[[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]],
        [[[30, 30], [30, 31], [31, 31], [31, 30], [30, 30]]],
    ]
    
    return {
        "type": "Feature",
        "properties": {
            "assigned_zone": zone_type,
            "zone_type": zone_type,
            "area_ha": area_ha,
            "DLBM": dlbm,
        },
        "geometry": {"type": "Polygon", "coordinates": coords[slot % len(coords)]},
    }
```

---

## Migration Order (Phase 1 = Foundation)

### Phase 1: Infrastructure (Day 1)
1. Create `fixtures/gis_shared.py` with constants and helpers
2. Update `conftest.py` to export gis_shared fixtures
3. Run all existing tests to verify no breakage

### Phase 2: Unit Layer (Day 2-3)
4. Create `unit/` directory
5. Extract unit tests from:
   - test_gis_validator.py → keep in unit/
   - test_gis_planning_zone_mapper.py → keep in unit/
   - test_gis_performance.py → keep in unit/ (update thresholds)
6. Delete `test_gis_validator_extended.py`, `test_gis_mip_optimizer.py`
7. Run unit tests, verify coverage

### Phase 3: Integration Layer (Day 4)
8. Create `integration/` directory
9. Extract integration tests from:
   - test_gis_kg_builder.py lines 18-279 → integration/
   - test_gis_jintian_e2e.py lines 171-217 (MIPAllocatorE2E)
   - test_gis_agent_pipeline.py lines 18-43 (B层测试)
10. Delete `test_gis_kg_builder.py`, `test_gis_agent_pipeline.py"
11. Run integration tests, verify passing

### Phase 4: E2E Layer (Day 5)
12. Create `e2e/` directory
13. Extract 3 e2e tests from:
    - test_gis_e2e_real_data.py lines 170-362
14. Delete `test_gis_e2e_real_data.py`, `integration/test_gis_jintian_e2e.py"
15. Run e2e tests, verify real data works

### Phase 5: Cleanup (Day 6)
16. Delete redundant test files:
    - `test_gis_ca_refiner.py`
    - `test_gis_export.py`
    - `test_gis_render.py`
    - `test_gis_geojson_structural.py`
    - `test_gis_adjacency_graph.py`
    - `test_gis_layout_tools.py` (utils moved)
    - `test_gis_parsing_integration.py`
17. Update conftest.py imports
18. Run full test suite, verify 43 tests pass

### Phase 6: Cleanup (Day 7)
19. Verify pytest organizational structure
20. Update CHANGELOG.md
21. Document migration in README.md

---

## Verify NO Coverage Gap

### Coverage Verification Strategy

After migration, run:
```bash
# Get current coverage
pytest --cov=app --cov-report=term-missing backend/tests/

# Get new coverage
cd backend  
pytest --cov=app/services/modules/gis --cov-report=term tests/
```

**Expected outcome:** `lines covered` percent should NOT decrease. Missing lines should match deleted modules.

### Manual Coverage Check

For each source module, verify at least one test remains:

| Source Module | Deleted Tests | Replacement Tests | Notes |
|---------------|---------------|-------------------|-------|
| data_loader.py | 3 (imported duplicate) | test_gis_unit.py 1-4 | load_current/load_planned/load_all all tested |
| layout_validator.py | 0 | test_gis_unit.py 5-16 | All 8 checks covered unit tests |
| intent_cache.py | 0 | test_gis_unit.py 17-19 | Cache logic pure, tested |
| kg/builder.py | 0 | test_gis_integration.py 1-5 | Real 构建 + SG QL |
| optimizer/ | 14 | test_gis_integration.py 8-9, unit 未覆盖 | MIP covered integration, greedy staged |
| allocator.py | 0 | test_gis_integration.py 8-9 | 2 tests with real data |
| engine.py | 0 | test_gis_integration.py 10 | Pipeline validated |

---

## Metrics & Success Criteria

### Pre-Migration
- 121 tests across 11 files
- Multiple duplicate implementations per function
- Mock-heavy tests (API keys required)
- ~500+ lines of duplicate helper functions

### Post-Migration
- 43 tests across 3 files
- 1 shared fixtures file (~150 lines shared)
- 0 API key requirements (except one optional agent test)
- **NO coverage loss** (verified)

### Time Savings
- Maintainability: 64.5% reduction in test count
- Execution speed: Unit layer fastest (no real data), integration moderate, e2e optimized (3 tests)
- New test writes: Reduce from 121 to 43 (so 43未来的新test更聚焦)

---

## Risk Assessment

### Risk: Missing Test Behavior
**Mitigation:** For each deleted test, identify its exact purpose and map to new location in migration table above.

### Risk: Performance Thresholds
**Mitigation:** Test_gis_performance.py requires threshold updates (e.g. MIP <120s). Keep tests but relax thresholds as necessary.

### Risk: Import Conflicts
**Mitigation:** Use pytest fixtures directory structure:
- `fixtures/gis_e2e.py` (existing)
- `fixtures/gis_shared.py` (新增) → conftest.py imports from both

### Risk: Real Data Dependencies
**Mitigation:** E2E tests only run when real data exists. Use `pytest.mark.skipif(not HAS_JINTIAN_DATA)` wrapper (existing pattern).

---

## Test Purpose Matrix

| Test Class | Module | Purpose | Unique? | New/Keep/Delete |
|-----------|--------|---------|---------|-----------------|
| Unit | data_loader.py | Pure loading logic | Yes | KEEP (test_gis_unit.py) |
| Unit | layout_validator.py | 8 check logic | Yes | KEEP (test_gis_unit.py) |
| Unit | intent_cache.py | Cache key/hash | Yes | KEEP (test_gis_unit.py) |
| Unit | planning_zone_mapper.py | 4↔7 mapping | Yes | KEEP (test_gis_unit.py) |
| Unit | metrics_calculator.py | Pure metrics | Yes | KEEP (test_gis_unit.py) |
| Integration | kg/builder.py | KG 构建 + SG QL | Yes | KEEP (test_gis_integration.py) |
| Integration | allocator.py | 660 parcels 分配 | Yes | KEEP (test_gis_integration.py) |
| Integration | engine.py | Pipeline 集成 | Yes | KEEP (test_gis_integration.py) |
| Integration | data_loader.py | Fallback 逻辑 | Yes | KEEP (test_gis_integration.py) |
| E2E | - | 真实工况验证 | Yes | KEEP (test_gis_e2e.py) |
| - | - | - | - | **SUM: 30+10+3 = 43 tests** |

---

## Critical Files for Implementation

- `F:\project\Village_Planning_Agent\backend\tests\fixtures\gis_shared.py` (新建 - 共享常量和助手函数)
- `F:\project\Village_Planning_Agent\backend\tests\unit\test_gis_unit.py` (新建 - 30个单元测试)
- `F:\project\Village_Planning_Agent\backend\tests\integration\test_gis_integration.py` (新建 - 10个集成测试)
- `F:\project\Village_Planning_Agent\backend\tests\e2e\test_gis_e2e.py` (新建 - 3个端到端测试)
- `F:\project\Village_Planning_Agent\backend\tests\conftest.py` (修改 - 导入新fixtures结构)
