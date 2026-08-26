# Task 2 brief — executable PlanningTaskGraph in GROUND

Implementer: start from the current dirty worktree; do not reset or revert
unrelated user edits. This is a bounded implementation task. Do not restore
CurrentAsset, DemandRegisterRow, CoverageDecision, or any retired compatibility
register path.

## Objective

Turn the already compiled `PlanningTaskGraph` into an executable prerequisite
DAG. GROUND must schedule tasks, bind typed artifacts, and leave explicit
`blocked`/`deferred` states when source evidence or spatial inputs are absent.
It must not silently convert every task into a generic evidence requirement or
claim that a task is complete merely because it was compiled.

## Required behavior

1. Extend the task lifecycle contract with deterministic states sufficient for
   execution (`planned`, `ready`, `running`, `resolved`, `blocked`,
   `deferred`, `failed` as appropriate; preserve existing semantics where
   possible). Each transition records reason, input artifact refs, output refs,
   and lineage.
2. Compile all relation templates used by the intent graph, not only the
   current topology subset. At minimum cover `serve`, `provide_access`,
   `connect_network`, `follow_alignment`, `preserve_existing`,
   `upgrade_existing`, `near`, and `precedes`, in addition to existing
   `contains`, `located_in`, `adjacent_to`, `intersects`, and `overlaps`.
   Relation tasks must carry typed endpoint/entity, demand, network,
   geometry/constraint, candidate, solver, and validation prerequisites as
   needed; no final geometry or solver candidate may be fabricated by L3.
3. Add a GROUND-side scheduler/executor that topologically processes the DAG,
   resolves tasks against the session KG/spatial bridge/evidence artifacts, and
   binds outputs into the task graph and CAS artifact refs. If prerequisites
   are missing, preserve the task with a typed blocked/deferred reason and an
   evidence request; do not mark it resolved or drop it.
4. Keep deterministic ownership: IDs, geometry/CRS, topology, lineage and
   lifecycle transitions are code-owned; LLMs may provide semantic proposals
   only. Avoid regex/special-case mapping as the implementation mechanism.
5. Keep the frontend-visible artifact/state projection coherent. A task graph
   loaded at SELECT must show lifecycle states and bound artifacts rather than
   every task remaining `planned`.

## Verification

- Add focused unit/contract tests for lifecycle transitions, every relation
  template, topological scheduling, missing-prerequisite blocking, and CAS
  bindings. Use deterministic fakes for unit tests only.
- Run the focused suite with repository addopts disabled as needed.
- Do not claim the task complete without a fresh real session checkpoint that
  reaches SELECT and shows task states beyond `planned`; record the session id,
  run root, artifact digests, task-state counts, and any provider/runtime
  limitation in the task report.

## Review boundary

Before handoff, inspect the diff for accidental compatibility restoration,
prompt-only claims without runtime bindings, or a solver invocation hidden in
GROUND. Report any unresolved Important/Critical issue instead of masking it.
