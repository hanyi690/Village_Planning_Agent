# Task 4 Independent Review — Mixed Solver Decomposition and SELECT Integration

**Reviewer:** independent review agent  
**Scope:** SolverSubproblem / SolverSubproblemPlan contracts, compiler and
portfolio merge, partial topology semantics, and SELECT dispatch/persistence.  
**Initial result:** CHANGES REQUIRED  
**Repair re-review result:** **PASS**

## Resolved on final repair — candidate-scoped shared-resource ownership

The initial repair started every target slice with every global
`problem.shared_resource_refs` value.  It therefore marked each such ref as
owned by all target subproblems, independent of candidate lineage, parcel
membership, or a relation connecting the target to the resource.

The loss of ownership has already happened upstream:
`intent_graph_compiler._shared_resource_refs()` flattens the resource refs from
all interventions into `PlanningIntentGraph.shared_resource_refs` without a
target mapping.  A global ref must consequently be treated as a parent input to
be resolved, not as evidence that every target consumes it.

**Fresh counterexample:** I used two ready, unrelated targets from the mixed
fixture (facility + zone), removed the road/topology relation, retained the
zone's real parcel pool, and set only
`shared_resource_refs=['unrelated:shared-reference']`.  Neither candidate has
that identifier.  The optimizer nevertheless returned:

```text
status=unknown
UNSUPPORTED_SOLVER_KIND: CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED,
resource:unrelated:shared-reference:targets:facility-1,zone-1
recommended=<none>
```

That initial implementation made a normally executable, complete multi-target
plan permanently provisional whenever L3/GROUND supplied one legitimate
shared-resource lookup.  The final repair now derives ownership only from each
subproblem candidate IDs: candidate source BSMs plus the matching pool
resource's ID and geometry ref.  Global refs are used only when they match one
of those candidate-scoped typed identities.

### Final verification — facility/non-parcel and parcel/parcel cases

The follow-up repair correctly makes the facility + zone counterexample above
formal (`status=feasible`, one recommendation).  It restricts global refs to
`parcel_assignment` slices and ignores ordinary point/line candidate source
identities.

The intermediate repair still assigned the **entire** global resource pool and
every global `shared_resource_refs` value to every `parcel_assignment` target.
I directly constructed two independent site-area targets with different source
BSMs (`bsm:a` and `bsm:b`), one polygon candidate per target, and no overlap or
topology relation.  It initially returned `unknown` and reported every resource
as owned by both targets:

```text
CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED
resource:bsm:a:targets:zone-a,zone-b
resource:bsm:b:targets:zone-a,zone-b
resource:parcel-resource:bsm:a:targets:zone-a,zone-b
resource:parcel-resource:bsm:b:targets:zone-a,zone-b
... (pool and each candidate source ref likewise)
```

The final repair resolves this: the same direct disjoint-BSM case now returns
`status=feasible`, one formal recommendation and one feasible scenario.  The
new `test_disjoint_parcel_resources_remain_formally_composable` regression
covers it.  A direct same-BSM two-target case remains `unknown` with
`CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED`, so the fail-closed boundary is
preserved without inheriting unrelated pool entries.

## Resolved on repair — product materialization bound

The initial review found that `optimize_solver_subproblems()` accepted and
recorded `max_scenarios`, while `_merge_scenario_sets()` materialized until
`search_limit`.  With SELECT's normal `max_scenarios=8` and
`search_limit=20_000`, a mixed plan could have materialized 20,000 rows.

The repair correctly uses `min(search_limit, max_scenarios)`, marks the
certificate `bounded` when the complete Cartesian product is larger, and has a
regression for the cap.  This initial issue is resolved.

## Resolved on repair — genuine cross-subproblem shared-resource collision

Child slices remove cross-target factors (`subproblem_optimizer.py:97-110`),
and `_merge_scenario_sets()` only unions their target selections/features
(`197-259`). The parent merge does not re-evaluate candidate geometry overlap,
shared parcel/resource ownership, capacity, budget, or hard cross-subproblem
relations before marking a merged scenario `complete`/feasible.

Topology factors happen to be retained as provisional blocked work, which is
safe. But a facility and a zone/site-area in separate solver kinds can select
the same parcel/shared resource without a topology factor and still receive a
formal recommended ScenarioSet. This is exactly the mixed-planning conflict the
global coordinator must either resolve or fail closed.

The repair adds a deterministic candidate-scoped conflict guard and returns an
unknown ScenarioSet with
`CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED` for the genuine collision
fixture.  Disjoint candidate BSMs remain independently composable, so the
original false-formal-recommendation path is resolved without making the whole
resource pool look owned by every target.

**Initial reproduction:** starting from the mixed
facility + site-area fixture, I removed the road, gave the facility candidate
the same `source_bsms=['bsm:zone-1']` as the parcel-assignment candidate, and
declared `shared_resource_refs=['pool:zone']` without adding a topology factor.
`optimize_solver_subproblems()` returned `status=feasible`, a non-null
recommendation, and both `facility-candidate` and `zone-candidate` selections.
The scenario is therefore formal despite the declared shared resource.

## Resolved on repair — blocked reason remains canonically available

The initial focused test below failed:

```text
tests/core/test_solver_subproblem_decomposition.py::
  test_missing_network_input_blocks_composition_fail_closed
```

The composed result correctly has `solver_certificate.status == "unknown"`.
The certificate termination summary remains generic for the partial merge, but
the repair preserves `SOLVER_SUBPROBLEM_BLOCKED` in the canonical
`infeasibility_explanations` projection.  That meets the typed audit boundary
and the current focused suite passes.

## What is correct

- The product merge now materializes at most
  `min(search_limit, max_scenarios)` scenarios and marks the certificate
  `bounded` with `SUBPROBLEM_PRODUCT_BOUND` when the complete Cartesian product
  is larger.  The new regression covers the `max_scenarios=1` case.
- The genuine same-source-BSM conflict fixture now fails closed with
  `CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED`; disjoint source BSMs remain
  formally composable.
- `SolverSubproblem` and `SolverSubproblemPlan` canonicalize fields, validate
  dependencies/cycles, and reject stale fingerprints.
- The compiler is typed and deterministic: it derives route kinds from grounded
  target/factor semantics, candidate domains, relation evaluators, network refs,
  and parcel resource pool. It does not parse planning prose.
- Target solver kinds remain distinct when a topology relation exists; topology
  is represented as its own dependent subproblem rather than coercing the whole
  village into one global kind.
- The topology path intentionally creates `partial` scenarios with no feasible
  or recommended IDs and an `unknown` certificate, which the ScenarioSet
  contract correctly prevents from becoming formal/selectable.
- SELECT dispatches to subproblem merge only when there are multiple target
  subproblems of different kinds, persists `SolverSubproblemPlan` before solve,
  and still uses the existing single-scenario approval/execution gate.

## Fresh verification

```text
pytest tests/core/test_solver_subproblem_decomposition.py \
       tests/core/test_solver_portfolio_slice1.py \
       tests/core/test_scenario_optimizer.py \
       tests/core/test_scenario_hard_relation_feasibility.py \
       tests/core/test_select_gate_deferred_targets.py \
       tests/contracts/test_scenario_set_contracts.py \
       tests/contracts/test_single_scenario_authority.py -q -o addopts=''
# 106 passed

python -m compileall -q app/contracts/planning/solver.py \
  app/contracts/planning/scenario.py \
  app/domain/allocation/subproblem_compiler.py \
  app/domain/allocation/subproblem_optimizer.py app/workflow/stages/select.py
# passed

git diff --check
# passed
```

I also directly verified the new route boundary:

```text
exact road candidate, no network ref/factor -> single_choice, ready
explicit network_path factor, no network ref -> network_path, blocked,
  required_input_refs includes missing:network_ref
```

The blocked-subproblem reason remains available in the canonical
`infeasibility_explanations` projection even where the certificate termination
summary is generic.  That is sufficient for the typed audit boundary.

Final direct resource checks:

```text
two disjoint parcel targets, BSM a / BSM b -> feasible, recommendation present
two parcel targets sharing BSM one -> unknown, no recommendation,
  CROSS_SUBPROBLEM_RESOURCE_CONFLICT_UNRESOLVED
```

No production files were edited by the reviewer.
