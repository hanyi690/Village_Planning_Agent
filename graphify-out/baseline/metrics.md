# Graphify Baseline Metrics

> Phase 0 baseline for post-Phase 4 comparison. Generated `2026-08-07` from local AST-only
> extraction (`graphify extract --code-only`), so all edges are real import/call edges found by
> the parser, not LLM-inferred. No LLM backend was configured, so community labels are
> auto-names derived from the dominant file per community (not semantic names).

## Method

- Each domain was extracted with `graphify extract --code-only --out <staging>` (local AST, no API key).
- `data-kg` combines `backend/app/modules/data/` + `backend/app/modules/kg/` by merging the two
  per-module graphs with `graphify merge-graphs`.
- Community detection / cohesion / god-node analysis from `graphify cluster-only --no-viz`,
  saved per domain at `graphify-out/baseline/<domain>/`.

## Metrics

### Agent (`backend/app/agent/` → `baseline/agent/`)

| Metric | Value |
|---|---|
| Nodes | 1164 |
| Edges | 2258 |
| Communities | 64 |
| Low-cohesion communities (cohesion < 0.3) | 39 / 64 |
| Cohesion (min / mean) | 0.052 / 0.331 |
| Largest degree (god-node) | `execute_execute_agent` (43) |
| Top god-nodes | `ExecuteAgentState` (32), `create_unified_planning_graph()` (26), `analyze_dimension()` (24) |
| Cycles (undirected cycle basis) | 1106 |

### Data + KG (`backend/app/modules/data/` + `backend/app/modules/kg/` → `baseline/data-kg/`)

| Metric | Value |
|---|---|
| Nodes | 706 |
| Edges | 1548 |
| Communities | 32 |
| Low-cohesion communities (cohesion < 0.3) | 21 / 32 |
| Cohesion (min / mean) | 0.053 / 0.274 |
| Largest degree (god-node) | `kg::init` (57) |
| Top god-nodes | `EntityTypes` (23), `PlanningKG` (21), `KGBuilder` (20), `add_geo_feature_type()` (20) |
| Cycles (undirected cycle basis) | 850 |

### Spatial Ops (`backend/app/modules/spatial_ops/` → `baseline/spatial-ops/`)

| Metric | Value |
|---|---|
| Nodes | 990 |
| Edges | 2490 |
| Communities | 38 |
| Low-cohesion communities (cohesion < 0.3) | 31 / 38 |
| Cohesion (min / mean) | 0.068 / 0.203 |
| Largest degree (god-node) | `road_planning_nodes` (93) |
| Top god-nodes | `build_planning_nodes()` (41), `score_road_candidates()` (24), `compare_road_plans()` (23) |
| Cycles (undirected cycle basis) | 1505 |

### Frontend (`frontend/src/` → `baseline/frontend/`)

| Metric | Value |
|---|---|
| Nodes | 720 |
| Edges | 1808 |
| Communities | 30 |
| Low-cohesion communities (cohesion < 0.3) | 21 / 30 |
| Cohesion (min / mean) | 0.053 / 0.245 |
| Largest degree (god-node) | `usePlanningStore` (84) |
| Top god-nodes | `usePlanningStore` (84), `Message` (20), `usePlanningActions()` (18) |
| Cycles (undirected cycle basis) | 1094 |

## Cross-Domain Import Edges (boundary violations)

Counted by grepping the three measured backend module domains for imports of
`app.services`, `app.api`, and `app.agent` (the upward/boundary directions the docs forbid):

| Direction | Files offending |
|---|---|
| `modules/data` → services/api | 0 |
| `modules/kg` → services/api | 1 (`kg/enrichment/report_entity_enrichment.py` → `app.services`) |
| `modules/spatial_ops` → services | 0 |
| `modules/spatial_ops` → agent | 1 (`spatial_ops/grounding/resolver.py` → `app.agent`) |
| `modules/data` → agent | 0 |
| `modules/kg` → agent | 0 |
| `services` → `api` | 2 (`services/runtime.py`, `services/session.py`) |

Notes:

- `modules/kg → services` is a single lazy import of the context service
  (`report_entity_enrichment.py:548`); `modules/spatial_ops → agent` is a single import in the
  grounding resolver (`grounding/resolver.py`).
- `app.services` importing `app.api` (`runtime.py`, `session.py`) is a separate boundary
  direction worth tracking across phases.

## Interpretation

- The **frontend** god-node `usePlanningStore` (84) is the largest single hub — the Zustand store
  is a classic god-node candidate.
- **spatial-ops** has the highest edge density and the largest god-node (`road_planning_nodes`, 93)
  and the lowest mean cohesion (0.203).
- All four domains show a large share of low-cohesion communities (roughly half or more),
  indicating diffuse module boundaries pre-refactoring.
- Cycle counts are high everywhere (undirected cycle basis); these are structural import cycles to
  be compared against after Phase 4.