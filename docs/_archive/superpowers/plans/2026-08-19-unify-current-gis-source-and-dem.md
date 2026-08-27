# Unified Current GIS Source and DEM Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the incomplete static `jintian-offline.json` fallback with a read-only API projection of the same complete current GIS bundle used by the example/session catalog, while exposing DEM as raster metadata rather than a fake GeoJSON layer.

**Architecture:** Add a stable v1 read-only source-layer endpoint that loads the configured village bundle through `DataCatalog`, serializes all current vector groups with authoritative layer metadata, and returns a separate DEM manifest from the configured local raster source. The frontend will consume this endpoint for the current/reference base layers, merge session planning layers on top, and keep `/map-layers` reserved for DELIVER outputs.

**Tech Stack:** FastAPI/Pydantic v2, existing `DataCatalog`/`VillageBundle`, Next.js/React/TypeScript, existing GIS layer normalizer.

## Global Constraints

- Do not change backend workflow or spatial business logic; backend changes are read-only API transport and contract code only.
- Do not fabricate vector features or planning outputs.
- Use the configured catalog sources, not `backend/tests/fixtures` paths, as the runtime source of current GIS data.
- Do not put DEM raster bytes into the GeoJSON layer collection or count DEM as a vector feature layer.
- Keep DELIVER `/api/v1/sessions/{id}/map-layers` authoritative for planning-result layers.
- Do not silently fall back to the incomplete static two-layer file when the complete source API fails; surface source failure in the UI.

---

### Task 1: Add a complete current-source API projection

**Files:**
- Create: `backend/app/api/v1/routes/source_layers.py`
- Modify: `backend/app/api/v1/contracts.py`
- Modify: `backend/app/api/v1/routes/__init__.py`
- Test: existing API route/contract test location under `backend/tests`

**Interfaces:**
- Produces `GET /api/v1/source-layers?village_name=金田村`.
- Returns `{schema_version, village_name, source, layers, rasters}`.
- Each vector layer returns `{layer_name, layer_type, display_role, data_authority, feature_count, crs, geojson}`.
- Each raster manifest returns `{layer_name, layer_type, format, crs, available, resolution, width, height, bands, bounds, source_ref}` without a local filesystem path or raster bytes.

- [x] **Step 1: Write contract tests for complete vector names/counts and separate DEM metadata**
- [x] **Step 2: Implement a route that reads the configured current vector sources through `DataCatalog`**
- [x] **Step 3: Map configured source semantics into stable human-readable layer metadata**
- [x] **Step 4: Read the configured DEM source only for raster metadata**
- [x] **Step 5: Register the route in the v1 router and verify OpenAPI generation**

### Task 2: Add frontend API/client types and replace the incomplete fallback

**Files:**
- Modify: `frontend/src/features/planning/api/types.ts`
- Modify: `frontend/src/features/planning/api/planning-api.ts`
- Modify: `frontend/src/features/planning/utils/offline-basemap.ts` or replace with a current-source loader
- Modify: `frontend/src/features/planning/components/PlanningWorkbenchPage.tsx`

**Interfaces:**
- Consumes `planningApi.getSourceLayers(villageName)`.
- Produces normalized `GISLayerConfig[]` for all current vector layers and `RasterManifest[]` for terrain status.

- [x] **Step 1: Add TypeScript contracts for source layers and raster manifests**
- [x] **Step 2: Add `planningApi.getCurrentSourceLayers()` for the snake_case transport contract**
- [x] **Step 3: Replace `/basemap/jintian-offline.json` loading with the source-layer API**
- [x] **Step 4: Preserve session GIS layers and merge them over current source layers**
- [x] **Step 5: Remove the silent two-layer fallback and surface source errors**
- [x] **Step 6: Show a compact “现状数据源 / DEM” status in the spatial page without adding DEM to vector counts**

### Task 3: Validate the real example data path

**Files:**
- Test: backend API tests and frontend API/type checks
- Verify: browser spatial page using the running backend

- [x] **Step 1: Verify the API reports all configured current vector counts**
- [x] **Step 2: Verify the API reports DEM availability and metadata separately**
- [x] **Step 3: Verify the source-backed spatial page reports real current layer totals**
- [x] **Step 4: Keep DELIVER planning layers separate from current source layers**
- [x] **Step 5: Run backend focused tests, frontend type-check, and production build**
