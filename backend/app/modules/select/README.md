# SELECT

`backend/app/modules/select/` owns closed-set scenario selection. It consumes
`target_projection` and `grounding_result`, validates the candidate domain,
invokes deterministic solver backends, ranks formal scenarios, and creates
the approval input consumed by EXECUTE.

## Public boundary

- `application.SelectApplication.run(state) -> SelectRunResult`
- `application.run_select(state) -> SelectRunResult`
- `ports` defines solver and approval ports.
- `projections` contains bounded solver/approval projections.

The facade requires canonical artifact references for both upstream inputs.
The output references are produced by the real SELECT stage and may include
`scenario_set`, `planning_scenario`, `approved_execution_input`,
`execution_plan`, and `select_gate`. A partial or infeasible scenario set is
typed and routed explicitly; it is not treated as approval.

## Invariants

Every scenario selection must reference a candidate from GROUND and retain the
problem fingerprint and solver certificate. LLMs may summarize or explain a
scenario, but cannot create candidates, geometry, quantities, or constraints.
Evidence completion uses the centralized Evidence facade. Demand and
suitability are L2-owned inputs; SELECT only applies them while solving the
grounded problem.

The SELECT-owned spatial helpers are kept in this package as well:
`selection.py` contains parcel filters/ranking, `facility_location.py` contains
coverage solving, `global_site_allocator.py` and
`global_zone_parcel_allocator.py` contain global allocation, and
`zone_allocator_adapter.py` is the typed port adapter. `spatial/` no longer
contains a second allocation implementation.

If no executable grounded problem exists, SELECT routes to the structured
`diagnostic_only` terminal while retaining target-scoped recovery information.
A missing approval for an otherwise executable scenario remains a HUMAN
approval boundary; unresolved grounding is never treated as approval.

## Recovery and verification

Scenario and approval artifacts are persisted by the shared CAS runtime and
reloaded before being returned to the workflow. The normal lightweight gate
is compile/import plus the boundary probe. A real end-to-end probe must start
from a newly produced GROUND artifact and must never use a historical session
as a substitute for the current run.
