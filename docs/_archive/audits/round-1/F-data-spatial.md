# Round-1 Audit: data/ + spatial/ typed workspace modules (F)

Scope: `backend/app/data/{catalog,snapshots,ports}`, `backend/app/spatial/{query,grounding,allocation,network,change,validation}`.
Additive only; no existing `data/model`, `data/ingestion`, `spatial/model`, `spatial/delivery` file modified.

## Files created

### data/
- `data/catalog/collection_registry.py` — **defines** `CollectionRecord` (frozen pydantic: collection_id/schema/crs/digest/source/feature_count) and `CollectionRegistry` (`register`/`get`/`register_snapshot`/`keys`/`all`). **Reuses** `CollectionSnapshot` (via `from_snapshot`). The `schema` field shadows `BaseModel`; warning suppressed with a scoped `warnings.catch_warnings()`.
- `data/snapshots/data_quality.py` — **defines** `DataQualityReport` (collection_checks/total_features/issues/frozen) and `build_data_quality_report`. **Reuses** `SessionDataSnapshot` + `CollectionRecord`.
- `data/snapshots/snapshot_service.py` — **defines** `FrozenSessionSnapshot` (wrapper: snapshot + registry + quality, `refresh()` raises) and `freeze_session_snapshot(manifest, workspace)`. **Reuses** `SessionDataSnapshot.from_bundle`. Wrapper needed because `SessionDataSnapshot` is `frozen` + `extra="forbid"` and cannot carry the attachments.
- `data/ports/ingest.py` — **defines** `DataIngestPort` Protocol (`ingest(files, *, session_id) -> SessionDataSnapshot`). **Reuses** `SessionDataSnapshot`.

### spatial/
- `spatial/query/feature_query.py` — **defines** `FeatureQuery` + `query_workspace` (by layer across points/lines/polygons, bbox via shapely `box().intersects`, property filters) returning typed `SpatialFeature`. **Reuses** `SpatialWorkspace`, `app.modules.schema.types.base.SpatialFeature`.
- `spatial/grounding/grounding_service.py` — **re-exports** `CandidateSite`, `GroundingResult`, `HardConstraintResult`, `SpatialQueryEvidence` from `app.modules.schema.contracts.grounding_contracts`; thin workspace wrappers `ground_parcels_in_bbox`/`ground_parcels_near`/`resolve_spatial_reference` lazily delegate to `app.modules.spatial_ops.grounding.grounding`. No duplication.
- `spatial/allocation/allocation_problem.py` — **defines** `AllocationProblem`/`AllocationProblemSet`; **re-exports** `AllocationAssignment`, `AllocationStatus`, `PortfolioDecision` from `app.domain.allocation.model`.
- `spatial/network/network_index.py` — **defines** thin `NetworkIndex` (lazy imports `RoadNetworkBuilder`, builds from `workspace.lines["roads_current"]`); **re-exports** `NetworkBuildConfig`, `NetworkBuildResult`, `RoadNodeRecord`, `RoadEdgeRecord` from `app.modules.spatial_ops.road.schemas`. No reimplementation; heavy deps (geopandas/networkx) stay lazy.
- `spatial/change/parcel_change.py` — **re-exports** `ParcelChange`, `ParcelChangeSet`, `FacilityChange`, `RoadChange`, `SettlementChange` from `app.modules.schema.contracts.parcel_change_contracts` (single owner).
- `spatial/validation/spatial_quality.py` — **defines** `SpatialQualityReport` + `spatial_quality_check(geometries)` (validity, `make_valid` repair, `app.utils.area_engine.calculate_area_ha`). Reuses existing shapely/area helpers; shapely imported lazily.

Each package got an `__init__.py` re-exporting public symbols. All modules are import-light (no network/DB/LLM; heavy deps imported only inside functions).

## Verification
From `F:\project\Village_Planning_Agent\backend`:

```
python -c "import app.data.catalog.collection_registry; import app.data.snapshots.snapshot_service; import app.data.snapshots.data_quality; import app.data.ports.ingest; import app.spatial.query.feature_query; import app.spatial.grounding.grounding_service; import app.spatial.allocation.allocation_problem; import app.spatial.network.network_index; import app.spatial.change.parcel_change; import app.spatial.validation.spatial_quality; print('OK')"
=> OK
```
Also passed with `-W error::UserWarning` (the `schema` shadow warning is scoped-suppressed). A functional smoke test (fake bundle → `SpatialWorkspace.from_bundle` → freeze, registry, feature query, quality check, allocation/change/network wrapper) printed `FUNCTIONAL OK`.

## Notes
- `GroundingResult`/`CandidateSite` were located in `app/modules/schema/contracts/grounding_contracts.py` (referenced by `app/agent/ground/*`), not defined there — re-exported from the contracts module.
- `freeze_session_snapshot` returns `FrozenSessionSnapshot` (not bare `SessionDataSnapshot`) because the frozen manifest cannot be mutated; the wrapper carries the collection records + quality report and blocks refresh.
- Line endings LF, 4-space indent, double quotes throughout.
