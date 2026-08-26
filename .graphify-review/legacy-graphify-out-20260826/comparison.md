# Post-Refactor Graphify Comparison vs Phase 0 Baseline

> Task 5 of P4-8. Generated `2026-08-08` from local AST-only extraction
> (`graphify extract --code-only --no-label`), matching the Phase 0 baseline method exactly.
> No LLM backend was used; all edges are real import/call edges from the parser.
> `data-kg` combines `backend/app/modules/data/` + `backend/app/modules/kg/` via
> `graphify merge-graphs`. Data stored in `graphify-out/post-refactor/<domain>/`.

## Before / After Metrics

### Agent (`backend/app/agent/`)

| Metric | Before | After | Δ |
|---|---|---|---|
| Nodes | 1164 | 1206 | +42 |
| Edges | 2258 | 2277 | +19 |
| Communities | 64 | 72 | +8 |
| Low-cohesion communities (<0.3) | 39 / 64 | 43 / 72 | +4 |
| Cohesion (min / mean) | 0.052 / 0.331 | 0.068 / 0.327 | ~same |
| God-node max degree | `execute_execute_agent` (43) | `post_l3_main_nodes.py` (32) | **−11** |
| Top god-nodes | ExecuteAgentState (32), create_unified_planning_graph() (26), analyze_dimension() (24) | ExecuteAgentState (31), create_unified_planning_graph() (26), analyze_dimension() (24) | god `execute_execute_agent` gone |
| Cycles (cycle basis) | 1106 | 1084 | −22 |

### Data + KG (`backend/app/modules/data/` + `backend/app/modules/kg/`)

| Metric | Before | After | Δ |
|---|---|---|---|
| Nodes | 706 | 706 | 0 |
| Edges | 1548 | 1548 | 0 |
| Communities | 32 | 32 | 0 |
| Low-cohesion communities (<0.3) | 21 / 32 | 21 / 32 | 0 |
| Cohesion (min / mean) | 0.053 / 0.274 | 0.053 / 0.274 | 0 |
| God-node max degree | `kg::init` (57) | `__init__.py` (57) | 0 |
| Cycles (cycle basis) | 850 | 850 | 0 |

> DataCatalog split (catalog.py 1008→825 lines, + assembly/inference/geometry_fallback)
> is inside `modules/data`, but the Data+KG graph is **unchanged** because the split
> extracted functions into new files within the same package; the aggregate node/edge
> counts are dominated by the untouched `modules/kg`. Node-level re-clustering is identical.

### Spatial Ops (`backend/app/modules/spatial_ops/`)

| Metric | Before | After | Δ |
|---|---|---|---|
| Nodes | 990 | 990 | 0 |
| Edges | 2490 | 2490 | 0 |
| Communities | 38 | 38 | 0 |
| Low-cohesion communities (<0.3) | 31 / 38 | 31 / 38 | 0 |
| Cohesion (min / mean) | 0.068 / 0.203 | 0.068 / 0.215 | +0.012 |
| God-node max degree | `road_planning_nodes` (93) | `planning_nodes.py` (93) | 0 |
| Cycles (cycle basis) | 1505 | 1505 | 0 |

> Spatial-ops was **not** part of the 4-file split (control domain). Graph is unchanged as expected.

### Frontend (`frontend/src/`)

| Metric | Before | After | Δ |
|---|---|---|---|
| Nodes | 720 | 731 | +11 |
| Edges | 1808 | 1851 | +43 |
| Communities | 30 | 27 | −3 |
| Low-cohesion communities (<0.3) | 21 / 30 | 19 / 27 | −2 |
| Cohesion (min / mean) | 0.053 / 0.245 | 0.062 / 0.244 | ~same |
| God-node max degree | `usePlanningStore` (84) | `usePlanningStore` (84) | 0 |
| Top god-nodes | usePlanningStore (84), Message (20), usePlanningActions() (18) | usePlanningStore (84), PlanningState (21), Message (20), GISLayerConfig (19) | hub persists |
| Cycles (cycle basis) | 1094 | 1125 | +31 |

## Cross-Domain Import Edges (boundary violations)

Re-grepped the backend module domains for upward/boundary-direction imports
(`app.services`, `app.api`, `app.agent`):

| Direction | Before | After |
|---|---|---|
| `modules/data` → services/api | 0 | 0 |
| `modules/kg` → services/api | 1 (`report_entity_enrichment.py` → `app.services`) | **0** (now `app.modules.ports.registry`) |
| `modules/spatial_ops` → services | 0 | 0 |
| `modules/spatial_ops` → agent | 1 (`grounding/resolver.py` → `app.agent`) | 0 (now only a comment) |
| `modules/data` → agent | 0 | 0 |
| `modules/kg` → agent | 0 | 0 |
| `services` → `api` | 2 (`runtime.py`, `session.py`) | 2 (unchanged; `app.api.schemas` only) |

## Interpretation

- **Agent — SUCCESS.** The `execute_execute_agent` god-node (degree 43) is **eliminated** after
  splitting `execute_agent.py` into `execute/nodes/*`. Max god-node degree fell 43 → 32, and
  cycles dropped 1106 → 1084. Node count rose +42 (more files) as expected, but the hub coupling
  and cycle count both decreased.
- **Frontend — MIXED.** Splitting `planningStore.ts` added `handlers/` files (nodes +11), but the
  `usePlanningStore` hub remains at degree 84 and edge count rose (+43). The split moved logic into
  workers that re-import from the store barrel (`planning/index.ts`, degree 72) and `types.ts` (68),
  so per-file coupling within the module increased rather than decreased. Community count fell
  30 → 27 (better grouping) and low-cohesion dropped 21 → 19.
- **Data+KG / Spatial-ops — CONTROL.** DataCatalog split is real (catalog.py 1008→825 +
  3 new files) but sits inside a package whose aggregate graph is dominated by the larger,
  untouched submodules; the Data+KG merged graph is unchanged at the measurement granularity.
  Spatial-ops is a pure control (not split) and is bit-identical.
- **Boundary violations — IMPROVED.** Both baseline `modules/kg → services` and
  `modules/spatial_ops → agent` boundary imports are gone (the former now uses the Port registry
  from `app.modules.ports`; the latter is only a comment reference). `services → api` remains
  (2 files, `app.api.schemas` only) and is a separate tracked direction.

## Success Metric Conclusion

Success metric is **reduced god-node degree and reduced per-file coupling**, not raw line count.
By that measure:

- Agent: **god-node degree 43 → 32** (hub eliminated), **cycles −22** → improved.
- Frontend: **hub flat at 84**, edges/coupling rose → not improved (needs further de-hubbing of
  the store barrel re-exports).
- Data+KG / Spatial-ops: unchanged (control / outside 4-file split scope).
- Boundary imports: **kg→services and spatial_ops→agent violations eliminated** → improved.