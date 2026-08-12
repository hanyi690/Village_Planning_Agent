# B — materialization worker module (blueprint M6)

## Files created

All under `backend/app/domain/materialization/` (new package):

- `__init__.py` — exports `WorkerInput`, `WorkerResult`, `run_workers`.
- `worker_contract.py` — canonical `WorkerInput`/`WorkerResult` models, `blocked_result`, `adapt_legacy_result`, `to_task_result`, `_load_runner`, and `run_workers` aggregator.
- `project_worker.py`, `zone_worker.py`, `facility_worker.py`, `road_worker.py`, `axis_worker.py` — per-worker `async def run_worker(task: WorkerInput, *, deps=None) -> WorkerResult` wrappers.

## WorkerInput / WorkerResult fields

- `WorkerInput`: `worker: str`, `target_ref: str`, `task_ref: str = ""`, `input_refs: dict[str, str]`. Structurally satisfies `app.contracts.ports.workers.WorkerInput` protocol.
- `WorkerResult`: `worker: str`, `target_ref: str`, `task_ref: str = ""`, `status: Literal["succeeded","failed","unresolved","deferred"]`, `change_refs: list[str]`, `diagnostics: dict[str, Any]`, `provenance: dict[str, str]`. Satisfies the `WorkerResult` protocol.

## How each worker delegates

Each wrapper lazily imports the existing node (`app/agent/execute/nodes/...`) **inside the function** and calls the plan-level worker with the state taken from `deps["state"]`. If `deps` carries no `state`, the wrapper returns a typed `WorkerResult(status="unresolved")` with `diagnostics.code="input_requirements_unmet"` and `provenance.blocked="missing_dependency"` — no input fabrication. No algorithm code is duplicated.

- project → `_project_worker` (nodes/project_worker.py)
- zone → `_zone_worker` (nodes/zone_worker.py)
- facility → `_facility_worker` (nodes/facility_worker.py)
- road → `_road_worker` (nodes/road_worker.py)
- axis → `_axis_worker` (nodes/axis_worker.py)

Legacy `WorkerResult` is folded via `adapt_legacy_result`: `status` derived from unresolved_items/task statuses/output presence; `change_refs` = parcel change bsm ids + layer types; per-task evidence kept under `diagnostics`.

## run_workers aggregation shape

`async def run_workers(inputs: list[WorkerInput], deps: dict) -> ExecutionResult`:

1. Loads the per-worker runner lazily by `worker` name; unknown names produce a blocked `WorkerResult`.
2. Fans out all workers with `asyncio.gather(..., return_exceptions=True)` (independent, concurrent).
3. Exceptions / non-`WorkerResult` returns become blocked results.
4. Builds the canonical `ExecutionResult` (single owner: `execution_plan_contracts.ExecutionResult`): each `WorkerResult` maps via `to_task_result` into `task_results` (status map: succeeded→succeeded, failed→failed, unresolved/deferred→deferred), plus a `diagnostics` summary per worker.
5. Child refs `parcel_changeset_ref` / `planned_state_ref` / `layout_configs_ref` are read from `deps` (required `ArtifactRef`); missing refs raise a clear `ValueError` — never fabricated. Optional `execution_plan_ref` / `deferral_ledger_ref` pass through.

## Verification

Import command (from `backend`):

```
OK
```

WorkerInput smoke:

```
{'worker': 'project', 'target_ref': 't1', 'task_ref': 'tk1', 'input_refs': {}}
```

Aggregator smoke (no `state`, valid refs): `ExecutionResult 3.0` with 2 task_results mapped to `deferred` (unresolved workers). Delegation smoke (fake state): `_project_worker` ran, produced `WorkerResult status=deferred`.
