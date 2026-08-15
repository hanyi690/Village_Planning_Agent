# Round-2 Audit: G — Worker Cleanup (materialization wrappers)

Date: 2026-08-12
Scope: `backend/app/domain/materialization/` only. No edits to
`app/agent/execute/nodes/*_worker.py`; no server / LLM invocation.

## Files changed

- `worker_contract.py` — rewritten (contract, taxonomy, gate, aggregator).
- `project_worker.py`, `zone_worker.py`, `facility_worker.py`, `road_worker.py`,
  `axis_worker.py` — rewritten as explicit-input wrappers.

## Diagnostic `code` taxonomy (new field on `WorkerResult`, distinct from `status`)

| code | meaning |
|------|---------|
| `input_requirements_unmet` | task spec lacks a real ExecutionPlan `task_ref` (or artifact ref); inputs never fabricated |
| `worker_needs_explicit_input` | legacy node still re-sites / reclassifies / reads KG directly; explicit inputs required before delegation |
| `delegated_ok` | delegated to the execution worker via explicit opt-in and produced typed output |
| `algorithm_unavailable` | required algorithm / port unavailable (reserved) |
| `unknown_worker` | no worker registered for `task.worker` |
| `worker_raised` | worker raised while executing |
| `unexpected_payload` | worker returned a non-`WorkerResult` payload |

`WorkerStatus` extended with `"blocked"` (maps to plan `deferred` in
`STATUS_TO_TASK_STATUS`).

## Per-worker behavior

All five `run_worker(task, *, deps=None)`:
1. `task.task_ref` empty -> `blocked` + `input_requirements_unmet` (never fabricate).
2. `task_ref` set but no explicit `input_refs['legacy_opt_in']='true'` ->
   `blocked` + `worker_needs_explicit_input`, naming the offending legacy
   operations (re-siting / reclassification / KG or workspace reads).
3. Opt-in only then lazy-imports the legacy node (`import` inside function,
   side-effect-free module import) and folds output via `adapt_legacy_result`
   (`delegated_ok`). No algorithm code duplicated; nothing silently falls back.

- project: re-siting (selected_bsm join / full_ranking fallback)
- zone: reclassification (design_zone_parcel), MIP re-allocation, KG three-lines read
- facility: re-siting (anchor lookup + design_facility_parcel)
- road: network re-siting via RoadPlannerPort / stage generator
- axis: direct spatial-workspace (KG) read + axis geometry building

## Aggregator hardening

`run_workers` calls `_require_refs(deps)` up front and raises `ValueError` when
`parcel_changeset_ref`, `planned_state_ref` or `layout_configs_ref` is missing
(fails loudly instead of an empty `ExecutionResult`). `to_task_result` and the
root `diagnostics` now carry the worker `code`.

## Verification

Import:
```
OK
```
Smoke (task without `task_ref` -> status in {unresolved, blocked}):
```
project blocked input_requirements_unmet
zone blocked input_requirements_unmet
facility blocked input_requirements_unmet
road blocked input_requirements_unmet
axis blocked input_requirements_unmet
```
Opt-in gate (`task_ref` present, no opt-in -> `worker_needs_explicit_input`):
```
project blocked worker_needs_explicit_input
zone blocked worker_needs_explicit_input
facility blocked worker_needs_explicit_input
road blocked worker_needs_explicit_input
axis blocked worker_needs_explicit_input
```
Parent-ref loud failure:
```
run_workers raised: ExecutionResult requires parent artifact refs parcel_changeset_ref, planned_state_ref, layout_configs_ref; ... (missing: all three)
```
Files verified LF (CRLF=0). Constraints: LF, 4-space indent, double quotes, no tests.
