# LLM-to-GIS Layer Generation Pipeline - Implementation Plan

## Problem Statement

LLMs cannot reliably generate spatial data (coordinates, polygons) from vague planning text like "eastern area for industrial use" (东部布局产业用地). The current system has STUB tool definitions for `spatial_layout_generator`, `planning_vectorizer`, and `map_renderer` with no actual implementations. The frontend MapView component can already render GeoJSON with data-driven styling, and the `SPATIAL_LAYOUT_PARSE_PROMPT` already defines the structured planning intent JSON schema (zones/facilities/axis), but no code bridges the gap between parsed intent and actual GeoJSON geometry.

## Core Design Principle

**LLM reasons about WHAT to place; algorithms determine WHERE to place it; humans adjust the result.**

This is a three-phase pipeline:
1. LLM Parse Phase: Planning text -> structured JSON (planning intent)
2. Algorithm Phase: Structured JSON + reference GIS data -> GeoJSON (deterministic geometry generation)
3. Human Feedback Phase: GeoJSON -> human review -> adjustment -> final GeoJSON

---

## 1. Architecture: Text-to-Layer Conversion Pipeline

### 1.1 Pipeline Overview

```
Planning Text (L3 report)
    |
    v
[Flash LLM] -- SPATIAL_LAYOUT_PARSE_PROMPT --> PlanningIntent (JSON)
    |
    v
[LayoutEngine] -- algorithmic geometry generation --> GeoJSON layers
    |               uses: boundary, landuse_current, constraints
    v
[MapRenderer] -- style assignment + color mapping --> GISLayerConfig[]
    |
    v
[SSE Event] --> Frontend MapView renders layers
    |
    v
[Human Review] --> approve / spatial_feedback / reject
    |
    v (if feedback)
[LayoutEngine.adjust()] -- incremental geometry update --> updated GeoJSON
```

### 1.2 New Module Structure

```
backend/app/tools/core/
    __init__.py                    # (existing, add exports)
    gis_tool_wrappers.py           # (existing, add 3 new wrappers)
    spatial_layout_engine.py       # NEW: core geometry generation algorithms
    planning_vectorizer.py         # NEW: intent-to-GeoJSON conversion
    map_renderer.py                # NEW: style assignment + GISLayerConfig assembly

backend/app/services/modules/gis/
    ... (existing)
    layout_algorithms/             # NEW: geometry algorithms package
        __init__.py
        zone_generator.py          # Polygon generation from planning intent
        facility_placer.py         # Point placement from location hints
        axis_builder.py            # LineString generation from axis specs
        constraint_solver.py       # Constraint validation + adjustment
```

### 1.3 Data Flow Through Agent Graph

The spatial layout generation is triggered when the `spatial_layout_generator` tool is called during L3 `spatial_structure` dimension analysis (as configured in `phases.yaml`). The flow:

1. Agent calls `spatial_layout_generator` tool with `planning_scheme` parameter
2. Tool wrapper extracts context: planning text, GIS data from SharedGISContext
3. Flash LLM parses planning text into PlanningIntent JSON
4. LayoutEngine generates GeoJSON using boundary + landuse_current as base
5. MapRenderer wraps GeoJSON into GISLayerConfig with proper colors
6. Result flows back through agent as GisResultMessage via SSE
7. Frontend renders layers; human can approve or provide spatial feedback

---

## 2. Algorithms: Geometry Generation from Planning Intent

### 2.1 Zone Generator (zone_generator.py)

**Input**: PlanningIntent.zones[] + boundary GeoJSON + landuse_current GeoJSON + constraint_zones
**Output**: FeatureCollection of Polygon features (one per zone)

**Algorithm - Constrained Area Subdivision**:

```
Step 1: Load boundary polygon from SharedGISContext (boundary_current.geojson)
Step 2: For each zone, compute target area = total_area * zone.area_ratio
Step 3: Determine zone placement quadrant based on zone.location_bias.direction:
    - "center" -> center 60% of boundary
    - "north" -> top half
    - "east" -> right half
    - etc.
    Use boundary centroid + bbox to compute quadrant polygon
Step 4: Clip quadrant with boundary -> candidate placement area
Step 5: Subtract constraint zones (farmland_protection, ecological_protection, etc.)
        from candidate area using shapely.difference()
Step 6: If landuse_current exists, prioritize placing zone where current use
        matches planned use (e.g., "居住用地" -> existing DLBM 2121宅基地)
Step 7: Generate zone polygon with target area using iterative subdivision:
    a. Start with the candidate polygon
    b. If area > target_area * 1.1, shrink from edges using buffer(-delta)
    c. If area < target_area * 0.9, expand toward unconstrained areas
    d. Converge within 5% tolerance
Step 8: Assign properties: zone_id, land_use, area_ratio, color (from ZONE_TYPE_COLORS)
```

**Key insight**: Use existing `landuse_current` as the primary placement guide. When the planning intent says "居住用地", find existing 宅基地(DLBM 2121) polygons and extend/adjust them rather than creating polygons from scratch. This produces more realistic and defensible geometries.

### 2.2 Facility Placer (facility_placer.py)

**Input**: PlanningIntent.facilities[] + boundary GeoJSON + existing POI data + placed zones
**Output**: FeatureCollection of Point features (one per facility)

**Algorithm - Weighted Centroid Placement**:

```
Step 1: For "现状保留" facilities, search existing POI/residential data for matches
    - If found, use existing coordinates directly
    - If not found, use village center as fallback
Step 2: For "规划新建" facilities, compute placement:
    a. Parse location_hint for direction keywords
    b. Find the zone whose land_use best matches the facility type:
       - "村委会" -> "公共服务用地" zone centroid
       - "学校" -> "公共服务用地" zone centroid
       - "医疗站" -> "公共服务用地" zone centroid
       - "产业设施" -> "产业用地" zone centroid
    c. Offset from zone centroid toward direction by service_radius * 0.1
    d. Snap to nearest road point if road data available (within 200m)
Step 3: For "规划改扩建", find existing facility location and offset slightly
Step 4: For "规划迁建", compute new location same as "规划新建"
Step 5: Assign properties: facility_id, facility_type, status, color (from FACILITY_STATUS_COLORS)
```

### 2.3 Axis Builder (axis_builder.py)

**Input**: PlanningIntent.axes[] + boundary GeoJSON + road data
**Output**: FeatureCollection of LineString features (one per axis)

**Algorithm - Directional Line Generation**:

```
Step 1: Compute boundary centroid and bbox
Step 2: For each axis, determine start/end points based on direction:
    - "east-west": left edge mid -> right edge mid of bbox
    - "north-south": top edge mid -> bottom edge mid of bbox
    - etc.
Step 3: If reference_feature mentions a road, snap axis to that road geometry:
    a. Find road feature whose name/properties match reference_feature
    b. If found, use road centerline as axis geometry (clipped to boundary)
    c. If not found, fall back to directional line
Step 4: Clip axis LineString to boundary polygon
Step 5: Assign properties: axis_id, axis_type, direction, color (from AXIS_TYPE_COLORS)
```

### 2.4 Constraint Solver (constraint_solver.py)

**Input**: Generated zones GeoJSON + constraint zones from SharedGISContext
**Output**: Validated/adjusted zones GeoJSON

**Algorithm**:

```
Step 1: For each zone polygon, check intersection with constraint zones:
    - farmland_protection: reduce zone area by the overlap
    - ecological_protection: remove zone overlap entirely
    - historical_protection: remove zone overlap entirely
    - hazard_buffer: reduce zone area by the overlap, flag as "需要专项评估"
Step 2: After constraint removal, check if remaining area still meets area_ratio
    within tolerance. If not, expand zone toward unconstrained areas.
Step 3: Compute constraint violation report for each zone
Step 4: Return adjusted zones + violation report
```

### 2.5 GeoPandas Integration

All geometry operations should use the existing `geojson_to_geodataframe()` and `geodataframe_to_geojson()` utilities in `backend/app/services/modules/gis/utils/geojson_utils.py`. The algorithms should be written to accept GeoDataFrame objects internally, converting from/to GeoJSON at the boundaries.

---

## 3. Human Feedback Loop Mechanism

### 3.1 Feedback Types

1. **Spatial Adjustment**: User drags/moves a zone polygon, facility point, or axis line
2. **Area Change**: User resizes a zone (e.g., "make the industrial zone smaller")
3. **Text Feedback**: User describes changes in natural language (e.g., "move the school closer to the main road")
4. **Approve**: User accepts the layout as-is
5. **Reject**: User requests regeneration with specific guidance

### 3.2 Backend: New API Endpoints

```
POST /api/session/{session_id}/spatial-feedback
    Body: {
        feedback_type: "spatial_adjustment" | "area_change" | "text_feedback" | "approve" | "reject"
        target_type: "zone" | "facility" | "axis"
        target_id: "Z01" | "F01" | "A01"
        action: "move" | "resize" | "relocate" | "remove" | "add"
        payload: {
            # For spatial_adjustment:
            new_geometry: GeoJSON Geometry,  # New polygon/point/line
            # For area_change:
            new_area_ratio: float,
            # For text_feedback:
            description: str,
            # For reject:
            regeneration_guidance: str,
        }
    }
    Response: { success: bool, updated_layers: GISLayerConfig[], message: str }
```

### 3.3 Backend: Feedback Processing Flow

```
1. Receive spatial feedback via API
2. Load current layout state from SharedGISContext (or database)
3. Apply the adjustment:
    a. "move" zone: translate polygon centroid to new position, clip to boundary
    b. "resize" zone: scale polygon, redistribute area to adjacent zones
    c. "relocate" facility: update point coordinates, validate constraints
    d. "text_feedback": parse with LLM, apply as structured adjustment
4. Run constraint validation on modified layout
5. Update layout state
6. Push updated GISLayerConfig via SSE
7. Frontend re-renders without full page reload
```

### 3.4 State Management for Layout Iteration

Add new fields to a `SpatialLayoutState` stored in database (not in AgentState to avoid bloating the graph state):

```python
# New table: spatial_layout_state
class SpatialLayoutState:
    session_id: str
    version: int
    planning_intent: Dict  # The parsed JSON from LLM
    layout_geojson: Dict   # Current generated GeoJSON
    feedback_history: List[Dict]  # Accumulated feedback
    constraint_violations: List[Dict]  # Current constraint issues
    created_at: datetime
    updated_at: datetime
```

This keeps the agent state clean while providing persistence for the spatial editing workflow.

---

## 4. Stub Tool Implementation Plan

### 4.1 spatial_layout_generator (Backend Tool)

**File**: `backend/app/tools/core/spatial_layout_engine.py`

```python
class SpatialLayoutEngine:
    """Core engine: planning text -> structured intent -> GeoJSON layers"""
    
    def __init__(self, gis_context: SharedGISContext, llm=None):
        self.gis_context = gis_context
        self.llm = llm  # Flash model for parsing
    
    async def generate(self, planning_text: str, dimension_key: str = "spatial_structure") -> ToolResult:
        """
        Full pipeline: text -> intent -> GeoJSON
        
        Steps:
        1. Format SPATIAL_LAYOUT_PARSE_PROMPT with planning_text + context
        2. Call Flash LLM to get PlanningIntent JSON
        3. Validate and normalize intent (area_ratio sum = 1.0)
        4. Generate zone polygons via ZoneGenerator
        5. Generate facility points via FacilityPlacer
        6. Generate axis lines via AxisBuilder
        7. Run ConstraintSolver validation
        8. Return ToolResult with GeoJSON layers
        """
        pass
    
    async def adjust(self, feedback: SpatialFeedback) -> ToolResult:
        """Apply human feedback and regenerate affected layers"""
        pass
    
    def _get_reference_data(self) -> Dict:
        """Extract boundary, landuse, constraints from SharedGISContext"""
        pass
```

**Wrapper** in `gis_tool_wrappers.py`:

```python
def spatial_layout_generator_wrapper(context: Dict[str, Any]) -> str:
    """
    Tool wrapper for spatial_layout_generator.
    
    Context expects:
    - planning_scheme: dict or str (planning text or parsed intent)
    - village_boundary: optional GeoJSON
    - road_network: optional GeoJSON
    - constraint_zones: optional dict
    """
    planning_scheme = context.get("planning_scheme", {})
    # ... extract parameters, create engine, call generate()
    # Return JSON string with GeoJSON layers
```

**IMPL_STATUS upgrade path**: STUB -> MOCK (with jintian test data) -> IMPLEMENTED

### 4.2 planning_vectorizer (Backend Tool)

**File**: `backend/app/tools/core/planning_vectorizer.py`

This tool is a subset of spatial_layout_engine that handles the structured JSON -> GeoJSON conversion step. It can be called directly when the planning intent JSON is already available (e.g., from a previous parse).

```python
class PlanningVectorizer:
    """Convert structured planning intent to GeoJSON"""
    
    def __init__(self, gis_context: SharedGISContext):
        self.gis_context = gis_context
        self.zone_gen = ZoneGenerator(gis_context)
        self.facility_placer = FacilityPlacer(gis_context)
        self.axis_builder = AxisBuilder(gis_context)
    
    def vectorize(self, intent: PlanningIntent) -> Dict[str, FeatureCollection]:
        """Convert intent to {zones: FeatureCollection, facilities: FeatureCollection, axes: FeatureCollection}"""
        pass
```

### 4.3 map_renderer (Backend Tool)

**File**: `backend/app/tools/core/map_renderer.py`

```python
class MapRenderer:
    """Style GeoJSON layers and assemble GISLayerConfig for frontend"""
    
    def render(self, geojson_layers: Dict[str, FeatureCollection], 
               center: Tuple[float, float]) -> List[Dict]:
        """
        Convert raw GeoJSON to GISLayerConfig list with proper colors/styles.
        
        Maps:
        - zones -> function_zone layerType with PLANNING_COLORS.function_zone
        - facilities -> facility_point layerType with PLANNING_COLORS.facility_point
        - axes -> development_axis layerType with PLANNING_COLORS.development_axis
        """
        pass
```

### 4.4 Implementation Sequence (MVP-first)

**Phase 1 - MVP (1-2 weeks)**: Get zones rendering on map
1. Implement `ZoneGenerator` with simplified quadrant-based subdivision
2. Implement `SpatialLayoutEngine.generate()` using Flash LLM parse + ZoneGenerator
3. Add `spatial_layout_generator_wrapper` to `GIS_TOOL_WRAPPERS`
4. Add `POST /api/dev/gis/test/spatial-layout` endpoint (referenced by frontend but missing)
5. Test with jintian test data

**Phase 2 - Complete Tools (1 week)**: Add facilities, axes, and renderer
6. Implement `FacilityPlacer`
7. Implement `AxisBuilder`
8. Implement `PlanningVectorizer`
9. Implement `MapRenderer`
10. Add `planning_vectorizer_wrapper` and `map_renderer_wrapper` to `GIS_TOOL_WRAPPERS`
11. Update `IMPL_STATUS` from STUB to IMPLEMENTED

**Phase 3 - Feedback Loop (1-2 weeks)**: Human-in-the-loop spatial editing
12. Add `ConstraintSolver` with constraint validation
13. Implement `SpatialLayoutEngine.adjust()` for incremental updates
14. Add `POST /api/session/{id}/spatial-feedback` endpoint
15. Add database model for `SpatialLayoutState`

**Phase 4 - Frontend Editing (1 week)**: Interactive map editing
16. Add MapLibre Draw plugin for polygon/point editing
17. Add editing toolbar UI
18. Wire up feedback API calls
19. Add visual constraint violation indicators

---

## 5. Frontend Changes for Interactive Editing

### 5.1 MapLibre Draw Integration

Add `@maplibre/maplibre-gl-draw` (or `mapbox-gl-draw` compatible fork) to the MapView component:

```typescript
// New dependency: @maplibre/maplibre-gl-draw
// Or: use mapbox-gl-draw which is compatible with maplibre-gl

import MapboxDraw from '@maplibre/maplibre-gl-draw';

// In MapView component:
const drawRef = useRef<MapboxDraw | null>(null);

// Initialize draw control when map loads
const onMapLoad = useCallback((event) => {
  const map = event.target;
  drawRef.current = new MapboxDraw({
    displayControlsDefault: false,
    controls: {
      polygon: true,
      point: true,
      line_string: true,
      trash: true,
    },
    modes: {
      ...MapboxDraw.modes,
      // Custom mode for zone resizing
    },
  });
  map.addControl(drawRef.current);
}, []);

// Listen for draw events
map.on('draw.create', handleDrawCreate);
map.on('draw.update', handleDrawUpdate);
map.on('draw.delete', handleDrawDelete);
```

### 5.2 Editing Toolbar Component

New component: `frontend/src/features/planning/components/gis/EditingToolbar.tsx`

```typescript
interface EditingToolbarProps {
  enabled: boolean;           // Whether editing mode is active
  selectedLayer: string;      // Currently selected layer type
  onModeChange: (mode: EditingMode) => void;
  onApply: (changes: SpatialChange[]) => void;
  onReset: () => void;
}

type EditingMode = 'select' | 'move' | 'resize' | 'draw' | 'delete';
```

Features:
- Toggle between view and edit modes
- Select a zone/facility/axis by clicking
- Move by dragging
- Resize zone by dragging vertices
- Add new features by drawing
- Delete by selecting + trash button
- "Apply Changes" button sends feedback to backend
- "Reset" button reverts to last server state

### 5.3 Constraint Visualization

When constraint violations exist, render them as hatched overlay patterns:

```typescript
// In MapView, add a separate layer for constraint violations
const constraintLayer: FillLayerSpecification = {
  id: 'constraint-violations',
  type: 'fill',
  paint: {
    'fill-pattern': 'hatch-pattern',  // Custom pattern
    'fill-color': '#FF0000',
    'fill-opacity': 0.3,
  },
  filter: ['==', 'has_violation', true],
};
```

### 5.4 MapView State Extensions

Add to MapView props:

```typescript
interface MapViewProps {
  // ... existing props
  editable?: boolean;                    // Enable editing mode
  onFeatureUpdate?: (updates: FeatureUpdate[]) => void;  // Callback for edits
  constraintViolations?: ViolationReport[];  // Display violations
  highlightFeatureId?: string;           // Highlight a specific feature
}
```

---

## 6. Integration with Existing Review/Feedback System

### 6.1 Review Service Extension

The existing `ReviewService` in `backend/app/services/review.py` has three actions: approve, reject, rollback. The spatial feedback mechanism extends this with a new action type:

**Option A (Recommended)**: Extend reject with spatial data

When the user rejects a planning step and the step involves spatial layout, the reject action can carry spatial adjustment data alongside text feedback:

```python
# In ReviewService.reject():
# The existing `images` parameter already supports multimodal feedback.
# Add a `spatial_adjustments` parameter:
async def reject(
    session_id: str,
    feedback: str,
    dimensions: Optional[List[str]] = None,
    review_id: Optional[str] = None,
    images: Optional[List[Dict]] = None,
    spatial_adjustments: Optional[List[Dict]] = None,  # NEW
) -> RejectResponse:
    # ... existing code ...
    await PlanningRuntimeService.aupdate_state(session_id, {
        "need_revision": True,
        "revision_target_dimensions": dimensions or [],
        "human_feedback": feedback,
        "revision_feedback": feedback,
        "is_revision": True,
        "revision_images": images or [],
        "spatial_adjustments": spatial_adjustments or [],  # NEW
        "pause_after_step": False,
    }, as_node="revision")
```

### 6.2 Agent Graph Integration

When the agent processes the revision (after a reject with spatial_adjustments), the `analyze_dimension` node should:

1. Check if `spatial_adjustments` is present in state
2. If so, call `SpatialLayoutEngine.adjust()` instead of generating from scratch
3. The adjusted layout becomes part of the revised dimension report

This requires adding `spatial_adjustments` to `AgentState`:

```python
class AgentState(TypedDict, total=False):
    # ... existing fields ...
    spatial_adjustments: List[Dict[str, Any]]  # NEW: human spatial feedback
```

### 6.3 SSE Event for Layout Updates

When spatial layout is generated or adjusted, emit a dedicated SSE event:

```python
# In SSE event types
"spatial_layout_generated": {
    "session_id": str,
    "layers": GISLayerConfig[],
    "statistics": {...},
    "constraint_violations": [...],
    "version": int,
}
```

The frontend already handles `gis_result` events. Add `spatial_layout_generated` as a new event type that the MapView component listens for.

### 6.4 Revision Cascade Consideration

The existing revision cascade system (`revision_impact_tree`, `revision_completed_dims`) handles dimension-level dependencies. Spatial layout adjustments should be treated as part of the `spatial_structure` dimension revision. When spatial layout is adjusted:

1. The `spatial_structure` dimension is marked as revised
2. Downstream dimensions that depend on `spatial_structure` (e.g., `land_use_planning`, `settlement_planning`, `project_bank`) are flagged for potential revision
3. The revision cascade in `AgentState.revision_impact_tree` propagates changes

No changes needed to the cascade mechanism itself -- it already handles this case since `spatial_structure` is already a dimension with dependencies defined in `phases.yaml`.

---

## 7. Key Implementation Details

### 7.1 PlanningIntent Schema (Python)

```python
from pydantic import BaseModel
from typing import List, Optional, Dict

class LocationBias(BaseModel):
    direction: str  # center/north/south/east/west/northeast/northwest/southeast/southwest/edge
    reference_feature: str = ""

class Adjacency(BaseModel):
    adjacent_to: List[str] = []
    avoid_adjacent_to: List[str] = []

class ZoneIntent(BaseModel):
    zone_id: str
    land_use: str
    area_ratio: float
    location_bias: LocationBias
    adjacency: Adjacency
    density: str = "medium"  # low/medium/high

class FacilityIntent(BaseModel):
    facility_id: str
    facility_type: str
    status: str  # 现状保留/规划新建/规划改扩建/规划迁建
    location_hint: str
    service_radius: int = 500

class AxisIntent(BaseModel):
    axis_id: str
    axis_type: str  # primary/secondary/corridor/connector
    direction: str  # east-west/north-south/northeast-southwest/etc.
    reference_feature: str = ""

class PlanningIntent(BaseModel):
    zones: List[ZoneIntent]
    facilities: List[FacilityIntent]
    axes: List[AxisIntent]
    rationale: str = ""
    development_axes: List[str] = []
```

### 7.2 Color Assignment (Synchronized with Frontend)

The backend `MapRenderer` must assign colors matching `PLANNING_COLORS` in `frontend/src/features/planning/constants/gis.ts`:

```python
# These MUST match the frontend PLANNING_COLORS exactly
ZONE_COLORS = {
    "居住用地": "#FFD700",
    "产业用地": "#FF6B6B",
    "公共服务用地": "#4A90D9",
    "生态绿地": "#90EE90",
    "交通用地": "#808080",
    "水域": "#87CEEB",
    "农业用地": "#8B4513",
    "商业用地": "#FFA500",
}

FACILITY_COLORS = {
    "现状保留": "#006400",
    "规划新建": "#00008B",
    "规划改扩建": "#CC8400",
    "规划迁建": "#800080",
}

AXIS_COLORS = {
    "primary": "#FF0000",
    "secondary": "#00AA00",
    "corridor": "#0000FF",
    "connector": "#888888",
}
```

Each GeoJSON feature should have a `color` property set by MapRenderer. The frontend MapView already uses `['get', 'color']` for data-driven fill-color.

### 7.3 Using landuse_current as Placement Guide

The jintian `landuse_current.geojson` data has properties:
- `DLBM`: land use code (1100=耕地, 2121=宅基地, 3100=水域, etc.)
- `DLMC`: Chinese name
- `DLMJ`: area in square meters

The `landuse_planned.geojson` has:
- `GHYTBM`/`GHFLBM`: planned use code
- `GHYTMC`: planned use name (商品林, 宅基地, etc.)

The ZoneGenerator should use a mapping from planning intent `land_use` to DLBM codes:

```python
LAND_USE_TO_DLBMS = {
    "居住用地": ["2121"],          # 宅基地
    "产业用地": ["2010", "2020"],   # 工矿仓储用地
    "农业用地": ["1100", "1200", "1300", "1400", "1510"],  # 耕/园/林/草/设施农
    "水域": ["3100"],              # 水域
    "生态绿地": ["1300"],          # 林地
    "交通用地": ["1030"],          # 公路用地
    "公共服务用地": ["0810", "0830"],  # 公共设施/科教文卫
    "商业用地": ["0510", "0520"],   # 零售/餐饮
}
```

When generating zones, the algorithm first identifies existing landuse_current features whose DLBM matches the zone's land_use type, then uses those polygons as seeds for the zone geometry. This produces realistic layouts that respect the current spatial structure.

### 7.4 Error Handling and Fallbacks

1. **No boundary data**: Use `SharedGISContext.get_or_generate_boundary()` which has fallback strategies
2. **No landuse_current data**: Fall back to pure quadrant-based subdivision without placement guidance
3. **No road data**: Skip road-snapping for facility placement
4. **LLM parse failure**: Return partial result with error metadata, don't crash the agent
5. **Constraint violation**: Generate layout anyway, include violation report, let human decide

### 7.5 Testing Strategy

Use the jintian test data (loaded via `SharedGISContext.load_jintian_test_data()`) for development:
- `boundary_current.geojson`: Village boundary polygon
- `landuse_current.geojson`: Current land use polygons with DLBM codes
- `landuse_planned.geojson`: Planned land use (reference for expected output)
- `road_planned.geojson`: Road network for axis/facility placement

The existing `/api/dev/gis/test/spatial-layout` endpoint (referenced in frontend but not yet implemented in backend) should be created as the primary test interface.

---

## 8. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| GeoPandas/shapely not available | Guard all geometry code with `GEOPANDAS_AVAILABLE` check; provide simplified bbox-based fallback |
| LLM generates invalid intent JSON | Use Pydantic validation with generous defaults; re-prompt with ZONE_AREA_ADJUSTMENT_PROMPT |
| Generated polygons overlap | Run ConstraintSolver; subtract overlaps with priority ordering (larger zones keep area) |
| Area ratios don't sum to 1.0 | Normalize ratios before geometry generation; use ZONE_AREA_ADJUSTMENT_PROMPT for LLM correction |
| Frontend draw library incompatibility | Use `@maplibre/maplibre-gl-draw` which is officially maintained for MapLibre GL |
| Large GeoJSON performance | Simplify polygons before sending (tolerance-based); use vector tiles for >1000 features |
| Constraint data unavailable | Skip constraint validation, generate unconstrained layout with warning in metadata |

---

## 9. File Change Summary

### New Files (9)
1. `backend/app/services/modules/gis/layout_algorithms/__init__.py`
2. `backend/app/services/modules/gis/layout_algorithms/zone_generator.py`
3. `backend/app/services/modules/gis/layout_algorithms/facility_placer.py`
4. `backend/app/services/modules/gis/layout_algorithms/axis_builder.py`
5. `backend/app/services/modules/gis/layout_algorithms/constraint_solver.py`
6. `backend/app/tools/core/spatial_layout_engine.py`
7. `backend/app/tools/core/planning_vectorizer.py`
8. `backend/app/tools/core/map_renderer.py`
9. `frontend/src/features/planning/components/gis/EditingToolbar.tsx`

### Modified Files (8)
1. `backend/app/tools/core/gis_tool_wrappers.py` - Add 3 new wrappers
2. `backend/app/tools/protocol.py` - Upgrade IMPL_STATUS after implementation
3. `backend/app/agent/state.py` - Add spatial_adjustments field
4. `backend/app/services/review.py` - Add spatial_adjustments parameter to reject()
5. `backend/app/api/session_routes.py` - Add spatial feedback endpoint
6. `frontend/src/features/planning/components/gis/MapView.tsx` - Add editing mode, draw control
7. `frontend/src/types/message/message-types.ts` - Add spatial feedback types
8. `frontend/src/features/planning/constants/gis.ts` - Add editing-related constants

---

## 10. MVP Definition (Minimum Viable Product)

The MVP delivers value with the smallest scope:

**MVP Scope**:
1. `ZoneGenerator` with quadrant-based subdivision + landuse_current seed placement
2. `SpatialLayoutEngine.generate()` with Flash LLM parsing
3. `spatial_layout_generator_wrapper` registered in `GIS_TOOL_WRAPPERS`
4. `POST /api/dev/gis/test/spatial-layout` endpoint
5. Frontend: existing MapView renders generated zones (no editing yet)

**MVP Success Criteria**:
- Given jintian test data + a planning text, the system generates zone polygons that:
  - Respect the village boundary
  - Have areas proportional to the intent's area_ratio
  - Are placed in the correct direction quadrants
  - Use existing landuse as placement seeds
  - Render correctly in MapView with proper colors

**What MVP deliberately excludes**:
- Facility placement (Phase 2)
- Axis generation (Phase 2)
- Human spatial feedback loop (Phase 3)
- Interactive map editing (Phase 4)
- Constraint validation (Phase 3)
