# Village Boundary Proxy Verification Report v3

**Verification Time**: 2026-04-26 00:54:32
**Test Location**: Jintian Village (115.891, 24.567)

## Dependency Check

- geopandas: OK
- shapely: OK
- alphashape: OK
- matplotlib: OK
- contextily: OK

## Actual Boundary (Baseline)

**Source**: `docs/gis/jintian_boundary/admin_boundary_line.geojson`
**Area**: 4.6442 km2
**Perimeter**: 15.1404 km
**Contains Center**: True
**Line Count**: 538

## Proxy Methods Comparison

| Method | Status | Area (km2) | IoU | Coverage | Actual Cov |
|--------|--------|------------|-----|----------|------------|
| Isochrone | OK | 5.4005 | 0.5972 | 0.8087 | 0.6955 |
| Morphological (Convex) | OK | 9.0072 | 0.3769 | 0.8046 | 0.4149 |
| Natural Boundary | OK | 42.5421 | 0.0415 | 0.6721 | 0.0423 |
| Integrated Fusion | OK | 9.3366 | 0.4 | 0.8601 | 0.4278 |
| Polygonize Fusion | OK | 5.4005 | 0.5972 | 0.8087 | 0.6955 |

## Detailed Results

### 等时圈边界

**Method**: 15分钟步行可达性分析
**Status**: Success

**Statistics**:
- time_minutes: 15
- travel_mode: walk
- radius_km: 1.25
- area_km2: 5.4005
- perimeter_km: 8.2674

### 形态学包络线

**Method**: 居民地(RESA)分布包络
**Status**: Success

**Statistics**:
- feature_count: 3

### 自然闭合边界

**Method**: 水系(HYDL)+公路(LRDL)闭合切割
**Status**: Success

**Statistics**:
- line_count: 14
- water_count: 7
- road_count: 7
- area_km2: 42.5421
- perimeter_km: 347.3098
- polygon_count: 1
- contains_center: True

### Integrated Fusion Boundary

**Method**: Weighted hierarchy: isochrone ceiling + morphological core + natural clipping
**Status**: Success

**Statistics**:
- area_km2: 9.3366
- perimeter_km: 11.9572
- fusion_method: isochrone_base
- components: {'has_ceiling': True, 'has_core': True, 'has_constraints': False, 'constraint_count': 0}

### Polygonize Fusion Boundary

**Method**: Geometric stitching: isochrone segments + road/water lines -> polygonize
**Status**: Success

**Statistics**:
- area_km2: 5.4005
- perimeter_km: 8.2674
- trimmed: True
- polygon_count: 1
- boundary_segments: 32
- natural_segments: 15

## Method Evaluation

### Approach 1: Isochrone Boundary
- **Pros**: Reflects real accessibility based on road network
- **Cons**: Requires API support, circular approximation has limits
- **Best for**: Transportation accessibility analysis, service range delineation

### Approach 2: Morphological Envelope
- **Pros**: Tightly fits built-up area distribution, no API needed
- **Cons**: Needs dense RESA data points
- **Best for**: Settlement cluster boundary delineation

### Approach 3: Natural Boundary
- **Pros**: Uses geographic barriers, natural boundary logic
- **Cons**: Needs closed line network, unstable success rate
- **Best for**: Areas with clear geographic divisions

## Recommendation (IoU Ranking)

**Ranked by IoU (Intersection over Union)**:

1. **Isochrone**: IoU=0.5972, Coverage=0.8087
2. **Polygonize Fusion**: IoU=0.5972, Coverage=0.8087
3. **Integrated Fusion**: IoU=0.4, Coverage=0.8601
4. **Morphological (Convex)**: IoU=0.3769, Coverage=0.8046
5. **Natural Boundary**: IoU=0.0415, Coverage=0.6721

**Primary Recommendation**: Isochrone (IoU >= 0.3)

## Output Files

- `output/boundary_proxy/actual_boundary.geojson`
- `output/boundary_proxy/isochrone_boundary.geojson`
- `output/boundary_proxy/morphological_hull.geojson`
- `output/boundary_proxy/morphological_concave.geojson`
- `output/boundary_proxy/natural_boundary.geojson`
- `output/boundary_proxy/integrated_fusion_boundary.geojson`
- `output/boundary_proxy/integrated_fusion_boundary_v2.geojson`
- `output/boundary_proxy/comparison_chart_v3.png`
- `output/boundary_proxy/boundary_proxy_report_v3.md`