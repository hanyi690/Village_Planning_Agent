# MVP village GeoJSON source validity audit

This audit is against the files uploaded by the real-session core test from
`backend/tests/fixtures/mvp_village/gis/`. It uses Shapely `is_valid` and
`explain_validity`; the raw files are not rewritten.

| Source file | Features | Invalid | First reason / locations |
|---|---:|---:|---|
| `ecological_protection.geojson` | 5 | 1 | feature index 4: `Ring Self-intersection` at `116.075681527946, 24.8391157538604` |
| `landuse.geojson` | 660 | 5 | feature indices 22, 104, 258, 446, 575: `Ring Self-intersection` |
| all other uploaded GIS files | 997 | 0 | no invalid geometry detected |

The five land-use samples include BSMs `441426211000049192`,
`441426211000049300`, and `441426211000055592`. The upload endpoint now stores
the bounded audit in the session's `uploaded_files` metadata, including the
feature index, reason, and BSM sample. This makes the original source
traceable in a stage report without copying all GeoJSON into the report.

## Handling decision

The source is retained unchanged for provenance. At the spatial boundary,
parcel and constraint geometries are checked with `is_valid`; invalid shapes
are repaired with Shapely `validation.make_valid`. A repair may produce a
`MultiPolygon` or `GeometryCollection`, so the adapter accepts valid multipart
results and drops only empty or unrecoverable results. No invalid geometry is
allowed into GEOS predicates such as `intersects` or `intersection`.

This is a fail-closed data-quality boundary: repair prevents a native GEOS
topology exception, but it does not invent missing village-to-BSM bindings.
When a required named village still has no real geometry, SELECT routes to
HUMAN and records the missing evidence instead of fabricating a parcel.

Official reference: [Shapely validation and make_valid documentation](https://github.com/shapely/shapely/blob/main/docs/manual.md).
