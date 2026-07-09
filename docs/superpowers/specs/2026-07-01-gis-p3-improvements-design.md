# GIS P3 Improvements Design Spec

## Context

P0-P2 GIS compliance issues have been fixed (OSM BBOX bug, Direction enum, DLBM prompt, hazard buffer, GCJ-02 iterative, metadata cleanup, properties whitelist, sync/async dedup). This spec addresses the remaining 5 P3 issues: GeoJSON validation, coordinate system documentation, adjacency graph utilization, and hardcoded KG values elimination.

## 1. KG Builder Hardcoded Area Values (#13)

### Problem
`_add_constraints()` and `_add_zones()` in `kg/builder.py` hardcode Jintian-specific values (362.02, 30.50, 1960.70 ha) via string matching in report content. Other villages get incorrect KG zone data.

### Solution
Compute area values from `gis_data["landuse_current"]` GeoJSON using GeoPandas:

1. `PlanningKG.build_from_reports()` gains optional `gis_data: Dict` parameter
2. New method `_compute_zone_areas_from_gis(gis_data) -> Dict[str, float]`:
   - Load `landuse_current` as GeoDataFrame
   - Project to metric CRS via `crs_engine.project_to_metric()`
   - Group by `zone_type`, dissolve, compute area in hectares
   - Map zone_type names to planning zone names via `PlanningZoneMapper`
3. `_add_zones()` uses computed areas when available, falls back to regex extraction from report metrics, final fallback: omit `area_target_ha` triple
4. `_add_constraints()` extracts constraint bounds from report metrics dict (e.g., `metrics["max_construction_ha"]`) instead of string-matching `"362.02"` in content

### Files
- `backend/app/services/modules/gis/layout/kg/builder.py`
- `backend/app/tools/gis/layout_tools.py` (pass gis_data to KG build)

## 2. Adjacency Graph Integration into Allocator (#12)

### Problem
`_add_spatial_relations()` computes up to 5000 adjacency edges but `ConstraintDrivenAllocator` never queries them. Zones may be spatially fragmented.

### Solution
Add adjacency-aware parcel preference in the greedy allocator:

1. `PlanningKG` adds `get_adjacency_map() -> Dict[str, Set[str]]` method that SPARQL-queries `pln:adjacent_to` triples and returns `{bsm: {adjacent_bsm, ...}}`
2. `ConstraintDrivenAllocator.__init__()` gains optional `adjacency_map: Dict[str, Set[str]]` parameter
3. In greedy assign stage, when multiple parcels have equal DLBM preference cost, sort by adjacency score: count of adjacent parcels already assigned to the target zone. Higher score = higher priority.
4. `layout_tools.py` `allocate_zones` tool queries adjacency from KG and passes to allocator

### Files
- `backend/app/services/modules/gis/layout/kg/builder.py`
- `backend/app/services/modules/gis/layout/optimizer/mip_solver.py`
- `backend/app/tools/gis/layout_tools.py`

## 3. GeoJSON RFC 7946 Structural Validation (#9)

### Problem
`LayoutValidator` checks planning constraints but not GeoJSON structural correctness.

### Solution
Add `_check_geojson_structural` as the 6th validation check in `LayoutValidator.validate()`:

1. For each layer config, validate the `geojson` field:
   - Top-level has `type: "FeatureCollection"` and `features` array
   - Each feature has `type: "Feature"`, `properties` (dict or None), `geometry` (dict or None)
   - Geometry type is one of: Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon
   - Coordinates: longitude in [-180, 180], latitude in [-90, 90]
   - Polygon rings are closed (first coord == last coord, tolerance 1e-10)
   - No `crs` member at top level
2. Report violations as warnings (not errors) to avoid blocking layout generation
3. Return `ValidationCheck` with `passed=True/False` and list of specific violations

### Files
- `backend/app/services/modules/gis/layout/validator.py`

## 4. CGCS2000/WGS-84 Documentation (#10)

### Problem
`gd_service.py` treats EPSG:4490 as EPSG:4326 without explaining why.

### Solution
Add detailed docstring/comments to `_transform_crs()` and `_transform_bbox_for_request()`:
- CGCS2000 (EPSG:4490) and WGS-84 (EPSG:4326) share the GRS80 ellipsoid parameters (semi-major axis 6378137.0m, inverse flattening 298.257222101)
- pyproj Transformer returns identity because the Helmert transformation between them is sub-meter (<1m) across China
- For village planning at hectare scale, this difference is negligible (<0.01% of typical zone area)
- Reference: GB/T 21010-2017 uses CGCS2000; GeoJSON RFC 7946 requires WGS-84

### Files
- `backend/app/services/modules/gis/providers/tianditu/gd_service.py`

## 5. Tianditu Coordinate System Documentation (#11)

### Problem
`TiandituProvider` uses CGCS2000 coordinates as WGS-84 without documentation.

### Solution
Add class-level docstring section explaining:
- Tianditu WFS/API returns coordinates in CGCS2000 (EPSG:4490)
- Code stores these as WGS-84 (EPSG:4326) for GeoJSON compliance
- The sub-meter difference is acceptable for village planning
- No conversion is applied (unlike Amap which requires GCJ-02 ↔ WGS-84)

### Files
- `backend/app/services/modules/gis/providers/tianditu/provider.py`

## Implementation Order

| Step | Item | Depends On | Est. |
|------|------|-----------|------|
| 1 | #13 KG hardcoded elimination | None | 2h |
| 2 | #12 Adjacency graph integration | #13 | 2h |
| 3 | #9 GeoJSON structural validation | None | 1.5h |
| 4 | #10+#11 Coordinate system docs | None | 30min |

Steps 1, 3, 4 are independent and can run in parallel. Step 2 depends on step 1.

## Verification

- #13: Build KG for a non-Jintian village, verify zone areas come from GIS data not hardcoded strings
- #12: Run allocator with adjacency map, verify planning zones are more spatially compact (measure average nearest-neighbor distance between same-zone parcels)
- #9: Feed invalid GeoJSON (unclosed ring, swapped coords) to validator, verify violations reported
- #10/#11: Code review confirms documentation present and accurate
- E2E: Run `test_gis_e2e_real_data.py` to confirm no regression
