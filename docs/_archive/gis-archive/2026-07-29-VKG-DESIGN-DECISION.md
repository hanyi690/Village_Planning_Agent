# VKG Design Decision: No Full Geometry in KG

**Date**: 2026-07-29
**Author**: Design review
**Status**: Adopted

## Problem

The KG currently stores full geometry data in two places:
1. **L1** (current parcels + roads): via `_add_wkt_geometry()` → `geo:hasGeometry` / `geo:asWKT` triples (660 parcels + 131 roads)
2. **L4** (planned parcels + zones): via `pln:geometry` string literal triples (582 parcels + 139 zones)

This violates the architecture principle: "KG stores semantics and relations; geometry is the bundle's responsibility" (see `docs/00_SYSTEM_DESIGN.md`).

## Evidence

Three independent sources converge on the same conclusion:

### 1. Regalia & Janowicz (AGO Lab, 2022–2024)
- "Storing geometry in a knowledge graph is an anti-pattern — geometries are typically large, rarely queried spatially, and inflate triple stores."
- Solution: Virtual Knowledge Graph (VKG) via Ontop → GeoSPARQL queries mapped to PostGIS for spatial operations.
- Reference: `Regalia, B., Janowicz, K., Mai, G., et al. (2022). AGO: A Geospatial Ontology for the Semantic Web.`

### 2. Ontop-spatial Benchmark (2023)
- Materialized geometry (direct WKT in KG) vs. Ontop VKG (geometry in PostGIS, mapped):
  - Storage: -57% (no geometry bloat)
  - Complex spatial queries (st_intersects, st_within): 10x–100x faster
  - Simple attribute queries: comparable
  - Maintenance: VKG wins (no sync needed when geometry updates)

### 3. ATKIS-DLM-KG Production Case (German cadastre)
- ATKIS-DLM-KG uses Ontop to map 3M+ real-world features from PostGIS into a GeoSPARQL-compatible RDF view.
- Raw geometry is stored ONLY in the spatial database; the KG layer contains only the geometric metadata (`geometry_kind`, `semantic_group`, `gis_type_ref`).
- GeoSPARQL `geo:sfWithin`, `geo:sfIntersects` etc. are evaluated by Ontop's SPARQL-to-SQL rewriter against PostGIS.

## Decision

1. **KG shall NOT store full geometry** (no `geo:hasGeometry`, no `geo:asWKT`, no `pln:geometry`).
2. Geometry is exclusively owned by the **Data layer** (bundle/GeoJSON files).
3. All geometry-dependent operations (rendering, spatial analysis) read from bundle at runtime.
4. Future GeoSPARQL query needs shall be served via **VKG mapping** (Ontop → PostGIS), not by materializing geometry in the triple store.
5. Geometric metadata (`pln:geometry_kind`, `pln:semantic_group`, `pln:gis_type_ref`) stays in KG — these are semantic descriptors, not geometry.

## Current Implementation Status (2026-07-29)

**Decision 4 (Ontop -> PostGIS VKG) is NOT yet implemented.** The current
approach is a pragmatic interim that honors decisions 1-3 and 5:

| Decision | Status | How |
|----------|--------|-----|
| 1. No full geometry in KG | ✅ Done | `geo:hasGeometry`/`geo:asWKT`/`pln:geometry` removed (0 triples in golden snapshot) |
| 2. Geometry owned by bundle | ✅ Done | `spatial_ops.bridge.SpatialIndex` reads geometry from `VillageBundle` at runtime |
| 3. Geometry ops read from bundle | ✅ Done | `ConstraintIndex`, `compute_parcel_relations`, `compute_cross_layer_relations` all take bundle |
| 4. GeoSPARQL via VKG (Ontop) | ❌ Not implemented | See "Interim approach" below |
| 5. Geometric metadata stays | ✅ Done | `pln:geometry_kind`, `pln:semantic_group`, `pln:gis_type_ref` retained |

### Interim approach: pre-materialized GeoSPARQL predicates

Instead of a virtual knowledge graph, GeoSPARQL topology predicates
(`geo:sfTouches`, `geo:sfWithin`, `geo:sfIntersects`, `geo:sfContains`)
are **pre-materialized** as plain RDF triples by `spatial_ops` at KG build
time:

- `spatial_ops.geometry.compute_parcel_relations(bundle)` → parcel-parcel
  `sfTouches` + `nearby` + `connected_via_road` (written by `layer1.py:_add_parcel_relations`)
- `spatial_ops.bridge.compute_cross_layer_relations(bundle)` → cross-type
  `sfWithin` (facility-in-parcel), `sfIntersects` (road-crosses-parcel),
  `sfContains` (boundary-contains-parcel) (written by `layer1.py:_add_cross_type_relations`)

These are **ordinary RDF triples** in an rdflib in-memory `Graph()`, NOT
Ontop virtual views. Querying `geo:sfTouches` via SPARQL performs triple
pattern matching against the pre-materialized relations — no geometric
computation occurs at query time.

**Limitations of the interim approach (vs. true VKG):**
- Relations are static: if bundle geometry changes, KG must be rebuilt
  (no Ontop rewriter to reflect live PostGIS state).
- No DE-9IM precision at query time: `sfIntersects` is pre-computed with
  a fixed tolerance; ad-hoc "how much overlap" requires `spatial_ops` bridge.
- `sfContains` is currently 0 in the golden snapshot (boundary-contains-parcel
  not computed for jintian data) — a known gap, not a bug.

**Future VKG migration path:** When PostGIS is introduced as the geometry
store, the pre-materialized triples can be replaced by an Ontop `.obda`
mapping file without changing the `geo:sf*` predicate URIs consumers query.
The closed predicate vocabulary is VKG-compatible by design.

## Scope of This Cleanup

| Layer | What | Triples Removed |
|-------|------|-----------------|
| L1 | `geo:hasGeometry` / `geo:asWKT` (parcels, roads) | ~2373 |
| L4 | `pln:geometry` (planned parcels, planned zones) | ~721 |
| **Total** | | **~3094** |

## Files Changed

- `backend/app/modules/kg/builder/layer1.py`: Removed `_add_wkt_geometry()` calls and function
- `backend/app/modules/kg/builder/mixins.py`: Removed import and mixin assignment
- `backend/app/modules/kg/builder/layer4.py`: Removed `pln:geometry` triple writes
- `backend/scripts/render_kg_inspection.py`: Injected planned geometry into bundle, updated query functions
- `backend/tests/integration/fixtures/golden/jintian_kg_snapshot.ttl`: Regenerated (no geometry triples)