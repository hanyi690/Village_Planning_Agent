# Wave 0 Task 1 baseline: empty planning delivery

Date: 2026-08-17

This baseline records the evidence and acceptance boundary for the first
vertical slice. It is intentionally separate from the implementation-status
documents, which contain historical claims from earlier runs.

## Current evidence

The active 金田村 demonstration can finish upstream analysis without an
authoritative `delivery_manifest`, `delivery_spatial_snapshot`, or
`render_layers` reference. In that case `/sessions/{session_id}/map-layers`
must not imply that the map is complete; it returns an explicit
`no_planning_output` status when a manifest exists, and retains the existing
404 behavior when no delivery artifact exists at all.

The isolated historical run used during the design audit had the following
shape:

| Artifact fact | Count / result |
|---|---:|
| `complete_planned_landuse` features | 660 |
| actual `ParcelChange` features | 0 |
| project point overlays | 17 |
| facility point overlays | 16 |
| planned road layer | absent |
| planned zone layer | absent |
| planned changes layer | absent |

The 660 features are current/baseline parcels carried into the complete
planned view. They are not evidence of a planning land-use change. The
project and facility points are useful diagnostic overlays but do not, by
themselves, prove a complete parcel, road, zone, or network plan.

The existing `integrated_planning_map.png` is produced by a standalone
renderer reading `data/gis/jintian/current`, `data/gis/jintian/planned`,
reports, and the gazetteer. It is not a `DeliverySpatialSnapshot` or
`RenderLayers` artifact from the main workflow and is excluded from this
acceptance.

## Test command trap

The repository `pytest.ini` applies an e2e marker filter by default. A command
that names core tests without overriding `addopts` can report zero collected
tests with exit code 0. Focused verification must use:

```powershell
pytest -o addopts='' -p no:cacheprovider -q <test-paths>
```

The pre-Task-1 focused audit previously observed 19 passing and 3 failing
tests when the default filter was disabled. The three failures were stale
semantic-contract fixtures that omitted the now-required closed-set road
`asset_kind`; they were not evidence that a real plan had been delivered.

## Wave 0 output contract

`DELIVER` now records `planning_output` and `spatial_yield` in the manifest
diagnostic summary. The yield records the following immutable boundaries:

```text
PlanningProgram → TargetProjection → Grounding → Selection
→ Execution → PlannedState → DeliverySnapshot → RenderLayers
```

Each record includes input/output counts, deferred count, non-baseline feature
count, and the relevant artifact digest. `RenderLayers` counts exclude current
land-use, current roads, boundary, and input constraints. Unchanged features
in `complete_planned_landuse` are treated as baseline copies.

When no non-baseline planning feature survives this boundary:

- the manifest remains `partial`, never `complete`;
- `statutory_complete` is false;
- the delivery gate routes to `END_DIAGNOSTIC` with
  `deliver_no_planning_output`;
- map-layer projection reports `no_planning_output` and an empty planning
  layer list when refs are missing or the render payload is baseline-only;
- the real 金田村 runner prints the status and first zero stage;
- `scripts/audit_planning_layer_quality.py` does not inspect static planned
  GIS inputs.

## Controlled vertical-slice fixture

`backend/tests/characterization/fixtures/jintian_minimal_planning_problem.json`
contains a typed facility target with an exact point candidate and a typed
road endpoint/network reference. The integration test creates a
`PlannedState` from that typed input, sends it through the authoritative
delivery snapshot and render-layer builders, and asserts that the facility
feature is visible with its target lineage. It does not load a static planned
layer or invoke the standalone PNG renderer as a source of features.

The fixture is a controlled delivery boundary characterization. Full
PlanningProgram → TargetProjection → Ground → Select → Execute orchestration
remains a Wave 3 integration requirement and must use the same non-baseline
feature and artifact evidence checks.
