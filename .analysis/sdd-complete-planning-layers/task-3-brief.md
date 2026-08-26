# Task 3 Brief — Compile a typed PlanningTaskGraph at TARGET_PROJECTION

## Why

The current IntentGraph has targets, relations, and one global solver kind, but
it does not expose the evidence prerequisites, candidate producers, solver
subproblems, or validation obligations that GROUND/SELECT need.  Add the
smallest typed, deterministic task graph boundary so spatial intent is expanded
without re-parsing prose and without selecting geometry or fabricating evidence.

## Scope

1. Add `backend/app/contracts/planning/task_graph.py` with typed contracts for:
   - task kind: `evidence`, `candidate_producer`, `solver_subproblem`,
     `validation`;
   - stable task id, target/relation refs, capability, required inputs,
     produced artifact refs, dependency task ids, optional solver kind, and
     status/diagnostic fields;
   - a graph contract with deterministic canonicalization, dependency existence
     checks, and cycle rejection.
2. Add a pure compiler under
   `backend/app/domain/program/target_projection/` that expands a typed
   `PlanningIntentGraph` into task nodes.  Use only typed target kinds,
   operations, endpoint refs, relation templates, and existing capability
   enums.  Do not inspect or parse natural-language fields.
3. Attach the graph to `IntentCompilationResult` and create it in
   `compile_program_deterministic`.
4. Add focused contract/compiler tests for facility, road, zone/site-area,
   topology relation, non-spatial action, deterministic ordering, missing
   prerequisites, and cycle rejection.

## Required semantics

- New facility targets expose a demand evidence prerequisite, eligible-candidate
  producer, and facility solver task; preserve/upgrade existing targets expose
  source identity evidence instead of demand by default.
- Road/linear/axis targets expose endpoint binding and network snapshot
  evidence tasks, then a network candidate producer and network solver task.
- Zone/site-area targets expose parcel/resource-pool evidence, candidate
  producer, and a parcel/site solver task.
- Topology relations (`part_of`, `co_locate`, `mutually_exclusive`, and
  `within_allowed_area`/`avoid_constraint` when applicable) expose a validation
  task depending on the relevant target tasks.
- Tasks may remain planned when inputs are missing; the graph must make the
  missing input explicit.  It must not silently drop a target or invent an
  identity/geometry.
- The compiler remains deterministic and side-effect free.  GROUND remains the
  authority for KG/Bundle queries and geometry; SELECT remains the authority
  for solving.

## Verification

Run the focused task-graph tests plus existing target projection,
artifact-requirement, and executable-admission tests.  Run compileall and
`git diff --check`.

